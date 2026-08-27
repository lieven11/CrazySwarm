from __future__ import annotations

import hashlib
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
# Importing and validating the full campaign catalog can take longer than 20 seconds
# on a cold start.  Keep the process alive long enough to finish initialization;
# once it is running, the normal consecutive-failure checks still detect outages.
STARTUP_GRACE_S = 90.0
UI_RELEASES_DIRECTORY = ".crazyswarm-builds"
UI_RELEASE_MANIFEST = ".crazyswarm-release.json"
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


def is_git_worktree(project_root: Path) -> bool:
    return (project_root / ".git").is_file()


def default_dashboard_ports(project_root: Path) -> tuple[int, int]:
    """Keep Local stable and give each managed worktree deterministic private ports."""

    if not is_git_worktree(project_root):
        return 8011, 3001
    slot = int(hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()[:8], 16) % 2000
    return 18_000 + slot, 22_000 + slot


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


def signal_process_tree(process: subprocess.Popen[bytes], requested_signal: int) -> None:
    pid = getattr(process, "pid", None)
    if isinstance(pid, int):
        try:
            os.killpg(pid, requested_signal)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    process.send_signal(requested_signal)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    signal_process_tree(process, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        signal_process_tree(process, signal.SIGKILL)
        process.wait(timeout=2)


def _valid_ui_distribution(directory: Path) -> bool:
    distribution = directory / "dist"
    server = distribution / "server"
    return (distribution / "client").is_dir() and (
        (server / "index.js").is_file() or (server / "entry.js").is_file()
    )


def ui_source_sha256(ui_directory: Path) -> str:
    """Hash the UI inputs copied into an immutable production release."""

    digest = hashlib.sha256()

    def visit(directory: Path) -> None:
        for source in sorted(directory.iterdir(), key=lambda item: item.name):
            if directory == ui_directory and source.name in UI_BUILD_EXCLUDES:
                continue
            relative = source.relative_to(ui_directory)
            digest.update(relative.as_posix().encode())
            if source.is_symlink():
                digest.update(b"L")
                digest.update(os.readlink(source).encode())
            elif source.is_file():
                digest.update(b"F")
                digest.update(source.read_bytes())
            elif source.is_dir():
                digest.update(b"D")
                visit(source)

    visit(ui_directory)
    return digest.hexdigest()


def release_matches_ui_source(ui_directory: Path, release: Path) -> bool:
    try:
        manifest = json.loads((release / UI_RELEASE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return bool(
        manifest.get("schema_version") == 1
        and manifest.get("release") == release.name
        and manifest.get("source_sha256") == ui_source_sha256(ui_directory)
    )


def production_ui_directory(ui_directory: Path, release_name: str | None = None) -> Path:
    releases = ui_directory / UI_RELEASES_DIRECTORY
    if release_name is not None:
        if Path(release_name).name != release_name or not release_name.startswith("release-"):
            raise RuntimeError(f"invalid published UI release name: {release_name}")
        release = (releases / release_name).resolve(strict=True)
        if release.parent != releases.resolve():
            raise RuntimeError(f"published UI release escapes release directory: {release}")
    else:
        current = releases / "current"
        if current.is_symlink() or current.exists():
            release = current.resolve(strict=True)
        elif _valid_ui_distribution(ui_directory):
            # Backward-compatible first start before the service has published its
            # first immutable release.
            return ui_directory
        else:
            raise RuntimeError("UI production build not found; reinstall the dashboard service")

    if _valid_ui_distribution(release):
        return release
    raise RuntimeError(f"published UI release is incomplete: {release}")


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
        source_sha256 = ui_source_sha256(staging)
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
        shutil.copy2(staging / "package.json", release_staging / "package.json")
        (release_staging / UI_RELEASE_MANIFEST).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "release": release_name,
                    "source_sha256": source_sha256,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
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
        # Each managed component owns a process group so npm/node helpers and
        # Python worker children cannot survive a dashboard restart and retain
        # ports or hardware handles.
        self.process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=environment,
            start_new_session=True,
        )
        self.started_at_s = time.monotonic()
        self.failed_health_checks = 0

    def terminate(self) -> None:
        if self.process is not None and self.process.poll() is None:
            signal_process_tree(self.process, signal.SIGTERM)

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
    api_port: int | None,
    ui_port: int | None,
    development: bool = False,
    skip_build: bool = False,
    hardware_owner: str | None = None,
    ui_release: str | None = None,
) -> int:
    project_root = Path(__file__).resolve().parents[2]
    default_api_port, default_ui_port = default_dashboard_ports(project_root)
    api_port = default_api_port if api_port is None else api_port
    ui_port = default_ui_port if ui_port is None else ui_port
    if hardware_owner is not None and is_git_worktree(project_root):
        raise RuntimeError(
            "physical hardware runtime may only start from the Local checkout, never a worktree"
        )
    if hardware_owner is not None and development:
        raise RuntimeError(
            "physical hardware requires the stable production dashboard; pass --production"
        )
    if ui_release is not None and development:
        raise RuntimeError("an immutable UI release may be selected only in production")
    if not port_available("127.0.0.1", api_port):
        raise RuntimeError(f"API port {api_port} is already in use")
    if not port_available("127.0.0.1", ui_port):
        raise RuntimeError(f"UI port {ui_port} is already in use")
    npm = find_npm()
    if npm is None:
        raise RuntimeError("Node.js and npm are required to start the dashboard")
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
            "CRAZYSWARM_PHYSICAL_HARDWARE_ENABLED": ("1" if hardware_owner is not None else "0"),
        }
    )
    if not development and not skip_build:
        build_ui(npm, ui_directory, environment)
    ui_working_directory = ui_directory
    if not development:
        ui_working_directory = production_ui_directory(ui_directory, ui_release)
        # Port availability above guarantees that no older dashboard process is
        # still reading an earlier release when it is removed here.
        if ui_release is None:
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
    if hardware_owner is not None:
        api_command.extend(["--hardware-owner", hardware_owner])
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
        # The UI server is healthy when it can serve its own shell.  API health is
        # supervised separately, so an API cold start must not flap the UI process.
        health_url=f"http://127.0.0.1:{ui_port}/",
    )
    services = (api, ui)
    stopping = False

    def request_stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        # Forward immediately instead of waiting up to one health interval. This
        # gives the API time to zero physical outputs and close the Crazyradio
        # before launchd's service-exit deadline.
        for service in reversed(services):
            service.terminate()

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
                "physical_hardware": (
                    f"owned by {hardware_owner}" if hardware_owner is not None else "disabled"
                ),
                "checkout": "worktree" if is_git_worktree(project_root) else "local",
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
