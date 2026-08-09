from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from crazyswarm_app.api.app import generate_local_token
from crazyswarm_app.dashboard import build_ui, find_npm

SERVICE_LABEL = "com.crazyswarm.control-center"
BOOTSTRAP_ATTEMPTS = 10


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
    project_root = Path(__file__).resolve().parents[2]
    ui_directory = project_root / "ui"
    npm = find_npm()
    if npm is None:
        raise RuntimeError("npm is required to install the dashboard service")
    environment = os.environ.copy()
    token = generate_local_token()
    environment.update(
        {
            "CRAZYSWARM_LOCAL_TOKEN": token,
            "CRAZYSWARM_HIDE_LOCAL_TOKEN": "1",
            "CRAZYSWARM_API_URL": f"http://127.0.0.1:{api_port}",
        }
    )
    build_ui(npm, ui_directory, environment)

    plist_path, stdout_path, stderr_path = service_paths(project_root)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    node_bin = str(Path(npm).parent)
    service_environment = {
        "PATH": f"{node_bin}:/usr/local/bin:/usr/bin:/bin",
        "PYTHONUNBUFFERED": "1",
        "CRAZYSWARM_LOCAL_TOKEN": token,
        "CRAZYSWARM_HIDE_LOCAL_TOKEN": "1",
        "CRAZYSWARM_API_URL": f"http://127.0.0.1:{api_port}",
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
        ],
        "WorkingDirectory": str(project_root),
        "EnvironmentVariables": service_environment,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 5,
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
    deadline_s = time.monotonic() + 45.0
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


def service_status(*, ui_port: int) -> int:
    completed = subprocess.run(
        ["launchctl", "print", service_target()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    healthy = _url_healthy(f"http://127.0.0.1:{ui_port}/control-api/api/v1/state")

    print(f"service={'loaded' if completed.returncode == 0 else 'not-loaded'} healthy={healthy}")
    return 0 if completed.returncode == 0 and healthy else 1


def _url_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            return 200 <= int(response.status) < 300
    except OSError:
        return False


def restart_service() -> int:
    subprocess.run(["launchctl", "kickstart", "-k", service_target()], check=True)
    return 0


def uninstall_service() -> int:
    project_root = Path(__file__).resolve().parents[2]
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
