import inspect
from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.execution_head import CampaignExecutionHead
from crazyswarm_app.campaign.perception import PerceivedWorldState, PerceptionObservation
from crazyswarm_app.campaign.replanning import (
    InFlightReplanCoordinator,
    commit_changed_world_replacement,
)
from crazyswarm_app.campaign.submissions import resolve_planning_submission
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.simulation.sensors import (
    PerceptionModelConfig,
    SimulatedPerceptionObservationSource,
)
from crazyswarm_app.simulation.world import (
    DynamicWorldTimeline,
    ObstacleConfig,
    WorldTruthEvent,
    WorldTruthEventKind,
)


def _event(*, x: float = 0.0) -> WorldTruthEvent:
    return WorldTruthEvent.create(
        event_id="future-rock",
        sequence=1,
        source_timestamp_s=2.0,
        effective_source_s=5.0,
        kind=WorldTruthEventKind.SOLID_APPEARED,
        solid_id="rock",
        obstacle=ObstacleConfig(
            obstacle_id="rock",
            minimum_m=Vector3(x=x - 0.1, y=-0.1, z=0.1),
            maximum_m=Vector3(x=x + 0.1, y=0.1, z=0.7),
        ),
    )


def test_future_world_truth_is_absent_from_initial_plan_identity() -> None:
    first = DynamicWorldTimeline((), (_event(x=0.0),))
    alternate = DynamicWorldTimeline((), (_event(x=0.4),))
    assert first.initial_world_sha256 == alternate.initial_world_sha256
    assert first.events[0].truth_sha256 != alternate.events[0].truth_sha256


def test_sensor_adapter_emits_delayed_hash_bound_observation() -> None:
    source = SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline((), (_event(),)),
        config=PerceptionModelConfig(latency_s=0.12),
        mission_id="mission",
        run_id="run",
        vehicle_id="Alpha",
    )
    assert source.pop_ready(2.11) is None
    observation = source.pop_ready(2.12)
    assert observation is not None
    assert observation.received_timestamp_s - observation.source_timestamp_s == pytest.approx(
        0.12
    )
    state = PerceivedWorldState.empty().apply(observation)
    assert state.revision == 1
    assert "rock" in state.solids

    payload = observation.model_dump(mode="python")
    payload["world_revision"] = 9
    with pytest.raises(ValueError, match="hash mismatch"):
        PerceptionObservation.model_validate(payload)


def test_production_head_enables_one_drone_only_with_sensor_source() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    source = SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline((), (_event(),)),
        config=PerceptionModelConfig(),
        mission_id="mission",
        run_id="run",
        vehicle_id="Alpha",
    )
    head = CampaignExecutionHead(
        case=case,
        planning_submission=resolve_planning_submission(case, None),
        perception_source=source,
        mission_id="mission",
        run_id="run",
    )
    assert head.enabled
    InFlightReplanCoordinator(case)
    assert "old_epoch_still_safe" not in inspect.signature(
        commit_changed_world_replacement
    ).parameters
