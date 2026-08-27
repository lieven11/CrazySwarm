from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from crazyswarm_app.api.runtime import ApplicationRuntime
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    ContractModel,
    CoordinateFrame,
    EulerAttitude,
    Vector3,
    VehicleIdentity,
)
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.telemetry import (
    EstimatorReading,
    FlowReading,
    ImuReading,
    Percentage,
    RadioFailureKind,
    RangeReadings,
    TelemetryEnvelope,
    TransportReading,
)
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld
from crazyswarm_app.twin.ingestion import default_twin_channels
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinIngestionBatch,
    TwinInitialState,
    TwinQuality,
    TwinSessionConfig,
    TwinSourceClass,
    TwinStreamSample,
    TwinStreamSide,
)
from crazyswarm_app.vehicles._cflib_link import CflibCrazyflieLink
from crazyswarm_app.vehicles.crazyflie import RADIO_URI_PATTERN, CrazyflieVehicle
from crazyswarm_app.vehicles.crazyflie_link import CrazyflieLink


class ObservationTwinState(StrEnum):
    UNCONFIGURED = "UNCONFIGURED"
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    PAIRED = "PAIRED"
    SUSPENDED = "SUSPENDED"
    ERROR = "ERROR"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"


class ObservationProvenance(StrEnum):
    MEASURED_REAL = "MEASURED_REAL"
    TEST = "TEST"


class PhysicalTwinBindingRequest(ContractModel):
    selected_uri: str = Field(min_length=1, max_length=120)
    vehicle_label: str = Field(default="Crazyflie", min_length=1, max_length=80)
    confirm_exact_uri: Literal[True]


class PhysicalTwinConfirmRequest(ContractModel):
    connection_nonce: str = Field(min_length=32, max_length=128)
    observed_identity_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PhysicalTwinSourceStatus(ContractModel):
    role: Literal["OBSERVED", "PREDICTED"]
    vehicle_id: str
    source_class: TwinSourceClass
    freshness: Literal["CURRENT", "STALE", "MISSING"]
    frame: CoordinateFrame | None = None
    source_clock_id: str | None = None
    source_epoch: int | None = Field(default=None, ge=1)
    raw_source_timestamp_s: float | None = Field(default=None, ge=0.0)
    source_timestamp_s: float | None = Field(default=None, ge=0.0)
    pair_sequence: int | None = Field(default=None, ge=1)
    alignment_epoch: int | None = Field(default=None, ge=1)
    position_availability: Literal["AVAILABLE", "MISSING", "INCOMPATIBLE"]
    position_m: Vector3 | None = None
    battery_availability: Literal["AVAILABLE", "MISSING"]
    battery_voltage_v: float | None = Field(default=None, ge=0.0)
    armed: bool | None = None
    flying: bool | None = None
    faults: tuple[str, ...] = ()
    attitude: EulerAttitude | None = None
    imu: ImuReading | None = None
    flow: FlowReading | None = None
    ranges: RangeReadings | None = None
    estimator: EstimatorReading | None = None
    transport: TransportReading | None = None
    motor_pwm_percent: tuple[Percentage, Percentage, Percentage, Percentage] | None = None
    family_availability: dict[str, TwinAvailability] = Field(default_factory=dict)


class PhysicalTwinStatus(ContractModel):
    schema_version: Literal[1] = 1
    state: ObservationTwinState
    configured: bool
    auto_connect_enabled: bool = False
    vehicle_label: str | None = None
    redacted_uri: str | None = None
    uri_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    connection_nonce: str | None = None
    observed_identity_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    command_readiness: Literal["NOT_ASSESSED", "UNQUALIFIED"] = "NOT_ASSESSED"
    command_readiness_issues: tuple[str, ...] = ()
    session_id: str | None = None
    observed_source_class: TwinSourceClass | None = None
    predicted_source_class: TwinSourceClass | None = None
    provenance: ObservationProvenance | None = None
    test_only: bool = False
    sample_count: int = Field(default=0, ge=0)
    paired_cycle_count: int = Field(default=0, ge=0)
    observed: PhysicalTwinSourceStatus | None = None
    predicted: PhysicalTwinSourceStatus | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_failure_kind: RadioFailureKind | None = None
    last_failure_at_utc: datetime | None = None
    reconnect_attempt: int = Field(default=0, ge=0)
    reconnect_mode: Literal["IDLE", "FAST", "LOW_DUTY"] = "IDLE"
    next_reconnect_at_utc: datetime | None = None
    suspension_reason: str | None = None
    suspension_owner: str | None = None
    suspended_at_utc: datetime | None = None
    telemetry_owner: Literal["OBSERVER", "PHYSICAL_OPERATION"] = "OBSERVER"
    operation_sample_count: int = Field(default=0, ge=0)


class PhysicalTwinLiveFrame(ContractModel):
    """Compact presentation sample; retained twin evidence remains separately decimated."""

    schema_version: Literal[1] = 1
    state: ObservationTwinState
    vehicle_label: str | None = None
    live_sequence: int = Field(ge=0)
    paired_cycle_count: int = Field(ge=0)
    channel_record_count: int = Field(ge=0)
    observed: PhysicalTwinSourceStatus | None = None
    telemetry_owner: Literal["OBSERVER", "PHYSICAL_OPERATION"] = "OBSERVER"
    operation_sample_count: int = Field(default=0, ge=0)


@dataclass(frozen=True, slots=True)
class ObservationConnectionResult:
    observed_identity_sha256: str
    command_readiness_issues: tuple[str, ...]
    first_sample: TelemetryEnvelope


@dataclass(frozen=True, slots=True)
class PhysicalCommandTarget:
    selected_uri: str
    vehicle_label: str
    observed_identity_sha256: str | None


class ObservationFacade(Protocol):
    async def connect(self) -> ObservationConnectionResult: ...

    async def snapshot(self) -> TelemetryEnvelope: ...

    async def restart_telemetry(self) -> TelemetryEnvelope: ...

    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]: ...

    async def disconnect(self) -> None: ...


class CrazyflieObservationFacade:
    """Small read-only surface around a service-private Crazyflie adapter."""

    def __init__(self, vehicle: CrazyflieVehicle) -> None:
        self.__vehicle = vehicle

    async def connect(self) -> ObservationConnectionResult:
        await self.__vehicle.connect()
        metadata = self.__vehicle.connection_metadata
        if metadata is None:
            raise RuntimeError("connected observer did not expose identity metadata")
        first_sample = await self.__vehicle.snapshot()
        return ObservationConnectionResult(
            observed_identity_sha256=canonical_sha256(
                {
                    "selected_uri": metadata.selected_uri,
                    "connected_uri": metadata.connected_uri,
                    "protocol_version": metadata.protocol_version,
                    "firmware_version": metadata.firmware_version,
                    "deck_parameters": metadata.deck_parameters,
                    "adapter_contract": self.__vehicle.contract_manifest,
                }
            ),
            command_readiness_issues=self.__vehicle.command_readiness_issues,
            first_sample=first_sample,
        )

    async def snapshot(self) -> TelemetryEnvelope:
        return await self.__vehicle.snapshot()

    async def restart_telemetry(self) -> TelemetryEnvelope:
        return await self.__vehicle.restart_observation_telemetry()

    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        return self.__vehicle.telemetry_stream()

    async def disconnect(self) -> None:
        await self.__vehicle.disconnect()

    def borrow_command_vehicle(
        self,
        *,
        vehicle_id: str,
        telemetry_listener: Callable[[TelemetryEnvelope], None] | None,
    ) -> CrazyflieVehicle:
        return self.__vehicle.borrow_connected_command_adapter(
            vehicle_id=vehicle_id,
            telemetry_listener=telemetry_listener,
        )

    @property
    def supervisor_auto_arming(self) -> bool | None:
        return self.__vehicle.supervisor_auto_arming


@dataclass(frozen=True, slots=True)
class _Binding:
    selected_uri: str
    vehicle_label: str
    uri_sha256: str
    confirmed_identity_sha256: str | None = None
    auto_connect_enabled: bool = False


@dataclass(slots=True)
class _ClockMap:
    producer_epoch: int
    session_epoch: int
    first_raw_s: float
    session_base_s: float
    last_raw_s: float
    last_mapped_s: float


LinkFactory = Callable[[], CrazyflieLink]


class ObservationTwinService:
    """Private, read-only real/Fast-Sim pairing with no flight authority surface."""

    BINDING_SCHEMA_VERSION = 1
    CONFIRMATION_TTL_S = 300.0
    # The UI observes cached radio values at 30 Hz. Evidence pairing remains at
    # 10 Hz so smoother presentation does not triple retained channel volume.
    LIVE_SAMPLE_PERIOD_S = 1.0 / 30.0
    SAMPLE_PERIOD_S = 0.100
    # Keep retained evidence below the hard rolling-window admission limit.
    # Scheduling at exactly 100 ms can still place eleven admissions inside an
    # open one-second window after accumulated event-loop and clock jitter.
    EVIDENCE_PERIOD_S = 0.105
    AUTO_RECONNECT_DELAYS_S = (1.0, 2.0, 5.0, 10.0, 30.0)
    RECONNECT_STABILITY_RESET_S = 30.0
    # Healthy radio ACKs plus stale logs indicate that the on-board log blocks
    # need to be installed again. An active RF fade gets a longer in-place
    # recovery window so carrying or briefly obscuring a grounded drone does
    # not churn the connection.
    STALE_RECONNECT_S = 5.0
    RF_FADE_RECONNECT_S = 15.0
    LOG_REPAIR_STABILITY_RESET_S = 30.0

    def __init__(
        self,
        runtime: ApplicationRuntime,
        *,
        binding_path: Path | None = None,
        link_factory: LinkFactory | None = None,
    ) -> None:
        self._runtime = runtime
        self._binding_path = binding_path or (
            runtime.config.cache_directory / "physical-twin-binding.json"
        )
        self._link_factory = link_factory or (
            lambda: CflibCrazyflieLink(
                cache_directory=runtime.config.cache_directory / "cflib",
                enable_latency_pings=False,
            )
        )
        # An injected transport is always test provenance.  Production real
        # provenance is reserved for the in-module cflib construction above.
        self._test_transport = link_factory is not None
        self._lock = asyncio.Lock()
        self._binding: _Binding | None = None
        self._state = ObservationTwinState.UNCONFIGURED
        self._facade: ObservationFacade | None = None
        self._predicted: SimulatedVehicle | None = None
        self._first_observed: TelemetryEnvelope | None = None
        self._session_id: str | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._evidence_task: asyncio.Task[None] | None = None
        self._nonce: str | None = None
        self._nonce_deadline_s = 0.0
        self._observed_identity_sha256: str | None = None
        self._issues: tuple[str, ...] = ()
        self._sample_count = 0
        self._last_error_code: str | None = None
        self._last_error_message: str | None = None
        self._last_failure_kind: RadioFailureKind | None = None
        self._last_failure_at_utc: datetime | None = None
        self._reconnect_attempt = 0
        self._reconnect_mode: Literal["IDLE", "FAST", "LOW_DUTY"] = "IDLE"
        self._next_reconnect_at_utc: datetime | None = None
        self._clock_maps: dict[tuple[TwinStreamSide, str], _ClockMap] = {}
        self._sequences: dict[tuple[TwinStreamSide, str], int] = {}
        self._batch_admission_times_s: deque[float] = deque()
        self._observed_vehicle_id: str | None = None
        self._predicted_vehicle_id: str | None = None
        self._latest_observed: TelemetryEnvelope | None = None
        self._latest_predicted: TelemetryEnvelope | None = None
        self._last_pair_received_monotonic_s: float | None = None
        self._pair_origin_monotonic_s: float | None = None
        self._last_pair_source_timestamp_s: float | None = None
        self._pair_sequence = 0
        self._alignment_epoch = 1
        self._last_pair_epoch_signature: tuple[str, int, str, int] | None = None
        self._last_live_received_monotonic_s: float | None = None
        self._stale_observation_since_monotonic_s: float | None = None
        self._paired_at_monotonic_s: float | None = None
        self._live_sequence = 0
        self._latest_operation: TelemetryEnvelope | None = None
        self._last_operation_received_monotonic_s: float | None = None
        self._operation_sample_count = 0
        self._live_subscribers: set[asyncio.Queue[PhysicalTwinLiveFrame | None]] = set()
        self._suspended = False
        self._suspension_reason: str | None = None
        self._suspension_owner: str | None = None
        self._suspended_at_utc: datetime | None = None
        self._connection_retained_during_suspension = False
        self._supervisor_task: asyncio.Task[None] | None = None
        self._supervisor_wake = asyncio.Event()
        self._load_binding()

    def status(self) -> PhysicalTwinStatus:
        binding = self._binding
        operation_owns_telemetry = self._suspended
        provenance = (
            ObservationProvenance.TEST
            if self._test_transport
            and (self._session_id is not None or self._latest_operation is not None)
            else ObservationProvenance.MEASURED_REAL
            if self._session_id is not None or self._latest_operation is not None
            else None
        )
        observed_source = None
        predicted_source = None
        if self._session_id is not None or self._latest_operation is not None:
            observed_source = (
                TwinSourceClass.TEST if self._test_transport else TwinSourceClass.MEASURED_REAL
            )
        if self._session_id is not None:
            predicted_source = (
                TwinSourceClass.TEST if self._test_transport else TwinSourceClass.SIMULATED_MODEL
            )
        return PhysicalTwinStatus(
            state=self._state,
            configured=binding is not None,
            auto_connect_enabled=(
                False if binding is None else binding.auto_connect_enabled
            ),
            vehicle_label=None if binding is None else binding.vehicle_label,
            redacted_uri=None if binding is None else self._redact_uri(binding.selected_uri),
            uri_sha256=None if binding is None else binding.uri_sha256,
            connection_nonce=(
                self._nonce
                if self._state is ObservationTwinState.PENDING_CONFIRMATION
                and time.monotonic() <= self._nonce_deadline_s
                else None
            ),
            observed_identity_sha256=self._observed_identity_sha256,
            command_readiness="UNQUALIFIED" if self._issues else "NOT_ASSESSED",
            command_readiness_issues=self._issues,
            session_id=self._session_id,
            observed_source_class=observed_source,
            predicted_source_class=predicted_source,
            provenance=provenance,
            test_only=self._test_transport
            and (self._session_id is not None or self._latest_operation is not None),
            sample_count=self._sample_count,
            paired_cycle_count=self._pair_sequence,
            observed=self._source_status(TwinStreamSide.OBSERVED),
            predicted=self._source_status(TwinStreamSide.PREDICTED),
            last_error_code=self._last_error_code,
            last_error_message=self._last_error_message,
            last_failure_kind=self._last_failure_kind,
            last_failure_at_utc=self._last_failure_at_utc,
            reconnect_attempt=self._reconnect_attempt,
            reconnect_mode=self._reconnect_mode,
            next_reconnect_at_utc=self._next_reconnect_at_utc,
            suspension_reason=self._suspension_reason,
            suspension_owner=self._suspension_owner,
            suspended_at_utc=self._suspended_at_utc,
            telemetry_owner=(
                "PHYSICAL_OPERATION" if operation_owns_telemetry else "OBSERVER"
            ),
            operation_sample_count=self._operation_sample_count,
        )

    def command_target(self) -> PhysicalCommandTarget:
        binding = self._binding
        if binding is None:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "configure an exact physical drone binding before requesting flight",
            )
        return PhysicalCommandTarget(
            selected_uri=binding.selected_uri,
            vehicle_label=binding.vehicle_label,
            observed_identity_sha256=(
                self._observed_identity_sha256 or binding.confirmed_identity_sha256
            ),
        )

    def supervisor_auto_arming(self) -> bool | None:
        """Return the latest measured firmware arming mode, if connected."""

        facade = self._facade
        return (
            facade.supervisor_auto_arming
            if isinstance(facade, CrazyflieObservationFacade)
            else None
        )

    async def borrow_command_vehicle(
        self,
        *,
        vehicle_id: str,
        selected_uri: str,
        telemetry_listener: Callable[[TelemetryEnvelope], None] | None = None,
    ) -> CrazyflieVehicle:
        """Borrow the suspended observer's connected link for one operation."""

        async with self._lock:
            facade = self._facade
            binding = self._binding
            if (
                not self._suspended
                or not self._connection_retained_during_suspension
                or self._state is not ObservationTwinState.SUSPENDED
                or binding is None
                or not isinstance(facade, CrazyflieObservationFacade)
            ):
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "the paired observer did not retain a command connection",
                )
            if selected_uri != binding.selected_uri:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "the physical command target does not match the retained observer link",
                )
            try:
                await facade.snapshot()
            except Exception as retained_error:
                # No command permit exists yet, so this is the only safe point at
                # which the handoff may retry a stale transport. Keep the recovered
                # link owned by the observer so resume does not cause another
                # disconnect/reconnect cycle.
                with suppress(Exception):
                    await facade.disconnect()
                self._facade = None
                facade = self._new_observation_facade(binding)
                self._facade = facade
                try:
                    connection = await facade.connect()
                    if (
                        binding.confirmed_identity_sha256
                        != connection.observed_identity_sha256
                    ):
                        raise CrazySwarmError(
                            ErrorCode.IDENTITY_MISMATCH,
                            "the reconnected Crazyflie does not match the confirmed binding",
                        )
                except Exception as retry_error:
                    with suppress(Exception):
                        await facade.disconnect()
                    self._facade = None
                    raise CrazySwarmError(
                        ErrorCode.LINK_LOST,
                        "the retained Crazyflie link was stale and one safe reconnect failed",
                        details={
                            "retained_error": str(retained_error),
                            "retry_error": str(retry_error),
                        },
                    ) from retry_error
                self._first_observed = connection.first_sample
                self._observed_identity_sha256 = connection.observed_identity_sha256
                self._issues = connection.command_readiness_issues
            return facade.borrow_command_vehicle(
                vehicle_id=vehicle_id,
                telemetry_listener=telemetry_listener,
            )

    def live_frame(self) -> PhysicalTwinLiveFrame:
        binding = self._binding
        return PhysicalTwinLiveFrame(
            state=self._state,
            vehicle_label=None if binding is None else binding.vehicle_label,
            live_sequence=self._live_sequence,
            paired_cycle_count=self._pair_sequence,
            channel_record_count=self._sample_count,
            observed=self._source_status(TwinStreamSide.OBSERVED),
            telemetry_owner=(
                "PHYSICAL_OPERATION" if self._suspended else "OBSERVER"
            ),
            operation_sample_count=self._operation_sample_count,
        )

    async def live_stream(self) -> AsyncIterator[PhysicalTwinLiveFrame]:
        """Yield latest-only presentation frames with bounded per-client backpressure."""

        queue: asyncio.Queue[PhysicalTwinLiveFrame | None] = asyncio.Queue(maxsize=1)
        self._live_subscribers.add(queue)
        try:
            yield self.live_frame()
            live_states = {
                ObservationTwinState.PAIRED,
                ObservationTwinState.SUSPENDED,
            }
            if self._state not in live_states:
                return
            while True:
                frame = await queue.get()
                if frame is None:
                    return
                yield frame
                if frame.state not in live_states:
                    return
        finally:
            self._live_subscribers.discard(queue)

    async def configure(self, request: PhysicalTwinBindingRequest) -> PhysicalTwinStatus:
        async with self._lock:
            if self._state in {
                ObservationTwinState.CONNECTING,
                ObservationTwinState.PENDING_CONFIRMATION,
                ObservationTwinState.PAIRED,
            }:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "disconnect the physical twin before changing its exact URI",
                )
            if RADIO_URI_PATTERN.fullmatch(request.selected_uri) is None:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "selected_uri must be a full explicit Crazyradio URI",
                )
            uri_hash = hashlib.sha256(request.selected_uri.encode()).hexdigest()
            previous = self._binding
            confirmed = (
                previous.confirmed_identity_sha256
                if previous is not None and previous.uri_sha256 == uri_hash
                else None
            )
            self._binding = _Binding(
                selected_uri=request.selected_uri,
                vehicle_label=request.vehicle_label,
                uri_sha256=uri_hash,
                confirmed_identity_sha256=confirmed,
                auto_connect_enabled=False,
            )
            self._persist_binding()
            self._clear_ephemeral()
            self._state = ObservationTwinState.DISCONNECTED
            return self.status()

    async def connect(self) -> PhysicalTwinStatus:
        async with self._lock:
            if self._binding is None:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE, "physical twin URI is not configured"
                )
            if not self._binding.auto_connect_enabled:
                self._binding = replace(self._binding, auto_connect_enabled=True)
                self._persist_binding()
            status = await self._connect_locked()
            if status.state is ObservationTwinState.ERROR:
                self._supervisor_wake.set()
            return status

    async def _connect_locked(self) -> PhysicalTwinStatus:
        binding = self._binding
        if binding is None:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE, "physical twin URI is not configured"
            )
        if self._suspended:
            self._state = ObservationTwinState.SUSPENDED
            return self.status()
        if self._state in {
            ObservationTwinState.CONNECTING,
            ObservationTwinState.PENDING_CONFIRMATION,
            ObservationTwinState.PAIRED,
        }:
            return self.status()
        # ERROR retains the failed session for inspection. A new connection is
        # a fresh observation epoch with fresh counters, clocks, and samples.
        previous_error_code = self._last_error_code
        previous_error_message = self._last_error_message
        self._clear_ephemeral()
        # Keep the authoritative failure visible while an automatic retry is in
        # CONNECTING. It is cleared only after a new pair is established.
        self._last_error_code = previous_error_code
        self._last_error_message = previous_error_message
        self._state = ObservationTwinState.CONNECTING
        facade = self._new_observation_facade(binding)
        self._facade = facade
        try:
            connection = await facade.connect()
            self._first_observed = connection.first_sample
            self._observed_identity_sha256 = connection.observed_identity_sha256
            self._issues = connection.command_readiness_issues
            self._last_error_code = None
            self._last_error_message = None
            if binding.confirmed_identity_sha256 is None:
                # Confirming and saving the exact URI is the operator's one pairing
                # action. Capture the first identity from that command-inert link so
                # reconnects never require a second confirmation step.
                self._binding = replace(
                    binding,
                    confirmed_identity_sha256=connection.observed_identity_sha256,
                )
                self._persist_binding()
            elif binding.confirmed_identity_sha256 != connection.observed_identity_sha256:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "connected drone identity does not match the saved observer binding",
                )
            await self._pair_locked()
        except Exception as error:
            await self._disconnect_adapters_locked(failed=True)
            self._state = ObservationTwinState.ERROR
            self._remember_failure(self._classify_transport_failure(error))
            self._last_error_code = (
                "RADIO_UNAVAILABLE"
                if isinstance(error, CrazySwarmError) and error.code is ErrorCode.LINK_LOST
                else "IDENTITY_MISMATCH"
                if isinstance(error, CrazySwarmError)
                and error.code is ErrorCode.IDENTITY_MISMATCH
                else "IDENTITY_OR_TELEMETRY_INVALID"
            )
            underlying = (
                error.details.get("error")
                if isinstance(error, CrazySwarmError) and error.details is not None
                else None
            )
            self._last_error_message = (
                f"{error.message}: {underlying}"
                if isinstance(error, CrazySwarmError)
                and isinstance(underlying, str)
                and underlying
                else str(error)
            )
        return self.status()

    @staticmethod
    def _classify_transport_failure(error: Exception) -> RadioFailureKind:
        message = str(error).lower()
        if (
            "crazyradio dongle" in message
            or "cannot find radio" in message
            or "probably been unplugged" in message
            or "usb" in message
        ):
            return RadioFailureKind.USB_UNAVAILABLE
        if "queue is saturated" in message or "could not send packet" in message:
            return RadioFailureKind.OUTBOUND_QUEUE_SATURATED
        if isinstance(error, CrazySwarmError) and error.code is ErrorCode.TELEMETRY_STALE:
            transport = (
                error.details.get("radio_transport")
                if error.details is not None
                else None
            )
            if isinstance(transport, dict):
                raw_failure_kind = transport.get("failure_kind")
                if isinstance(raw_failure_kind, str):
                    with suppress(ValueError):
                        failure_kind = RadioFailureKind(raw_failure_kind)
                        if failure_kind is not RadioFailureKind.NONE:
                            return failure_kind
                if transport.get("state") in {"DEGRADED", "STALE"}:
                    return RadioFailureKind.RF_ACK_LOSS
            return RadioFailureKind.TELEMETRY_STALE
        if "packet" in message or "acknowledgement" in message or "ack" in message:
            return RadioFailureKind.RF_ACK_LOSS
        if "parameter download" in message or "protocol" in message or "log telemetry" in message:
            return RadioFailureKind.PROTOCOL_SETUP_FAILED
        if "connection did not finish" in message or "timed out" in message:
            return RadioFailureKind.TARGET_OFFLINE
        return RadioFailureKind.UNKNOWN

    def _remember_failure(self, failure_kind: RadioFailureKind) -> None:
        self._last_failure_kind = failure_kind
        self._last_failure_at_utc = datetime.now(UTC)

    def _new_observation_facade(self, binding: _Binding) -> CrazyflieObservationFacade:
        vehicle_id = f"physical:pending-{secrets.token_hex(8)}"
        return CrazyflieObservationFacade(
            CrazyflieVehicle(
                vehicle_id=vehicle_id,
                selected_uri=binding.selected_uri,
                link=self._link_factory(),
                telemetry_timeout_s=self._runtime.config.safety_envelope.telemetry_timeout_s,
                observation_only=True,
            )
        )

    async def confirm(self, request: PhysicalTwinConfirmRequest) -> PhysicalTwinStatus:
        async with self._lock:
            if self._state is ObservationTwinState.PAIRED:
                return self.status()
            if self._state is not ObservationTwinState.PENDING_CONFIRMATION:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE, "no identity confirmation is pending"
                )
            if time.monotonic() > self._nonce_deadline_s:
                self._nonce = None
                await self._disconnect_adapters_locked(failed=True)
                self._state = ObservationTwinState.DISCONNECTED
                raise CrazySwarmError(ErrorCode.INVALID_STATE, "identity confirmation expired")
            if (
                not secrets.compare_digest(request.connection_nonce, self._nonce or "")
                or request.observed_identity_sha256 != self._observed_identity_sha256
            ):
                self._nonce = None
                await self._disconnect_adapters_locked(failed=True)
                self._state = ObservationTwinState.DISCONNECTED
                raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "identity confirmation mismatch")
            assert self._binding is not None
            self._binding = _Binding(
                selected_uri=self._binding.selected_uri,
                vehicle_label=self._binding.vehicle_label,
                uri_sha256=self._binding.uri_sha256,
                confirmed_identity_sha256=request.observed_identity_sha256,
                auto_connect_enabled=self._binding.auto_connect_enabled,
            )
            self._persist_binding()
            self._nonce = None
            try:
                await self._pair_locked()
            except Exception as error:
                await self._disconnect_adapters_locked(failed=True)
                self._state = ObservationTwinState.ERROR
                self._last_error_code = "PAIRING_FAILED"
                self._last_error_message = str(error)
                raise
            return self.status()

    async def disconnect(self) -> PhysicalTwinStatus:
        async with self._lock:
            if self._binding is not None and self._binding.auto_connect_enabled:
                self._binding = replace(self._binding, auto_connect_enabled=False)
            self._suspended = False
            self._connection_retained_during_suspension = False
            self._clear_suspension()
            await self._disconnect_adapters_locked(failed=False)
            self._clear_ephemeral()
            self._state = (
                ObservationTwinState.DISCONNECTED
                if self._binding is not None
                else ObservationTwinState.UNCONFIGURED
            )
            self._supervisor_wake.set()
            return self.status()

    async def start(self) -> None:
        if self._supervisor_task is not None:
            return
        self._supervisor_task = asyncio.create_task(
            self._supervise_connection(),
            name="physical-twin-connection-supervisor",
        )
        self._supervisor_wake.set()

    async def suspend(
        self,
        *,
        reason: str = "Physical operation owns the radio",
        owner: str = "control-api",
        retain_connection: bool = False,
    ) -> PhysicalTwinStatus:
        """Pause observation while preserving persistent connection intent."""

        async with self._lock:
            if self._suspended:
                # Abort during startup or flight joins the operation that already
                # owns the radio. It must not replace the authoritative reason or
                # disconnect the retained command transport underneath that task.
                return self.status()
            if retain_connection and (
                self._state is not ObservationTwinState.PAIRED
                or not isinstance(self._facade, CrazyflieObservationFacade)
            ):
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "a paired Crazyflie observer is required for connected handoff",
                )
            self._suspended = True
            self._suspension_reason = reason
            self._suspension_owner = owner
            self._suspended_at_utc = datetime.now(UTC)
            retained_identity = self._observed_identity_sha256
            retained_issues = self._issues
            if retain_connection:
                await self._pause_pairing_adapters_locked(failed=False)
            else:
                await self._disconnect_adapters_locked(failed=False)
            self._clear_ephemeral()
            if retain_connection:
                self._observed_identity_sha256 = retained_identity
                self._issues = retained_issues
            self._connection_retained_during_suspension = retain_connection
            self._state = (
                ObservationTwinState.SUSPENDED
                if self._binding is not None and self._binding.auto_connect_enabled
                else ObservationTwinState.DISCONNECTED
                if self._binding is not None
                else ObservationTwinState.UNCONFIGURED
            )
            self._supervisor_wake.set()
            self._publish_live_frame()
            return self.status()

    async def resume(self) -> PhysicalTwinStatus:
        """Resume an enabled observer after exclusive radio work."""

        async with self._lock:
            retained_connection = self._connection_retained_during_suspension
            self._connection_retained_during_suspension = False
            self._suspended = False
            self._clear_suspension()
            self._clear_operation_telemetry()
            self._state = (
                ObservationTwinState.DISCONNECTED
                if self._binding is not None
                else ObservationTwinState.UNCONFIGURED
            )
            if self._binding is None or not self._binding.auto_connect_enabled:
                if retained_connection and self._facade is not None:
                    await self._disconnect_adapters_locked(failed=False)
                return self.status()
            if retained_connection and isinstance(self._facade, CrazyflieObservationFacade):
                try:
                    observed = await self._facade.snapshot()
                    self._first_observed = observed
                    await self._pair_locked()
                except Exception as error:
                    await self._disconnect_adapters_locked(failed=True)
                    self._clear_ephemeral()
                    self._state = ObservationTwinState.ERROR
                    self._last_error_code = "RADIO_UNAVAILABLE"
                    self._last_error_message = str(error)
                    self._remember_failure(self._classify_transport_failure(error))
                    self._supervisor_wake.set()
                return self.status()
            status = await self._connect_locked()
            if status.state is ObservationTwinState.ERROR:
                self._supervisor_wake.set()
            return status

    def accept_operation_sample(self, sample: TelemetryEnvelope) -> None:
        """Publish telemetry from the physical link that temporarily owns the radio."""

        if not self._suspended:
            return
        self._latest_operation = sample
        self._last_operation_received_monotonic_s = time.monotonic()
        self._operation_sample_count += 1
        self._live_sequence += 1
        self._publish_live_frame()

    async def shutdown(self) -> None:
        supervisor = self._supervisor_task
        self._supervisor_task = None
        if supervisor is not None:
            supervisor.cancel()
            await asyncio.gather(supervisor, return_exceptions=True)
        async with self._lock:
            self._suspended = False
            self._connection_retained_during_suspension = False
            self._clear_suspension()
            await self._disconnect_adapters_locked(failed=False)
            self._clear_ephemeral()
            self._state = (
                ObservationTwinState.DISCONNECTED
                if self._binding is not None
                else ObservationTwinState.UNCONFIGURED
            )
            self._reconnect_attempt = 0
            self._reconnect_mode = "IDLE"
            self._next_reconnect_at_utc = None

    async def _supervise_connection(self) -> None:
        retry_index = 0
        try:
            while True:
                await self._supervisor_wake.wait()
                self._supervisor_wake.clear()
                if self._state is not ObservationTwinState.ERROR or (
                    self._paired_at_monotonic_s is not None
                    and time.monotonic() - self._paired_at_monotonic_s
                    >= self.RECONNECT_STABILITY_RESET_S
                ):
                    retry_index = 0
                while self._auto_connect_ready():
                    if self._state is ObservationTwinState.ERROR:
                        delay_s = self.AUTO_RECONNECT_DELAYS_S[
                            min(retry_index, len(self.AUTO_RECONNECT_DELAYS_S) - 1)
                        ]
                        retry_index += 1
                        self._reconnect_attempt = retry_index
                        self._reconnect_mode = (
                            "LOW_DUTY"
                            if retry_index >= len(self.AUTO_RECONNECT_DELAYS_S)
                            else "FAST"
                        )
                        self._next_reconnect_at_utc = datetime.now(UTC) + timedelta(
                            seconds=delay_s
                        )
                        self._publish_live_frame()
                        try:
                            await asyncio.wait_for(
                                self._supervisor_wake.wait(),
                                timeout=delay_s,
                            )
                        except TimeoutError:
                            pass
                        else:
                            self._supervisor_wake.clear()
                            if self._state is not ObservationTwinState.ERROR:
                                retry_index = 0
                        if not self._auto_connect_ready():
                            break
                    async with self._lock:
                        status = await self._connect_locked()
                    if status.state in {
                        ObservationTwinState.PAIRED,
                        ObservationTwinState.PENDING_CONFIRMATION,
                        ObservationTwinState.SUSPENDED,
                    }:
                        self._reconnect_attempt = 0
                        self._reconnect_mode = "IDLE"
                        self._next_reconnect_at_utc = None
                        break
        except asyncio.CancelledError:
            raise

    def _auto_connect_ready(self) -> bool:
        return (
            self._binding is not None
            and self._binding.auto_connect_enabled
            and not self._suspended
            and self._state is not ObservationTwinState.PAIRED
        )

    async def _pair_locked(self) -> None:
        assert self._binding is not None
        assert self._facade is not None
        assert self._first_observed is not None
        observed = self._first_observed
        # Crazyflie estimates are HOME-frame and may retain an arbitrary offset
        # that lies outside the configured Fast-Sim WORLD. Position channels are
        # explicitly incompatible until a transform is qualified, so the private
        # predictor starts at the scenario's configured WORLD spawn instead of
        # relabelling or clamping the measured HOME value.
        predictor_start = self._runtime.scenario.vehicles[0].position_m
        if self._observed_identity_sha256 is None:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "observed identity is unavailable")
        binding_id = self._observed_identity_sha256[:16]
        observed_id = f"physical:{binding_id}"
        predicted_id = f"fast-sim:{binding_id}"
        self._observed_vehicle_id = observed_id
        self._predicted_vehicle_id = predicted_id
        predicted = SimulatedVehicle(
            VehicleIdentity(
                vehicle_id=predicted_id,
                display_name=f"{self._binding.vehicle_label} predicted",
                adapter="fast-sim-observer",
            ),
            IndoorWorld(self._runtime.scenario.world),
            config=self._runtime.scenario.simulation,
            initial_position_m=predictor_start,
            scenario_id=self._runtime.scenario.scenario_id,
            scenario_schema_version=str(self._runtime.scenario.schema_version),
            scenario_configuration_sha256=canonical_sha256(self._runtime.scenario),
        )
        await predicted.connect()
        self._predicted = predicted
        source_real = (
            TwinSourceClass.TEST if self._test_transport else TwinSourceClass.MEASURED_REAL
        )
        source_sim = (
            TwinSourceClass.TEST if self._test_transport else TwinSourceClass.SIMULATED_MODEL
        )
        record = self._runtime.twins.create_session(
            TwinSessionConfig(
                observed_vehicle_id=observed_id,
                simulated_vehicle_id=predicted_id,
                mission_id="physical-observation",
                mission_version="1",
                physics_model_id=predicted.config.physics.model_id,
                physics_model_version=predicted.config.physics.model_version,
                physics_configuration_sha256=predicted.config.vehicle_parameters().sha256,
                observed_initial_state=TwinInitialState(
                    source_class=source_real,
                    source_id=("test-fixture" if self._test_transport else "crazyflie-firmware"),
                    frame=CoordinateFrame.HOME,
                    position_m=observed.telemetry.position_m,
                    velocity_m_s=observed.telemetry.velocity_m_s,
                    yaw_rad=(
                        None
                        if observed.telemetry.attitude is None
                        else observed.telemetry.attitude.yaw_rad
                    ),
                    battery_percent=observed.telemetry.battery_percent,
                ),
                simulated_initial_state=TwinInitialState(
                    source_class=source_sim,
                    source_id=("test-fixture" if self._test_transport else "fast-sim-observer"),
                    frame=CoordinateFrame.WORLD,
                    position_m=predictor_start,
                    battery_percent=predicted.battery_percent,
                ),
                test_only=self._test_transport,
            )
        )
        self._session_id = record.session_id
        self._state = ObservationTwinState.PAIRED
        self._last_error_code = None
        self._last_error_message = None
        self._reconnect_attempt = 0
        self._reconnect_mode = "IDLE"
        self._next_reconnect_at_utc = None
        self._paired_at_monotonic_s = time.monotonic()
        await predicted.advance_idle(self.SAMPLE_PERIOD_S)
        await self._ingest_pair(observed, await predicted.snapshot())
        self._accept_live_sample(observed)
        self._stream_task = asyncio.create_task(
            self._stream_loop(), name=f"physical-twin-{record.session_id}"
        )
        self._evidence_task = asyncio.create_task(
            self._evidence_loop(), name=f"physical-twin-evidence-{record.session_id}"
        )

    async def _stream_loop(self) -> None:
        last_log_repair_at_monotonic_s: float | None = None
        try:
            next_live_s = time.monotonic() + self.LIVE_SAMPLE_PERIOD_S
            while True:
                await asyncio.sleep(max(0.0, next_live_s - time.monotonic()))
                facade = self._facade
                if facade is None:
                    return
                try:
                    observed = await facade.snapshot()
                except CrazySwarmError as error:
                    if error.code is not ErrorCode.TELEMETRY_STALE:
                        raise
                    now_s = time.monotonic()
                    if self._stale_observation_since_monotonic_s is None:
                        self._stale_observation_since_monotonic_s = now_s
                    elif (
                        now_s - self._stale_observation_since_monotonic_s
                        >= self._stale_reconnect_grace_s(error)
                    ):
                        failure_kind = self._classify_transport_failure(error)
                        recent_log_repair = (
                            last_log_repair_at_monotonic_s is not None
                            and now_s - last_log_repair_at_monotonic_s
                            < self.LOG_REPAIR_STABILITY_RESET_S
                        )
                        if (
                            failure_kind is RadioFailureKind.TELEMETRY_STALE
                            and not recent_log_repair
                        ):
                            # Healthy ACKs with stale callbacks isolate the failure
                            # to cflib/firmware logging. Repair only those command-inert
                            # blocks first; a failed repair still reaches the existing
                            # full reconnect below without replaying anything.
                            self._remember_failure(failure_kind)
                            try:
                                observed = await facade.restart_telemetry()
                            except Exception as repair_error:
                                details = dict(error.details or {})
                                details["error"] = (
                                    "in-place firmware log restart failed: "
                                    f"{repair_error}"
                                )
                                raise CrazySwarmError(
                                    ErrorCode.TELEMETRY_STALE,
                                    "Crazyflie telemetry remained stale after one log restart",
                                    details=details,
                                ) from repair_error
                            self._stale_observation_since_monotonic_s = None
                            last_log_repair_at_monotonic_s = time.monotonic()
                            self._accept_live_sample(observed)
                        else:
                            # RF/USB/queue failures are not log-block failures, and
                            # a log stream that stalls again before the stability
                            # window has not been repaired. Preserve that measured
                            # boundary and use the existing full reconnect fallback.
                            raise
                    # Observation owns no command authority. A temporary idle RF
                    # fade must become truthful STALE presentation state without
                    # closing the cflib transport: the radio loop can then recover
                    # in place as soon as the same drone answers again. Command
                    # paths still reject this exact stale sample before dispatch.
                    self._publish_live_frame()
                else:
                    self._stale_observation_since_monotonic_s = None
                    self._accept_live_sample(observed)
                now_s = time.monotonic()
                next_live_s += self.LIVE_SAMPLE_PERIOD_S
                if next_live_s <= now_s:
                    next_live_s = now_s + self.LIVE_SAMPLE_PERIOD_S
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._fail_stream(error)

    def _stale_reconnect_grace_s(self, error: CrazySwarmError) -> float:
        failure_kind = self._classify_transport_failure(error)
        if failure_kind in {
            RadioFailureKind.RF_ACK_LOSS,
            RadioFailureKind.OUTBOUND_QUEUE_SATURATED,
        }:
            return self.RF_FADE_RECONNECT_S
        return self.STALE_RECONNECT_S

    async def _evidence_loop(self) -> None:
        try:
            next_evidence_s = time.monotonic() + self.EVIDENCE_PERIOD_S
            while True:
                await asyncio.sleep(max(0.0, next_evidence_s - time.monotonic()))
                predicted = self._predicted
                observed = self._latest_observed
                if predicted is None or observed is None:
                    return
                admitted_at_s = time.monotonic()
                await predicted.advance_idle(self.SAMPLE_PERIOD_S)
                await self._ingest_pair(
                    observed,
                    await predicted.snapshot(),
                    admitted_at_monotonic_s=admitted_at_s,
                )
                next_evidence_s = admitted_at_s + self.EVIDENCE_PERIOD_S
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._fail_stream(error)

    async def _fail_stream(self, error: Exception) -> None:
        async with self._lock:
            await self._disconnect_adapters_locked(failed=True)
            # The failed session remains retained in the twin journal, but its
            # last sample is no longer live operational truth. Clear only the
            # presentation pointers/cursors so status and SSE consumers render
            # the source as missing instead of continuing to show frozen values.
            self._clear_failed_live_telemetry()
            self._state = ObservationTwinState.ERROR
            self._last_error_code = "TELEMETRY_STREAM_FAILED"
            self._remember_failure(self._classify_transport_failure(error))
            underlying = (
                error.details.get("error")
                if isinstance(error, CrazySwarmError) and error.details is not None
                else None
            )
            self._last_error_message = (
                f"{error.message}: {underlying}"
                if isinstance(error, CrazySwarmError)
                and isinstance(underlying, str)
                and underlying
                else str(error)
            )
            self._publish_live_frame()
            self._supervisor_wake.set()

    def _accept_live_sample(self, observed: TelemetryEnvelope) -> None:
        self._latest_observed = observed
        # Freshness follows the latest real link callback, not the cadence of
        # cached presentation snapshots. The adapter independently fails the
        # stream when this received timestamp exceeds the safety timeout.
        self._last_live_received_monotonic_s = observed.received_timestamp_s
        self._live_sequence += 1
        self._publish_live_frame()

    def _publish_live_frame(self) -> None:
        frame = self.live_frame()
        for queue in tuple(self._live_subscribers):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(frame)

    def _close_live_streams(self) -> None:
        for queue in tuple(self._live_subscribers):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(None)

    async def _ingest_pair(
        self,
        observed: TelemetryEnvelope,
        predicted: TelemetryEnvelope,
        *,
        admitted_at_monotonic_s: float | None = None,
    ) -> None:
        if self._session_id is None:
            return
        admitted_at = (
            time.monotonic() if admitted_at_monotonic_s is None else admitted_at_monotonic_s
        )
        if self._all_measured_families_missing(observed):
            return
        self._admit_batch(admitted_at)
        if self._pair_origin_monotonic_s is None:
            self._pair_origin_monotonic_s = admitted_at
        source_timestamp_s = admitted_at - self._pair_origin_monotonic_s
        observed_clock_id = self._source_clock_id(TwinStreamSide.OBSERVED)
        predicted_clock_id = self._source_clock_id(TwinStreamSide.PREDICTED)
        observed_epoch = self._advance_source_epoch(
            TwinStreamSide.OBSERVED, observed, source_clock_id=observed_clock_id
        )
        predicted_epoch = self._advance_source_epoch(
            TwinStreamSide.PREDICTED, predicted, source_clock_id=predicted_clock_id
        )
        signature = (
            observed_clock_id,
            observed_epoch,
            predicted_clock_id,
            predicted_epoch,
        )
        if (
            self._last_pair_epoch_signature is not None
            and signature != self._last_pair_epoch_signature
        ):
            self._alignment_epoch += 1
        self._last_pair_epoch_signature = signature
        pair_sequence = self._pair_sequence + 1
        pair_identity = {
            "session_id": self._session_id,
            "sequence": pair_sequence,
            "admitted_at_monotonic_s": admitted_at,
        }
        pair_id = f"pair-{canonical_sha256(pair_identity)[:24]}"
        samples = (
            *self._samples_for(
                TwinStreamSide.OBSERVED,
                observed,
                source_timestamp_s=source_timestamp_s,
                source_epoch=observed_epoch,
                pair_id=pair_id,
                pair_sequence=pair_sequence,
                alignment_epoch=self._alignment_epoch,
            ),
            *self._samples_for(
                TwinStreamSide.PREDICTED,
                predicted,
                source_timestamp_s=source_timestamp_s,
                source_epoch=predicted_epoch,
                pair_id=pair_id,
                pair_sequence=pair_sequence,
                alignment_epoch=self._alignment_epoch,
            ),
        )
        if samples:
            batch = TwinIngestionBatch(session_id=self._session_id, samples=samples)
            # Durable compression and journal I/O are synchronous. Keep them off
            # the event loop so a retention write cannot stall 30 Hz live frames.
            await asyncio.to_thread(
                self._runtime.twins.ingest,
                batch,
            )
            # Publish retention counters together after the durable write; status
            # readers must never observe a completed cycle without its records.
            self._pair_sequence = pair_sequence
            self._sample_count += len(samples)
            self._latest_observed = observed
            self._latest_predicted = predicted
            self._last_pair_received_monotonic_s = admitted_at
            self._last_pair_source_timestamp_s = source_timestamp_s

    def _samples_for(
        self,
        side: TwinStreamSide,
        envelope: TelemetryEnvelope,
        *,
        source_timestamp_s: float,
        source_epoch: int,
        pair_id: str,
        pair_sequence: int,
        alignment_epoch: int,
    ) -> tuple[TwinStreamSample, ...]:
        assert self._session_id is not None
        source_clock_id = self._source_clock_id(side)
        values = self._channel_values(envelope)
        result: list[TwinStreamSample] = []
        raw_hash = canonical_sha256(envelope)
        vehicle_id = (
            self._observed_vehicle_id
            if side is TwinStreamSide.OBSERVED
            else self._predicted_vehicle_id
        )
        assert vehicle_id is not None
        for definition in default_twin_channels():
            value, availability, quality, source_frame = values[definition.channel_id]
            stream = (side, definition.channel_id)
            sequence = self._sequences.get(stream, 0) + 1
            self._sequences[stream] = sequence
            result.append(
                TwinStreamSample.create(
                    sample_id=f"pts-{secrets.token_hex(12)}",
                    session_id=self._session_id,
                    side=side,
                    vehicle_id=vehicle_id,
                    channel_id=definition.channel_id,
                    sequence=sequence,
                    pair_id=pair_id,
                    pair_sequence=pair_sequence,
                    alignment_epoch=alignment_epoch,
                    source_clock_id=source_clock_id,
                    source_epoch=source_epoch,
                    raw_source_timestamp_s=envelope.source_timestamp_s,
                    source_timestamp_s=source_timestamp_s,
                    received_timestamp_s=max(time.monotonic(), source_timestamp_s),
                    availability=availability,
                    quality=quality,
                    unit=definition.unit,
                    frame=definition.frame,
                    source_frame=source_frame,
                    value=value,
                    raw_payload_sha256=raw_hash,
                )
            )
        return tuple(result)

    @staticmethod
    def _all_measured_families_missing(envelope: TelemetryEnvelope) -> bool:
        telemetry = envelope.telemetry
        return all(
            value is None
            for value in (
                telemetry.position_m,
                telemetry.velocity_m_s,
                telemetry.attitude,
                telemetry.imu,
                telemetry.battery_voltage_v,
                telemetry.flow,
                telemetry.ranges,
                telemetry.estimator,
                telemetry.motor_pwm_percent,
            )
        )

    def _channel_values(
        self,
        envelope: TelemetryEnvelope,
    ) -> dict[
        str,
        tuple[object | None, TwinAvailability, TwinQuality, str | None],
    ]:
        telemetry = envelope.telemetry
        missing = (
            None,
            TwinAvailability.MISSING,
            TwinQuality.UNQUALIFIED,
            None,
        )
        values: dict[
            str,
            tuple[object | None, TwinAvailability, TwinQuality, str | None],
        ] = {definition.channel_id: missing for definition in default_twin_channels()}

        def available(
            value: object, source_frame: str | None = None
        ) -> tuple[object, TwinAvailability, TwinQuality, str | None]:
            return value, TwinAvailability.AVAILABLE, TwinQuality.GOOD, source_frame

        # The observed estimator and its private predictor both use the confirmed
        # HOME origin.  The common channel is WORLD, so retain the source frame and
        # make the incompatibility literal instead of relabelling coordinates.
        if telemetry.position_m is not None:
            values["pose.position"] = (
                None,
                TwinAvailability.INCOMPATIBLE,
                TwinQuality.UNQUALIFIED,
                CoordinateFrame.HOME.value,
            )
        if telemetry.velocity_m_s is not None:
            values["velocity.linear"] = (
                None,
                TwinAvailability.INCOMPATIBLE,
                TwinQuality.UNQUALIFIED,
                CoordinateFrame.HOME.value,
            )
        if telemetry.attitude is not None:
            values["attitude.euler"] = available(
                Vector3(
                    x=telemetry.attitude.roll_rad,
                    y=telemetry.attitude.pitch_rad,
                    z=telemetry.attitude.yaw_rad,
                ),
                CoordinateFrame.BODY.value,
            )
        if telemetry.imu is not None:
            values["imu.acceleration"] = available(
                telemetry.imu.acceleration_body_m_s2,
                CoordinateFrame.BODY.value,
            )
            values["imu.angular_velocity"] = available(
                telemetry.imu.angular_velocity_body_rad_s,
                CoordinateFrame.BODY.value,
            )
        if telemetry.battery_voltage_v is not None:
            values["battery.voltage"] = available(telemetry.battery_voltage_v, "vehicle")
        if telemetry.battery_current_a is not None:
            values["battery.current"] = available(telemetry.battery_current_a, "vehicle")
        battery_state = {
            "percent": telemetry.battery_percent,
            "cutoff_active": telemetry.battery_cutoff_active,
            "cutoff_reason": telemetry.battery_cutoff_reason,
            "current_limited": telemetry.powertrain_current_limited,
        }
        if any(value is not None for value in battery_state.values()):
            values["battery.state"] = available(self._json_value(battery_state), "vehicle")
        if telemetry.estimator is not None:
            values["estimator.health"] = available(
                self._json_value(telemetry.estimator.model_dump(mode="json")), "vehicle"
            )
        if telemetry.flow is not None:
            values["flow.state"] = available(
                self._json_value(telemetry.flow.model_dump(mode="json")),
                CoordinateFrame.BODY.value,
            )
        if telemetry.ranges is not None:
            values["range.state"] = available(
                self._json_value(telemetry.ranges.model_dump(mode="json")),
                CoordinateFrame.BODY.value,
            )
        if telemetry.transport is not None:
            values["transport.radio"] = available(
                self._json_value(telemetry.transport.model_dump(mode="json")),
                "transport",
            )
        values["safety.state"] = available(telemetry.state.value, "authority")

        if telemetry.motors is not None:
            readings = {reading.motor_id.lower(): reading for reading in telemetry.motors.readings}
            for index in range(1, 5):
                reading = readings[f"m{index}"]
                values[f"motor.m{index}.thrust"] = available(
                    reading.thrust_n, CoordinateFrame.BODY.value
                )
                if reading.applied_pwm_percent is not None:
                    values[f"motor.m{index}.pwm"] = available(
                        reading.applied_pwm_percent, CoordinateFrame.BODY.value
                    )
                values[f"motor.m{index}.state"] = available(
                    self._json_value(reading.model_dump(mode="json")),
                    CoordinateFrame.BODY.value,
                )
        elif telemetry.motor_pwm_percent is not None:
            for index, pwm_percent in enumerate(telemetry.motor_pwm_percent, start=1):
                values[f"motor.m{index}.pwm"] = available(
                    pwm_percent,
                    CoordinateFrame.BODY.value,
                )
        return values

    @staticmethod
    def _json_value(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def _source_status(self, side: TwinStreamSide) -> PhysicalTwinSourceStatus | None:
        if side is TwinStreamSide.OBSERVED and self._suspended:
            return self._operation_source_status()
        envelope = (
            self._latest_observed if side is TwinStreamSide.OBSERVED else self._latest_predicted
        )
        vehicle_id = (
            self._observed_vehicle_id
            if side is TwinStreamSide.OBSERVED
            else self._predicted_vehicle_id
        )
        if envelope is None or vehicle_id is None or self._session_id is None:
            return None
        source_clock_id = self._source_clock_id(side)
        clock = self._clock_maps.get((side, source_clock_id))
        last_received = (
            self._last_live_received_monotonic_s
            if side is TwinStreamSide.OBSERVED
            else self._last_pair_received_monotonic_s
        )
        freshness_period_s = (
            self.LIVE_SAMPLE_PERIOD_S if side is TwinStreamSide.OBSERVED else self.SAMPLE_PERIOD_S
        )
        freshness_timeout_s = max(
            freshness_period_s * 3,
            self._runtime.config.safety_envelope.telemetry_timeout_s,
        )
        freshness = (
            "MISSING"
            if last_received is None
            else "STALE"
            if time.monotonic() - last_received > freshness_timeout_s
            else "CURRENT"
        )
        source_class = (
            TwinSourceClass.TEST
            if self._test_transport
            else TwinSourceClass.MEASURED_REAL
            if side is TwinStreamSide.OBSERVED
            else TwinSourceClass.SIMULATED_MODEL
        )
        position = envelope.telemetry.position_m
        battery = envelope.telemetry.battery_voltage_v
        supervisor_known = "SUPERVISOR_STATE_UNKNOWN" not in envelope.telemetry.faults
        return PhysicalTwinSourceStatus(
            role=side.value,
            vehicle_id=vehicle_id,
            source_class=source_class,
            freshness=freshness,
            frame=CoordinateFrame.HOME,
            source_clock_id=source_clock_id,
            source_epoch=None if clock is None else clock.session_epoch,
            raw_source_timestamp_s=envelope.source_timestamp_s,
            source_timestamp_s=self._last_pair_source_timestamp_s,
            pair_sequence=self._pair_sequence or None,
            alignment_epoch=self._alignment_epoch if self._pair_sequence else None,
            position_availability=("MISSING" if position is None else "INCOMPATIBLE"),
            position_m=position,
            battery_availability="MISSING" if battery is None else "AVAILABLE",
            battery_voltage_v=battery,
            armed=envelope.telemetry.armed if supervisor_known else None,
            flying=envelope.telemetry.flying if supervisor_known else None,
            faults=envelope.telemetry.faults,
            attitude=envelope.telemetry.attitude,
            imu=envelope.telemetry.imu,
            flow=envelope.telemetry.flow,
            ranges=envelope.telemetry.ranges,
            estimator=envelope.telemetry.estimator,
            transport=envelope.telemetry.transport,
            motor_pwm_percent=envelope.telemetry.motor_pwm_percent,
            family_availability={
                "attitude": TwinAvailability.AVAILABLE
                if envelope.telemetry.attitude is not None
                else TwinAvailability.MISSING,
                "imu": TwinAvailability.AVAILABLE
                if envelope.telemetry.imu is not None
                else TwinAvailability.MISSING,
                "battery": TwinAvailability.AVAILABLE
                if battery is not None
                else TwinAvailability.MISSING,
                "flow": TwinAvailability.AVAILABLE
                if envelope.telemetry.flow is not None
                else TwinAvailability.MISSING,
                "ranges": TwinAvailability.AVAILABLE
                if envelope.telemetry.ranges is not None
                else TwinAvailability.MISSING,
                "estimator": TwinAvailability.AVAILABLE
                if envelope.telemetry.estimator is not None
                else TwinAvailability.MISSING,
                "transport": TwinAvailability.AVAILABLE
                if envelope.telemetry.transport is not None
                else TwinAvailability.MISSING,
                "motors": TwinAvailability.AVAILABLE
                if envelope.telemetry.motor_pwm_percent is not None
                else TwinAvailability.MISSING,
            },
        )

    def _operation_source_status(self) -> PhysicalTwinSourceStatus | None:
        envelope = self._latest_operation
        if envelope is None:
            return None
        last_received = self._last_operation_received_monotonic_s
        freshness_timeout_s = max(
            self.SAMPLE_PERIOD_S * 3,
            self._runtime.config.safety_envelope.telemetry_timeout_s,
        )
        freshness = (
            "MISSING"
            if last_received is None
            else "STALE"
            if time.monotonic() - last_received > freshness_timeout_s
            else "CURRENT"
        )
        telemetry = envelope.telemetry
        position = telemetry.position_m
        battery = telemetry.battery_voltage_v
        supervisor_known = "SUPERVISOR_STATE_UNKNOWN" not in telemetry.faults
        return PhysicalTwinSourceStatus(
            role="OBSERVED",
            vehicle_id=envelope.vehicle_id,
            source_class=(
                TwinSourceClass.TEST if self._test_transport else TwinSourceClass.MEASURED_REAL
            ),
            freshness=freshness,
            frame=telemetry.frame or CoordinateFrame.HOME,
            source_clock_id=envelope.source_clock_id,
            source_epoch=max(1, envelope.source_clock_epoch),
            raw_source_timestamp_s=envelope.source_timestamp_s,
            source_timestamp_s=envelope.source_timestamp_s,
            position_availability="MISSING" if position is None else "INCOMPATIBLE",
            position_m=position,
            battery_availability="MISSING" if battery is None else "AVAILABLE",
            battery_voltage_v=battery,
            armed=telemetry.armed if supervisor_known else None,
            flying=telemetry.flying if supervisor_known else None,
            faults=telemetry.faults,
            attitude=telemetry.attitude,
            imu=telemetry.imu,
            flow=telemetry.flow,
            ranges=telemetry.ranges,
            estimator=telemetry.estimator,
            transport=telemetry.transport,
            motor_pwm_percent=telemetry.motor_pwm_percent,
            family_availability={
                "attitude": TwinAvailability.AVAILABLE
                if telemetry.attitude is not None
                else TwinAvailability.MISSING,
                "imu": TwinAvailability.AVAILABLE
                if telemetry.imu is not None
                else TwinAvailability.MISSING,
                "battery": TwinAvailability.AVAILABLE
                if battery is not None
                else TwinAvailability.MISSING,
                "flow": TwinAvailability.AVAILABLE
                if telemetry.flow is not None
                else TwinAvailability.MISSING,
                "ranges": TwinAvailability.AVAILABLE
                if telemetry.ranges is not None
                else TwinAvailability.MISSING,
                "estimator": TwinAvailability.AVAILABLE
                if telemetry.estimator is not None
                else TwinAvailability.MISSING,
                "transport": TwinAvailability.AVAILABLE
                if telemetry.transport is not None
                else TwinAvailability.MISSING,
                "motors": TwinAvailability.AVAILABLE
                if telemetry.motor_pwm_percent is not None
                else TwinAvailability.MISSING,
            },
        )

    def _source_clock_id(self, side: TwinStreamSide) -> str:
        if self._test_transport:
            return "test-fixture"
        return "crazyflie-firmware" if side is TwinStreamSide.OBSERVED else "fast-sim-observer"

    def _advance_source_epoch(
        self,
        side: TwinStreamSide,
        envelope: TelemetryEnvelope,
        *,
        source_clock_id: str,
    ) -> int:
        key = (side, source_clock_id)
        raw = envelope.source_timestamp_s
        state = self._clock_maps.get(key)
        if state is None:
            state = _ClockMap(
                producer_epoch=envelope.source_clock_epoch,
                session_epoch=1,
                first_raw_s=raw,
                session_base_s=0.0,
                last_raw_s=raw,
                last_mapped_s=0.0,
            )
            self._clock_maps[key] = state
            return state.session_epoch
        if envelope.source_clock_epoch != state.producer_epoch or raw < state.last_raw_s:
            state.producer_epoch = envelope.source_clock_epoch
            state.session_epoch += 1
            state.first_raw_s = raw
        state.last_raw_s = raw
        return state.session_epoch

    def _admit_batch(self, admitted_at_monotonic_s: float) -> None:
        cutoff = admitted_at_monotonic_s - 1.0
        while self._batch_admission_times_s and self._batch_admission_times_s[0] <= cutoff:
            self._batch_admission_times_s.popleft()
        if len(self._batch_admission_times_s) >= 10:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "physical twin observer exceeds the 10 Hz service bound",
            )
        self._batch_admission_times_s.append(admitted_at_monotonic_s)

    async def _pause_pairing_adapters_locked(self, *, failed: bool) -> None:
        tasks = (self._stream_task, self._evidence_task)
        self._stream_task = None
        self._evidence_task = None
        current = asyncio.current_task()
        pending = tuple(task for task in tasks if task is not None and task is not current)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._session_id is not None:
            with suppress(CrazySwarmError):
                self._runtime.twins.complete(self._session_id, failed=failed)
        if self._predicted is not None:
            await self._predicted.disconnect()
            self._predicted = None
        self._close_live_streams()

    async def _disconnect_adapters_locked(self, *, failed: bool) -> None:
        await self._pause_pairing_adapters_locked(failed=failed)
        if self._facade is not None:
            try:
                await self._facade.disconnect()
            finally:
                self._facade = None

    def _clear_ephemeral(self) -> None:
        self._nonce = None
        self._nonce_deadline_s = 0.0
        self._observed_identity_sha256 = None
        self._first_observed = None
        self._session_id = None
        self._issues = ()
        self._sample_count = 0
        self._clock_maps.clear()
        self._sequences.clear()
        self._batch_admission_times_s.clear()
        self._observed_vehicle_id = None
        self._predicted_vehicle_id = None
        self._latest_observed = None
        self._latest_predicted = None
        self._last_pair_received_monotonic_s = None
        self._pair_origin_monotonic_s = None
        self._last_pair_source_timestamp_s = None
        self._pair_sequence = 0
        self._alignment_epoch = 1
        self._last_pair_epoch_signature = None
        self._last_live_received_monotonic_s = None
        self._stale_observation_since_monotonic_s = None
        self._paired_at_monotonic_s = None
        self._live_sequence = 0
        self._last_error_code = None
        self._last_error_message = None
        self._clear_operation_telemetry()

    def _clear_operation_telemetry(self) -> None:
        self._latest_operation = None
        self._last_operation_received_monotonic_s = None
        self._operation_sample_count = 0

    def _clear_failed_live_telemetry(self) -> None:
        self._latest_observed = None
        self._latest_predicted = None
        self._last_live_received_monotonic_s = None
        self._last_pair_received_monotonic_s = None
        self._last_pair_source_timestamp_s = None
        self._clear_operation_telemetry()

    def _clear_suspension(self) -> None:
        self._suspension_reason = None
        self._suspension_owner = None
        self._suspended_at_utc = None

    def _load_binding(self) -> None:
        if not self._binding_path.exists():
            return
        try:
            payload = json.loads(self._binding_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.BINDING_SCHEMA_VERSION:
                raise ValueError("unsupported binding schema")
            selected_uri = str(payload["selected_uri"])
            uri_hash = hashlib.sha256(selected_uri.encode()).hexdigest()
            if (
                payload.get("uri_sha256") != uri_hash
                or RADIO_URI_PATTERN.fullmatch(selected_uri) is None
            ):
                raise ValueError("binding identity is invalid")
            self._binding = _Binding(
                selected_uri=selected_uri,
                vehicle_label=str(payload["vehicle_label"]),
                uri_sha256=uri_hash,
                confirmed_identity_sha256=payload.get("confirmed_identity_sha256"),
                # Saving the exact URI is durable observation intent. Older releases
                # could persist that binding before capturing the first measured
                # identity; restart must still resume and finish automatic pairing.
                # Disconnect remains a process-local pause.
                auto_connect_enabled=True,
            )
            self._state = ObservationTwinState.DISCONNECTED
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self._binding = None
            self._state = ObservationTwinState.CONFIGURATION_INVALID
            self._last_error_code = "CONFIGURATION_INVALID"
            self._last_error_message = str(error)

    def _persist_binding(self) -> None:
        assert self._binding is not None
        self._binding_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._binding_path.with_suffix(f".tmp-{secrets.token_hex(6)}")
        payload = {
            "schema_version": self.BINDING_SCHEMA_VERSION,
            "selected_uri": self._binding.selected_uri,
            "vehicle_label": self._binding.vehicle_label,
            "uri_sha256": self._binding.uri_sha256,
            "confirmed_identity_sha256": self._binding.confirmed_identity_sha256,
            "auto_connect_enabled": self._binding.auto_connect_enabled,
        }
        try:
            temporary.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self._binding_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _redact_uri(uri: str) -> str:
        prefix, address = uri.rsplit("/", 1)
        return f"{prefix}/******{address[-4:]}"
