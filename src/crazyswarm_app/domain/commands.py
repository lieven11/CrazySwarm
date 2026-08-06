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


class CommandKind(StrEnum):
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    ARM = "arm"
    DISARM = "disarm"
    TAKEOFF = "takeoff"
    HOVER = "hover"
    MOVE_RELATIVE = "move_relative"
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
    | StopAndHoldCommand
    | LandCommand
    | AbortCommand
    | EmergencyStopCommand,
    Field(discriminator="kind"),
]


class CommandEnvelope(ContractModel):
    schema_version: Literal[1] = 1
    vehicle_id: Identifier
    command_id: Identifier
    mission_run_id: Identifier | None = None
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
            self.status in {AcknowledgementStatus.REJECTED, AcknowledgementStatus.TIMED_OUT}
            and not self.reason_code
        ):
            raise ValueError("rejected and timed-out acknowledgements require a reason code")
        return self
