from pathlib import Path

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.simulation import MissionRunBinding, canonical_sha256
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    load_versioned_contract,
)
from crazyswarm_app.fleet.backends import software_backend_factory
from crazyswarm_app.fleet.qualification import run_persistent_fleet_qualification
from crazyswarm_app.vehicles.mock_isaac import MockIsaacSimVehicle

ROOT = Path(__file__).resolve().parents[2]


def test_persistent_fleet_qualification_is_equivalent_and_truthfully_bounded() -> None:
    first = run_persistent_fleet_qualification(ROOT)
    second = run_persistent_fleet_qualification(ROOT)
    assert first.decision == "PASS_SOFTWARE_ONLY"
    assert first.equivalent_normalized_intent
    assert first.equivalent_normalized_outcome
    assert first.live_isaac == "NOT_RUN"
    assert first.physical_flight == "NOT_RUN"
    assert first.cameras_depth_rtx_ros == "ABSENT"
    assert first.fallback == "FAST_SIM_AVAILABLE"
    assert len(first.fast_sim.scenario_outcomes) == 81
    assert all(item.invariant_passed for item in first.fast_sim.scenario_outcomes)
    assert first.normalized_report_sha256 == second.normalized_report_sha256


def test_three_mock_isaac_vehicles_have_unique_declared_namespaces() -> None:
    deployment = load_versioned_contract(
        ROOT / "config/fleet/three-drone-persistent-coverage-v1.yaml",
        DeploymentManifest,
    )
    binding = load_versioned_contract(
        ROOT / "config/fleet/mock-isaac-three-drone-binding-v1.yaml",
        BackendBindingProfile,
    )
    vehicles = software_backend_factory(deployment, binding).build(deployment, binding)
    mock = tuple(item for item in vehicles if isinstance(item, MockIsaacSimVehicle))
    assert [item.identity.vehicle_id for item in mock] == ["cf01", "cf02", "cf03"]
    assert [item.backend_namespace for item in mock] == [
        "/World/Crazyflie/cf01",
        "/World/Crazyflie/cf02",
        "/World/Crazyflie/cf03",
    ]
    assert len({item.backend_namespace for item in mock}) == 3


async def test_mock_isaac_rejects_cross_namespace_fleet_binding() -> None:
    vehicle = MockIsaacSimVehicle(vehicle_id="cf01", backend_identifier="/World/Crazyflie/cf01")
    metadata = vehicle.execution_metadata
    digest = canonical_sha256({"fixture": "namespace"})
    binding = MissionRunBinding(
        mission_run_id="namespace-run",
        mission_source_sha256=digest,
        run_identity_sha256=digest,
        model_id=str(metadata["physics_model_id"]),
        model_version=str(metadata["physics_model_version"]),
        model_configuration_sha256=str(metadata["physics_configuration_sha256"]),
        scenario_id=str(metadata["scenario_id"]),
        scenario_configuration_sha256=str(metadata["scenario_configuration_sha256"]),
        fleet_session_id="fleet-session",
        fleet_run_id="fleet-run",
        deployment_sha256=digest,
        task_id="cover-zone-a",
        task_lease_generation=1,
        backend_namespace="/World/Crazyflie/cf02",
        preparation_state="READY",
    )
    with pytest.raises(CrazySwarmError, match="namespace"):
        await vehicle.bind_run(binding)


def test_fleet_and_mission_layers_do_not_import_isaac_or_ros_types() -> None:
    for directory in (ROOT / "src/crazyswarm_app/fleet", ROOT / "src/crazyswarm_app/missions"):
        source = "\n".join(path.read_text(encoding="utf-8") for path in directory.glob("*.py"))
        assert "import isaac" not in source.lower()
        assert "from isaac" not in source.lower()
        assert "import rclpy" not in source.lower()
        assert "from rclpy" not in source.lower()
