#!/usr/bin/env python3
"""Qualify the verified WP-52--56 R6 registry without overstating runtime scope."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.planner import BoundedJointPlanner, PlanningStatus
from crazyswarm_app.campaign.service import CampaignService
from crazyswarm_app.campaign.submission_measurement import (
    _independent_samples,
    compare_for_collapse,
    derive_sampled_route_semantics,
    measure_planning_behavior,
)
from crazyswarm_app.campaign.submissions import (
    BASELINE_PLANNING_SUBMISSION_ID,
    AdmissionLifecycle,
    PlanningSelectionOracle,
    SubmissionStatus,
    admission_record_for_case,
    compile_registry_planning_submission,
    load_admission_registry,
    load_case_submission_registry,
    proposal_oracle_for_case,
    registry_row_for_case,
    resolve_planning_package,
    resolve_planning_submission,
    validate_registry_coverage,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.simulation import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "missions/campaigns/sim/qualification/selective-submission-registry-v1.json"
UI_INSPECTION = (
    ROOT / "missions/campaigns/sim/qualification/selective-submission-ui-inspection-v1.json"
)
R6_DESIGN_EVIDENCE = ROOT / "docs/work-packages/WP52_56_R6_NUMERICAL_PREDRAFT_AUDIT_2026-08-12.json"

PROFILE_KEYS = (
    (
        "1d.continuous_waypoint_sequence.canonical_nominal",
        "waypoint.smoothness_first",
    ),
    ("1d.curved_route.canonical_nominal", "curve.jerk_first"),
    (
        "1d.planar_shape_loop.figure_eight",
        "loop.curvature_continuity",
    ),
)
CAPACITY_KEYS = (
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
ATOMIC_PAIRS = (
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


def _metric_map(measurement: Any) -> dict[str, Any]:
    return {item.metric_id: item.value for item in measurement.metrics}


def _plan_package(
    planner: BoundedJointPlanner,
    case: Any,
    *,
    planning_submission_id: str | None = None,
    execution_profile_submission_id: str | None = None,
    comparison_context_id: str | None = None,
) -> tuple[Any, Any, Any]:
    package = resolve_planning_package(
        case,
        planning_submission_id,
        execution_profile_submission_id,
        comparison_context_id=comparison_context_id,
    )
    plan = planner.plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
    )
    if plan.status is not PlanningStatus.READY or plan.selected is None:
        raise ValueError(
            f"qualification plan blocked for {case.case_id}: "
            f"{plan.blocking_reason or plan.search_disposition.value}"
        )
    measurement = measure_planning_behavior(
        case,
        package.planning_submission,
        plan,
        admission_record_for_case(case).metric_ids,
        execution_profile=package.execution_profile,
        capability_resolution=package.capability_resolution,
    )
    return package, plan, measurement


def _collapse_results(
    catalog: CampaignCatalog,
    planner: BoundedJointPlanner,
) -> tuple[list[dict[str, Any]], list[str]]:
    results = []
    failures = []
    for registry_row in load_case_submission_registry().rows:
        hidden_specs = tuple(item for item in registry_row.submissions if not item.catalog_visible)
        if not hidden_specs:
            continue
        case = catalog.get(registry_row.case_id)
        try:
            profile = resolve_planning_package(case).execution_profile
        except ValueError as error:
            raise ValueError(
                f"collapse baseline unavailable for {case.case_id}: {error}"
            ) from error
        for hidden in hidden_specs:
            oracle = proposal_oracle_for_case(case, hidden.submission_id)
            compiled_hidden = compile_registry_planning_submission(
                case,
                hidden,
                audit_hidden=True,
            )
            hidden_plan = planner.plan(
                case,
                profile,
                planning_submission=compiled_hidden,
            )
            comparator_id = oracle.comparator_id
            assert comparator_id is not None
            if comparator_id.startswith("PEER("):
                peer_key = comparator_id.removeprefix("PEER(").removesuffix(")")
                peer_case_id, peer_submission_id = peer_key.split("/", 1)
                if peer_case_id != case.case_id:
                    raise ValueError("collapse peer leaves its exact case")
                visible = resolve_planning_submission(case, peer_submission_id)
            else:
                visible = resolve_planning_submission(case, BASELINE_PLANNING_SUBMISSION_ID)
            visible_plan = planner.plan(case, profile, planning_submission=visible)
            metric_ids = admission_record_for_case(case).metric_ids
            hidden_measurement = measure_planning_behavior(
                case,
                compiled_hidden,
                hidden_plan,
                metric_ids,
                execution_profile=profile,
            )
            visible_measurement = measure_planning_behavior(
                case,
                visible,
                visible_plan,
                metric_ids,
                execution_profile=profile,
            )
            evidence = compare_for_collapse(
                hidden_submission=compiled_hidden,
                visible_submission=visible,
                hidden=hidden_measurement,
                visible=visible_measurement,
            )
            key = f"{case.case_id}/{hidden.submission_id}"
            result = {
                "proposal_key": key,
                "comparator_id": comparator_id,
                "hidden_plan_sha256": hidden_plan.plan_sha256,
                "visible_plan_sha256": visible_plan.plan_sha256,
                "evidence": evidence.model_dump(mode="json"),
                "collapse_proven": evidence.collapse_proven,
                "claim_boundary": ["INTEGRATION", "NO_RUNTIME", "NOT_APPLICABLE"],
            }
            results.append(result)
            if not evidence.collapse_proven:
                failures.append(key)
    return results, failures


def _profile_counterexamples(case: Any, package: Any, plan: Any) -> dict[str, Any]:
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
    output: dict[str, Any] = {}
    if case.case_id == "1d.continuous_waypoint_sequence.canonical_nominal":
        stopped = {}
        persistence = case.hard_constraints.dynamics.unintended_stop_persistence_s
        for role_id, values in samples.items():
            pivot = len(values) // 2
            pivot_time = values[pivot]["time_s"]
            pivot_position = values[pivot]["position_m"]
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
        observation = derive_sampled_route_semantics(case, plan.selected.routes, stopped)
        output["inserted_interior_stop"] = {
            "observation": observation,
            "rejected": observation["DS_UNINTENDED_STOP_COUNT"] >= 1,
        }
    if case.case_id == "1d.planar_shape_loop.figure_eight":
        reordered = {}
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
        observation = derive_sampled_route_semantics(case, plan.selected.routes, reordered)
        output["reordered_traversal"] = {
            "observation": observation,
            "rejected": observation["DS_TOPOLOGY"] == "order_violation",
        }
    return output


def _profile_results(
    catalog: CampaignCatalog,
    planner: BoundedJointPlanner,
) -> list[dict[str, Any]]:
    results = []
    for case_id, submission_id in PROFILE_KEYS:
        case = catalog.get(case_id)
        baseline_package, baseline_plan, baseline_measurement = _plan_package(planner, case)
        package, plan, measurement = _plan_package(
            planner,
            case,
            execution_profile_submission_id=submission_id,
        )
        baseline = _metric_map(baseline_measurement)
        subject = _metric_map(measurement)
        if submission_id == "waypoint.smoothness_first":
            clauses = {
                "curvature": subject["DY_CURVATURE"] <= baseline["DY_CURVATURE"] - 0.05,
                "reference": subject["SP_REFERENCE"] <= baseline["SP_REFERENCE"] - 0.01,
                "duration": subject["TM_DURATION"] >= baseline["TM_DURATION"] + 0.10,
                "capture": subject["SP_CAPTURE"] <= 1e-4,
                "unintended_stops": subject["DS_UNINTENDED_STOP_COUNT"] == 0,
            }
        elif submission_id == "curve.jerk_first":
            clauses = {
                "jerk": subject["DY_JERK"] <= baseline["DY_JERK"] - 0.10,
                "duration": subject["TM_DURATION"] >= baseline["TM_DURATION"] + 0.10,
                "radial": abs(subject["SP_RADIAL"] - baseline["SP_RADIAL"]) <= 1e-4,
                "reference": abs(subject["SP_REFERENCE"] - baseline["SP_REFERENCE"]) <= 1e-4,
                "capture": subject["SP_CAPTURE"] <= 1e-4,
            }
        else:
            expected_order = tuple(
                goal.region_id for drone in case.drones for goal in drone.goal_sequence
            )
            clauses = {
                "curvature": subject["DY_CURVATURE"] <= baseline["DY_CURVATURE"] - 0.05,
                "reference": subject["SP_REFERENCE"] <= baseline["SP_REFERENCE"] - 0.01,
                "capture": subject["SP_CAPTURE"] <= 1e-4,
                "topology": subject["DS_TOPOLOGY"] == "figure_eight",
                "lobe_order": tuple(subject["DS_LOBE_ORDER"]) == expected_order,
            }
        counterexamples = _profile_counterexamples(case, package, plan)
        counterexamples_passed = all(item["rejected"] for item in counterexamples.values())
        results.append(
            {
                "proposal_key": f"{case_id}/{submission_id}",
                "baseline_package_sha256": baseline_package.resolved_package_sha256,
                "subject_package_sha256": package.resolved_package_sha256,
                "baseline_plan_sha256": baseline_plan.plan_sha256,
                "subject_plan_sha256": plan.plan_sha256,
                "baseline_measurement": baseline_measurement.model_dump(mode="json"),
                "subject_measurement": measurement.model_dump(mode="json"),
                "relation_clauses": clauses,
                "counterexamples": counterexamples,
                "passed": all(clauses.values()) and counterexamples_passed,
                "claim_boundary": ["INTEGRATION", "NO_RUNTIME", "NOT_APPLICABLE"],
            }
        )
    return results


def _capacity_results(
    catalog: CampaignCatalog,
    planner: BoundedJointPlanner,
) -> list[dict[str, Any]]:
    expected_winner = {
        "head_on.earliest_safe_release": (
            "4b58f90649bf145d5226192d413fc03388b73510f6a159e1bdfea0743943626c"
        ),
        "crossing.earliest_equal_release": (
            "cbd3bc0dfea31532c5b8927aedb14248eb42ff1e41d24ffd86dd0b70289f98f1"
        ),
    }
    results = []
    for case_id, submission_id in CAPACITY_KEYS:
        case = catalog.get(case_id)
        baseline_package, baseline_plan, baseline_measurement = _plan_package(
            planner,
            case,
            comparison_context_id="overlap-capacity-v1",
        )
        package, plan, measurement = _plan_package(
            planner,
            case,
            planning_submission_id=submission_id,
            comparison_context_id="overlap-capacity-v1",
        )
        baseline = _metric_map(baseline_measurement)
        subject = _metric_map(measurement)
        clauses = {
            "overlap_both": min(baseline["TM_OVERLAP"], subject["TM_OVERLAP"]) >= 2.0,
            "clearance_both": min(baseline["SP_CLEARANCE"], subject["SP_CLEARANCE"]) >= -1e-9,
        }
        if submission_id == "merge.fair_release":
            clauses["minimum_wait"] = subject["TM_WAIT"] <= baseline["TM_WAIT"] - 0.10
        else:
            clauses.update(
                {
                    "timing_maneuver": subject["DS_MANEUVER"] == "GROUND_DELAY",
                    "complete_family": (
                        plan.generated_candidate_count == 16
                        and plan.retained_candidate_count == 16
                        and not plan.truncated
                        and plan.bounded_search_complete
                    ),
                    "bounded_argmin": (
                        package.planning_submission.selection_oracle
                        is PlanningSelectionOracle.ARGMIN_BOUNDED_RELEASE
                        and plan.selected_candidate_sha256 == expected_winner[submission_id]
                    ),
                }
            )
        results.append(
            {
                "proposal_key": f"{case_id}/{submission_id}",
                "context_id": "overlap-capacity-v1",
                "context_sha256": package.planning_submission.comparison_context_sha256,
                "baseline_package_sha256": baseline_package.resolved_package_sha256,
                "subject_package_sha256": package.resolved_package_sha256,
                "baseline_plan_sha256": baseline_plan.plan_sha256,
                "subject_plan_sha256": plan.plan_sha256,
                "selected_candidate_sha256": plan.selected_candidate_sha256,
                "optimality_claim": plan.optimality_claim,
                "baseline_measurement": baseline_measurement.model_dump(mode="json"),
                "subject_measurement": measurement.model_dump(mode="json"),
                "relation_clauses": clauses,
                "passed": all(clauses.values()),
                "claim_boundary": ["INTEGRATION", "NO_RUNTIME", "NOT_APPLICABLE"],
            }
        )
    return results


def _atomic_results(catalog: CampaignCatalog, planner: BoundedJointPlanner) -> list[dict[str, Any]]:
    results = []
    for pair_id, case_id, left_id, right_id in ATOMIC_PAIRS:
        case = catalog.get(case_id)
        row = registry_row_for_case(case)
        members = []
        for submission_id in (left_id, right_id):
            spec = next(item for item in row.submissions if item.submission_id == submission_id)
            planning = compile_registry_planning_submission(case, spec)
            plan = planner.plan(case, planning_submission=planning)
            members.append(
                {
                    "proposal_key": f"{case_id}/{submission_id}",
                    "catalog_status": spec.status.value,
                    "planning_status": plan.status.value,
                    "search_disposition": plan.search_disposition.value,
                    "bounded_search_complete": plan.bounded_search_complete,
                    "blocking_reason": plan.blocking_reason,
                    "plan_sha256": plan.plan_sha256,
                }
            )
        passed = all(
            member["catalog_status"] == SubmissionStatus.PLANNED_NOT_EXECUTABLE.value
            for member in members
        ) and not all(member["planning_status"] == PlanningStatus.READY.value for member in members)
        results.append(
            {
                "pair_id": pair_id,
                "fixed_inputs": {
                    "synchronized_route_start_required": True,
                    "maximum_route_start_skew_s": 0.2,
                    "minimum_simultaneous_flight_s": 2.0,
                },
                "members": members,
                "disposition": "BOTH_REMAIN_PLANNED_NOT_EXECUTABLE",
                "passed": passed,
                "claim_boundary": ["MODEL_ONLY", "NO_RUNTIME", "NOT_APPLICABLE"],
            }
        )
    return results


def _robust_center_result(catalog: CampaignCatalog, planner: BoundedJointPlanner) -> dict[str, Any]:
    case = catalog.get("3d.simultaneous_center_conflict.joint_schedule_v2")
    package, plan, measurement = _plan_package(
        planner,
        case,
        planning_submission_id="center.robust_combined",
    )
    metrics = _metric_map(measurement)
    expected = "08ef10cd30a72bdd0612c302f7d9446cf500c4a9e9b7e7e690dfa9f88af8b57a"
    clauses = {
        "complete_family": (
            plan.generated_candidate_count == 163
            and plan.retained_candidate_count == 163
            and not plan.truncated
            and plan.bounded_search_complete
        ),
        "bounded_argmax": (
            package.planning_submission.selection_oracle
            is PlanningSelectionOracle.ARGMAX_BOUNDED_CLEARANCE
            and plan.selected_candidate_sha256 == expected
        ),
        "positive_overlap": metrics["TM_OVERLAP"] >= 2.0,
        "all_roles_complete": set(metrics["DS_ALL_ROLE_COMPLETION"]) == {"Alpha", "Beta", "Gamma"},
    }
    return {
        "proposal_key": (
            "3d.simultaneous_center_conflict.joint_schedule_v2/center.robust_combined"
        ),
        "package_sha256": package.resolved_package_sha256,
        "plan_sha256": plan.plan_sha256,
        "selected_candidate_sha256": plan.selected_candidate_sha256,
        "optimality_claim": plan.optimality_claim,
        "measurement": measurement.model_dump(mode="json"),
        "relation_clauses": clauses,
        "passed": all(clauses.values()),
        "claim_boundary": ["INTEGRATION", "NO_RUNTIME", "NOT_APPLICABLE"],
    }


def _production_previews() -> list[dict[str, Any]]:
    output = []
    with tempfile.TemporaryDirectory(prefix="wp52-56-r6-production-preview-") as temporary:
        service = CampaignService(
            catalog=CampaignCatalog(ROOT / "missions/campaigns/sim/cases"),
            state_directory=Path(temporary),
        )
        requests = (
            [(case_id, None, submission_id, None) for case_id, submission_id in PROFILE_KEYS]
            + [
                (case_id, submission_id, None, "overlap-capacity-v1")
                for case_id, submission_id in CAPACITY_KEYS
            ]
            + [
                (
                    "3d.simultaneous_center_conflict.joint_schedule_v2",
                    "center.robust_combined",
                    None,
                    None,
                )
            ]
        )
        for case_id, planning_id, execution_id, context_id in requests:
            service.set_active(
                case_id,
                actor_id="wp52-56-r6-qualification",
                reason="normal public service preview qualification",
            )
            plan, schedule, trajectories = service.preview_active(
                submission_id=execution_id,
                planning_submission_id=planning_id,
                comparison_context_id=context_id,
            )
            output.append(
                {
                    "case_id": case_id,
                    "planning_submission_id": planning_id,
                    "execution_profile_submission_id": execution_id,
                    "comparison_context_id": context_id,
                    "plan_sha256": plan.plan_sha256,
                    "schedule_sha256": schedule.schedule_sha256,
                    "trajectory_set_sha256": trajectories.set_sha256,
                    "profile_audits_passed": all(
                        item.passed for item in trajectories.profile_audits
                    ),
                    "dynamics_audits_passed": all(item.passed for item in trajectories.audits),
                    "claim_boundary": [
                        "PRODUCTION_ENTRY",
                        "NO_RUNTIME",
                        "NOT_APPLICABLE",
                    ],
                }
            )
    return output


def _ui_attestation() -> dict[str, Any]:
    if not UI_INSPECTION.exists():
        return {"passed": False, "status": "NOT_RUN", "reason": "inspection artifact absent"}
    inspection = json.loads(UI_INSPECTION.read_text(encoding="utf-8"))
    current_link = ROOT / "ui/.crazyswarm-builds/current"
    if not current_link.exists():
        return {
            "passed": False,
            "status": "NOT_RUN",
            "reason": "served release symlink absent",
            "inspection": inspection,
        }
    release = current_link.resolve(strict=True)
    assets = sorted((release / "dist/client/assets").glob("*.css"))
    return {
        "passed": bool(inspection.get("passed")),
        "status": "RETAINED_INSPECTION",
        "inspection_sha256": canonical_sha256(inspection),
        "release_name": release.name,
        "release_tree_sha256": canonical_sha256(
            sorted(
                (
                    str(path.relative_to(release)),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
                for path in release.rglob("*")
                if path.is_file()
            )
        ),
        "css_asset_sha256s": {
            str(path.relative_to(release)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in assets
        },
        "inspection": inspection,
    }


def main() -> None:
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    validate_registry_coverage(catalog.cases())
    registry = load_case_submission_registry()
    admissions = load_admission_registry()
    planner = BoundedJointPlanner()

    collapse_results, collapse_failures = _collapse_results(catalog, planner)
    profile_results = _profile_results(catalog, planner)
    capacity_results = _capacity_results(catalog, planner)
    atomic_results = _atomic_results(catalog, planner)
    robust_center = _robust_center_result(catalog, planner)
    production_previews = _production_previews()
    ui_attestation = _ui_attestation()

    proposal_count = sum(len(row.proposals) for row in admissions.rows)
    visible_count = proposal_count - len(collapse_results)
    lifecycle_counts = {
        lifecycle.value: sum(row.lifecycle is lifecycle for row in admissions.rows)
        for lifecycle in AdmissionLifecycle
    }
    matrix_passed = (
        len(registry.rows) == 55
        and proposal_count == 111
        and len(collapse_results) == 21
        and visible_count == 90
        and lifecycle_counts == {"SUBMISSIONS": 43, "BASELINE_ONLY": 10, "RETAIN_EXISTING_ONLY": 2}
    )
    passed = (
        matrix_passed
        and not collapse_failures
        and all(item["passed"] for item in profile_results)
        and all(item["passed"] for item in capacity_results)
        and all(item["passed"] for item in atomic_results)
        and robust_center["passed"]
        and all(
            item["profile_audits_passed"] and item["dynamics_audits_passed"]
            for item in production_previews
        )
    )
    design_evidence = json.loads(R6_DESIGN_EVIDENCE.read_text(encoding="utf-8"))
    payload = {
        "schema_version": 2,
        "qualification_id": "selective-submission-registry-r6-v1",
        "claim": (
            "Registry, collapse, numerical relation, and public-service preview evidence are "
            "integration/no-runtime unless a separate retained runtime artifact says otherwise."
        ),
        "accepted_design_payload_sha256": (
            "6294fc5b7e246f300069313a6c1b9d23696018b5f50c390a37b82103a0a8cf93"
        ),
        "design_numerical_evidence_file_sha256": hashlib.sha256(
            R6_DESIGN_EVIDENCE.read_bytes()
        ).hexdigest(),
        "design_numerical_evidence_internal_sha256": design_evidence["audit_sha256"],
        "reviewed_counts": registry.reviewed_counts,
        "case_count": len(registry.rows),
        "proposal_count": proposal_count,
        "collapsed_submission_count": len(collapse_results),
        "visible_relation_count": visible_count,
        "lifecycle_counts": lifecycle_counts,
        "matrix_passed": matrix_passed,
        "collapsed_results": collapse_results,
        "collapse_failures": collapse_failures,
        "execution_profile_results": profile_results,
        "capacity_context_results": capacity_results,
        "atomic_pair_results": atomic_results,
        "robust_center_result": robust_center,
        "center_earliest_disposition": {
            "proposal_key": (
                "3d.simultaneous_center_conflict.joint_schedule_v2/center.earliest_combined"
            ),
            "status": "PLANNED_NOT_EXECUTABLE",
            "relation": "OPEN(INCONCLUSIVE_MISSING_FEASIBLE_WITNESS)",
            "claim_boundary": ["MODEL_ONLY", "NO_RUNTIME", "NOT_APPLICABLE"],
        },
        "production_preview_results": production_previews,
        "ui_inspection": ui_attestation,
        "planning_failures": [],
        "passed": passed,
    }
    payload["report_sha256"] = canonical_sha256(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not passed:
        raise SystemExit("R6 selective submission qualification failed")


if __name__ == "__main__":
    main()
