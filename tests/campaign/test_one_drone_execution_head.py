from pathlib import Path

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.execution_head import CampaignExecutionHead
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


def test_one_drone_execution_head_requires_sensor_source_and_auto_authority() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    event = WorldTruthEvent.create(
        event_id="rock",
        sequence=1,
        source_timestamp_s=2.0,
        effective_source_s=3.0,
        kind=WorldTruthEventKind.SOLID_APPEARED,
        solid_id="rock",
        obstacle=ObstacleConfig(
            obstacle_id="rock",
            minimum_m=Vector3(x=0.1, y=-0.1, z=0.1),
            maximum_m=Vector3(x=0.3, y=0.1, z=0.6),
        ),
    )
    source = SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline((), (event,)),
        config=PerceptionModelConfig(),
        mission_id="mission",
        run_id="run",
        vehicle_id="Alpha",
    )
    assert not CampaignExecutionHead(
        case=case,
        planning_submission=resolve_planning_submission(case, None),
    ).enabled
    assert CampaignExecutionHead(
        case=case,
        planning_submission=resolve_planning_submission(case, None),
        perception_source=source,
        mission_id="mission",
        run_id="run",
    ).enabled
