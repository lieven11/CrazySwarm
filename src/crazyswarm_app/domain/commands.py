from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from crazyswarm_app.domain.goals import GoalFailureAction, LandingGoalRegion
from crazyswarm_app.domain.models import (
    CommandSource,
    ContractModel,
    CoordinateFrame,
    Identifier,
    NonNegativeSeconds,
    OperatingMode,
    Vector3,
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
    BODY_RATE_THRUST = "body_rate_thrust"
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


class BodyRateThrustSetpoint(ContractModel):
    """One fixed-period body-rate and collective-thrust controller input."""

    roll_rate_deg_s: Annotated[float, Field(ge=-2_000.0, le=2_000.0)] = 0.0
    pitch_rate_deg_s: Annotated[float, Field(ge=-2_000.0, le=2_000.0)] = 0.0
    yaw_rate_deg_s: Annotated[float, Field(ge=-1_000.0, le=1_000.0)] = 0.0
    thrust_percent: Annotated[float, Field(ge=0.0, le=100.0)]


class BodyRateThrustCommand(ContractModel):
    """Finite, fully authored rate/thrust stream for the onboard rate controller.

    This command does not expose per-motor PWM. The flight-controller rate PID and
    mixer retain responsibility for converting the body-rate error and collective
    thrust into four motor outputs using measured gyro feedback.
    """

    kind: Literal[CommandKind.BODY_RATE_THRUST] = CommandKind.BODY_RATE_THRUST
    profile_id: Identifier
    sample_period_s: Annotated[float, Field(ge=0.005, le=0.02)]
    duration_s: Annotated[float, Field(gt=0.0, le=2.0)]
    max_abs_xy_displacement_m: Annotated[float, Field(gt=0.0, le=1.0)] = 0.50
    xy_reference_m: Vector3 | None = None
    setpoints: Annotated[
        tuple[BodyRateThrustSetpoint, ...],
        Field(min_length=2, max_length=400),
    ]

    @model_validator(mode="after")
    def require_bounded_complete_stream(self) -> BodyRateThrustCommand:
        expected_duration_s = len(self.setpoints) * self.sample_period_s
        if not math.isclose(self.duration_s, expected_duration_s, abs_tol=1e-9):
            raise ValueError("body-rate command duration must equal sample count times period")
        terminal = self.setpoints[-1]
        if any(
            not math.isclose(rate, 0.0, abs_tol=1e-9)
            for rate in (
                terminal.roll_rate_deg_s,
                terminal.pitch_rate_deg_s,
                terminal.yaw_rate_deg_s,
            )
        ):
            raise ValueError("body-rate command must end with a zero-rate handoff sample")
        if not any(
            abs(setpoint.roll_rate_deg_s) > 0.0
            or abs(setpoint.pitch_rate_deg_s) > 0.0
            or abs(setpoint.yaw_rate_deg_s) > 0.0
            for setpoint in self.setpoints
        ):
            raise ValueError("body-rate command must contain a nonzero rate setpoint")
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
    target_position_m: Vector3 | None = None
    goal_region: LandingGoalRegion | None = None
    duration_s: Annotated[float, Field(gt=0.0)] = 2.0

    @model_validator(mode="after")
    def target_height_agrees(self) -> LandCommand:
        if self.target_position_m is not None and not math.isclose(
            self.target_position_m.z, self.target_height_m, abs_tol=1e-9
        ):
            raise ValueError("landing position z must match target_height_m")
        if self.goal_region is not None:
            if self.target_position_m is None:
                raise ValueError("goal-bound landing requires an explicit target position")
            goal_target = self.goal_region.landing_target_m
            nominal_region_target = math.hypot(
                self.target_position_m.x - goal_target.x,
                self.target_position_m.y - goal_target.y,
            ) <= self.goal_region.horizontal_tolerance_m + 1e-12 and math.isclose(
                self.target_position_m.z,
                goal_target.z,
                abs_tol=1e-9,
            )
            diversion = self.goal_region.diversion_target_m
            exact_diversion_target = (
                self.goal_region.failure_action is GoalFailureAction.DIVERT
                and diversion is not None
                and all(
                    math.isclose(actual, expected, abs_tol=1e-9)
                    for actual, expected in zip(
                        (
                            self.target_position_m.x,
                            self.target_position_m.y,
                            self.target_position_m.z,
                        ),
                        (diversion.x, diversion.y, diversion.z),
                        strict=True,
                    )
                )
            )
            if not nominal_region_target and not exact_diversion_target:
                raise ValueError(
                    "landing command target is outside its immutable goal region and diversion"
                )
        return self


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
    | BodyRateThrustCommand
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
    received_at_source_s: NonNegativeSeconds | None = None
    completed_at_source_s: NonNegativeSeconds | None = None
    source_clock_id: Identifier | None = None
    source_clock_epoch: int | None = Field(default=None, ge=0)
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
        source_identity = (
            self.received_at_source_s,
            self.source_clock_id,
            self.source_clock_epoch,
        )
        if any(value is not None for value in source_identity) and not all(
            value is not None for value in source_identity
        ):
            raise ValueError("source command time requires a complete clock identity")
        if self.completed_at_source_s is not None and self.received_at_source_s is None:
            raise ValueError("source completion time requires a source receipt time")
        if (
            self.completed_at_source_s is not None
            and self.received_at_source_s is not None
            and self.completed_at_source_s < self.received_at_source_s
        ):
            raise ValueError("source command completion cannot precede receipt")
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


class TrajectoryReplacementPreparationReceipt(ContractModel):
    """Hash-bound Supervisor acknowledgement for a not-yet-dispatched replacement.

    Preparation validates the currently executing trajectory, the exact replacement
    command, fleet binding, certified fallback, and proposal identity.  It does not
    interrupt the old command or send the replacement to the adapter.
    """

    schema_version: Literal[1] = 1
    vehicle_id: Identifier
    role_id: Identifier
    mission_run_id: Identifier
    fleet_binding_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    proposal_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    safe_prefix_certificate_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    active_trajectory_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    replacement_trajectory_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    replacement_route_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    replacement_plan_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    replacement_authority_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    prepared_at_monotonic_s: NonNegativeSeconds
    cancellation_acknowledged: Literal[True] = True
    replacement_acknowledged: Literal[True] = True
    fallback_acknowledged: Literal[True] = True
    dispatch_started: Literal[False] = False

    @property
    def receipt_sha256(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
