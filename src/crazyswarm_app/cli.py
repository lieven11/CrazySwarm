from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from crazyswarm_app import __version__
from crazyswarm_app.api.app import create_app, generate_local_token
from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.missions.models import MissionResult, MissionStatus
from crazyswarm_app.missions.registry import default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.factory import vehicles_from_scenario


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crazyswarm-control")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="validate config and dependencies")
    health.add_argument("--config", type=Path, default=Path("config/app.yaml"))

    missions = subparsers.add_parser("missions", help="inspect and run registered missions")
    mission_commands = missions.add_subparsers(dest="mission_command", required=True)
    mission_commands.add_parser("list", help="list registered mission metadata")

    describe = mission_commands.add_parser("describe", help="describe one mission")
    describe.add_argument("mission_id")

    validate = mission_commands.add_parser("validate", help="validate mission parameters")
    validate.add_argument("mission_id")
    _add_mission_parameter_arguments(validate)

    run = mission_commands.add_parser("run", help="run a mission against the simulator")
    run.add_argument("mission_id")
    run.add_argument("--config", type=Path, default=Path("config/app.yaml"))
    run.add_argument("--scenario", type=Path, default=Path("config/worlds/one_drone.yaml"))
    run.add_argument("--vehicle-id")
    _add_mission_parameter_arguments(run)

    serve = subparsers.add_parser("serve", help="start the local authenticated control API")
    serve.add_argument("--config", type=Path, default=Path("config/app.yaml"))
    serve.add_argument("--scenario", type=Path, default=Path("config/worlds/one_drone.yaml"))
    serve.add_argument("--port", type=_port_number)

    dashboard = subparsers.add_parser(
        "dashboard", help="start the control UI and local API as one application"
    )
    dashboard.add_argument("--config", type=Path, default=Path("config/app.yaml"))
    dashboard.add_argument("--scenario", type=Path, default=Path("config/worlds/one_drone.yaml"))
    dashboard.add_argument("--api-port", type=_port_number, default=8001)
    dashboard.add_argument("--ui-port", type=_port_number, default=3001)
    return parser


def _port_number(raw: str) -> int:
    port = int(raw)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _add_mission_parameter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preset")
    parser.add_argument("--parameters", default="{}", help="JSON object of parameter values")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="NAME=JSON_VALUE",
        help="validated parameter override; may be repeated",
    )


def _json_parameters(raw: str) -> dict[str, object]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--parameters must contain a JSON object")
    return value


def _overrides(values: list[str]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"override must use NAME=JSON_VALUE: {value}")
        name, raw = value.split("=", 1)
        parsed[name] = json.loads(raw)
    return parsed


def _health(config_path: Path) -> int:
    config = load_config(config_path)
    report = {
        "status": "ok",
        "application_version": __version__,
        "config_schema_version": config.schema_version,
        "default_mode": config.default_mode.value,
        "config_path": str(config_path),
        "dependencies": {
            "cflib": _package_version("cflib"),
            "fastapi": _package_version("fastapi"),
            "pydantic": _package_version("pydantic"),
            "PyYAML": _package_version("PyYAML"),
            "uvicorn": _package_version("uvicorn"),
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _missions(args: argparse.Namespace) -> int:
    registry = default_registry()
    if args.mission_command == "list":
        print(
            json.dumps(
                [item.model_dump(mode="json") for item in registry.list_metadata()],
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.mission_command == "describe":
        print(json.dumps(registry.metadata(args.mission_id).model_dump(mode="json"), indent=2))
        return 0
    parameters = _json_parameters(args.parameters)
    overrides = _overrides(args.overrides)
    if args.mission_command == "validate":
        validated = registry.validate_parameters(
            args.mission_id,
            parameters,
            preset=args.preset,
            overrides=overrides,
        )
        print(
            json.dumps(
                {"valid": True, "parameters": validated.model_dump(mode="json")},
                indent=2,
            )
        )
        return 0
    if args.mission_command == "run":
        result = asyncio.run(
            _run_sim_mission(
                args.mission_id,
                args.config,
                args.scenario,
                args.vehicle_id,
                parameters,
                args.preset,
                overrides,
            )
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2))
        return 0 if result.status is MissionStatus.SUCCEEDED else 1
    raise AssertionError(f"unhandled mission command: {args.mission_command}")


def _serve(config_path: Path, scenario_path: Path, port_override: int | None = None) -> int:
    import uvicorn

    config = load_config(config_path)
    runtime = create_runtime(config, scenario_path)
    token = os.environ.get("CRAZYSWARM_LOCAL_TOKEN") or generate_local_token()
    port = config.api.port if port_override is None else port_override
    hide_internal_service = os.environ.get("CRAZYSWARM_HIDE_LOCAL_TOKEN") == "1"
    report = {
        "status": "starting",
        "url": f"http://{config.api.bind_host}:{port}",
        "mode": config.default_mode.value,
    }
    if not hide_internal_service:
        report.update(
            {
                "local_token": token,
                "token_note": "send as X-Local-Token; generated tokens change on restart",
            }
        )
        print(json.dumps(report, indent=2), file=sys.stderr)
    app = create_app(runtime, local_token=token)
    uvicorn.run(
        app,
        host=config.api.bind_host,
        port=port,
        access_log=False,
        log_level="warning" if hide_internal_service else "info",
    )
    return 0


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _dashboard(
    config_path: Path,
    scenario_path: Path,
    *,
    api_port: int,
    ui_port: int,
) -> int:
    if not _port_available("127.0.0.1", api_port):
        raise RuntimeError(f"API port {api_port} is already in use")
    if not _port_available("127.0.0.1", ui_port):
        raise RuntimeError(f"UI port {ui_port} is already in use")
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required to start the dashboard")
    project_root = Path(__file__).resolve().parents[2]
    ui_directory = project_root / "ui"
    if not (ui_directory / "package.json").exists():
        raise RuntimeError(f"UI package not found: {ui_directory}")

    config = load_config(config_path)
    token = generate_local_token()
    environment = os.environ.copy()
    environment.update(
        {
            "CRAZYSWARM_LOCAL_TOKEN": token,
            "CRAZYSWARM_HIDE_LOCAL_TOKEN": "1",
            "CRAZYSWARM_API_URL": f"http://127.0.0.1:{api_port}",
        }
    )
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
    ui_command = [npm, "run", "dev", "--", "--port", str(ui_port)]
    api_process = subprocess.Popen(api_command, cwd=project_root, env=environment)
    ui_process = subprocess.Popen(ui_command, cwd=ui_directory, env=environment)
    print(
        json.dumps(
            {
                "status": "starting",
                "url": f"http://localhost:{ui_port}",
                "mode": config.default_mode.value,
            },
            indent=2,
        )
    )
    try:
        while api_process.poll() is None and ui_process.poll() is None:
            time.sleep(0.25)
        return api_process.returncode or ui_process.returncode or 1
    except KeyboardInterrupt:
        return 0
    finally:
        _stop_process(ui_process)
        _stop_process(api_process)


async def _run_sim_mission(
    mission_id: str,
    config_path: Path,
    scenario_path: Path,
    vehicle_id: str | None,
    parameters: dict[str, object],
    preset: str | None,
    overrides: dict[str, object],
) -> MissionResult:
    config = load_config(config_path)
    vehicles = vehicles_from_scenario(scenario_path)
    selected = next(
        (vehicle for vehicle in vehicles if vehicle.identity.vehicle_id == vehicle_id),
        vehicles[0] if vehicle_id is None and vehicles else None,
    )
    if selected is None:
        raise ValueError(f"vehicle not found in scenario: {vehicle_id}")
    supervisor = SafetySupervisor(config.safety_envelope)
    supervisor.register_vehicle(selected)
    runner = MissionRunner(supervisor, default_registry())
    return await runner.run(
        mission_id,
        selected.identity.vehicle_id,
        parameters=parameters,
        preset=preset,
        overrides=overrides,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "health":
        return _health(args.config)
    if args.command == "missions":
        return _missions(args)
    if args.command == "serve":
        return _serve(args.config, args.scenario, args.port)
    if args.command == "dashboard":
        return _dashboard(
            args.config,
            args.scenario,
            api_port=args.api_port,
            ui_port=args.ui_port,
        )
    raise AssertionError(f"unhandled command: {args.command}")
