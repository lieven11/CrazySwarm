from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import CoordinateFrame, VehicleCapability
from crazyswarm_app.missions.base import Mission, MissionContext, MissionParameters
from crazyswarm_app.missions.registry import MissionRegistry

MAX_SOURCE_BYTES = 128 * 1024
ALLOWED_ACTIONS = frozenset({"takeoff", "hover", "move_relative", "land"})
MISSION_WORKER_ID = "restricted-python-dsl"
MISSION_WORKER_VERSION = "1.0.0"
MISSION_WORKER_TIMEOUT_S = 2.0
MISSION_ID_PATTERN = re.compile(r"py-[0-9a-f]{20}\Z")


class EmptyScriptParameters(MissionParameters):
    """Uploaded mission files are complete artifacts and expose no UI parameters."""


class ScriptStep(MissionParameters):
    action: Literal["takeoff", "hover", "move_relative", "land"]
    arguments: dict[str, float | str] = Field(default_factory=dict)


class MissionFileRecord(MissionParameters):
    mission_id: str
    name: str
    filename: str
    source_sha256: str
    source: str
    steps: tuple[ScriptStep, ...]
    archived: bool = False


class ScriptMission(Mission[EmptyScriptParameters]):
    parameters_type = EmptyScriptParameters
    manages_flight_path = True
    source_kind = "UPLOADED_PYTHON"
    runtime_id = MISSION_WORKER_ID
    runtime_version = MISSION_WORKER_VERSION
    required_capabilities = frozenset(
        {
            VehicleCapability.ARMING,
            VehicleCapability.RELATIVE_POSITIONING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
        }
    )

    def __init__(self, record: MissionFileRecord) -> None:
        self.record = record
        self.mission_id = record.mission_id
        self.mission_version = record.source_sha256[:12]
        self.name = record.name
        self.description = record.filename
        self.source_filename = record.filename
        self.source_sha256 = record.source_sha256
        self.planned_commands = tuple(step.model_dump(mode="json") for step in record.steps)

    async def execute(
        self,
        context: MissionContext,
        parameters: EmptyScriptParameters,
    ) -> None:
        del parameters
        steps = await execute_isolated_mission(self.record)
        for step in steps:
            arguments = step.arguments
            if step.action == "takeoff":
                await context.takeoff(
                    height_m=float(arguments["height_m"]),
                    duration_s=float(arguments["duration_s"]),
                )
            elif step.action == "hover":
                await context.hover(float(arguments["duration_s"]))
            elif step.action == "move_relative":
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
            else:
                await context.land(duration_s=float(arguments["duration_s"]))

    def execution_timeout_s(self, parameters: EmptyScriptParameters) -> float:
        del parameters
        duration = sum(float(step.arguments.get("duration_s", 0.0)) for step in self.record.steps)
        return duration + 15.0


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


async def execute_isolated_mission(record: MissionFileRecord) -> tuple[ScriptStep, ...]:
    worker = Path(__file__).with_name("_mission_worker.py")
    request = json.dumps(
        {"source": record.source, "source_sha256": record.source_sha256},
        separators=(",", ":"),
    ).encode()
    with tempfile.TemporaryDirectory(prefix="crazyswarm-mission-") as temporary_directory:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(worker),
            cwd=temporary_directory,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(request),
                timeout=MISSION_WORKER_TIMEOUT_S,
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission worker timed out") from error
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
    if steps != record.steps or response.get("source_sha256") != record.source_sha256:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission worker output does not match the validated artifact",
        )
    return steps


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
            ErrorCode.INVALID_COMMAND,
            f"invalid Python at line {error.lineno}",
        ) from error
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
    other_nodes = [
        node
        for node in tree.body
        if not isinstance(node, ast.AsyncFunctionDef)
        and not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    if other_nodes or len(functions) != 1 or functions[0].name != "mission":
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "file must contain only async def mission(drone)",
        )
    function = functions[0]
    if function.decorator_list or function.args.vararg or function.args.kwarg:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission decorators and variable arguments are not allowed",
        )
    if [argument.arg for argument in function.args.args] != ["drone"]:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission must accept exactly one drone argument",
        )
    steps = tuple(_parse_step(statement) for statement in function.body)
    if len(steps) < 2 or steps[0].action != "takeoff" or steps[-1].action != "land":
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission must start with takeoff and end with land",
        )
    takeoff_count = sum(step.action == "takeoff" for step in steps)
    landing_count = sum(step.action == "land" for step in steps)
    if takeoff_count != 1 or landing_count != 1:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission requires one takeoff and one landing",
        )
    source_sha256 = hashlib.sha256(encoded).hexdigest()
    return MissionFileRecord(
        mission_id=f"py-{source_sha256[:20]}",
        name=clean_name,
        filename=clean_filename,
        source_sha256=source_sha256,
        source=source,
        steps=steps,
    )


def _parse_step(statement: ast.stmt) -> ScriptStep:
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Await):
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            "mission body may contain only awaited drone commands",
        )
    call = statement.value.value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission command must call drone.<action>")
    if not isinstance(call.func.value, ast.Name) or call.func.value.id != "drone":
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission commands must target drone")
    action = call.func.attr
    if action not in ALLOWED_ACTIONS or call.args:
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"unsupported mission command: {action}")
    arguments: dict[str, float | str] = {}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg in arguments:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "mission command keywords must be unique",
            )
        if not isinstance(keyword.value, ast.Constant) or isinstance(keyword.value.value, bool):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "mission command values must be literal numbers or strings",
            )
        value = keyword.value.value
        if not isinstance(value, (int, float, str)):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "mission command values must be literal numbers or strings",
            )
        arguments[keyword.arg] = float(value) if isinstance(value, (int, float)) else value
    return ScriptStep(action=action, arguments=_validate_arguments(action, arguments))


def _validate_arguments(action: str, values: dict[str, float | str]) -> dict[str, float | str]:
    try:
        if action == "takeoff":
            required = {"height_m", "duration_s"}
            if set(values) != required:
                raise ValueError
            height = float(values["height_m"])
            duration = float(values["duration_s"])
            if not 0.0 < height <= 1.0 or not 0.0 < duration <= 30.0:
                raise ValueError
        elif action == "hover":
            if set(values) != {"duration_s"} or not 0.0 < float(values["duration_s"]) <= 300.0:
                raise ValueError
        elif action == "land":
            if set(values) != {"duration_s"} or not 0.0 < float(values["duration_s"]) <= 30.0:
                raise ValueError
        else:
            allowed = {"x_m", "y_m", "z_m", "yaw_rad", "duration_s", "frame"}
            if not set(values).issubset(allowed) or "duration_s" not in values:
                raise ValueError
            command = MoveRelativeCommand.model_validate(values)
            values = {
                "x_m": command.x_m,
                "y_m": command.y_m,
                "z_m": command.z_m,
                "yaw_rad": command.yaw_rad,
                "duration_s": command.duration_s,
                "frame": command.frame.value,
            }
    except (TypeError, ValueError) as error:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            f"invalid arguments for {action}",
        ) from error
    return values
