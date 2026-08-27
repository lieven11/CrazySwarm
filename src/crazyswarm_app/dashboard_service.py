from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from crazyswarm_app.api.app import generate_local_token
from crazyswarm_app.config import load_config
from crazyswarm_app.dashboard import (
    STARTUP_GRACE_S,
    build_ui,
    find_npm,
    is_git_worktree,
    production_ui_directory,
    release_matches_ui_source,
)
from crazyswarm_app.hardware.ownership import claim_hardware_deployment

SERVICE_LABEL = "com.crazyswarm.control-center"
BOOTSTRAP_ATTEMPTS = 10


def _require_local_checkout() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    if is_git_worktree(project_root):
        raise RuntimeError(
            "the operator dashboard service may only be managed from the Local checkout"
        )
    return project_root


def service_paths(project_root: Path) -> tuple[Path, Path, Path]:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    log_directory = project_root / ".cache" / "crazyswarm"
    return plist, log_directory / "dashboard.stdout.log", log_directory / "dashboard.stderr.log"


def service_target() -> str:
    return f"gui/{os.getuid()}/{SERVICE_LABEL}"


def _rotate_log(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return
    previous = path.with_suffix(f"{path.suffix}.1")
    previous.unlink(missing_ok=True)
    path.replace(previous)


def _bootstrap(plist_path: Path) -> None:
    command = ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)]
    last: subprocess.CompletedProcess[bytes] | None = None
    for _ in range(BOOTSTRAP_ATTEMPTS):
        last = subprocess.run(
            command,
            capture_output=True,
            check=False,
        )
        if last.returncode == 0:
            return
        time.sleep(0.5)
    assert last is not None
    raise subprocess.CalledProcessError(
        last.returncode,
        command,
        output=last.stdout,
        stderr=last.stderr,
    )


def install_service(
    config_path: Path,
    scenario_path: Path,
    *,
    api_port: int,
    ui_port: int,
) -> int:
    project_root = _require_local_checkout()
    ui_directory = project_root / "ui"
    npm = find_npm()
    if npm is None:
        raise RuntimeError("npm is required to install the dashboard service")
    config = load_config(config_path)
    configured_cache = config.cache_directory
    if not configured_cache.is_absolute():
        configured_cache = project_root / configured_cache
    canonical_cache = project_root / ".cache" / "crazyswarm"
    if configured_cache.resolve() != canonical_cache.resolve():
        raise RuntimeError(
            "the operator dashboard must use the Local checkout's canonical "
            f"cache directory: {canonical_cache}"
        )
    with claim_hardware_deployment(canonical_cache):
        _require_safe_deployment_state(
            ui_port=ui_port,
            physical_power_removed=os.environ.get("CRAZYSWARM_PHYSICAL_POWER_REMOVED") == "1",
        )
        return _install_service_with_admission_blocked(
            project_root=project_root,
            ui_directory=ui_directory,
            npm=npm,
            config_path=config_path,
            scenario_path=scenario_path,
            api_port=api_port,
            ui_port=ui_port,
        )


def _install_service_with_admission_blocked(
    *,
    project_root: Path,
    ui_directory: Path,
    npm: str,
    config_path: Path,
    scenario_path: Path,
    api_port: int,
    ui_port: int,
) -> int:
    environment = os.environ.copy()
    node_bin = str(Path(npm).parent)
    environment["PATH"] = os.pathsep.join(
        part for part in (node_bin, environment.get("PATH", "")) if part
    )
    token = generate_local_token()
    environment.update(
        {
            "CRAZYSWARM_LOCAL_TOKEN": token,
            "CRAZYSWARM_HIDE_LOCAL_TOKEN": "1",
            "CRAZYSWARM_API_URL": f"http://127.0.0.1:{api_port}",
            "CRAZYSWARM_PHYSICAL_HARDWARE_ENABLED": "1",
            "CRAZYSWARM_HARDWARE_OWNER": "operator-dashboard-service",
        }
    )
    release = build_ui(npm, ui_directory, environment)
    if production_ui_directory(ui_directory, release.name) != release.resolve():
        raise RuntimeError("new UI release was not published at its immutable path")
    if not release_matches_ui_source(ui_directory, release):
        raise RuntimeError("new UI release does not match the current UI source")

    plist_path, stdout_path, stderr_path = service_paths(project_root)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    service_environment = {
        "PATH": f"{node_bin}:/usr/local/bin:/usr/bin:/bin",
        "PYTHONUNBUFFERED": "1",
        "CRAZYSWARM_LOCAL_TOKEN": token,
        "CRAZYSWARM_HIDE_LOCAL_TOKEN": "1",
        "CRAZYSWARM_API_URL": f"http://127.0.0.1:{api_port}",
        "CRAZYSWARM_PHYSICAL_HARDWARE_ENABLED": "1",
        "CRAZYSWARM_HARDWARE_OWNER": "operator-dashboard-service",
    }
    payload: dict[str, Any] = {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "crazyswarm_app",
            "dashboard",
            "--config",
            str(config_path.resolve()),
            "--scenario",
            str(scenario_path.resolve()),
            "--api-port",
            str(api_port),
            "--ui-port",
            str(ui_port),
            "--production",
            "--skip-build",
            "--ui-release",
            release.name,
            "--hardware-owner",
            "operator-dashboard-service",
        ],
        "WorkingDirectory": str(project_root),
        "EnvironmentVariables": service_environment,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 5,
        "ExitTimeOut": 30,
        "ProcessType": "Interactive",
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
    }
    with plist_path.open("wb") as output:
        plistlib.dump(payload, output, sort_keys=True)
    plist_path.chmod(0o600)

    subprocess.run(
        ["launchctl", "bootout", service_target()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    _rotate_log(stdout_path)
    _rotate_log(stderr_path)
    _bootstrap(plist_path)
    subprocess.run(["launchctl", "kickstart", "-k", service_target()], check=True)
    deadline_s = time.monotonic() + STARTUP_GRACE_S + 15.0
    urls = (
        f"http://127.0.0.1:{ui_port}/",
        f"http://127.0.0.1:{ui_port}/control-api/api/v1/state",
    )
    while time.monotonic() < deadline_s:
        if all(_url_healthy(url) for url in urls):
            break
        time.sleep(0.5)
    else:
        raise RuntimeError(f"dashboard service did not become ready; inspect {stderr_path}")
    print(
        f"Dashboard service installed at http://localhost:{ui_port}; "
        f"logs: {stdout_path} and {stderr_path}"
    )
    return 0


def _require_safe_deployment_state(
    *,
    ui_port: int,
    physical_power_removed: bool,
) -> None:
    base_url = f"http://127.0.0.1:{ui_port}/control-api/api/v1/physical-twin/lab"
    actuation = _read_json_url(f"{base_url}/motor-actuation")
    if actuation.get("state") != "IDLE" or actuation.get("stop_required") is not False:
        raise RuntimeError(
            "dashboard deployment refused: physical motor output is active or unconfirmed"
        )
    flight = _read_json_url(f"{base_url}/physical-flight")
    if flight.get("stop_required") is not False and not physical_power_removed:
        raise RuntimeError(
            "dashboard deployment refused: a physical flight stop is active or unconfirmed"
        )


def _read_json_url(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:
            payload = json.load(response)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "dashboard deployment refused: current physical state could not be confirmed"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError(
            "dashboard deployment refused: current physical state response is invalid"
        )
    return payload


def service_status(*, ui_port: int, allow_stale_source: bool = False) -> int:
    project_root = _require_local_checkout()
    completed = subprocess.run(
        ["launchctl", "print", service_target()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    healthy = _url_healthy(f"http://127.0.0.1:{ui_port}/control-api/api/v1/state")
    plist_path, _, _ = service_paths(project_root)
    canonical = False
    current_source = False
    release_name: str | None = None
    try:
        with plist_path.open("rb") as source:
            payload = plistlib.load(source)
        arguments = payload.get("ProgramArguments", [])
        release_index = arguments.index("--ui-release") + 1
        release_name = arguments[release_index]
        canonical = (
            payload.get("WorkingDirectory") == str(project_root)
            and "--hardware-owner" in arguments
            and arguments[arguments.index("--hardware-owner") + 1] == "operator-dashboard-service"
        )
        release = production_ui_directory(project_root / "ui", release_name)
        current_source = release_matches_ui_source(project_root / "ui", release)
    except (OSError, ValueError, IndexError, KeyError, RuntimeError):
        pass

    print(
        f"service={'loaded' if completed.returncode == 0 else 'not-loaded'} "
        f"healthy={healthy} canonical={canonical} current_source={current_source} "
        f"release={release_name or 'unselected'}"
    )
    ready = completed.returncode == 0 and healthy and canonical
    return 0 if ready and (current_source or allow_stale_source) else 1


def _url_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            return 200 <= int(response.status) < 300
    except OSError:
        return False


def restart_service() -> int:
    _require_local_checkout()
    subprocess.run(["launchctl", "kickstart", "-k", service_target()], check=True)
    return 0


def uninstall_service() -> int:
    project_root = _require_local_checkout()
    plist_path, _, _ = service_paths(project_root)
    subprocess.run(
        ["launchctl", "bootout", service_target()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    plist_path.unlink(missing_ok=True)
    print("Dashboard service removed; application data and logs were kept.")
    return 0
