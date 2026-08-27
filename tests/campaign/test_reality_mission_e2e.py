from __future__ import annotations

import json
from pathlib import Path

import pytest

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import LifecycleState
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.service import (
    CampaignRunMode,
    CampaignRunStatus,
    CampaignService,
    ReviewDecision,
)
from crazyswarm_app.campaign.submissions import MotionPreparationRequest
from crazyswarm_app.config import load_config
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.faults import FaultType, FaultWindow
from crazyswarm_app.simulation.world import load_scenario


@pytest.mark.parametrize(
    ("run_mode", "clock_mode"),
    (
        (CampaignRunMode.AUTOMATED_ACCELERATED, ClockMode.ACCELERATED),
        (CampaignRunMode.OPERATOR_OBSERVED_REALTIME, ClockMode.REALTIME),
    ),
    ids=("accelerated", "observed-realtime"),
)
@pytest.mark.asyncio
async def test_sensor_sourced_one_drone_reality_mission_replans_and_lands(
    tmp_path: Path,
    run_mode: CampaignRunMode,
    clock_mode: ClockMode,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={"simulation": scenario.simulation.model_copy(update={"clock_mode": clock_mode})}
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    service = CampaignService(
        catalog=catalog,
        state_directory=tmp_path / "campaign",
        executor=FastSimCampaignExecutor(runtime),
    )

    await runtime.start()
    try:
        service.set_lifecycle_state(
            "1d.point_to_point_relocation.canonical_nominal",
            LifecycleState.ACTIVE_DEVELOPMENT,
            actor_id="wp62-e2e",
            reason="explicitly open the static predecessor lifecycle",
        )
        service.set_active(
            "1d.point_to_point_relocation.canonical_nominal",
            actor_id="wp59-e2e",
            reason="qualify the required static predecessor",
        )
        predecessor = await service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="wp59-static-predecessor",
        )
        service.decide_review(
            predecessor.review_id,
            operator_id="wp59-test-operator",
            decision=ReviewDecision.APPROVE,
            reason="test fixture accepts the completed Fast Sim predecessor",
        )
        service.set_active(
            "1d.online_obstacle_replan.dynamic_nominal",
            actor_id="wp59-e2e",
            reason="qualify delayed sensor-sourced changed-world replanning",
        )
        review = await service.run_active(
            run_mode,
            idempotency_key=f"wp62-one-drone-reality-e2e:{run_mode.value}",
            motion_preparation_request=MotionPreparationRequest(),
        )
        cleanup = {
            "dynamic_obstacles_cleared": not runtime.dynamic_obstacles,
            "dynamic_physics_cleared": all(
                getattr(getattr(vehicle, "world", None), "dynamic_timeline", None) is None
                for vehicle in runtime.vehicles.values()
            ),
            "fleet_tasks_terminal": all(task.done() for task in runtime.fleet_tasks.values()),
        }
    finally:
        await runtime.stop()

    assert review.status is CampaignRunStatus.SUCCEEDED
    assert review.analysis.all_required_behavior_oracles_passed
    if run_mode is CampaignRunMode.OPERATOR_OBSERVED_REALTIME:
        realtime_factors = tuple(
            item.realtime_factor
            for item in review.analysis.vehicles
            if item.realtime_factor is not None
        )
        assert realtime_factors
        assert min(realtime_factors) >= 0.8
    assert all(cleanup.values())
    evidence = tmp_path / "campaign" / "evidence" / review.analysis.mission_execution_id
    telemetry_csv = (evidence / "telemetry.csv").read_text(encoding="utf-8")
    assert "TELEMETRY_STALE" not in telemetry_csv
    assert "STALE_FLEET_OBSERVATION" not in telemetry_csv
    bundle = json.loads((evidence / "execution-bundle.json").read_text(encoding="utf-8"))
    context = bundle["context"]
    trace = context["campaign_execution_head_trace"]
    assert trace["enabled"] is True
    assert context["campaign_locked_inputs"]["submission_id"].startswith("prepared-motion.")
    assert (
        trace["execution_profile_sha256"] == context["campaign_locked_inputs"]["submission_sha256"]
    )
    dynamic_world_trace = context["campaign_dynamic_world_trace"]
    assert dynamic_world_trace["timeline_sha256"]
    assert len(dynamic_world_trace["events"]) == 4
    assert all(
        isinstance(event, dict) and event["truth_sha256"] for event in dynamic_world_trace["events"]
    )
    online_case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    assert online_case.semantics is not None
    expected_event_ids = {event.event_id for event in online_case.semantics.scenario_events}
    persisted = [item for item in trace["records"] if item.get("stage") == "PERCEPTION_PERSISTED"]
    recertified = [
        item for item in trace["records"] if item.get("stage") == "MOVING_CUTOVER_RECERTIFIED"
    ]
    dispatched = [
        item for item in trace["records"] if item.get("execution_disposition") == "DISPATCHED"
    ]
    assert {item["event_id"] for item in recertified} == expected_event_ids
    assert {item["event_id"] for item in dispatched} == expected_event_ids
    assert len(persisted) == len(expected_event_ids)
    assert all(
        item["received_timestamp_s"] >= item["source_timestamp_s"] and item["raw_payload_sha256"]
        for item in persisted
    )
    assert all(item["moving_cutover_certificate"]["passed"] for item in recertified)
    assert all(item["safe_prefix_certificate"]["passed"] for item in dispatched)
    assert all(item["replacement_world_sha256"] for item in dispatched)
    child_results = context["fleet_result"]["child_results"]
    assert len(child_results) == 1
    # Source-clock waiting uses the supervised telemetry cache. Only exact
    # planning/cutover observations belong in the durable mission evidence.
    assert len(child_results[0]["mission_result"]["observations_read"]) <= 12
    # Initial accepted planning evidence is case-derived and contains no authored
    # future obstacle solid; geometry appears only after persisted observations.
    assert context["campaign_plan"]["case_sha256"] == context["campaign_case_sha256"]
    assert all(
        "sensed-rock" not in json.dumps(item)
        for item in context["campaign_plan"]["retained_candidates"]
    )


@pytest.mark.asyncio
async def test_production_telemetry_dropout_aborts_cleans_up_and_immediately_retries(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(update={"clock_mode": ClockMode.REALTIME})
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    service = CampaignService(
        catalog=catalog,
        state_directory=tmp_path / "campaign",
        executor=FastSimCampaignExecutor(runtime),
    )

    await runtime.start()
    try:
        service.set_lifecycle_state(
            "1d.point_to_point_relocation.canonical_nominal",
            LifecycleState.ACTIVE_DEVELOPMENT,
            actor_id="wp62-dropout-e2e",
            reason="open the static predecessor lifecycle",
        )
        service.set_active(
            "1d.point_to_point_relocation.canonical_nominal",
            actor_id="wp62-dropout-e2e",
            reason="qualify the static predecessor",
        )
        predecessor = await service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="wp62-dropout-static-predecessor",
        )
        service.decide_review(
            predecessor.review_id,
            operator_id="wp62-dropout-e2e",
            decision=ReviewDecision.APPROVE,
            reason="software-only production-entry fixture",
        )
        service.set_active(
            "1d.online_obstacle_replan.dynamic_nominal",
            actor_id="wp62-dropout-e2e",
            reason="exercise authoritative telemetry dropout",
        )

        runtime.scenario = scenario.model_copy(
            update={
                "faults": (
                    FaultWindow(
                        fault=FaultType.STALE_TELEMETRY,
                        start_s=5.0,
                        end_s=5.65,
                        vehicle_id="Alpha",
                    ),
                )
            }
        )
        failed = await service.run_active(
            CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
            idempotency_key="wp62-production-dropout",
        )
        failed_record = next(item for item in service.state.runs if item.run_id == failed.run_id)
        failed_evidence = tmp_path / "campaign" / "evidence" / failed.analysis.mission_execution_id
        failed_bundle = json.loads(
            (failed_evidence / "execution-bundle.json").read_text(encoding="utf-8")
        )
        failed_fleet = failed_bundle["context"]["fleet_result"]
        failed_cleanup = {
            "dynamic_obstacles": not runtime.dynamic_obstacles,
            "fleet_tasks": not runtime.fleet_tasks,
            "fleet_preparations": not runtime.fleet_preparations,
            "fleet_coordinators": not runtime.fleet_coordinators,
        }

        runtime.scenario = scenario
        retry = await service.run_active(
            CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
            idempotency_key="wp62-production-dropout-immediate-retry",
        )
        retry_cleanup = {
            "dynamic_obstacles": not runtime.dynamic_obstacles,
            "fleet_tasks": not runtime.fleet_tasks,
            "fleet_preparations": not runtime.fleet_preparations,
            "fleet_coordinators": not runtime.fleet_coordinators,
        }
    finally:
        await runtime.stop()

    assert failed.status is not CampaignRunStatus.SUCCEEDED
    assert failed_record.status is CampaignRunStatus.FAILED
    assert failed_fleet["status"] == "FAILED"
    assert failed_fleet["child_results"][0]["mission_result"]["reason_code"] == ("TELEMETRY_STALE")
    assert (
        sum(
            event["event_type"] == "VEHICLE_ABORT_REQUESTED"
            and event["details"].get("reason") == "STALE_FLEET_OBSERVATION"
            for event in failed_fleet["events"]
        )
        == 1
    )
    assert (
        sum(event["event_type"] == "STALE_MEMBER_ABORTED" for event in failed_fleet["events"]) == 1
    )
    assert all(failed_cleanup.values())
    assert retry.status is CampaignRunStatus.SUCCEEDED
    assert retry.analysis.all_required_behavior_oracles_passed
    assert all(retry_cleanup.values())
