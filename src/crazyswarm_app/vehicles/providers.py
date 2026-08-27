from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import BackendRole, VehicleIdentity
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    ExecutionBackend,
)
from crazyswarm_app.simulation.faults import FaultInjector
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import DynamicWorldTimeline, IndoorWorld, ScenarioConfig
from crazyswarm_app.vehicles.base import Vehicle
from crazyswarm_app.vehicles.mock_isaac import MockIsaacSimVehicle


@dataclass(frozen=True, slots=True)
class ProvisionedFleet:
    vehicles: tuple[Vehicle, ...]
    session_created_vehicle_ids: frozenset[str]


class BackendVehicleProvider(Protocol):
    def provision(
        self,
        deployment: DeploymentManifest,
        binding: BackendBindingProfile,
        *,
        existing: dict[str, Vehicle],
    ) -> ProvisionedFleet: ...


@dataclass(frozen=True, slots=True)
class SoftwareBackendVehicleProvider:
    """Session provider for Fast Sim and mock Isaac using one logical deployment."""

    scenario: ScenarioConfig
    dynamic_world_timeline: DynamicWorldTimeline | None = None

    def provision(
        self,
        deployment: DeploymentManifest,
        binding: BackendBindingProfile,
        *,
        existing: dict[str, Vehicle],
    ) -> ProvisionedFleet:
        binding.validate_for(deployment)
        expected_role = {
            ExecutionBackend.FAST_SIM: BackendRole.FAST_SIM,
            ExecutionBackend.MOCK_ISAAC: BackendRole.ISAAC_SIM,
        }.get(binding.backend)
        if expected_role is None:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                f"{binding.backend.value} requires an explicitly approved external provider",
            )
        world = IndoorWorld(
            self.scenario.world,
            dynamic_timeline=self.dynamic_world_timeline,
        )
        environment_sha = hashlib.sha256(
            json.dumps(
                {
                    "schema_version": self.scenario.schema_version,
                    "scenario_id": self.scenario.scenario_id,
                    "world": self.scenario.world.model_dump(mode="json"),
                    "simulation": self.scenario.simulation.model_dump(mode="json"),
                    "faults": [item.model_dump(mode="json") for item in self.scenario.faults],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        selected: list[Vehicle] = []
        created: set[str] = set()
        for member in deployment.fleet:
            current = existing.get(member.vehicle_id)
            if current is not None and current.backend_profile.role is expected_role:
                if isinstance(current, SimulatedVehicle):
                    current.world.dynamic_timeline = self.dynamic_world_timeline
                selected.append(current)
                continue
            if current is not None:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "logical identity is already owned by another backend role",
                    details={"vehicle_id": member.vehicle_id},
                )
            backend_identifier = binding.binding(member.vehicle_id).backend_identifier
            if binding.backend is ExecutionBackend.FAST_SIM:
                vehicle: Vehicle = SimulatedVehicle(
                    VehicleIdentity(
                        vehicle_id=member.vehicle_id,
                        display_name=member.display_name,
                        adapter="sim",
                    ),
                    world,
                    config=self.scenario.simulation,
                    initial_position_m=member.home,
                    faults=FaultInjector(self.scenario.faults, vehicle_id=member.vehicle_id),
                    scenario_id=self.scenario.scenario_id,
                    scenario_schema_version=str(self.scenario.schema_version),
                    scenario_configuration_sha256=environment_sha,
                )
            else:
                vehicle = MockIsaacSimVehicle(
                    member.vehicle_id,
                    display_name=member.display_name,
                    backend_identifier=backend_identifier,
                    initial_position_m=member.home,
                    scenario_id=self.scenario.scenario_id,
                    scenario_configuration_sha256=environment_sha,
                )
            selected.append(vehicle)
            created.add(member.vehicle_id)
        return ProvisionedFleet(
            vehicles=tuple(selected),
            session_created_vehicle_ids=frozenset(created),
        )
