from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from crazyswarm_app import __version__
from crazyswarm_app.api.app import create_app, generate_local_token
from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.dashboard import is_git_worktree, port_available, run_dashboard
from crazyswarm_app.dashboard_service import (
    install_service,
    restart_service,
    service_status,
    uninstall_service,
)
from crazyswarm_app.hardware.ownership import (
    claim_hardware_runtime,
    read_hardware_runtime_owner,
)
from crazyswarm_app.missions.models import MissionResult, MissionStatus
from crazyswarm_app.missions.registry import default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.provenance import repository_provenance
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
    serve.add_argument("--reload", action="store_true", help="restart when backend files change")
    serve.add_argument(
        "--hardware-owner",
        help="claim the exclusive physical Crazyradio runtime for this named operator process",
    )

    dashboard = subparsers.add_parser(
        "dashboard", help="start the control UI and local API as one application"
    )
    dashboard.add_argument("--config", type=Path, default=Path("config/app.yaml"))
    dashboard.add_argument("--scenario", type=Path, default=Path("config/worlds/one_drone.yaml"))
    dashboard.add_argument("--api-port", type=_port_number)
    dashboard.add_argument("--ui-port", type=_port_number)
    dashboard.set_defaults(development=True)
    dashboard.add_argument(
        "--dev",
        dest="development",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    dashboard.add_argument(
        "--production",
        dest="development",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    dashboard.add_argument("--skip-build", action="store_true", help=argparse.SUPPRESS)
    dashboard.add_argument("--ui-release", help=argparse.SUPPRESS)
    dashboard.add_argument(
        "--hardware-owner",
        help="claim the exclusive physical Crazyradio runtime; omitted means simulation-only",
    )

    hardware_owner = subparsers.add_parser(
        "hardware-owner", help="inspect exclusive physical-runtime ownership"
    )
    hardware_owner.add_argument("owner_command", choices=("status",))

    service = subparsers.add_parser(
        "dashboard-service", help="manage the persistent macOS dashboard service"
    )
    service_commands = service.add_subparsers(dest="service_command", required=True)
    install = service_commands.add_parser("install", help="build and install the user service")
    install.add_argument("--config", type=Path, default=Path("config/app.yaml"))
    install.add_argument("--scenario", type=Path, default=Path("config/worlds/one_drone.yaml"))
    install.add_argument("--api-port", type=_port_number, default=8011)
    install.add_argument("--ui-port", type=_port_number, default=3001)
    status = service_commands.add_parser("status", help="check the user service")
    status.add_argument("--ui-port", type=_port_number, default=3001)
    status.add_argument(
        "--allow-stale-source",
        action="store_true",
        help=(
            "report success when the installed service is healthy but source changes "
            "are undeployed"
        ),
    )
    service_commands.add_parser("restart", help="restart the user service")
    service_commands.add_parser("uninstall", help="remove the user service")
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
    provenance = repository_provenance()
    report = {
        "status": "ok",
        "application_version": __version__,
        "config_schema_version": config.schema_version,
        "default_mode": config.default_mode.value,
        "config_path": str(config_path),
        **provenance.as_dict(),
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


def _create_reloadable_app() -> object:
    config_path = Path(os.environ["CRAZYSWARM_CONFIG_PATH"])
    scenario_path = Path(os.environ["CRAZYSWARM_SCENARIO_PATH"])
    token = os.environ["CRAZYSWARM_LOCAL_TOKEN"]
    config = load_config(config_path)
    runtime = create_runtime(config, scenario_path)
    return create_app(runtime, local_token=token)


def _serve(
    config_path: Path,
    scenario_path: Path,
    port_override: int | None = None,
    *,
    reload: bool = False,
    hardware_owner: str | None = None,
) -> int:
    import uvicorn

    project_root = Path(__file__).resolve().parents[2]
    if hardware_owner is not None and is_git_worktree(project_root):
        raise RuntimeError(
            "physical hardware runtime may only start from the Local checkout, never a worktree"
        )
    if reload and hardware_owner is not None:
        raise RuntimeError(
            "physical hardware runtime cannot use auto-reload; use a stable production service"
        )
    config = load_config(config_path)
    token = os.environ.get("CRAZYSWARM_LOCAL_TOKEN") or generate_local_token()
    port = config.api.port if port_override is None else port_override
    if not port_available(config.api.bind_host, port):
        raise RuntimeError(f"API port {port} is already in use")
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
    if reload:
        os.environ.update(
            {
                "CRAZYSWARM_CONFIG_PATH": str(config_path.resolve()),
                "CRAZYSWARM_SCENARIO_PATH": str(scenario_path.resolve()),
                "CRAZYSWARM_LOCAL_TOKEN": token,
            }
        )
        uvicorn.run(
            "crazyswarm_app.cli:_create_reloadable_app",
            factory=True,
            host=config.api.bind_host,
            port=port,
            access_log=False,
            log_level="warning" if hide_internal_service else "info",
            reload=True,
            reload_dirs=[
                str(project_root / "src"),
                str(project_root / "config"),
                str(project_root / "missions"),
            ],
            reload_includes=["*.py", "*.yaml", "*.yml", "*.json"],
        )
        return 0

    if hardware_owner is None:
        os.environ["CRAZYSWARM_PHYSICAL_HARDWARE_ENABLED"] = "0"
        runtime = create_runtime(config, scenario_path)
        app = create_app(runtime, local_token=token, physical_hardware_enabled=False)
        uvicorn.run(
            app,
            host=config.api.bind_host,
            port=port,
            access_log=False,
            log_level="warning" if hide_internal_service else "info",
        )
        return 0

    with claim_hardware_runtime(hardware_owner, checkout=Path.cwd()):
        runtime = create_runtime(config, scenario_path)
        app = create_app(runtime, local_token=token, physical_hardware_enabled=True)
        uvicorn.run(
            app,
            host=config.api.bind_host,
            port=port,
            access_log=False,
            log_level="warning" if hide_internal_service else "info",
        )
    return 0


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
        return _serve(
            args.config,
            args.scenario,
            args.port,
            reload=args.reload,
            hardware_owner=args.hardware_owner,
        )
    if args.command == "dashboard":
        return run_dashboard(
            args.config,
            args.scenario,
            api_port=args.api_port,
            ui_port=args.ui_port,
            development=args.development,
            skip_build=args.skip_build,
            hardware_owner=args.hardware_owner,
            ui_release=args.ui_release,
        )
    if args.command == "hardware-owner":
        owner = read_hardware_runtime_owner()
        print(
            json.dumps(
                {
                    "owned": owner is not None,
                    "owner": None
                    if owner is None
                    else {
                        "name": owner.owner,
                        "pid": owner.pid,
                        "hostname": owner.hostname,
                        "checkout": owner.checkout,
                        "acquired_at_utc": owner.acquired_at_utc,
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "dashboard-service":
        if args.service_command == "install":
            return install_service(
                args.config,
                args.scenario,
                api_port=args.api_port,
                ui_port=args.ui_port,
            )
        if args.service_command == "status":
            return service_status(
                ui_port=args.ui_port,
                allow_stale_source=args.allow_stale_source,
            )
        if args.service_command == "restart":
            return restart_service()
        if args.service_command == "uninstall":
            return uninstall_service()
    raise AssertionError(f"unhandled command: {args.command}")
