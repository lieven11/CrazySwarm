from __future__ import annotations

import pytest

from crazyswarm_app.domain.models import Vector3, VehicleCapability
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    BackendVehicleBinding,
    CompletionPolicy,
    DeploymentManifest,
    DeploymentTaskDefinition,
    ExecutionBackend,
    FleetConstraints,
    FleetMemberDefinition,
    InitialFleetRole,
    ZoneDefinition,
    ZoneGeometry,
)


@pytest.fixture
def two_drone_deployment() -> DeploymentManifest:
    return DeploymentManifest(
        deployment_id="two-drone-foundation-v1",
        fleet=(
            FleetMemberDefinition(
                vehicle_id="cf01",
                display_name="Coverage One",
                home=Vector3(x=-1.0),
                initial_role=InitialFleetRole.ACTIVE,
                required_capabilities=frozenset({VehicleCapability.RELATIVE_POSITIONING}),
            ),
            FleetMemberDefinition(
                vehicle_id="cf02",
                display_name="Coverage Two",
                home=Vector3(x=1.0),
                initial_role=InitialFleetRole.ACTIVE,
                required_capabilities=frozenset({VehicleCapability.RELATIVE_POSITIONING}),
            ),
        ),
        zones=(
            ZoneDefinition(
                zone_id="zone-a",
                geometry=ZoneGeometry(
                    minimum_m=Vector3(x=-1.2, y=-0.2),
                    maximum_m=Vector3(x=-0.8, y=0.2, z=0.5),
                ),
            ),
            ZoneDefinition(
                zone_id="zone-b",
                geometry=ZoneGeometry(
                    minimum_m=Vector3(x=0.8, y=-0.2),
                    maximum_m=Vector3(x=1.2, y=0.2, z=0.5),
                ),
            ),
        ),
        tasks=(
            _task("inspect-a", "zone-a"),
            _task("inspect-b", "zone-b"),
        ),
        constraints=FleetConstraints(
            warning_separation_m=0.75,
            critical_separation_m=0.5,
            observation_freshness_s=2.0,
        ),
        completion_policy=CompletionPolicy(require_all_tasks=True),
    )


def binding_for(
    deployment: DeploymentManifest,
    backend: ExecutionBackend,
) -> BackendBindingProfile:
    return BackendBindingProfile(
        binding_id=f"{backend.value.lower()}-two-drone-v1",
        backend=backend,
        vehicles=tuple(
            BackendVehicleBinding(
                vehicle_id=member.vehicle_id,
                expected_vehicle_id=member.vehicle_id,
                backend_identifier=f"/World/Crazyflie/{member.vehicle_id}",
            )
            for member in deployment.fleet
        ),
    )


def _task(task_id: str, zone_id: str) -> DeploymentTaskDefinition:
    return DeploymentTaskDefinition(
        task_id=task_id,
        task_type="inspect-zone",
        zone_id=zone_id,
        priority=100,
        mission_id="hover",
        mission_parameters={
            "height_m": 0.2,
            "duration_s": 0.05,
            "takeoff_duration_s": 2.0,
            "landing_duration_s": 2.0,
        },
        required_capabilities=frozenset(
            {
                VehicleCapability.RELATIVE_POSITIONING,
                VehicleCapability.HIGH_LEVEL_COMMANDS,
            }
        ),
        estimated_duration_s=4.05,
        estimated_energy_percent=2.0,
        energy_margin_percent=10.0,
    )
