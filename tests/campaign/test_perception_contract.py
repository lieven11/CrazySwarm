import pytest

from crazyswarm_app.campaign.perception import PerceivedWorldState, PerceptionObservation
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


def _observation() -> PerceptionObservation:
    event = WorldTruthEvent.create(
        event_id="rock-appears",
        sequence=1,
        source_timestamp_s=1.0,
        effective_source_s=2.0,
        kind=WorldTruthEventKind.SOLID_APPEARED,
        solid_id="rock",
        obstacle=ObstacleConfig(
            obstacle_id="rock",
            minimum_m=Vector3(x=0.2, y=-0.1, z=0.1),
            maximum_m=Vector3(x=0.4, y=0.1, z=0.6),
        ),
    )
    source = SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline((), (event,)),
        config=PerceptionModelConfig(latency_s=0.12),
        mission_id="mission",
        run_id="run",
        vehicle_id="Alpha",
    )
    observation = source.pop_ready(1.12)
    assert observation is not None
    return observation


def test_perception_is_hash_bound_and_revision_ordered() -> None:
    observation = _observation()
    state = PerceivedWorldState.empty().apply(observation)
    assert state.revision == 1
    assert state.solids["rock"].center_m.x == pytest.approx(0.3)
    tampered = observation.model_dump(mode="python")
    tampered["confidence"] = 0.1
    with pytest.raises(ValueError, match="hash mismatch"):
        PerceptionObservation.model_validate(tampered)
