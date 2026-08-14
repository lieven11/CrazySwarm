#!/usr/bin/env python3
"""Qualify the selective 55-case submission registry through production planning."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import tempfile
from itertools import pairwise
from pathlib import Path
from typing import Any

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.planner import (
    BoundedJointPlanner,
    PlanningStatus,
    SearchDisposition,
)
from crazyswarm_app.campaign.service import CampaignService
from crazyswarm_app.campaign.submission_measurement import (
    compare_for_collapse,
    measure_planning_behavior,
)
from crazyswarm_app.campaign.submissions import (
    BASELINE_PLANNING_SUBMISSION_ID,
    CapabilityFeasibilityDisposition,
    SubmissionStatus,
    admission_record_for_case,
    compile_registry_planning_submission,
    load_capability_registry,
    load_case_submission_registry,
    planning_submissions_for_case,
    registry_row_for_case,
    resolve_capability_resolution,
    resolve_planning_package,
    resolve_submission,
    validate_registry_coverage,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.simulation import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "missions/campaigns/sim/qualification/selective-submission-registry-v1.json"
UI_INSPECTION = (
    ROOT / "missions/campaigns/sim/qualification/selective-submission-ui-inspection-v1.json"
)


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
    a0 = start
    a1 = start_velocity
    a2 = start_acceleration / 2.0
    c0 = end - (a0 + a1 * duration_s + a2 * duration_s**2)
    c1 = end_velocity - (a1 + 2.0 * a2 * duration_s)
    c2 = end_acceleration - 2.0 * a2
    a3 = (10.0 * c0 - 4.0 * c1 * duration_s + 0.5 * c2 * duration_s**2) / duration_s**3
    a4 = (-15.0 * c0 + 7.0 * c1 * duration_s - c2 * duration_s**2) / duration_s**4
    a5 = (6.0 * c0 - 3.0 * c1 * duration_s + 0.5 * c2 * duration_s**2) / duration_s**5
    value = max(0.0, min(duration_s, elapsed_s))
    position = a0 + a1 * value + a2 * value**2 + a3 * value**3 + a4 * value**4 + a5 * value**5
    velocity = (
        a1 + 2.0 * a2 * value + 3.0 * a3 * value**2 + 4.0 * a4 * value**3 + 5.0 * a5 * value**4
    )
    acceleration = 2.0 * a2 + 6.0 * a3 * value + 12.0 * a4 * value**2 + 20.0 * a5 * value**3
    return position, velocity, acceleration


def _independent_samples(trajectory: Any, step_s: float = 0.02) -> list[dict[str, Any]]:
    times = [point.time_from_start_s for point in trajectory.points]
    samples = []
    timestamp = 0.0
    while timestamp <= trajectory.duration_s + step_s * 0.25:
        bounded = min(timestamp, trajectory.duration_s)
        index = max(0, min(len(times) - 2, bisect.bisect_right(times, bounded) - 1))
        before = trajectory.points[index]
        after = trajectory.points[index + 1]
        duration = after.time_from_start_s - before.time_from_start_s
        axes = [
            _quintic_axis(
                getattr(before.position_m, axis),
                getattr(before.velocity_m_s, axis),
                getattr(before.acceleration_m_s2, axis),
                getattr(after.position_m, axis),
                getattr(after.velocity_m_s, axis),
                getattr(after.acceleration_m_s2, axis),
                duration,
                bounded - before.time_from_start_s,
            )
            for axis in ("x", "y", "z")
        ]
        samples.append(
            {
                "time_s": round(bounded, 9),
                "position": tuple(item[0] for item in axes),
                "velocity": tuple(item[1] for item in axes),
                "acceleration": tuple(item[2] for item in axes),
            }
        )
        timestamp += step_s
    return samples


def _point_segment_distance(point: tuple[float, ...], start: Any, end: Any) -> float:
    a = (start.x, start.y, start.z)
    b = (end.x, end.y, end.z)
    delta = tuple(b[index] - a[index] for index in range(3))
    denominator = sum(value * value for value in delta)
    if denominator <= 1e-18:
        return math.dist(point, a)
    projection = max(
        0.0,
        min(1.0, sum((point[index] - a[index]) * delta[index] for index in range(3)) / denominator),
    )
    closest = tuple(a[index] + projection * delta[index] for index in range(3))
    return math.dist(point, closest)


def _independent_oracle(trajectory: Any, route: Any) -> dict[str, Any]:
    samples = _independent_samples(trajectory)
    maximum_deviation = max(
        min(
            _point_segment_distance(sample["position"], before, after)
            for before, after in pairwise(route.points_m)
        )
        for sample in samples
    )
    jerks = [
        math.dist(after["acceleration"], before["acceleration"])
        / (after["time_s"] - before["time_s"])
        for before, after in pairwise(samples)
        if after["time_s"] > before["time_s"]
    ]
    return {
        "oracle_id": "independent-local-quintic-dense-sampler-v1",
        "sample_step_s": 0.02,
        "sample_count": len(samples),
        "samples_sha256": canonical_sha256(samples),
        "maximum_reference_polyline_deviation_m": maximum_deviation,
        "maximum_finite_difference_jerk_m_s3": max(jerks, default=0.0),
        "terminal_position_m": samples[-1]["position"],
    }


def main() -> None:
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    cases = tuple(sorted(catalog.cases(), key=lambda item: item.case_id))
    registry = load_case_submission_registry()
    validate_registry_coverage(cases)
    planner = BoundedJointPlanner()

    rows = []
    executable_planning_count = 0
    planning_failures = []
    collapse_failures = []
    collapsed_results: list[dict[str, Any]] = []
    for case in cases:
        registry_row = next(item for item in registry.rows if item.case_id == case.case_id)
        compiled = planning_submissions_for_case(case)
        baseline = next(
            item
            for item in compiled
            if item.planning_submission_id == BASELINE_PLANNING_SUBMISSION_ID
        )
        baseline_plan = (
            planner.plan(case, planning_submission=baseline)
            if baseline.status is SubmissionStatus.EXECUTABLE
            else None
        )
        metric_ids = admission_record_for_case(case).metric_ids
        baseline_measurement = (
            measure_planning_behavior(case, baseline, baseline_plan, metric_ids)
            if baseline_plan is not None
            and baseline_plan.status is PlanningStatus.READY
            and baseline_plan.selected is not None
            else None
        )
        planning_results = []
        for submission in compiled[1:]:
            result: dict[str, Any] = {
                "planning_submission_id": submission.planning_submission_id,
                "status": submission.status.value,
                "semantic_fingerprint_sha256": submission.semantic_fingerprint_sha256,
                "support_reason": submission.support_reason,
                "claim_boundary": (
                    ["INTEGRATION", "NO_RUNTIME", "NOT_APPLICABLE"]
                    if submission.status is SubmissionStatus.EXECUTABLE
                    else ["MODEL_ONLY", "NO_RUNTIME", "NOT_APPLICABLE"]
                ),
            }
            if submission.status is SubmissionStatus.EXECUTABLE:
                executable_planning_count += 1
                planned = planner.plan(case, planning_submission=submission)
                measurement = (
                    measure_planning_behavior(case, submission, planned, metric_ids)
                    if planned.status is PlanningStatus.READY and planned.selected is not None
                    else None
                )
                baseline_comparison = (
                    compare_for_collapse(
                        hidden_submission=submission,
                        visible_submission=baseline,
                        hidden=measurement,
                        visible=baseline_measurement,
                    )
                    if measurement is not None and baseline_measurement is not None
                    else None
                )
                result.update(
                    {
                        "planning_status": planned.status.value,
                        "plan_sha256": planned.plan_sha256,
                        "selected_candidate_sha256": (
                            planned.selected.candidate_sha256 if planned.selected else None
                        ),
                        "selected_strategy": (
                            planned.selected.strategy.value if planned.selected else None
                        ),
                        "behavior_differs_from_baseline": (
                            baseline_comparison is not None
                            and not baseline_comparison.collapse_proven
                        ),
                        "independent_measurement": (
                            measurement.model_dump(mode="json") if measurement else None
                        ),
                        "baseline_metric_comparison": (
                            baseline_comparison.model_dump(mode="json")
                            if baseline_comparison
                            else None
                        ),
                        "continuous_feasibility_passed": bool(
                            planned.feasibility_certificate
                            and planned.feasibility_certificate.passed
                        ),
                    }
                )
                if (
                    planned.status is not PlanningStatus.READY
                    or planned.selected is None
                    or baseline_comparison is None
                    or baseline_comparison.collapse_proven
                    or planned.feasibility_certificate is None
                    or not planned.feasibility_certificate.passed
                ):
                    planning_failures.append(f"{case.case_id}:{submission.planning_submission_id}")
            planning_results.append(result)
        for hidden in (item for item in registry_row.submissions if not item.catalog_visible):
            compiled_hidden = compile_registry_planning_submission(
                case,
                hidden,
                audit_hidden=True,
            )
            hidden_plan = planner.plan(case, planning_submission=compiled_hidden)
            hidden_candidate = (
                hidden_plan.selected.candidate_sha256 if hidden_plan.selected is not None else None
            )
            hidden_measurement = (
                measure_planning_behavior(case, compiled_hidden, hidden_plan, metric_ids)
                if hidden_plan.status is PlanningStatus.READY
                and hidden_plan.selected is not None
                else None
            )
            collapse_evidence = (
                compare_for_collapse(
                    hidden_submission=compiled_hidden,
                    visible_submission=baseline,
                    hidden=hidden_measurement,
                    visible=baseline_measurement,
                )
                if hidden_measurement is not None and baseline_measurement is not None
                else None
            )
            collapse_proven = bool(
                collapse_evidence is not None and collapse_evidence.collapse_proven
            )
            collapse_result = {
                "case_id": case.case_id,
                "submission_id": hidden.submission_id,
                "compiled_semantic_fingerprint_sha256": (
                    compiled_hidden.semantic_fingerprint_sha256
                ),
                "plan_sha256": hidden_plan.plan_sha256,
                "selected_candidate_sha256": hidden_candidate,
                "equivalent_visible_submission_ids": (
                    (BASELINE_PLANNING_SUBMISSION_ID,) if collapse_proven else ()
                ),
                "independent_collapse_evidence": (
                    collapse_evidence.model_dump(mode="json")
                    if collapse_evidence is not None
                    else None
                ),
                "collapse_proven": collapse_proven,
                "claim_boundary": ["INTEGRATION", "NO_RUNTIME", "NOT_APPLICABLE"],
            }
            collapsed_results.append(collapse_result)
            if not collapse_proven:
                collapse_failures.append(f"{case.case_id}:{hidden.submission_id}")
        rows.append(
            {
                "case_id": case.case_id,
                "case_sha256": case.case_sha256,
                "dimension": (
                    "3d"
                    if case.case_id.startswith("3d.")
                    or case.case_id == "three_drone_multi_conflict"
                    else case.case_id[:2]
                ),
                "implementation_status": case.implementation_status.value,
                "baseline_only": registry_row.baseline_only,
                "retain_existing_only": registry_row.retain_existing_only,
                "baseline_only_rationale": registry_row.baseline_only_rationale,
                "registry_submissions": [
                    item.model_dump(mode="json") for item in registry_row.submissions
                ],
                "planning_results": planning_results,
            }
        )

    anchor_ids = {
        "1d.takeoff_hover_land.canonical_nominal": (
            "vertical_cycle.precision_first",
            "vertical_cycle.minimum_duration",
        ),
        "1d.planar_shape_loop.circle": ("core.constant_path_speed",),
        "1d.planar_shape_loop.rounded_square": ("corner_transition.lookahead_0_60s",),
    }
    anchor_results: list[dict[str, Any]] = []
    for case_id, submission_ids in anchor_ids.items():
        case = catalog.get(case_id)
        for submission_id in submission_ids:
            profile = resolve_submission(case, submission_id)
            package = resolve_planning_package(
                case,
                execution_profile_submission_id=submission_id,
            )
            plan = planner.plan(
                case,
                profile,
                planning_submission=package.planning_submission,
                capability_resolution=package.capability_resolution,
                first_certified_within_budget=True,
            )
            if plan.status is not PlanningStatus.READY or plan.selected is None:
                raise RuntimeError(f"anchor planning failed: {case_id}:{submission_id}")
            trajectories = generate_smooth_trajectories(
                case,
                plan.selected,
                submission=profile,
                planning_submission=package.planning_submission,
                capability_resolution=package.capability_resolution,
            )
            anchor_results.append(
                {
                    "case_id": case_id,
                    "case_sha256": case.case_sha256,
                    "submission_id": submission_id,
                    "profile_sha256": profile.profile_sha256,
                    "semantic_fingerprint_sha256": profile.semantic_fingerprint_sha256,
                    "resolved_package_sha256": package.resolved_package_sha256,
                    "capability_resolution": (
                        package.capability_resolution.model_dump(mode="json")
                        if package.capability_resolution
                        else None
                    ),
                    "plan_sha256": plan.plan_sha256,
                    "trajectory_set_sha256": trajectories.set_sha256,
                    "trajectory_duration_s": trajectories.trajectories[0].duration_s,
                    "transition_start_distance_m": math.dist(
                        (
                            trajectories.trajectories[0].points[0].position_m.x,
                            trajectories.trajectories[0].points[0].position_m.y,
                            trajectories.trajectories[0].points[0].position_m.z,
                        ),
                        (
                            trajectories.trajectories[0].points[1].position_m.x,
                            trajectories.trajectories[0].points[1].position_m.y,
                            trajectories.trajectories[0].points[1].position_m.z,
                        ),
                    ),
                    "profile_audits_passed": all(
                        item.passed for item in trajectories.profile_audits
                    ),
                    "dynamics_audits_passed": all(item.passed for item in trajectories.audits),
                    "independent_oracle": _independent_oracle(
                        trajectories.trajectories[0], plan.selected.routes[0]
                    ),
                    "claim_boundary": [
                        "INTEGRATION",
                        "NO_RUNTIME",
                        "NOT_APPLICABLE",
                    ],
                }
            )

    rejected_corner_case = catalog.get("1d.planar_shape_loop.rounded_square")
    rejected_corner_profile = resolve_submission(
        rejected_corner_case,
        "corner_transition.lookahead_0_20s",
        require_executable=False,
    )
    rejected_corner_resolution = resolve_capability_resolution(
        rejected_corner_case,
        rejected_corner_profile,
    )
    assert rejected_corner_resolution is not None
    rejected_corner_plan = planner.plan(
        rejected_corner_case,
        rejected_corner_profile,
        capability_resolution=rejected_corner_resolution,
    )
    corner_rejection = {
        "case_id": rejected_corner_case.case_id,
        "submission_id": rejected_corner_profile.submission_id,
        "status": rejected_corner_profile.status.value,
        "support_reason": next(
            item.support_reason
            for item in registry_row_for_case(rejected_corner_case).submissions
            if item.submission_id == rejected_corner_profile.submission_id
        ),
        "capability_resolution": rejected_corner_resolution.model_dump(mode="json"),
        "planning_status": rejected_corner_plan.status.value,
        "search_disposition": rejected_corner_plan.search_disposition.value,
        "bounded_search_complete": rejected_corner_plan.bounded_search_complete,
        "blocking_reason": rejected_corner_plan.blocking_reason,
        "safe_rejection_proven": (
            rejected_corner_profile.status is SubmissionStatus.PLANNED_NOT_EXECUTABLE
            and rejected_corner_plan.status is PlanningStatus.BLOCKED
            and rejected_corner_plan.search_disposition
            is SearchDisposition.PROVEN_INFEASIBLE_WITHIN_DECLARED_BOUNDS
            and rejected_corner_plan.bounded_search_complete
            and rejected_corner_resolution.feasibility is not None
            and rejected_corner_resolution.feasibility.disposition
            is CapabilityFeasibilityDisposition.PROVEN_INFEASIBLE
            and rejected_corner_resolution.feasibility.violated_constraints
            == ("DEADLINE_VIOLATION",)
        ),
        "claim_boundary": ["INTEGRATION", "NO_RUNTIME", "NOT_APPLICABLE"],
    }

    production_preview_results = []
    with tempfile.TemporaryDirectory(prefix="wp52-56-production-preview-") as temporary:
        service = CampaignService(
            catalog=CampaignCatalog(ROOT / "missions/campaigns/sim/cases"),
            state_directory=Path(temporary),
        )
        for case_id, submission_ids in anchor_ids.items():
            for submission_id in submission_ids:
                service.set_active(
                    case_id,
                    actor_id="wp52-56-qualification",
                    reason="normal production preview qualification",
                )
                plan, schedule, trajectories = service.preview_active(
                    submission_id=submission_id,
                )
                production_preview_results.append(
                    {
                        "case_id": case_id,
                        "submission_id": submission_id,
                        "plan_sha256": plan.plan_sha256,
                        "schedule_sha256": schedule.schedule_sha256,
                        "trajectory_set_sha256": trajectories.set_sha256,
                        "profile_audits_passed": all(
                            item.passed for item in trajectories.profile_audits
                        ),
                        "claim_boundary": [
                            "PRODUCTION_ENTRY",
                            "NO_RUNTIME",
                            "NOT_APPLICABLE",
                        ],
                    }
                )

    by_submission: dict[str, dict[str, Any]] = {
        str(item["submission_id"]): item for item in anchor_results
    }
    duration_pair: list[dict[str, Any]] = [
        by_submission["vertical_cycle.precision_first"],
        by_submission["vertical_cycle.minimum_duration"],
    ]
    corner_anchor = by_submission["corner_transition.lookahead_0_60s"]
    comparisons: dict[str, dict[str, Any]] = {
        "vertical_cycle": {
            "plan_hashes_distinct": len({item["plan_sha256"] for item in duration_pair}) == 2,
            "trajectory_hashes_distinct": len(
                {item["trajectory_set_sha256"] for item in duration_pair}
            )
            == 2,
            "durations_distinct": not math.isclose(
                duration_pair[0]["trajectory_duration_s"],
                duration_pair[1]["trajectory_duration_s"],
                abs_tol=1e-6,
            ),
        },
        "corner_transition": {
            "executable_request_time_s": corner_anchor["capability_resolution"][
                "authored_lookahead_time_s"
            ],
            "executable_derived_distance_m": corner_anchor["capability_resolution"][
                "derived_lookahead_distance_m"
            ],
            "trajectory_consumes_resolved_distance": math.isclose(
                corner_anchor["transition_start_distance_m"],
                corner_anchor["capability_resolution"]["derived_lookahead_distance_m"],
                abs_tol=1e-9,
            ),
            "short_lookahead_safe_rejection": corner_rejection["safe_rejection_proven"],
        },
    }
    ui_inspection = json.loads(UI_INSPECTION.read_text(encoding="utf-8"))
    ui_source_css = ROOT / "ui/app/globals.css"
    current_release = (ROOT / "ui/.crazyswarm-builds/current").resolve(strict=True)
    built_css_paths = tuple((current_release / "dist/client/assets").glob("*.css"))
    if len(built_css_paths) != 1:
        raise SystemExit("selective submission qualification found no unique production CSS")
    built_css = built_css_paths[0]
    source_css_sha256 = hashlib.sha256(ui_source_css.read_bytes()).hexdigest()
    built_css_sha256 = hashlib.sha256(built_css.read_bytes()).hexdigest()
    built_css_text = built_css.read_text(encoding="utf-8")
    ui_build_attested = (
        ui_inspection["production_build"]["release_name"] == current_release.name
        and ui_inspection["production_build"]["source_css_sha256"] == source_css_sha256
        and ui_inspection["production_build"]["built_css_sha256"] == built_css_sha256
        and "@media (width<=900px)" in built_css_text
    )
    passed = (
        not planning_failures
        and not collapse_failures
        and all(
            item["profile_audits_passed"] and item["dynamics_audits_passed"]
            for item in anchor_results
        )
        and all(item["profile_audits_passed"] for item in production_preview_results)
        and all(comparisons["vertical_cycle"].values())
        and comparisons["corner_transition"]["trajectory_consumes_resolved_distance"]
        and comparisons["corner_transition"]["short_lookahead_safe_rejection"]
        and ui_build_attested
    )
    payload = {
        "schema_version": 1,
        "qualification_id": "selective-submission-registry-v1",
        "claim": (
            "Registry-wide planning and independent trajectory oracles are integration/no-runtime; "
            "the four executable anchors additionally pass the normal production preview entry "
            "without starting a simulator or issuing commands."
        ),
        "reviewed_counts": registry.reviewed_counts,
        "case_count": len(rows),
        "registry_submission_count": sum(len(item.submissions) for item in registry.rows),
        "collapsed_submission_count": sum(
            not item.catalog_visible for row in registry.rows for item in row.submissions
        ),
        "executable_planning_alternative_count": executable_planning_count,
        "capability_registry": load_capability_registry().model_dump(mode="json"),
        "rows": rows,
        "collapsed_results": collapsed_results,
        "collapse_failures": collapse_failures,
        "anchor_results": anchor_results,
        "anchor_comparisons": comparisons,
        "corner_rejection": corner_rejection,
        "production_preview_results": production_preview_results,
        "ui_inspection": {
            "path": str(UI_INSPECTION.relative_to(ROOT)),
            "sha256": canonical_sha256(ui_inspection),
            "passed": ui_inspection["passed"],
            "visual_recheck_required": ui_inspection["visual_recheck_required"],
            "production_build_attested": ui_build_attested,
            "release_name": current_release.name,
            "source_css_sha256": source_css_sha256,
            "built_css_sha256": built_css_sha256,
        },
        "planning_failures": planning_failures,
        "passed": passed,
    }
    payload["report_sha256"] = canonical_sha256(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not passed:
        raise SystemExit("selective submission qualification failed")


if __name__ == "__main__":
    from qualify_submission_registry_r6 import main as r6_main

    r6_main()
