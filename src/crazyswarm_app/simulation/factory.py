from __future__ import annotations

from pathlib import Path

from crazyswarm_app.domain.models import VehicleIdentity
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.simulation.faults import FaultInjector
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, ScenarioConfig, load_scenario


def vehicles_from_scenario(
    scenario: ScenarioConfig | Path,
) -> tuple[SimulatedVehicle, ...]:
    selected = load_scenario(scenario) if isinstance(scenario, Path) else scenario
    world = IndoorWorld(selected.world)
    scenario_configuration_sha256 = canonical_sha256(selected)
    return tuple(
        SimulatedVehicle(
            VehicleIdentity(
                vehicle_id=spawn.vehicle_id,
                display_name=spawn.display_name,
                adapter="sim",
            ),
            world,
            config=selected.simulation,
            initial_position_m=spawn.position_m,
            initial_yaw_rad=spawn.yaw_rad,
            faults=FaultInjector(selected.faults, vehicle_id=spawn.vehicle_id),
            scenario_id=selected.scenario_id,
            scenario_schema_version=str(selected.schema_version),
            scenario_configuration_sha256=scenario_configuration_sha256,
        )
        for spawn in selected.vehicles
    )
