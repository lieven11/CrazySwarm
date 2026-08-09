from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from crazyswarm_app.api.app import generate_local_token
from crazyswarm_app.config import load_config

HEALTH_INTERVAL_S = 2.0
HEALTH_FAILURE_LIMIT = 3
STARTUP_GRACE_S = 20.0
UI_RELEASES_DIRECTORY = ".crazyswarm-builds"
UI_BUILD_EXCLUDES = frozenset(
    {
        ".next",
        ".vinext",
        ".wrangler",
        UI_RELEASES_DIRECTORY,
        "coverage",
        "dist",
        "node_modules",
        "out",
    }
)


def find_npm(home_directory: Path | None = None) -> str | None:
    available = shutil.which("npm")
    if available is not None:
        return available

    home = Path.home() if home_directory is None else home_directory
    nvm_root = home / ".nvm" / "versions" / "node"
    candidates = [candidate for candidate in nvm_root.glob("v*/bin/npm") if candidate.is_file()]
    if not candidates:
        return None

    def version(candidate: Path) -> tuple[int, ...]:
        raw = candidate.parent.parent.name.removeprefix("v")
        try:
            return tuple(int(part) for part in raw.split("."))
        except ValueError:
            return ()

    return str(max(candidates, key=version))


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _valid_ui_distribution(directory: Path) -> bool:
    distribution = directory / "dist"
    server = distribution / "server"
    return (distribution / "client").is_dir() and (
        (server / "index.js").is_file() or (server / "entry.js").is_file()
    )


def production_ui_directory(ui_directory: Path) -> Path:
    current = ui_directory / UI_RELEASES_DIRECTORY / "current"
    if current.is_symlink() or current.exists():
        release = current.resolve(strict=True)
        if _valid_ui_distribution(release):
            return release
        raise RuntimeError(f"published UI release is incomplete: {release}")
    if _valid_ui_distribution(ui_directory):
        # Backward-compatible first start before the service has published its
        # first immutable release.
        return ui_directory
    raise RuntimeError("UI production build not found; reinstall the dashboard service")


def _copy_ui_build_source(ui_directory: Path, staging_directory: Path) -> None:
    for source in ui_directory.iterdir():
        if source.name in UI_BUILD_EXCLUDES:
            continue
        destination = staging_directory / source.name
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination, follow_symlinks=False)
    (staging_directory / "node_modules").symlink_to(
        ui_directory / "node_modules",
        target_is_directory=True,
    )


def build_ui(npm: str, ui_directory: Path, environment: dict[str, str]) -> Path:
    """Build away from the live server and atomically publish a release pointer."""
    releases = ui_directory / UI_RELEASES_DIRECTORY
    releases.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".build-", dir=releases))
    try:
        _copy_ui_build_source(ui_directory, staging)
        subprocess.run(
            [npm, "run", "build"],
            cwd=staging,
            env=environment,
            check=True,
        )
        if not _valid_ui_distribution(staging):
            raise RuntimeError("UI build completed without a runnable distribution")

        release_name = f"release-{uuid.uuid4().hex}"
        release_staging = releases / f".{release_name}"
        release_staging.mkdir()
        (staging / "dist").replace(release_staging / "dist")
        shutil.copy2(ui_directory / "package.json", release_staging / "package.json")
        (release_staging / "node_modules").symlink_to(
            ui_directory / "node_modules",
            target_is_directory=True,
        )
        release = releases / release_name
        release_staging.replace(release)

        next_pointer = releases / f".current-{uuid.uuid4().hex}"
        next_pointer.symlink_to(release.name, target_is_directory=True)
        next_pointer.replace(releases / "current")
        return release
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def prune_inactive_ui_releases(ui_directory: Path, active_directory: Path) -> None:
    releases = ui_directory / UI_RELEASES_DIRECTORY
    if active_directory.parent != releases:
        return
    for candidate in releases.glob("release-*"):
        if candidate != active_directory and candidate.is_dir():
            shutil.rmtree(candidate)


def endpoint_healthy(url: str, *, token: str | None = None) -> bool:
    headers = {"X-Local-Token": token} if token is not None else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


@dataclass(slots=True)
class ManagedProcess:
    name: str
    command: list[str]
    cwd: Path
    health_url: str
    token: str | None = None
    process: subprocess.Popen[bytes] | None = None
    started_at_s: float = 0.0
    failed_health_checks: int = 0
    restart_count: int = 0

    def start(self, environment: dict[str, str]) -> None:
        self.process = subprocess.Popen(self.command, cwd=self.cwd, env=environment)
        self.started_at_s = time.monotonic()
        self.failed_health_checks = 0

    def stop(self) -> None:
        if self.process is not None:
            stop_process(self.process)
            self.process = None

    def needs_restart(
        self,
        *,
        now_s: float,
        health_probe: Callable[..., bool] = endpoint_healthy,
    ) -> str | None:
        if self.process is None:
            return "not started"
        return_code = self.process.poll()
        if return_code is not None:
            return f"exited with status {return_code}"
        if now_s - self.started_at_s < STARTUP_GRACE_S:
            return None
        if health_probe(self.health_url, token=self.token):
            self.failed_health_checks = 0
            return None
        self.failed_health_checks += 1
        if self.failed_health_checks >= HEALTH_FAILURE_LIMIT:
            return f"failed {self.failed_health_checks} consecutive health checks"
        return None

    def restart(self, environment: dict[str, str], reason: str) -> None:
        print(
            json.dumps(
                {
                    "status": "restarting",
                    "component": self.name,
                    "reason": reason,
                    "restart": self.restart_count + 1,
                }
            ),
            file=sys.stderr,
            flush=True,
        )
        self.stop()
        self.restart_count += 1
        time.sleep(min(5.0, 0.5 * self.restart_count))
        self.start(environment)


def run_dashboard(
    config_path: Path,
    scenario_path: Path,
    *,
    api_port: int,
    ui_port: int,
    development: bool = False,
    skip_build: bool = False,
) -> int:
    if not port_available("127.0.0.1", api_port):
        raise RuntimeError(f"API port {api_port} is already in use")
    if not port_available("127.0.0.1", ui_port):
        raise RuntimeError(f"UI port {ui_port} is already in use")
    npm = find_npm()
    if npm is None:
        raise RuntimeError("Node.js and npm are required to start the dashboard")
    project_root = Path(__file__).resolve().parents[2]
    ui_directory = project_root / "ui"
    if not (ui_directory / "package.json").exists():
        raise RuntimeError(f"UI package not found: {ui_directory}")

    config = load_config(config_path)
    token = os.environ.get("CRAZYSWARM_LOCAL_TOKEN") or generate_local_token()
    environment = os.environ.copy()
    npm_directory = str(Path(npm).parent)
    existing_path = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join(part for part in (npm_directory, existing_path) if part)
    environment.update(
        {
            "CRAZYSWARM_LOCAL_TOKEN": token,
            "CRAZYSWARM_HIDE_LOCAL_TOKEN": "1",
            "CRAZYSWARM_API_URL": f"http://127.0.0.1:{api_port}",
            "CRAZYSWARM_DEV_WATCH": "1" if development else "0",
        }
    )
    if not development and not skip_build:
        build_ui(npm, ui_directory, environment)
    ui_working_directory = ui_directory
    if not development:
        ui_working_directory = production_ui_directory(ui_directory)
        # Port availability above guarantees that no older dashboard process is
        # still reading an earlier release when it is removed here.
        prune_inactive_ui_releases(ui_directory, ui_working_directory)

    api_command = [
        sys.executable,
        "-m",
        "crazyswarm_app",
        "serve",
        "--config",
        str(config_path.resolve()),
        "--scenario",
        str(scenario_path.resolve()),
        "--port",
        str(api_port),
    ]
    if development:
        api_command.append("--reload")
    api = ManagedProcess(
        name="api",
        command=api_command,
        cwd=project_root,
        health_url=f"http://127.0.0.1:{api_port}/api/v1/health",
        token=token,
    )
    ui_script = "dev" if development else "start"
    ui = ManagedProcess(
        name="ui",
        command=[npm, "run", ui_script, "--", "--port", str(ui_port)],
        cwd=ui_working_directory,
        health_url=f"http://127.0.0.1:{ui_port}/control-api/api/v1/state",
    )
    services = (api, ui)
    stopping = False

    def request_stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous_term = signal.signal(signal.SIGTERM, request_stop)
    previous_int = signal.signal(signal.SIGINT, request_stop)
    for service in services:
        service.start(environment)
    print(
        json.dumps(
            {
                "status": "starting",
                "url": f"http://localhost:{ui_port}",
                "mode": config.default_mode.value,
                "runtime": "development" if development else "production",
                "supervised": True,
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        while not stopping:
            now_s = time.monotonic()
            for service in services:
                reason = service.needs_restart(now_s=now_s)
                if reason is not None:
                    service.restart(environment, reason)
            time.sleep(HEALTH_INTERVAL_S)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        for service in reversed(services):
            service.stop()
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
