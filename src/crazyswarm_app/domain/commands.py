from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import (
    CommandSource,
    ContractModel,
    CoordinateFrame,
    Identifier,
    NonNegativeSeconds,
    OperatingMode,
)
from crazyswarm_app.domain.trajectory import SHA256_PATTERN, TimeParameterizedTrajectory


class CommandKind(StrEnum):
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    ARM = "arm"
    DISARM = "disarm"
    TAKEOFF = "takeoff"
    HOVER = "hover"
    MOVE_RELATIVE = "move_relative"
    EXECUTE_TRAJECTORY = "execute_trajectory"
    STOP_AND_HOLD = "stop_and_hold"
    LAND = "land"
    ABORT = "abort"
    EMERGENCY_STOP = "emergency_stop"


class ConnectCommand(ContractModel):
    kind: Literal[CommandKind.CONNECT] = CommandKind.CONNECT


class DisconnectCommand(ContractModel):
    kind: Literal[CommandKind.DISCONNECT] = CommandKind.DISCONNECT


class ArmCommand(ContractModel):
    kind: Literal[CommandKind.ARM] = CommandKind.ARM


class DisarmCommand(ContractModel):
    kind: Literal[CommandKind.DISARM] = CommandKind.DISARM


class TakeoffCommand(ContractModel):
    kind: Literal[CommandKind.TAKEOFF] = CommandKind.TAKEOFF
    height_m: Annotated[float, Field(gt=0.0)]
    duration_s: Annotated[float, Field(gt=0.0)] = 2.0
    yaw_rad: float | None = None


class HoverCommand(ContractModel):
    kind: Literal[CommandKind.HOVER] = CommandKind.HOVER
    duration_s: Annotated[float, Field(gt=0.0)]


class MoveRelativeCommand(ContractModel):
    kind: Literal[CommandKind.MOVE_RELATIVE] = CommandKind.MOVE_RELATIVE
    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    yaw_rad: float = 0.0
    duration_s: Annotated[float, Field(gt=0.0)] = 1.0
    frame: CoordinateFrame = CoordinateFrame.HOME

    @model_validator(mode="after")
    def require_motion(self) -> MoveRelativeCommand:
        if self.x_m == self.y_m == self.z_m == self.yaw_rad == 0.0:
            raise ValueError("relative move must change position or yaw")
        if self.frame not in {CoordinateFrame.HOME, CoordinateFrame.BODY}:
            raise ValueError("relative movement requires home or body frame")
        return self


class ExecuteTrajectoryCommand(ContractModel):
    kind: Literal[CommandKind.EXECUTE_TRAJECTORY] = CommandKind.EXECUTE_TRAJECTORY
    accepted_plan_id: Identifier
    accepted_plan_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    execution_program_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    trajectory_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    route_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    trajectory: TimeParameterizedTrajectory

    @model_validator(mode="after")
    def identities_match_payload(self) -> ExecuteTrajectoryCommand:
        if self.trajectory_sha256 != self.trajectory.sha256:
            raise ValueError("trajectory command hash does not match its payload")
        if self.route_sha256 != self.trajectory.route_sha256:
            raise ValueError("trajectory command route hash does not match its payload")
        return self


class StopAndHoldCommand(ContractModel):
    kind: Literal[CommandKind.STOP_AND_HOLD] = CommandKind.STOP_AND_HOLD


class LandCommand(ContractModel):
    kind: Literal[CommandKind.LAND] = CommandKind.LAND
    target_height_m: Annotated[float, Field(ge=0.0)] = 0.0
    duration_s: Annotated[float, Field(gt=0.0)] = 2.0


class AbortCommand(ContractModel):
    kind: Literal[CommandKind.ABORT] = CommandKind.ABORT
    reason: str = Field(min_length=1, max_length=500)


class EmergencyStopCommand(ContractModel):
    kind: Literal[CommandKind.EMERGENCY_STOP] = CommandKind.EMERGENCY_STOP
    reason: str = Field(min_length=1, max_length=500)


CommandPayload: TypeAlias = Annotated[
    ConnectCommand
    | DisconnectCommand
    | ArmCommand
    | DisarmCommand
    | TakeoffCommand
    | HoverCommand
    | MoveRelativeCommand
    | ExecuteTrajectoryCommand
    | StopAndHoldCommand
    | LandCommand
    | AbortCommand
    | EmergencyStopCommand,
    Field(discriminator="kind"),
]


class FleetCommandBinding(ContractModel):
    """Immutable fleet/task ownership attached to every coordinated command."""

    schema_version: Literal[1] = 1
    fleet_session_id: Identifier
    fleet_run_id: Identifier
    deployment_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    task_id: Identifier
    task_lease_generation: int = Field(ge=1)
    backend_namespace: str = Field(min_length=1, max_length=500)
    preparation_state: Literal["READY"] = "READY"


class CommandEnvelope(ContractModel):
    schema_version: Literal[1] = 1
    vehicle_id: Identifier
    command_id: Identifier
    mission_run_id: Identifier | None = None
    fleet: FleetCommandBinding | None = None
    issued_at_monotonic_s: NonNegativeSeconds
    issued_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: CommandSource
    mode: OperatingMode
    payload: CommandPayload

    @model_validator(mode="after")
    def replay_cannot_command(self) -> CommandEnvelope:
        if self.mode is OperatingMode.REPLAY:
            raise ValueError("REPLAY mode cannot contain vehicle commands")
        return self


class AcknowledgementStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


class CommandAcknowledgement(ContractModel):
    schema_version: Literal[1] = 1
    vehicle_id: Identifier
    command_id: Identifier
    status: AcknowledgementStatus
    received_at_monotonic_s: NonNegativeSeconds
    completed_at_monotonic_s: NonNegativeSeconds | None = None
    reason_code: str | None = None
    message: str | None = None

    @model_validator(mode="after")
    def completion_is_ordered_and_explicit(self) -> CommandAcknowledgement:
        if self.status is AcknowledgementStatus.COMPLETED and self.completed_at_monotonic_s is None:
            raise ValueError("completed acknowledgements require a completion timestamp")
        if (
            self.completed_at_monotonic_s is not None
            and self.completed_at_monotonic_s < self.received_at_monotonic_s
        ):
            raise ValueError("command completion cannot precede receipt")
        if (
            self.status
            in {
                AcknowledgementStatus.REJECTED,
                AcknowledgementStatus.TIMED_OUT,
                AcknowledgementStatus.UNKNOWN_OUTCOME,
            }
            and not self.reason_code
        ):
            raise ValueError("rejected and timed-out acknowledgements require a reason code")
        return self
