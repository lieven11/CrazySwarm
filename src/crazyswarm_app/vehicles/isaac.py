from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from pydantic import ValidationError

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
from crazyswarm_app.domain.telemetry import TelemetryEnvelope, VehicleTelemetry
from crazyswarm_app.isaac.mapping import command_to_gateway_payload, gateway_sample_to_canonical
from crazyswarm_app.isaac.protocol import (
    GatewayCapabilities,
    GatewayHealth,
    GatewayLifecycleState,
    GatewayOperation,
    GatewayRequest,
    GatewayResponse,
    GatewayRunBinding,
)
from crazyswarm_app.isaac.scene import IsaacSceneSpecification
from crazyswarm_app.isaac.transport import (
    GatewayTransport,
    LocalProcessEndpoint,
    ManagedProcessTransport,
    TlsGatewayEndpoint,
    TlsGatewayTransport,
)
from crazyswarm_app.vehicles.base import Vehicle


class IsaacSimVehicle(Vehicle):
    """Out-of-process Isaac adapter; this module never imports Isaac or ROS packages."""

    def __init__(
        self,
        *,
        scene: IsaacSceneSpecification,
        endpoint: LocalProcessEndpoint | TlsGatewayEndpoint,
        authentication_token: str | None = None,
    ) -> None:
        vehicle = scene.vehicles[0]
        self._scene = scene
        self._identity = VehicleIdentity(
            vehicle_id=vehicle.vehicle_id,
            display_name="Isaac Sim vehicle",
            adapter="isaac-gateway-v1",
        )
        self._capabilities = VehicleCapabilities(
            features=frozenset(
                {
                    VehicleCapability.ARMING,
                    VehicleCapability.RELATIVE_POSITIONING,
                    VehicleCapability.HIGH_LEVEL_COMMANDS,
                    VehicleCapability.RANGE_SENSING,
                    VehicleCapability.EMERGENCY_STOP,
                }
            )
        )
        self._transport: GatewayTransport = (
            ManagedProcessTransport(endpoint)
            if isinstance(endpoint, LocalProcessEndpoint)
            else TlsGatewayTransport(endpoint)
        )
        if isinstance(endpoint, TlsGatewayEndpoint) and authentication_token is None:
            raise ValueError("remote Isaac gateway requires an authentication token")
        self._authentication_token = authentication_token or secrets.token_urlsafe(32)
        if isinstance(endpoint, LocalProcessEndpoint):
            endpoint.environment["CRAZYSWARM_ISAAC_GATEWAY_TOKEN"] = self._authentication_token
        self._request_lock = asyncio.Lock()
        self._next_request_id = 0
        self._session_id: str | None = None
        self._gateway_instance_id: str | None = None
        self._binding: GatewayRunBinding | None = None
        self._negotiated: GatewayCapabilities | None = None
        self._health: GatewayHealth | None = None
        self._subscribers: set[asyncio.Queue[TelemetryEnvelope]] = set()
        self._telemetry_dropped_total = 0
        self._latest = self._disconnected_sample()
        self._last_source_marker: tuple[int, int, float] | None = None

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
            supports_duration_aware_timeout=True,
            supports_source_clock_reset=True,
            recommended_watchdog_period_s=0.02,
        )

    @property
    def contract_manifest(self) -> AdapterContractManifest:
        vehicle = self._scene.vehicles[0]
        signals = (
            self._negotiated.signals
            if self._negotiated is not None
            else frozenset({"position", "ground-truth-position", "imu", "flow", "ranges"})
        )
        return AdapterContractManifest(
            adapter_id=self.identity.adapter,
            supported_capabilities=self.capabilities.features,
            supported_signals=signals,
            supported_model_ids=frozenset({vehicle.model_id}),
        )

    @property
    def execution_metadata(self) -> dict[str, str | int | float | None]:
        vehicle = self._scene.vehicles[0]
        return {
            "vehicle_adapter": self.identity.adapter,
            "backend_role": self.backend_profile.role.value,
            "authority_class": self.backend_profile.authority.value,
            "physics_model_id": vehicle.model_id,
            "physics_model_version": vehicle.model_version,
            "physics_configuration_sha256": vehicle.parameter_configuration_sha256,
            "scenario_id": self._scene.scene_id,
            "scenario_schema_version": str(self._scene.schema_version),
            "scenario_configuration_sha256": self._scene.sha256,
            "simulation_seed": 0,
            "simulation_fixed_step_s": self._scene.runtime.fixed_step_s,
            "initial_state_sha256": canonical_sha256(
                {
                    "position_m": vehicle.initial_position_m.model_dump(mode="json"),
                    "yaw_rad": vehicle.initial_yaw_rad,
                }
            ),
            "run_identity_sha256": self._binding.run_identity_sha256
            if self._binding is not None
            else None,
        }

    @property
    def gateway_health(self) -> GatewayHealth | None:
        return self._health

    @property
    def telemetry_dropped_total(self) -> int:
        return self._telemetry_dropped_total

    async def connect(self) -> None:
        if self._transport.state not in {
            GatewayLifecycleState.NEW,
            GatewayLifecycleState.STOPPED,
        }:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "Isaac gateway is already connected")
        await self._transport.start()
        self._next_request_id = 0
        self._last_source_marker = None
        try:
            response = await self._request(
                GatewayOperation.CONNECT,
                {
                    "expected_scene_id": self._scene.scene_id,
                    "expected_scene_sha256": self._scene.sha256,
                    "expected_model_id": self._scene.vehicles[0].model_id,
                    "expected_model_version": self._scene.vehicles[0].model_version,
                    "headless": self._scene.runtime.headless,
                    "renderer_enabled": self._scene.runtime.renderer_enabled,
                },
                include_authentication=True,
            )
            if response.capabilities is None:
                raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "Isaac capabilities are absent")
            self._validate_capabilities(response.capabilities)
        except BaseException:
            await self._transport.close()
            raise
        self._negotiated = response.capabilities
        self._session_id = response.session_id
        self._gateway_instance_id = response.gateway_instance_id
        self._health = response.health
        if response.telemetry is not None:
            self._ingest(response)

    async def bind_run(self, binding: MissionRunBinding) -> None:
        if binding.mission_source_sha256 is None or any(
            item is None
            for item in (
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
                "Isaac mission requires complete source/model/scenario run identity",
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
        expected = self.execution_metadata
        if (
            gateway_binding.model_id != expected["physics_model_id"]
            or gateway_binding.model_version != expected["physics_model_version"]
            or gateway_binding.model_configuration_sha256
            != expected["physics_configuration_sha256"]
            or gateway_binding.scenario_id != expected["scenario_id"]
            or gateway_binding.scenario_configuration_sha256
            != expected["scenario_configuration_sha256"]
        ):
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac run binding changed model")
        response = await self._request(
            GatewayOperation.BIND_RUN,
            {"binding": gateway_binding.model_dump(mode="json")},
        )
        self._binding = gateway_binding
        self._health = response.health
        if response.telemetry is not None:
            self._ingest(response)

    async def disconnect(self) -> None:
        if self._transport.state in {
            GatewayLifecycleState.READY,
            GatewayLifecycleState.RUN_BOUND,
        }:
            with suppress(CrazySwarmError):
                response = await self._request(GatewayOperation.DISCONNECT, {})
                if response.telemetry is not None:
                    self._ingest(response)
        await self._transport.close()
        self._session_id = None
        self._binding = None
        self._negotiated = None
        self._latest = self._disconnected_sample()

    async def execute(self, command: CommandEnvelope) -> CommandAcknowledgement:
        if command.vehicle_id != self.identity.vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac command target mismatch")
        try:
            response = await self._request(
                GatewayOperation.COMMAND,
                command_to_gateway_payload(command, binding=self._binding),
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
        if response.command_id != command.command_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac acknowledgement mismatch")
        if response.telemetry is not None:
            self._ingest(response)
        now = time.monotonic()
        return CommandAcknowledgement(
            vehicle_id=self.identity.vehicle_id,
            command_id=command.command_id,
            status=AcknowledgementStatus.COMPLETED,
            received_at_monotonic_s=command.issued_at_monotonic_s,
            completed_at_monotonic_s=max(now, command.issued_at_monotonic_s),
            message="Isaac gateway command completed",
        )

    async def snapshot(self) -> TelemetryEnvelope:
        response = await self._request(GatewayOperation.SNAPSHOT, {})
        if response.telemetry is None:
            raise CrazySwarmError(ErrorCode.TELEMETRY_STALE, "Isaac snapshot is absent")
        return self._ingest(response)

    async def refresh_gateway_health(self) -> GatewayHealth:
        response = await self._request(GatewayOperation.HEALTH, {})
        if response.health is None:
            raise CrazySwarmError(ErrorCode.TELEMETRY_STALE, "Isaac health is absent")
        self._health = response.health.model_copy(
            update={"telemetry_dropped_total": self._telemetry_dropped_total}
        )
        return self._health

    async def manual_step(self, steps: int = 1) -> TelemetryEnvelope:
        if isinstance(steps, bool) or not 1 <= steps <= 10_000:
            raise ValueError("Isaac manual step count must be between 1 and 10000")
        if self._negotiated is None or not self._negotiated.supports_manual_step:
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "Isaac manual stepping is absent")
        response = await self._request(GatewayOperation.STEP, {"steps": steps})
        if response.telemetry is None:
            raise CrazySwarmError(ErrorCode.TELEMETRY_STALE, "Isaac step telemetry is absent")
        return self._ingest(response)

    async def reset_source_clock(self) -> TelemetryEnvelope:
        response = await self._request(GatewayOperation.RESET_CLOCK, {})
        if response.telemetry is None:
            raise CrazySwarmError(ErrorCode.TELEMETRY_STALE, "Isaac clock reset sample is absent")
        return self._ingest(response)

    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryEnvelope]:
        queue: asyncio.Queue[TelemetryEnvelope] = asyncio.Queue(
            maxsize=self._scene.runtime.telemetry_queue_bound
        )
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    async def _request(
        self,
        operation: GatewayOperation,
        payload: dict[str, Any],
        *,
        include_authentication: bool = False,
    ) -> GatewayResponse:
        async with self._request_lock:
            self._next_request_id += 1
            request = GatewayRequest(
                request_id=self._next_request_id,
                operation=operation,
                vehicle_id=self.identity.vehicle_id,
                session_id=self._session_id,
                authentication_token=self._authentication_token if include_authentication else None,
                payload=payload,
            )
            try:
                raw = await self._transport.request(request.model_dump(mode="json"))
                response = GatewayResponse.model_validate(raw)
            except ValidationError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND, "malformed Isaac gateway response"
                ) from error
            if response.request_id != request.request_id or response.operation is not operation:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH, "Isaac request identity mismatch"
                )
            if response.vehicle_id != self.identity.vehicle_id:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH, "Isaac vehicle identity mismatch"
                )
            if not response.ok:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    response.error or "Isaac gateway rejected request",
                    details={"gateway_error_code": response.error_code},
                )
            if response.model_id != self._scene.vehicles[0].model_id:
                raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac model identity mismatch")
            if response.model_version != self._scene.vehicles[0].model_version:
                raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac model version mismatch")
            if response.frame is not CoordinateFrame.HOME:
                raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac frame mismatch")
            if self._session_id is not None and response.session_id != self._session_id:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH, "Isaac session identity mismatch"
                )
            return response

    def _ingest(self, response: GatewayResponse) -> TelemetryEnvelope:
        sample = response.telemetry
        if sample is None:
            raise CrazySwarmError(ErrorCode.TELEMETRY_STALE, "Isaac telemetry is absent")
        marker = (sample.source_clock_epoch, sample.sequence, sample.source_timestamp_s)
        if self._last_source_marker is not None:
            previous_epoch, previous_sequence, previous_time = self._last_source_marker
            if marker[0] < previous_epoch or (
                marker[0] == previous_epoch
                and (marker[1] <= previous_sequence or marker[2] < previous_time)
            ):
                raise CrazySwarmError(ErrorCode.TELEMETRY_STALE, "Isaac telemetry is stale")
        self._last_source_marker = marker
        envelope = gateway_sample_to_canonical(
            sample,
            vehicle_id=self.identity.vehicle_id,
            expected_model_id=self._scene.vehicles[0].model_id,
            expected_model_version=self._scene.vehicles[0].model_version,
            binding=self._binding,
        )
        self._latest = envelope
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
                self._telemetry_dropped_total += 1
            queue.put_nowait(envelope)
        return envelope

    def _validate_capabilities(self, capabilities: GatewayCapabilities) -> None:
        required_commands = frozenset(
            {
                "arm",
                "disarm",
                "takeoff",
                "hover",
                "move_relative",
                "stop_and_hold",
                "land",
                "abort",
                "emergency_stop",
            }
        )
        required_signals = frozenset({"position", "ground-truth-position", "imu", "flow", "ranges"})
        if capabilities.authority is not AuthorityClass.SIMULATION:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED, "Isaac authority is not simulation"
            )
        if capabilities.digital_twin_enabled:
            raise CrazySwarmError(ErrorCode.MODE_NOT_AUTHORIZED, "DIGITAL_TWIN is disabled")
        if not self.capabilities.features.issubset(capabilities.vehicle_capabilities):
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "Isaac capabilities are incomplete")
        if not required_commands.issubset(capabilities.commands):
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "Isaac command set is incomplete")
        if not required_signals.issubset(capabilities.signals):
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "Isaac signal set is incomplete")
        if self._scene.runtime.headless and not capabilities.supports_headless:
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "Isaac headless mode is unsupported")
        if not capabilities.supports_manual_step:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED, "Isaac manual stepping is unsupported"
            )
        if not capabilities.supports_clock_reset:
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "Isaac clock reset is unsupported")
        if capabilities.maximum_vehicles < 1:
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "Isaac vehicle capacity is absent")

    def _disconnected_sample(self) -> TelemetryEnvelope:
        return TelemetryEnvelope(
            vehicle_id=self.identity.vehicle_id,
            sequence=0,
            source_timestamp_s=0.0,
            received_timestamp_s=0.0,
            source_clock_id=f"isaac-{self.identity.vehicle_id}",
            telemetry=VehicleTelemetry(state=VehicleState.DISCONNECTED),
        )
