import json
import math
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import LockedDevelopmentInputs, PlannerStrategy, RouteNodeMode
from crazyswarm_app.campaign.planner import BoundedJointPlanner, PlanningStatus, SearchDisposition
from crazyswarm_app.campaign.service import CampaignService
from crazyswarm_app.campaign.submission_measurement import (
    _independent_samples,
    _point_polyline_distance,
    derive_sampled_route_semantics,
)
from crazyswarm_app.campaign.submissions import (
    BASELINE_PLANNING_SUBMISSION_ID,
    BASELINE_SUBMISSION_ID,
    CONSTANT_PATH_SPEED_CAPABILITY_ID,
    AdmissionRegistry,
    CapabilityFeasibilityDisposition,
    CaseSubmissionRegistryRow,
    ExecutionCapabilityRequest,
    ExecutionProfileParameters,
    MotionPreparationRequest,
    PathAdherenceMode,
    PlanningCapabilityRequest,
    PlanningSelectionOracle,
    ResolvedPlanningPackage,
    SubmissionStatus,
    load_admission_registry,
    load_capability_registry,
    load_case_submission_registry,
    normalized_route_polyline,
    planning_submissions_for_case,
    rebind_planning_submission,
    resolve_capability_resolution,
    resolve_planning_package,
    resolve_planning_submission,
    resolve_submission,
    submissions_for_case,
    validate_registry_coverage,
    validate_submission_set,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.trajectory import sample_trajectory


@pytest.fixture(scope="module")
def catalog() -> CampaignCatalog:
    value = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    value.discover()
    return value


def test_altitude_submissions_are_case_bound_and_selective(catalog: CampaignCatalog) -> None:
    canonical = catalog.get("1d.altitude_transition.canonical_nominal")
    wide = catalog.get("1d.altitude_transition.wide")
    unrelated = catalog.get("1d.takeoff_hover_land.canonical_nominal")

    canonical_ids = {item.submission_id for item in submissions_for_case(canonical)}
    wide_ids = {item.submission_id for item in submissions_for_case(wide)}

    assert canonical_ids == {
        BASELINE_SUBMISSION_ID,
        "constant_path_speed.slow",
        "constant_path_speed.stress",
        "ramped_segment_speed.altitude_kinks",
        "constant_rotor_speed",
    }
    assert wide_ids == {
        BASELINE_SUBMISSION_ID,
        "constant_path_speed.stress",
        "bounded_vertical_rate.wide",
        "constant_rotor_speed",
    }
    assert tuple(item.submission_id for item in submissions_for_case(unrelated)) == (
        BASELINE_SUBMISSION_ID,
        "vertical_cycle.precision_first",
        "vertical_cycle.minimum_duration",
    )
    assert all(
        item.case_sha256 == canonical.case_sha256 for item in submissions_for_case(canonical)
    )


def test_core_constant_speed_binds_without_a_case_catalog_submission(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.point_to_point_relocation.canonical_nominal")
    assert tuple(item.submission_id for item in submissions_for_case(case)) == (
        BASELINE_SUBMISSION_ID,
    )

    request = ExecutionCapabilityRequest(
        capability_id=CONSTANT_PATH_SPEED_CAPABILITY_ID,
        parameters=ExecutionProfileParameters(target_path_speed_m_s=0.18),
    )
    package = resolve_planning_package(case, execution_capability_request=request)
    plan = BoundedJointPlanner().plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        first_certified_within_budget=True,
    )

    assert package.execution_profile.submission_id == CONSTANT_PATH_SPEED_CAPABILITY_ID
    assert (
        package.planning_submission.execution_profile_submission_id
        == CONSTANT_PATH_SPEED_CAPABILITY_ID
    )
    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=package.execution_profile,
        planning_submission=package.planning_submission,
    )
    assert trajectories.profile_audits
    assert all(audit.passed for audit in trajectories.profile_audits)


def test_selective_registry_covers_the_exact_21_18_16_catalog(
    catalog: CampaignCatalog,
) -> None:
    registry = load_case_submission_registry()
    validate_registry_coverage(catalog.cases())

    assert registry.reviewed_counts == {"1d": 21, "2d": 18, "3d": 16}
    assert len(registry.rows) == 55
    assert sum(row.baseline_only for row in registry.rows) == 10
    assert all(
        row.baseline_only or row.retain_existing_only or row.submissions for row in registry.rows
    )


def test_literal_admission_registry_is_closed_complete_and_tamper_evident() -> None:
    admissions = load_admission_registry()
    proposals = tuple(proposal for row in admissions.rows for proposal in row.proposals)

    assert admissions.source_payload_sha256 == (
        "d1bdaa28f4e1403265fa15d4cf66a2cd62113c78990ac6caebc2f08ea4674c87"
    )
    assert admissions.oracle_contract_version == "wp52-56-r6-verified-oracle-v1"
    assert len(admissions.rows) == 69
    assert len(proposals) == 111
    assert sum("COLLAPSE_ALL" in item.qualifying_relation for item in proposals) == 21
    assert (
        sum(
            item.qualifying_relation == "DISTINGUISHABLE_AFTER_WP58_WHOLE_ROUTE_SMOOTHING"
            for item in proposals
        )
        == 7
    )
    assert sum(item.comparison_context_id is not None for item in proposals) == 3
    proposal_keys = {
        (row.case_id, item.submission_id) for row in admissions.rows for item in row.proposals
    }
    assert len(proposal_keys) == 111

    rounded = next(
        row for row in admissions.rows if row.case_id == "1d.planar_shape_loop.rounded_square"
    )
    assert rounded.metric_ids == (
        "TM_TRANSITION_START",
        "SP_CAPTURE",
        "SP_CORNER_CUT",
        "SP_REFERENCE",
        "DY_CURVATURE",
        "DY_JERK",
        "SP_CLOSURE",
    )
    assert all(
        phrase in rounded.comparison_and_distinguishing_oracle
        for phrase in ("transition start", "corner cut", "curvature", "jerk", "loop closure")
    )

    tampered = admissions.model_dump(mode="python")
    tampered["rows"][0]["metric_ids"] = (*tampered["rows"][0]["metric_ids"], "UNKNOWN")
    with pytest.raises(ValueError, match="unknown metrics"):
        AdmissionRegistry.model_validate(tampered)

    tampered = admissions.model_dump(mode="python")
    tampered["source_payload_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source payload hash mismatch"):
        AdmissionRegistry.model_validate(tampered)


def test_duration_and_corner_anchors_change_behavior_without_changing_case_hash(
    catalog: CampaignCatalog,
) -> None:
    takeoff = catalog.get("1d.takeoff_hover_land.canonical_nominal")
    duration_profiles = tuple(
        resolve_submission(takeoff, submission_id)
        for submission_id in (
            "vertical_cycle.precision_first",
            "vertical_cycle.minimum_duration",
        )
    )
    duration_plans = tuple(BoundedJointPlanner().plan(takeoff, item) for item in duration_profiles)
    assert all(plan.status is PlanningStatus.READY for plan in duration_plans)
    assert len({plan.plan_sha256 for plan in duration_plans}) == 2
    assert all(item.case_sha256 == takeoff.case_sha256 for item in duration_profiles)

    rounded = catalog.get("1d.planar_shape_loop.rounded_square")
    short = resolve_submission(
        rounded,
        "corner_transition.lookahead_0_20s",
    )
    assert short.status is SubmissionStatus.EXECUTABLE
    short_resolution = resolve_capability_resolution(rounded, short)
    assert short_resolution is not None
    assert short_resolution.authored_lookahead_time_s == 0.2
    short_package = resolve_planning_package(
        rounded,
        execution_profile_submission_id=short.submission_id,
    )
    assert short_package.execution_profile == short

    smooth = resolve_submission(rounded, "corner_transition.lookahead_0_60s")
    package = resolve_planning_package(
        rounded,
        execution_profile_submission_id=smooth.submission_id,
    )
    resolution = package.capability_resolution
    assert resolution is not None
    assert resolution.authored_lookahead_time_s == 0.6
    assert resolution.certified_entry_speed_m_s < resolution.authored_target_path_speed_m_s
    plan = BoundedJointPlanner().plan(
        rounded,
        smooth,
        planning_submission=package.planning_submission,
        capability_resolution=resolution,
        first_certified_within_budget=True,
    )
    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    trajectories = generate_smooth_trajectories(
        rounded,
        plan.selected,
        submission=smooth,
        planning_submission=package.planning_submission,
        capability_resolution=resolution,
    )
    transition_start = math.dist(
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
    )
    assert transition_start == pytest.approx(resolution.derived_lookahead_distance_m)


def test_r6_execution_profiles_and_bounded_selection_oracles_are_production_owned(
    catalog: CampaignCatalog,
) -> None:
    expected_profiles = {
        "1d.continuous_waypoint_sequence.canonical_nominal": (
            "waypoint.smoothness_first",
            0.08,
            0.60,
            None,
        ),
        "1d.curved_route.canonical_nominal": (
            "curve.jerk_first",
            None,
            None,
            1.30,
        ),
        "1d.planar_shape_loop.figure_eight": (
            "loop.curvature_continuity",
            0.08,
            0.60,
            None,
        ),
    }
    for case_id, (submission_id, speed, lookahead, duration_scale) in expected_profiles.items():
        case = catalog.get(case_id)
        profile = resolve_submission(case, submission_id)
        assert profile.status is SubmissionStatus.EXECUTABLE
        assert profile.parameters.target_path_speed_m_s == speed
        assert profile.parameters.lookahead_time_s == lookahead
        assert profile.parameters.duration_scale == duration_scale

    expected_plans = (
        (
            "2d.head_on_conflict.canonical_nominal",
            "head_on.earliest_safe_release",
            "overlap-capacity-v1",
            PlanningSelectionOracle.ARGMIN_BOUNDED_RELEASE,
            16,
            "4ab920b82459cb7903760a681500574b812bad642a488e2b5e861d79ac8adc1b",
        ),
        (
            "2d.perpendicular_crossing.nominal_equal_priority",
            "crossing.earliest_equal_release",
            "overlap-capacity-v1",
            PlanningSelectionOracle.ARGMIN_BOUNDED_RELEASE,
            16,
            "cbd3bc0dfea31532c5b8927aedb14248eb42ff1e41d24ffd86dd0b70289f98f1",
        ),
        (
            "3d.simultaneous_center_conflict.joint_schedule_v2",
            "center.robust_combined",
            None,
            PlanningSelectionOracle.ARGMAX_BOUNDED_CLEARANCE,
            163,
            "08ef10cd30a72bdd0612c302f7d9446cf500c4a9e9b7e7e690dfa9f88af8b57a",
        ),
    )
    for case_id, submission_id, context_id, oracle, count, selected_sha in expected_plans:
        case = catalog.get(case_id)
        package = resolve_planning_package(
            case,
            submission_id,
            comparison_context_id=context_id,
        )
        plan = BoundedJointPlanner().plan(
            case,
            package.execution_profile,
            planning_submission=package.planning_submission,
        )
        assert package.planning_submission.selection_oracle is oracle
        assert plan.status is PlanningStatus.READY
        assert plan.bounded_search_complete is True
        assert plan.truncated is False
        assert plan.generated_candidate_count == plan.retained_candidate_count == count
        assert plan.selected_candidate_sha256 == selected_sha


def test_r6_atomic_peers_remain_visible_with_only_certified_2d_choices_enabled(
    catalog: CampaignCatalog,
) -> None:
    expected = {
        "head_on.synchronized_lateral",
        "head_on.synchronized_vertical",
        "head_on.path_fidelity_combined",
        "head_on.robustness_combined",
        "merge.parallel_lanes",
        "merge.vertical_stack",
        "crossing.synchronized_lateral",
        "crossing.synchronized_vertical",
        "merge.parallel_capacity",
        "merge.vertical_capacity",
        "center.synchronized_lateral",
        "center.synchronized_layers",
    }
    observed = {
        submission.planning_submission_id: submission.status
        for case in catalog.cases()
        for submission in planning_submissions_for_case(case)
        if submission.planning_submission_id in expected
    }
    assert set(observed) == expected
    assert {
        submission_id
        for submission_id, status in observed.items()
        if status is SubmissionStatus.EXECUTABLE
    } == {
        "head_on.synchronized_lateral",
        "merge.parallel_lanes",
        "crossing.synchronized_vertical",
    }


def test_r6_sampled_discrete_oracle_rejects_stop_and_reordered_loop(
    catalog: CampaignCatalog,
) -> None:
    waypoint = catalog.get("1d.continuous_waypoint_sequence.canonical_nominal")
    waypoint_package = resolve_planning_package(
        waypoint,
        execution_profile_submission_id="waypoint.smoothness_first",
    )
    waypoint_plan = BoundedJointPlanner().plan(
        waypoint,
        waypoint_package.execution_profile,
        planning_submission=waypoint_package.planning_submission,
        capability_resolution=waypoint_package.capability_resolution,
    )
    waypoint_trajectories = generate_smooth_trajectories(
        waypoint,
        waypoint_plan.selected,
        submission=waypoint_package.execution_profile,
        planning_submission=waypoint_package.planning_submission,
        capability_resolution=waypoint_package.capability_resolution,
    )
    samples = {
        item.role_id: _independent_samples(item) for item in waypoint_trajectories.trajectories
    }
    original = derive_sampled_route_semantics(waypoint, waypoint_plan.selected.routes, samples)
    assert original["DS_UNINTENDED_STOP_COUNT"] == 0
    stopped = {}
    for role_id, values in samples.items():
        pivot = len(values) // 2
        pivot_time = values[pivot]["time_s"]
        stopped[role_id] = tuple(
            {
                **sample,
                "position_m": values[pivot]["position_m"],
                "velocity_m_s": (0.0, 0.0, 0.0),
                "acceleration_m_s2": (0.0, 0.0, 0.0),
            }
            if pivot_time <= sample["time_s"] <= pivot_time + 0.22
            else sample
            for sample in values
        )
    assert (
        derive_sampled_route_semantics(waypoint, waypoint_plan.selected.routes, stopped)[
            "DS_UNINTENDED_STOP_COUNT"
        ]
        == 1
    )

    loop = catalog.get("1d.planar_shape_loop.figure_eight")
    loop_package = resolve_planning_package(
        loop,
        execution_profile_submission_id="loop.curvature_continuity",
    )
    loop_plan = BoundedJointPlanner().plan(
        loop,
        loop_package.execution_profile,
        planning_submission=loop_package.planning_submission,
        capability_resolution=loop_package.capability_resolution,
    )
    loop_trajectories = generate_smooth_trajectories(
        loop,
        loop_plan.selected,
        submission=loop_package.execution_profile,
        planning_submission=loop_package.planning_submission,
        capability_resolution=loop_package.capability_resolution,
    )
    loop_samples = {
        item.role_id: _independent_samples(item) for item in loop_trajectories.trajectories
    }
    assert (
        derive_sampled_route_semantics(
            loop,
            loop_plan.selected.routes,
            loop_samples,
        )["DS_TOPOLOGY"]
        == "figure_eight"
    )
    reversed_samples = {
        role_id: tuple(
            {
                **source,
                "time_s": target["time_s"],
                "velocity_m_s": tuple(-value for value in source["velocity_m_s"]),
            }
            for target, source in zip(values, reversed(values), strict=True)
        )
        for role_id, values in loop_samples.items()
    }
    assert (
        derive_sampled_route_semantics(
            loop,
            loop_plan.selected.routes,
            reversed_samples,
        )["DS_TOPOLOGY"]
        == "order_violation"
    )


def test_core_constant_speed_composes_with_flexible_fleet_geometry(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("2d.merge.canonical_nominal")
    request = ExecutionCapabilityRequest(
        capability_id=CONSTANT_PATH_SPEED_CAPABILITY_ID,
        parameters=ExecutionProfileParameters(target_path_speed_m_s=0.30),
    )
    package = resolve_planning_package(
        case,
        "constraint_directed.merge.flexible_geometry",
        execution_capability_request=request,
    )

    plan = BoundedJointPlanner().plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        first_certified_within_budget=True,
    )

    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    assert plan.selected.strategy is not PlannerStrategy.DIRECT
    assert plan.selected.parameters["execution_capability_id"] == CONSTANT_PATH_SPEED_CAPABILITY_ID
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=package.execution_profile,
        planning_submission=package.planning_submission,
    )
    assert len(trajectories.profile_audits) == case.drone_count
    assert all(audit.passed for audit in trajectories.profile_audits)


def test_core_constant_speed_fails_closed_outside_case_feasibility(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.point_to_point_relocation.canonical_nominal")
    request = ExecutionCapabilityRequest(
        capability_id=CONSTANT_PATH_SPEED_CAPABILITY_ID,
        parameters=ExecutionProfileParameters(target_path_speed_m_s=0.01),
    )

    with pytest.raises(ValueError, match="outside the case feasibility interval"):
        resolve_planning_package(case, execution_capability_request=request)


@pytest.mark.parametrize(
    ("case_id", "submission_id"),
    [
        ("1d.altitude_transition.canonical_nominal", "constant_path_speed.slow"),
        ("1d.altitude_transition.canonical_nominal", "constant_path_speed.stress"),
        (
            "1d.altitude_transition.canonical_nominal",
            "ramped_segment_speed.altitude_kinks",
        ),
        ("1d.altitude_transition.wide", "constant_path_speed.stress"),
        ("1d.altitude_transition.wide", "bounded_vertical_rate.wide"),
    ],
)
def test_executable_submission_has_hash_bound_plan_and_profile_audit(
    catalog: CampaignCatalog,
    case_id: str,
    submission_id: str,
) -> None:
    case = catalog.get(case_id)
    submission = resolve_submission(case, submission_id)
    plan = BoundedJointPlanner().plan(case, submission)

    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    assert plan.submission_id == submission.submission_id
    assert plan.submission_sha256 == submission.profile_sha256

    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=submission,
    )
    assert trajectories.submission_id == submission.submission_id
    assert trajectories.submission_sha256 == submission.profile_sha256
    assert trajectories.profile_audits
    assert all(item.hard_constraints_preserved for item in trajectories.profile_audits)
    assert all(item.passed for item in trajectories.profile_audits)

    lock = LockedDevelopmentInputs.from_case(
        case,
        submission_id=submission.submission_id,
        submission_sha256=submission.profile_sha256,
    )
    assert lock.submission_id == submission.submission_id
    assert lock.submission_sha256 == submission.profile_sha256


def test_constant_rotor_submission_is_explicitly_non_executable(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.altitude_transition.canonical_nominal")
    rotor = next(
        item for item in submissions_for_case(case) if item.submission_id == "constant_rotor_speed"
    )
    assert rotor.status is SubmissionStatus.PLANNED_NOT_EXECUTABLE
    with pytest.raises(ValueError, match="PLANNED_NOT_EXECUTABLE"):
        resolve_submission(case, rotor.submission_id)


def test_label_only_submission_cannot_pass_semantic_admission(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.altitude_transition.canonical_nominal")
    baseline = submissions_for_case(case)[0]
    relabeled = baseline.model_copy(
        update={
            "submission_id": "planner_retained_baseline.relabelled",
            "display_name": "A different label only",
            "rationale": "Different prose cannot create a new experiment.",
        }
    )

    with pytest.raises(ValueError, match="behavioral semantic fingerprint"):
        validate_submission_set((baseline, relabeled))


@pytest.mark.parametrize(
    "submission_id",
    (
        "constant_path_speed.slow",
        "constant_path_speed.stress",
        "ramped_segment_speed.altitude_kinks",
    ),
)
def test_altitude_speed_profiles_have_flat_interiors_and_monotonic_terminal_ramps(
    catalog: CampaignCatalog,
    submission_id: str,
) -> None:
    case = catalog.get("1d.altitude_transition.canonical_nominal")
    submission = resolve_submission(case, submission_id)
    plan = BoundedJointPlanner().plan(case, submission)
    assert plan.selected is not None
    generated = generate_smooth_trajectories(case, plan.selected, submission=submission)
    trajectory = generated.trajectories[0]
    profile = generated.profile_audits[0]

    assert len(trajectory.points) > len(plan.selected.routes[0].points_m)
    assert profile.maximum_fractional_error <= 0.10
    assert profile.steady_window_coverage_fraction >= 0.35

    terminal_speeds = []
    timestamp_s = trajectory.duration_s - submission.parameters.entry_exit_ramp_s
    while timestamp_s <= trajectory.duration_s + 1e-9:
        velocity = sample_trajectory(trajectory, timestamp_s).velocity_m_s
        terminal_speeds.append(math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2))
        timestamp_s += 0.01
    assert terminal_speeds[-1] <= 1e-6
    assert all(after <= before + 1e-6 for before, after in pairwise(terminal_speeds))


def test_successor_profile_reports_missing_evidence_prerequisite(
    catalog: CampaignCatalog,
    tmp_path: Path,
) -> None:
    service = CampaignService(catalog=catalog, state_directory=tmp_path / "campaign")
    case = catalog.get("1d.altitude_transition.canonical_nominal")
    stress = resolve_submission(case, "constant_path_speed.stress")

    assert service.missing_submission_prerequisites(case, stress) == ("constant_path_speed.slow",)


def test_registry_reused_evidence_is_not_a_runtime_submission_prerequisite(
    catalog: CampaignCatalog,
    tmp_path: Path,
) -> None:
    service = CampaignService(catalog=catalog, state_directory=tmp_path / "campaign")
    case = catalog.get("1d.continuous_waypoint_sequence.canonical_nominal")
    smooth = resolve_submission(case, "waypoint.smoothness_first")

    assert smooth.admission.reused_evidence == (
        "immutable_case_hash",
        "bounded_planner_contract",
        "continuous_safety_certificate",
    )
    assert smooth.prerequisite_submission_ids == ()
    assert service.missing_submission_prerequisites(case, smooth) == ()


def test_retained_wp43_runtime_matrix_is_complete_and_repeatable() -> None:
    path = Path(
        "missions/campaigns/sim/qualification/altitude-profile-runtime-qualification-v1.json"
    )
    qualification = json.loads(path.read_text(encoding="utf-8"))

    assert qualification["requested_mode"] == "both"
    assert qualification["repetitions"] == 2
    assert qualification["run_count"] == 24
    assert qualification["all_runs_and_gates_passed"] is True
    rows = qualification["runs"]
    assert all(
        row["status"] == "SUCCEEDED"
        and row["evaluation_status"] == "COMPLETE"
        and row["evaluation_evidence_complete"] is True
        and row["planned_profile_conformance_passed"] is True
        and row["all_required_behavior_oracles_passed"] is True
        for row in rows
    )
    assert all(
        row["baseline_comparison"]["baseline_available"] is True
        for row in rows
        if row["submission_id"] != BASELINE_SUBMISSION_ID
    )
    assert all(
        row["cross_case_profile_comparison"]["comparison_available"] is True
        for row in rows
        if row["case_id"] == "1d.altitude_transition.wide"
        and row["submission_id"] == "constant_path_speed.stress"
    )
    assert all(
        row["mode_comparison"] is not None and row["mode_comparison"]["all_gates_passed"] is True
        for row in rows
        if row["mode"] == "OPERATOR_OBSERVED_REALTIME"
    )
    repeats: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        repeats[(row["case_id"], row["submission_id"], row["mode"])].append(row)
    assert all(len(group) == 2 for group in repeats.values())
    assert all(len({row["plan_sha256"] for row in group}) == 1 for group in repeats.values())
    assert all(
        len({row["trajectory_set_sha256"] for row in group}) == 1 for group in repeats.values()
    )


def test_selective_submission_qualification_is_complete_and_truthful() -> None:
    path = Path("missions/campaigns/sim/qualification/selective-submission-registry-v1.json")
    qualification = json.loads(path.read_text(encoding="utf-8"))

    assert qualification["passed"] is True
    assert qualification["case_count"] == 55
    assert qualification["reviewed_counts"] == {"1d": 21, "2d": 18, "3d": 16}
    assert qualification["planning_failures"] == []
    assert qualification["qualification_id"] == "selective-submission-registry-r6-v1"
    assert qualification["proposal_count"] == 111
    assert qualification["collapsed_submission_count"] == 21
    assert qualification["visible_relation_count"] == 90
    assert qualification["collapse_failures"] == []
    assert len(qualification["collapsed_results"]) == 21
    assert all(item["collapse_proven"] for item in qualification["collapsed_results"])
    assert qualification["ui_inspection"]["passed"] is False
    assert qualification["ui_inspection"]["status"] == "RETAINED_INSPECTION"
    assert all(item["passed"] for item in qualification["execution_profile_results"])
    assert all(item["passed"] for item in qualification["capacity_context_results"])
    assert all(item["passed"] for item in qualification["atomic_pair_results"])
    assert qualification["robust_center_result"]["passed"] is True
    assert all(
        item["claim_boundary"] == ["INTEGRATION", "NO_RUNTIME", "NOT_APPLICABLE"]
        for item in qualification["execution_profile_results"]
    )
    assert all(
        item["claim_boundary"] == ["PRODUCTION_ENTRY", "NO_RUNTIME", "NOT_APPLICABLE"]
        for item in qualification["production_preview_results"]
    )


@pytest.mark.parametrize(
    ("case_id", "planning_submission_id"),
    [
        (
            "2d.bottleneck.canonical_nominal",
            "constraint_directed.bottleneck.simultaneous_vertical",
        ),
        (
            "2d.head_on_conflict.canonical_nominal",
            "constraint_directed.head_on.same_path",
        ),
        (
            "2d.merge.canonical_nominal",
            "constraint_directed.merge.flexible_geometry",
        ),
    ],
)
def test_constraint_directed_planning_submission_is_resolved_and_hash_bound(
    catalog: CampaignCatalog,
    case_id: str,
    planning_submission_id: str,
) -> None:
    case = catalog.get(case_id)
    available = planning_submissions_for_case(case)
    assert available[0].planning_submission_id == BASELINE_PLANNING_SUBMISSION_ID

    selected = resolve_planning_submission(case, planning_submission_id)
    package = resolve_planning_package(case, planning_submission_id)

    assert selected.case_sha256 == case.case_sha256
    assert selected.path_adherence.mode is PathAdherenceMode.GOAL_SEQUENCE_ONLY
    assert selected.coordination.synchronized_route_start_required
    assert selected.coordination.minimum_simultaneous_flight_s == 2.0
    assert package.planning_submission == selected
    assert package.execution_profile.submission_id == BASELINE_SUBMISSION_ID
    assert package.resolved_package_sha256 == canonical_sha256(package.canonical_payload())


def test_planning_package_rejects_cross_case_submission(catalog: CampaignCatalog) -> None:
    case = catalog.get("2d.merge.canonical_nominal")
    with pytest.raises(ValueError, match="not admitted"):
        resolve_planning_submission(
            case,
            "constraint_directed.head_on.same_path",
        )


def test_rebound_child_submission_rejects_removed_maneuver_dimensions(
    catalog: CampaignCatalog,
) -> None:
    source = catalog.get("2d.head_on_conflict.canonical_nominal")
    submission = resolve_planning_submission(
        source,
        "constraint_directed.head_on.same_path",
    )
    child = source.model_copy(
        update={
            "case_id": "2d.head_on_conflict.lateral_only_child",
            "parent_case_sha256": source.case_sha256,
            "allowed_strategies": (PlannerStrategy.HORIZONTAL_DETOUR,),
        }
    )

    choices = {item.planning_submission_id: item for item in planning_submissions_for_case(child)}
    narrowed = choices[submission.planning_submission_id]
    assert narrowed.status is SubmissionStatus.PLANNED_NOT_EXECUTABLE
    assert narrowed.strategy_authority == submission.strategy_authority
    with pytest.raises(ValueError, match="removed required planning authority"):
        rebind_planning_submission(child, submission)


def test_compatible_child_rejects_unqualified_backend(catalog: CampaignCatalog) -> None:
    source = catalog.get("2d.head_on_conflict.canonical_nominal")
    submission = resolve_planning_submission(source, "constraint_directed.head_on.same_path")
    child = source.model_copy(
        update={
            "case_id": "2d.head_on_conflict.unsupported_backend_child",
            "parent_case_sha256": source.case_sha256,
            "execution": source.execution.model_copy(
                update={"backend_profile_id": "unsupported-backend-v99"}
            ),
        }
    )

    assert all(
        item.status is SubmissionStatus.PLANNED_NOT_EXECUTABLE
        for item in planning_submissions_for_case(child)
    )
    with pytest.raises(ValueError, match=r"backend .* is not qualified"):
        rebind_planning_submission(child, submission)


def test_renamed_compatible_altitude_child_retains_profiles(
    catalog: CampaignCatalog,
) -> None:
    source = catalog.get("1d.altitude_transition.canonical_nominal")
    child = source.model_copy(
        update={
            "case_id": "1d.altitude_transition.renamed_compatible_child",
            "parent_case_sha256": source.case_sha256,
        }
    )

    assert {item.submission_id for item in submissions_for_case(child)} == {
        BASELINE_SUBMISSION_ID,
        "constant_path_speed.slow",
        "constant_path_speed.stress",
        "ramped_segment_speed.altitude_kinks",
        "constant_rotor_speed",
    }


def test_registry_enforces_one_axis_and_capability_status_truth(
    catalog: CampaignCatalog,
) -> None:
    row = next(
        item
        for item in load_case_submission_registry().rows
        if item.case_id == "1d.boundary_constrained_route.canonical_nominal"
    )
    assert {item.maximum_centerline_deviation_m for item in row.submissions} == {0.03}
    tampered = row.model_dump(mode="python")
    tampered["submissions"][1]["maximum_centerline_deviation_m"] = 0.25
    with pytest.raises(ValueError, match="changes fixed behavior fields"):
        CaseSubmissionRegistryRow.model_validate(tampered)

    capabilities = {item.capability_id: item for item in load_capability_registry().capabilities}
    assert capabilities["core.route_fidelity"].status is SubmissionStatus.EXECUTABLE
    assert capabilities["core.energy_aware_retiming"].status is SubmissionStatus.EXECUTABLE


def test_route_fidelity_is_a_planning_owned_exact_route_capability(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.curved_route.canonical_nominal")
    baseline = resolve_planning_package(case)
    request = PlanningCapabilityRequest(capability_id="core.route_fidelity")
    package = resolve_planning_package(case, planning_capability_request=request)

    assert package.planning_submission.path_adherence.mode is PathAdherenceMode.EXACT_ROUTE
    assert package.planning_submission.path_adherence.maximum_centerline_deviation_m == 1e-6
    assert package.capability_resolution is not None
    assert package.capability_resolution.exact_route_tolerance_m == 1e-6
    assert package.planning_submission.strategy_authority == (
        baseline.planning_submission.strategy_authority
    )
    assert package.planning_submission.objective == baseline.planning_submission.objective
    assert package.planning_submission.coordination == baseline.planning_submission.coordination
    assert package.execution_profile.profile_sha256 == baseline.execution_profile.profile_sha256

    plan = BoundedJointPlanner().plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        first_certified_within_budget=True,
    )
    assert plan.status is PlanningStatus.READY
    assert plan.feasibility_certificate is not None
    assert plan.feasibility_certificate.maximum_path_deviation_m == 0.0
    assert plan.selected is not None
    baseline_plan = BoundedJointPlanner().plan(
        case,
        baseline.execution_profile,
        planning_submission=baseline.planning_submission,
        first_certified_within_budget=True,
    )
    assert baseline_plan.selected is not None
    exact_trajectory = generate_smooth_trajectories(
        case,
        plan.selected,
        planning_submission=package.planning_submission,
    ).trajectories[0]
    baseline_trajectory = generate_smooth_trajectories(
        case,
        baseline_plan.selected,
        planning_submission=baseline.planning_submission,
    ).trajectories[0]
    authored = tuple(point for route in plan.selected.routes for point in route.points_m)
    exact_deviation = max(
        _point_polyline_distance(sample["position_m"], authored)
        for sample in _independent_samples(exact_trajectory)
    )
    baseline_deviation = max(
        _point_polyline_distance(sample["position_m"], authored)
        for sample in _independent_samples(baseline_trajectory)
    )
    assert exact_deviation <= 1e-6 + 1e-9
    assert baseline_deviation - exact_deviation >= 0.01

    child = case.model_copy(
        update={
            "case_id": "1d.curved_route.renamed-compatible-child",
            "parent_case_sha256": case.case_sha256,
        }
    )
    child_package = resolve_planning_package(child, planning_capability_request=request)
    assert child_package.planning_submission.case_sha256 == child.case_sha256
    assert child_package.capability_resolution is not None
    assert child_package.capability_resolution.exact_route_tolerance_m == 1e-6

    removed_authority = child.model_copy(
        update={
            "case_id": "1d.curved_route.removed-path-authority-child",
            "allowed_strategies": tuple(
                item for item in child.allowed_strategies if item is not PlannerStrategy.DIRECT
            ),
        }
    )
    with pytest.raises(ValueError, match="removed required exact-route planning authority"):
        resolve_planning_package(
            removed_authority,
            planning_capability_request=request,
        )

    unsupported = child.model_copy(
        update={
            "case_id": "1d.curved_route.unsupported-backend-child",
            "execution": child.execution.model_copy(
                update={"backend_profile_id": "unsupported-backend-v99"}
            ),
        }
    )
    with pytest.raises(ValueError, match="not qualified for backend"):
        resolve_planning_package(unsupported, planning_capability_request=request)

    tampered = package.model_dump(mode="python")
    tampered["planning_submission"]["path_adherence"]["maximum_centerline_deviation_m"] = 1e-5
    tampered["resolved_package_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "resolved_package_sha256"}
    )
    with pytest.raises(ValueError, match="frozen exact-route authority"):
        ResolvedPlanningPackage.model_validate(tampered)


def test_energy_aware_retiming_compiles_and_binds_all_five_candidates(
    catalog: CampaignCatalog,
) -> None:
    request = ExecutionCapabilityRequest(
        capability_id="core.energy_aware_retiming",
        parameters=ExecutionProfileParameters(),
    )
    case = catalog.get("1d.point_to_point_relocation.canonical_nominal")
    baseline = resolve_planning_package(case)
    package = resolve_planning_package(case, execution_capability_request=request)
    resolution = package.capability_resolution
    assert resolution is not None and resolution.energy_retiming is not None
    energy = resolution.energy_retiming

    assert tuple(item.duration_factor for item in energy.candidates) == (
        0.80,
        0.90,
        1.00,
        1.15,
        1.30,
    )
    assert package.execution_profile.parameters.duration_scale == energy.selected_factor
    assert energy.selected_factor == 0.80
    selected = next(
        item for item in energy.candidates if item.duration_factor == energy.selected_factor
    )
    baseline_candidate = next(item for item in energy.candidates if item.duration_factor == 1.0)
    assert selected.predicted_energy_wh <= baseline_candidate.predicted_energy_wh * 0.98
    assert baseline_candidate.duration_s - selected.duration_s >= 0.10

    baseline_plan = BoundedJointPlanner().plan(
        case,
        baseline.execution_profile,
        planning_submission=baseline.planning_submission,
        first_certified_within_budget=True,
    )
    selected_plan = BoundedJointPlanner().plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=resolution,
        first_certified_within_budget=True,
    )
    assert baseline_plan.selected is not None and selected_plan.selected is not None
    assert (
        baseline_plan.selected.routes[0].route_duration_s
        - selected_plan.selected.routes[0].route_duration_s
        >= 0.10
    )

    child = case.model_copy(
        update={
            "case_id": "1d.point_to_point_relocation.renamed-compatible-child",
            "parent_case_sha256": case.case_sha256,
        }
    )
    child_package = resolve_planning_package(child, execution_capability_request=request)
    assert child_package.capability_resolution is not None
    assert child_package.capability_resolution.energy_retiming is not None
    assert child_package.capability_resolution.energy_retiming.selected_factor == 0.80

    coupled = catalog.get("2d.parallel_routes.canonical_nominal")
    coupled_package = resolve_planning_package(coupled, execution_capability_request=request)
    assert coupled_package.capability_resolution is not None
    assert coupled_package.capability_resolution.energy_retiming is not None
    assert len(coupled_package.capability_resolution.energy_retiming.candidates) == 5

    tampered = package.model_dump(mode="python")
    tampered["capability_resolution"]["energy_retiming"]["selected_factor"] = 1.30
    tampered["resolved_package_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "resolved_package_sha256"}
    )
    with pytest.raises(ValueError, match=r"selected factor|capability resolution mismatch"):
        ResolvedPlanningPackage.model_validate(tampered)

    with pytest.raises(ValueError, match="no caller-selected scalar"):
        ExecutionCapabilityRequest(
            capability_id="core.energy_aware_retiming",
            parameters=ExecutionProfileParameters(duration_scale=1.15),
        )


def test_resolved_package_rejects_its_own_hash_tampering(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("2d.merge.canonical_nominal")
    package = resolve_planning_package(
        case,
        "constraint_directed.merge.flexible_geometry",
    )
    payload = package.model_dump(mode="python")
    payload["resolved_package_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="resolved hash mismatch"):
        ResolvedPlanningPackage.model_validate(payload)


def test_corner_resolution_rejects_radius_and_limit_tampering(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.planar_shape_loop.rounded_square")
    package = resolve_planning_package(
        case,
        execution_profile_submission_id="corner_transition.lookahead_0_60s",
    )
    payload = package.model_dump(mode="python")
    assert payload["capability_resolution"] is not None
    payload["capability_resolution"]["derived_turn_blend_radius_m"] = 0.25
    payload["capability_resolution"]["limiting_constraint"] = "bogus-unverified-limit"
    payload["resolved_package_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "resolved_package_sha256"}
    )

    with pytest.raises(ValueError, match=r"capability resolution mismatch|turn blend radius"):
        ResolvedPlanningPackage.model_validate(payload)


def test_corner_resolution_is_semantic_polyline_invariant_and_rejection_is_exact(
    catalog: CampaignCatalog,
) -> None:
    source = catalog.get("1d.planar_shape_loop.rounded_square")
    drone = source.drones[0]
    assert source.semantics is not None
    goals = list(drone.goal_sequence)
    route_nodes = list(source.route_nodes_for(drone.role_id))
    before = goals[1].center_m
    after = goals[2].center_m
    inserted_goals = []
    inserted_nodes = []
    for index in range(1, 20):
        fraction = index / 20.0
        center = before.model_copy(
            update={
                "x": before.x + fraction * (after.x - before.x),
                "y": before.y + fraction * (after.y - before.y),
                "z": before.z + fraction * (after.z - before.z),
            }
        )
        region_id = f"resampled-edge-{index:02d}"
        half_width = 0.04
        inserted_goals.append(
            goals[1].model_copy(
                update={
                    "region_id": region_id,
                    "minimum_m": center.model_copy(
                        update={
                            "x": center.x - half_width,
                            "y": center.y - half_width,
                            "z": center.z - half_width,
                        }
                    ),
                    "maximum_m": center.model_copy(
                        update={
                            "x": center.x + half_width,
                            "y": center.y + half_width,
                            "z": center.z + half_width,
                        }
                    ),
                }
            )
        )
        inserted_nodes.append(route_nodes[1].model_copy(update={"region_id": region_id}))
    child_goals = tuple((*goals[:2], *inserted_goals, *goals[2:]))
    child_nodes = tuple((*route_nodes[:2], *inserted_nodes, *route_nodes[2:]))
    child = source.model_copy(
        update={
            "case_id": "1d.planar_shape_loop.rounded_square.resampled-child",
            "parent_case_sha256": source.case_sha256,
            "drones": (drone.model_copy(update={"goal_sequence": child_goals}),),
            "semantics": source.semantics.model_copy(
                update={
                    "route_intent_by_role": {
                        **source.semantics.route_intent_by_role,
                        drone.role_id: child_nodes,
                    }
                }
            ),
        }
    )
    source_profile = resolve_submission(source, "corner_transition.lookahead_0_60s")
    child_profile = resolve_submission(child, "corner_transition.lookahead_0_60s")
    source_resolution = resolve_capability_resolution(source, source_profile)
    child_resolution = resolve_capability_resolution(child, child_profile)
    assert source_resolution is not None and child_resolution is not None
    assert (
        source_resolution.normalized_geometry_sha256 == child_resolution.normalized_geometry_sha256
    )
    assert source_resolution.raw_capture_sha256s != child_resolution.raw_capture_sha256s
    for field in (
        "certified_entry_speed_m_s",
        "derived_lookahead_distance_m",
        "derived_turn_blend_radius_m",
        "adjacent_segment_cap_m",
        "protected_free_space_cap_m",
        "path_deviation_cap_m",
        "dynamics_speed_cap_m_s",
        "safety_retiming_factor",
    ):
        assert math.isclose(
            getattr(source_resolution, field),
            getattr(child_resolution, field),
            abs_tol=1e-9,
        )
    assert len(normalized_route_polyline(child, drone.role_id).normalized_points_m) == len(
        normalized_route_polyline(source, drone.role_id).normalized_points_m
    )

    source_plan = BoundedJointPlanner().plan(
        source,
        source_profile,
        capability_resolution=source_resolution,
    )
    child_plan = BoundedJointPlanner().plan(
        child,
        child_profile,
        capability_resolution=child_resolution,
    )
    assert source_plan.selected is not None and child_plan.selected is not None
    source_trajectory = generate_smooth_trajectories(
        source,
        source_plan.selected,
        submission=source_profile,
        capability_resolution=source_resolution,
    ).trajectories[0]
    child_trajectory = generate_smooth_trajectories(
        child,
        child_plan.selected,
        submission=child_profile,
        capability_resolution=child_resolution,
    ).trajectories[0]
    assert math.isclose(source_trajectory.duration_s, child_trajectory.duration_s, abs_tol=1e-9)
    elapsed = 0.0
    while elapsed <= source_trajectory.duration_s:
        first = sample_trajectory(source_trajectory, elapsed)
        second = sample_trajectory(child_trajectory, elapsed)
        assert (
            math.dist(
                (first.position_m.x, first.position_m.y, first.position_m.z),
                (second.position_m.x, second.position_m.y, second.position_m.z),
            )
            <= 1e-6
        )
        assert (
            math.dist(
                (first.velocity_m_s.x, first.velocity_m_s.y, first.velocity_m_s.z),
                (second.velocity_m_s.x, second.velocity_m_s.y, second.velocity_m_s.z),
            )
            <= 1e-6
        )
        assert (
            math.dist(
                (
                    first.acceleration_m_s2.x,
                    first.acceleration_m_s2.y,
                    first.acceleration_m_s2.z,
                ),
                (
                    second.acceleration_m_s2.x,
                    second.acceleration_m_s2.y,
                    second.acceleration_m_s2.z,
                ),
            )
            <= 1e-5
        )
        elapsed += 0.01

    short = resolve_submission(
        source,
        "corner_transition.lookahead_0_20s",
        require_executable=False,
    )
    short_resolution = resolve_capability_resolution(source, short)
    assert short_resolution is not None and short_resolution.feasibility is not None
    assert short_resolution.feasibility.disposition is CapabilityFeasibilityDisposition.CERTIFIED
    assert short_resolution.feasibility.violated_constraints == ()
    short_plan = BoundedJointPlanner().plan(
        source,
        short,
        capability_resolution=short_resolution,
    )
    assert short_plan.search_disposition is SearchDisposition.SELECTED
    assert short_plan.bounded_search_complete

    tiny_budget = child.model_copy(
        update={
            "case_id": "1d.planar_shape_loop.rounded_square.tiny-budget-child",
            "parent_case_sha256": source.case_sha256,
            "search": child.search.model_copy(update={"planning_budget_s": 1e-9}),
        }
    )
    tiny_profile = resolve_submission(tiny_budget, "corner_transition.lookahead_0_60s")
    tiny_resolution = resolve_capability_resolution(tiny_budget, tiny_profile)
    tiny_plan = BoundedJointPlanner().plan(
        tiny_budget,
        tiny_profile,
        capability_resolution=tiny_resolution,
    )
    assert tiny_plan.search_disposition is SearchDisposition.BUDGET_EXHAUSTED
    assert not tiny_plan.bounded_search_complete


def test_corner_resolution_changes_for_real_geometry_stop_and_clearance_changes(
    catalog: CampaignCatalog,
) -> None:
    source = catalog.get("1d.planar_shape_loop.rounded_square")
    drone = source.drones[0]
    assert source.semantics is not None
    profile = resolve_submission(source, "corner_transition.lookahead_0_60s")
    baseline = resolve_capability_resolution(source, profile)
    assert baseline is not None

    def moved_region(index: int, *, x: float, y: float):
        region = drone.goal_sequence[index]
        center = region.center_m
        offset_x = x - center.x
        offset_y = y - center.y
        return region.model_copy(
            update={
                "minimum_m": region.minimum_m.model_copy(
                    update={
                        "x": region.minimum_m.x + offset_x,
                        "y": region.minimum_m.y + offset_y,
                    }
                ),
                "maximum_m": region.maximum_m.model_copy(
                    update={
                        "x": region.maximum_m.x + offset_x,
                        "y": region.maximum_m.y + offset_y,
                    }
                ),
            }
        )

    shortened_goals = list(drone.goal_sequence)
    shortened_goals[2] = moved_region(2, x=-0.10, y=-0.60)
    shortened = source.model_copy(
        update={
            "case_id": "1d.planar_shape_loop.rounded_square.shortened-child",
            "parent_case_sha256": source.case_sha256,
            "drones": (drone.model_copy(update={"goal_sequence": tuple(shortened_goals)}),),
        }
    )
    shortened_resolution = resolve_capability_resolution(
        shortened,
        resolve_submission(shortened, "corner_transition.lookahead_0_60s"),
    )
    assert shortened_resolution is not None
    assert shortened_resolution.normalized_geometry_sha256 != baseline.normalized_geometry_sha256
    assert shortened_resolution.adjacent_segment_cap_m < baseline.adjacent_segment_cap_m

    perturbed_goals = list(drone.goal_sequence)
    midpoint_x = (drone.goal_sequence[1].center_m.x + drone.goal_sequence[2].center_m.x) / 2
    inserted = drone.goal_sequence[1].model_copy(
        update={
            "region_id": "non-collinear-perturbation",
            "minimum_m": drone.goal_sequence[1].minimum_m.model_copy(
                update={"x": midpoint_x - 0.04, "y": -0.56 - 0.04}
            ),
            "maximum_m": drone.goal_sequence[1].maximum_m.model_copy(
                update={"x": midpoint_x + 0.04, "y": -0.56 + 0.04}
            ),
        }
    )
    perturbed_goals.insert(2, inserted)
    route_nodes = list(source.route_nodes_for(drone.role_id))
    route_nodes.insert(
        2,
        route_nodes[1].model_copy(update={"region_id": inserted.region_id}),
    )
    perturbed = source.model_copy(
        update={
            "case_id": "1d.planar_shape_loop.rounded_square.perturbed-child",
            "parent_case_sha256": source.case_sha256,
            "drones": (drone.model_copy(update={"goal_sequence": tuple(perturbed_goals)}),),
            "semantics": source.semantics.model_copy(
                update={
                    "route_intent_by_role": {
                        **source.semantics.route_intent_by_role,
                        drone.role_id: tuple(route_nodes),
                    }
                }
            ),
        }
    )
    perturbed_resolution = resolve_capability_resolution(
        perturbed,
        resolve_submission(perturbed, "corner_transition.lookahead_0_60s"),
    )
    assert perturbed_resolution is not None
    assert perturbed_resolution.normalized_geometry_sha256 != baseline.normalized_geometry_sha256

    stop_goal = inserted.model_copy(
        update={
            "region_id": "collinear-required-stop",
            "minimum_m": inserted.minimum_m.model_copy(update={"y": -0.64}),
            "maximum_m": inserted.maximum_m.model_copy(update={"y": -0.56}),
        }
    )
    stop_goals = list(drone.goal_sequence)
    stop_goals.insert(2, stop_goal)
    stop_nodes = list(source.route_nodes_for(drone.role_id))
    stop_nodes.insert(
        2,
        stop_nodes[1].model_copy(
            update={"region_id": stop_goal.region_id, "mode": RouteNodeMode.CAPTURE}
        ),
    )
    stopped = source.model_copy(
        update={
            "case_id": "1d.planar_shape_loop.rounded_square.stop-child",
            "parent_case_sha256": source.case_sha256,
            "drones": (drone.model_copy(update={"goal_sequence": tuple(stop_goals)}),),
            "semantics": source.semantics.model_copy(
                update={
                    "route_intent_by_role": {
                        **source.semantics.route_intent_by_role,
                        drone.role_id: tuple(stop_nodes),
                    }
                }
            ),
        }
    )
    stopped_polyline = normalized_route_polyline(stopped, drone.role_id)
    assert stop_goal.center_m in stopped_polyline.normalized_points_m
    assert stopped_polyline.normalized_geometry_sha256 != (
        normalized_route_polyline(source, drone.role_id).normalized_geometry_sha256
    )
    stopped_resolution = resolve_capability_resolution(
        stopped,
        resolve_submission(stopped, "corner_transition.lookahead_0_60s"),
    )
    assert stopped_resolution is not None and stopped_resolution.feasibility is not None
    assert "SEMANTIC_STOP_INCOMPATIBLE_WITH_CORNER_PROFILE" in (
        stopped_resolution.feasibility.violated_constraints
    )

    figure_eight = catalog.get("1d.planar_shape_loop.figure_eight")
    figure_role = figure_eight.drones[0].role_id
    figure_polyline = normalized_route_polyline(figure_eight, figure_role)
    assert (
        sum(
            math.dist((point.x, point.y, point.z), (0.0, 0.0, 0.45)) <= 1e-9
            for point in figure_polyline.normalized_points_m
        )
        == 3
    )

    volume = source.hard_constraints.flight_volume
    reduced_volume = volume.model_copy(
        update={
            "maximum_m": volume.maximum_m.model_copy(update={"y": 0.90}),
        }
    )
    reduced_clearance = source.model_copy(
        update={
            "case_id": "1d.planar_shape_loop.rounded_square.clearance-child",
            "parent_case_sha256": source.case_sha256,
            "hard_constraints": source.hard_constraints.model_copy(
                update={"flight_volume": reduced_volume}
            ),
        }
    )
    clearance_resolution = resolve_capability_resolution(
        reduced_clearance,
        resolve_submission(reduced_clearance, "corner_transition.lookahead_0_60s"),
    )
    assert clearance_resolution is not None
    assert clearance_resolution.protected_free_space_cap_m < baseline.protected_free_space_cap_m


@pytest.mark.parametrize(
    "case_id",
    (
        "2d.bottleneck.canonical_nominal",
        "3d.constrained_volume.canonical_nominal",
        "3d.formation_shape_transform.canonical_nominal",
        "3d.bottleneck.canonical_nominal",
    ),
)
def test_prepared_multidrone_motion_does_not_block_simulation_launch(
    catalog: CampaignCatalog,
    case_id: str,
) -> None:
    case = catalog.get(case_id)
    package = resolve_planning_package(
        case,
        motion_preparation_request=MotionPreparationRequest(),
    )
    plan = BoundedJointPlanner().plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
        first_certified_within_budget=True,
    )

    assert package.planning_submission.path_adherence == (
        resolve_planning_submission(case, None).path_adherence
    )
    assert plan.status is PlanningStatus.READY
    assert plan.feasibility_certificate is not None
    assert plan.feasibility_certificate.passed
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
    )
    assert len(trajectories.trajectories) == case.drone_count


def test_object_bearing_child_retains_flexible_submission_and_plans_joint_lanes(
    catalog: CampaignCatalog,
) -> None:
    source = catalog.get("2d.head_on_conflict.canonical_nominal")
    obstacle = source.hard_constraints.flight_volume.model_copy(
        update={
            "region_id": "line-object",
            "minimum_m": source.hard_constraints.flight_volume.minimum_m.model_copy(
                update={"x": 0.1, "y": -0.2, "z": 0.1}
            ),
            "maximum_m": source.hard_constraints.flight_volume.maximum_m.model_copy(
                update={"x": 0.4, "y": 0.2, "z": 0.6}
            ),
        }
    )
    assert source.semantics is not None
    child = source.model_copy(
        update={
            "case_id": "2d.head-on.object-in-line",
            "parent_case_sha256": source.case_sha256,
            "baseline_sha256": source.case_sha256,
            "semantics": source.semantics.model_copy(
                update={
                    "environment_constraints": (
                        source.semantics.environment_constraints.model_copy(
                            update={"keep_out_regions": (obstacle,)}
                        )
                    )
                }
            ),
        }
    )
    submission = resolve_planning_submission(
        child,
        "constraint_directed.head_on.same_path",
    )

    plan = BoundedJointPlanner().plan(child, planning_submission=submission)

    assert submission.case_sha256 == child.case_sha256
    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    assert plan.selected.generator_id == "fleet-solid-lanes-v1"
    assert plan.feasibility_certificate is not None
    assert plan.feasibility_certificate.passed


@pytest.mark.parametrize(
    ("case_id", "submission_id"),
    (
        (
            "2d.unequal_priority.canonical_nominal",
            "priority.strict_lexicographic",
        ),
        (
            "3d.unequal_priorities.canonical_nominal",
            "priorities.strict_lexicographic",
        ),
    ),
)
def test_priority_submission_preserves_required_source_time_precedence(
    catalog: CampaignCatalog,
    case_id: str,
    submission_id: str,
) -> None:
    case = catalog.get(case_id)
    submission = resolve_planning_submission(case, submission_id)
    plan = BoundedJointPlanner().plan(case, planning_submission=submission)

    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    routes = {route.role_id: route for route in plan.selected.routes}
    prioritized = sorted(case.drones, key=lambda drone: (-drone.priority, drone.role_id))
    assert all(
        routes[later.role_id].route_start_s - routes[earlier.role_id].route_start_s >= 0.1 - 1e-9
        for earlier, later in pairwise(prioritized)
    )


def test_boundary_robustness_compiles_a_runtime_safe_hard_tube(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.boundary_constrained_route.canonical_nominal")
    baseline = resolve_planning_package(case, None, None).planning_submission
    subject = resolve_planning_submission(case, "boundary.robustness_first")
    planner = BoundedJointPlanner()
    baseline_plan = planner.plan(case, planning_submission=baseline)
    subject_plan = planner.plan(case, planning_submission=subject)

    assert baseline_plan.selected is not None and subject_plan.selected is not None
    baseline_trajectory = generate_smooth_trajectories(
        case,
        baseline_plan.selected,
        planning_submission=baseline,
    ).trajectories[0]
    subject_trajectory = generate_smooth_trajectories(
        case,
        subject_plan.selected,
        planning_submission=subject,
    ).trajectories[0]
    baseline_samples = _independent_samples(baseline_trajectory)
    subject_samples = _independent_samples(subject_trajectory)
    volume = case.hard_constraints.flight_volume
    radius = subject.clearance.nominal_vehicle_radius_m

    def protected_boundary(samples: tuple[dict[str, object], ...]) -> float:
        return min(
            min(
                point[0] - volume.minimum_m.x - radius,
                volume.maximum_m.x - point[0] - radius,
                point[1] - volume.minimum_m.y - radius,
                volume.maximum_m.y - point[1] - radius,
            )
            for sample in samples
            for point in (sample["position_m"],)
        )

    authored = tuple(point for route in subject_plan.selected.routes for point in route.points_m)
    maximum_reference_deviation = max(
        _point_polyline_distance(sample["position_m"], authored) for sample in subject_samples
    )

    assert protected_boundary(subject_samples) >= protected_boundary(baseline_samples) + 0.01
    assert maximum_reference_deviation <= 0.03 + 1e-9
