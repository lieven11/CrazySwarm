from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path

import pytest

from crazyswarm_app.campaign.analyzer import AnalysisParameters, RootCauseStage, analyze_execution
from crazyswarm_app.campaign.catalog import CampaignCatalog, migrate_case_bytes
from crazyswarm_app.campaign.execution import compile_campaign_execution_programs
from crazyswarm_app.campaign.models import LifecycleRecord, LifecycleState, Region3D
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
from crazyswarm_app.campaign.scheduling import build_ground_first_schedule
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


def test_wp33_catalog_is_complete_immutable_and_non_executing(catalog: CampaignCatalog) -> None:
    cases = catalog.cases()
    assert len(cases) >= 100
    assert len({case.case_sha256 for case in cases}) == len(cases)
    families = Counter((case.drone_count, case.family) for case in cases)
    assert families[(1, "takeoff_hover_land")] >= 3
    assert families[(2, "perpendicular_crossing")] >= 9
    assert families[(3, "simultaneous_center_conflict")] >= 9
    assert catalog.get("three_drone_multi_conflict").variation_name == ("wide_priority_200_150_100")
    assert all(case.drone_count <= 3 for case in cases)
    dynamic = [case for case in cases if case.implementation_milestone is not None]
    assert len(dynamic) == 13
    assert {case.implementation_milestone for case in dynamic} == {"WP-34A", "WP-34B"}
    assert all(case.implementation_status.value == "EXECUTABLE" for case in dynamic)

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
        isinstance(program.operations[0], GroundWaitExecutionOperation)
        for program in programs[1:]
    )
    assert all(program.execution_timeout_s == schedule.wall_watchdog_s for program in programs)


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
