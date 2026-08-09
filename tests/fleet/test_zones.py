from pathlib import Path

from crazyswarm_app.domain.models import Vector3, VehicleCapability
from crazyswarm_app.fleet.artifacts import DeploymentTaskDefinition, ZoneDefinition, ZoneGeometry
from crazyswarm_app.fleet.zones import ZoneObstacle, ZoneTaskPlanner
from crazyswarm_app.simulation.world import load_scenario

ROOT = Path(__file__).resolve().parents[2]


def task() -> DeploymentTaskDefinition:
    return DeploymentTaskDefinition(
        task_id="inspect-zone-b",
        task_type="inspect-zone",
        zone_id="zone-b",
        priority=100,
        mission_id="hover",
        required_capabilities=frozenset(
            {VehicleCapability.RELATIVE_POSITIONING, VehicleCapability.HIGH_LEVEL_COMMANDS}
        ),
        estimated_duration_s=20.0,
        estimated_energy_percent=5.0,
    )


def zone() -> ZoneDefinition:
    return ZoneDefinition(
        zone_id="zone-b",
        geometry=ZoneGeometry(
            minimum_m=Vector3(x=1.0, y=-0.1, z=0.2),
            maximum_m=Vector3(x=1.4, y=0.1, z=0.4),
        ),
    )


def test_nominal_zone_task_decomposes_to_backend_neutral_actions() -> None:
    plan = ZoneTaskPlanner().plan(task(), zone(), start_m=Vector3(x=-1.2))
    assert not plan.obstacle_aware
    assert [item.kind.value for item in plan.actions] == [
        "TAKEOFF",
        "MOVE_TO",
        "HOLD",
        "LAND",
    ]
    assert plan.waypoints_m[-1] == zone().geometry.center_m
    assert plan.estimated_energy_percent > task().estimated_energy_percent


def test_obstacle_scenario_adds_deterministic_clearance_waypoints() -> None:
    scenario = load_scenario(ROOT / "config/worlds/two_zone_obstacle.yaml")
    obstacle_config = scenario.world.obstacles[0]
    obstacle = ZoneObstacle(
        obstacle_id=obstacle_config.obstacle_id,
        minimum_m=obstacle_config.minimum_m,
        maximum_m=obstacle_config.maximum_m,
    )
    planner = ZoneTaskPlanner(safety_margin_m=0.2)
    first = planner.plan(
        task(),
        zone(),
        start_m=scenario.vehicles[0].position_m,
        obstacles=(obstacle,),
    )
    second = planner.plan(
        task(),
        zone(),
        start_m=scenario.vehicles[0].position_m,
        obstacles=(obstacle,),
    )
    assert first.obstacle_aware
    assert len(first.waypoints_m) == 4
    assert first.waypoints_m[1].y == -0.4
    assert first.plan_sha256 == second.plan_sha256
