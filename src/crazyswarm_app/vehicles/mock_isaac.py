from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Any

from crazyswarm_app.domain.commands import (
    AcknowledgementStatus,
    CommandAcknowledgement,
    CommandEnvelope,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    AuthorityClass,
    BackendRole,
    CommandCompletionMode,
    CoordinateFrame,
    SourceClockPolicy,
    Vector3,
    VehicleBackendProfile,
    VehicleCapabilities,
    VehicleCapability,
    VehicleIdentity,
    VehicleState,
)
from crazyswarm_app.domain.simulation import (
    AdapterContractManifest,
    MissionRunBinding,
    canonical_sha256,
)
from crazyswarm_app.domain.telemetry import (
    FlowReading,
    ImuReading,
    LocalizationSource,
    RangeReadings,
    RangeStatus,
    TelemetryEnvelope,
    TransportReading,
    VehicleTelemetry,
)
from crazyswarm_app.isaac.protocol import GatewayRunBinding
from crazyswarm_app.vehicles.base import Vehicle

MOCK_ISAAC_GATEWAY_PROTOCOL_VERSION = "1.3.0"
MOCK_ISAAC_MODEL_ID = "mock-isaac-crazyflie"


class MockGatewayFault(StrEnum):
    DELAYED = "delayed"
    DUPLICATE = "duplicate"
    REORDERED = "reordered"
    MALFORMED = "malformed"
    WRONG_ID = "wrong_id"
    WRONG_FRAME = "wrong_frame"
    WRONG_MODEL = "wrong_model"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    CRASHED = "crashed"
    RESTARTED = "restarted"
    ACKNOWLEDGEMENT_LOST = "acknowledgement_lost"


class MockIsaacSimVehicle(Vehicle):
    """Command-capable process boundary used before Isaac is installed."""

    def __init__(
        self,
        vehicle_id: str = "isaac01",
        *,
        display_name: str = "Isaac gateway mock",
        backend_identifier: str | None = None,
        initial_position_m: Vector3 | None = None,
        scenario_id: str = "mock-isaac-room",
        scenario_configuration_sha256: str | None = None,
        withhold_position_after_s: float | None = None,
        gateway_faults: tuple[MockGatewayFault, ...] = (),
    ) -> None:
        self._identity = VehicleIdentity(
            vehicle_id=vehicle_id,
            display_name=display_name,
            adapter="mock-isaac-gateway-v1",
        )
        self._capabilities = VehicleCapabilities(
            features=frozenset(
                {
                    VehicleCapability.ARMING,
                    VehicleCapability.RELATIVE_POSITIONING,
                    VehicleCapability.HIGH_LEVEL_COMMANDS,
                    VehicleCapability.RANGE_SENSING,
                    VehicleCapability.EMERGENCY_STOP,
                    VehicleCapability.TIME_PARAMETERIZED_TRAJECTORY,
                }
            )
        )
        self._process: asyncio.subprocess.Process | None = None
        self._request_lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[TelemetryEnvelope]] = set()
        self._latest = self._disconnected_sample()
        self._backend_identifier = backend_identifier or f"/World/{vehicle_id}"
        self._initial_position_m = initial_position_m or Vector3()
        self._scenario_id = scenario_id
        self._scenario_configuration_sha256 = scenario_configuration_sha256 or canonical_sha256(
            {"room": [4.0, 4.0, 2.5]}
        )
        self._withhold_position_after_s = withhold_position_after_s
        self._gateway_faults = gateway_faults
        self._next_request_id = 0
        self._last_source_marker: tuple[int, int, float] | None = None
        self._binding: GatewayRunBinding | None = None
        self._telemetry_dropped_total = 0

    @property
    def identity(self) -> VehicleIdentity:
        return self._identity

    @property
    def capabilities(self) -> VehicleCapabilities:
        return self._capabilities

    @property
    def backend_namespace(self) -> str:
        return self._backend_identifier

    @property
    def backend_profile(self) -> VehicleBackendProfile:
        return VehicleBackendProfile(
            role=BackendRole.ISAAC_SIM,
            authority=AuthorityClass.SIMULATION,
            clock_policy=SourceClockPolicy.ACCELERATED_OR_REALTIME,
            command_completion=CommandCompletionMode.BLOCKING_COMPLETION,
            supports_duration_aware_timeout=True,
            supports_source_clock_reset=True,
            recommended_watchdog_period_s=0.0,
        )

    @property
    def contract_manifest(self) -> AdapterContractManifest:
        return AdapterContractManifest(
            adapter_id=self.identity.adapter,
            supported_capabilities=self.capabilities.features,
            supported_signals=frozenset({"position", "flow", "ranges", "battery", "transport"}),
            supported_model_ids=frozenset({MOCK_ISAAC_MODEL_ID}),
        )

    @property
    def execution_metadata(self) -> dict[str, str | int | float | None]:
        configuration = {
            "gateway_protocol": MOCK_ISAAC_GATEWAY_PROTOCOL_VERSION,
            "model": MOCK_ISAAC_MODEL_ID,
        }
        return {
            "vehicle_adapter": self.identity.adapter,
            "backend_role": self.backend_profile.role.value,
            "authority_class": self.backend_profile.authority.value,
            "physics_model_id": MOCK_ISAAC_MODEL_ID,
            "physics_model_version": "1.0.0",
            "physics_configuration_sha256": canonical_sha256(configuration),
            "scenario_id": self._scenario_id,
            "scenario_schema_version": "1",
            "scenario_configuration_sha256": self._scenario_configuration_sha256,
            "simulation_seed": 0,
            "simulation_fixed_step_s": 0.01,
            "initial_state_sha256": canonical_sha256(
                {"position": self._initial_position_m.model_dump(mode="json")}
            ),
            "run_identity_sha256": self._binding.run_identity_sha256
            if self._binding is not None
            else None,
        }

    @property
    def telemetry_dropped_total(self) -> int:
        return self._telemetry_dropped_total

    async def connect(self) -> None:
        if self._process is not None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "mock gateway is already connected")
        worker = Path(__file__).with_name("_mock_isaac_gateway.py")
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(worker),
            env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._next_request_id = 0
        self._last_source_marker = None
        self._binding = None
        response = await self._request(
            {
                "type": "connect",
                "vehicle_id": self.identity.vehicle_id,
                "backend_identifier": self._backend_identifier,
                "initial_position_m": self._initial_position_m.model_dump(mode="json"),
                "faults": [fault.value for fault in self._gateway_faults],
            }
        )
        self._ingest(response["telemetry"])

    async def bind_run(self, binding: MissionRunBinding) -> None:
        if binding.mission_source_sha256 is None or any(
            value is None
            for value in (
                binding.run_identity_sha256,
                binding.model_id,
                binding.model_version,
                binding.model_configuration_sha256,
                binding.scenario_id,
                binding.scenario_configuration_sha256,
            )
        ):
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "mock Isaac requires complete source/model/scenario run identity",
            )
        gateway_binding = GatewayRunBinding(
            mission_run_id=binding.mission_run_id,
            mission_source_sha256=binding.mission_source_sha256,
            run_identity_sha256=str(binding.run_identity_sha256),
            model_id=str(binding.model_id),
            model_version=str(binding.model_version),
            model_configuration_sha256=str(binding.model_configuration_sha256),
            scenario_id=str(binding.scenario_id),
            scenario_configuration_sha256=str(binding.scenario_configuration_sha256),
            fleet_session_id=binding.fleet_session_id,
            fleet_run_id=binding.fleet_run_id,
            deployment_sha256=binding.deployment_sha256,
            task_id=binding.task_id,
            task_lease_generation=binding.task_lease_generation,
            backend_namespace=binding.backend_namespace,
            preparation_state=binding.preparation_state,
        )
        if (
            gateway_binding.backend_namespace is not None
            and gateway_binding.backend_namespace != self._backend_identifier
        ):
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "mock Isaac fleet namespace does not match the vehicle binding",
            )
        metadata = self.execution_metadata
        if (
            gateway_binding.model_id != metadata["physics_model_id"]
            or gateway_binding.model_version != metadata["physics_model_version"]
            or gateway_binding.model_configuration_sha256
            != metadata["physics_configuration_sha256"]
            or gateway_binding.scenario_id != metadata["scenario_id"]
            or gateway_binding.scenario_configuration_sha256
            != metadata["scenario_configuration_sha256"]
        ):
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "mock Isaac run binding mismatch")
        response = await self._request(
            {
                "type": "bind_run",
                "vehicle_id": self.identity.vehicle_id,
                "payload": {"binding": gateway_binding.model_dump(mode="json")},
            }
        )
        self._binding = gateway_binding
        self._ingest(response["telemetry"])

    async def disconnect(self) -> None:
        process = self._process
        if process is None:
            self._latest = self._disconnected_sample()
            return
        with suppress(CrazySwarmError, KeyError):
            response = await self._request(
                {"type": "disconnect", "vehicle_id": self.identity.vehicle_id}
            )
            self._ingest(response["telemetry"])
        if process.stdin is not None:
            process.stdin.close()
        with suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=0.5)
        if process.returncode is None:
            process.kill()
            await process.wait()
        self._process = None
        self._binding = None

    async def execute(self, command: CommandEnvelope) -> CommandAcknowledgement:
        if command.vehicle_id != self.identity.vehicle_id:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH, "mock gateway command target mismatch"
            )
        try:
            response = await self._request(
                {
                    "type": "command",
                    "vehicle_id": self.identity.vehicle_id,
                    "command": command.model_dump(mode="json"),
                    "run_identity_sha256": self._binding.run_identity_sha256
                    if self._binding is not None
                    else None,
                }
            )
        except CrazySwarmError as error:
            raise CrazySwarmError(
                error.code,
                error.message,
                details={
                    **error.details,
                    "command_id": command.command_id,
                    "command_outcome": AcknowledgementStatus.UNKNOWN_OUTCOME.value,
                    "automatic_retry_safe": False,
                },
            ) from error
        if response.get("command_id") != command.command_id:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH, "mock gateway acknowledgement mismatch"
            )
        self._ingest(response["telemetry"])
        now = time.monotonic()
        return CommandAcknowledgement(
            vehicle_id=self.identity.vehicle_id,
            command_id=command.command_id,
            status=AcknowledgementStatus.COMPLETED,
            received_at_monotonic_s=command.issued_at_monotonic_s,
            completed_at_monotonic_s=max(now, command.issued_at_monotonic_s),
            message="mock Isaac command completed",
        )

    async def snapshot(self) -> TelemetryEnvelope:
        if self._process is None:
            return self._latest
        response = await self._request({"type": "snapshot", "vehicle_id": self.identity.vehicle_id})
        return self._ingest(response["telemetry"])

    async def reset_source_clock(self) -> TelemetryEnvelope:
        response = await self._request(
            {"type": "reset_clock", "vehicle_id": self.identity.vehicle_id}
        )
        return self._ingest(response["telemetry"])

    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryEnvelope]:
        queue: asyncio.Queue[TelemetryEnvelope] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    async def _request(self, value: dict[str, Any]) -> dict[str, Any]:
        async with self._request_lock:
            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                raise CrazySwarmError(ErrorCode.LINK_LOST, "mock Isaac gateway is unavailable")
            if process.returncode is not None:
                raise CrazySwarmError(ErrorCode.LINK_LOST, "mock Isaac gateway process exited")
            self._next_request_id += 1
            request_id = self._next_request_id
            request = {**value, "request_id": request_id}
            process.stdin.write(json_line(request))
            try:
                await process.stdin.drain()
                raw = await asyncio.wait_for(process.stdout.readline(), timeout=2.0)
            except (BrokenPipeError, ConnectionError, TimeoutError) as error:
                raise CrazySwarmError(
                    ErrorCode.LINK_LOST, "mock Isaac gateway request failed"
                ) from error
            if not raw:
                raise CrazySwarmError(ErrorCode.LINK_LOST, "mock Isaac gateway closed")
            try:
                response = json_loads(raw)
            except (TypeError, ValueError) as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND, "malformed mock gateway response"
                ) from error
            if response.get("request_id") != request_id:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "mock gateway response request identity mismatch",
                )
            if response.get("protocol_version") != MOCK_ISAAC_GATEWAY_PROTOCOL_VERSION:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "mock gateway protocol version mismatch",
                )
            if response.get("model_id") != MOCK_ISAAC_MODEL_ID:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "mock gateway model identity mismatch",
                )
            if response.get("frame") != CoordinateFrame.HOME.value:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "mock gateway coordinate frame mismatch",
                )
            if not response.get("ok"):
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    str(response.get("error") or "mock gateway rejected request"),
                )
            return response

    def _ingest(self, raw: dict[str, Any]) -> TelemetryEnvelope:
        if raw.get("vehicle_id") != self.identity.vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "mock telemetry identity mismatch")
        if self._binding is not None and raw.get("run_identity_sha256") != (
            self._binding.run_identity_sha256
        ):
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "mock telemetry run mismatch")
        position = Vector3(
            x=float(raw["position"][0]),
            y=float(raw["position"][1]),
            z=float(raw["position"][2]),
        )
        source_time = float(raw["source_timestamp_s"])
        source_epoch = int(raw["source_clock_epoch"])
        sequence = int(raw["sequence"])
        marker = self._last_source_marker
        if marker is not None:
            previous_epoch, previous_sequence, previous_time = marker
            if source_epoch < previous_epoch or (
                source_epoch == previous_epoch
                and (sequence <= previous_sequence or source_time < previous_time)
            ):
                raise CrazySwarmError(
                    ErrorCode.TELEMETRY_STALE,
                    "mock gateway telemetry did not advance monotonically",
                )
        self._last_source_marker = (source_epoch, sequence, source_time)
        position_available = (
            self._withhold_position_after_s is None or source_time < self._withhold_position_after_s
        )
        envelope = TelemetryEnvelope(
            vehicle_id=self.identity.vehicle_id,
            sequence=sequence,
            source_timestamp_s=source_time,
            received_timestamp_s=source_time,
            simulation_timestamp_s=source_time,
            source_clock_id=f"mock-isaac-{self.identity.vehicle_id}",
            source_clock_epoch=source_epoch,
            telemetry=VehicleTelemetry(
                state=VehicleState(str(raw["state"])),
                armed=bool(raw["armed"]),
                flying=bool(raw["flying"]),
                position_m=position if position_available else None,
                velocity_m_s=Vector3(),
                attitude={"roll_rad": 0.0, "pitch_rad": 0.0, "yaw_rad": float(raw["yaw"])},
                frame=CoordinateFrame.HOME,
                position_is_estimate=True if position_available else None,
                localization_source=(
                    LocalizationSource.SIMULATED if position_available else LocalizationSource.NONE
                ),
                localization_quality_percent=100.0 if position_available else None,
                battery_percent=100.0,
                transport=TransportReading(
                    kind="modeled_transport",
                    source_class="SIMULATED_MODEL",
                    delivery_quality_percent=100.0,
                    latency_ms=0.0,
                    packet_loss_percent=0.0,
                ),
                capabilities=self.capabilities,
                imu=ImuReading(),
                flow=FlowReading(
                    velocity_body_m_s=Vector3(),
                    ground_distance_m=position.z,
                    quality_percent=100.0 if position.z > 0.0 else 0.0,
                ),
                ranges=RangeReadings(
                    front_m=max(0.0, 2.0 - position.x),
                    back_m=max(0.0, 2.0 + position.x),
                    left_m=max(0.0, 2.0 - position.y),
                    right_m=max(0.0, 2.0 + position.y),
                    up_m=max(0.0, 2.5 - position.z),
                    down_m=position.z,
                    statuses={
                        name: RangeStatus.VALID
                        for name in ("front", "back", "left", "right", "up", "down")
                    },
                    source_timestamp_s=source_time,
                ),
            ),
        )
        self._latest = envelope
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
                self._telemetry_dropped_total += 1
            queue.put_nowait(envelope)
        return envelope

    def _disconnected_sample(self) -> TelemetryEnvelope:
        return TelemetryEnvelope(
            vehicle_id=self.identity.vehicle_id,
            sequence=0,
            source_timestamp_s=0.0,
            received_timestamp_s=0.0,
            source_clock_id=f"mock-isaac-{self.identity.vehicle_id}",
            telemetry=VehicleTelemetry(state=VehicleState.DISCONNECTED),
        )


def json_line(value: dict[str, Any]) -> bytes:
    import json

    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def json_loads(value: bytes) -> dict[str, Any]:
    import json

    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise TypeError("gateway response must be an object")
    return parsed
