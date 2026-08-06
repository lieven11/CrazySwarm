from __future__ import annotations

from pathlib import Path

import pytest

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.simulation.world import IndoorWorld, ObstacleConfig, WorldConfig, load_scenario


def test_room_and_obstacle_ray_intersection() -> None:
    world = IndoorWorld(
        WorldConfig(
            width_m=4.0,
            depth_m=4.0,
            height_m=2.0,
            obstacles=(
                ObstacleConfig(
                    obstacle_id="box",
                    minimum_m=Vector3(x=0.5, y=-0.2, z=0.0),
                    maximum_m=Vector3(x=1.0, y=0.2, z=1.0),
                ),
            ),
        )
    )
    origin = Vector3(x=0.0, y=0.0, z=0.3)
    assert world.ray_distance(origin, Vector3(x=1.0), 4.0) == pytest.approx(0.5)
    assert world.ray_distance(origin, Vector3(y=1.0), 4.0) == pytest.approx(2.0)
    assert world.ray_distance(origin, Vector3(z=-1.0), 4.0) == pytest.approx(0.3)
    assert not world.contains(Vector3(x=0.75, y=0.0, z=0.3))


def test_example_worlds_load() -> None:
    one = load_scenario(Path("config/worlds/one_drone.yaml"))
    three = load_scenario(Path("config/worlds/three_drone.yaml"))
    assert len(one.vehicles) == 1
    assert len(three.vehicles) == 3


def test_failure_scenarios_load() -> None:
    low_battery = load_scenario(Path("config/scenarios/low_battery.yaml"))
    link_loss = load_scenario(Path("config/scenarios/link_loss.yaml"))
    assert low_battery.simulation.battery_start_percent == 11.0
    assert len(link_loss.faults) == 1
