from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from crazyswarm_app.dashboard import (
    HEALTH_FAILURE_LIMIT,
    UI_RELEASES_DIRECTORY,
    ManagedProcess,
    build_ui,
    find_npm,
    production_ui_directory,
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


def test_managed_process_requires_consecutive_health_failures() -> None:
    service = managed(FakeProcess())

    def unhealthy(_url: str, **_kwargs: Any) -> bool:
        return False

    for _ in range(HEALTH_FAILURE_LIMIT - 1):
        assert service.needs_restart(now_s=100.0, health_probe=unhealthy) is None
    assert "consecutive health checks" in str(
        service.needs_restart(now_s=100.0, health_probe=unhealthy)
    )


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
    assert (ui_directory / UI_RELEASES_DIRECTORY / "current").is_symlink()


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
