from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import CoordinateFrame, Identifier, VehicleCapability
from crazyswarm_app.domain.telemetry import RangeStatus
from crazyswarm_app.domain.trajectory import (
    GroundWaitExecutionOperation,
    HoldExecutionOperation,
    LandExecutionOperation,
    TakeoffExecutionOperation,
    TrajectoryExecutionOperation,
)
from crazyswarm_app.missions.base import Mission, MissionContext, MissionParameters
from crazyswarm_app.missions.observation import MissionObservation
from crazyswarm_app.missions.registry import MissionRegistry

MAX_SOURCE_BYTES = 128 * 1024
MAX_COMMAND_BUDGET = 128
MAX_OBSERVATION_BUDGET = 64
MAX_LOOP_ITERATIONS = 64
MAX_PROTOCOL_BYTES = 1024 * 1024
TIER_A_ACTIONS = frozenset({"takeoff", "hover", "move_relative", "land"})
TIER_B_ACTIONS = TIER_A_ACTIONS | frozenset({"observe", "wait", "checkpoint"})
MISSION_WORKER_ID = "restricted-python-online"
MISSION_WORKER_VERSION = "2.0.0"
MISSION_LANGUAGE_VERSION = "bounded-python-1"
MISSION_WORKER_START_TIMEOUT_S = 2.0
MISSION_WORKER_TIMEOUT_S = MISSION_WORKER_START_TIMEOUT_S  # Tier-A compatibility alias
MISSION_CALL_TIMEOUT_S = 5.0
MISSION_ID_PATTERN = re.compile(r"py-[0-9a-f]{20}\Z")
_WORKER_DIRECTORIES: dict[int, str] = {}


class MissionTier(StrEnum):
    LINEAR = "TIER_A_LINEAR"
    BOUNDED_OBSERVATION = "TIER_B_BOUNDED_OBSERVATION"


class EmptyScriptParameters(MissionParameters):
    """Uploaded mission files are complete artifacts and expose no UI parameters."""


class ScriptStep(MissionParameters):
    action: Literal[
        "takeoff",
        "hover",
        "move_relative",
        "land",
        "observe",
        "wait",
        "checkpoint",
    ]
    arguments: dict[str, float | str] = Field(default_factory=dict)


class MissionZoneSpec(MissionParameters):
    minimum_m: tuple[float, float, float]
    maximum_m: tuple[float, float, float]

    @model_validator(mode="after")
    def ordered(self) -> MissionZoneSpec:
        if not all(low <= high for low, high in zip(self.minimum_m, self.maximum_m, strict=True)):
            raise ValueError("mission role zone bounds are not ordered")
        if not (self.minimum_m[0] < self.maximum_m[0] and self.minimum_m[1] < self.maximum_m[1]):
            raise ValueError("mission role zone requires non-zero horizontal area")
        return self


class MissionTaskSpec(MissionParameters):
    task_type: Identifier = "MISSION_ROLE"
    priority: int = Field(default=100, ge=0, le=1000)
    estimated_energy_percent: float | None = Field(default=None, gt=0.0, le=100.0)
    energy_margin_percent: float = Field(default=10.0, ge=0.0, le=100.0)


class MissionRoleSpec(MissionParameters):
    role_id: Identifier
    logical_vehicle_id: Identifier
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    home_m: tuple[float, float, float]
    initial_role: Literal["ACTIVE", "RESERVE"] = "ACTIVE"
    required: bool = True
    required_capabilities: frozenset[VehicleCapability] = Field(default_factory=frozenset)
    zone: MissionZoneSpec | None = None
    task: MissionTaskSpec = Field(default_factory=MissionTaskSpec)


class MissionPackageV2(MissionParameters):
    schema_version: Literal[2]
    roles: tuple[MissionRoleSpec, ...]
    warning_separation_m: float = Field(default=0.75, gt=0.0)
    critical_separation_m: float = Field(default=0.5, gt=0.0)
    observation_freshness_s: float = Field(default=1.0, gt=0.0)
    child_failure_policy: Literal["CONTINUE_HEALTHY", "HOLD_ALL", "LAND_ALL"] = "CONTINUE_HEALTHY"
    planned_hold_permitted: bool = True
    deconfliction_strategies: tuple[
        Literal[
            "STAGING_HOLD",
            "SPEED_RETIMING",
            "HORIZONTAL_DETOUR",
            "VERTICAL_SEPARATION",
            "COMBINED_RETIMING_VERTICAL",
        ],
        ...,
    ] = (
        "STAGING_HOLD",
        "SPEED_RETIMING",
        "HORIZONTAL_DETOUR",
        "VERTICAL_SEPARATION",
        "COMBINED_RETIMING_VERTICAL",
    )

    @model_validator(mode="after")
    def valid_fleet(self) -> MissionPackageV2:
        if not 1 <= len(self.roles) <= 3:
            raise ValueError("mission package requires between one and three roles")
        if len({item.role_id for item in self.roles}) != len(self.roles):
            raise ValueError("mission role identities must be unique")
        if len({item.logical_vehicle_id for item in self.roles}) != len(self.roles):
            raise ValueError("logical vehicle identities must be unique")
        if not any(item.initial_role == "ACTIVE" for item in self.roles):
            raise ValueError("mission package requires at least one active role")
        if self.warning_separation_m <= self.critical_separation_m:
            raise ValueError("warning separation must exceed critical separation")
        if not self.deconfliction_strategies:
            raise ValueError("mission package requires at least one deconfliction strategy")
        if len(set(self.deconfliction_strategies)) != len(self.deconfliction_strategies):
            raise ValueError("deconfliction strategies must be unique")
        if not self.planned_hold_permitted and "STAGING_HOLD" in self.deconfliction_strategies:
            raise ValueError("no-hover mission package cannot admit staging hold")
        return self


class MissionFileRecord(MissionParameters):
    mission_id: str
    name: str
    filename: str
    source_sha256: str
    source: str
    language_version: str = MISSION_LANGUAGE_VERSION
    tier: MissionTier
    steps: tuple[ScriptStep, ...]
    planned_command_budget: int = Field(ge=2, le=MAX_COMMAND_BUDGET)
    planned_observation_budget: int = Field(ge=0, le=MAX_OBSERVATION_BUDGET)
    planned_duration_s: float = Field(ge=0.0, le=300.0)
    requires_range: bool = False
    package_schema_version: Literal[1, 2] = 1
    roles: tuple[MissionRoleSpec, ...] = ()
    package: MissionPackageV2 | None = None
    archived: bool = False


class ScriptMission(Mission[EmptyScriptParameters]):
    parameters_type = EmptyScriptParameters
    manages_flight_path = True
    source_kind = "UPLOADED_PYTHON"
    runtime_id = MISSION_WORKER_ID
    runtime_version = MISSION_WORKER_VERSION

    def __init__(self, record: MissionFileRecord) -> None:
        self.record = record
        self.mission_id = record.mission_id
        self.mission_version = record.source_sha256[:12]
        self.name = record.name
        self.description = record.filename
        self.source_filename = record.filename
        self.source_sha256 = record.source_sha256
        capabilities = {
            VehicleCapability.ARMING,
            VehicleCapability.RELATIVE_POSITIONING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
        }
        if record.requires_range:
            capabilities.add(VehicleCapability.RANGE_SENSING)
        self.required_capabilities = frozenset(capabilities)
        self.planned_commands = tuple(step.model_dump(mode="json") for step in record.steps)
        self.package_schema_version = record.package_schema_version
        self.logical_roles = tuple(role.model_dump(mode="json") for role in record.roles)

    async def execute(
        self,
        context: MissionContext,
        parameters: EmptyScriptParameters,
    ) -> None:
        del parameters
        if context.accepted_execution_program is not None:
            await execute_accepted_program(self.record, context)
        else:
            await execute_online_mission(self.record, context, role_id=context.role_id)

    def execution_timeout_s(self, parameters: EmptyScriptParameters) -> float:
        del parameters
        return min(300.0, self.record.planned_duration_s + 15.0)


async def execute_accepted_program(
    record: MissionFileRecord,
    context: MissionContext,
) -> None:
    program = context.accepted_execution_program
    if program is None:
        raise CrazySwarmError(ErrorCode.INVALID_STATE, "accepted execution program is absent")
    if (
        program.mission_source_sha256 != record.source_sha256
        or program.role_id != context.role_id
        or program.vehicle_id != context.vehicle_id
    ):
        raise CrazySwarmError(
            ErrorCode.IDENTITY_MISMATCH,
            "accepted execution program does not match mission, role, and vehicle",
        )
    for operation in program.operations:
        context.checkpoint()
        if isinstance(operation, GroundWaitExecutionOperation):
            if operation.sequence not in context.completed_ground_wait_sequences:
                await context.ground_wait(operation.ends_at_s - operation.starts_at_s)
        elif isinstance(operation, TakeoffExecutionOperation):
            await context.takeoff(
                height_m=operation.target_height_m,
                duration_s=operation.ends_at_s - operation.starts_at_s,
            )
        elif isinstance(operation, HoldExecutionOperation):
            await context.hover(operation.ends_at_s - operation.starts_at_s)
        elif isinstance(operation, TrajectoryExecutionOperation):
            await context.execute_trajectory(operation.trajectory)
        elif isinstance(operation, LandExecutionOperation):
            if operation.goal_region is not None:
                await context.capture_and_land(
                    operation.goal_region,
                    duration_s=operation.ends_at_s - operation.starts_at_s,
                )
            else:
                await context.land(duration_s=operation.ends_at_s - operation.starts_at_s)
        else:  # pragma: no cover - discriminated contract is exhaustive
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "unknown execution operation")


@dataclass(slots=True)
class MissionFileLibrary:
    directory: Path
    registry: MissionRegistry

    def load(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for metadata_path in sorted(self.directory.glob("*.json")):
            try:
                raw, source_path = self._read_owned_artifact(metadata_path)
                if bool(raw.get("archived", False)):
                    continue
                record = parse_python_mission(
                    filename=str(raw["filename"]),
                    name=str(raw["name"]),
                    source=source_path.read_text(encoding="utf-8"),
                )
                self.registry.register(ScriptMission(record), replace=True)
            except (OSError, ValueError, KeyError, json.JSONDecodeError, CrazySwarmError):
                continue

    def add(self, *, filename: str, name: str, source: str) -> MissionFileRecord:
        record = parse_python_mission(filename=filename, name=name, source=source)
        self.directory.mkdir(parents=True, exist_ok=True)
        source_filename = f"{record.mission_id}.py"
        source_path = self.directory / source_filename
        metadata_path = self.directory / f"{record.mission_id}.json"
        if source_path.is_symlink() or metadata_path.is_symlink():
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission artifact path is unsafe")
        if source_path.exists() and source_path.read_text(encoding="utf-8") != record.source:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission artifact hash collision")
        if not source_path.exists():
            source_path.write_text(record.source, encoding="utf-8")
        metadata = {
            "mission_id": record.mission_id,
            "name": record.name,
            "filename": record.filename,
            "source_sha256": record.source_sha256,
            "source_file": source_filename,
            "language_version": record.language_version,
            "tier": record.tier.value,
            "archived": False,
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self.registry.register(ScriptMission(record), replace=True)
        return record

    def archive(self, mission_id: str) -> MissionFileRecord:
        if not MISSION_ID_PATTERN.fullmatch(mission_id):
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "invalid uploaded mission identity")
        metadata_path = self.directory / f"{mission_id}.json"
        try:
            raw, source_path = self._read_owned_artifact(metadata_path)
            record = parse_python_mission(
                filename=str(raw["filename"]),
                name=str(raw["name"]),
                source=source_path.read_text(encoding="utf-8"),
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                f"unknown uploaded mission: {mission_id}",
            ) from error
        if record.mission_id != mission_id:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission artifact identity mismatch")
        raw["archived"] = True
        metadata_path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
        self.registry.unregister(mission_id)
        return record.model_copy(update={"archived": True})

    def list_archive(self) -> tuple[MissionFileRecord, ...]:
        records: list[MissionFileRecord] = []
        for metadata_path in sorted(self.directory.glob("*.json")):
            try:
                raw, source_path = self._read_owned_artifact(metadata_path)
                if not bool(raw.get("archived", False)):
                    continue
                record = parse_python_mission(
                    filename=str(raw["filename"]),
                    name=str(raw["name"]),
                    source=source_path.read_text(encoding="utf-8"),
                )
                records.append(record.model_copy(update={"archived": True}))
            except (OSError, KeyError, json.JSONDecodeError, CrazySwarmError):
                continue
        return tuple(records)

    def _read_owned_artifact(self, metadata_path: Path) -> tuple[dict[str, object], Path]:
        if metadata_path.is_symlink() or metadata_path.parent.resolve() != self.directory.resolve():
            raise ValueError("mission metadata path is unsafe")
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        mission_id = str(raw["mission_id"])
        if not MISSION_ID_PATTERN.fullmatch(mission_id):
            raise ValueError("mission identity is invalid")
        if metadata_path.name != f"{mission_id}.json":
            raise ValueError("mission metadata identity does not match its filename")
        source_file = str(raw["source_file"])
        if source_file != f"{mission_id}.py":
            raise ValueError("mission source path does not match its identity")
        source_path = self.directory / source_file
        if source_path.is_symlink() or source_path.parent.resolve() != self.directory.resolve():
            raise ValueError("mission source path is unsafe")
        return raw, source_path


async def execute_online_mission(
    record: MissionFileRecord,
    context: MissionContext,
    *,
    role_id: str = "primary",
) -> None:
    process = await _start_worker(record, mode="online", role_id=role_id)
    assert process.stdout is not None
    assert process.stdin is not None
    try:
        while True:
            raw = await asyncio.wait_for(
                process.stdout.readline(),
                timeout=max(MISSION_CALL_TIMEOUT_S, record.planned_duration_s + 5.0),
            )
            if not raw:
                stderr = await _bounded_stderr(process)
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    f"mission worker exited before completion: {stderr}",
                )
            if len(raw) > MAX_PROTOCOL_BYTES:
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission worker output too large")
            message = json.loads(raw)
            if message.get("type") == "result":
                if not message.get("ok"):
                    raise CrazySwarmError(
                        ErrorCode.INVALID_COMMAND,
                        f"mission worker rejected artifact: {message.get('error')}",
                    )
                if message.get("source_sha256") != record.source_sha256:
                    raise CrazySwarmError(
                        ErrorCode.IDENTITY_MISMATCH, "mission source identity changed"
                    )
                break
            if message.get("type") != "call" or not isinstance(message.get("id"), int):
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "malformed mission request")
            try:
                result = await _dispatch_request(context, message)
                response = {"id": message["id"], "ok": True, "result": result}
            except CrazySwarmError as error:
                response = {"id": message["id"], "ok": False, "error": error.message}
                await _write_worker(process, response)
                raise
            await _write_worker(process, response)
        return_code = await asyncio.wait_for(process.wait(), timeout=1.0)
        if return_code != 0:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission worker failed")
    except (asyncio.CancelledError, TimeoutError):
        await _terminate_worker(process)
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        await _terminate_worker(process)
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "invalid mission worker protocol"
        ) from error
    finally:
        await _terminate_worker(process)


async def execute_isolated_mission(record: MissionFileRecord) -> tuple[ScriptStep, ...]:
    """Compatibility validator for Tier A tests; production execution is online."""

    role_id = record.roles[0].role_id if record.roles else "primary"
    steps = await preview_isolated_mission_role(record, role_id)
    if steps != record.steps:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission worker output does not match the validated artifact",
        )
    return steps


async def preview_isolated_mission_role(
    record: MissionFileRecord,
    role_id: str,
) -> tuple[ScriptStep, ...]:
    """Record the deterministic command branch for one declared mission role."""

    process = await _start_worker(record, mode="record", role_id=role_id)
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=MISSION_WORKER_TIMEOUT_S,
        )
    except TimeoutError as error:
        await _terminate_worker(process)
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission worker timed out") from error
    finally:
        if process.returncode is not None:
            _cleanup_worker_directory(process)
    try:
        response = json.loads(stdout)
        if process.returncode != 0 or not response.get("ok"):
            detail = str(response.get("error") or stderr.decode(errors="replace"))
            raise ValueError(detail)
        steps = tuple(
            ScriptStep(
                action=item["action"],
                arguments=_validate_arguments(item["action"], dict(item["arguments"])),
            )
            for item in response["steps"]
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            f"mission worker rejected artifact: {error}",
        ) from error
    if response.get("source_sha256") != record.source_sha256:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission preview output does not match the validated artifact",
        )
    if len(steps) > record.planned_command_budget:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission preview exceeded the validated command budget",
        )
    return steps


async def _start_worker(
    record: MissionFileRecord,
    *,
    mode: Literal["online", "record"],
    role_id: str,
) -> asyncio.subprocess.Process:
    worker = Path(__file__).with_name("_mission_worker.py")
    temporary_directory = tempfile.mkdtemp(prefix="crazyswarm-mission-")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(worker),
        cwd=temporary_directory,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=MAX_PROTOCOL_BYTES,
    )
    if process.pid is not None:
        _WORKER_DIRECTORIES[process.pid] = temporary_directory
    request = {
        "mode": mode,
        "source": record.source,
        "source_sha256": record.source_sha256,
        "language_version": record.language_version,
        "command_budget": record.planned_command_budget,
        "observation_budget": record.planned_observation_budget,
        "role_id": role_id,
    }
    await _write_worker(process, request)
    return process


async def _write_worker(process: asyncio.subprocess.Process, value: dict[str, Any]) -> None:
    if process.stdin is None:
        raise CrazySwarmError(ErrorCode.INTERNAL_ERROR, "mission worker stdin unavailable")
    encoded = json.dumps(value, separators=(",", ":")).encode() + b"\n"
    if len(encoded) > MAX_PROTOCOL_BYTES:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission protocol message too large")
    process.stdin.write(encoded)
    await process.stdin.drain()


async def _terminate_worker(process: asyncio.subprocess.Process) -> None:
    if process.stdin is not None:
        process.stdin.close()
    if process.returncode is None:
        process.terminate()
        with suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=0.5)
    if process.returncode is None:
        process.kill()
        await process.wait()
    _cleanup_worker_directory(process)


def _cleanup_worker_directory(process: asyncio.subprocess.Process) -> None:
    if process.pid is None:
        return
    directory = _WORKER_DIRECTORIES.pop(process.pid, None)
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)


async def _bounded_stderr(process: asyncio.subprocess.Process) -> str:
    if process.stderr is None:
        return ""
    return (await process.stderr.read(MAX_PROTOCOL_BYTES)).decode(errors="replace")


async def _dispatch_request(context: MissionContext, message: dict[str, Any]) -> Any:
    action = str(message["action"])
    arguments = _validate_arguments(action, dict(message.get("arguments") or {}))
    if action == "takeoff":
        await context.takeoff(
            height_m=float(arguments["height_m"]),
            duration_s=float(arguments["duration_s"]),
        )
    elif action == "hover":
        await context.hover(float(arguments["duration_s"]))
    elif action == "move_relative":
        await context.move_relative(
            MoveRelativeCommand(
                x_m=float(arguments.get("x_m", 0.0)),
                y_m=float(arguments.get("y_m", 0.0)),
                z_m=float(arguments.get("z_m", 0.0)),
                yaw_rad=float(arguments.get("yaw_rad", 0.0)),
                duration_s=float(arguments["duration_s"]),
                frame=CoordinateFrame(str(arguments.get("frame", "home"))),
            )
        )
    elif action == "land":
        await context.land(duration_s=float(arguments["duration_s"]))
    elif action == "wait":
        await context.wait(duration_s=float(arguments["duration_s"]))
    elif action == "checkpoint":
        await context.async_checkpoint()
    elif action == "observe":
        observation = await context.observe(timeout_s=float(arguments.get("timeout_s", 0.5)))
        _require_observation(observation, str(arguments.get("required", "position")))
        return observation.model_dump(mode="json")
    else:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"unsupported mission command: {action}")
    return None


def _require_observation(observation: MissionObservation, required: str) -> None:
    if required == "none":
        return
    if not observation.valid or observation.frame is not CoordinateFrame.HOME:
        raise CrazySwarmError(ErrorCode.LOCALIZATION_INVALID, "required position is unavailable")
    if required == "position":
        return
    if not required.endswith("_range"):
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "unknown observation requirement")
    direction = required.removesuffix("_range")
    ranges = observation.ranges
    value = None if ranges is None else getattr(ranges, f"{direction}_m", None)
    status = None if ranges is None else ranges.statuses.get(direction)
    if value is None or status in {RangeStatus.STALE, RangeStatus.UNAVAILABLE}:
        raise CrazySwarmError(ErrorCode.TELEMETRY_STALE, f"required {direction} range unavailable")


def parse_python_mission(*, filename: str, name: str, source: str) -> MissionFileRecord:
    clean_filename = Path(filename).name
    clean_name = name.strip()
    if not clean_filename.endswith(".py"):
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission file must use .py")
    if not clean_name or len(clean_name) > 120:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission name is required")
    encoded = source.encode("utf-8")
    if not encoded or len(encoded) > MAX_SOURCE_BYTES:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission file is empty or too large")
    try:
        tree = ast.parse(source, filename=clean_filename)
    except SyntaxError as error:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, f"invalid Python at line {error.lineno}"
        ) from error
    function = _mission_function(tree)
    package = _mission_package(tree)
    direct = _direct_steps(function)
    if direct is not None:
        tier = MissionTier.LINEAR
        steps = direct
        command_budget = len(steps)
        observation_budget = 0
        duration = sum(float(step.arguments.get("duration_s", 0.0)) for step in steps)
    else:
        _require_awaited_drone_calls(tree)
        _BoundedMissionValidator().visit(function)
        _require_lifecycle(function)
        steps = tuple(_all_steps(function))
        command_budget, observation_budget, duration = _estimate_block(function.body)
        tier = MissionTier.BOUNDED_OBSERVATION
    if command_budget > MAX_COMMAND_BUDGET or observation_budget > MAX_OBSERVATION_BUDGET:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission static budget exceeded")
    if duration > 300.0:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission duration budget exceeded")
    source_sha256 = hashlib.sha256(encoded).hexdigest()
    return MissionFileRecord(
        mission_id=f"py-{source_sha256[:20]}",
        name=clean_name,
        filename=clean_filename,
        source_sha256=source_sha256,
        source=source,
        tier=tier,
        steps=steps,
        planned_command_budget=command_budget,
        planned_observation_budget=observation_budget,
        planned_duration_s=duration,
        requires_range=".ranges" in source,
        package_schema_version=2 if package is not None else 1,
        roles=package.roles if package is not None else (),
        package=package,
    )


def _mission_function(tree: ast.Module) -> ast.AsyncFunctionDef:
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
    other_nodes = [
        node
        for node in tree.body
        if not isinstance(node, ast.AsyncFunctionDef)
        and not _is_mission_declaration(node)
        and not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    if other_nodes or len(functions) != 1 or functions[0].name != "mission":
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "file must contain only async def mission(drone), plus an optional MISSION declaration",
        )
    function = functions[0]
    if function.decorator_list or function.args.vararg or function.args.kwarg:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "mission decorators and variable arguments are not allowed"
        )
    if [argument.arg for argument in function.args.args] != ["drone"]:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "mission must accept exactly one drone argument"
        )
    return function


def _is_mission_declaration(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "MISSION"
    )


def _mission_package(tree: ast.Module) -> MissionPackageV2 | None:
    declarations = [node for node in tree.body if _is_mission_declaration(node)]
    if not declarations:
        return None
    if len(declarations) != 1:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "MISSION must be declared exactly once")
    declaration = cast(ast.Assign, declarations[0])
    try:
        raw = ast.literal_eval(declaration.value)
        if not isinstance(raw, dict) or raw.get("schema_version") != 2:
            raise ValueError("MISSION schema_version must be 2")
        raw_roles = raw.get("roles")
        if not isinstance(raw_roles, dict):
            raise ValueError("MISSION roles must be a mapping")
        roles = tuple(
            MissionRoleSpec.model_validate({"role_id": role_id, **definition})
            for role_id, definition in sorted(raw_roles.items())
            if isinstance(role_id, str) and isinstance(definition, dict)
        )
        if len(roles) != len(raw_roles):
            raise ValueError("MISSION role definitions must be literal mappings")
        payload = {key: value for key, value in raw.items() if key != "roles"}
        return MissionPackageV2.model_validate({**payload, "roles": roles})
    except (TypeError, ValueError) as error:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            f"invalid MISSION package: {error}",
        ) from error


def _require_awaited_drone_calls(tree: ast.Module) -> None:
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "drone"
        ):
            continue
        if not isinstance(parents.get(node), ast.Await):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "every drone operation must be awaited",
            )


def _direct_steps(function: ast.AsyncFunctionDef) -> tuple[ScriptStep, ...] | None:
    steps: list[ScriptStep] = []
    try:
        for statement in function.body:
            steps.append(_parse_direct_step(statement, actions=TIER_A_ACTIONS))
    except CrazySwarmError:
        return None
    result = tuple(steps)
    if len(result) < 2 or result[0].action != "takeoff" or result[-1].action != "land":
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "mission must start with takeoff and end with land"
        )
    if (
        sum(step.action == "takeoff" for step in result) != 1
        or sum(step.action == "land" for step in result) != 1
    ):
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "mission requires one takeoff and one landing"
        )
    return result


def _parse_direct_step(statement: ast.stmt, *, actions: frozenset[str]) -> ScriptStep:
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Await):
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "mission body contains online control flow"
        )
    call = statement.value.value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission command must call drone.<action>")
    if not isinstance(call.func.value, ast.Name) or call.func.value.id != "drone":
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission commands must target drone")
    action = call.func.attr
    if action not in actions or call.args:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"unsupported mission command: {action}")
    arguments = _literal_keywords(call)
    return ScriptStep(action=action, arguments=_validate_arguments(action, arguments))


def _literal_keywords(call: ast.Call) -> dict[str, float | str]:
    arguments: dict[str, float | str] = {}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg in arguments:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "mission command keywords must be unique"
            )
        value_node = keyword.value
        sign = 1.0
        if isinstance(value_node, ast.UnaryOp) and isinstance(value_node.op, ast.USub):
            value_node = value_node.operand
            sign = -1.0
        if not isinstance(value_node, ast.Constant) or isinstance(value_node.value, bool):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "mission command values must be literals"
            )
        value = value_node.value
        if not isinstance(value, (int, float, str)):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "mission command values must be literals"
            )
        arguments[keyword.arg] = sign * float(value) if isinstance(value, (int, float)) else value
    return arguments


def _validate_arguments(action: str, values: dict[str, Any]) -> dict[str, float | str]:
    try:
        if action == "takeoff":
            if set(values) != {"height_m", "duration_s"}:
                raise ValueError
            height = float(values["height_m"])
            duration = float(values["duration_s"])
            if not 0.0 < height <= 1.0 or not 0.0 < duration <= 30.0:
                raise ValueError
            return {"height_m": height, "duration_s": duration}
        if action in {"hover", "wait", "land"}:
            maximum = 300.0 if action in {"hover", "wait"} else 30.0
            if set(values) != {"duration_s"} or not 0.0 < float(values["duration_s"]) <= maximum:
                raise ValueError
            return {"duration_s": float(values["duration_s"])}
        if action == "move_relative":
            allowed = {"x_m", "y_m", "z_m", "yaw_rad", "duration_s", "frame"}
            if not set(values).issubset(allowed) or "duration_s" not in values:
                raise ValueError
            command = MoveRelativeCommand.model_validate(values)
            return {
                "x_m": command.x_m,
                "y_m": command.y_m,
                "z_m": command.z_m,
                "yaw_rad": command.yaw_rad,
                "duration_s": command.duration_s,
                "frame": command.frame.value,
            }
        if action == "observe":
            if not set(values).issubset({"timeout_s", "required"}):
                raise ValueError
            timeout = float(values.get("timeout_s", 0.5))
            required = str(values.get("required", "position"))
            if not 0.0 < timeout <= 5.0:
                raise ValueError
            return {"timeout_s": timeout, "required": required}
        if action == "checkpoint":
            if values:
                raise ValueError
            return {}
        raise ValueError
    except (TypeError, ValueError) as error:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, f"invalid arguments for {action}"
        ) from error


_ALLOWED_NODES = (
    ast.Module,
    ast.AsyncFunctionDef,
    ast.arguments,
    ast.arg,
    ast.Expr,
    ast.Await,
    ast.Call,
    ast.Attribute,
    ast.Name,
    ast.Constant,
    ast.keyword,
    ast.Assign,
    ast.If,
    ast.For,
    ast.While,
    ast.Compare,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.Load,
    ast.Store,
    ast.And,
    ast.Or,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.USub,
    ast.Not,
)


class _BoundedMissionValidator(ast.NodeVisitor):
    def __init__(self) -> None:
        self._integer_constants: dict[str, int] = {}

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, _ALLOWED_NODES):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                f"unsupported bounded mission syntax: {type(node).__name__}",
            )
        super().generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "private/reflection access is forbidden"
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "mission assignment must target one name"
            )
        if node.targets[0].id == "drone":
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission cannot replace drone")
        target = node.targets[0].id
        if (
            isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
            and not isinstance(node.value.value, bool)
            and 0 <= node.value.value <= MAX_LOOP_ITERATIONS
        ):
            self._integer_constants[target] = node.value.value
        else:
            self._integer_constants.pop(target, None)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "range":
            if len(node.keywords) != 0:
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "range keywords are not allowed")
            return self.generic_visit(node)
        if node.args:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "mission calls require keyword arguments"
            )
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "drone"
            and node.func.attr in TIER_B_ACTIONS
        ):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "direct adapter or host calls are forbidden"
            )
        _validate_arguments(node.func.attr, _literal_keywords(node))
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if not isinstance(node.target, ast.Name) or node.orelse:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "mission for loop must be simple and bounded"
            )
        if not (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
            and len(node.iter.args) == 1
            and isinstance(node.iter.args[0], ast.Constant)
            and isinstance(node.iter.args[0].value, int)
            and 0 <= node.iter.args[0].value <= MAX_LOOP_ITERATIONS
        ):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "mission loop requires literal bounded range"
            )
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        counter, limit, inclusive = _bounded_while_condition(node)
        initial = self._integer_constants.get(counter)
        maximum_iterations = (
            limit - initial + (1 if inclusive else 0) if initial is not None else -1
        )
        if initial is None or not 0 <= maximum_iterations <= MAX_LOOP_ITERATIONS:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "mission while loop requires a preceding bounded integer counter",
            )
        if node.orelse or any(isinstance(item, ast.Continue) for item in ast.walk(node)):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "bounded mission while loops cannot use else or continue",
            )
        if not node.body or not _is_counter_increment(node.body[-1], counter):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "bounded mission while loop must end by incrementing its counter",
            )
        assignments = [
            item
            for statement in node.body
            for item in ast.walk(statement)
            if isinstance(item, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == counter for target in item.targets
            )
        ]
        if assignments != [node.body[-1]]:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "bounded mission while counter can only change in its final increment",
            )
        self.generic_visit(node)


def _require_lifecycle(function: ast.AsyncFunctionDef) -> None:
    if len(function.body) < 2:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "mission must start with takeoff and end with land"
        )
    first = _parse_direct_step(function.body[0], actions=TIER_B_ACTIONS)
    last = _parse_direct_step(function.body[-1], actions=TIER_B_ACTIONS)
    if first.action != "takeoff" or last.action != "land":
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "mission must start with takeoff and end with land"
        )
    calls = [
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "drone"
    ]
    if calls.count("takeoff") != 1 or calls.count("land") != 1:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "mission requires one takeoff and one landing"
        )


def _all_steps(function: ast.AsyncFunctionDef) -> list[ScriptStep]:
    located: list[tuple[int, int, ScriptStep]] = []
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "drone"
            and node.func.attr in TIER_B_ACTIONS
        ):
            located.append(
                (
                    node.lineno,
                    node.col_offset,
                    ScriptStep(
                        action=node.func.attr,
                        arguments=_validate_arguments(node.func.attr, _literal_keywords(node)),
                    ),
                )
            )
    return [item[2] for item in sorted(located)]


def _estimate_block(statements: list[ast.stmt]) -> tuple[int, int, float]:
    commands = observations = 0
    duration = 0.0
    for statement in statements:
        if isinstance(statement, ast.For):
            iteration_call = cast(ast.Call, statement.iter)
            iteration_argument = cast(ast.Constant, iteration_call.args[0])
            iterations = cast(int, iteration_argument.value)
            child = _estimate_block(statement.body)
            commands += iterations * child[0]
            observations += iterations * child[1]
            duration += iterations * child[2]
        elif isinstance(statement, ast.While):
            _, limit, inclusive = _bounded_while_condition(statement)
            iterations = limit + (1 if inclusive else 0)
            child = _estimate_block(statement.body)
            commands += iterations * child[0]
            observations += iterations * child[1]
            duration += iterations * child[2]
        elif isinstance(statement, ast.If):
            body = _estimate_block(statement.body)
            alternate = _estimate_block(statement.orelse)
            selected = max((body, alternate), key=lambda item: (item[0], item[1], item[2]))
            commands += selected[0]
            observations += selected[1]
            duration += max(body[2], alternate[2])
        else:
            calls = [
                node
                for node in ast.walk(statement)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "drone"
            ]
            for call in calls:
                action = cast(ast.Attribute, call.func).attr
                arguments = _validate_arguments(action, _literal_keywords(call))
                if action == "observe":
                    observations += 1
                elif action != "checkpoint":
                    commands += 1
                    duration += float(arguments.get("duration_s", 0.0))
    return commands, observations, duration


def _bounded_while_condition(node: ast.While) -> tuple[str, int, bool]:
    test = node.test
    if not (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and len(test.ops) == 1
        and isinstance(test.ops[0], (ast.Lt, ast.LtE))
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and isinstance(test.comparators[0].value, int)
        and not isinstance(test.comparators[0].value, bool)
        and 0 <= test.comparators[0].value <= MAX_LOOP_ITERATIONS
    ):
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission while loop requires counter < literal bound",
        )
    return (
        test.left.id,
        test.comparators[0].value,
        isinstance(test.ops[0], ast.LtE),
    )


def _is_counter_increment(statement: ast.stmt, counter: str) -> bool:
    return (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == counter
        and isinstance(statement.value, ast.BinOp)
        and isinstance(statement.value.op, ast.Add)
        and isinstance(statement.value.left, ast.Name)
        and statement.value.left.id == counter
        and isinstance(statement.value.right, ast.Constant)
        and statement.value.right.value == 1
    )
