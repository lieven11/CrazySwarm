from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import VehicleCapability, VehicleIdentity, VehicleState
from crazyswarm_app.missions.base import Mission, MissionContext
from crazyswarm_app.missions.catalog import HoverParameters
from crazyswarm_app.missions.models import MissionPhase, MissionStatus
from crazyswarm_app.missions.registry import MissionRegistry, default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig


def make_runtime(
    *, registry: MissionRegistry | None = None, realtime: bool = False
) -> tuple[MissionRunner, SafetySupervisor, SimulatedVehicle]:
    config = (
        SimulationConfig(clock_mode="realtime", speed=100.0, fixed_step_s=0.05)
        if realtime
        else SimulationConfig()
    )
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Sim 01", adapter="sim"),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=1.0)),
        config=config,
    )
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    return MissionRunner(supervisor, registry or default_registry()), supervisor, vehicle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mission_id", "parameters"),
    [
        ("hover", {"duration_s": 0.1}),
        ("move-return", {"x_m": 0.2, "move_duration_s": 1.5, "dwell_s": 0.0}),
        ("square", {"side_m": 0.2, "leg_duration_s": 1.5, "dwell_s": 0.0}),
    ],
)
async def test_every_catalog_mission_runs_against_simulated_vehicle(
    mission_id: str,
    parameters: dict[str, float],
) -> None:
    runner, supervisor, vehicle = make_runtime()
    result = await runner.run(mission_id, vehicle.identity.vehicle_id, parameters=parameters)
    assert result.status is MissionStatus.SUCCEEDED
    assert len(result.configuration_hash) == 64
    assert result.mission_version == "1.0.0"
    assert result.events[-1].phase is MissionPhase.COMPLETE
    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.DISCONNECTED


@pytest.mark.asyncio
async def test_invalid_parameters_fail_before_connection_or_preflight() -> None:
    runner, supervisor, vehicle = make_runtime()
    result = await runner.run("hover", vehicle.identity.vehicle_id, parameters={"height_m": 4.0})
    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "INVALID_COMMAND"
    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.DISCONNECTED
    assert not any(event.event_type == "PREFLIGHT_COMPLETED" for event in supervisor.events)


class GlobalMission(Mission[HoverParameters]):
    mission_id = "global"
    name = "Global"
    description = "Requires global positioning"
    parameters_type = HoverParameters
    required_capabilities = frozenset({VehicleCapability.GLOBAL_POSITIONING})

    async def execute(self, context: MissionContext, parameters: HoverParameters) -> None:
        await context.hover(parameters.duration_s)


@pytest.mark.asyncio
async def test_missing_capability_fails_preflight_before_arm() -> None:
    registry = MissionRegistry()
    registry.register(GlobalMission())
    runner, supervisor, vehicle = make_runtime(registry=registry)
    result = await runner.run("global", vehicle.identity.vehicle_id)
    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "PREFLIGHT_FAILED"
    assert not any(event.to_state is VehicleState.ARMING for event in supervisor.events)


class ExplodingMission(Mission[HoverParameters]):
    mission_id = "explode"
    name = "Explode"
    description = "Test mission that raises while airborne"
    parameters_type = HoverParameters
    required_capabilities = frozenset({VehicleCapability.RELATIVE_POSITIONING})

    async def execute(self, context: MissionContext, parameters: HoverParameters) -> None:
        raise RuntimeError("injected failure")


@pytest.mark.asyncio
async def test_mission_exception_causes_abort_and_land() -> None:
    registry = MissionRegistry()
    registry.register(ExplodingMission())
    runner, supervisor, vehicle = make_runtime(registry=registry)
    result = await runner.run("explode", vehicle.identity.vehicle_id)
    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "MISSION_EXCEPTION"
    assert any("ABORT" in fault for fault in (await vehicle.snapshot()).telemetry.faults)
    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.DISCONNECTED


class BlockingMission(Mission[HoverParameters]):
    mission_id = "blocking"
    name = "Blocking"
    description = "Test mission with a cancellation point"
    parameters_type = HoverParameters
    required_capabilities = frozenset({VehicleCapability.RELATIVE_POSITIONING})
    presets: ClassVar[dict[str, dict[str, float]]] = {
        "fast": {"height_m": 0.1, "takeoff_duration_s": 1.0}
    }

    async def execute(self, context: MissionContext, parameters: HoverParameters) -> None:
        await asyncio.sleep(30.0)


async def wait_for_phase(runner: MissionRunner, run_id: str, phase: MissionPhase) -> None:
    for _ in range(200):
        try:
            if runner.get_run(run_id).phase is phase:
                return
        except CrazySwarmError:
            pass
        await asyncio.sleep(0.005)
    raise AssertionError(f"mission did not reach {phase}")


@pytest.mark.asyncio
async def test_cancellation_aborts_lands_and_releases_ownership() -> None:
    registry = MissionRegistry()
    registry.register(BlockingMission())
    runner, supervisor, vehicle = make_runtime(registry=registry, realtime=True)
    run_id = "run-cancel"
    task = asyncio.create_task(
        runner.run("blocking", vehicle.identity.vehicle_id, preset="fast", mission_run_id=run_id)
    )
    await wait_for_phase(runner, run_id, MissionPhase.EXECUTING)
    await runner.cancel(run_id)
    result = await task
    assert result.status is MissionStatus.ABORTED
    assert result.reason_code == "MISSION_CANCELLED"
    assert supervisor.session(vehicle.identity.vehicle_id).lease is None
    assert not (await vehicle.snapshot()).telemetry.flying


@pytest.mark.asyncio
async def test_concurrent_mission_ownership_is_rejected() -> None:
    registry = MissionRegistry()
    registry.register(BlockingMission())
    runner, _, vehicle = make_runtime(registry=registry, realtime=True)
    first_id = "run-first"
    first = asyncio.create_task(
        runner.run("blocking", vehicle.identity.vehicle_id, preset="fast", mission_run_id=first_id)
    )
    await wait_for_phase(runner, first_id, MissionPhase.EXECUTING)
    second = await runner.run(
        "blocking", vehicle.identity.vehicle_id, preset="fast", mission_run_id="run-second"
    )
    assert second.status is MissionStatus.FAILED
    assert second.reason_code == "MISSION_CONFLICT"
    await runner.cancel(first_id)
    await first
