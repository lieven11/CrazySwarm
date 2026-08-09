from __future__ import annotations

from pathlib import Path

import pytest

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.service import (
    CampaignRunMode,
    CampaignRunStatus,
    CampaignService,
)
from crazyswarm_app.campaign.timing import BoundedTimingTrace
from crazyswarm_app.config import load_config
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario


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
            "three_drone_multi_conflict",
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

    assert lock.case_id == "three_drone_multi_conflict"
    for review in (accelerated_review, realtime_review):
        assert review.status is CampaignRunStatus.SUCCEEDED
        assert review.analysis.telemetry_row_count > 5_000
        assert review.analysis.minimum_truth_separation_m is not None
        assert review.analysis.minimum_truth_separation_m >= 0.75
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
