from pathlib import Path

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.planner import BoundedJointPlanner
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
    materialize_seeded_world_events,
)


def test_future_truth_cannot_change_initial_world_or_leak_before_latency() -> None:
    def event(x: float) -> WorldTruthEvent:
        return WorldTruthEvent.create(
            event_id=f"rock-{x}",
            sequence=1,
            source_timestamp_s=2.0,
            effective_source_s=3.0,
            kind=WorldTruthEventKind.SOLID_APPEARED,
            solid_id="rock",
            obstacle=ObstacleConfig(
                obstacle_id="rock",
                minimum_m=Vector3(x=x, y=-0.1, z=0.1),
                maximum_m=Vector3(x=x + 0.2, y=0.1, z=0.6),
            ),
        )

    first = DynamicWorldTimeline((), (event(0.1),))
    alternate = DynamicWorldTimeline((), (event(0.5),))
    assert first.initial_world_sha256 == alternate.initial_world_sha256
    released = []
    source = SimulatedPerceptionObservationSource(
        timeline=first,
        config=PerceptionModelConfig(latency_s=0.15),
        mission_id="mission",
        run_id="run",
        vehicle_id="Alpha",
        on_release=released.append,
    )
    assert source.pop_ready(2.149) is None
    assert released == []
    assert source.pop_ready(2.15) is not None
    assert len(released) == 1


def test_run_private_world_sequence_is_reproducible_but_not_preplanned() -> None:
    template = (
        WorldTruthEvent.create(
            event_id="wall-appears",
            sequence=1,
            source_timestamp_s=2.0,
            effective_source_s=5.0,
            kind=WorldTruthEventKind.SOLID_APPEARED,
            solid_id="wall",
            obstacle=ObstacleConfig(
                obstacle_id="wall",
                minimum_m=Vector3(x=-0.1, y=-0.2, z=0.1),
                maximum_m=Vector3(x=0.1, y=0.2, z=0.8),
            ),
        ),
        WorldTruthEvent.create(
            event_id="wall-disappears",
            sequence=2,
            source_timestamp_s=6.0,
            effective_source_s=6.0,
            kind=WorldTruthEventKind.SOLID_DISAPPEARED,
            solid_id="wall",
            obstacle=None,
        ),
    )
    bounds = {
        "volume_minimum_m": Vector3(x=-1.0, y=-1.0, z=0.0),
        "volume_maximum_m": Vector3(x=1.0, y=1.0, z=1.0),
    }
    first = materialize_seeded_world_events(template, seed_material="run-a", **bounds)
    repeat = materialize_seeded_world_events(template, seed_material="run-a", **bounds)
    alternate = materialize_seeded_world_events(template, seed_material="run-b", **bounds)

    assert first == repeat
    assert first != alternate
    assert first[0].obstacle != alternate[0].obstacle
    assert first[0].source_timestamp_s != alternate[0].source_timestamp_s
    assert first[1].kind is WorldTruthEventKind.SOLID_DISAPPEARED
    assert first[1].source_timestamp_s > first[0].source_timestamp_s


def test_future_obstacle_geometry_and_timing_cannot_change_initial_plan_identity() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    assert case.semantics is not None
    first_event = case.semantics.scenario_events[0]
    assert first_event.replacement_goal is not None
    shifted_region = first_event.replacement_goal.model_copy(
        update={
            "minimum_m": first_event.replacement_goal.minimum_m.model_copy(
                update={"x": first_event.replacement_goal.minimum_m.x + 0.6}
            ),
            "maximum_m": first_event.replacement_goal.maximum_m.model_copy(
                update={"x": first_event.replacement_goal.maximum_m.x + 0.6}
            ),
        }
    )
    alternate = case.model_copy(
        update={
            "semantics": case.semantics.model_copy(
                update={
                    "scenario_events": (
                        first_event.model_copy(
                            update={
                                "trigger_time_s": first_event.trigger_time_s + 0.7,
                                "replacement_goal": shifted_region,
                            }
                        ),
                        *case.semantics.scenario_events[1:],
                    )
                }
            )
        }
    )

    original_plan = BoundedJointPlanner().plan(case)
    alternate_plan = BoundedJointPlanner().plan(alternate)
    assert case.execution_semantics_sha256 != alternate.execution_semantics_sha256
    assert case.case_sha256 == alternate.case_sha256
    assert case.initial_planning_view().semantics.scenario_events == ()
    assert original_plan.plan_sha256 == alternate_plan.plan_sha256
