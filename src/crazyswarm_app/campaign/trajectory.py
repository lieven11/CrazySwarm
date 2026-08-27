from __future__ import annotations

import math
from functools import lru_cache
from itertools import pairwise
from typing import Any, Literal, TypeAlias, cast

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import (
    BehaviorOracleKind,
    CampaignCase,
    MotionQualityContract,
)
from crazyswarm_app.campaign.planner import CandidateEvaluation, CandidateRoute, RouteStop
from crazyswarm_app.campaign.submissions import (
    BASELINE_SUBMISSION_ID,
    CapabilityFeasibilityDisposition,
    CapabilityResolution,
    ExecutionProfileKind,
    ExecutionProfileSubmission,
    PathAdherenceMode,
    PlanningSubmission,
    motion_contract_for_execution_profile,
    normalized_route_polyline,
    resolve_capability_resolution,
    resolve_package_capability_resolution,
    resolve_submission,
)
from crazyswarm_app.domain.models import ContractModel, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import (
    TimeParameterizedTrajectory,
    TrajectoryPoint,
    sample_trajectory,
    sample_trajectory_segment,
)

PROFILED_KNOT_ACCELERATION_GAIN_SMOOTH = 2.5
PROFILED_KNOT_ACCELERATION_GAIN_BALANCED = 4.0


class TrajectoryDynamicsAudit(ContractModel):
    trajectory_sha256: SHA256
    c2_continuous: bool
    sample_step_s: float = Field(gt=0.0)
    maximum_speed_m_s: float = Field(ge=0.0)
    maximum_horizontal_speed_m_s: float = Field(ge=0.0)
    maximum_vertical_speed_m_s: float = Field(ge=0.0)
    maximum_acceleration_m_s2: float = Field(ge=0.0)
    maximum_jerk_m_s3: float = Field(ge=0.0)
    minimum_undeclared_internal_speed_m_s: float = Field(default=0.0, ge=0.0)
    generated_unintended_stop_count: int = Field(ge=0)
    passed: bool
    failures: tuple[str, ...]


class ExecutionProfileAudit(ContractModel):
    submission_id: str
    submission_sha256: SHA256
    role_id: str
    profile_kind: ExecutionProfileKind
    requested_segment_values: tuple[float, ...]
    achieved_segment_values: tuple[float, ...]
    value_unit: Literal["m/s"] = "m/s"
    safety_retiming_factor: float = Field(ge=1.0)
    maximum_fractional_error: float = Field(ge=0.0)
    steady_window_coverage_fraction: float = Field(ge=0.0, le=1.0)
    tolerance_fraction: float = Field(gt=0.0, le=0.5)
    hard_constraints_preserved: bool
    passed: bool


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
    schema_version: Literal[1, 2, 3] = 3
    profile_id: Literal["fast-sim-smoothness-v1"] = "fast-sim-smoothness-v1"
    case_sha256: SHA256
    candidate_sha256: SHA256
    motion_quality_contract: MotionQualityContract | None = None
    motion_quality_contract_sha256: SHA256 | None = None
    submission_id: str | None = None
    submission_sha256: SHA256 | None = None
    planning_submission_id: str | None = None
    planning_submission_sha256: SHA256 | None = None
    trajectories: tuple[TimeParameterizedTrajectory, ...]
    audits: tuple[TrajectoryDynamicsAudit, ...]
    profile_audits: tuple[ExecutionProfileAudit, ...] = ()
    execution_profile_fallback: Literal["PLANNER_CANDIDATE_NATIVE_TIMING"] | None = None
    set_sha256: SHA256

    @model_validator(mode="after")
    def planning_authority_is_paired(self) -> SmoothTrajectorySet:
        if (self.planning_submission_id is None) != (self.planning_submission_sha256 is None):
            raise ValueError("trajectory-set planning submission identity must be complete")
        if (self.motion_quality_contract is None) != (self.motion_quality_contract_sha256 is None):
            raise ValueError("trajectory-set motion-quality contract identity is incomplete")
        if (
            self.motion_quality_contract is not None
            and canonical_sha256(self.motion_quality_contract)
            != self.motion_quality_contract_sha256
        ):
            raise ValueError("trajectory-set motion-quality contract hash mismatch")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="python", exclude={"set_sha256"})
        payload.pop("schema_version", None)
        payload.pop("profile_id", None)
        if self.submission_id is None:
            payload.pop("submission_id", None)
            payload.pop("submission_sha256", None)
            payload.pop("profile_audits", None)
        if self.planning_submission_id is None:
            payload.pop("planning_submission_id", None)
            payload.pop("planning_submission_sha256", None)
        if self.motion_quality_contract is None:
            payload.pop("motion_quality_contract", None)
            payload.pop("motion_quality_contract_sha256", None)
        if self.execution_profile_fallback is None:
            payload.pop("execution_profile_fallback", None)
        return payload


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
    submission: ExecutionProfileSubmission | None = None,
    planning_submission: PlanningSubmission | None = None,
    capability_resolution: CapabilityResolution | None = None,
) -> SmoothTrajectorySet:
    selected_submission = submission or resolve_submission(case, None, require_executable=False)
    expected_resolution = (
        resolve_package_capability_resolution(
            case,
            planning_submission,
            selected_submission,
        )
        if planning_submission is not None
        else resolve_capability_resolution(case, selected_submission)
    )
    if capability_resolution is not None and capability_resolution != expected_resolution:
        raise ValueError("trajectory capability resolution does not match case/profile")
    selected_resolution = capability_resolution or expected_resolution
    planner_native_timing = _uses_planner_native_timing(
        case,
        selected_submission,
        selected_resolution,
    )
    trajectories: list[TimeParameterizedTrajectory] = []
    audits: list[TrajectoryDynamicsAudit] = []
    profile_audits: list[ExecutionProfileAudit] = []
    for route in sorted(candidate.routes, key=lambda item: item.role_id):
        trajectory = _trajectory_for_route(
            case,
            route,
            sample_step_s,
            selected_submission,
            selected_resolution,
            planning_submission,
        )
        audit = audit_trajectory(case, trajectory, sample_step_s=sample_step_s)
        if not audit.passed:
            raise ValueError(
                f"trajectory {trajectory.trajectory_id} failed pre-execution dynamics: "
                f"{audit.failures}"
            )
        trajectories.append(trajectory)
        audits.append(audit)
        if (
            selected_submission.submission_id != BASELINE_SUBMISSION_ID
            and not planner_native_timing
        ):
            profile_audits.append(
                _audit_execution_profile(case, route, trajectory, selected_submission, audit)
            )
    motion_contract = motion_contract_for_execution_profile(case, selected_submission)
    payload: dict[str, Any] = {
        "case_sha256": case.case_sha256,
        "candidate_sha256": candidate.candidate_sha256,
        "motion_quality_contract": motion_contract,
        "motion_quality_contract_sha256": canonical_sha256(motion_contract),
        "trajectories": tuple(trajectories),
        "audits": tuple(audits),
    }
    if selected_submission.submission_id != BASELINE_SUBMISSION_ID:
        payload.update(
            {
                "submission_id": selected_submission.submission_id,
                "submission_sha256": selected_submission.profile_sha256,
                "profile_audits": tuple(profile_audits),
            }
        )
    if planner_native_timing:
        payload["execution_profile_fallback"] = "PLANNER_CANDIDATE_NATIVE_TIMING"
    if planning_submission is not None:
        payload.update(
            {
                "planning_submission_id": planning_submission.planning_submission_id,
                "planning_submission_sha256": (planning_submission.planning_submission_sha256),
            }
        )
    return SmoothTrajectorySet(**payload, set_sha256=canonical_sha256(payload))


def _audit_execution_profile(
    case: CampaignCase,
    route: CandidateRoute,
    trajectory: TimeParameterizedTrajectory,
    submission: ExecutionProfileSubmission,
    dynamics_audit: TrajectoryDynamicsAudit,
) -> ExecutionProfileAudit:
    if not route.segment_durations_s:
        raise ValueError("profiled route has no authored segment time law")
    parameters = submission.parameters
    audit_route = route
    windows_override: tuple[tuple[float, float], ...] | None = None
    audit_segment_durations = route.segment_durations_s
    if submission.kind is ExecutionProfileKind.DURATION_SCALE:
        assert parameters.duration_scale is not None
        return ExecutionProfileAudit(
            submission_id=submission.submission_id,
            submission_sha256=submission.profile_sha256,
            role_id=route.role_id,
            profile_kind=submission.kind,
            requested_segment_values=(parameters.duration_scale,),
            achieved_segment_values=(parameters.duration_scale,),
            safety_retiming_factor=1.0,
            maximum_fractional_error=0.0,
            steady_window_coverage_fraction=1.0,
            tolerance_fraction=parameters.steady_window_tolerance_fraction,
            hard_constraints_preserved=dynamics_audit.passed,
            passed=dynamics_audit.passed,
        )
    if submission.kind is ExecutionProfileKind.CONSTANT_PATH_SPEED:
        assert parameters.target_path_speed_m_s is not None
        requested = (parameters.target_path_speed_m_s,) * len(route.segment_durations_s)
    elif submission.kind is ExecutionProfileKind.RAMPED_SEGMENT_SPEED:
        requested = parameters.segment_target_speeds_m_s
    elif submission.kind is ExecutionProfileKind.BOUNDED_VERTICAL_RATE:
        assert parameters.target_vertical_rate_m_s is not None
        requested = tuple(
            parameters.target_vertical_rate_m_s if abs(after.z - before.z) > 1e-9 else 0.0
            for before, after in pairwise(route.points_m)
        )
    elif submission.kind is ExecutionProfileKind.CORNER_TRANSITION:
        assert parameters.target_path_speed_m_s is not None
        windows_override = _corner_cut_steady_windows(trajectory)
        audit_segment_durations = tuple(after - before for before, after in windows_override)
        requested = (parameters.target_path_speed_m_s,) * len(windows_override)
    else:
        raise ValueError(f"profile {submission.kind.value} has no trajectory conformance audit")
    windows = (
        windows_override
        if windows_override is not None
        else _profile_steady_windows(
            audit_route,
            trajectory,
            requested,
            submission.kind,
            (
                parameters.lookahead_time_s
                if submission.kind is ExecutionProfileKind.CORNER_TRANSITION
                and parameters.lookahead_time_s is not None
                else parameters.entry_exit_ramp_s
            ),
        )
    )
    achieved_values: list[float] = []
    errors: list[float] = []
    covered_duration_s = 0.0
    missing_required_window = False
    for index, (requested_value, window) in enumerate(zip(requested, windows, strict=True)):
        if window is None:
            achieved_values.append(0.0)
            missing_required_window = missing_required_window or (
                requested_value > 0.0
                and audit_segment_durations[index] > 2.0 * parameters.entry_exit_ramp_s
            )
            continue
        start_s, end_s = window
        covered_duration_s += end_s - start_s
        values = []
        timestamp_s = start_s
        while timestamp_s <= end_s + 0.0025:
            sample = sample_trajectory(trajectory, timestamp_s)
            values.append(
                abs(sample.velocity_m_s.z)
                if submission.kind is ExecutionProfileKind.BOUNDED_VERTICAL_RATE
                else _norm(sample.velocity_m_s)
            )
            timestamp_s += 0.01
        achieved_values.append(sum(values) / len(values))
        if requested_value > 0.0:
            errors.extend(abs(value - requested_value) / requested_value for value in values)
    achieved = tuple(achieved_values)
    maximum_error = max(errors, default=0.0)
    tolerance = parameters.steady_window_tolerance_fraction
    movement_duration_s = trajectory.duration_s - sum(
        stop.dwell_s for stop in audit_route.declared_stops
    )
    scale = max(
        (
            1.0,
            *(
                target / actual
                for target, actual in zip(requested, achieved, strict=True)
                if target > 0.0 and actual > 0.0
            ),
        )
    )
    if submission.kind in {
        ExecutionProfileKind.CONSTANT_PATH_SPEED,
        ExecutionProfileKind.CORNER_TRANSITION,
    }:
        # A requested speed law may be uniformly safety-retimed by the bounded
        # allocator. Conformance is measured against that explicit resolved speed,
        # while the safety factor remains visible rather than pretending the
        # original target was reached. Short transition-only segments have no
        # steady window.
        retimed_errors = [
            abs(actual - requested_value / scale) / (requested_value / scale)
            for requested_value, actual in zip(requested, achieved, strict=True)
            if requested_value > 0.0 and actual > 0.0
        ]
        maximum_error = max(retimed_errors, default=0.0)
        missing_required_window = False
    coverage = min(1.0, covered_duration_s / max(movement_duration_s, 1e-9))
    if (
        submission.kind is ExecutionProfileKind.CONSTANT_PATH_SPEED
        and coverage >= 0.35
        and any(value > 0.0 for value in achieved)
    ):
        # Short authored loop-closure transitions can consume an entire segment;
        # the qualified steady interiors remain the conformance domain.
        missing_required_window = False
    return ExecutionProfileAudit(
        submission_id=submission.submission_id,
        submission_sha256=submission.profile_sha256,
        role_id=route.role_id,
        profile_kind=submission.kind,
        requested_segment_values=requested,
        achieved_segment_values=achieved,
        safety_retiming_factor=scale,
        maximum_fractional_error=maximum_error,
        steady_window_coverage_fraction=coverage,
        tolerance_fraction=tolerance,
        hard_constraints_preserved=dynamics_audit.passed,
        passed=(
            dynamics_audit.passed and not missing_required_window and maximum_error <= tolerance
        ),
    )


def _corner_cut_steady_windows(
    trajectory: TimeParameterizedTrajectory,
) -> tuple[tuple[float, float], ...]:
    """Return the straight constant-speed interiors of a corner-cut trajectory."""

    windows = []
    for start, end in pairwise(trajectory.points):
        start_speed = _norm(start.velocity_m_s)
        end_speed = _norm(end.velocity_m_s)
        displacement = _subtract(end.position_m, start.position_m)
        if start_speed <= 1e-9 or end_speed <= 1e-9 or _norm(displacement) <= 1e-9:
            continue
        start_direction = _unit(start.velocity_m_s)
        end_direction = _unit(end.velocity_m_s)
        path_direction = _unit(displacement)
        if (
            _dot(start_direction, end_direction) >= 1.0 - 1e-9
            and _dot(start_direction, path_direction) >= 1.0 - 1e-9
            and _norm(start.acceleration_m_s2) <= 1e-9
            and _norm(end.acceleration_m_s2) <= 1e-9
        ):
            windows.append((start.time_from_start_s, end.time_from_start_s))
    return tuple(windows)


def _profile_steady_windows(
    route: CandidateRoute,
    trajectory: TimeParameterizedTrajectory,
    requested: tuple[float, ...],
    profile_kind: ExecutionProfileKind,
    ramp_s: float,
) -> tuple[tuple[float, float] | None, ...]:
    """Return only intervals whose commanded profile is intended to be steady."""

    authored_times = tuple(
        next(
            point.time_from_start_s
            for point in trajectory.points
            if _distance(point.position_m, position) <= 1e-9
        )
        for position in route.points_m
    )
    windows: list[tuple[float, float] | None] = []
    for index, (before, after) in enumerate(pairwise(route.points_m)):
        if profile_kind in {
            ExecutionProfileKind.CONSTANT_PATH_SPEED,
            ExecutionProfileKind.RAMPED_SEGMENT_SPEED,
            ExecutionProfileKind.BOUNDED_VERTICAL_RATE,
            ExecutionProfileKind.CORNER_TRANSITION,
        }:
            segment = _subtract(after, before)
            length = _norm(segment)
            direction = _unit(segment)
            interior_times = tuple(
                point.time_from_start_s
                for point in trajectory.points
                if (
                    authored_times[index] < point.time_from_start_s < authored_times[index + 1]
                    and length > 1e-9
                    and 1e-9
                    < (
                        _subtract(point.position_m, before).x * direction.x
                        + _subtract(point.position_m, before).y * direction.y
                        + _subtract(point.position_m, before).z * direction.z
                    )
                    < length - 1e-9
                    and _distance(
                        point.position_m,
                        Vector3(
                            x=before.x
                            + direction.x
                            * (
                                _subtract(point.position_m, before).x * direction.x
                                + _subtract(point.position_m, before).y * direction.y
                                + _subtract(point.position_m, before).z * direction.z
                            ),
                            y=before.y
                            + direction.y
                            * (
                                _subtract(point.position_m, before).x * direction.x
                                + _subtract(point.position_m, before).y * direction.y
                                + _subtract(point.position_m, before).z * direction.z
                            ),
                            z=before.z
                            + direction.z
                            * (
                                _subtract(point.position_m, before).x * direction.x
                                + _subtract(point.position_m, before).y * direction.y
                                + _subtract(point.position_m, before).z * direction.z
                            ),
                        ),
                    )
                    <= 1e-8
                )
            )
            window = (
                (min(interior_times), max(interior_times))
                if len(interior_times) >= 2 and max(interior_times) > min(interior_times)
                else None
            )
        else:
            start_s = authored_times[index] + ramp_s
            end_s = authored_times[index + 1] - ramp_s
            window = (start_s, end_s) if end_s > start_s else None
        windows.append(window)
    return tuple(windows)


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
    declared_sequences = (
        trajectory.declared_stop_sequences
        if isinstance(trajectory, TimeParameterizedTrajectory)
        else ()
    )
    declared_times = tuple(
        trajectory.points[sequence - 1].time_from_start_s for sequence in declared_sequences
    )
    terminal_capture_start_s = trajectory.points[-2].time_from_start_s
    minimum_undeclared_internal_speed = min(
        (
            speed
            for (timestamp_s, _sample), speed in zip(samples, speeds, strict=True)
            if timestamp_s < terminal_capture_start_s
            and not any(
                abs(timestamp_s - declared_time_s)
                <= case.hard_constraints.dynamics.unintended_stop_persistence_s
                for declared_time_s in declared_times
            )
        ),
        default=0.0,
    )
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
        minimum_undeclared_internal_speed_m_s=minimum_undeclared_internal_speed,
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


def _uses_planner_native_timing(
    case: CampaignCase,
    submission: ExecutionProfileSubmission,
    capability_resolution: CapabilityResolution | None,
) -> bool:
    return bool(
        (
            case.family == "online_obstacle_replan"
            and "source_time_changed_world" in case.named_variations
        )
        or (
            submission.kind is ExecutionProfileKind.CORNER_TRANSITION
            and capability_resolution is not None
            and (
                case.drone_count > 1
                or (
                    capability_resolution.feasibility is not None
                    and capability_resolution.feasibility.disposition
                    is CapabilityFeasibilityDisposition.PROVEN_INFEASIBLE
                )
            )
        )
    )


def _trajectory_for_route(
    case: CampaignCase,
    route: CandidateRoute,
    sample_step_s: float,
    submission: ExecutionProfileSubmission,
    capability_resolution: CapabilityResolution | None,
    planning_submission: PlanningSubmission | None,
) -> TimeParameterizedTrajectory:
    corner_transition_active = (
        submission.kind is ExecutionProfileKind.CORNER_TRANSITION
        and not _uses_planner_native_timing(case, submission, capability_resolution)
    )
    planner_native_timing = _uses_planner_native_timing(
        case,
        submission,
        capability_resolution,
    )
    path_speed_targets_m_s: tuple[float, ...] = ()
    allocation_positions = route.points_m
    if not planner_native_timing and submission.kind is ExecutionProfileKind.CONSTANT_PATH_SPEED:
        assert submission.parameters.target_path_speed_m_s is not None
        path_speed_targets_m_s = (submission.parameters.target_path_speed_m_s,) * (
            len(route.points_m) - 1
        )
    elif not planner_native_timing and submission.kind is ExecutionProfileKind.RAMPED_SEGMENT_SPEED:
        path_speed_targets_m_s = submission.parameters.segment_target_speeds_m_s
    elif (
        not planner_native_timing and submission.kind is ExecutionProfileKind.BOUNDED_VERTICAL_RATE
    ):
        assert submission.parameters.target_vertical_rate_m_s is not None
        path_speed_targets_m_s = tuple(
            (
                _distance(before, after)
                / max(
                    0.01,
                    abs(after.z - before.z) / submission.parameters.target_vertical_rate_m_s,
                )
                if abs(after.z - before.z) > 1e-9
                else 0.18
            )
            for before, after in pairwise(route.points_m)
        )
    elif corner_transition_active:
        if capability_resolution is None:
            raise ValueError("corner-transition trajectory requires a capability resolution")
        certified_speed = (
            submission.parameters.certified_path_speed_m_s
            or capability_resolution.certified_entry_speed_m_s
        )
        if certified_speed is None:
            raise ValueError("corner-transition trajectory lacks a certified path speed")
        allocation_positions = normalized_route_polyline(
            case,
            route.role_id,
            route.points_m,
        ).normalized_points_m
        path_speed_targets_m_s = (certified_speed,) * (len(allocation_positions) - 1)
    points = allocate_trajectory_points(
        case,
        allocation_positions,
        speed_factor=route.speed_factor,
        declared_stops=route.declared_stops,
        segment_durations_s=(() if corner_transition_active else route.segment_durations_s),
        path_speed_targets_m_s=path_speed_targets_m_s,
        entry_exit_ramp_s=(
            submission.parameters.lookahead_time_s
            if corner_transition_active and submission.parameters.lookahead_time_s is not None
            else submission.parameters.entry_exit_ramp_s
        ),
        transition_distance_m=(
            capability_resolution.derived_lookahead_distance_m
            if capability_resolution is not None and corner_transition_active
            else None
        ),
        turn_blend_radius_m=(
            capability_resolution.derived_turn_blend_radius_m
            if capability_resolution is not None and corner_transition_active
            else None
        ),
        corner_cut_tolerance_m=(
            capability_resolution.path_deviation_cap_m
            if capability_resolution is not None
            and corner_transition_active
            and case.drone_count == 1
            else None
        ),
    )
    if not math.isclose(points[-1].time_from_start_s, route.route_duration_s, abs_tol=1e-9):
        raise ValueError("planner route duration does not match smooth time allocation")
    points = apply_planning_trajectory_envelope(
        case,
        route,
        points,
        planning_submission,
        sample_step_s=sample_step_s,
    )
    stop_sequences = set(declared_stop_sequences(route, points))
    if planning_submission is not None and planning_submission.path_adherence.mode in {
        PathAdherenceMode.HARD_TUBE,
        PathAdherenceMode.EXACT_ROUTE,
    }:
        stop_sequences.update(
            point.sequence
            for point in points[1:-1]
            if _norm(point.velocity_m_s)
            <= case.hard_constraints.dynamics.stop_speed_threshold_m_s + 1e-9
        )
    return TimeParameterizedTrajectory(
        trajectory_id=f"trajectory-{canonical_sha256([route.role_id, points])[:20]}",
        role_id=route.role_id,
        vehicle_id=route.role_id,
        route_sha256=canonical_sha256(route),
        points=points,
        declared_stop_sequences=tuple(sorted(stop_sequences)),
        completion_position_tolerance_m=0.05,
        completion_velocity_tolerance_m_s=0.05,
    )


def apply_planning_trajectory_envelope(
    case: CampaignCase,
    route: CandidateRoute,
    points: tuple[TrajectoryPoint, ...],
    planning_submission: PlanningSubmission | None,
    *,
    sample_step_s: float,
) -> tuple[TrajectoryPoint, ...]:
    """Bind trajectory interpolation to the accepted path and boundary authority.

    Candidate routes are only knot geometry.  Their Hermite tangents must not create
    an execution path that violates a hard-tube request or a required sampled
    boundary margin.  Scaling internal derivatives preserves route knots and timing
    while deterministically removing the unsafe overshoot.
    """

    if planning_submission is None:
        return points
    path_limit = (
        planning_submission.path_adherence.maximum_centerline_deviation_m
        if planning_submission.path_adherence.mode
        in {PathAdherenceMode.HARD_TUBE, PathAdherenceMode.EXACT_ROUTE}
        else None
    )
    boundary_threshold = (
        next(
            (
                float(oracle.threshold or 0.0)
                for oracle in case.semantics.behavior_oracles
                if oracle.required
                and oracle.kind is BehaviorOracleKind.BOUNDARY_MARGIN
                and (not oracle.role_ids or route.role_id in oracle.role_ids)
            ),
            None,
        )
        if case.semantics is not None
        else None
    )
    boundary_limit = (
        boundary_threshold + planning_submission.clearance.uncertainty_allowance_m
        if boundary_threshold is not None
        else None
    )
    if path_limit is None and boundary_limit is None:
        return points

    def scaled(factor: float) -> tuple[TrajectoryPoint, ...]:
        return tuple(
            point.model_copy(
                update={
                    "velocity_m_s": _scale_vector(point.velocity_m_s, factor),
                    "acceleration_m_s2": _scale_vector(point.acceleration_m_s2, factor),
                }
            )
            if 0 < index < len(points) - 1
            else point
            for index, point in enumerate(points)
        )

    def sampled_limits(
        candidate: tuple[TrajectoryPoint, ...],
    ) -> tuple[float | None, float | None]:
        sampled = _sample_points(candidate, sample_step_s)
        maximum_path_error = (
            max(
                (
                    _distance_to_segment(sample.position_m, segment_start, segment_end)
                    for sample, segment_start, segment_end in sampled
                ),
                default=float("inf"),
            )
            if path_limit is not None
            else None
        )
        minimum_boundary_margin = (
            min(
                (_lateral_ceiling_margin(sample.position_m, case) for sample, _, _ in sampled),
                default=-float("inf"),
            )
            if boundary_limit is not None
            else None
        )
        return maximum_path_error, minimum_boundary_margin

    def accepted(limits: tuple[float | None, float | None]) -> bool:
        path_error, boundary_margin = limits
        return not (
            path_limit is not None and (path_error is None or path_error > path_limit + 1e-9)
        ) and not (
            boundary_limit is not None
            and (boundary_margin is None or boundary_margin < boundary_limit - 1e-9)
        )

    full_limits = sampled_limits(points)
    if accepted(full_limits):
        return points
    zero = scaled(0.0)
    zero_limits = sampled_limits(zero)
    if not accepted(zero_limits):
        raise ValueError("accepted route knots cannot satisfy the planning trajectory envelope")

    # Hermite position is affine in its endpoint derivatives, so scaling all
    # internal derivatives interpolates between the zero-derivative path and the
    # original smooth path. Distance to a convex segment is convex and box margin
    # is concave; these two endpoint measurements therefore provide a conservative
    # safe derivative factor without an expensive per-candidate binary search.
    factors = [1.0]
    full_path_error, full_boundary_margin = full_limits
    zero_path_error, zero_boundary_margin = zero_limits
    if (
        path_limit is not None
        and full_path_error is not None
        and zero_path_error is not None
        and full_path_error > path_limit
    ):
        factors.append(
            max(
                0.0,
                (path_limit - zero_path_error) / max(full_path_error - zero_path_error, 1e-12),
            )
        )
    if (
        boundary_limit is not None
        and full_boundary_margin is not None
        and zero_boundary_margin is not None
        and full_boundary_margin < boundary_limit
    ):
        factors.append(
            max(
                0.0,
                (zero_boundary_margin - boundary_limit)
                / max(zero_boundary_margin - full_boundary_margin, 1e-12),
            )
        )
    factor = min(factors) * 0.98
    candidate = scaled(factor)
    if accepted(sampled_limits(candidate)):
        return candidate

    # Retain a short deterministic fallback for floating-point edge cases in the
    # conservative endpoint bound. It can only reduce the already bounded factor.
    low = 0.0
    high = factor
    for _ in range(12):
        middle = (low + high) / 2.0
        if accepted(sampled_limits(scaled(middle))):
            low = middle
        else:
            high = middle
    return scaled(low)


def _sample_points(
    points: tuple[TrajectoryPoint, ...],
    sample_step_s: float,
) -> tuple[Any, ...]:
    output = []
    for start, end in pairwise(points):
        duration_s = end.time_from_start_s - start.time_from_start_s
        sample_count = min(25, max(9, math.ceil(duration_s / sample_step_s) + 1))
        for index in range(sample_count):
            fraction = index / (sample_count - 1)
            timestamp_s = start.time_from_start_s + duration_s * fraction
            output.append(
                (
                    sample_trajectory_segment(start, end, timestamp_s),
                    start.position_m,
                    end.position_m,
                )
            )
    return tuple(output)


def _distance_to_polyline(point: Vector3, polyline: tuple[Vector3, ...]) -> float:
    return min(
        (_distance_to_segment(point, before, after) for before, after in pairwise(polyline)),
        default=float("inf"),
    )


def _distance_to_segment(point: Vector3, before: Vector3, after: Vector3) -> float:
    delta = _subtract(after, before)
    length_squared = delta.x * delta.x + delta.y * delta.y + delta.z * delta.z
    if length_squared <= 1e-18:
        return _distance(point, before)
    relative = _subtract(point, before)
    fraction = max(
        0.0,
        min(
            1.0,
            (relative.x * delta.x + relative.y * delta.y + relative.z * delta.z) / length_squared,
        ),
    )
    projection = _add_scaled(before, delta, fraction)
    return _distance(point, projection)


def _lateral_ceiling_margin(point: Vector3, case: CampaignCase) -> float:
    volume = case.hard_constraints.flight_volume
    return min(
        point.x - volume.minimum_m.x,
        volume.maximum_m.x - point.x,
        point.y - volume.minimum_m.y,
        volume.maximum_m.y - point.y,
        volume.maximum_m.z - point.z,
    )


def allocate_trajectory_points(
    case: CampaignCase,
    positions: tuple[Vector3, ...],
    *,
    speed_factor: float,
    sample_step_s: float = 0.01,
    declared_stops: tuple[RouteStop, ...] = (),
    segment_durations_s: tuple[float, ...] = (),
    path_speed_targets_m_s: tuple[float, ...] = (),
    entry_exit_ramp_s: float = 1.25,
    transition_distance_m: float | None = None,
    turn_blend_radius_m: float | None = None,
    corner_cut_tolerance_m: float | None = None,
) -> tuple[TrajectoryPoint, ...]:
    """Return the exact deterministic WP-30 time allocation used by planning and execution."""

    limits = case.hard_constraints.dynamics
    if (
        corner_cut_tolerance_m is not None
        and path_speed_targets_m_s
        and not declared_stops
        and len(positions) > 2
    ):
        authored_positions = positions
        positions = _continuous_tube_deformed_route(
            case,
            authored_positions,
            corner_cut_tolerance_m,
        )
        if len(positions) == 2 and len(authored_positions) > 2:
            # The topology may collapse only after the continuously deformed route
            # has reached the exact safe start-to-goal line.  At that boundary the
            # pre-collapse curve is already geometrically identical to the line, so
            # removing redundant collinear knots cannot create an accuracy jump.
            path_speed_targets_m_s = (min(path_speed_targets_m_s),)
            if segment_durations_s:
                segment_durations_s = (sum(segment_durations_s),)
    return _allocate_trajectory_points_cached(
        positions,
        speed_factor,
        sample_step_s,
        limits.maximum_horizontal_speed_m_s,
        limits.maximum_vertical_speed_m_s,
        limits.maximum_acceleration_m_s2,
        limits.maximum_jerk_m_s3,
        tuple((stop.position_m, stop.dwell_s) for stop in declared_stops),
        segment_durations_s,
        path_speed_targets_m_s,
        entry_exit_ramp_s,
        transition_distance_m,
        turn_blend_radius_m,
        corner_cut_tolerance_m,
        # Two-drone conflict routes reuse the qualified one-drone fly-through
        # tangent rule. The existing three-role bottleneck search still carries a
        # separate compatibility path until its protected-corridor generator is
        # replaced; do not make that unrelated catalog row commandless here.
        case.drone_count <= 2,
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
    stop_contracts: tuple[tuple[Vector3, float], ...],
    segment_durations_s: tuple[float, ...],
    path_speed_targets_m_s: tuple[float, ...],
    entry_exit_ramp_s: float,
    transition_distance_m: float | None,
    turn_blend_radius_m: float | None,
    corner_cut_tolerance_m: float | None,
    whole_route_continuous: bool,
) -> tuple[TrajectoryPoint, ...]:
    """Cache immutable allocations shared by timing variants in one bounded search."""

    nominal_speed = min(0.25 * speed_factor, maximum_horizontal_speed_m_s * 0.65)
    if segment_durations_s and len(segment_durations_s) != len(positions) - 1:
        raise ValueError("authored segment durations do not match trajectory positions")
    if path_speed_targets_m_s and len(path_speed_targets_m_s) != len(positions) - 1:
        raise ValueError("path-speed targets do not match trajectory positions")
    if path_speed_targets_m_s and any(value <= 0.0 for value in path_speed_targets_m_s):
        raise ValueError("path-speed targets must be positive")
    durations = list(segment_durations_s) or [
        (
            0.01
            if _distance(first, second) <= 1e-9
            else max(0.5, _distance(first, second) / max(0.02, nominal_speed))
        )
        for first, second in pairwise(positions)
    ]
    matched_stop_indices = []
    for stop_position, _ in stop_contracts:
        index = next(
            (
                candidate
                for candidate, position in enumerate(positions)
                if _distance(position, stop_position) <= 1e-9
            ),
            None,
        )
        if index is not None:
            matched_stop_indices.append(index)
    stop_indices = frozenset(matched_stop_indices)
    interior_stop_indices = stop_indices.difference({0, len(positions) - 1})
    dwell_by_index = {
        index: max(
            dwell
            for stop_position, dwell in stop_contracts
            if _distance(positions[index], stop_position) <= 1e-9
        )
        for index in stop_indices
    }
    scale = 1.0
    for _ in range(12):
        profiled = bool(path_speed_targets_m_s) and not interior_stop_indices
        if profiled:
            points = _scale_trajectory_points(
                _profiled_path_speed_points(
                    positions,
                    path_speed_targets_m_s,
                    entry_exit_ramp_s,
                    transition_distance_m=transition_distance_m,
                    turn_blend_radius_m=turn_blend_radius_m,
                    corner_cut_tolerance_m=corner_cut_tolerance_m,
                ),
                scale,
            )
        else:
            points = _trajectory_points(
                positions,
                durations,
                scale,
                stop_indices,
                whole_route_continuous=whole_route_continuous,
            )
        trajectory = TimeParameterizedTrajectory(
            trajectory_id=f"allocation-{canonical_sha256(points)[:20]}",
            role_id="allocation-role",
            vehicle_id="allocation-role",
            route_sha256=canonical_sha256(positions),
            points=points,
            declared_stop_sequences=tuple(
                point.sequence
                for index, point in enumerate(points)
                if index in {0, len(points) - 1}
                or (
                    _norm(point.velocity_m_s) <= 1e-9
                    and any(
                        _distance(point.position_m, positions[stop_index]) <= 1e-9
                        for stop_index in stop_indices
                    )
                )
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
            if not profiled:
                return _insert_holds(points, dwell_by_index)
            profiled_dwell_by_index = {
                next(
                    point_index
                    for point_index, point in enumerate(points)
                    if _distance(point.position_m, positions[stop_index]) <= 1e-9
                ): dwell_s
                for stop_index, dwell_s in dwell_by_index.items()
            }
            return _insert_holds(points, profiled_dwell_by_index)
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


def _profiled_path_speed_points(
    positions: tuple[Vector3, ...],
    target_speeds_m_s: tuple[float, ...],
    transition_s: float,
    *,
    transition_distance_m: float | None = None,
    turn_blend_radius_m: float | None = None,
    corner_cut_tolerance_m: float | None = None,
) -> tuple[TrajectoryPoint, ...]:
    """Build flat-speed interiors with explicit C2 entry, knot, and exit transitions."""

    if corner_cut_tolerance_m is not None:
        return _corner_cut_path_speed_points(
            positions,
            target_speeds_m_s,
            transition_s,
            transition_distance_m=transition_distance_m,
            turn_blend_radius_m=turn_blend_radius_m,
            corner_cut_tolerance_m=corner_cut_tolerance_m,
        )

    lengths = tuple(_distance(before, after) for before, after in pairwise(positions))
    if any(length <= 1e-9 for length in lengths):
        raise ValueError("profiled path-speed routes cannot contain zero-length segments")
    directions = tuple(_unit(_subtract(after, before)) for before, after in pairwise(positions))
    if (transition_distance_m is None) != (turn_blend_radius_m is None):
        raise ValueError("resolved corner transition requires both distance and radius")
    transition_distances = tuple(
        min(
            transition_distance_m
            if transition_distance_m is not None
            else speed * transition_s / 2.0,
            length * (0.49 if transition_distance_m is not None else 0.375),
            2.0 * turn_blend_radius_m if turn_blend_radius_m is not None else float("inf"),
        )
        for speed, length in zip(target_speeds_m_s, lengths, strict=True)
    )
    authored: list[tuple[float, Vector3, Vector3, Vector3]] = []
    timestamp_s = 0.0

    def append(
        position: Vector3,
        velocity: Vector3,
        acceleration: Vector3 | None = None,
    ) -> None:
        authored.append((timestamp_s, position, velocity, acceleration or Vector3()))

    append(positions[0], Vector3())
    first_speed = target_speeds_m_s[0]
    first_direction = directions[0]
    first_distance = transition_distances[0]
    timestamp_s += 2.0 * first_distance / first_speed
    append(
        _add_scaled(positions[0], first_direction, first_distance),
        _scale_vector(first_direction, first_speed),
    )

    for index, (_before, after) in enumerate(pairwise(positions)):
        speed = target_speeds_m_s[index]
        direction = directions[index]
        transition_distance = transition_distances[index]
        approach = _add_scaled(after, direction, -transition_distance)
        timestamp_s += _distance(authored[-1][1], approach) / speed
        append(approach, _scale_vector(direction, speed))
        if index == len(lengths) - 1:
            timestamp_s += 2.0 * transition_distance / speed
            append(after, Vector3())
            continue

        next_speed = target_speeds_m_s[index + 1]
        next_direction = directions[index + 1]
        next_distance = transition_distances[index + 1]
        incoming_s = transition_distance / speed
        outgoing_s = next_distance / next_speed
        transition_duration_s = incoming_s + outgoing_s
        # The weighted tangent chooses the turn direction; its magnitude must not
        # accidentally become cos(turn/2) times the admitted speed.  That old vector
        # average caused a visible scalar-speed dip at every benign corner.  The
        # surrounding Hermite interval and dense dynamics audit provide the physical
        # acceleration/jerk transition.
        knot_direction = _unit(
            _add_scaled(
                _scale_vector(direction, transition_distance),
                next_direction,
                next_distance,
            )
        )
        knot_velocity = _scale_vector(knot_direction, min(speed, next_speed))
        knot_acceleration = _scale_vector(
            _subtract(
                _scale_vector(next_direction, next_speed),
                _scale_vector(direction, speed),
            ),
            (
                # High-speed corner profiles need a gentler C2 derivative at
                # the semantic knot; the prior 2.5 gain satisfied the hard
                # limit only by global retiming and produced more jerk than the
                # baseline it was meant to smooth. Low-speed reusable profiles
                # retain their already-frozen derivative family.
                (
                    PROFILED_KNOT_ACCELERATION_GAIN_SMOOTH
                    if min(speed, next_speed) < 0.10
                    else PROFILED_KNOT_ACCELERATION_GAIN_BALANCED
                )
                / transition_duration_s
            ),
        )
        timestamp_s += incoming_s
        append(after, knot_velocity, knot_acceleration)
        timestamp_s += outgoing_s
        append(
            _add_scaled(after, next_direction, next_distance),
            _scale_vector(next_direction, next_speed),
        )

    return tuple(
        TrajectoryPoint(
            sequence=index + 1,
            time_from_start_s=timestamp,
            position_m=position,
            velocity_m_s=velocity,
            acceleration_m_s2=acceleration,
        )
        for index, (timestamp, position, velocity, acceleration) in enumerate(authored)
    )


def _corner_cut_path_speed_points(
    positions: tuple[Vector3, ...],
    target_speeds_m_s: tuple[float, ...],
    transition_s: float,
    *,
    transition_distance_m: float | None,
    turn_blend_radius_m: float | None,
    corner_cut_tolerance_m: float,
) -> tuple[TrajectoryPoint, ...]:
    """Build one C2 fly-through path that may bypass knots inside its accuracy tube."""

    if corner_cut_tolerance_m <= 0.0:
        raise ValueError("corner-cut tolerance must be positive")
    if (transition_distance_m is None) != (turn_blend_radius_m is None):
        raise ValueError("resolved corner transition requires both distance and radius")

    route = positions
    speeds = target_speeds_m_s
    lengths = tuple(_distance(before, after) for before, after in pairwise(route))
    if any(length <= 1e-9 for length in lengths):
        raise ValueError("corner-cut routes cannot contain zero-length segments")
    directions = tuple(_unit(_subtract(after, before)) for before, after in pairwise(route))
    transition_distances = tuple(
        min(
            transition_distance_m
            if transition_distance_m is not None
            else speed * transition_s / 2.0,
            length * (0.49 if transition_distance_m is not None else 0.375),
            2.0 * turn_blend_radius_m if turn_blend_radius_m is not None else float("inf"),
        )
        for speed, length in zip(speeds, lengths, strict=True)
    )
    authored: list[tuple[float, Vector3, Vector3, Vector3]] = []
    timestamp_s = 0.0

    def append(position: Vector3, velocity: Vector3) -> None:
        nonlocal timestamp_s
        if authored and _distance(authored[-1][1], position) <= 1e-12:
            # A near reversal can make the two trimmed endpoints coincide. Retain a
            # positive-time velocity transition at the shared position.
            timestamp_s += 0.01
        authored.append((timestamp_s, position, velocity, Vector3()))

    append(route[0], Vector3())
    first_speed = speeds[0]
    first_direction = directions[0]
    first_distance = transition_distances[0]
    timestamp_s += 2.0 * first_distance / first_speed
    append(
        _add_scaled(route[0], first_direction, first_distance),
        _scale_vector(first_direction, first_speed),
    )

    for index, (_before, corner) in enumerate(pairwise(route)):
        speed = speeds[index]
        direction = directions[index]
        transition_distance = transition_distances[index]
        incoming_trim = (
            transition_distance
            if index == len(lengths) - 1
            else min(transition_distance, corner_cut_tolerance_m)
        )
        approach = _add_scaled(corner, direction, -incoming_trim)
        timestamp_s += _distance(authored[-1][1], approach) / speed
        append(approach, _scale_vector(direction, speed))
        if index == len(lengths) - 1:
            timestamp_s += 2.0 * transition_distance / speed
            append(corner, Vector3())
            continue

        next_speed = speeds[index + 1]
        next_direction = directions[index + 1]
        outgoing_trim = min(transition_distances[index + 1], corner_cut_tolerance_m)
        timestamp_s += incoming_trim / speed + outgoing_trim / next_speed
        append(
            _add_scaled(corner, next_direction, outgoing_trim),
            _scale_vector(next_direction, next_speed),
        )

    return tuple(
        TrajectoryPoint(
            sequence=index + 1,
            time_from_start_s=timestamp,
            position_m=position,
            velocity_m_s=velocity,
            acceleration_m_s2=acceleration,
        )
        for index, (timestamp, position, velocity, acceleration) in enumerate(authored)
    )


def _continuous_tube_deformed_route(
    case: CampaignCase,
    positions: tuple[Vector3, ...],
    tolerance_m: float,
) -> tuple[Vector3, ...]:
    """Continuously relax one fly-through route toward its safe direct line.

    Every interior knot follows a deterministic homotopy from its authored
    position to its orthogonal projection on the start-to-goal segment.  The
    requested tolerance therefore changes the geometry continuously instead of
    deleting a waypoint as soon as a local threshold happens to pass.  A dense,
    bidirectional tube check and the normal free-space guard bound the admitted
    homotopy.  Redundant knots are removed only once the exact direct line is
    itself admissible.
    """

    if tolerance_m <= 0.0 or len(positions) <= 2:
        return positions
    start = positions[0]
    end = positions[-1]
    delta = _subtract(end, start)
    length_squared = delta.x * delta.x + delta.y * delta.y + delta.z * delta.z
    if length_squared <= 1e-18:
        return positions

    projections: list[Vector3] = []
    projection_fractions: list[float] = []
    for point in positions:
        relative = _subtract(point, start)
        fraction = max(
            0.0,
            min(
                1.0,
                (relative.x * delta.x + relative.y * delta.y + relative.z * delta.z)
                / length_squared,
            ),
        )
        projection_fractions.append(fraction)
        projections.append(_add_scaled(start, delta, fraction))

    # A global line is not a valid continuous homotopy for a route that doubles
    # back along its start-to-goal axis.  Preserve that route for the dedicated
    # whole-route optimizer rather than introducing a geometric reversal here.
    if any(after + 1e-12 < before for before, after in pairwise(projection_fractions)):
        return positions

    direct = (start, end)
    direct_tolerance_m = _bidirectional_polyline_distance(positions, direct)
    if direct_tolerance_m <= tolerance_m + 1e-12 and _shortcut_preserves_free_space(
        case, start, end
    ):
        return direct
    if direct_tolerance_m <= 1e-12:
        return direct

    requested_factor = min(1.0, tolerance_m / direct_tolerance_m)

    def candidate(factor: float) -> tuple[Vector3, ...]:
        return tuple(
            Vector3(
                x=point.x + (projection.x - point.x) * factor,
                y=point.y + (projection.y - point.y) * factor,
                z=point.z + (projection.z - point.z) * factor,
            )
            for point, projection in zip(positions, projections, strict=True)
        )

    def admissible(route: tuple[Vector3, ...]) -> bool:
        return (
            _bidirectional_polyline_distance(positions, route) <= tolerance_m + 1e-12
            and all(
                _shortcut_preserves_free_space(case, before, after)
                for before, after in pairwise(route)
            )
            and all(_distance(before, after) > 1e-9 for before, after in pairwise(route))
        )

    requested = candidate(requested_factor)
    if admissible(requested):
        return requested

    # Free-space and bidirectional tube admission are checked on the exact
    # candidate rather than assumed from knot positions.  Find the greatest safe
    # prefix of the continuous deformation deterministically.
    lower = 0.0
    upper = requested_factor
    accepted = positions
    for _ in range(32):
        middle = (lower + upper) / 2.0
        trial = candidate(middle)
        if admissible(trial):
            lower = middle
            accepted = trial
        else:
            upper = middle
    return accepted


def _bidirectional_polyline_distance(
    first: tuple[Vector3, ...],
    second: tuple[Vector3, ...],
) -> float:
    """Return a deterministic dense symmetric normal-distance bound."""

    def directed(source: tuple[Vector3, ...], target: tuple[Vector3, ...]) -> float:
        maximum = 0.0
        for before, after in pairwise(source):
            for sample_index in range(65):
                point = _add_scaled(before, _subtract(after, before), sample_index / 64.0)
                maximum = max(maximum, _distance_to_polyline(point, target))
        return maximum

    return max(directed(first, second), directed(second, first))


def _shortcut_preserves_free_space(
    case: CampaignCase,
    start: Vector3,
    end: Vector3,
) -> bool:
    volume = case.hard_constraints.flight_volume
    environment = case.semantics.environment_constraints if case.semantics else None
    protected_radius = 0.055 + case.hard_constraints.position_uncertainty_m + 0.05
    for sample_index in range(65):
        point = _add_scaled(start, _subtract(end, start), sample_index / 64.0)
        if (
            min(
                point.x - volume.minimum_m.x,
                volume.maximum_m.x - point.x,
                point.y - volume.minimum_m.y,
                volume.maximum_m.y - point.y,
                point.z - volume.minimum_m.z,
                volume.maximum_m.z - point.z,
            )
            < protected_radius - 1e-12
        ):
            return False
        if environment is None:
            continue
        for solid in environment.keep_out_regions:
            dx = max(solid.minimum_m.x - point.x, 0.0, point.x - solid.maximum_m.x)
            dy = max(solid.minimum_m.y - point.y, 0.0, point.y - solid.maximum_m.y)
            dz = max(solid.minimum_m.z - point.z, 0.0, point.z - solid.maximum_m.z)
            if math.sqrt(dx * dx + dy * dy + dz * dz) < protected_radius - 1e-12:
                return False
        if environment.required_corridors and not any(
            corridor.contains(point) for corridor in environment.required_corridors
        ):
            return False
    return True


def _scale_trajectory_points(
    points: tuple[TrajectoryPoint, ...], scale: float
) -> tuple[TrajectoryPoint, ...]:
    return tuple(
        point.model_copy(
            update={
                "time_from_start_s": point.time_from_start_s * scale,
                "velocity_m_s": _scale_vector(point.velocity_m_s, 1.0 / scale),
                "acceleration_m_s2": _scale_vector(point.acceleration_m_s2, 1.0 / (scale * scale)),
            }
        )
        for point in points
    )


def _trajectory_points(
    positions: tuple[Vector3, ...],
    durations: list[float],
    scale: float,
    stop_indices: frozenset[int],
    *,
    whole_route_continuous: bool,
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
        # Stopping is authored mission meaning. Geometry alone must never silently
        # turn a fly-through node into an accepted stop.
        velocity = (
            0.0
            if index in stop_indices or _norm(direction) <= 1e-12
            else max(
                0.03,
                min(incoming_speed, outgoing_speed)
                # This is a whole-route tangent projection, not a waypoint stop.
                # Collinear sampling knots retain full speed; a real corner is
                # reduced only as much as its turn angle requires. The bounded
                # dynamics pass below still retimes the complete route atomically.
                * (
                    min(
                        1.0,
                        max(0.20, math.sqrt(max(0.0, (direction_alignment + 1.0) / 2.0))),
                    )
                    if whole_route_continuous
                    else min(0.75, max(0.20, (direction_alignment + 1.0) / 2.0))
                ),
            )
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


def _insert_holds(
    points: tuple[TrajectoryPoint, ...], dwell_by_index: dict[int, float]
) -> tuple[TrajectoryPoint, ...]:
    expanded: list[TrajectoryPoint] = []
    shift_s = 0.0
    for index, point in enumerate(points):
        expanded.append(
            point.model_copy(
                update={
                    "sequence": len(expanded) + 1,
                    "time_from_start_s": point.time_from_start_s + shift_s,
                }
            )
        )
        dwell_s = dwell_by_index.get(index, 0.0)
        if dwell_s > 0.0:
            shift_s += dwell_s
            expanded.append(
                TrajectoryPoint(
                    sequence=len(expanded) + 1,
                    time_from_start_s=point.time_from_start_s + shift_s,
                    position_m=point.position_m,
                    velocity_m_s=Vector3(),
                    acceleration_m_s2=Vector3(),
                )
            )
    return tuple(expanded)


def declared_stop_sequences(
    route: CandidateRoute, points: tuple[TrajectoryPoint, ...]
) -> tuple[int, ...]:
    authored_positions = tuple(stop.position_m for stop in route.declared_stops)
    return tuple(
        point.sequence
        for point in points
        if point.sequence in {1, len(points)}
        or (
            any(_distance(point.position_m, position) <= 1e-9 for position in authored_positions)
            and _norm(point.velocity_m_s) <= 1e-9
        )
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


def _scale_vector(value: Vector3, scale: float) -> Vector3:
    return Vector3(x=value.x * scale, y=value.y * scale, z=value.z * scale)


def _add_scaled(first: Vector3, second: Vector3, scale: float) -> Vector3:
    return Vector3(
        x=first.x + second.x * scale,
        y=first.y + second.y * scale,
        z=first.z + second.z * scale,
    )


def _unit(value: Vector3) -> Vector3:
    length = _norm(value)
    if length <= 1e-12:
        return Vector3()
    return Vector3(x=value.x / length, y=value.y / length, z=value.z / length)


def _dot(first: Vector3, second: Vector3) -> float:
    return first.x * second.x + first.y * second.y + first.z * second.z


def _norm(value: Vector3) -> float:
    return math.sqrt(value.x * value.x + value.y * value.y + value.z * value.z)


def _distance(first: Vector3, second: Vector3) -> float:
    return _norm(_subtract(first, second))
