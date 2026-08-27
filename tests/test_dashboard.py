from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from crazyswarm_app import dashboard_service
from crazyswarm_app.dashboard import (
    HEALTH_FAILURE_LIMIT,
    STARTUP_GRACE_S,
    UI_RELEASES_DIRECTORY,
    ManagedProcess,
    build_ui,
    default_dashboard_ports,
    find_npm,
    is_git_worktree,
    production_ui_directory,
    release_matches_ui_source,
)


def test_worktree_gets_deterministic_isolated_default_ports(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /tmp/common/worktrees/task")

    first = default_dashboard_ports(tmp_path)

    assert is_git_worktree(tmp_path) is True
    assert first == default_dashboard_ports(tmp_path)
    assert 18_000 <= first[0] < 20_000
    assert 22_000 <= first[1] < 24_000


def test_worktree_cannot_manage_operator_dashboard_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dashboard_service, "is_git_worktree", lambda _root: True)

    with pytest.raises(RuntimeError, match="Local checkout"):
        dashboard_service.restart_service()


def test_service_readiness_can_allow_explicitly_undeployed_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plist_path = tmp_path / "service.plist"
    with plist_path.open("wb") as output:
        plistlib.dump(
            {
                "WorkingDirectory": str(tmp_path),
                "ProgramArguments": [
                    "python",
                    "-m",
                    "crazyswarm_app",
                    "dashboard",
                    "--ui-release",
                    "release-test",
                    "--hardware-owner",
                    "operator-dashboard-service",
                ],
            },
            output,
        )
    monkeypatch.setattr(dashboard_service, "_require_local_checkout", lambda: tmp_path)
    monkeypatch.setattr(
        dashboard_service,
        "service_paths",
        lambda _root: (plist_path, tmp_path / "stdout.log", tmp_path / "stderr.log"),
    )
    monkeypatch.setattr(
        dashboard_service.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0),
    )
    monkeypatch.setattr(dashboard_service, "_url_healthy", lambda _url: True)
    monkeypatch.setattr(
        dashboard_service,
        "production_ui_directory",
        lambda _ui, _release: tmp_path / "release-test",
    )
    monkeypatch.setattr(
        dashboard_service,
        "release_matches_ui_source",
        lambda _ui, _release: False,
    )

    assert dashboard_service.service_status(ui_port=3001) == 1
    assert dashboard_service.service_status(ui_port=3001, allow_stale_source=True) == 0


def test_deployment_rechecks_idle_physical_state_after_admission_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "motor-actuation": {"state": "IDLE", "stop_required": False},
        "physical-flight": {"state": "IDLE", "stop_required": False},
    }
    monkeypatch.setattr(
        dashboard_service,
        "_read_json_url",
        lambda url: responses[url.rsplit("/", 1)[-1]],
    )

    dashboard_service._require_safe_deployment_state(
        ui_port=3001,
        physical_power_removed=False,
    )


def test_deployment_refuses_unconfirmed_flight_without_power_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "motor-actuation": {"state": "IDLE", "stop_required": False},
        "physical-flight": {"state": "STOP_UNCONFIRMED", "stop_required": True},
    }
    monkeypatch.setattr(
        dashboard_service,
        "_read_json_url",
        lambda url: responses[url.rsplit("/", 1)[-1]],
    )

    with pytest.raises(RuntimeError, match="physical flight stop"):
        dashboard_service._require_safe_deployment_state(
            ui_port=3001,
            physical_power_removed=False,
        )

    dashboard_service._require_safe_deployment_state(
        ui_port=3001,
        physical_power_removed=True,
    )


class FakeProcess:
    def __init__(self, return_code: int | None = None) -> None:
        self.return_code = return_code
        self.stopped = False

    def poll(self) -> int | None:
        return self.return_code

    def send_signal(self, _signal: int) -> None:
        self.stopped = True

    def wait(self, timeout: int) -> int:
        del timeout
        self.return_code = 0
        return 0

    def kill(self) -> None:
        self.stopped = True


def managed(process: FakeProcess) -> ManagedProcess:
    service = ManagedProcess(
        name="test",
        command=["test"],
        cwd=Path("."),
        health_url="http://127.0.0.1:1/health",
    )
    service.process = process  # type: ignore[assignment]
    service.started_at_s = 0.0
    return service


def test_find_npm_uses_highest_installed_nvm_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("crazyswarm_app.dashboard.shutil.which", lambda _name: None)
    older = tmp_path / ".nvm" / "versions" / "node" / "v20.19.0" / "bin" / "npm"
    newer = tmp_path / ".nvm" / "versions" / "node" / "v22.19.0" / "bin" / "npm"
    older.parent.mkdir(parents=True)
    newer.parent.mkdir(parents=True)
    older.write_text("older")
    newer.write_text("newer")

    assert find_npm(tmp_path) == str(newer)


def test_managed_process_restarts_immediately_after_exit() -> None:
    service = managed(FakeProcess(return_code=7))
    assert service.needs_restart(now_s=100.0) == "exited with status 7"


def test_managed_process_starts_in_its_own_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def start_process(*args: object, **kwargs: object) -> FakeProcess:
        captured["args"] = args
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr("crazyswarm_app.dashboard.subprocess.Popen", start_process)
    service = ManagedProcess(
        name="test",
        command=["test"],
        cwd=Path("."),
        health_url="http://127.0.0.1:1/health",
    )

    service.start({"PATH": "/usr/bin"})

    assert captured["start_new_session"] is True


def test_managed_process_requires_consecutive_health_failures() -> None:
    service = managed(FakeProcess())

    def unhealthy(_url: str, **_kwargs: Any) -> bool:
        return False

    for _ in range(HEALTH_FAILURE_LIMIT - 1):
        assert service.needs_restart(now_s=100.0, health_probe=unhealthy) is None
    assert "consecutive health checks" in str(
        service.needs_restart(now_s=100.0, health_probe=unhealthy)
    )


def test_managed_process_does_not_probe_during_cold_start_grace() -> None:
    service = managed(FakeProcess())
    probed = False

    def unhealthy(_url: str, **_kwargs: Any) -> bool:
        nonlocal probed
        probed = True
        return False

    assert (
        service.needs_restart(
            now_s=STARTUP_GRACE_S - 0.01,
            health_probe=unhealthy,
        )
        is None
    )
    assert probed is False


def test_successful_health_probe_resets_failure_counter() -> None:
    service = managed(FakeProcess())
    service.failed_health_checks = HEALTH_FAILURE_LIMIT - 1

    def healthy(_url: str, **_kwargs: Any) -> bool:
        return True

    assert service.needs_restart(now_s=100.0, health_probe=healthy) is None
    assert service.failed_health_checks == 0


def test_ui_build_publishes_without_mutating_live_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui_directory = tmp_path / "ui"
    ui_directory.mkdir()
    (ui_directory / "package.json").write_text('{"scripts":{"build":"build"}}')
    (ui_directory / "app").mkdir()
    (ui_directory / "app" / "page.tsx").write_text("export default function Page() {}")
    (ui_directory / "node_modules").mkdir()
    (ui_directory / "dist").mkdir()
    (ui_directory / "dist" / "live-asset.js").write_text("still-serving")
    build_number = 0

    def fake_build(*_args: object, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal build_number
        build_number += 1
        staging = Path(kwargs["cwd"])
        (staging / "dist" / "client").mkdir(parents=True)
        (staging / "dist" / "client" / f"asset-{build_number}.js").write_text("built")
        (staging / "dist" / "server").mkdir()
        (staging / "dist" / "server" / "index.js").write_text("export default {}")
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", fake_build)

    first = build_ui("npm", ui_directory, {})
    second = build_ui("npm", ui_directory, {})

    assert (ui_directory / "dist" / "live-asset.js").read_text() == "still-serving"
    assert first.is_dir()
    assert second.is_dir()
    assert first != second
    assert (first / "dist" / "client" / "asset-1.js").is_file()
    assert (second / "dist" / "client" / "asset-2.js").is_file()
    assert production_ui_directory(ui_directory) == second
    assert production_ui_directory(ui_directory, first.name) == first
    assert release_matches_ui_source(ui_directory, second) is True
    assert (ui_directory / UI_RELEASES_DIRECTORY / "current").is_symlink()

    (ui_directory / "app" / "page.tsx").write_text("export default function Changed() {}")
    assert release_matches_ui_source(ui_directory, second) is False


def test_failed_ui_build_keeps_previous_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui_directory = tmp_path / "ui"
    ui_directory.mkdir()
    (ui_directory / "package.json").write_text('{"scripts":{"build":"build"}}')
    (ui_directory / "node_modules").mkdir()

    def successful_build(*_args: object, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        staging = Path(kwargs["cwd"])
        (staging / "dist" / "client").mkdir(parents=True)
        (staging / "dist" / "server").mkdir()
        (staging / "dist" / "server" / "index.js").write_text("export default {}")
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", successful_build)
    published = build_ui("npm", ui_directory, {})

    def failed_build(*_args: object, **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(1, ["npm", "run", "build"])

    monkeypatch.setattr(subprocess, "run", failed_build)
    with pytest.raises(subprocess.CalledProcessError):
        build_ui("npm", ui_directory, {})

    assert production_ui_directory(ui_directory) == published
