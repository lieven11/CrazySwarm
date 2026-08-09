from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from crazyswarm_app.domain.goals import LandingGoalRegion
from crazyswarm_app.domain.models import (
    ContractModel,
    CoordinateFrame,
    Identifier,
    SourceClockPolicy,
    Vector3,
)

SHA256_PATTERN = r"^[a-f0-9]{64}$"


def _canonical_sha256(value: ContractModel) -> str:
    encoded = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _length(value: Vector3) -> float:
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


@dataclass(frozen=True, slots=True)
class TrajectorySetpoint:
    position_m: Vector3
    velocity_m_s: Vector3
    acceleration_m_s2: Vector3
    yaw_rad: float
    yaw_rate_rad_s: float


def quintic_sample(
    start: float,
    start_velocity: float,
    start_acceleration: float,
    end: float,
    end_velocity: float,
    end_acceleration: float,
    duration_s: float,
    elapsed_s: float,
) -> tuple[float, float, float]:
    """Evaluate one quintic Hermite axis with position, velocity, and acceleration."""

    a0 = start
    a1 = start_velocity
    a2 = start_acceleration / 2.0
    c0 = end - (a0 + a1 * duration_s + a2 * duration_s**2)
    c1 = end_velocity - (a1 + 2.0 * a2 * duration_s)
    c2 = end_acceleration - 2.0 * a2
    a3 = (10.0 * c0 - 4.0 * c1 * duration_s + 0.5 * c2 * duration_s**2) / (duration_s**3)
    a4 = (-15.0 * c0 + 7.0 * c1 * duration_s - c2 * duration_s**2) / (duration_s**4)
    a5 = (6.0 * c0 - 3.0 * c1 * duration_s + 0.5 * c2 * duration_s**2) / (duration_s**5)
    time_s = max(0.0, min(duration_s, elapsed_s))
    position = a0 + a1 * time_s + a2 * time_s**2 + a3 * time_s**3 + a4 * time_s**4 + a5 * time_s**5
    velocity = (
        a1 + 2.0 * a2 * time_s + 3.0 * a3 * time_s**2 + 4.0 * a4 * time_s**3 + 5.0 * a5 * time_s**4
    )
    acceleration = 2.0 * a2 + 6.0 * a3 * time_s + 12.0 * a4 * time_s**2 + 20.0 * a5 * time_s**3
    return position, velocity, acceleration


def sample_trajectory_segment(
    start: TrajectoryPoint,
    end: TrajectoryPoint,
    sample_time_s: float,
) -> TrajectorySetpoint:
    duration_s = end.time_from_start_s - start.time_from_start_s
    elapsed_s = sample_time_s - start.time_from_start_s
    axes = tuple(
        quintic_sample(
            getattr(start.position_m, axis),
            getattr(start.velocity_m_s, axis),
            getattr(start.acceleration_m_s2, axis),
            getattr(end.position_m, axis),
            getattr(end.velocity_m_s, axis),
            getattr(end.acceleration_m_s2, axis),
            duration_s,
            elapsed_s,
        )
        for axis in ("x", "y", "z")
    )
    yaw = quintic_sample(
        start.yaw_rad,
        start.yaw_rate_rad_s,
        0.0,
        end.yaw_rad,
        end.yaw_rate_rad_s,
        0.0,
        duration_s,
        elapsed_s,
    )
    return TrajectorySetpoint(
        position_m=Vector3(x=axes[0][0], y=axes[1][0], z=axes[2][0]),
        velocity_m_s=Vector3(x=axes[0][1], y=axes[1][1], z=axes[2][1]),
        acceleration_m_s2=Vector3(x=axes[0][2], y=axes[1][2], z=axes[2][2]),
        yaw_rad=yaw[0],
        yaw_rate_rad_s=yaw[1],
    )


class ExecutionClockMode(StrEnum):
    ACCELERATED = "ACCELERATED"
    REALTIME = "REALTIME"


class ExecutionClockContract(ContractModel):
    """Clock semantics shared by scheduling, supervision, and trajectory tracking."""

    source_policy: SourceClockPolicy = SourceClockPolicy.ACCELERATED_OR_REALTIME
    supported_modes: tuple[ExecutionClockMode, ...] = (
        ExecutionClockMode.ACCELERATED,
        ExecutionClockMode.REALTIME,
    )
    schedule_time_basis: Literal["SOURCE_CLOCK"] = "SOURCE_CLOCK"
    watchdog_time_basis: Literal["MONOTONIC_WALL_CLOCK"] = "MONOTONIC_WALL_CLOCK"
    blocking_completion: Literal[True] = True


class TrajectoryPoint(ContractModel):
    sequence: int = Field(ge=1)
    time_from_start_s: float = Field(ge=0.0)
    position_m: Vector3
    velocity_m_s: Vector3 = Vector3()
    acceleration_m_s2: Vector3 = Vector3()
    yaw_rad: float = 0.0
    yaw_rate_rad_s: float = 0.0

    @model_validator(mode="after")
    def finite_values(self) -> TrajectoryPoint:
        values = (
            self.time_from_start_s,
            self.position_m.x,
            self.position_m.y,
            self.position_m.z,
            self.velocity_m_s.x,
            self.velocity_m_s.y,
            self.velocity_m_s.z,
            self.acceleration_m_s2.x,
            self.acceleration_m_s2.y,
            self.acceleration_m_s2.z,
            self.yaw_rad,
            self.yaw_rate_rad_s,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("trajectory point values must be finite")
        return self


class TimeParameterizedTrajectory(ContractModel):
    """Absolute C2 trajectory accepted as ordinary backend motion authority."""

    schema_version: Literal[1] = 1
    trajectory_id: Identifier
    role_id: Identifier
    vehicle_id: Identifier
    route_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    frame: Literal[CoordinateFrame.WORLD] = CoordinateFrame.WORLD
    interpolation: Literal["QUINTIC_HERMITE_C2"] = "QUINTIC_HERMITE_C2"
    points: tuple[TrajectoryPoint, ...] = Field(min_length=2)
    declared_stop_sequences: tuple[int, ...]
    completion_position_tolerance_m: float = Field(gt=0.0, le=1.0)
    completion_velocity_tolerance_m_s: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def ordered_and_continuous(self) -> TimeParameterizedTrajectory:
        if self.points[0].time_from_start_s != 0.0:
            raise ValueError("trajectory must start at source time zero")
        expected_sequences = tuple(range(1, len(self.points) + 1))
        if tuple(point.sequence for point in self.points) != expected_sequences:
            raise ValueError("trajectory point sequences must be contiguous")
        if any(
            current.time_from_start_s <= previous.time_from_start_s
            for previous, current in zip(self.points, self.points[1:], strict=False)
        ):
            raise ValueError("trajectory timestamps must increase strictly")
        if self.declared_stop_sequences != tuple(sorted(set(self.declared_stop_sequences))):
            raise ValueError("declared stop sequences must be sorted and unique")
        if not self.declared_stop_sequences or (
            self.declared_stop_sequences[0] != 1
            or self.declared_stop_sequences[-1] != len(self.points)
        ):
            raise ValueError("trajectory start and terminal points must be declared stops")
        for sequence in self.declared_stop_sequences:
            if sequence < 1 or sequence > len(self.points):
                raise ValueError("declared trajectory stop sequence is absent")
            point = self.points[sequence - 1]
            if _length(point.velocity_m_s) > self.completion_velocity_tolerance_m_s:
                raise ValueError("declared trajectory stop has non-zero velocity")
        return self

    @property
    def duration_s(self) -> float:
        return self.points[-1].time_from_start_s

    @property
    def sha256(self) -> str:
        return _canonical_sha256(self)


def sample_trajectory(
    trajectory: TimeParameterizedTrajectory,
    sample_time_s: float,
) -> TrajectorySetpoint:
    bounded_time_s = max(0.0, min(trajectory.duration_s, sample_time_s))
    segment_index = 0
    while (
        segment_index + 1 < len(trajectory.points) - 1
        and bounded_time_s > trajectory.points[segment_index + 1].time_from_start_s
    ):
        segment_index += 1
    return sample_trajectory_segment(
        trajectory.points[segment_index],
        trajectory.points[segment_index + 1],
        bounded_time_s,
    )


class TakeoffExecutionOperation(ContractModel):
    kind: Literal["takeoff"] = "takeoff"
    sequence: int = Field(ge=1)
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(gt=0.0)
    target_height_m: float = Field(gt=0.0)


class GroundWaitExecutionOperation(ContractModel):
    """A source-clock delay that grants no arm or flight command authority."""

    kind: Literal["ground_wait"] = "ground_wait"
    sequence: int = Field(ge=1)
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(gt=0.0)
    readiness_revalidation_required: Literal[True] = True


class HoldExecutionOperation(ContractModel):
    kind: Literal["hold"] = "hold"
    sequence: int = Field(ge=1)
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(gt=0.0)
    declared: Literal[True] = True


class TrajectoryExecutionOperation(ContractModel):
    kind: Literal["trajectory"] = "trajectory"
    sequence: int = Field(ge=1)
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(gt=0.0)
    trajectory_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    trajectory: TimeParameterizedTrajectory

    @model_validator(mode="after")
    def identity_matches(self) -> TrajectoryExecutionOperation:
        if self.trajectory_sha256 != self.trajectory.sha256:
            raise ValueError("trajectory operation hash does not match its payload")
        if not math.isclose(
            self.ends_at_s - self.starts_at_s,
            self.trajectory.duration_s,
            abs_tol=1e-9,
        ):
            raise ValueError("trajectory operation duration does not match its payload")
        return self


class LandExecutionOperation(ContractModel):
    kind: Literal["land"] = "land"
    sequence: int = Field(ge=1)
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(gt=0.0)
    target_height_m: float = Field(ge=0.0)
    goal_region: LandingGoalRegion | None = None

    @model_validator(mode="after")
    def goal_matches_descent(self) -> LandExecutionOperation:
        if self.goal_region is not None and not math.isclose(
            self.goal_region.landing_target_m.z,
            self.target_height_m,
            abs_tol=1e-9,
        ):
            raise ValueError("landing operation target contradicts its goal region")
        return self


ExecutionOperation: TypeAlias = Annotated[
    TakeoffExecutionOperation
    | GroundWaitExecutionOperation
    | HoldExecutionOperation
    | TrajectoryExecutionOperation
    | LandExecutionOperation,
    Field(discriminator="kind"),
]


class AcceptedExecutionProgram(ContractModel):
    """Static role program bound into an accepted mission plan."""

    schema_version: Literal[1] = 1
    program_id: Identifier
    mission_source_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    role_id: Identifier
    vehicle_id: Identifier
    operations: tuple[ExecutionOperation, ...] = Field(min_length=1)
    route_sha256s: tuple[Annotated[str, Field(pattern=SHA256_PATTERN)], ...] = ()
    schedule_duration_s: float = Field(gt=0.0)
    contingency_reserve_s: float = Field(ge=0.0)
    recovery_reserve_s: float = Field(ge=0.0)
    execution_timeout_s: float = Field(gt=0.0)
    clock: ExecutionClockContract = ExecutionClockContract()

    @model_validator(mode="after")
    def coherent_schedule(self) -> AcceptedExecutionProgram:
        if tuple(operation.sequence for operation in self.operations) != tuple(
            range(1, len(self.operations) + 1)
        ):
            raise ValueError("execution operation sequences must be contiguous")
        if self.operations[0].starts_at_s != 0.0:
            raise ValueError("execution program must begin at zero")
        for previous, current in zip(self.operations, self.operations[1:], strict=False):
            if not math.isclose(previous.ends_at_s, current.starts_at_s, abs_tol=1e-9):
                raise ValueError("execution operations must form one continuous schedule")
        if not math.isclose(self.operations[-1].ends_at_s, self.schedule_duration_s, abs_tol=1e-9):
            raise ValueError("execution program duration contradicts its operations")
        expected_timeout = (
            self.schedule_duration_s + self.contingency_reserve_s + self.recovery_reserve_s
        )
        if not math.isclose(self.execution_timeout_s, expected_timeout, abs_tol=1e-9):
            raise ValueError("execution timeout contradicts declared schedule reserves")
        trajectories = tuple(
            operation
            for operation in self.operations
            if isinstance(operation, TrajectoryExecutionOperation)
        )
        if self.route_sha256s != tuple(item.trajectory.route_sha256 for item in trajectories):
            raise ValueError("execution program route identities do not match its trajectories")
        if any(
            item.trajectory.role_id != self.role_id or item.trajectory.vehicle_id != self.vehicle_id
            for item in trajectories
        ):
            raise ValueError("trajectory role or vehicle identity does not match its program")
        return self

    @property
    def trajectory_sha256s(self) -> tuple[str, ...]:
        return tuple(
            operation.trajectory_sha256
            for operation in self.operations
            if isinstance(operation, TrajectoryExecutionOperation)
        )

    @property
    def sha256(self) -> str:
        return _canonical_sha256(self)
