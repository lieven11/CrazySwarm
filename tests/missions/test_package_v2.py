from __future__ import annotations

from pathlib import Path

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    BackendVehicleBinding,
    ExecutionBackend,
)
from crazyswarm_app.fleet.planning import plan_mission_deployment
from crazyswarm_app.missions.script import parse_python_mission

ROOT = Path(__file__).resolve().parents[2]

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

THREE_ROLE_RESERVE_SOURCE = TWO_ROLE_SOURCE.replace(
    '        "right": {',
    '        "reserve": {\n'
    '            "logical_vehicle_id": "drone-reserve",\n'
    '            "home_m": [0.0, 1.2, 0.0],\n'
    '            "initial_role": "RESERVE",\n'
    "        },\n"
    '        "right": {',
)


def test_v2_roles_are_static_backend_neutral_and_deterministic() -> None:
    record = parse_python_mission(
        filename="two_roles.py",
        name="Two roles",
        source=TWO_ROLE_SOURCE,
    )
    assert record.package_schema_version == 2
    assert [(item.role_id, item.logical_vehicle_id) for item in record.roles] == [
        ("left", "drone-left"),
        ("right", "drone-right"),
    ]
    world_minimum_m = Vector3(x=-2.0, y=-2.0, z=0.0)
    world_maximum_m = Vector3(x=2.0, y=2.0, z=1.0)
    fast = plan_mission_deployment(
        record,
        backend=ExecutionBackend.FAST_SIM,
        required_capabilities=frozenset(),
        implicit_vehicle_id="unused",
        implicit_display_name="Unused",
        implicit_home=Vector3(),
        world_minimum_m=world_minimum_m,
        world_maximum_m=world_maximum_m,
    )
    isaac = plan_mission_deployment(
        record,
        backend=ExecutionBackend.MOCK_ISAAC,
        required_capabilities=frozenset(),
        implicit_vehicle_id="unused",
        implicit_display_name="Unused",
        implicit_home=Vector3(),
        world_minimum_m=world_minimum_m,
        world_maximum_m=world_maximum_m,
    )
    assert fast.deployment.sha256 == isaac.deployment.sha256
    assert (
        fast.assignments
        == isaac.assignments
        == {
            "left": "drone-left",
            "right": "drone-right",
        }
    )
    assert fast.binding.sha256 != isaac.binding.sha256

    physical_binding = BackendBindingProfile(
        binding_id="operator-approved-fake-real",
        backend=ExecutionBackend.CRAZYFLIE,
        vehicles=tuple(
            BackendVehicleBinding(
                vehicle_id=vehicle_id,
                expected_vehicle_id=vehicle_id,
                backend_identifier=f"radio://approved/{vehicle_id}",
                operator_selected=True,
            )
            for vehicle_id in ("drone-left", "drone-right")
        ),
    )
    physical = plan_mission_deployment(
        record,
        backend=ExecutionBackend.CRAZYFLIE,
        approved_binding_profile=physical_binding,
        required_capabilities=frozenset(),
        implicit_vehicle_id="unused",
        implicit_display_name="Unused",
        implicit_home=Vector3(),
        world_minimum_m=world_minimum_m,
        world_maximum_m=world_maximum_m,
    )
    assert physical.deployment.sha256 == fast.deployment.sha256
    assert physical.binding is physical_binding


def test_persistent_coverage_artifact_is_backend_neutral_and_reserve_aware() -> None:
    path = ROOT / "missions/qualification/persistent_coverage_rotation.py"
    record = parse_python_mission(
        filename=path.name,
        name="Persistent coverage rotation",
        source=path.read_text(encoding="utf-8"),
    )

    assert record.package_schema_version == 2
    assert [item.role_id for item in record.roles] == ["reserve", "zone_a", "zone_b"]
    reserve = next(item for item in record.roles if item.role_id == "reserve")
    assert reserve.initial_role == "RESERVE"
    active = [item for item in record.roles if item.initial_role == "ACTIVE"]
    assert {item.task.task_type for item in active} == {"persistent-zone-coverage"}
    assert all(item.zone is not None for item in active)

    source = record.source.lower()
    for forbidden in ("fast_sim", "isaac", "radio://", "fault", "seed"):
        assert forbidden not in source


def test_wp10_coordination_artifacts_are_backend_neutral_and_role_explicit() -> None:
    expectations = {
        "crossing_route_separation.py": {
            "cross_west": "crossing-route",
            "cross_south": "crossing-route",
        },
        "leader_follower_recovery.py": {
            "leader": "leader-route",
            "follower": "follower-route",
        },
    }
    for filename, expected_tasks in expectations.items():
        path = ROOT / "missions" / "qualification" / filename
        record = parse_python_mission(
            filename=filename,
            name=filename,
            source=path.read_text(encoding="utf-8"),
        )

        assert record.package_schema_version == 2
        assert {item.role_id: item.task.task_type for item in record.roles} == (expected_tasks)
        assert all(item.initial_role == "ACTIVE" for item in record.roles)
        source = record.source.lower()
        for forbidden in ("fast_sim", "isaac", "radio://", "fault", "seed"):
            assert forbidden not in source
