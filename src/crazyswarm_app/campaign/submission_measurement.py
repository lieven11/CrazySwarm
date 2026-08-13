from __future__ import annotations

import bisect
import math
from itertools import combinations, pairwise
from typing import Any, Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import CampaignCase
from crazyswarm_app.campaign.planner import BoundedPlanningResult, PlanningStatus
from crazyswarm_app.campaign.submissions import (
    CapabilityResolution,
    ExecutionProfileSubmission,
    PlanningSubmission,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class IndependentMetricObservation(ContractModel):
    metric_id: Identifier
    value: Any
    unit: str
    equality_tolerance: float | None = Field(default=None, ge=0.0)
    evidence_sha256: SHA256

    @model_validator(mode="after")
    def evidence_matches_value(self) -> IndependentMetricObservation:
        payload = self.model_dump(mode="python", exclude={"evidence_sha256"})
        if self.evidence_sha256 != canonical_sha256(payload):
            raise ValueError("independent metric evidence hash mismatch")
        return self


class IndependentBehaviorMeasurement(ContractModel):
    schema_version: Literal[1] = 1
    oracle_id: Literal["independent-submission-behavior-v1"] = (
        "independent-submission-behavior-v1"
    )
    case_id: Identifier
    case_sha256: SHA256
    submission_id: Identifier
    sample_step_s: Literal[0.01] = 0.01
    sample_artifact_sha256s: tuple[SHA256, ...]
    accepted_artifact_sha256s: tuple[SHA256, ...]
    metrics: tuple[IndependentMetricObservation, ...] = Field(min_length=1)
    measurement_sha256: SHA256

    @model_validator(mode="after")
    def measurement_is_closed(self) -> IndependentBehaviorMeasurement:
        ids = tuple(item.metric_id for item in self.metrics)
        if len(ids) != len(set(ids)):
            raise ValueError("independent behavior measurement repeats a metric")
        payload = self.model_dump(mode="python", exclude={"measurement_sha256"})
        if self.measurement_sha256 != canonical_sha256(payload):
            raise ValueError("independent behavior measurement hash mismatch")
        return self


class MetricEquivalence(ContractModel):
    metric_id: Identifier
    left_value: Any
    right_value: Any
    equality_tolerance: float | None = Field(default=None, ge=0.0)
    equivalent: bool
    reason: str = Field(min_length=1, max_length=500)


class CollapseEvidence(ContractModel):
    schema_version: Literal[1] = 1
    hidden_submission_id: Identifier
    visible_submission_id: Identifier
    hidden_semantic_fingerprint_sha256: SHA256
    visible_semantic_fingerprint_sha256: SHA256
    hidden_accepted_artifact_sha256s: tuple[SHA256, ...]
    visible_accepted_artifact_sha256s: tuple[SHA256, ...]
    hidden_measurement: IndependentBehaviorMeasurement
    visible_measurement: IndependentBehaviorMeasurement
    per_metric: tuple[MetricEquivalence, ...] = Field(min_length=1)
    collapse_proven: bool
    evidence_sha256: SHA256

    @model_validator(mode="after")
    def result_matches_metric_evidence(self) -> CollapseEvidence:
        if self.collapse_proven != all(item.equivalent for item in self.per_metric):
            raise ValueError("collapse disposition does not match per-metric evidence")
        payload = self.model_dump(mode="python", exclude={"evidence_sha256"})
        if self.evidence_sha256 != canonical_sha256(payload):
            raise ValueError("collapse evidence hash mismatch")
        return self


def measure_planning_behavior(
    case: CampaignCase,
    submission: PlanningSubmission,
    plan: BoundedPlanningResult,
    metric_ids: tuple[str, ...],
    *,
    execution_profile: ExecutionProfileSubmission | None = None,
    capability_resolution: CapabilityResolution | None = None,
) -> IndependentBehaviorMeasurement:
    """Measure an accepted plan without consulting semantic/candidate fingerprint helpers."""

    if plan.status is not PlanningStatus.READY or plan.selected is None:
        raise ValueError("independent behavior measurement requires an accepted plan")
    if plan.feasibility_certificate is None or not plan.feasibility_certificate.passed:
        raise ValueError("independent behavior measurement requires continuous certification")
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=execution_profile,
        planning_submission=submission,
        capability_resolution=capability_resolution,
    )
    routes = tuple(sorted(plan.selected.routes, key=lambda item: item.role_id))
    trajectory_by_role = {item.role_id: item for item in trajectories.trajectories}
    samples_by_role = {
        route.role_id: _independent_samples(trajectory_by_role[route.role_id])
        for route in routes
    }
    raw = _raw_metrics(case, plan, routes, samples_by_role)
    observations = []
    for metric_id in metric_ids:
        value = raw[metric_id]
        tolerance, unit = _metric_contract(metric_id)
        payload = {
            "metric_id": metric_id,
            "value": value,
            "unit": unit,
            "equality_tolerance": tolerance,
        }
        observations.append(
            IndependentMetricObservation(
                **payload,
                evidence_sha256=canonical_sha256(payload),
            )
        )
    sample_hashes = tuple(
        canonical_sha256(samples_by_role[role_id]) for role_id in sorted(samples_by_role)
    )
    payload = {
        "schema_version": 1,
        "oracle_id": "independent-submission-behavior-v1",
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "submission_id": (
            execution_profile.submission_id
            if execution_profile is not None
            else submission.planning_submission_id
        ),
        "sample_step_s": 0.01,
        "sample_artifact_sha256s": sample_hashes,
        "accepted_artifact_sha256s": (
            plan.plan_sha256,
            plan.feasibility_certificate.certificate_sha256,
            trajectories.set_sha256,
        ),
        "metrics": tuple(observations),
    }
    return IndependentBehaviorMeasurement(
        **payload,
        measurement_sha256=canonical_sha256(payload),
    )


def compare_for_collapse(
    *,
    hidden_submission: PlanningSubmission,
    visible_submission: PlanningSubmission,
    hidden: IndependentBehaviorMeasurement,
    visible: IndependentBehaviorMeasurement,
) -> CollapseEvidence:
    hidden_by_id = {item.metric_id: item for item in hidden.metrics}
    visible_by_id = {item.metric_id: item for item in visible.metrics}
    if set(hidden_by_id) != set(visible_by_id):
        raise ValueError("collapse measurements do not cover the same closed metric set")
    comparisons = []
    for metric_id in hidden_by_id:
        left = hidden_by_id[metric_id]
        right = visible_by_id[metric_id]
        if left.equality_tolerance != right.equality_tolerance:
            raise ValueError("collapse metric tolerances disagree")
        tolerance = left.equality_tolerance
        if tolerance is None:
            equivalent = left.value == right.value
            reason = (
                "exact discrete values are equal"
                if equivalent
                else "exact discrete values differ"
            )
        else:
            if not isinstance(left.value, (int, float)) or not isinstance(
                right.value, (int, float)
            ):
                raise ValueError("continuous collapse metric is not scalar")
            difference = abs(float(left.value) - float(right.value))
            equivalent = difference <= tolerance
            reason = (
                f"absolute delta {difference:.12g} is within frozen tolerance {tolerance:.12g}"
                if equivalent
                else f"absolute delta {difference:.12g} exceeds frozen tolerance {tolerance:.12g}"
            )
        comparisons.append(
            MetricEquivalence(
                metric_id=metric_id,
                left_value=left.value,
                right_value=right.value,
                equality_tolerance=tolerance,
                equivalent=equivalent,
                reason=reason,
            )
        )
    payload = {
        "schema_version": 1,
        "hidden_submission_id": hidden_submission.planning_submission_id,
        "visible_submission_id": visible_submission.planning_submission_id,
        "hidden_semantic_fingerprint_sha256": hidden_submission.semantic_fingerprint_sha256,
        "visible_semantic_fingerprint_sha256": visible_submission.semantic_fingerprint_sha256,
        "hidden_accepted_artifact_sha256s": hidden.accepted_artifact_sha256s,
        "visible_accepted_artifact_sha256s": visible.accepted_artifact_sha256s,
        "hidden_measurement": hidden,
        "visible_measurement": visible,
        "per_metric": tuple(comparisons),
        "collapse_proven": all(item.equivalent for item in comparisons),
    }
    return CollapseEvidence(
        **payload,
        evidence_sha256=canonical_sha256(payload),
    )


def _independent_samples(trajectory: Any) -> tuple[dict[str, Any], ...]:
    knot_times = tuple(point.time_from_start_s for point in trajectory.points)
    grid = {round(index * 0.01, 12) for index in range(math.ceil(trajectory.duration_s / 0.01) + 1)}
    grid.update(round(value, 12) for value in knot_times)
    grid.add(round(trajectory.duration_s, 12))
    output = []
    for timestamp_s in sorted(value for value in grid if value <= trajectory.duration_s + 1e-12):
        bounded = min(timestamp_s, trajectory.duration_s)
        index = max(0, min(len(knot_times) - 2, bisect.bisect_right(knot_times, bounded) - 1))
        before = trajectory.points[index]
        after = trajectory.points[index + 1]
        duration_s = after.time_from_start_s - before.time_from_start_s
        axes = tuple(
            _quintic_axis(
                getattr(before.position_m, axis),
                getattr(before.velocity_m_s, axis),
                getattr(before.acceleration_m_s2, axis),
                getattr(after.position_m, axis),
                getattr(after.velocity_m_s, axis),
                getattr(after.acceleration_m_s2, axis),
                duration_s,
                bounded - before.time_from_start_s,
            )
            for axis in ("x", "y", "z")
        )
        output.append(
            {
                "time_s": bounded,
                "position_m": tuple(item[0] for item in axes),
                "velocity_m_s": tuple(item[1] for item in axes),
                "acceleration_m_s2": tuple(item[2] for item in axes),
            }
        )
    return tuple(output)


def derive_sampled_route_semantics(
    case: CampaignCase,
    routes: tuple[Any, ...],
    samples_by_role: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any]:
    """Derive ordered captures, loop topology, and unintended stops from samples."""

    routes_by_role = {route.role_id: route for route in routes}
    roles = []
    for drone in sorted(case.drones, key=lambda item: item.role_id):
        samples = samples_by_role[drone.role_id]
        authored = tuple(drone.goal_sequence)
        captured: list[Any] = []
        observed: list[str] = []
        out_of_order: list[dict[str, Any]] = []
        expected_index = 0
        was_inside_expected = False
        for sample in samples:
            if expected_index >= len(authored):
                break
            expected = authored[expected_index]
            inside_expected = _point_region_distance(sample["position_m"], expected) <= 1e-12
            if inside_expected and not was_inside_expected:
                observed.append(expected.region_id)
                captured.append(expected)
                expected_index += 1
                was_inside_expected = False
                continue
            was_inside_expected = inside_expected
            if inside_expected:
                continue
            for future in authored[expected_index + 1 :]:
                same_as_expected = (
                    future.minimum_m == expected.minimum_m
                    and future.maximum_m == expected.maximum_m
                )
                same_as_captured = any(
                    future.minimum_m == prior.minimum_m
                    and future.maximum_m == prior.maximum_m
                    for prior in captured
                )
                if same_as_expected or same_as_captured:
                    continue
                if _point_region_distance(sample["position_m"], future) <= 1e-12:
                    event = {
                        "time_s": sample["time_s"],
                        "expected_region_id": expected.region_id,
                        "entered_region_id": future.region_id,
                    }
                    if not any(
                        prior["expected_region_id"] == event["expected_region_id"]
                        and prior["entered_region_id"] == event["entered_region_id"]
                        for prior in out_of_order
                    ):
                        out_of_order.append(event)
                    break

        stop_threshold = case.hard_constraints.dynamics.stop_speed_threshold_m_s
        persistence = case.hard_constraints.dynamics.unintended_stop_persistence_s
        terminal_guard_s = max(0.20, persistence)
        speed_by_index = tuple(
            _norm_tuple(sample["velocity_m_s"]) for sample in samples
        )
        low_start: int | None = None
        stop_intervals = []
        for index, (sample, speed) in enumerate(
            zip(samples, speed_by_index, strict=True)
        ):
            interior = (
                terminal_guard_s
                <= sample["time_s"]
                <= samples[-1]["time_s"] - terminal_guard_s
            )
            if interior and speed <= stop_threshold:
                if low_start is None:
                    low_start = index
                continue
            if low_start is None:
                continue
            end = index - 1
            duration_s = samples[end]["time_s"] - samples[low_start]["time_s"]
            midpoint = samples[(low_start + end) // 2]["position_m"]
            intended = any(
                math.dist(midpoint, _point_tuple(stop.position_m)) <= 0.08
                for stop in routes_by_role[drone.role_id].declared_stops
                if stop.dwell_s > 0.0
            )
            if duration_s + 1e-12 >= persistence and not intended:
                stop_intervals.append(
                    {
                        "start_s": samples[low_start]["time_s"],
                        "end_s": samples[end]["time_s"],
                        "duration_s": duration_s,
                    }
                )
            low_start = None

        geometry_counts: dict[str, int] = {}
        for region in authored:
            geometry_sha = canonical_sha256(
                {"minimum_m": region.minimum_m, "maximum_m": region.maximum_m}
            )
            geometry_counts[geometry_sha] = geometry_counts.get(geometry_sha, 0) + 1
        maximum_repeat = max(geometry_counts.values(), default=0)
        complete_order = tuple(observed) == tuple(
            region.region_id for region in authored
        ) and not out_of_order
        topology = (
            "figure_eight"
            if complete_order and maximum_repeat >= 3
            else (
                "closed_circle"
                if complete_order and maximum_repeat == 2
                else ("ordered_route" if complete_order else "order_violation")
            )
        )
        role_payload = {
            "role_id": drone.role_id,
            "expected_order": tuple(region.region_id for region in authored),
            "observed_order": tuple(observed),
            "out_of_order_entries": tuple(out_of_order),
            "complete_order": complete_order,
            "topology": topology,
            "maximum_repeated_checkpoint_visits": maximum_repeat,
            "unintended_stop_intervals": tuple(stop_intervals),
            "unintended_stop_count": len(stop_intervals),
            "samples_sha256": canonical_sha256(samples),
        }
        roles.append({**role_payload, "evidence_sha256": canonical_sha256(role_payload)})
    payload = {
        "oracle_id": "independent-dense-ordered-route-and-stop-v1",
        "sample_step_s": 0.01,
        "stop_speed_threshold_m_s": case.hard_constraints.dynamics.stop_speed_threshold_m_s,
        "unintended_stop_persistence_s": (
            case.hard_constraints.dynamics.unintended_stop_persistence_s
        ),
        "roles": tuple(roles),
        "DS_LOBE_ORDER": tuple(
            region_id for role in roles for region_id in role["observed_order"]
        ),
        "DS_TOPOLOGY": (
            roles[0]["topology"]
            if len(roles) == 1
            else (
                "ordered_fleet_routes"
                if all(role["complete_order"] for role in roles)
                else "order_violation"
            )
        ),
        "DS_UNINTENDED_STOP_COUNT": sum(
            role["unintended_stop_count"] for role in roles
        ),
    }
    return {**payload, "evidence_sha256": canonical_sha256(payload)}


def _quintic_axis(
    start: float,
    start_velocity: float,
    start_acceleration: float,
    end: float,
    end_velocity: float,
    end_acceleration: float,
    duration_s: float,
    elapsed_s: float,
) -> tuple[float, float, float]:
    a0, a1, a2 = start, start_velocity, start_acceleration / 2.0
    c0 = end - (a0 + a1 * duration_s + a2 * duration_s**2)
    c1 = end_velocity - (a1 + 2.0 * a2 * duration_s)
    c2 = end_acceleration - 2.0 * a2
    a3 = (10.0 * c0 - 4.0 * c1 * duration_s + 0.5 * c2 * duration_s**2) / duration_s**3
    a4 = (-15.0 * c0 + 7.0 * c1 * duration_s - c2 * duration_s**2) / duration_s**4
    a5 = (6.0 * c0 - 3.0 * c1 * duration_s + 0.5 * c2 * duration_s**2) / duration_s**5
    value = max(0.0, min(duration_s, elapsed_s))
    return (
        a0 + a1 * value + a2 * value**2 + a3 * value**3 + a4 * value**4 + a5 * value**5,
        a1 + 2.0 * a2 * value + 3.0 * a3 * value**2 + 4.0 * a4 * value**3 + 5.0 * a5 * value**4,
        2.0 * a2 + 6.0 * a3 * value + 12.0 * a4 * value**2 + 20.0 * a5 * value**3,
    )


def _raw_metrics(
    case: CampaignCase,
    plan: BoundedPlanningResult,
    routes: tuple[Any, ...],
    samples_by_role: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any]:
    assert plan.selected is not None and plan.feasibility_certificate is not None
    role_ids = tuple(route.role_id for route in routes)
    authored = {role_id: _authored_points(case, role_id) for role_id in role_ids}
    references = [
        _point_polyline_distance(sample["position_m"], authored[role_id])
        for role_id, samples in samples_by_role.items()
        for sample in samples
    ]
    capture_errors = []
    for drone in case.drones:
        samples = samples_by_role[drone.role_id]
        for goal in drone.goal_sequence:
            capture_errors.append(
                min(_point_region_distance(sample["position_m"], goal) for sample in samples)
            )
    velocities = [sample["velocity_m_s"] for samples in samples_by_role.values() for sample in samples]
    accelerations = [
        sample["acceleration_m_s2"] for samples in samples_by_role.values() for sample in samples
    ]
    speeds = [_norm_tuple(value) for value in velocities]
    moving_speeds = tuple(value for value in speeds if value > 1e-6)
    jerks = [
        math.dist(after["acceleration_m_s2"], before["acceleration_m_s2"])
        / (after["time_s"] - before["time_s"])
        for samples in samples_by_role.values()
        for before, after in pairwise(samples)
        if after["time_s"] > before["time_s"]
    ]
    curvatures = [
        _curvature(sample["velocity_m_s"], sample["acceleration_m_s2"])
        for samples in samples_by_role.values()
        for sample in samples
    ]
    starts = tuple(route.route_start_s for route in routes)
    finishes = tuple(route.route_start_s + route.route_duration_s for route in routes)
    overlap = max(0.0, min(finishes) - max(starts)) if routes else 0.0
    role_order = tuple(route.role_id for route in sorted(routes, key=lambda item: (item.route_start_s, item.role_id)))
    affected_roles = tuple(
        sorted(
            route.role_id
            for route in routes
            if plan.selected.strategy.value != "DIRECT"
            or route.points_m != authored[route.role_id]
            or route.route_start_s > 0.0
        )
    )
    reversal_count = sum(
        _dot(
            _subtract_tuple(_point_tuple(current), _point_tuple(before)),
            _subtract_tuple(_point_tuple(after), _point_tuple(current)),
        )
        < 0.0
        for points in authored.values()
        for before, current, after in zip(points, points[1:], points[2:], strict=False)
    )
    direction_change_count = sum(
        abs(_turn_angle(before, current, after)) > 1e-6
        for points in authored.values()
        for before, current, after in zip(points, points[1:], points[2:], strict=False)
    )
    priority_by_role = {drone.role_id: drone.priority for drone in case.drones}
    priority_inversions = sum(
        priority_by_role[later] < priority_by_role[earlier]
        for index, earlier in enumerate(role_order)
        for later in role_order[index + 1 :]
    )
    predicted_energy_wh = _predicted_hover_energy_wh(case, samples_by_role)
    sampled_semantics = derive_sampled_route_semantics(case, routes, samples_by_role)
    initial_reserves = tuple(drone.initial_battery_percent for drone in case.drones)
    capacity_wh = 0.25 * 4.2
    energy_share = predicted_energy_wh / max(1, len(case.drones))
    terminal_reserves = tuple(value - energy_share / capacity_wh * 100.0 for value in initial_reserves)
    formation_error, spacing_error = _fleet_shape_errors(routes, samples_by_role)
    route_identity = tuple(
        (route.role_id, canonical_sha256(tuple(point.model_dump(mode="python") for point in route.points_m)))
        for route in routes
    )
    schedule = tuple((route.role_id, route.route_start_s, route.route_duration_s) for route in routes)
    metric_values: dict[str, Any] = {
        "SP_CAPTURE": max(capture_errors, default=0.0),
        "SP_REFERENCE": max(references, default=0.0),
        "SP_RADIAL": max(references, default=0.0),
        "SP_CLOSURE": max(
            (math.dist(_point_tuple(points[0]), _point_tuple(points[-1])) for points in authored.values()),
            default=0.0,
        ),
        "SP_CORNER_CUT": max(references, default=0.0),
        "SP_SPLICE_POSITION": 0.0,
        "SP_FORMATION": formation_error,
        "SP_SPACING": spacing_error,
        "SP_OFFSET": formation_error,
        "SP_UNAFFECTED_PATH": 0.0,
        "SP_CLEARANCE": min(
            plan.feasibility_certificate.minimum_pairwise_protected_clearance_m,
            plan.feasibility_certificate.minimum_solid_protected_clearance_m,
        ),
        "SP_BOUNDARY": plan.feasibility_certificate.minimum_boundary_clearance_m,
        "TM_DURATION": max((route.route_duration_s for route in routes), default=0.0),
        "TM_SETTLE": max(finishes, default=0.0),
        "TM_TRANSITION_START": _transition_start_distance(routes),
        "TM_DWELL": max((sum(stop.dwell_s for stop in route.declared_stops) for route in routes), default=0.0),
        "TM_RELEASE": max(starts, default=0.0) - min(starts, default=0.0),
        "TM_OVERLAP": overlap,
        "TM_WAIT": max(starts, default=0.0),
        "TM_CUTOVER": 0.0,
        "TM_COVERAGE_GAP": 0.0,
        "TM_FINISH_SKEW": max(finishes, default=0.0) - min(finishes, default=0.0),
        "TM_PHASE_ERROR": max(starts, default=0.0) - min(starts, default=0.0),
        "TM_STARVATION": max(starts, default=0.0),
        "TM_HOLD": max((route.airborne_wait_s for route in routes), default=0.0),
        "TM_HORIZON": case.hard_constraints.deadline_s - max(finishes, default=0.0),
        "DY_SPEED_MIN": min(moving_speeds, default=0.0),
        "DY_SPEED_TRACKING": _speed_tracking_rms(routes, speeds),
        "DY_VERTICAL_TRACKING": 0.0,
        "DY_ACCELERATION": max((_norm_tuple(value) for value in accelerations), default=0.0),
        "DY_JERK": max(jerks, default=0.0),
        "DY_CURVATURE": max(curvatures, default=0.0),
        "EN_ENERGY_WH": predicted_energy_wh,
        "EN_RESERVE_PP": min(terminal_reserves, default=100.0),
        "EN_SPREAD_PP": max(terminal_reserves, default=0.0) - min(terminal_reserves, default=0.0),
        "EN_ACTUATOR_HEADROOM_N": _actuator_headroom(accelerations),
        "DS_TOPOLOGY": sampled_semantics["DS_TOPOLOGY"],
        "DS_LOBE_ORDER": sampled_semantics["DS_LOBE_ORDER"],
        "DS_REVERSAL_COUNT": reversal_count,
        "DS_UNINTENDED_STOP_COUNT": sampled_semantics["DS_UNINTENDED_STOP_COUNT"],
        "DS_DIRECTION_CHANGE_COUNT": direction_change_count,
        "DS_PRIORITY_INVERSION_COUNT": priority_inversions,
        "DS_PARTIAL_COMMIT_COUNT": 0,
        "DS_STALE_COMMAND_COUNT": 0,
        "DS_MANEUVER": plan.selected.strategy.value,
        "DS_FALLBACK": "NONE",
        "DS_DISPOSITION": plan.search_disposition.value,
        "DS_GENERATION": 0,
        "DS_ROUTE_IDENTITY": route_identity,
        "DS_AFFECTED_ROLES": affected_roles,
        "DS_PREPARED_ROLES": role_ids,
        "DS_ACKNOWLEDGED_ROLES": role_ids,
        "DS_QUEUE_ORDER": role_order,
        "DS_ROLE_ORDER": role_order,
        "DS_ASSIGNMENT": role_order,
        "DS_SCHEDULE": schedule,
        "DS_FLEET_EPOCH": 0,
        "DS_LEASE_GENERATION": 0,
        "DS_COMMAND_OWNERSHIP": role_ids,
        "DS_TERMINAL_STATE": tuple((role_id, "COMPLETED") for role_id in role_ids),
        "DS_ALL_ROLE_COMPLETION": role_ids,
        "DS_OCCUPANCY_INTERVALS": tuple(
            (route.role_id, route.route_start_s, route.route_start_s + route.route_duration_s)
            for route in routes
        ),
    }
    return metric_values


def _metric_contract(metric_id: str) -> tuple[float | None, str]:
    if metric_id.startswith("DS_"):
        return None, "exact"
    if metric_id == "TM_TRANSITION_START" or metric_id.startswith("SP_"):
        return 1e-4, "m"
    if metric_id.startswith("TM_"):
        return 1e-4, "s"
    if metric_id in {"DY_SPEED_MIN", "DY_SPEED_TRACKING", "DY_VERTICAL_TRACKING"}:
        return 1e-4, "m/s"
    if metric_id == "DY_ACCELERATION":
        return 1e-3, "m/s^2"
    if metric_id == "DY_JERK":
        return 1e-2, "m/s^3"
    if metric_id == "DY_CURVATURE":
        return 1e-3, "1/m"
    if metric_id.startswith("EN_"):
        return 1e-5, "Wh" if metric_id == "EN_ENERGY_WH" else "percentage_point"
    raise ValueError(f"unknown independent metric contract: {metric_id}")


def _authored_points(case: CampaignCase, role_id: str) -> tuple[Vector3, ...]:
    drone = next(item for item in case.drones if item.role_id == role_id)
    first_goal = drone.goal_sequence[0].center_m
    last_goal = drone.goal_sequence[-1].center_m
    return (
        drone.start_region.center_m.model_copy(update={"z": first_goal.z}),
        *(goal.center_m for goal in drone.goal_sequence),
        drone.landing_region.center_m.model_copy(update={"z": last_goal.z}),
    )


def _point_polyline_distance(point: tuple[float, float, float], points: tuple[Vector3, ...]) -> float:
    return min(_point_segment_distance(point, before, after) for before, after in pairwise(points))


def _point_segment_distance(point: tuple[float, float, float], before: Vector3, after: Vector3) -> float:
    start, end = _point_tuple(before), _point_tuple(after)
    delta = _subtract_tuple(end, start)
    denominator = _dot(delta, delta)
    fraction = 0.0 if denominator <= 1e-18 else max(0.0, min(1.0, _dot(_subtract_tuple(point, start), delta) / denominator))
    closest = tuple(start[index] + fraction * delta[index] for index in range(3))
    return math.dist(point, closest)


def _point_region_distance(point: tuple[float, float, float], region: Any) -> float:
    return math.sqrt(
        sum(
            value**2
            for value in (
                max(region.minimum_m.x - point[0], 0.0, point[0] - region.maximum_m.x),
                max(region.minimum_m.y - point[1], 0.0, point[1] - region.maximum_m.y),
                max(region.minimum_m.z - point[2], 0.0, point[2] - region.maximum_m.z),
            )
        )
    )


def _predicted_hover_energy_wh(
    case: CampaignCase,
    samples_by_role: dict[str, tuple[dict[str, Any], ...]],
) -> float:
    from crazyswarm_app.simulation.physics import PhysicsModelConfig
    from crazyswarm_app.simulation.powertrain import solve_coupled_powertrain

    physics = PhysicsModelConfig()
    command = physics.total_mass_kg * physics.gravity_m_s2 / (4.0 * physics.max_motor_thrust_n)
    total = 0.0
    for drone in case.drones:
        solution = solve_coupled_powertrain(
            physics,
            state_of_charge=drone.initial_battery_percent / 100.0,
            filtered_supply_voltage_v=physics.battery_full_voltage_v,
            motor_commands=(command,) * 4,
            additional_current_a=0.0,
        )
        duration = samples_by_role[drone.role_id][-1]["time_s"]
        total += solution.terminal_voltage_v * solution.total_current_a * duration / 3600.0
    return total


def _actuator_headroom(accelerations: list[tuple[float, float, float]]) -> float:
    from crazyswarm_app.simulation.physics import PhysicsModelConfig

    physics = PhysicsModelConfig()
    maximum_motor = max(
        (
            physics.total_mass_kg
            * math.sqrt(value[0] ** 2 + value[1] ** 2 + (physics.gravity_m_s2 + value[2]) ** 2)
            / 4.0
            for value in accelerations
        ),
        default=0.0,
    )
    return max(0.0, physics.max_motor_thrust_n - maximum_motor)


def _fleet_shape_errors(
    routes: tuple[Any, ...],
    samples_by_role: dict[str, tuple[dict[str, Any], ...]],
) -> tuple[float, float]:
    if len(routes) < 2:
        return 0.0, 0.0
    initial = {
        role_id: samples[0]["position_m"] for role_id, samples in samples_by_role.items()
    }
    formation = 0.0
    spacing = 0.0
    for first, second in combinations(sorted(samples_by_role), 2):
        initial_delta = _subtract_tuple(initial[first], initial[second])
        initial_spacing = _norm_tuple(initial_delta)
        for left, right in zip(samples_by_role[first], samples_by_role[second], strict=False):
            delta = _subtract_tuple(left["position_m"], right["position_m"])
            formation = max(formation, math.dist(delta, initial_delta))
            spacing = max(spacing, abs(_norm_tuple(delta) - initial_spacing))
    return formation, spacing


def _transition_start_distance(routes: tuple[Any, ...]) -> float:
    distances = []
    for route in routes:
        if len(route.points_m) < 3:
            continue
        distances.append(math.dist(_point_tuple(route.points_m[0]), _point_tuple(route.points_m[1])))
    return min(distances, default=0.0)


def _speed_tracking_rms(routes: tuple[Any, ...], speeds: list[float]) -> float:
    targets = [route.path_length_m / route.route_duration_s for route in routes]
    target = sum(targets) / max(1, len(targets))
    moving = tuple(value for value in speeds if value > 1e-6)
    return math.sqrt(sum((value - target) ** 2 for value in moving) / max(1, len(moving)))


def _curvature(velocity: tuple[float, ...], acceleration: tuple[float, ...]) -> float:
    speed = _norm_tuple(velocity)
    if speed <= 1e-6:
        return 0.0
    cross = (
        velocity[1] * acceleration[2] - velocity[2] * acceleration[1],
        velocity[2] * acceleration[0] - velocity[0] * acceleration[2],
        velocity[0] * acceleration[1] - velocity[1] * acceleration[0],
    )
    return _norm_tuple(cross) / speed**3


def _turn_angle(before: Vector3, current: Vector3, after: Vector3) -> float:
    first = _subtract_tuple(_point_tuple(current), _point_tuple(before))
    second = _subtract_tuple(_point_tuple(after), _point_tuple(current))
    denominator = _norm_tuple(first) * _norm_tuple(second)
    return 0.0 if denominator <= 1e-18 else math.acos(max(-1.0, min(1.0, _dot(first, second) / denominator)))


def _point_tuple(point: Vector3) -> tuple[float, float, float]:
    return point.x, point.y, point.z


def _subtract_tuple(first: tuple[float, ...], second: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(left - right for left, right in zip(first, second, strict=True))


def _dot(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    return sum(left * right for left, right in zip(first, second, strict=True))


def _norm_tuple(value: tuple[float, ...]) -> float:
    return math.sqrt(sum(item * item for item in value))
