from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from crazyswarm_app.campaign.analyzer import (
    AnalysisParameters,
    RootCauseStage,
    analyze_execution,
    compare_execution_modes,
)
from crazyswarm_app.campaign.catalog import CampaignCatalog, migrate_case_bytes
from crazyswarm_app.campaign.execution import compile_campaign_execution_programs
from crazyswarm_app.campaign.models import (
    LifecycleRecord,
    LifecycleState,
    PlannerStrategy,
    Region3D,
    RouteNodeMode,
)
from crazyswarm_app.campaign.planner import BoundedJointPlanner, PlanningStatus
from crazyswarm_app.campaign.replanning import (
    BoundedGoalUpdateQueue,
    CutoverAcknowledgements,
    FleetRouteReplacement,
    GoalUpdate,
    GoalUpdateDisposition,
    ReplanObservation,
    SingleDroneReplanner,
    atomic_fleet_replan,
)
from crazyswarm_app.campaign.scenario import compile_scenario_trace
from crazyswarm_app.campaign.scheduling import build_ground_first_schedule
from crazyswarm_app.campaign.semantic_audit import SemanticAuditClassification
from crazyswarm_app.campaign.timing import BoundedTimingTrace, TimingStage, classify_timing_trace
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.trajectory import GroundWaitExecutionOperation
from crazyswarm_app.safety.policy import SafetyPolicy


@pytest.fixture(scope="module")
def catalog() -> CampaignCatalog:
    value = CampaignCatalog(Path("missions/campaigns/sim/cases"), policy=SafetyPolicy())
    value.discover()
    return value


def test_successor_catalog_is_semantically_distinct_and_fail_closed(
    catalog: CampaignCatalog,
) -> None:
    cases = catalog.cases()
    assert len(cases) == 55
    assert len({case.case_sha256 for case in cases}) == len(cases)
    assert len({case.execution_semantics_sha256 for case in cases}) == len(cases)
    assert {case.drone_count for case in cases} == {1, 2, 3}
    assert catalog.get("three_drone_multi_conflict").variation_name == ("wide_priority_200_150_100")
    assert (
        catalog.get("three_drone_multi_conflict").case_sha256
        == "3a41c886c64b5c1c73998164ae41b6a9a6ac1150911f5e7f126688f384b06c96"
    )
    assert all(case.drone_count <= 3 for case in cases)
    dynamic = [case for case in cases if case.implementation_milestone is not None]
    assert len(dynamic) == 20
    assert {case.implementation_milestone for case in dynamic} == {
        "WP-34A",
        "WP-34B",
        "WP-36B",
        "WP-37B",
        "WP-38B",
    }
    assert all(case.implementation_status.value == "PLANNED_NOT_EXECUTABLE" for case in dynamic)
    assert all(case.execution_eligibility.value == "STATIC_VALIDATE_ONLY" for case in dynamic)
    assert all(compile_scenario_trace(case).all_expected_dispositions_observed for case in dynamic)
    quarantined = {
        item.case_id
        for item in catalog.semantic_audits()
        if item.classification is SemanticAuditClassification.PLACEHOLDER_QUARANTINED
    }
    assert quarantined == {
        *(case.case_id for case in dynamic),
        "2d.overtake.canonical_nominal",
        "2d.role_allocation.canonical_nominal",
        "3d.role_allocation.canonical_nominal",
    }

    complete = CampaignCatalog(
        Path("missions/campaigns/sim/cases"),
        additional_roots=(Path("missions/campaigns/real/authorized_cases"),),
    )
    complete.discover()
    assert set(complete.hierarchy()) == {"Real", "Simulation"}
    assert all(
        case.authorization.value == "NOT_AUTHORIZED"
        for case in complete.cases()
        if case.environment.value == "REAL"
    )


def test_semantic_fingerprint_ignores_prose_but_covers_route_modes(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.continuous_waypoint_sequence.canonical_nominal")
    prose = case.model_copy(update={"purpose": "Different operator-facing prose."})
    assert prose.case_sha256 != case.case_sha256
    assert prose.execution_semantics_sha256 == case.execution_semantics_sha256

    semantics = case.semantics
    assert semantics is not None
    nodes = semantics.route_intent_by_role["Alpha"]
    changed_node = nodes[0].model_copy(update={"mode": RouteNodeMode.CAPTURE})
    changed_semantics = semantics.model_copy(
        update={
            "route_intent_by_role": {
                **semantics.route_intent_by_role,
                "Alpha": (changed_node, *nodes[1:]),
            }
        }
    )
    changed = case.model_copy(update={"semantics": changed_semantics})
    assert changed.execution_semantics_sha256 != case.execution_semantics_sha256


@pytest.mark.parametrize(
    ("field", "unsupported"),
    (("kind", "UNSUPPORTED_ORACLE"), ("mode", "UNSUPPORTED_ROUTE_MODE")),
)
def test_unsupported_semantic_behavior_fails_during_case_parsing(
    catalog: CampaignCatalog,
    field: str,
    unsupported: str,
) -> None:
    case = catalog.get("1d.altitude_transition.canonical_nominal")
    payload = case.model_dump(mode="json")
    semantics = payload["semantics"]
    assert isinstance(semantics, dict)
    if field == "kind":
        semantics["behavior_oracles"][0][field] = unsupported
    else:
        semantics["route_intent_by_role"]["Alpha"][0][field] = unsupported
    with pytest.raises(ValueError, match=unsupported):
        type(case).model_validate(payload)


def test_static_qualification_manifest_binds_every_active_case(
    catalog: CampaignCatalog,
) -> None:
    manifest = json.loads(
        Path("missions/campaigns/sim/qualification/catalog-static-qualification-v2.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["qualification_kind"] == "FAIL_CLOSED_STATIC_COMPILATION"
    assert manifest["case_count"] == len(catalog.cases())
    assert manifest["executable_case_count"] == 31
    assert manifest["quarantined_case_count"] == 23
    assert manifest["planned_blocked_case_count"] == 2
    rows = {row["case_id"]: row for row in manifest["cases"]}
    assert set(rows) == {case.case_id for case in catalog.cases()}
    for case in catalog.cases():
        row = rows[case.case_id]
        assert row["case_sha256"] == case.case_sha256
        assert row["execution_semantics_sha256"] == case.execution_semantics_sha256
        assert row["plan_sha256"]
        if row["planning_status"] == "READY":
            assert row["trajectory_set_sha256"]
        else:
            assert case.implementation_status.value == "PLANNED_NOT_EXECUTABLE"
            assert row["trajectory_set_sha256"] is None
        assert row["accelerated_execution"] in {
            "NOT_RUN_BY_STATIC_QUALIFIER",
            "NOT_AUTHORIZED_FOR_QUARANTINED_DEFINITION",
        }


def test_case_hash_migration_and_catalog_discovery_are_deterministic(
    catalog: CampaignCatalog,
    tmp_path: Path,
) -> None:
    case = catalog.get("1d.move_return.canonical_nominal")
    changed_payload = case.model_dump(mode="python")
    changed_payload["execution"] = {
        **changed_payload["execution"],
        "seed": case.execution.seed + 1,
    }
    changed = type(case).model_validate(changed_payload)
    assert changed.case_sha256 != case.case_sha256

    v1_payload = case.model_dump(mode="json")
    v1_payload["schema_version"] = 1
    source = json.dumps(v1_payload, sort_keys=True).encode()
    receipt = migrate_case_bytes(source)
    assert receipt.source_schema_version == 1
    assert receipt.target_schema_version == 2
    assert receipt.source_bytes_sha256 != receipt.migrated_case_sha256
    assert receipt.migrated_case.case_id == case.case_id
    assert receipt.migrated_case.case_sha256 == case.case_sha256

    manifest = tmp_path / "case.json"
    manifest.write_text(json.dumps(case.model_dump(mode="json")), encoding="utf-8")
    isolated = CampaignCatalog(tmp_path)
    assert tuple(entry.case.case_id for entry in isolated.discover()) == (case.case_id,)
    assert tuple(entry.case.case_id for entry in isolated.discover()) == (case.case_id,)
    (tmp_path / "unknown.txt").write_text("not a case", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown catalog file"):
        isolated.discover()


def test_lifecycle_is_separate_and_requires_evidence_for_baseline(catalog: CampaignCatalog) -> None:
    case = catalog.get("1d.takeoff_hover_land.canonical_nominal")
    record = LifecycleRecord(case_id=case.case_id, case_sha256=case.case_sha256)
    ready = record.transition(LifecycleState.READY, actor_id="validator", reason="static pass")
    active = ready.transition(
        LifecycleState.ACTIVE_DEVELOPMENT,
        actor_id="operator",
        reason="selected",
    )
    with pytest.raises(ValueError, match="requires evidence"):
        active.transition(LifecycleState.BASELINED, actor_id="operator", reason="missing")
    assert case.case_sha256 == record.case_sha256


@pytest.mark.parametrize("source", list(LifecycleState))
@pytest.mark.parametrize("target", list(LifecycleState))
def test_operator_override_can_move_between_any_distinct_lifecycle_states(
    catalog: CampaignCatalog,
    source: LifecycleState,
    target: LifecycleState,
) -> None:
    if source is target:
        return
    case = catalog.get("1d.takeoff_hover_land.canonical_nominal")
    record = LifecycleRecord(
        case_id=case.case_id,
        case_sha256=case.case_sha256,
        state=source,
    )

    changed = record.transition(
        target,
        actor_id="operator",
        reason="explicit lifecycle correction",
        require_qualification_evidence=False,
    )

    assert changed.state is target
    assert changed.transitions[-1].previous_state is source
    assert changed.transitions[-1].new_state is target


def test_canonical_planner_uses_ground_first_and_smooth_c2(catalog: CampaignCatalog) -> None:
    case = catalog.get("three_drone_multi_conflict")
    first = BoundedJointPlanner().plan(case)
    second = BoundedJointPlanner().plan(case)
    assert first.status is PlanningStatus.READY
    assert first.plan_sha256 == second.plan_sha256
    assert first.selected is not None
    assert first.selected.generator_id == "joint-ground-delay-v1"
    assert first.selected.predicted_minimum_separation_m is not None
    assert first.selected.predicted_minimum_separation_m >= 0.80
    schedule = build_ground_first_schedule(case, first.selected)
    assert max(role.energy.airborne_hover_s for role in schedule.roles) <= 2.0
    assert (
        max(role.energy.predicted_end_battery_percent for role in schedule.roles)
        - min(role.energy.predicted_end_battery_percent for role in schedule.roles)
        <= 1.0
    )
    assert schedule.wall_watchdog_s >= (schedule.source_schedule_duration_s / 0.80 + 2.0)
    trajectories = generate_smooth_trajectories(case, first.selected)
    assert all(item.passed and item.c2_continuous for item in trajectories.audits)
    assert all(item.generated_unintended_stop_count == 0 for item in trajectories.audits)
    programs = compile_campaign_execution_programs(
        case=case,
        plan=first,
        schedule=schedule,
        trajectories=trajectories,
        mission_source_sha256=case.case_sha256,
    )
    assert not isinstance(programs[0].operations[0], GroundWaitExecutionOperation)
    assert all(
        isinstance(program.operations[0], GroundWaitExecutionOperation) for program in programs[1:]
    )
    assert all(program.execution_timeout_s == schedule.wall_watchdog_s for program in programs)


def test_planner_rejects_landing_on_a_waiting_vehicle_pad(catalog: CampaignCatalog) -> None:
    """Ground delay must not make a route look safe by hiding a grounded peer."""

    def region(region_id: str, x_m: float) -> Region3D:
        return Region3D(
            region_id=region_id,
            minimum_m=Vector3(x=x_m - 0.02, y=-0.02, z=0.33),
            maximum_m=Vector3(x=x_m + 0.02, y=0.02, z=0.37),
        )

    source = catalog.get("2d.bottleneck.canonical_nominal")
    alpha, beta = source.drones
    alpha_start = region("alpha-start", -0.40)
    beta_start = region("beta-start", 0.40)
    unsafe = source.model_copy(
        update={
            "case_id": "2d.bottleneck.occupied-pad-regression",
            "semantics": None,
            "drones": (
                alpha.model_copy(
                    update={
                        "start_region": alpha_start,
                        "goal_sequence": (region("alpha-mid", 0.0),),
                        "landing_region": beta_start,
                    }
                ),
                beta.model_copy(
                    update={
                        "start_region": beta_start,
                        "goal_sequence": (region("beta-mid", 0.0),),
                        "landing_region": alpha_start,
                    }
                ),
            ),
            "allowed_strategies": (PlannerStrategy.GROUND_DELAY,),
        }
    )

    result = BoundedJointPlanner().plan(unsafe)

    assert result.status is PlanningStatus.BLOCKED
    assert result.selected is None
    assert all(
        candidate.predicted_minimum_separation_m is not None
        and candidate.predicted_minimum_separation_m
        < unsafe.hard_constraints.warning_separation_m
        + unsafe.hard_constraints.position_uncertainty_m
        for candidate in result.retained_candidates
    )


def test_offline_analyzer_uses_source_clock_and_classifies_watchdog(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("2d.parallel_routes.canonical_nominal")
    content = _csv_fixture()
    analysis = analyze_execution(
        case=case,
        manifest={
            "mission_execution_id": "execution-timeout",
            "status": "ABORTED",
            "reason_code": "MISSION_TIMEOUT",
            "case_sha256": case.case_sha256,
        },
        bundle={
            "mission_execution_id": "execution-timeout",
            "case_sha256": case.case_sha256,
            "assignments": {"Alpha": "Alpha", "Beta": "Beta"},
            "faults": ["wall watchdog expired"],
        },
        csv_bytes=content,
        parameters=AnalysisParameters(source_resample_step_s=0.1, smoothing_window_s=0.0),
    )
    assert analysis.telemetry_row_count == 8
    assert analysis.primary_cause.stage is RootCauseStage.SIM_TIMING
    assert analysis.primary_cause.confidence >= 0.90
    assert analysis.minimum_truth_separation_m == pytest.approx(1.0, abs=0.005)
    assert all(
        item.acceleration_m_s2.peak == pytest.approx(0.0, abs=1e-8) for item in analysis.vehicles
    )

    single_case = catalog.get("1d.takeoff_hover_land.canonical_nominal")
    single_vehicle = analysis.vehicles[0].model_copy(
        update={"source_clock_target_error_s": None}
    )
    single_mode = analysis.model_copy(
        update={
            "case_sha256": single_case.case_sha256,
            "vehicles": (single_vehicle,),
            "pair_separation": (),
            "minimum_truth_separation_m": None,
        }
    )
    not_applicable = compare_execution_modes(single_case, single_mode, single_mode)
    assert not not_applicable.source_clock_target_error_gate_applicable
    assert not not_applicable.minimum_separation_gate_applicable
    assert not_applicable.source_clock_target_error_gate_passed
    assert not_applicable.minimum_separation_gate_passed
    assert not_applicable.all_gates_passed

    asymmetric = single_mode.model_copy(
        update={
            "vehicles": (
                single_vehicle.model_copy(update={"source_clock_target_error_s": 0.0}),
            )
        }
    )
    invalid = compare_execution_modes(single_case, single_mode, asymmetric)
    assert invalid.source_clock_target_error_gate_applicable
    assert not invalid.source_clock_target_error_gate_passed
    assert not invalid.all_gates_passed


def test_offline_analyzer_bounds_irregular_duplicate_missing_and_reordered_samples(
    catalog: CampaignCatalog,
) -> None:
    rows = list(csv.DictReader(io.StringIO(_csv_fixture().decode())))
    alpha = [row for row in rows if row["vehicle_id"] == "Alpha"]
    beta = [row for row in rows if row["vehicle_id"] == "Beta"]
    alpha[-1]["telemetry_sequence"] = "5"
    irregular = [alpha[0], alpha[2], alpha[1], dict(alpha[1]), alpha[3], *beta]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
    writer.writeheader()
    writer.writerows(irregular)
    case = catalog.get("2d.parallel_routes.canonical_nominal")
    analysis = analyze_execution(
        case=case,
        manifest={"mission_execution_id": "irregular-samples", "status": "SUCCEEDED"},
        bundle={"mission_execution_id": "irregular-samples"},
        csv_bytes=stream.getvalue().encode(),
    )
    analyzed_alpha = next(item for item in analysis.vehicles if item.vehicle_id == "Alpha")
    assert analyzed_alpha.duplicate_sample_count == 1
    assert analyzed_alpha.missing_sequence_count == 1
    assert analyzed_alpha.out_of_order_sample_count == 1
    assert analyzed_alpha.acceleration_m_s2.peak == pytest.approx(0.0, abs=1e-8)
    assert analyzed_alpha.jerk_m_s3.peak == pytest.approx(0.0, abs=1e-8)


def test_timing_trace_localizes_sim_delivery_and_render_stalls() -> None:
    simulator = BoundedTimingTrace("trace-sim")
    for sequence in range(1, 5):
        simulator.record(
            correlation_id=f"sample-{sequence}",
            stage=TimingStage.SIMULATOR_STEP,
            source_timestamp_s=sequence * 0.1,
            source_clock_id="clock",
            source_clock_epoch=1,
            observed_monotonic_s=sequence * 0.2,
        )
    assert classify_timing_trace(simulator.snapshot()).stage is RootCauseStage.SIM_TIMING

    delivery = BoundedTimingTrace("trace-delivery")
    _timing_pair(delivery, TimingStage.WEBSOCKET_ENQUEUE, TimingStage.WEBSOCKET_DELIVERY, 0.7)
    assert classify_timing_trace(delivery.snapshot()).stage is RootCauseStage.EVIDENCE_DELIVERY

    rendering = BoundedTimingTrace("trace-render")
    _timing_pair(rendering, TimingStage.BROWSER_RECEIPT, TimingStage.RENDER_FRAME, 0.3)
    assert classify_timing_trace(rendering.snapshot()).stage is RootCauseStage.UI_RENDERING


def test_single_and_fleet_replanning_are_deterministic_and_atomic(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("1d.moving_target.dynamic_nominal")
    update = GoalUpdate(
        source_id="operator-goal",
        sequence=1,
        update_id="goal-update-1",
        source_timestamp_s=2.0,
        requested_effective_time_s=2.5,
        goal_revision=1,
        goal_region=Region3D(
            region_id="replacement-goal",
            minimum_m=Vector3(x=0.4, y=-0.05, z=0.25),
            maximum_m=Vector3(x=0.5, y=0.05, z=0.35),
        ),
    )
    observation = ReplanObservation.create(
        observation_id="observation-1",
        role_id="Alpha",
        source_timestamp_s=2.0,
        captured_at_source_s=2.0,
        position_m=Vector3(x=0.0, y=0.0, z=0.3),
        velocity_m_s=Vector3(x=0.05, y=0.0, z=0.0),
    )
    acknowledgements = CutoverAcknowledgements(
        old_future_cancelled=True,
        old_future_cancellation_acknowledged=True,
        replacement_command_acknowledged=True,
        replacement_authority_acknowledged=True,
    )
    first_replanner = SingleDroneReplanner(case, role_id="Alpha")
    first = first_replanner.replan(
        update,
        observation,
        decision_time_source_s=2.1,
        old_plan_sha256="1" * 64,
        old_trajectory_sha256="2" * 64,
        old_reservation_sha256="3" * 64,
        acknowledgements=acknowledgements,
    )
    second = SingleDroneReplanner(case, role_id="Alpha").replan(
        update,
        observation,
        decision_time_source_s=2.1,
        old_plan_sha256="1" * 64,
        old_trajectory_sha256="2" * 64,
        old_reservation_sha256="3" * 64,
        acknowledgements=acknowledgements,
    )
    assert first.disposition is GoalUpdateDisposition.ACCEPTED
    assert first.decision_sha256 == second.decision_sha256
    assert first.replacement_trajectory is not None
    assert first.replacement_trajectory.points[0].velocity_m_s == observation.velocity_m_s
    duplicate = first_replanner.replan(
        update,
        observation,
        decision_time_source_s=2.1,
        old_plan_sha256="1" * 64,
        old_trajectory_sha256="2" * 64,
        old_reservation_sha256="3" * 64,
        acknowledgements=acknowledgements,
    )
    assert duplicate.disposition is GoalUpdateDisposition.DUPLICATE_IDEMPOTENT
    assert duplicate.authority_sha256 == first.authority_sha256
    assert duplicate.decision_sha256 != first.decision_sha256

    queue = BoundedGoalUpdateQueue(maximum_sources=2)
    assert queue.submit(update) is GoalUpdateDisposition.ACCEPTED
    assert queue.submit(update) is GoalUpdateDisposition.DUPLICATE_IDEMPOTENT
    newer = update.model_copy(
        update={"update_id": "goal-update-2", "sequence": 2, "goal_revision": 2}
    )
    assert queue.submit(newer) is GoalUpdateDisposition.ACCEPTED
    assert queue.pending() == (newer,)

    fleet_case = catalog.get("3d.cascading_replan.dynamic_nominal")
    replacements = tuple(
        FleetRouteReplacement(
            role_id=role,
            old_trajectory_sha256=str(index) * 64,
            replacement_trajectory_sha256=str(index + 3) * 64,
            replacement_plan_sha256=str(index + 6) * 64,
            feasible=index != 2,
            cancellation_acknowledged=True,
            replacement_acknowledged=True,
        )
        for index, role in enumerate(("Alpha", "Beta", "Gamma"), start=1)
    )
    blocked = atomic_fleet_replan(
        case=fleet_case,
        old_epoch=1,
        old_reservation_sha256="a" * 64,
        updates=(update,),
        replacements=replacements,
        shared_cutover_source_s=3.0,
        old_epoch_still_safe=False,
    )
    assert blocked.disposition is GoalUpdateDisposition.BLOCKED
    assert blocked.committed_route_count == 0


def _timing_pair(
    trace: BoundedTimingTrace,
    first: TimingStage,
    second: TimingStage,
    delay_s: float,
) -> None:
    for stage, wall in ((first, 1.0), (second, 1.0 + delay_s)):
        trace.record(
            correlation_id="sample-1",
            stage=stage,
            source_timestamp_s=1.0,
            source_clock_id="clock",
            source_clock_epoch=1,
            observed_monotonic_s=wall,
        )


def _csv_fixture() -> bytes:
    stream = io.StringIO(newline="")
    fields = [
        "vehicle_id",
        "recorded_at_utc",
        "source_timestamp_s",
        "simulation_timestamp_s",
        "telemetry_sequence",
        "source_clock_id",
        "source_clock_epoch",
        "position_x_m",
        "position_y_m",
        "position_z_m",
        "ground_truth_x_m",
        "ground_truth_y_m",
        "ground_truth_z_m",
        "battery_percent",
        "state",
        "flying",
        "faults_json",
    ]
    writer = csv.DictWriter(stream, fields, lineterminator="\n")
    writer.writeheader()
    wall_offsets = (0.0, 0.1, 1.5, 1.6)
    for vehicle, y in (("Alpha", 0.0), ("Beta", 1.0)):
        for sequence, (source, wall) in enumerate(
            zip((0.0, 0.1, 0.2, 0.3), wall_offsets, strict=True), start=1
        ):
            writer.writerow(
                {
                    "vehicle_id": vehicle,
                    "recorded_at_utc": f"2026-08-09T12:00:{wall:06.3f}+00:00",
                    "source_timestamp_s": source,
                    "simulation_timestamp_s": source,
                    "telemetry_sequence": sequence,
                    "source_clock_id": "sim-clock",
                    "source_clock_epoch": 1,
                    "position_x_m": source,
                    "position_y_m": y,
                    "position_z_m": 0.3,
                    "ground_truth_x_m": source,
                    "ground_truth_y_m": y,
                    "ground_truth_z_m": 0.3,
                    "battery_percent": 100 - source,
                    "state": "FLYING" if sequence < 4 else "EMERGENCY",
                    "flying": "true",
                    "faults_json": "[]",
                }
            )
    return stream.getvalue().encode()
