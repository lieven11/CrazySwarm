from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from crazyswarm_app.domain.commands import CommandEnvelope
from crazyswarm_app.domain.models import (
    AuthorityClass,
    BackendRole,
    CommandCompletionMode,
    OperatingMode,
    SourceClockPolicy,
    Vector3,
    VehicleBackendProfile,
    VehicleIdentity,
)
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    BackendVehicleBinding,
    DeploymentManifest,
    ExecutionBackend,
    FleetSessionIdentity,
    MissionArtifact,
)
from crazyswarm_app.fleet.backends import software_backend_factory
from crazyswarm_app.fleet.coordinator import FleetCoordinator, FleetResult, FleetStatus
from crazyswarm_app.fleet.preparation import (
    ConnectionState,
    FleetPreparation,
    ObservationState,
    RegistrationState,
)
from crazyswarm_app.missions.registry import default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.safety.models import LiveModeAuthorization
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig

from .conftest import binding_for


class FakeRealFleetVehicle(SimulatedVehicle):
    """Contract-only real-backend double; it never opens a radio or claims measurements."""

    @property
    def backend_profile(self) -> VehicleBackendProfile:
        return VehicleBackendProfile(
            role=BackendRole.REAL_CRAZYFLIE,
            authority=AuthorityClass.PHYSICAL,
            clock_policy=SourceClockPolicy.REALTIME_MONOTONIC,
            command_completion=CommandCompletionMode.BLOCKING_COMPLETION,
        )


@dataclass
class CommandCapture:
    commands: list[CommandEnvelope] = field(default_factory=list)

    def command_sent(self, command: CommandEnvelope) -> None:
        self.commands.append(command)

    def __getattr__(self, name: str) -> Any:
        del name
        return lambda value: None


async def _run_backend(
    deployment: DeploymentManifest,
    backend: ExecutionBackend,
) -> tuple[FleetPreparation, FleetResult, CommandCapture]:
    binding = binding_for(deployment, backend)
    capture = CommandCapture()
    supervisor = SafetySupervisor(audit_sinks=(capture,))
    preparation = FleetPreparation(
        execution_session_id="fleet-session-1",
        deployment=deployment,
        binding=binding,
        supervisor=supervisor,
    )
    placeholders = preparation.record.vehicles
    assert all(item.registration is RegistrationState.DECLARED for item in placeholders)
    assert all(item.observation is ObservationState.NOT_OBSERVED for item in placeholders)
    assert all(item.latest_telemetry is None for item in placeholders)

    preparation.initialize_backend(software_backend_factory(deployment, binding))
    assert all(
        item.registration is RegistrationState.VERIFIED for item in preparation.record.vehicles
    )
    assert all(
        item.connection is ConnectionState.DISCONNECTED for item in preparation.record.vehicles
    )
    await preparation.connect_all()
    await preparation.start_observation()
    preflight = await preparation.run_preflight()
    assert preflight.approved

    registry = default_registry()
    source_sha256 = registry.metadata("hover").source_sha256
    assert source_sha256 is not None
    mission = MissionArtifact(
        mission_id="hover",
        mission_version="1.0.0",
        source_sha256=source_sha256,
    )
    identity = FleetSessionIdentity.create(
        fleet_session_id="fleet-session-1",
        fleet_run_id="fleet-run-1",
        backend=backend,
        mission=mission,
        deployment=deployment,
        binding=binding,
        model_id="software-fleet-foundation",
        scenario_id=deployment.deployment_id,
        initial_state={
            member.vehicle_id: member.home.model_dump(mode="json") for member in deployment.fleet
        },
    )
    coordinator = FleetCoordinator(
        identity=identity,
        deployment=deployment,
        preparation=preparation,
        supervisor=supervisor,
        mission_runner=MissionRunner(supervisor, registry),
    )
    result = await coordinator.run({"inspect-a": "cf01", "inspect-b": "cf02"})
    return preparation, result, capture


async def test_one_drone_separation_monitor_does_not_resample_telemetry(
    two_drone_deployment: DeploymentManifest,
) -> None:
    deployment = two_drone_deployment.model_copy(
        update={
            "fleet": (two_drone_deployment.fleet[0],),
            "zones": (two_drone_deployment.zones[0],),
            "tasks": (two_drone_deployment.tasks[0],),
        }
    )
    coordinator = object.__new__(FleetCoordinator)
    coordinator.deployment = deployment

    # The early return intentionally needs no supervisor or adapter. Accessing
    # either would mean a no-op one-drone pair check still generated evidence.
    assert await coordinator.enforce_separation() == ()


@pytest.mark.parametrize("backend", (ExecutionBackend.FAST_SIM, ExecutionBackend.MOCK_ISAAC))
async def test_two_drone_fleet_completes_with_bound_commands(
    two_drone_deployment: DeploymentManifest,
    backend: ExecutionBackend,
) -> None:
    preparation, result, capture = await _run_backend(two_drone_deployment, backend)
    try:
        assert result.status is FleetStatus.SUCCEEDED
        assert [item.vehicle_id for item in result.child_results] == ["cf01", "cf02"]
        assert all(
            sum(event.event_type == "TASK_LEASE_RENEWED" for event in task.events) <= 1
            for task in result.tasks
        )
        assert all(item.fleet is not None for item in capture.commands)
        for command in capture.commands:
            assert command.fleet is not None
            assert command.vehicle_id in {"cf01", "cf02"}
            expected_task = "inspect-a" if command.vehicle_id == "cf01" else "inspect-b"
            assert command.fleet.task_id == expected_task
            assert command.fleet.fleet_session_id == "fleet-session-1"
    finally:
        await preparation.disconnect_all_safe()


async def test_fast_sim_and_mock_isaac_have_equivalent_normalized_outcomes(
    two_drone_deployment: DeploymentManifest,
) -> None:
    fast_preparation, fast, _ = await _run_backend(two_drone_deployment, ExecutionBackend.FAST_SIM)
    mock_preparation, mock, _ = await _run_backend(
        two_drone_deployment, ExecutionBackend.MOCK_ISAAC
    )
    try:
        golden = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "config/qualification/fleet-preparation-golden-v1.json"
            ).read_text(encoding="utf-8")
        )["events"]
        assert list(fast_preparation.normalized_trace()) == golden
        assert fast_preparation.normalized_trace() == mock_preparation.normalized_trace()
        assert fast.normalized_trace == mock.normalized_trace
        assert fast.normalized_outcome_sha256 == mock.normalized_outcome_sha256
    finally:
        await fast_preparation.disconnect_all_safe()
        await mock_preparation.disconnect_all_safe()


async def test_fake_real_adapter_has_the_same_normalized_preparation_trace(
    two_drone_deployment: DeploymentManifest,
) -> None:
    fast_preparation, _, _ = await _run_backend(two_drone_deployment, ExecutionBackend.FAST_SIM)
    binding = BackendBindingProfile(
        binding_id="fake-real-two-drone-v1",
        backend=ExecutionBackend.CRAZYFLIE,
        vehicles=tuple(
            BackendVehicleBinding(
                vehicle_id=member.vehicle_id,
                expected_vehicle_id=member.vehicle_id,
                backend_identifier=f"fake-radio/{member.vehicle_id}",
                operator_selected=True,
            )
            for member in two_drone_deployment.fleet
        ),
    )
    supervisor = SafetySupervisor()
    preparation = FleetPreparation(
        execution_session_id="fleet-session-1",
        deployment=two_drone_deployment,
        binding=binding,
        supervisor=supervisor,
    )
    world = IndoorWorld(WorldConfig(width_m=8.0, depth_m=6.0, height_m=3.0))
    vehicles = tuple(
        FakeRealFleetVehicle(
            VehicleIdentity(
                vehicle_id=member.vehicle_id,
                display_name=member.display_name,
                adapter="fake-real-contract",
            ),
            world,
            config=SimulationConfig(),
            initial_position_m=member.home,
        )
        for member in two_drone_deployment.fleet
    )
    preparation.discover(vehicles)
    for vehicle in vehicles:
        supervisor.set_mode(
            OperatingMode.LIVE,
            authorization=LiveModeAuthorization(
                vehicle_id=vehicle.identity.vehicle_id,
                operator_id="fake-real-qualification",
                mode=OperatingMode.LIVE,
                confirmed=True,
                authorized_at_monotonic_s=time.monotonic(),
            ),
        )
    await preparation.connect_all()
    await preparation.start_observation()
    assert (await preparation.run_preflight()).approved
    try:
        assert preparation.normalized_trace() == fast_preparation.normalized_trace()
    finally:
        await preparation.disconnect_all_safe()
        await fast_preparation.disconnect_all_safe()


async def test_warning_separation_blocks_launch_before_critical_threshold(
    two_drone_deployment: DeploymentManifest,
) -> None:
    close_deployment = two_drone_deployment.model_copy(
        update={
            "fleet": (
                two_drone_deployment.fleet[0].model_copy(update={"home": Vector3(x=-0.3)}),
                two_drone_deployment.fleet[1].model_copy(update={"home": Vector3(x=0.3)}),
            )
        }
    )
    preparation, result, _ = await _run_backend(close_deployment, ExecutionBackend.FAST_SIM)
    try:
        assert result.status is FleetStatus.FAILED
        assert result.reason_code == "PREFLIGHT_FAILED"
        assert result.child_results == ()
        assert result.warning_violations == 1
        assert result.critical_violations == 0
        assert result.minimum_separation_m == pytest.approx(0.6)
    finally:
        await preparation.disconnect_all_safe()
