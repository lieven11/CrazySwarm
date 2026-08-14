from __future__ import annotations

import json
from pathlib import Path

import pytest

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.service import (
    CampaignRunMode,
    CampaignRunStatus,
    CampaignService,
    ReviewDecision,
)
from crazyswarm_app.config import load_config
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario


@pytest.mark.asyncio
async def test_sensor_sourced_one_drone_reality_mission_replans_and_lands(
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
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="wp59-one-drone-reality-e2e",
        )
    finally:
        await runtime.stop()

    assert review.status is CampaignRunStatus.SUCCEEDED
    assert review.analysis.all_required_behavior_oracles_passed
    evidence = tmp_path / "campaign" / "evidence" / review.analysis.mission_execution_id
    bundle = json.loads((evidence / "execution-bundle.json").read_text(encoding="utf-8"))
    context = bundle["context"]
    trace = context["campaign_execution_head_trace"]
    assert trace["enabled"] is True
    persisted = [item for item in trace["records"] if item.get("stage") == "PERCEPTION_PERSISTED"]
    dispatched = [
        item for item in trace["records"] if item.get("execution_disposition") == "DISPATCHED"
    ]
    assert len(persisted) >= 3
    assert len(dispatched) >= 2
    assert all(
        item["received_timestamp_s"] >= item["source_timestamp_s"] and item["raw_payload_sha256"]
        for item in persisted
    )
    assert all(item["safe_prefix_certificate"]["passed"] for item in dispatched)
    assert all(item["replacement_world_sha256"] for item in dispatched)
    # Initial accepted planning evidence is case-derived and contains no authored
    # future obstacle solid; geometry appears only after persisted observations.
    assert context["campaign_plan"]["case_sha256"] == context["campaign_case_sha256"]
    assert all(
        "sensed-rock" not in json.dumps(item)
        for item in context["campaign_plan"]["retained_candidates"]
    )
