#!/usr/bin/env python3
"""Reproduce the complete WP-52--56 R6 pre-freeze numerical design audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.geometry import certify_candidate_routes
from crazyswarm_app.campaign.planner import (
    BoundedJointPlanner,
    CandidateStatus,
    PlanningStatus,
)
from crazyswarm_app.campaign.submission_measurement import (
    _independent_samples,
    _metric_contract,
    _raw_metrics,
)
from crazyswarm_app.campaign.submissions import (
    ExecutionCapabilityRequest,
    ExecutionProfileKind,
    ExecutionProfileParameters,
    ExperimentAxis,
    SubmissionStatus,
    admission_record_for_case,
    load_case_submission_registry,
    resolve_planning_package,
    resolve_planning_submission,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.simulation import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT / "docs/work-packages/WP52_56_R6_NUMERICAL_PREDRAFT_AUDIT_2026-08-12.json"
)
CAPACITY_CONTEXT = {"minimum_simultaneous_flight_s": 2.0}
CAPACITY_CONTEXT_ID = "overlap-capacity-v1"
CAPACITY_CONTEXT_SHA256 = canonical_sha256(CAPACITY_CONTEXT)
SYNCHRONIZED_FIXED_INPUTS = {
    "synchronized_route_start_required": True,
    "maximum_route_start_skew_s": 0.2,
    "minimum_simultaneous_flight_s": 2.0,
}
R5_AUDIT = ROOT / "docs/work-packages/WP52_56_R5_PREDRAFT_AUDIT_2026-08-12.json"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_profile(planning: Any, profile: Any) -> Any:
    return planning.model_copy(
        update={
            "execution_profile_submission_id": profile.submission_id,
            "execution_profile_sha256": profile.profile_sha256,
        }
    )


def _point_in_region(point: tuple[float, float, float], region: Any) -> bool:
    return (
        region.minimum_m.x <= point[0] <= region.maximum_m.x
        and region.minimum_m.y <= point[1] <= region.maximum_m.y
        and region.minimum_m.z <= point[2] <= region.maximum_m.z
    )


def _same_region_geometry(left: Any, right: Any) -> bool:
    return left.minimum_m == right.minimum_m and left.maximum_m == right.maximum_m


def _sampled_role_semantics(
    case: Any,
    role_id: str,
    samples: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Observe ordered regions/topology/stops from dense samples, not authored labels."""

    drone = next(item for item in case.drones if item.role_id == role_id)
    authored = tuple(drone.goal_sequence)
    observed_order: list[str] = []
    captured_regions: list[Any] = []
    out_of_order_entries: list[dict[str, Any]] = []
    expected_index = 0
    was_inside_expected = False
    for sample in samples:
        point = sample["position_m"]
        if expected_index >= len(authored):
            break
        expected = authored[expected_index]
        inside_expected = _point_in_region(point, expected)
        if inside_expected and not was_inside_expected:
            observed_order.append(expected.region_id)
            captured_regions.append(expected)
            expected_index += 1
            was_inside_expected = False
            continue
        was_inside_expected = inside_expected
        if inside_expected:
            continue
        for future in authored[expected_index + 1 :]:
            if _same_region_geometry(expected, future) or any(
                _same_region_geometry(captured, future) for captured in captured_regions
            ):
                continue
            if _point_in_region(point, future):
                event = {
                    "time_s": sample["time_s"],
                    "expected_region_id": expected.region_id,
                    "entered_region_id": future.region_id,
                }
                if not any(
                    existing["expected_region_id"] == event["expected_region_id"]
                    and existing["entered_region_id"] == event["entered_region_id"]
                    for existing in out_of_order_entries
                ):
                    out_of_order_entries.append(event)
                break

    speeds = [
        sum(component * component for component in sample["velocity_m_s"]) ** 0.5
        for sample in samples
    ]
    stop_threshold = case.hard_constraints.dynamics.stop_speed_threshold_m_s
    persistence = case.hard_constraints.dynamics.unintended_stop_persistence_s
    guard_s = max(persistence, 0.20)
    low_start: int | None = None
    stop_intervals: list[dict[str, float]] = []
    for index, (sample, speed) in enumerate(zip(samples, speeds, strict=True)):
        interior = guard_s <= sample["time_s"] <= samples[-1]["time_s"] - guard_s
        if interior and speed <= stop_threshold:
            if low_start is None:
                low_start = index
        elif low_start is not None:
            end = index - 1
            duration = samples[end]["time_s"] - samples[low_start]["time_s"]
            if duration + 1e-12 >= persistence:
                stop_intervals.append(
                    {
                        "start_s": samples[low_start]["time_s"],
                        "end_s": samples[end]["time_s"],
                        "duration_s": duration,
                    }
                )
            low_start = None
    if low_start is not None:
        end = len(samples) - 1
        duration = samples[end]["time_s"] - samples[low_start]["time_s"]
        if duration + 1e-12 >= persistence:
            stop_intervals.append(
                {
                    "start_s": samples[low_start]["time_s"],
                    "end_s": samples[end]["time_s"],
                    "duration_s": duration,
                }
            )

    expected_order = tuple(region.region_id for region in authored)
    complete_order = tuple(observed_order) == expected_order and not out_of_order_entries
    center_geometry_counts: dict[str, int] = {}
    for region in authored:
        geometry_sha = canonical_sha256(
            {
                "minimum_m": region.minimum_m,
                "maximum_m": region.maximum_m,
            }
        )
        center_geometry_counts[geometry_sha] = center_geometry_counts.get(geometry_sha, 0) + 1
    repeated_checkpoint_visits = max(center_geometry_counts.values(), default=0)
    topology = (
        "figure_eight"
        if case.case_id == "1d.planar_shape_loop.figure_eight"
        and complete_order
        and repeated_checkpoint_visits == 3
        else ("ordered_route" if complete_order else "order_violation")
    )
    payload = {
        "oracle_id": "independent-dense-ordered-route-and-stop-v1",
        "sample_step_s": 0.01,
        "role_id": role_id,
        "expected_order": expected_order,
        "observed_order": tuple(observed_order),
        "out_of_order_entries": tuple(out_of_order_entries),
        "complete_order": complete_order,
        "topology": topology,
        "repeated_checkpoint_visits": repeated_checkpoint_visits,
        "stop_speed_threshold_m_s": stop_threshold,
        "unintended_stop_persistence_s": persistence,
        "terminal_guard_s": guard_s,
        "unintended_stop_intervals": tuple(stop_intervals),
        "unintended_stop_count": len(stop_intervals),
        "samples_sha256": canonical_sha256(samples),
    }
    return {**payload, "evidence_sha256": canonical_sha256(payload)}


def _sampled_semantics(
    case: Any,
    samples_by_role: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any]:
    roles = tuple(
        _sampled_role_semantics(case, role_id, samples)
        for role_id, samples in sorted(samples_by_role.items())
    )
    payload = {
        "oracle_id": "independent-dense-ordered-route-and-stop-v1",
        "roles": roles,
        "DS_LOBE_ORDER": tuple(
            region_id for role in roles for region_id in role["observed_order"]
        ),
        "DS_TOPOLOGY": (
            "figure_eight"
            if len(roles) == 1 and roles[0]["topology"] == "figure_eight"
            else (
                "ordered_route"
                if all(role["complete_order"] for role in roles)
                else "order_violation"
            )
        ),
        "DS_UNINTENDED_STOP_COUNT": sum(
            role["unintended_stop_count"] for role in roles
        ),
    }
    return {**payload, "evidence_sha256": canonical_sha256(payload)}


def _observe(
    case: Any,
    planning: Any,
    profile: Any,
    plan: Any,
    *,
    capability_resolution: Any = None,
) -> dict[str, Any]:
    if plan.status is not PlanningStatus.READY or plan.selected is None:
        raise ValueError(
            f"accepted artifact required for {case.case_id}:{planning.planning_submission_id}"
        )
    if plan.feasibility_certificate is None or not plan.feasibility_certificate.passed:
        raise ValueError("accepted plan lacks an independent feasibility certificate")
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=profile,
        planning_submission=planning,
        capability_resolution=capability_resolution,
    )
    routes = tuple(sorted(plan.selected.routes, key=lambda item: item.role_id))
    trajectory_by_role = {item.role_id: item for item in trajectories.trajectories}
    samples = {
        route.role_id: _independent_samples(trajectory_by_role[route.role_id])
        for route in routes
    }
    raw = _raw_metrics(case, plan, routes, samples)
    sampled_semantics = _sampled_semantics(case, samples)
    raw.update(
        {
            metric_id: sampled_semantics[metric_id]
            for metric_id in (
                "DS_LOBE_ORDER",
                "DS_TOPOLOGY",
                "DS_UNINTENDED_STOP_COUNT",
            )
        }
    )
    metric_ids = admission_record_for_case(case).metric_ids
    metrics = []
    for metric_id in metric_ids:
        tolerance, unit = _metric_contract(metric_id)
        entry = {
            "metric_id": metric_id,
            "value": raw[metric_id],
            "unit": unit,
            "equality_tolerance": tolerance,
        }
        metrics.append({**entry, "evidence_sha256": canonical_sha256(entry)})
    artifact = {
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "planning_submission_id": planning.planning_submission_id,
        "planning_submission_sha256": planning.planning_submission_sha256,
        "execution_profile_submission_id": profile.submission_id,
        "execution_profile_sha256": profile.profile_sha256,
        "capability_resolution_sha256": (
            canonical_sha256(capability_resolution)
            if capability_resolution is not None
            else None
        ),
        "plan_sha256": plan.plan_sha256,
        "selected_candidate_sha256": plan.selected.candidate_sha256,
        "feasibility_certificate_sha256": (
            plan.feasibility_certificate.certificate_sha256
        ),
        "trajectory_set_sha256": trajectories.set_sha256,
        "trajectory_sha256_by_role": {
            item.role_id: item.sha256 for item in trajectories.trajectories
        },
        "independent_sample_sha256_by_role": {
            role_id: canonical_sha256(values) for role_id, values in sorted(samples.items())
        },
        "independent_discrete_observation": sampled_semantics,
        "metrics": metrics,
    }
    return {**artifact, "observation_sha256": canonical_sha256(artifact)}


def _metric_map(observation: dict[str, Any]) -> dict[str, Any]:
    return {item["metric_id"]: item["value"] for item in observation["metrics"]}


def _capacity_planning(case: Any, submission_id: str | None) -> Any:
    baseline = resolve_planning_submission(case, None, require_executable=False)
    coordination = baseline.coordination.model_copy(
        update={"minimum_simultaneous_flight_s": 2.0}
    )
    if submission_id is None:
        return baseline.model_copy(
            update={
                "planning_submission_id": (
                    f"{baseline.planning_submission_id}.{CAPACITY_CONTEXT_ID}"
                ),
                "coordination": coordination,
            }
        )
    source = resolve_planning_submission(case, submission_id, require_executable=False)
    update: dict[str, Any] = {
        "planning_submission_id": f"{submission_id}.{CAPACITY_CONTEXT_ID}",
        "coordination": coordination,
        "experiment_id": source.experiment_id,
        "experiment_axis": source.experiment_axis,
        "axis_value": source.axis_value,
        "admission": source.admission,
    }
    if source.experiment_axis is ExperimentAxis.MANEUVER_DIMENSION:
        update.update(
            {
                "strategy_authority": source.strategy_authority,
                "maneuver_dimensions": source.maneuver_dimensions,
            }
        )
    elif source.experiment_axis is ExperimentAxis.OBJECTIVE_ORDER:
        update["objective"] = source.objective
    else:
        raise ValueError(f"unsupported capacity prototype axis {source.experiment_axis}")
    return baseline.model_copy(update=update)


def _capacity_prototypes(catalog: CampaignCatalog, planner: BoundedJointPlanner) -> Any:
    keys = (
        (
            "2d.head_on_conflict.canonical_nominal",
            "head_on.earliest_safe_release",
        ),
        ("2d.merge.canonical_nominal", "merge.fair_release"),
        (
            "2d.perpendicular_crossing.nominal_equal_priority",
            "crossing.earliest_equal_release",
        ),
    )
    output = []
    for case_id, submission_id in keys:
        case = catalog.get(case_id)
        profile = resolve_planning_package(case).execution_profile
        baseline = _bound_profile(_capacity_planning(case, None), profile)
        subject = _bound_profile(_capacity_planning(case, submission_id), profile)
        baseline_plan = planner.plan(case, profile, planning_submission=baseline)
        subject_plan = planner.plan(case, profile, planning_submission=subject)
        baseline_observation = _observe(case, baseline, profile, baseline_plan)
        subject_observation = _observe(case, subject, profile, subject_plan)
        baseline_metrics = _metric_map(baseline_observation)
        subject_metrics = _metric_map(subject_observation)
        earliest_release = (
            _argmin_release_prototype(
                case,
                subject,
                profile,
                subject_plan,
            )
            if submission_id
            in {"head_on.earliest_safe_release", "crossing.earliest_equal_release"}
            else None
        )
        if submission_id == "head_on.earliest_safe_release":
            clauses = {
                "categorical_maneuver_is_timing": subject_metrics["DS_MANEUVER"]
                == "GROUND_DELAY",
                "absolute_bounded_earliest_release": earliest_release["passed"],
                "overlap_at_least_2s_both": min(
                    baseline_metrics["TM_OVERLAP"], subject_metrics["TM_OVERLAP"]
                )
                >= 2.0,
                "clearance_positive_both": min(
                    baseline_metrics["SP_CLEARANCE"], subject_metrics["SP_CLEARANCE"]
                )
                >= -1e-9,
            }
        elif submission_id == "merge.fair_release":
            clauses = {
                "wait_improves_by_at_least_0_10s": (
                    subject_metrics["TM_WAIT"] <= baseline_metrics["TM_WAIT"] - 0.10
                ),
                "overlap_at_least_2s_both": min(
                    baseline_metrics["TM_OVERLAP"], subject_metrics["TM_OVERLAP"]
                )
                >= 2.0,
                "clearance_positive_both": min(
                    baseline_metrics["SP_CLEARANCE"], subject_metrics["SP_CLEARANCE"]
                )
                >= -1e-9,
            }
        else:
            clauses = {
                "categorical_maneuver_is_timing": subject_metrics["DS_MANEUVER"]
                == "GROUND_DELAY",
                "absolute_bounded_earliest_release": earliest_release["passed"],
                "overlap_at_least_2s_both": min(
                    baseline_metrics["TM_OVERLAP"], subject_metrics["TM_OVERLAP"]
                )
                >= 2.0,
                "clearance_positive_both": min(
                    baseline_metrics["SP_CLEARANCE"], subject_metrics["SP_CLEARANCE"]
                )
                >= -1e-9,
            }
        output.append(
            {
                "proposal_key": f"{case_id}/{submission_id}",
                "context_id": CAPACITY_CONTEXT_ID,
                "context_sha256": CAPACITY_CONTEXT_SHA256,
                "context": CAPACITY_CONTEXT,
                "baseline": baseline_observation,
                "subject": subject_observation,
                "bounded_earliest_release_oracle": earliest_release,
                "relation_evaluation": {
                    "clauses": clauses,
                    "passed": all(clauses.values()),
                },
                "full_metric_delta": {
                    metric_id: (
                        _metric_map(subject_observation)[metric_id]
                        - _metric_map(baseline_observation)[metric_id]
                        if isinstance(_metric_map(subject_observation)[metric_id], (int, float))
                        and isinstance(_metric_map(baseline_observation)[metric_id], (int, float))
                        else {
                            "baseline": _metric_map(baseline_observation)[metric_id],
                            "subject": _metric_map(subject_observation)[metric_id],
                        }
                    )
                    for metric_id in _metric_map(baseline_observation)
                },
            }
        )
    return output


def _argmin_release_prototype(
    case: Any,
    planning: Any,
    profile: Any,
    plan: Any,
) -> dict[str, Any]:
    candidates = []
    eligible: list[tuple[float, tuple[float, ...], str]] = []
    objective_order = tuple(term.metric for term in planning.objective.terms)
    for index, candidate in enumerate(plan.retained_candidates):
        certificate = certify_candidate_routes(
            case,
            planning,
            candidate.candidate_sha256,
            candidate.routes,
        )
        entry: dict[str, Any] = {
            "retained_index": index,
            "candidate_sha256": candidate.candidate_sha256,
            "strategy": candidate.strategy.value,
            "generator_id": candidate.generator_id,
            "parameters": candidate.parameters,
            "sampled_status": candidate.status.value,
            "sampled_rejection_reasons": candidate.rejection_reasons,
            "candidate_cost": candidate.cost.model_dump(mode="json"),
            "independent_certificate": certificate.model_dump(mode="json"),
        }
        if candidate.status is CandidateStatus.FEASIBLE and certificate.passed:
            candidate_plan = plan.model_copy(
                update={
                    "status": PlanningStatus.READY,
                    "selected_candidate_index": index,
                    "selected_candidate_sha256": candidate.candidate_sha256,
                    "feasibility_certificate": certificate,
                }
            )
            try:
                observation = _observe(
                    case,
                    planning,
                    profile,
                    candidate_plan,
                )
            except ValueError as error:
                entry["trajectory_disposition"] = {
                    "status": "REJECTED",
                    "reason": str(error),
                }
            else:
                entry["trajectory_disposition"] = {
                    "status": "ACCEPTED",
                    "observation": observation,
                }
                release = float(_metric_map(observation)["TM_RELEASE"])
                eligible.append(
                    (
                        release,
                        candidate.cost.vector_for(objective_order),
                        candidate.candidate_sha256,
                    )
                )
        candidates.append(entry)
    if not eligible:
        raise ValueError("ARGMIN_BOUNDED release prototype has no accepted candidate")
    minimum = min(value for value, _, _ in eligible)
    tied_entries = sorted(
        (objective_vector, sha)
        for value, objective_vector, sha in eligible
        if abs(value - minimum) <= 1e-12
    )
    tied = [sha for _, sha in tied_entries]
    selected = tied[0]
    return {
        "oracle": "ARGMIN_BOUNDED(TM_RELEASE)",
        "candidate_family": {
            "generated_candidate_count": plan.generated_candidate_count,
            "retained_candidate_count": plan.retained_candidate_count,
            "truncated": plan.truncated,
            "bounded_search_complete": plan.bounded_search_complete,
        },
        "tie_tolerance_s": 1e-12,
        "tie_break": (
            "lexicographically smallest frozen subject-objective cost vector, then "
            "candidate_sha256"
        ),
        "objective_order": [item.value for item in objective_order],
        "minimum_release_s": minimum,
        "tied_candidate_sha256s": tied,
        "selected_candidate_sha256": selected,
        "planner_selected_candidate_sha256": plan.selected.candidate_sha256,
        "passed": (
            plan.bounded_search_complete
            and not plan.truncated
            and plan.selected.candidate_sha256 == selected
        ),
        "candidates": candidates,
    }


def _profile_counterexamples(
    case: Any,
    package: Any,
    plan: Any,
) -> dict[str, Any]:
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
    )
    samples = {
        trajectory.role_id: _independent_samples(trajectory)
        for trajectory in trajectories.trajectories
    }
    original = _sampled_semantics(case, samples)
    output: dict[str, Any] = {"original_observation": original}
    if case.case_id == "1d.planar_shape_loop.figure_eight":
        reordered: dict[str, tuple[dict[str, Any], ...]] = {}
        for role_id, values in samples.items():
            reversed_values = tuple(reversed(values))
            reordered[role_id] = tuple(
                {
                    **source,
                    "time_s": target["time_s"],
                    "velocity_m_s": tuple(-value for value in source["velocity_m_s"]),
                }
                for target, source in zip(values, reversed_values, strict=True)
            )
        result = _sampled_semantics(case, reordered)
        output["reordered_traversal"] = {
            "perturbation": "reverse sampled traversal while preserving the sample clock",
            "samples_sha256_by_role": {
                role_id: canonical_sha256(values)
                for role_id, values in sorted(reordered.items())
            },
            "observation": result,
            "rejected": (
                result["DS_TOPOLOGY"] != "figure_eight"
                or result["DS_LOBE_ORDER"]
                != original["DS_LOBE_ORDER"]
            ),
        }
    if case.case_id == "1d.continuous_waypoint_sequence.canonical_nominal":
        stopped: dict[str, tuple[dict[str, Any], ...]] = {}
        persistence = case.hard_constraints.dynamics.unintended_stop_persistence_s
        for role_id, values in samples.items():
            pivot_index = len(values) // 2
            pivot_time = values[pivot_index]["time_s"]
            pivot_position = values[pivot_index]["position_m"]
            stopped[role_id] = tuple(
                {
                    **sample,
                    "position_m": pivot_position,
                    "velocity_m_s": (0.0, 0.0, 0.0),
                    "acceleration_m_s2": (0.0, 0.0, 0.0),
                }
                if pivot_time <= sample["time_s"] <= pivot_time + persistence + 0.02
                else sample
                for sample in values
            )
        result = _sampled_semantics(case, stopped)
        output["inserted_interior_stop"] = {
            "perturbation": (
                "hold the independently sampled midpoint for longer than the frozen "
                "unintended-stop persistence"
            ),
            "samples_sha256_by_role": {
                role_id: canonical_sha256(values)
                for role_id, values in sorted(stopped.items())
            },
            "observation": result,
            "rejected": result["DS_UNINTENDED_STOP_COUNT"] >= 1,
        }
    return output


def _profile_prototypes(catalog: CampaignCatalog, planner: BoundedJointPlanner) -> Any:
    output = []
    corner_request = ExecutionCapabilityRequest(
        capability_id="core.corner_transition",
        parameters=ExecutionProfileParameters(
            target_path_speed_m_s=0.08,
            lookahead_time_s=0.60,
        ),
    )
    corner_cases = (
        (
            "1d.continuous_waypoint_sequence.canonical_nominal",
            "waypoint.smoothness_first",
        ),
        (
            "1d.planar_shape_loop.figure_eight",
            "loop.curvature_continuity",
        ),
    )
    for case_id, submission_id in corner_cases:
        case = catalog.get(case_id)
        baseline_package = resolve_planning_package(case)
        subject_package = resolve_planning_package(
            case,
            execution_capability_request=corner_request,
        )
        baseline_plan = planner.plan(
            case,
            baseline_package.execution_profile,
            planning_submission=baseline_package.planning_submission,
        )
        subject_plan = planner.plan(
            case,
            subject_package.execution_profile,
            planning_submission=subject_package.planning_submission,
            capability_resolution=subject_package.capability_resolution,
        )
        baseline_observation = _observe(
            case,
            baseline_package.planning_submission,
            baseline_package.execution_profile,
            baseline_plan,
        )
        subject_observation = _observe(
            case,
            subject_package.planning_submission,
            subject_package.execution_profile,
            subject_plan,
            capability_resolution=subject_package.capability_resolution,
        )
        baseline_metrics = _metric_map(baseline_observation)
        subject_metrics = _metric_map(subject_observation)
        clauses = {
            "curvature_improves_by_at_least_0_05_per_m": (
                subject_metrics["DY_CURVATURE"]
                <= baseline_metrics["DY_CURVATURE"] - 0.05
            ),
            "reference_improves_by_at_least_0_01m": (
                subject_metrics["SP_REFERENCE"]
                <= baseline_metrics["SP_REFERENCE"] - 0.01
            ),
            "capture_passes": subject_metrics["SP_CAPTURE"] <= 1e-4,
        }
        if case_id == "1d.planar_shape_loop.figure_eight":
            expected_order = tuple(
                goal.region_id for drone in case.drones for goal in drone.goal_sequence
            )
            clauses["sampled_topology_is_figure_eight"] = (
                subject_metrics["DS_TOPOLOGY"] == "figure_eight"
            )
            clauses["sampled_lobe_order_is_authored"] = (
                tuple(subject_metrics["DS_LOBE_ORDER"]) == expected_order
            )
        if "TM_DURATION" in subject_metrics:
            clauses["duration_increases_by_at_least_0_10s"] = (
                subject_metrics["TM_DURATION"] >= baseline_metrics["TM_DURATION"] + 0.10
            )
        if "DS_UNINTENDED_STOP_COUNT" in subject_metrics:
            clauses["unintended_stop_count_is_zero"] = (
                subject_metrics["DS_UNINTENDED_STOP_COUNT"] == 0
            )
        output.append(
            {
                "proposal_key": f"{case_id}/{submission_id}",
                "axis": "CAPABILITY_BINDING",
                "axis_value": "corner_transition_0_60s_at_0_08m_s",
                "baseline": baseline_observation,
                "subject": subject_observation,
                "relation_evaluation": {
                    "clauses": clauses,
                    "passed": all(clauses.values()),
                },
                "counterexamples": _profile_counterexamples(
                    case,
                    subject_package,
                    subject_plan,
                ),
            }
        )

    case = catalog.get("1d.curved_route.canonical_nominal")
    baseline_package = resolve_planning_package(case)
    subject_profile = baseline_package.execution_profile.model_copy(
        update={
            "submission_id": "curve.jerk_first",
            "display_name": "Curve jerk-first duration scale",
            "kind": ExecutionProfileKind.DURATION_SCALE,
            "parameters": ExecutionProfileParameters(duration_scale=1.30),
            "status": SubmissionStatus.EXECUTABLE,
            "support_reason": "R6 pre-freeze execution-profile feasibility witness.",
        }
    )
    subject_planning = _bound_profile(
        baseline_package.planning_submission,
        subject_profile,
    )
    baseline_plan = planner.plan(
        case,
        baseline_package.execution_profile,
        planning_submission=baseline_package.planning_submission,
    )
    subject_plan = planner.plan(
        case,
        subject_profile,
        planning_submission=subject_planning,
    )
    baseline_observation = _observe(
        case,
        baseline_package.planning_submission,
        baseline_package.execution_profile,
        baseline_plan,
    )
    subject_observation = _observe(
        case,
        subject_planning,
        subject_profile,
        subject_plan,
    )
    baseline_metrics = _metric_map(baseline_observation)
    subject_metrics = _metric_map(subject_observation)
    clauses = {
        "jerk_improves_by_at_least_0_10m_s3": (
            subject_metrics["DY_JERK"] <= baseline_metrics["DY_JERK"] - 0.10
        ),
        "duration_increases_by_at_least_0_10s": (
            subject_metrics["TM_DURATION"] >= baseline_metrics["TM_DURATION"] + 0.10
        ),
        "radial_equal_within_0_0001m": abs(
            subject_metrics["SP_RADIAL"] - baseline_metrics["SP_RADIAL"]
        )
        <= 1e-4,
        "reference_equal_within_0_0001m": abs(
            subject_metrics["SP_REFERENCE"] - baseline_metrics["SP_REFERENCE"]
        )
        <= 1e-4,
        "capture_passes": subject_metrics["SP_CAPTURE"] <= 1e-4,
    }
    output.append(
        {
            "proposal_key": "1d.curved_route.canonical_nominal/curve.jerk_first",
            "axis": "SCALAR_PARAMETER",
            "axis_value": "duration_scale_1_30",
            "baseline": baseline_observation,
            "subject": subject_observation,
            "relation_evaluation": {
                "clauses": clauses,
                "passed": all(clauses.values()),
            },
        }
    )
    return output


def _synchronized_planning(case: Any, submission_id: str) -> Any:
    source = resolve_planning_submission(case, submission_id, require_executable=False)
    return source.model_copy(
        update={
            "coordination": source.coordination.model_copy(
                update=SYNCHRONIZED_FIXED_INPUTS
            )
        }
    )


def _atomic_pair_prototypes(catalog: CampaignCatalog, planner: BoundedJointPlanner) -> Any:
    pairs = (
        (
            "head_on.authority",
            "2d.head_on_conflict.canonical_nominal",
            "head_on.synchronized_lateral",
            "head_on.synchronized_vertical",
        ),
        (
            "head_on.objective",
            "2d.head_on_conflict.canonical_nominal",
            "head_on.path_fidelity_combined",
            "head_on.robustness_combined",
        ),
        (
            "merge.authority",
            "2d.merge.canonical_nominal",
            "merge.parallel_lanes",
            "merge.vertical_stack",
        ),
        (
            "crossing.authority",
            "2d.perpendicular_crossing.nominal_equal_priority",
            "crossing.synchronized_lateral",
            "crossing.synchronized_vertical",
        ),
        (
            "merge3.authority",
            "3d.merge.canonical_nominal",
            "merge.parallel_capacity",
            "merge.vertical_capacity",
        ),
        (
            "center.authority",
            "3d.simultaneous_center_conflict.joint_schedule_v2",
            "center.synchronized_lateral",
            "center.synchronized_layers",
        ),
    )
    output = []
    for pair_id, case_id, left_id, right_id in pairs:
        case = catalog.get(case_id)
        profile = resolve_planning_package(case).execution_profile
        members = []
        for submission_id in (left_id, right_id):
            planning = _bound_profile(
                _synchronized_planning(case, submission_id),
                profile,
            )
            plan = planner.plan(case, profile, planning_submission=planning)
            member: dict[str, Any] = {
                "proposal_key": f"{case_id}/{submission_id}",
                "planning_status": plan.status.value,
                "search_disposition": plan.search_disposition.value,
                "bounded_search_complete": plan.bounded_search_complete,
                "blocking_reason": plan.blocking_reason,
                "plan_sha256": plan.plan_sha256,
                "retained_candidate_sha256s": [
                    item.candidate_sha256 for item in plan.retained_candidates
                ],
            }
            if plan.status is PlanningStatus.READY:
                member["accepted_observation"] = _observe(
                    case,
                    planning,
                    profile,
                    plan,
                )
            members.append(member)
        output.append(
            {
                "pair_id": pair_id,
                "case_id": case_id,
                "fixed_inputs": SYNCHRONIZED_FIXED_INPUTS,
                "members": members,
                "prefreeze_disposition": (
                    "BOTH_READY"
                    if all(item["planning_status"] == "READY" for item in members)
                    else "BOTH_REMAIN_PLANNED_NOT_EXECUTABLE"
                ),
            }
        )
    return output


def _argmax_prototype(catalog: CampaignCatalog, planner: BoundedJointPlanner) -> Any:
    case = catalog.get("3d.simultaneous_center_conflict.joint_schedule_v2")
    profile = resolve_planning_package(case).execution_profile
    baseline = resolve_planning_submission(case, None, require_executable=False)
    source = resolve_planning_submission(
        case,
        "center.robust_combined",
        require_executable=False,
    )
    planning = _bound_profile(
        baseline.model_copy(
            update={
                "planning_submission_id": "center.robust_combined.argmax_bounded_v1",
                "objective": source.objective,
                "experiment_id": source.experiment_id,
                "experiment_axis": source.experiment_axis,
                "axis_value": source.axis_value,
                "admission": source.admission,
                "coordination": baseline.coordination.model_copy(
                    update=SYNCHRONIZED_FIXED_INPUTS
                ),
            }
        ),
        profile,
    )
    plan = planner.plan(case, profile, planning_submission=planning)
    candidates = []
    eligible: list[tuple[float, str]] = []
    for index, candidate in enumerate(plan.retained_candidates):
        certificate = certify_candidate_routes(
            case,
            planning,
            candidate.candidate_sha256,
            candidate.routes,
        )
        entry: dict[str, Any] = {
            "retained_index": index,
            "candidate_sha256": candidate.candidate_sha256,
            "strategy": candidate.strategy.value,
            "generator_id": candidate.generator_id,
            "parameters": candidate.parameters,
            "sampled_status": candidate.status.value,
            "sampled_rejection_reasons": candidate.rejection_reasons,
            "candidate_cost": candidate.cost.model_dump(mode="json"),
            "independent_certificate": certificate.model_dump(mode="json"),
        }
        if candidate.status is CandidateStatus.FEASIBLE and certificate.passed:
            candidate_plan = plan.model_copy(
                update={
                    "status": PlanningStatus.READY,
                    "selected_candidate_index": index,
                    "selected_candidate_sha256": candidate.candidate_sha256,
                    "feasibility_certificate": certificate,
                }
            )
            try:
                observation = _observe(
                    case,
                    planning,
                    profile,
                    candidate_plan,
                )
            except ValueError as error:
                entry["trajectory_disposition"] = {
                    "status": "REJECTED",
                    "reason": str(error),
                }
            else:
                entry["trajectory_disposition"] = {
                    "status": "ACCEPTED",
                    "observation": observation,
                }
                clearance = float(_metric_map(observation)["SP_CLEARANCE"])
                eligible.append((clearance, candidate.candidate_sha256))
        candidates.append(entry)
    if not eligible:
        raise ValueError("ARGMAX_BOUNDED prototype has no accepted candidate")
    maximum = max(value for value, _ in eligible)
    tied = sorted(
        sha for value, sha in eligible if abs(value - maximum) <= 1e-12
    )
    selected = tied[0]
    return {
        "proposal_key": (
            "3d.simultaneous_center_conflict.joint_schedule_v2/center.robust_combined"
        ),
        "candidate_family": {
            "source": "BoundedJointPlanner retained candidates under exact R2 case/search bounds",
            "generated_candidate_count": plan.generated_candidate_count,
            "retained_candidate_count": plan.retained_candidate_count,
            "truncated": plan.truncated,
            "bounded_search_complete": plan.bounded_search_complete,
        },
        "oracle": "ARGMAX_BOUNDED(SP_CLEARANCE)",
        "tie_tolerance_m": 1e-12,
        "tie_break": "lexicographically smallest candidate_sha256",
        "maximum_clearance_m": maximum,
        "tied_candidate_sha256s": tied,
        "selected_candidate_sha256": selected,
        "candidates": candidates,
    }


def build_audit() -> dict[str, Any]:
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    planner = BoundedJointPlanner()
    registry = load_case_submission_registry()
    payload = {
        "schema_version": 1,
        "audit_id": "wp52-56-r6-complete-numerical-predraft-v1",
        "prototype_command": (
            "./.venv/bin/python scripts/audit_wp52_56_r6_design.py --check"
        ),
        "base_commit": "4bec32a827785f5c25cb32a4f2084ced8045f3b3",
        "source_identities": {
            "r5_classification_audit_path": str(R5_AUDIT.relative_to(ROOT)),
            "r5_classification_audit_file_sha256": _file_sha256(R5_AUDIT),
            "case_submission_registry_sha256": canonical_sha256(registry),
            "case_tree": sorted(
                {
                    case.case_id: case.case_sha256
                    for case in catalog.cases()
                }.items()
            ),
        },
        "r6_classification_correction": {
            "r5_collapse_count": 29,
            "removed_collapse_key": (
                "2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release"
            ),
            "reason": (
                "the hash-distinct capacity baseline selects HORIZONTAL_DETOUR while the "
                "subject selects GROUND_DELAY and improves SP_REFERENCE outside the frozen "
                "distinctness threshold"
            ),
            "r6_collapse_count": 28,
            "r6_visible_relation_count": 83,
        },
        "contracts": {
            "sample_step_s": 0.01,
            "capacity_context_id": CAPACITY_CONTEXT_ID,
            "capacity_context_sha256": CAPACITY_CONTEXT_SHA256,
            "synchronized_fixed_inputs": SYNCHRONIZED_FIXED_INPUTS,
            "metric_sets": {
                case.case_id: list(admission_record_for_case(case).metric_ids)
                for case in catalog.cases()
                if case.case_id
                in {
                    "1d.continuous_waypoint_sequence.canonical_nominal",
                    "1d.curved_route.canonical_nominal",
                    "1d.planar_shape_loop.figure_eight",
                    "2d.head_on_conflict.canonical_nominal",
                    "2d.merge.canonical_nominal",
                    "2d.perpendicular_crossing.nominal_equal_priority",
                    "3d.simultaneous_center_conflict.joint_schedule_v2",
                }
            },
        },
        "execution_profile_prototypes": _profile_prototypes(catalog, planner),
        "capacity_context_prototypes": _capacity_prototypes(catalog, planner),
        "synchronized_atomic_pair_prototypes": _atomic_pair_prototypes(catalog, planner),
        "center_robust_argmax_bounded_prototype": _argmax_prototype(catalog, planner),
    }
    return {**payload, "audit_sha256": canonical_sha256(payload)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    audit = build_audit()
    rendered = json.dumps(audit, indent=2, sort_keys=True) + "\n"
    if arguments.check:
        retained = arguments.output.read_text(encoding="utf-8")
        if retained != rendered:
            raise SystemExit("R6 numerical pre-draft audit is stale")
        print(audit["audit_sha256"])
        return
    if arguments.write:
        arguments.output.write_text(rendered, encoding="utf-8")
        print(arguments.output)
        print(audit["audit_sha256"])
        return
    print(rendered, end="")


if __name__ == "__main__":
    main()
