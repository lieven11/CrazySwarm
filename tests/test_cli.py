from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from crazyswarm_app import cli
from crazyswarm_app.cli import main


def test_health_command(capsys: object) -> None:
    assert main(["health", "--config", str(Path("config/app.yaml"))]) == 0
    # pytest's fixture is intentionally duck-typed here.
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    report = json.loads(output)
    assert report["status"] == "ok"
    assert report["default_mode"] == "SIM"


def test_mission_list_and_validate_commands(capsys: object) -> None:
    assert main(["missions", "list"]) == 0
    missions = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert [mission["mission_id"] for mission in missions] == [
        "hover",
        "move-return",
        "square",
    ]

    assert main(["missions", "validate", "hover", "--set", "height_m=0.25"]) == 0
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["valid"] is True
    assert report["parameters"]["height_m"] == 0.25


def test_dashboard_is_one_url_and_keeps_internal_credentials_hidden(
    monkeypatch: pytest.MonkeyPatch,
    capsys: object,
) -> None:
    processes: list[FakeProcess] = []

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        process = FakeProcess(command, kwargs)
        processes.append(process)
        return process

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/npm")
    monkeypatch.setattr(cli, "generate_local_token", lambda: "server-only-token")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(time, "sleep", interrupt)

    assert main(["dashboard"]) == 0
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report == {
        "status": "starting",
        "url": "http://localhost:3001",
        "mode": "SIM",
    }
    assert len(processes) == 2
    assert processes[0].environment["CRAZYSWARM_LOCAL_TOKEN"] == "server-only-token"
    assert processes[1].environment["CRAZYSWARM_API_URL"] == "http://127.0.0.1:8001"
    assert all(process.stopped for process in processes)


def test_dashboard_rejects_invalid_port() -> None:
    with pytest.raises(SystemExit):
        main(["dashboard", "--ui-port", "0"])


class FakeProcess:
    def __init__(self, command: list[str], kwargs: dict[str, Any]) -> None:
        self.command = command
        self.environment = kwargs["env"]
        self.returncode: int | None = None
        self.stopped = False

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, _signal: int) -> None:
        self.stopped = True

    def wait(self, timeout: int) -> int:
        del timeout
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.stopped = True
