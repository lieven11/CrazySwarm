from __future__ import annotations

import json
from pathlib import Path

import pytest

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import (
    LockedDevelopmentInputs,
    Region3D,
    ReplanningAuthority,
    ScenarioEvent,
    ScenarioEventKind,
    ScenarioExpectedDisposition,
)
from crazyswarm_app.campaign.planner import BoundedJointPlanner, PlanningStatus
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.scheduling import build_ground_first_schedule
from crazyswarm_app.campaign.service import (
    CampaignExecutionRequest,
    CampaignRunMode,
    CampaignRunStatus,
    CampaignService,
)
from crazyswarm_app.campaign.submissions import resolve_planning_package
from crazyswarm_app.campaign.timing import BoundedTimingTrace
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario


def test_execution_request_rejects_tampered_schedule_and_trajectory_chain() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.takeoff_hover_land.canonical_nominal")
    package = resolve_planning_package(case)
    plan = BoundedJointPlanner().plan(
        case,
        planning_submission=package.planning_submission,
    )
    assert plan.selected is not None
    schedule = build_ground_first_schedule(
        case,
        plan.selected,
        planning_submission_id=package.planning_submission.planning_submission_id,
        planning_submission_sha256=(
            package.planning_submission.planning_submission_sha256
        ),
    )
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        planning_submission=package.planning_submission,
    )
    lock = LockedDevelopmentInputs.from_case(
        case,
        submission_id=package.execution_profile.submission_id,
        submission_sha256=package.execution_profile.profile_sha256,
        planning_submission_id=package.planning_submission.planning_submission_id,
        planning_submission_sha256=(
            package.planning_submission.planning_submission_sha256
        ),
        resolved_planning_package_sha256=package.resolved_package_sha256,
    )
    common = {
        "run_id": "tamper-proof-execution-chain",
        "mode": CampaignRunMode.AUTOMATED_ACCELERATED,
        "locked_inputs": lock,
        "resolved_package": package,
        "case": case,
        "plan": plan,
    }

    CampaignExecutionRequest(
        **common,
        schedule=schedule,
        trajectories=trajectories,
    )
    with pytest.raises(ValueError, match="schedule differs"):
        CampaignExecutionRequest(
            **common,
            schedule=schedule.model_copy(
                update={
                    "source_schedule_duration_s": (
                        schedule.source_schedule_duration_s + 1.0
                    )
                }
            ),
            trajectories=trajectories,
        )
    with pytest.raises(ValueError, match="trajectories differ"):
        CampaignExecutionRequest(
            **common,
            schedule=schedule,
            trajectories=trajectories.model_copy(update={"set_sha256": "0" * 64}),
        )


@pytest.mark.asyncio
async def test_altitude_speed_submission_executes_with_profile_and_actuator_evidence(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.ACCELERATED}
            )
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
        executor=FastSimCampaignExecutor(runtime),
    )

    await runtime.start()
    try:
        service.set_active(
            "1d.altitude_transition.canonical_nominal",
            actor_id="campaign-profile-test",
            reason="qualify the admitted stress time law",
        )
        baseline_review = await service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="altitude-retained-baseline",
        )
        slow_review = await service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="altitude-slow-profile",
            submission_id="constant_path_speed.slow",
        )
        review = await service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="altitude-stress-profile",
            submission_id="constant_path_speed.stress",
        )
    finally:
        await runtime.stop()

    assert review.status is CampaignRunStatus.SUCCEEDED
    assert baseline_review.status is CampaignRunStatus.SUCCEEDED
    assert slow_review.status is CampaignRunStatus.SUCCEEDED
    assert review.baseline_comparison["comparison_kind"] == (
        "EXACT_CASE_SUBMISSION_BASELINE"
    )
    assert review.baseline_comparison["baseline_available"] is True
    assert review.baseline_comparison["baseline_run_id"] == baseline_review.run_id
    run = service.state.runs[-1]
    assert run.locked_inputs.submission_id == "constant_path_speed.stress"
    assert run.locked_inputs.submission_sha256
    evaluation = json.loads(
        (
            tmp_path
            / "campaign"
            / "evidence"
            / review.analysis.mission_execution_id
            / "evaluation.json"
        ).read_text(encoding="utf-8")
    )
    vehicle = evaluation["vehicles"][0]
    assert evaluation["status"] == "COMPLETE"
    assert vehicle["profile_submission_id"] == "constant_path_speed.stress"
    assert vehicle["planned_profile_conformance_passed"] is True
    assert vehicle["trajectory_speed_rms_error_m_s"] is not None
    assert vehicle["profile_steady_speed_ripple_m_s"] <= 0.05
    assert vehicle["profile_steady_speed_tracking_rms_error_m_s"] <= 0.03
    assert vehicle["peak_requested_motor_thrust_n"] > 0.0
    assert vehicle["peak_applied_pwm_percent"] > 0.0
    assert vehicle["minimum_motor_thrust_headroom_n"] >= 0.0
    # This remains tighter than the 0.04 m accepted landing region while allowing
    # the seeded estimator-in-loop drift that the controller is required to retain.
    assert vehicle["touchdown_target_center_error_m"] <= 0.03
    assert vehicle["post_contact_settling_s"] >= 0.10
    assert vehicle["motors_cut_after_contact"] is True
    landing = review.analysis.landing[0]
    assert landing.landing_goal_id is not None
    assert landing.terminal_contact == "SIMULATED_GROUND_CONTACT"
    assert landing.post_contact_settling_s is not None
    assert landing.post_contact_settling_s >= 0.10
    assert landing.motors_cut_after_contact is True


@pytest.mark.asyncio
async def test_canonical_campaign_executes_ground_first_through_retained_runtime(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.ACCELERATED}
            )
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    runtime.recorder.timing_trace = BoundedTimingTrace(
        "campaign-execution-test", retention_limit=20_000
    )
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    service = CampaignService(
        catalog=catalog,
        state_directory=tmp_path / "campaign",
        executor=FastSimCampaignExecutor(runtime),
    )

    await runtime.start()
    try:
        lock = service.set_active(
            "3d.simultaneous_center_conflict.joint_schedule_v2",
            actor_id="campaign-test",
            reason="qualify the selected canonical development mission",
        )
        accelerated_review = await service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="canonical-campaign-execution",
        )
        realtime_review = await service.run_active(
            CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
            idempotency_key="canonical-campaign-realtime-observation",
        )
    finally:
        await runtime.stop()

    assert lock.case_id == "3d.simultaneous_center_conflict.joint_schedule_v2"
    for review in (accelerated_review, realtime_review):
        assert review.status is CampaignRunStatus.SUCCEEDED
        assert review.analysis.telemetry_row_count > 5_000
        assert review.analysis.minimum_truth_separation_m is not None
        assert review.analysis.minimum_truth_separation_m >= 0.75
        assert review.analysis.all_required_behavior_oracles_passed
        assert review.analysis.behavior_oracles
        batteries = [
            item.battery_used_percent
            for item in review.analysis.vehicles
            if item.battery_used_percent is not None
        ]
        assert max(batteries) - min(batteries) <= 1.0
        assert all(
            item.timeline.airborne_wait_before_route_s is not None
            and item.timeline.airborne_wait_before_route_s <= 2.0
            for item in review.analysis.vehicles
        )
        assert all(item.unintended_stop_count == 0 for item in review.analysis.vehicles)
        assert all(
            item.tracking_rms_error_m is not None and item.tracking_rms_error_m <= 0.05
            for item in review.analysis.vehicles
        )
        assert all(
            item.tracking_max_error_m is not None and item.tracking_max_error_m <= 0.10
            for item in review.analysis.vehicles
        )
        evidence = tmp_path / "campaign" / "evidence" / review.analysis.mission_execution_id
        assert {path.name for path in evidence.iterdir()} == {
            "analysis.json",
            "evaluation.json",
            "execution-bundle.json",
            "manifest.json",
            "telemetry.csv",
        }

    assert accelerated_review.mode_comparison is None
    assert realtime_review.mode_comparison is not None
    assert realtime_review.mode_comparison.all_gates_passed


@pytest.mark.asyncio
async def test_head_on_runtime_commits_object_conditioned_replacement_epoch(
    tmp_path: Path,
) -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    source = catalog.get("2d.head_on_conflict.canonical_nominal")
    assert source.semantics is not None
    obstacle = Region3D(
        region_id="runtime-line-object",
        minimum_m=Vector3(x=0.1, y=-0.2, z=0.1),
        maximum_m=Vector3(x=0.4, y=0.2, z=0.6),
    )
    event = ScenarioEvent(
        event_id="runtime-line-object-detected",
        kind=ScenarioEventKind.OBSTACLE_ADDED,
        trigger_time_s=8.0,
        replacement_goal=obstacle,
        duration_s=3.0,
        source_id="runtime-world-observer",
        sequence=1,
        generation=1,
        update_identity="runtime-line-object-v1",
        expected_disposition=ScenarioExpectedDisposition.ACCEPTED_UPDATE,
    )
    case = source.model_copy(
        update={
            "case_id": "2d.head_on_conflict.runtime_object_replan",
            "parent_case_sha256": source.case_sha256,
            "baseline_sha256": source.case_sha256,
            "replanning_authority": ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS,
            "semantics": source.semantics.model_copy(
                update={"scenario_events": (event,)}
            ),
        }
    )
    package = resolve_planning_package(
        case,
        "constraint_directed.head_on.same_path",
    )
    plan = BoundedJointPlanner().plan(
        case,
        planning_submission=package.planning_submission,
    )
    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    schedule = build_ground_first_schedule(
        case,
        plan.selected,
        planning_submission_id=package.planning_submission.planning_submission_id,
        planning_submission_sha256=(
            package.planning_submission.planning_submission_sha256
        ),
    )
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        planning_submission=package.planning_submission,
    )
    lock = LockedDevelopmentInputs.from_case(
        case,
        submission_id=package.execution_profile.submission_id,
        submission_sha256=package.execution_profile.profile_sha256,
        planning_submission_id=package.planning_submission.planning_submission_id,
        planning_submission_sha256=(
            package.planning_submission.planning_submission_sha256
        ),
        resolved_planning_package_sha256=package.resolved_package_sha256,
    )
    request = CampaignExecutionRequest(
        run_id="campaign-runtime-object-replan",
        mode=CampaignRunMode.AUTOMATED_ACCELERATED,
        locked_inputs=lock,
        resolved_package=package,
        case=case,
        plan=plan,
        schedule=schedule,
        trajectories=trajectories,
    )
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.ACCELERATED}
            )
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")

    await runtime.start()
    try:
        artifacts = await FastSimCampaignExecutor(runtime)(request)
    finally:
        await runtime.stop()

    assert artifacts.status == "SUCCEEDED"
    trace = artifacts.bundle["context"]["campaign_execution_head_trace"]
    assert trace["enabled"] is True
    assert trace["event_count"] == 1
    assert trace["observation_count"] == 1
    record = next(
        item
        for item in trace["records"]
        if item.get("execution_disposition") == "DISPATCHED"
    )
    assert record["disposition"] == "ACCEPTED"
    assert record["planning_latency_s"] <= case.hard_constraints.planning_budget_s
    assert set(record["replacement_trajectory_sha256_by_role"]) == {"Alpha", "Beta"}
    assert set(record["replacement_authority_sha256_by_role"]) == {"Alpha", "Beta"}
    assert artifacts.evaluation["status"] == "COMPLETE"
    assert "dynamic_replanning" in artifacts.evaluation["evidence"]["present"]
    assert all(
        vehicle["accepted_plan_identity_match"] is True
        for vehicle in artifacts.evaluation["vehicles"]
    )
