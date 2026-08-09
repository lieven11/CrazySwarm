from __future__ import annotations

from collections.abc import Callable

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import VehicleIdentity
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    ExecutionBackend,
    FleetMemberDefinition,
)
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig
from crazyswarm_app.vehicles.base import Vehicle
from crazyswarm_app.vehicles.mock_isaac import MockIsaacSimVehicle

VehicleBuilder = Callable[[FleetMemberDefinition, str], Vehicle]


class BackendVehicleFactory:
    """The only fleet component that knows how binding profiles create adapters."""

    def __init__(self) -> None:
        self._builders: dict[ExecutionBackend, VehicleBuilder] = {}

    def register(self, backend: ExecutionBackend, builder: VehicleBuilder) -> None:
        self._builders[backend] = builder

    def build(
        self,
        deployment: DeploymentManifest,
        binding: BackendBindingProfile,
    ) -> tuple[Vehicle, ...]:
        binding.validate_for(deployment)
        try:
            builder = self._builders[binding.backend]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                f"backend requires an explicit external discovery/factory: {binding.backend.value}",
            ) from error
        vehicles: list[Vehicle] = []
        for member in deployment.fleet:
            try:
                selected = binding.binding(member.vehicle_id)
            except CrazySwarmError:
                if member.required:
                    raise
                continue
            vehicles.append(builder(member, selected.backend_identifier))
        return tuple(vehicles)


def software_backend_factory(
    deployment: DeploymentManifest,
    binding: BackendBindingProfile,
) -> BackendVehicleFactory:
    """Create the local Fast Sim/mock-Isaac builders for a deployment."""

    width = float(binding.backend_options.get("world_width_m", 8.0))
    depth = float(binding.backend_options.get("world_depth_m", 6.0))
    height = float(binding.backend_options.get("world_height_m", 3.0))
    seed = int(binding.backend_options.get("seed", 109))
    fixed_step_s = float(binding.backend_options.get("fixed_step_s", 0.01))
    world = IndoorWorld(
        WorldConfig(
            world_id=f"{deployment.deployment_id}-world",
            width_m=width,
            depth_m=depth,
            height_m=height,
        )
    )
    configuration = SimulationConfig(seed=seed, fixed_step_s=fixed_step_s)
    factory = BackendVehicleFactory()

    def fast_sim(member: FleetMemberDefinition, backend_identifier: str) -> Vehicle:
        del backend_identifier
        return SimulatedVehicle(
            VehicleIdentity(
                vehicle_id=member.vehicle_id,
                display_name=member.display_name,
                adapter="fast-sim",
            ),
            world,
            config=configuration,
            initial_position_m=member.home,
            scenario_id=deployment.deployment_id,
            scenario_schema_version=str(deployment.schema_version),
            scenario_configuration_sha256=deployment.sha256,
        )

    def mock_isaac(member: FleetMemberDefinition, backend_identifier: str) -> Vehicle:
        return MockIsaacSimVehicle(
            member.vehicle_id,
            display_name=member.display_name,
            backend_identifier=backend_identifier,
            initial_position_m=member.home,
            scenario_id=deployment.deployment_id,
            scenario_configuration_sha256=deployment.sha256,
        )

    factory.register(ExecutionBackend.FAST_SIM, fast_sim)
    factory.register(ExecutionBackend.MOCK_ISAAC, mock_isaac)
    return factory
