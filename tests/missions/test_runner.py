from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, ClassVar

import pytest

from crazyswarm_app.domain.commands import (
    CommandEnvelope,
    DisarmCommand,
    FleetCommandBinding,
)
from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import VehicleCapability, VehicleIdentity, VehicleState
from crazyswarm_app.domain.simulation import FleetAuthorityTransition
from crazyswarm_app.missions.base import Mission, MissionContext
from crazyswarm_app.missions.catalog import HoverParameters
from crazyswarm_app.missions.models import MissionPhase, MissionStatus
from crazyswarm_app.missions.registry import MissionRegistry, default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig


@dataclass
class CommandCapture:
    commands: list[CommandEnvelope] = field(default_factory=list)

    def command_sent(self, command: CommandEnvelope) -> None:
        self.commands.append(command)

    def __getattr__(self, name: str) -> Any:
        del name
        return lambda value: None


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


class ArmedReadyMission(Mission[HoverParameters]):
    mission_id = "armed-ready"
    name = "Armed ready"
    description = "Wait while armed so cleanup owns the disarm command"
    parameters_type = HoverParameters
    manages_flight_path = True

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, context: MissionContext, parameters: HoverParameters) -> None:
        del context, parameters
        self.started.set()
        await self.release.wait()


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
    first_cancel = await runner.cancel(run_id)
    second_cancel = await runner.cancel(run_id)
    result = await task
    assert first_cancel.cancellation_requested is True
    assert second_cancel.cancellation_requested is True
    assert result.status is MissionStatus.ABORTED
    assert result.reason_code == "MISSION_CANCELLED"
    assert supervisor.session(vehicle.identity.vehicle_id).lease is None
    assert not (await vehicle.snapshot()).telemetry.flying


@pytest.mark.asyncio
async def test_cleanup_disarm_uses_the_serialized_transferred_binding() -> None:
    mission = ArmedReadyMission()
    registry = MissionRegistry()
    registry.register(mission)
    runner, supervisor, vehicle = make_runtime(registry=registry)
    capture = CommandCapture()
    supervisor.add_audit_sink(capture)
    run_id = "run-cleanup-transition"
    initial = FleetCommandBinding(
        fleet_session_id="fleet-session-cleanup",
        fleet_run_id="fleet-run-cleanup",
        deployment_sha256="1" * 64,
        task_id="active-task",
        task_lease_generation=1,
        backend_namespace="fast-sim/sim01",
    )
    task = asyncio.create_task(
        runner.run(
            mission.mission_id,
            vehicle.identity.vehicle_id,
            mission_run_id=run_id,
            fleet_binding=initial,
        )
    )
    await asyncio.wait_for(mission.started.wait(), timeout=1.0)
    receipt = await runner.transition_fleet_authority(
        run_id,
        FleetAuthorityTransition(
            transition_id="cleanup-transition",
            sequence=1,
            vehicle_id=vehicle.identity.vehicle_id,
            mission_run_id=run_id,
            fleet_session_id=initial.fleet_session_id,
            fleet_run_id=initial.fleet_run_id,
            deployment_sha256=initial.deployment_sha256,
            expected_task_id=initial.task_id,
            expected_task_lease_generation=initial.task_lease_generation,
            next_task_id="return-task",
            next_task_lease_generation=2,
            reason_code="TEST_CLEANUP_AUTHORITY",
            authorization_sha256="2" * 64,
        ),
    )
    mission.release.set()
    result = await task
    assert result.status is MissionStatus.SUCCEEDED
    assert result.fleet_authority_transitions == (receipt,)
    cleanup = next(item for item in capture.commands if isinstance(item.payload, DisarmCommand))
    assert cleanup.mission_run_id == run_id
    assert cleanup.fleet is not None
    assert cleanup.fleet.task_id == "return-task"
    assert cleanup.fleet.task_lease_generation == 2


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
