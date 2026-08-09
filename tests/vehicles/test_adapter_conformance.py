from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from crazyswarm_app.domain.commands import (
    AcknowledgementStatus,
    ArmCommand,
    CommandAcknowledgement,
    CommandEnvelope,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    AuthorityClass,
    BackendRole,
    CommandCompletionMode,
    SourceClockPolicy,
    VehicleBackendProfile,
    VehicleCapabilities,
    VehicleCapability,
    VehicleIdentity,
    VehicleState,
)
from crazyswarm_app.domain.simulation import AdapterContractManifest
from crazyswarm_app.domain.telemetry import TelemetryEnvelope, VehicleTelemetry
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig
from crazyswarm_app.vehicles.base import Vehicle
from crazyswarm_app.vehicles.mock_isaac import (
    MockGatewayFault,
)
from crazyswarm_app.vehicles.mock_isaac import (
    MockIsaacSimVehicle as GatewayMockIsaacSimVehicle,
)
from tests.vehicles.conformance import (
    assert_flight_vehicle_conformance,
    assert_vehicle_conformance,
)


class MockIsaacSimVehicle(Vehicle):
    """Isaac-shaped test double proving the contract has no FastSim dependency."""

    def __init__(self) -> None:
        self._identity = VehicleIdentity(
            vehicle_id="isaac01",
            display_name="Isaac contract mock",
            adapter="isaac-sim-mock",
        )
        self._capabilities = VehicleCapabilities(
            features=frozenset({VehicleCapability.HIGH_LEVEL_COMMANDS})
        )
        self._state = VehicleState.DISCONNECTED
        self._sequence = 0

    @property
    def identity(self) -> VehicleIdentity:
        return self._identity

    @property
    def capabilities(self) -> VehicleCapabilities:
        return self._capabilities

    @property
    def backend_profile(self) -> VehicleBackendProfile:
        return VehicleBackendProfile(
            role=BackendRole.ISAAC_SIM,
            authority=AuthorityClass.SIMULATION,
            clock_policy=SourceClockPolicy.ACCELERATED_OR_REALTIME,
            command_completion=CommandCompletionMode.BLOCKING_COMPLETION,
        )

    @property
    def contract_manifest(self) -> AdapterContractManifest:
        return AdapterContractManifest(
            adapter_id="isaac-sim-mock",
            supported_capabilities=self.capabilities.features,
            supported_signals=frozenset({"position"}),
            supported_model_ids=frozenset({"isaac-crazyflie"}),
        )

    async def connect(self) -> None:
        self._state = VehicleState.READY

    async def disconnect(self) -> None:
        self._state = VehicleState.DISCONNECTED

    async def execute(self, command: CommandEnvelope) -> CommandAcknowledgement:
        if command.vehicle_id != self.identity.vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "mock target mismatch")
        return CommandAcknowledgement(
            vehicle_id=self.identity.vehicle_id,
            command_id=command.command_id,
            status=AcknowledgementStatus.COMPLETED,
            received_at_monotonic_s=command.issued_at_monotonic_s,
            completed_at_monotonic_s=command.issued_at_monotonic_s,
        )

    async def snapshot(self) -> TelemetryEnvelope:
        return TelemetryEnvelope(
            vehicle_id=self.identity.vehicle_id,
            sequence=self._sequence,
            source_timestamp_s=float(self._sequence),
            received_timestamp_s=float(self._sequence),
            source_clock_id="isaac-mock-clock",
            telemetry=VehicleTelemetry(state=self._state, capabilities=self.capabilities),
        )

    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryEnvelope]:
        yield await self.snapshot()


def adapter(adapter_id: str) -> Vehicle:
    if adapter_id == "fast-sim":
        return SimulatedVehicle(
            VehicleIdentity(vehicle_id="sim01", display_name="FastSim", adapter="sim"),
            IndoorWorld(WorldConfig()),
            config=SimulationConfig(),
        )
    return MockIsaacSimVehicle()


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_id", ["fast-sim", "isaac-mock"])
async def test_backend_neutral_adapter_conformance(adapter_id: str) -> None:
    await assert_vehicle_conformance(adapter(adapter_id))


def test_fast_sim_and_mock_reject_unsupported_capabilities_before_start() -> None:
    fast_sim = adapter("fast-sim")
    isaac = adapter("isaac-mock")
    isaac.contract_manifest.require(frozenset({VehicleCapability.HIGH_LEVEL_COMMANDS}))
    with pytest.raises(ValueError, match="capability missing"):
        fast_sim.contract_manifest.require(frozenset({VehicleCapability.GLOBAL_POSITIONING}))
    with pytest.raises(ValueError, match="capability missing"):
        isaac.contract_manifest.require(frozenset({VehicleCapability.EMERGENCY_STOP}))


def test_domain_and_mission_interfaces_do_not_name_concrete_simulators() -> None:
    import inspect

    import crazyswarm_app.domain.commands as commands
    import crazyswarm_app.missions.base as mission_base
    import crazyswarm_app.vehicles.base as vehicle_base

    source = "\n".join(
        inspect.getsource(module) for module in (commands, mission_base, vehicle_base)
    )
    assert "SimulatedVehicle" not in source
    assert "SixDofPhysics" not in source
    assert "IsaacSimVehicle" not in source


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_id", ["fast-sim", "isaac-gateway"])
async def test_shared_flight_adapter_conformance(adapter_id: str) -> None:
    vehicle = (
        adapter("fast-sim")
        if adapter_id == "fast-sim"
        else GatewayMockIsaacSimVehicle(vehicle_id="isaac01")
    )
    await assert_flight_vehicle_conformance(vehicle)


@pytest.mark.asyncio
async def test_gateway_process_loss_is_structured_and_never_retried_as_success() -> None:
    vehicle = GatewayMockIsaacSimVehicle()
    await vehicle.connect()
    process = vehicle._process
    assert process is not None
    process.kill()
    await process.wait()
    with pytest.raises(CrazySwarmError) as lost:
        await vehicle.snapshot()
    assert lost.value.code is ErrorCode.LINK_LOST
    await vehicle.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fault", "expected_code"),
    [
        (MockGatewayFault.REORDERED, ErrorCode.IDENTITY_MISMATCH),
        (MockGatewayFault.MALFORMED, ErrorCode.INVALID_COMMAND),
        (MockGatewayFault.WRONG_ID, ErrorCode.IDENTITY_MISMATCH),
        (MockGatewayFault.WRONG_FRAME, ErrorCode.IDENTITY_MISMATCH),
        (MockGatewayFault.WRONG_MODEL, ErrorCode.IDENTITY_MISMATCH),
        (MockGatewayFault.STALE, ErrorCode.TELEMETRY_STALE),
        (MockGatewayFault.CRASHED, ErrorCode.LINK_LOST),
        (MockGatewayFault.ACKNOWLEDGEMENT_LOST, ErrorCode.LINK_LOST),
    ],
)
async def test_gateway_rejects_invalid_or_lost_responses(
    fault: MockGatewayFault,
    expected_code: ErrorCode,
) -> None:
    vehicle = GatewayMockIsaacSimVehicle(gateway_faults=(fault,))
    await vehicle.connect()
    with pytest.raises(CrazySwarmError) as rejected:
        await vehicle.snapshot()
    assert rejected.value.code is expected_code
    await vehicle.disconnect()


@pytest.mark.asyncio
async def test_gateway_delay_duplicate_disconnect_and_restart_are_explicit() -> None:
    delayed = GatewayMockIsaacSimVehicle(gateway_faults=(MockGatewayFault.DELAYED,))
    await delayed.connect()
    assert (await delayed.snapshot()).telemetry.state is VehicleState.READY
    await delayed.disconnect()

    duplicate = GatewayMockIsaacSimVehicle(gateway_faults=(MockGatewayFault.DUPLICATE,))
    await duplicate.connect()
    assert (await duplicate.snapshot()).telemetry.state is VehicleState.READY
    with pytest.raises(CrazySwarmError) as duplicate_response:
        await duplicate.snapshot()
    assert duplicate_response.value.code is ErrorCode.IDENTITY_MISMATCH
    await duplicate.disconnect()

    for fault in (MockGatewayFault.DISCONNECTED, MockGatewayFault.RESTARTED):
        vehicle = GatewayMockIsaacSimVehicle(gateway_faults=(fault,))
        await vehicle.connect()
        telemetry = await vehicle.snapshot()
        assert telemetry.telemetry.state is VehicleState.DISCONNECTED
        await vehicle.disconnect()


@pytest.mark.asyncio
async def test_acknowledgement_loss_is_unknown_outcome_and_never_auto_retried() -> None:
    vehicle = GatewayMockIsaacSimVehicle(gateway_faults=(MockGatewayFault.ACKNOWLEDGEMENT_LOST,))
    await vehicle.connect()
    command = CommandEnvelope(
        vehicle_id=vehicle.identity.vehicle_id,
        command_id="unknown-arm-outcome",
        issued_at_monotonic_s=0.0,
        source="TEST",
        mode="SIM",
        payload=ArmCommand(),
    )
    with pytest.raises(CrazySwarmError) as unknown:
        await vehicle.execute(command)
    assert unknown.value.code is ErrorCode.LINK_LOST
    assert unknown.value.details == {
        "command_id": "unknown-arm-outcome",
        "command_outcome": AcknowledgementStatus.UNKNOWN_OUTCOME.value,
        "automatic_retry_safe": False,
    }
    await vehicle.disconnect()
