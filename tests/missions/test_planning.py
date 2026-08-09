from __future__ import annotations

import pytest

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.fleet.artifacts import ExecutionBackend
from crazyswarm_app.fleet.planning import MissionDeploymentPlan, plan_mission_deployment
from crazyswarm_app.missions.planning import (
    MissionPlanStatus,
    PlanningObstacle,
    build_mission_plan,
)
from crazyswarm_app.missions.script import MissionFileRecord, parse_python_mission
from crazyswarm_app.safety.policy import SafetyPolicy

TWO_ROLE_SOURCE = """\
MISSION = {
    "schema_version": 2,
    "roles": {
        "left": {
            "logical_vehicle_id": "drone-left",
            "home_m": [-0.8, 0.0, 0.0],
        },
        "right": {
            "logical_vehicle_id": "drone-right",
            "home_m": [0.8, 0.0, 0.0],
        },
    },
}

async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    if drone.role == "left":
        await drone.move_relative(x_m=-0.1, duration_s=1.0, frame="home")
    else:
        await drone.move_relative(y_m=0.1, duration_s=1.0, frame="home")
    await drone.land(duration_s=2.0)
"""


def _deployment(
    source: str,
    *,
    backend: ExecutionBackend = ExecutionBackend.FAST_SIM,
) -> tuple[MissionFileRecord, MissionDeploymentPlan]:
    record = parse_python_mission(filename="planned.py", name="Planned mission", source=source)
    return record, plan_mission_deployment(
        record,
        backend=backend,
        required_capabilities=frozenset(),
        implicit_vehicle_id="sim01",
        implicit_display_name="Simulation vehicle",
        implicit_home=Vector3(),
        world_minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
        world_maximum_m=Vector3(x=2.0, y=2.0, z=1.0),
    )


@pytest.mark.asyncio
async def test_plan_receipt_is_deterministic_and_backend_neutral() -> None:
    fast_record, fast = _deployment(TWO_ROLE_SOURCE)

    fast_plan = await build_mission_plan(
        fast_record,
        fast.deployment,
        fast.assignments,
        SafetyPolicy(),
    )
    other_plan = await build_mission_plan(
        fast_record,
        fast.deployment,
        fast.assignments,
        SafetyPolicy(),
    )

    assert fast_plan.status is MissionPlanStatus.APPROVED
    assert fast_plan.plan_id == other_plan.plan_id
    assert fast_plan.sha256 == other_plan.sha256
    assert "backend" not in fast_plan.model_dump(mode="json")
    assert [item.role_id for item in fast_plan.roles] == ["left", "right"]
    assert [item.preview_fidelity for item in fast_plan.roles] == [
        "EXACT_ROLE",
        "EXACT_ROLE",
    ]
    assert [len(item.waypoints) for item in fast_plan.roles] == [3, 3]


@pytest.mark.asyncio
async def test_plan_blocks_target_outside_safety_volume() -> None:
    source = TWO_ROLE_SOURCE.replace(
        "x_m=-0.1, duration_s=1.0",
        "x_m=-3.0, duration_s=10.0",
    )
    record, deployment = _deployment(source)

    plan = await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        SafetyPolicy(),
    )

    assert plan.status is MissionPlanStatus.BLOCKED
    assert "TARGET_OUTSIDE_FLIGHT_VOLUME" in {item.code for item in plan.findings}


@pytest.mark.asyncio
async def test_plan_blocks_route_through_known_obstacle() -> None:
    record, deployment = _deployment(TWO_ROLE_SOURCE)
    obstacle = PlanningObstacle(
        obstacle_id="left-route-box",
        minimum_m=Vector3(x=-0.87, y=-0.05, z=0.2),
        maximum_m=Vector3(x=-0.83, y=0.05, z=0.4),
    )

    plan = await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        SafetyPolicy(),
        obstacles=(obstacle,),
    )

    assert plan.status is MissionPlanStatus.BLOCKED
    finding = next(item for item in plan.findings if item.code == "ROUTE_INTERSECTS_OBSTACLE")
    assert finding.role_id == "left"
    assert finding.details["obstacle_id"] == "left-route-box"


@pytest.mark.asyncio
async def test_low_task_battery_requires_explicit_confirmation() -> None:
    record, deployment = _deployment(TWO_ROLE_SOURCE)

    plan = await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        SafetyPolicy(),
        observed_batteries={"drone-left": 5.0, "drone-right": 100.0},
    )

    assert plan.status is MissionPlanStatus.REQUIRES_CONFIRMATION
    finding = next(
        item for item in plan.findings if item.code == "BATTERY_BELOW_PLANNED_REQUIREMENT"
    )
    assert finding.role_id == "left"
    assert finding.requires_confirmation is True
    assert "BATTERY_BELOW_TAKEOFF_MINIMUM" in {item.code for item in plan.findings}


@pytest.mark.asyncio
async def test_missing_planning_observations_are_explicitly_deferred_to_preflight() -> None:
    record, deployment = _deployment(TWO_ROLE_SOURCE)

    plan = await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        SafetyPolicy(),
        existing_vehicle_ids=frozenset({"drone-left"}),
    )

    assert plan.status is MissionPlanStatus.APPROVED
    codes = {item.code for item in plan.findings}
    assert "START_POSITION_UNAVAILABLE" in codes
    assert "BATTERY_OBSERVATION_UNAVAILABLE" in codes
    assert all(item.details["preflight_observation_required"] is True for item in plan.findings)
