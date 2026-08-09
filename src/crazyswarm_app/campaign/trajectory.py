from __future__ import annotations

import math
from functools import lru_cache
from itertools import pairwise
from typing import Any, Literal, TypeAlias, cast

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import CampaignCase
from crazyswarm_app.campaign.planner import CandidateEvaluation, CandidateRoute
from crazyswarm_app.domain.models import ContractModel, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import (
    TimeParameterizedTrajectory,
    TrajectoryPoint,
    sample_trajectory,
)


class TrajectoryDynamicsAudit(ContractModel):
    trajectory_sha256: SHA256
    c2_continuous: bool
    sample_step_s: float = Field(gt=0.0)
    maximum_speed_m_s: float = Field(ge=0.0)
    maximum_horizontal_speed_m_s: float = Field(ge=0.0)
    maximum_vertical_speed_m_s: float = Field(ge=0.0)
    maximum_acceleration_m_s2: float = Field(ge=0.0)
    maximum_jerk_m_s3: float = Field(ge=0.0)
    generated_unintended_stop_count: int = Field(ge=0)
    passed: bool
    failures: tuple[str, ...]


class ContinuousCutoverTrajectory(ContractModel):
    """C2 replacement future whose first point may carry the measured cutover velocity."""

    schema_version: Literal[1] = 1
    trajectory_id: str
    role_id: str
    vehicle_id: str
    route_sha256: SHA256
    frame: Literal["world"] = "world"
    interpolation: Literal["QUINTIC_HERMITE_C2"] = "QUINTIC_HERMITE_C2"
    points: tuple[TrajectoryPoint, ...] = Field(min_length=2)
    completion_position_tolerance_m: float = Field(gt=0.0, le=1.0)
    completion_velocity_tolerance_m_s: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def continuous_future(self) -> ContinuousCutoverTrajectory:
        if self.points[0].time_from_start_s != 0.0:
            raise ValueError("cutover trajectory must start at source time zero")
        if tuple(point.sequence for point in self.points) != tuple(range(1, len(self.points) + 1)):
            raise ValueError("cutover trajectory sequences must be contiguous")
        if any(
            after.time_from_start_s <= before.time_from_start_s
            for before, after in pairwise(self.points)
        ):
            raise ValueError("cutover trajectory times must increase")
        if _norm(self.points[-1].velocity_m_s) > self.completion_velocity_tolerance_m_s:
            raise ValueError("replacement terminal velocity exceeds tolerance")
        return self

    @property
    def duration_s(self) -> float:
        return self.points[-1].time_from_start_s

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


AuditedTrajectory: TypeAlias = TimeParameterizedTrajectory | ContinuousCutoverTrajectory


class SmoothTrajectorySet(ContractModel):
    schema_version: Literal[1] = 1
    profile_id: Literal["fast-sim-smoothness-v1"] = "fast-sim-smoothness-v1"
    case_sha256: SHA256
    candidate_sha256: SHA256
    trajectories: tuple[TimeParameterizedTrajectory, ...]
    audits: tuple[TrajectoryDynamicsAudit, ...]
    set_sha256: SHA256

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"set_sha256"})


class LandingTransition(ContractModel):
    role_id: str
    frame: Literal["world"] = "world"
    arrival_point_m: Vector3
    descent_start_m: Vector3
    touchdown_target_m: Vector3
    goal_region_captured: bool
    commanded_position_continuous: bool
    commanded_velocity_continuous: bool
    horizontal_tolerance_m: float = Field(default=0.10, gt=0.0)
    vertical_tolerance_m: float = Field(default=0.08, gt=0.0)
    terminal_speed_tolerance_m_s: float = Field(default=0.05, ge=0.0)
    descent_authorized: bool


def generate_smooth_trajectories(
    case: CampaignCase,
    candidate: CandidateEvaluation,
    *,
    sample_step_s: float = 0.01,
) -> SmoothTrajectorySet:
    trajectories: list[TimeParameterizedTrajectory] = []
    audits: list[TrajectoryDynamicsAudit] = []
    for route in sorted(candidate.routes, key=lambda item: item.role_id):
        trajectory = _trajectory_for_route(case, route, sample_step_s)
        audit = audit_trajectory(case, trajectory, sample_step_s=sample_step_s)
        if not audit.passed:
            raise ValueError(
                f"trajectory {trajectory.trajectory_id} failed pre-execution dynamics: "
                f"{audit.failures}"
            )
        trajectories.append(trajectory)
        audits.append(audit)
    payload: dict[str, Any] = {
        "case_sha256": case.case_sha256,
        "candidate_sha256": candidate.candidate_sha256,
        "trajectories": tuple(trajectories),
        "audits": tuple(audits),
    }
    return SmoothTrajectorySet(**payload, set_sha256=canonical_sha256(payload))


def audit_trajectory(
    case: CampaignCase,
    trajectory: AuditedTrajectory,
    *,
    sample_step_s: float = 0.01,
) -> TrajectoryDynamicsAudit:
    samples = []
    timestamp = 0.0
    while timestamp <= trajectory.duration_s + sample_step_s * 0.25:
        samples.append(
            (timestamp, sample_trajectory(cast(TimeParameterizedTrajectory, trajectory), timestamp))
        )
        timestamp += sample_step_s
    speeds = [_norm(sample.velocity_m_s) for _, sample in samples]
    horizontal_speeds = [
        math.hypot(sample.velocity_m_s.x, sample.velocity_m_s.y) for _, sample in samples
    ]
    vertical_speeds = [abs(sample.velocity_m_s.z) for _, sample in samples]
    acceleration = [_norm(sample.acceleration_m_s2) for _, sample in samples]
    jerks = [
        _distance(after[1].acceleration_m_s2, before[1].acceleration_m_s2) / (after[0] - before[0])
        for before, after in pairwise(samples)
        if after[0] > before[0]
    ]
    limits = case.hard_constraints.dynamics
    failures = []
    maximum_speed = max(speeds, default=0.0)
    maximum_horizontal_speed = max(horizontal_speeds, default=0.0)
    maximum_vertical_speed = max(vertical_speeds, default=0.0)
    maximum_acceleration = max(acceleration, default=0.0)
    maximum_jerk = max(jerks, default=0.0)
    if maximum_horizontal_speed > limits.maximum_horizontal_speed_m_s + 1e-6:
        failures.append("MAXIMUM_HORIZONTAL_SPEED")
    if maximum_vertical_speed > limits.maximum_vertical_speed_m_s + 1e-6:
        failures.append("MAXIMUM_VERTICAL_SPEED")
    if maximum_acceleration > limits.maximum_acceleration_m_s2 + 1e-6:
        failures.append("MAXIMUM_ACCELERATION")
    if maximum_jerk > limits.maximum_jerk_m_s3 + 1e-6:
        failures.append("MAXIMUM_JERK")
    stops = (
        _generated_stops(trajectory, samples, case)
        if isinstance(trajectory, TimeParameterizedTrajectory)
        else 0
    )
    if stops:
        failures.append("UNINTENDED_INTERNAL_STOP")
    return TrajectoryDynamicsAudit(
        trajectory_sha256=trajectory.sha256,
        c2_continuous=True,
        sample_step_s=sample_step_s,
        maximum_speed_m_s=maximum_speed,
        maximum_horizontal_speed_m_s=maximum_horizontal_speed,
        maximum_vertical_speed_m_s=maximum_vertical_speed,
        maximum_acceleration_m_s2=maximum_acceleration,
        maximum_jerk_m_s3=maximum_jerk,
        generated_unintended_stop_count=stops,
        passed=not failures,
        failures=tuple(failures),
    )


def compile_landing_transition(
    *,
    role_id: str,
    arrival_point_m: Vector3,
    descent_start_m: Vector3,
    touchdown_target_m: Vector3,
    goal_region_captured: bool,
    arrival_velocity_m_s: Vector3 | None = None,
    descent_start_velocity_m_s: Vector3 | None = None,
) -> LandingTransition:
    arrival_velocity_m_s = arrival_velocity_m_s or Vector3()
    descent_start_velocity_m_s = descent_start_velocity_m_s or Vector3()
    position_continuous = _distance(arrival_point_m, descent_start_m) <= 1e-9
    velocity_continuous = _distance(arrival_velocity_m_s, descent_start_velocity_m_s) <= 1e-9
    return LandingTransition(
        role_id=role_id,
        arrival_point_m=arrival_point_m,
        descent_start_m=descent_start_m,
        touchdown_target_m=touchdown_target_m,
        goal_region_captured=goal_region_captured,
        commanded_position_continuous=position_continuous,
        commanded_velocity_continuous=velocity_continuous,
        descent_authorized=goal_region_captured and position_continuous and velocity_continuous,
    )


def terminal_landing_gate(
    transition: LandingTransition,
    *,
    observed_touchdown_m: Vector3,
    terminal_velocity_m_s: Vector3,
) -> tuple[bool, tuple[str, ...]]:
    horizontal = math.hypot(
        observed_touchdown_m.x - transition.touchdown_target_m.x,
        observed_touchdown_m.y - transition.touchdown_target_m.y,
    )
    vertical = abs(observed_touchdown_m.z - transition.touchdown_target_m.z)
    speed = _norm(terminal_velocity_m_s)
    failures = []
    if not transition.descent_authorized:
        failures.append("DESCENT_NOT_AUTHORIZED")
    if horizontal > transition.horizontal_tolerance_m:
        failures.append("HORIZONTAL_TOUCHDOWN_ERROR")
    if vertical > transition.vertical_tolerance_m:
        failures.append("VERTICAL_TOUCHDOWN_ERROR")
    if speed > transition.terminal_speed_tolerance_m_s:
        failures.append("TERMINAL_SPEED")
    return not failures, tuple(failures)


def _trajectory_for_route(
    case: CampaignCase, route: CandidateRoute, sample_step_s: float
) -> TimeParameterizedTrajectory:
    points = allocate_trajectory_points(case, route.points_m, speed_factor=route.speed_factor)
    if not math.isclose(points[-1].time_from_start_s, route.route_duration_s, abs_tol=1e-9):
        raise ValueError("planner route duration does not match smooth time allocation")
    return TimeParameterizedTrajectory(
        trajectory_id=f"trajectory-{canonical_sha256([route.role_id, points])[:20]}",
        role_id=route.role_id,
        vehicle_id=route.role_id,
        route_sha256=canonical_sha256(route),
        points=points,
        declared_stop_sequences=tuple(
            point.sequence
            for point in points
            if point.sequence in {1, len(points)} or _norm(point.velocity_m_s) <= 1e-9
        ),
        completion_position_tolerance_m=0.05,
        completion_velocity_tolerance_m_s=0.05,
    )


def allocate_trajectory_points(
    case: CampaignCase,
    positions: tuple[Vector3, ...],
    *,
    speed_factor: float,
    sample_step_s: float = 0.01,
) -> tuple[TrajectoryPoint, ...]:
    """Return the exact deterministic WP-30 time allocation used by planning and execution."""

    limits = case.hard_constraints.dynamics
    return _allocate_trajectory_points_cached(
        positions,
        speed_factor,
        sample_step_s,
        limits.maximum_horizontal_speed_m_s,
        limits.maximum_vertical_speed_m_s,
        limits.maximum_acceleration_m_s2,
        limits.maximum_jerk_m_s3,
    )


@lru_cache(maxsize=2_048)
def _allocate_trajectory_points_cached(
    positions: tuple[Vector3, ...],
    speed_factor: float,
    sample_step_s: float,
    maximum_horizontal_speed_m_s: float,
    maximum_vertical_speed_m_s: float,
    maximum_acceleration_m_s2: float,
    maximum_jerk_m_s3: float,
) -> tuple[TrajectoryPoint, ...]:
    """Cache immutable allocations shared by timing variants in one bounded search."""

    nominal_speed = min(0.25 * speed_factor, maximum_horizontal_speed_m_s * 0.65)
    durations = [
        max(0.5, _distance(first, second) / max(0.02, nominal_speed))
        for first, second in pairwise(positions)
    ]
    scale = 1.0
    for _ in range(12):
        points = _trajectory_points(positions, durations, scale)
        trajectory = TimeParameterizedTrajectory(
            trajectory_id=f"allocation-{canonical_sha256(points)[:20]}",
            role_id="allocation-role",
            vehicle_id="allocation-role",
            route_sha256=canonical_sha256(positions),
            points=points,
            declared_stop_sequences=tuple(
                point.sequence
                for point in points
                if point.sequence in {1, len(points)} or _norm(point.velocity_m_s) <= 1e-9
            ),
            completion_position_tolerance_m=0.05,
            completion_velocity_tolerance_m_s=0.05,
        )
        (
            maximum_horizontal_speed,
            maximum_vertical_speed,
            maximum_acceleration,
            maximum_jerk,
        ) = _sample_dynamics(trajectory, sample_step_s)
        horizontal_speed_ratio = maximum_horizontal_speed / maximum_horizontal_speed_m_s
        vertical_speed_ratio = maximum_vertical_speed / maximum_vertical_speed_m_s
        acceleration_ratio = maximum_acceleration / maximum_acceleration_m_s2
        jerk_ratio = maximum_jerk / maximum_jerk_m_s3
        if (
            horizontal_speed_ratio <= 1.0
            and vertical_speed_ratio <= 1.0
            and acceleration_ratio <= 1.0
            and jerk_ratio <= 1.0
        ):
            return points
        scale *= (
            max(
                horizontal_speed_ratio,
                vertical_speed_ratio,
                math.sqrt(acceleration_ratio),
                jerk_ratio ** (1.0 / 3.0),
                1.05,
            )
            * 1.01
        )
    raise ValueError("bounded time allocation could not satisfy acceleration/jerk limits")


def _trajectory_points(
    positions: tuple[Vector3, ...], durations: list[float], scale: float
) -> tuple[TrajectoryPoint, ...]:
    timestamps = [0.0]
    for duration in durations:
        timestamps.append(timestamps[-1] + duration * scale)
    velocities = [Vector3()]
    for index in range(1, len(positions) - 1):
        incoming = _unit(_subtract(positions[index], positions[index - 1]))
        outgoing = _unit(_subtract(positions[index + 1], positions[index]))
        direction = _unit(
            Vector3(x=incoming.x + outgoing.x, y=incoming.y + outgoing.y, z=incoming.z + outgoing.z)
        )
        incoming_speed = _distance(positions[index], positions[index - 1]) / (
            timestamps[index] - timestamps[index - 1]
        )
        outgoing_speed = _distance(positions[index + 1], positions[index]) / (
            timestamps[index + 1] - timestamps[index]
        )
        direction_alignment = (
            incoming.x * outgoing.x + incoming.y * outgoing.y + incoming.z * outgoing.z
        )
        # A sharp route-to-descent knot is an accepted goal-capture stop, not an
        # unintended stop. Smooth through ordinary route/detour knots.
        velocity = (
            0.0 if direction_alignment <= 0.30 else min(incoming_speed, outgoing_speed) * 0.75
        )
        velocities.append(
            Vector3(x=direction.x * velocity, y=direction.y * velocity, z=direction.z * velocity)
        )
    velocities.append(Vector3())
    return tuple(
        TrajectoryPoint(
            sequence=index + 1,
            time_from_start_s=timestamps[index],
            position_m=position,
            velocity_m_s=velocities[index],
            acceleration_m_s2=Vector3(),
        )
        for index, position in enumerate(positions)
    )


def _sample_dynamics(
    trajectory: TimeParameterizedTrajectory, step_s: float
) -> tuple[float, float, float, float]:
    horizontal_speeds = []
    vertical_speeds = []
    acceleration = []
    timestamp = 0.0
    while timestamp <= trajectory.duration_s + step_s * 0.25:
        sample = sample_trajectory(trajectory, timestamp)
        horizontal_speeds.append(math.hypot(sample.velocity_m_s.x, sample.velocity_m_s.y))
        vertical_speeds.append(abs(sample.velocity_m_s.z))
        acceleration.append((timestamp, sample.acceleration_m_s2))
        timestamp += step_s
    peak_acceleration = max((_norm(value) for _, value in acceleration), default=0.0)
    peak_jerk = max(
        (
            _distance(after[1], before[1]) / (after[0] - before[0])
            for before, after in pairwise(acceleration)
            if after[0] > before[0]
        ),
        default=0.0,
    )
    return (
        max(horizontal_speeds, default=0.0),
        max(vertical_speeds, default=0.0),
        peak_acceleration,
        peak_jerk,
    )


def _generated_stops(
    trajectory: TimeParameterizedTrajectory,
    samples: list[tuple[float, Any]],
    case: CampaignCase,
) -> int:
    threshold = case.hard_constraints.dynamics.stop_speed_threshold_m_s
    persistence = case.hard_constraints.dynamics.unintended_stop_persistence_s
    declared_times = {
        trajectory.points[sequence - 1].time_from_start_s
        for sequence in trajectory.declared_stop_sequences
    }
    count = 0
    start: float | None = None
    interval_has_declared_stop = False
    for timestamp, sample in samples:
        interior = 0.0 < timestamp < trajectory.duration_s
        if interior and _norm(sample.velocity_m_s) <= threshold:
            start = timestamp if start is None else start
            interval_has_declared_stop = interval_has_declared_stop or any(
                abs(timestamp - declared) <= persistence for declared in declared_times
            )
        elif start is not None:
            if timestamp - start >= persistence and not interval_has_declared_stop:
                count += 1
            start = None
            interval_has_declared_stop = False
    return count


def _subtract(first: Vector3, second: Vector3) -> Vector3:
    return Vector3(x=first.x - second.x, y=first.y - second.y, z=first.z - second.z)


def _unit(value: Vector3) -> Vector3:
    length = _norm(value)
    if length <= 1e-12:
        return Vector3()
    return Vector3(x=value.x / length, y=value.y / length, z=value.z / length)


def _norm(value: Vector3) -> float:
    return math.sqrt(value.x * value.x + value.y * value.y + value.z * value.z)


def _distance(first: Vector3, second: Vector3) -> float:
    return _norm(_subtract(first, second))
