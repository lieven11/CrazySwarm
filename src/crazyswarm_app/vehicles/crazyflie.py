from __future__ import annotations

import asyncio
import math
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

from crazyswarm_app.domain.commands import (
    AbortCommand,
    AcknowledgementStatus,
    ArmCommand,
    BodyRateThrustCommand,
    CommandAcknowledgement,
    CommandEnvelope,
    DisarmCommand,
    EmergencyStopCommand,
    HoverCommand,
    LandCommand,
    MoveRelativeCommand,
    StopAndHoldCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    AuthorityClass,
    BackendRole,
    CommandCompletionMode,
    CoordinateFrame,
    DeckStatus,
    DeckType,
    EulerAttitude,
    HealthStatus,
    SourceClockPolicy,
    Vector3,
    VehicleBackendProfile,
    VehicleCapabilities,
    VehicleCapability,
    VehicleIdentity,
    VehicleState,
)
from crazyswarm_app.domain.simulation import AdapterContractManifest, canonical_sha256
from crazyswarm_app.domain.telemetry import (
    EstimatorReading,
    FlowReading,
    ImuReading,
    LocalizationSource,
    QuaternionAttitude,
    RangeReadings,
    RangeStatus,
    TelemetryEnvelope,
    TransportReading,
    VehicleTelemetry,
)
from crazyswarm_app.hardware.models import CommandPermit, PermitScope
from crazyswarm_app.vehicles.base import Vehicle
from crazyswarm_app.vehicles.crazyflie_link import (
    CrazyflieConnectionMetadata,
    CrazyflieLink,
    CrazyflieRawSample,
)

CRAZYFLIE_ADAPTER_VERSION = "1.0.0-preflight"
CRAZYFLIE_COMMAND_MAPPING_ID = "cf21-flow-hlc-relative-v1-provisional"
CFLIB_PIN = "0.1.32"
RADIO_URI_PATTERN = re.compile(r"^radio://[0-9]+/[0-9]{1,3}/(?:250K|1M|2M)/[A-Fa-f0-9]{10}$")

# These are adapter safety bounds for the deliberately slow, contained physical
# motions exposed by the Control Center. They are not controller gains and do not
# claim to qualify the aircraft dynamics. Each non-firmware condition must persist
# so asynchronous Crazyflie log groups and one noisy sample cannot stop a flight.
AIRBORNE_GUARD_FLOOR_PROXIMITY_M = 0.06
AIRBORNE_GUARD_MAX_TILT_RAD = math.radians(20.0)
AIRBORNE_GUARD_SATURATION_PWM_PERCENT = 95.0
AIRBORNE_GUARD_LOW_LOADED_VOLTAGE_V = 3.75
AIRBORNE_GUARD_FLOOR_PERSISTENCE_S = 0.30
AIRBORNE_GUARD_CONDITION_PERSISTENCE_S = 0.25


class _AirborneStabilityGuard:
    """Turn sustained measured loss of contained-flight stability into recovery."""

    def __init__(
        self,
        *,
        command_kind: str,
        grace_s: float = 0.0,
        floor_proximity_m: float = AIRBORNE_GUARD_FLOOR_PROXIMITY_M,
    ) -> None:
        self._command_kind = command_kind
        self._started_at_monotonic_s = time.monotonic()
        self._grace_s = max(0.0, grace_s)
        self._floor_proximity_m = max(0.0, floor_proximity_m)
        self._airborne_observed = False
        self._condition_started_at: dict[str, float] = {}

    def observe(self, sample: TelemetryEnvelope) -> None:
        telemetry = sample.telemetry
        now = time.monotonic()
        elapsed_s = now - self._started_at_monotonic_s
        if telemetry.flying:
            self._airborne_observed = True

        supervisor_faults = tuple(
            fault
            for fault in telemetry.faults
            if fault in {"SUPERVISOR_TUMBLED", "SUPERVISOR_CRASHED", "SUPERVISOR_LOCKED"}
        )
        if supervisor_faults:
            self._raise(
                "firmware_safety_fault",
                sample,
                observed={"faults": supervisor_faults},
            )
        if self._airborne_observed and not telemetry.flying:
            self._raise(
                "unexpected_grounded_state",
                sample,
                observed={"flying": telemetry.flying, "armed": telemetry.armed},
            )
        if not telemetry.flying or elapsed_s < self._grace_s:
            self._condition_started_at.clear()
            return

        position_z_m = None if telemetry.position_m is None else telemetry.position_m.z
        down_range_m = None if telemetry.ranges is None else telemetry.ranges.down_m
        available_heights = tuple(
            value for value in (position_z_m, down_range_m) if value is not None
        )
        near_floor = bool(available_heights) and min(available_heights) <= self._floor_proximity_m
        if self._sustained(
            "near_floor",
            near_floor,
            now,
            AIRBORNE_GUARD_FLOOR_PERSISTENCE_S,
        ):
            self._raise(
                "near_floor",
                sample,
                observed={
                    "position_z_m": position_z_m,
                    "down_range_m": down_range_m,
                    "minimum_admitted_height_m": self._floor_proximity_m,
                },
            )

        estimator_converged = (
            None if telemetry.estimator is None else telemetry.estimator.converged
        )
        if self._sustained(
            "estimator_unconverged",
            estimator_converged is not True,
            now,
            AIRBORNE_GUARD_CONDITION_PERSISTENCE_S,
        ):
            variance = (
                None
                if telemetry.estimator is None
                else telemetry.estimator.position_variance_m2
            )
            self._raise(
                "estimator_unconverged",
                sample,
                observed={
                    "estimator_converged": estimator_converged,
                    "position_variance_m2": (
                        None if variance is None else variance.model_dump(mode="json")
                    ),
                },
            )

        attitude = telemetry.attitude
        maximum_tilt_rad = (
            None
            if attitude is None
            else max(abs(attitude.roll_rad), abs(attitude.pitch_rad))
        )
        excessive_tilt = (
            maximum_tilt_rad is not None
            and maximum_tilt_rad >= AIRBORNE_GUARD_MAX_TILT_RAD
        )
        if self._sustained(
            "excessive_tilt",
            excessive_tilt,
            now,
            AIRBORNE_GUARD_CONDITION_PERSISTENCE_S,
        ):
            self._raise(
                "excessive_tilt",
                sample,
                observed={
                    "roll_rad": None if attitude is None else attitude.roll_rad,
                    "pitch_rad": None if attitude is None else attitude.pitch_rad,
                    "maximum_admitted_tilt_rad": AIRBORNE_GUARD_MAX_TILT_RAD,
                },
            )

        pwm = telemetry.motor_pwm_percent
        maximum_pwm_percent = None if pwm is None else max(pwm)
        loaded_voltage_v = telemetry.battery_voltage_v
        saturation_with_voltage_sag = (
            maximum_pwm_percent is not None
            and maximum_pwm_percent >= AIRBORNE_GUARD_SATURATION_PWM_PERCENT
            and loaded_voltage_v is not None
            and loaded_voltage_v <= AIRBORNE_GUARD_LOW_LOADED_VOLTAGE_V
        )
        if self._sustained(
            "actuator_saturation_with_voltage_sag",
            saturation_with_voltage_sag,
            now,
            AIRBORNE_GUARD_CONDITION_PERSISTENCE_S,
        ):
            self._raise(
                "actuator_saturation_with_voltage_sag",
                sample,
                observed={
                    "motor_pwm_percent": pwm,
                    "maximum_pwm_percent": maximum_pwm_percent,
                    "battery_voltage_v": loaded_voltage_v,
                    "saturation_threshold_percent": (
                        AIRBORNE_GUARD_SATURATION_PWM_PERCENT
                    ),
                    "loaded_voltage_threshold_v": (
                        AIRBORNE_GUARD_LOW_LOADED_VOLTAGE_V
                    ),
                },
            )

    def _sustained(
        self,
        condition: str,
        active: bool,
        now_monotonic_s: float,
        persistence_s: float,
    ) -> bool:
        if not active:
            self._condition_started_at.pop(condition, None)
            return False
        started = self._condition_started_at.setdefault(condition, now_monotonic_s)
        return now_monotonic_s - started >= persistence_s

    def _raise(
        self,
        trigger: str,
        sample: TelemetryEnvelope,
        *,
        observed: dict[str, object],
    ) -> None:
        transport = sample.telemetry.transport
        radio = None if transport is None else transport.radio
        raise CrazySwarmError(
            ErrorCode.PREFLIGHT_FAILED,
            "measured airborne stability guard requested abort and land",
            details={
                "trigger": trigger,
                "command_kind": self._command_kind,
                "source_timestamp_s": sample.source_timestamp_s,
                "observed": observed,
                "radio_transport": None if radio is None else radio.model_dump(mode="json"),
            },
        )


class CrazyflieVehicle(Vehicle):
    """Fail-closed Crazyflie 2.1+ Flow/Multi-ranger adapter.

    Construction is inert. ``connect`` uses only the exact URI supplied here and
    never scans. Command execution additionally requires a short-lived physical
    permit that matches both the vehicle identity and URI.
    """

    def __init__(
        self,
        *,
        vehicle_id: str,
        selected_uri: str,
        link: CrazyflieLink,
        expected_firmware_version: str | None = None,
        expected_controller: str | None = None,
        expected_estimator: str | None = None,
        minimum_protocol_version: int = 12,
        telemetry_period_s: float = 0.02,
        telemetry_timeout_s: float = 1.0,
        estimator_variance_limit_m2: float = 0.01,
        max_range_m: float = 4.0,
        observation_only: bool = False,
        telemetry_listener: Callable[[TelemetryEnvelope], None] | None = None,
    ) -> None:
        if not RADIO_URI_PATTERN.fullmatch(selected_uri):
            raise ValueError("selected_uri must be a full explicit Crazyradio URI")
        if telemetry_period_s <= 0.0:
            raise ValueError("telemetry_period_s must be positive")
        if estimator_variance_limit_m2 <= 0.0:
            raise ValueError("estimator variance limit must be positive")
        self._identity = VehicleIdentity(
            vehicle_id=vehicle_id,
            display_name=f"Crazyflie {vehicle_id}",
            adapter=f"crazyflie-cflib-{CRAZYFLIE_ADAPTER_VERSION}",
            radio_uri=selected_uri,
        )
        self._selected_uri = selected_uri
        self._link = link
        self._expected_firmware_version = expected_firmware_version
        self._expected_controller = expected_controller
        self._expected_estimator = expected_estimator
        self._minimum_protocol_version = minimum_protocol_version
        self._telemetry_period_s = telemetry_period_s
        self._telemetry_timeout_s = telemetry_timeout_s
        self._estimator_variance_limit_m2 = estimator_variance_limit_m2
        self._max_range_m = max_range_m
        self._observation_only = observation_only
        self._telemetry_listener = telemetry_listener
        self._owns_link = True
        self._command_readiness_issues: tuple[str, ...] = ()
        self._metadata: CrazyflieConnectionMetadata | None = None
        self._permit: CommandPermit | None = None
        self._latest_motor_pwm_percent: tuple[float, float, float, float] | None = None
        self._supervisor_auto_arming: bool | None = None
        self._sequence = 0
        # Producer epochs are one-based.  Every firmware-clock rollback starts a
        # new epoch; the unmodified raw timestamp remains visible to observers.
        self._source_epoch = 1
        self._last_source_timestamp_ms: int | None = None
        self._last_source_timestamp_s = 0.0
        self._latest = self._disconnected_sample()
        self._telemetry_history: deque[TelemetryEnvelope] = deque(maxlen=100_000)

    @property
    def identity(self) -> VehicleIdentity:
        return self._identity

    @property
    def capabilities(self) -> VehicleCapabilities:
        metadata = self._metadata
        flow_present = bool(metadata and metadata.deck_parameters.get("deck.bcFlow2"))
        multiranger_present = bool(metadata and metadata.deck_parameters.get("deck.bcMultiranger"))
        features = {
            VehicleCapability.ARMING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
            VehicleCapability.BODY_RATE_THRUST,
            VehicleCapability.PARAMETER_ACCESS,
            VehicleCapability.EMERGENCY_STOP,
        }
        if flow_present:
            features.add(VehicleCapability.RELATIVE_POSITIONING)
        if multiranger_present:
            features.add(VehicleCapability.RANGE_SENSING)
        return VehicleCapabilities(
            features=frozenset(features),
            decks=(
                DeckStatus(
                    deck_type=DeckType.FLOW,
                    name="Flow deck v2",
                    present=flow_present,
                    health=HealthStatus.HEALTHY if flow_present else HealthStatus.FAILED,
                    details={
                        "measured_parameter": "deck.bcFlow2",
                        "measured_value": (
                            None
                            if metadata is None
                            else metadata.deck_parameters.get("deck.bcFlow2")
                        ),
                    },
                ),
                DeckStatus(
                    deck_type=DeckType.MULTIRANGER,
                    name="Multi-ranger deck",
                    present=multiranger_present,
                    health=(HealthStatus.HEALTHY if multiranger_present else HealthStatus.FAILED),
                    details={
                        "measured_parameter": "deck.bcMultiranger",
                        "measured_value": (
                            None
                            if metadata is None
                            else metadata.deck_parameters.get("deck.bcMultiranger")
                        ),
                    },
                ),
            ),
        )

    @property
    def backend_profile(self) -> VehicleBackendProfile:
        return VehicleBackendProfile(
            role=BackendRole.REAL_CRAZYFLIE,
            authority=AuthorityClass.PHYSICAL,
            clock_policy=SourceClockPolicy.REALTIME_MONOTONIC,
            command_completion=CommandCompletionMode.BLOCKING_COMPLETION,
            supports_duration_aware_timeout=True,
            supports_source_clock_reset=True,
            supports_parameters=True,
            recommended_watchdog_period_s=0.02,
        )

    @property
    def contract_manifest(self) -> AdapterContractManifest:
        variables = (
            frozenset() if self._metadata is None else self._metadata.available_log_variables
        )
        return AdapterContractManifest(
            adapter_id=self.identity.adapter,
            supported_capabilities=self.capabilities.features,
            supported_signals=variables,
            supported_model_ids=frozenset(),
        )

    @property
    def execution_metadata(self) -> dict[str, str | int | float | None]:
        hardware_configuration = {
            "adapter_version": CRAZYFLIE_ADAPTER_VERSION,
            "command_mapping_id": CRAZYFLIE_COMMAND_MAPPING_ID,
            "cflib_pin": CFLIB_PIN,
            "selected_uri": self._selected_uri,
            "firmware_version": self.identity.firmware_version,
            "protocol_version": (
                None if self._metadata is None else self._metadata.protocol_version
            ),
            "deck_parameters": ({} if self._metadata is None else self._metadata.deck_parameters),
            "observed_parameters": (
                {} if self._metadata is None else self._metadata.observed_parameters
            ),
        }
        return {
            "vehicle_adapter": self.identity.adapter,
            "backend_role": self.backend_profile.role.value,
            "authority_class": self.backend_profile.authority.value,
            "physics_model_id": None,
            "physics_model_version": None,
            "physics_configuration_sha256": canonical_sha256(hardware_configuration),
            "scenario_id": None,
            "scenario_schema_version": None,
            "scenario_configuration_sha256": None,
            "simulation_seed": None,
            "simulation_fixed_step_s": None,
            "initial_state_sha256": None,
            "run_identity_sha256": None,
        }

    @property
    def connection_metadata(self) -> CrazyflieConnectionMetadata | None:
        """Measured identity for the currently attached physical link."""

        return self._metadata

    @property
    def connected(self) -> bool:
        return self._metadata is not None

    def borrow_connected_command_adapter(
        self,
        *,
        vehicle_id: str,
        telemetry_listener: Callable[[TelemetryEnvelope], None] | None = None,
    ) -> CrazyflieVehicle:
        """Create a command-capable view without reopening the physical link.

        The observer remains the sole owner of the cflib transport. Its sampling
        tasks are paused before this view is borrowed, so only one adapter reads
        or commands the shared session at a time. Disconnecting the borrowed view
        clears its permit and metadata but deliberately leaves the radio open for
        observation to resume.
        """

        metadata = self._metadata
        if metadata is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "Crazyflie is not connected")
        borrowed = CrazyflieVehicle(
            vehicle_id=vehicle_id,
            selected_uri=self._selected_uri,
            link=self._link,
            expected_firmware_version=self._expected_firmware_version,
            expected_controller=self._expected_controller,
            expected_estimator=self._expected_estimator,
            minimum_protocol_version=self._minimum_protocol_version,
            telemetry_period_s=self._telemetry_period_s,
            telemetry_timeout_s=self._telemetry_timeout_s,
            estimator_variance_limit_m2=self._estimator_variance_limit_m2,
            max_range_m=self._max_range_m,
            telemetry_listener=telemetry_listener,
        )
        # Observation tolerates partially qualified firmware so operators can
        # inspect it, but borrowing authority must satisfy the full command
        # contract exactly as a fresh command connection would.
        borrowed._validate_connection(metadata)
        borrowed._metadata = metadata
        borrowed._identity = borrowed._identity.model_copy(
            update={"firmware_version": metadata.firmware_version}
        )
        borrowed._owns_link = False
        borrowed._supervisor_auto_arming = self._supervisor_auto_arming
        borrowed._source_epoch = self._source_epoch
        borrowed._last_source_timestamp_ms = self._last_source_timestamp_ms
        borrowed._last_source_timestamp_s = self._last_source_timestamp_s
        return borrowed

    @property
    def command_readiness_issues(self) -> tuple[str, ...]:
        return self._command_readiness_issues

    @property
    def telemetry_history(self) -> tuple[TelemetryEnvelope, ...]:
        """Measured samples read by command completion and preflight polling."""

        return tuple(self._telemetry_history)

    def install_command_permit(self, permit: CommandPermit) -> None:
        if self._observation_only:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "observation-only Crazyflie adapters cannot accept command permits",
            )
        if permit.vehicle_id != self.identity.vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "permit vehicle mismatch")
        if permit.selected_uri != self._selected_uri:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "permit URI mismatch")
        self._permit = permit

    def clear_command_permit(self) -> None:
        self._permit = None

    @property
    def latest_motor_pwm_percent(self) -> tuple[float, float, float, float] | None:
        return self._latest_motor_pwm_percent

    @property
    def supervisor_auto_arming(self) -> bool | None:
        """Whether firmware automatically arms this grounded Crazyflie.

        Crazyflie 2.1 brushed builds enable automatic arming by default.  In
        that mode ``armed=true`` is a configuration-backed ready state and a
        host disarm request is immediately reversed by the firmware.
        """

        return self._supervisor_auto_arming

    async def restart_observation_telemetry(self) -> TelemetryEnvelope:
        """Repair stale firmware logs without changing radio or command authority."""

        if not self._observation_only:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "in-place telemetry repair is restricted to the observation-only adapter",
            )
        if self._metadata is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "Crazyflie is not connected")
        try:
            await asyncio.to_thread(self._link.restart_observation_logs)
            return await self.snapshot()
        except Exception as error:
            raise CrazySwarmError(
                ErrorCode.TELEMETRY_STALE,
                "Crazyflie firmware log restart did not restore fresh telemetry",
                details={"error": str(error)},
            ) from error

    async def recover_from_crash(self) -> TelemetryEnvelope:
        if self._metadata is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "Crazyflie is not connected")
        await asyncio.to_thread(self._link.recover_from_crash)
        await asyncio.sleep(0.1)
        return await self.snapshot()

    async def begin_motor_bench(self, motor_selection: str) -> None:
        self._require_bench_permit()
        await asyncio.to_thread(self._link.begin_motor_power_override, motor_selection)

    async def set_motor_bench_power(self, motor_selection: str, percent: float) -> None:
        self._require_bench_permit()
        await asyncio.to_thread(
            self._link.set_motor_power_percent,
            motor_selection,
            percent,
        )

    async def feed_motor_bench_watchdog(self) -> None:
        self._require_bench_permit()
        await asyncio.to_thread(self._link.feed_motor_watchdog)

    async def end_motor_bench(self) -> None:
        await asyncio.to_thread(self._link.end_motor_power_override)

    def _require_bench_permit(self) -> None:
        permit = self._permit
        if (
            permit is None
            or permit.scope is not PermitScope.PROPS_OFF_BENCH
            or not permit.operator_present
            or not permit.props_removed
            or not permit.physically_restrained
            or datetime.now(UTC) >= permit.expires_at_utc
            or permit.vehicle_id != self.identity.vehicle_id
            or permit.selected_uri != self._selected_uri
        ):
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "motor control requires an active props-off bench permit",
            )

    async def reset_estimator(self, *, timeout_s: float = 10.0) -> TelemetryEnvelope:
        if self._observation_only:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "observation-only Crazyflie adapters cannot reset the estimator",
            )
        if self._metadata is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "Crazyflie is not connected")
        await asyncio.to_thread(self._link.reset_estimator)
        deadline = time.monotonic() + timeout_s
        consecutive = 0
        latest = await self.snapshot()
        while time.monotonic() < deadline:
            latest = await self.snapshot()
            estimator = latest.telemetry.estimator
            if estimator is not None and estimator.converged is True:
                consecutive += 1
                if consecutive >= 5:
                    return latest
            else:
                consecutive = 0
            await asyncio.sleep(0.1)
        raise CrazySwarmError(
            ErrorCode.PREFLIGHT_FAILED,
            "Crazyflie estimator did not converge after reset",
            details={"timeout_s": timeout_s},
        )

    async def connect(self) -> None:
        if self._metadata is not None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "Crazyflie is already connected")
        try:
            metadata = await asyncio.to_thread(self._link.connect, self._selected_uri)
        except Exception as error:
            raise CrazySwarmError(
                ErrorCode.LINK_LOST,
                "failed to connect to the explicitly selected Crazyflie URI",
                details={"selected_uri": self._selected_uri, "error": str(error)},
            ) from error
        try:
            self._validate_connection(metadata)
        except Exception:
            await asyncio.to_thread(self._link.disconnect)
            raise
        self._metadata = metadata
        self._identity = self._identity.model_copy(
            update={"firmware_version": metadata.firmware_version}
        )
        self._sequence = 0
        self._source_epoch = 1
        self._last_source_timestamp_ms = None
        self._telemetry_history.clear()
        try:
            # A successful observation connection includes one parseable sample;
            # transport metadata alone is not enough to confirm the device.
            self._latest = await self.snapshot()
        except Exception:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        try:
            if self._owns_link:
                await asyncio.to_thread(self._link.disconnect)
        finally:
            self._metadata = None
            self._permit = None
            self._latest = self._disconnected_sample()

    async def execute(self, command: CommandEnvelope) -> CommandAcknowledgement:
        if self._observation_only:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "observation-only Crazyflie adapters cannot execute commands",
            )
        if command.vehicle_id != self.identity.vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Crazyflie command target mismatch")
        if self._metadata is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "Crazyflie is not connected")
        self._require_permit(command)
        received = time.monotonic()
        dispatched = False
        try:
            payload = command.payload
            if isinstance(payload, ArmCommand):
                dispatched = True
                await asyncio.to_thread(self._link.request_arm, True)
                await self._wait_for_supervisor(armed=True, timeout_s=1.5)
            elif isinstance(payload, DisarmCommand):
                dispatched = True
                await asyncio.to_thread(self._link.request_arm, False)
                await self._wait_for_supervisor(armed=False, timeout_s=1.5)
            elif isinstance(payload, TakeoffCommand):
                dispatched = True
                await asyncio.to_thread(
                    self._link.takeoff,
                    payload.height_m,
                    payload.duration_s,
                    payload.yaw_rad,
                )
                await self._wait_duration_and_refresh(
                    payload.duration_s,
                    stability_guard=_AirborneStabilityGuard(
                        command_kind=payload.kind.value,
                        grace_s=min(0.75, payload.duration_s * 0.5),
                        floor_proximity_m=min(
                            AIRBORNE_GUARD_FLOOR_PROXIMITY_M,
                            payload.height_m * 0.25,
                        ),
                    ),
                )
            elif isinstance(payload, HoverCommand):
                dispatched = True
                await asyncio.to_thread(self._link.hold_position, payload.duration_s)
                await self._wait_duration_and_refresh(
                    payload.duration_s,
                    stability_guard=_AirborneStabilityGuard(command_kind=payload.kind.value),
                )
            elif isinstance(payload, MoveRelativeCommand):
                x_m, y_m = self._home_frame_displacement(payload)
                dispatched = True
                await asyncio.to_thread(
                    self._link.go_to_relative,
                    x_m,
                    y_m,
                    payload.z_m,
                    payload.yaw_rad,
                    payload.duration_s,
                )
                await self._wait_duration_and_refresh(
                    payload.duration_s,
                    stability_guard=_AirborneStabilityGuard(command_kind=payload.kind.value),
                )
            elif isinstance(payload, BodyRateThrustCommand):
                dispatched = True
                await self._execute_body_rate_thrust(payload)
            elif isinstance(payload, StopAndHoldCommand):
                dispatched = True
                await asyncio.to_thread(self._link.hold_position, 0.25)
                await self._wait_duration_and_refresh(
                    0.25,
                    stability_guard=_AirborneStabilityGuard(command_kind=payload.kind.value),
                )
            elif isinstance(payload, LandCommand):
                dispatched = True
                await asyncio.to_thread(
                    self._link.land,
                    payload.target_height_m,
                    payload.duration_s,
                )
                await self._wait_duration_and_refresh(payload.duration_s)
            elif isinstance(payload, AbortCommand):
                dispatched = True
                await asyncio.to_thread(self._link.land, 0.0, 2.0)
                await self._wait_duration_and_refresh(2.0)
            elif isinstance(payload, EmergencyStopCommand):
                dispatched = True
                await asyncio.to_thread(self._link.emergency_stop)
                await self._wait_for_supervisor(armed=False, timeout_s=1.0)
            else:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    f"unsupported physical command: {payload.kind.value}",
                )
        except CrazySwarmError as error:
            if dispatched and error.code in {ErrorCode.LINK_LOST, ErrorCode.TELEMETRY_STALE}:
                raise self._unknown_outcome(command, error) from error
            raise
        except Exception as error:
            if dispatched:
                raise self._unknown_outcome(command, error) from error
            raise
        completed = time.monotonic()
        return CommandAcknowledgement(
            vehicle_id=self.identity.vehicle_id,
            command_id=command.command_id,
            status=AcknowledgementStatus.COMPLETED,
            received_at_monotonic_s=received,
            completed_at_monotonic_s=completed,
        )

    async def _execute_body_rate_thrust(self, payload: BodyRateThrustCommand) -> None:
        """Stream a finite rate profile while enforcing its measured HOME XY box."""

        reference_sample = await self.snapshot(poll_supervisor=False)
        reference = payload.xy_reference_m or reference_sample.telemetry.position_m
        if reference is None:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "Body-rate flight requires a current position estimate",
            )
        stream_task = asyncio.create_task(
            asyncio.to_thread(
                self._link.stream_body_rate_thrust,
                payload.setpoints,
                payload.sample_period_s,
            ),
            name=f"body-rate-stream-{payload.profile_id}",
        )
        try:
            while not stream_task.done():
                done, _ = await asyncio.wait({stream_task}, timeout=0.02)
                if done:
                    break
                sample = await self.snapshot(poll_supervisor=False)
                position = sample.telemetry.position_m
                if position is None:
                    raise CrazySwarmError(
                        ErrorCode.TELEMETRY_STALE,
                        "Body-rate containment lost the current position estimate",
                    )
                dx_m = position.x - reference.x
                dy_m = position.y - reference.y
                if (
                    abs(dx_m) > payload.max_abs_xy_displacement_m
                    or abs(dy_m) > payload.max_abs_xy_displacement_m
                ):
                    raise CrazySwarmError(
                        ErrorCode.PREFLIGHT_FAILED,
                        "Body-rate stream left its measured HOME XY containment box",
                        details={
                            "dx_m": dx_m,
                            "dy_m": dy_m,
                            "max_abs_xy_displacement_m": payload.max_abs_xy_displacement_m,
                        },
                    )
            await stream_task
        except BaseException:
            if not stream_task.done():
                with suppress(Exception):
                    await asyncio.to_thread(self._link.cancel_body_rate_thrust)
                with suppress(Exception):
                    await stream_task
            raise

    async def snapshot(self, *, poll_supervisor: bool = True) -> TelemetryEnvelope:
        if self._metadata is None:
            return self._latest
        try:
            reader = self._link.read_sample
            if self._observation_only or not poll_supervisor:
                reader = getattr(self._link, "read_observation_sample", reader)
            raw = await asyncio.to_thread(reader)
        except Exception as error:
            raise CrazySwarmError(
                ErrorCode.LINK_LOST,
                "Crazyflie telemetry is unavailable",
                details={"error": str(error)},
            ) from error
        telemetry_age_s = time.monotonic() - raw.received_at_monotonic_s
        if telemetry_age_s > self._telemetry_timeout_s:
            details: dict[str, object] = {
                "telemetry_age_s": telemetry_age_s,
                "telemetry_timeout_s": self._telemetry_timeout_s,
            }
            if raw.radio_transport is not None:
                # Preserve the measured transport boundary that accompanied the
                # stale log sample. The observer can then distinguish an RF fade
                # from a healthy-ACK firmware log stall before reconnecting.
                details["radio_transport"] = raw.radio_transport.model_dump(mode="json")
            raise CrazySwarmError(
                ErrorCode.TELEMETRY_STALE,
                "Crazyflie telemetry stopped updating",
                details=details,
            )
        envelope = self._normalize(raw)
        self._latest = envelope
        self._telemetry_history.append(envelope)
        self._sequence += 1
        if self._telemetry_listener is not None:
            # Presentation telemetry must never interrupt command completion
            # or the safety path that owns this measured sample.
            with suppress(Exception):
                self._telemetry_listener(envelope)
        return envelope

    async def cancel_body_rate_thrust(self) -> None:
        """Release an in-progress manual rate stream before a recovery command."""

        if self._metadata is None:
            return
        await asyncio.to_thread(self._link.cancel_body_rate_thrust)

    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryEnvelope]:
        while self._metadata is not None:
            yield await self.snapshot()
            await asyncio.sleep(self._telemetry_period_s)

    def _validate_connection(self, metadata: CrazyflieConnectionMetadata) -> None:
        if (
            metadata.selected_uri != self._selected_uri
            or metadata.connected_uri != self._selected_uri
        ):
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "connected Crazyflie URI does not match the explicit selection",
            )
        if self._observation_only:
            self._command_readiness_issues = self._collect_command_readiness_issues(metadata)
            return
        if (
            metadata.protocol_version is None
            or metadata.protocol_version < self._minimum_protocol_version
        ):
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "Crazyflie firmware protocol is too old for verified supervisor state",
                details={
                    "observed_protocol": metadata.protocol_version,
                    "required_protocol": self._minimum_protocol_version,
                },
            )
        missing = [
            name
            for name in ("deck.bcFlow2", "deck.bcMultiranger")
            if not metadata.deck_parameters.get(name)
        ]
        if missing:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "required Crazyflie decks were not measured as present",
                details={"missing_deck_parameters": missing},
            )
        if "supervisor.info" not in metadata.available_log_variables:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "required Crazyflie supervisor telemetry is unavailable",
                details={"missing_log_variable": "supervisor.info"},
            )
        self._require_parameter_pin(
            metadata,
            "stabilizer.controller",
            self._expected_controller,
        )
        self._require_parameter_pin(
            metadata,
            "stabilizer.estimator",
            self._expected_estimator,
        )
        if (
            self._expected_firmware_version is not None
            and metadata.firmware_version != self._expected_firmware_version
        ):
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "Crazyflie firmware does not match the pinned version",
                details={
                    "expected": self._expected_firmware_version,
                    "observed": metadata.firmware_version,
                },
            )
        try:
            installed_cflib = version("cflib")
        except PackageNotFoundError as error:
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "cflib is not installed") from error
        if installed_cflib != CFLIB_PIN:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "installed cflib does not match the qualification pin",
                details={"expected": CFLIB_PIN, "observed": installed_cflib},
            )

    def _collect_command_readiness_issues(
        self, metadata: CrazyflieConnectionMetadata
    ) -> tuple[str, ...]:
        """Report flight-preflight gaps without blocking read-only observation."""

        issues: list[str] = []
        if (
            metadata.protocol_version is None
            or metadata.protocol_version < self._minimum_protocol_version
        ):
            issues.append("PROTOCOL_UNQUALIFIED")
        for name in ("deck.bcFlow2", "deck.bcMultiranger"):
            if not metadata.deck_parameters.get(name):
                issues.append(f"MISSING_{name.upper().replace('.', '_')}")
        for name, expected in (
            ("stabilizer.controller", self._expected_controller),
            ("stabilizer.estimator", self._expected_estimator),
        ):
            observed = metadata.observed_parameters.get(name)
            if observed is None or (expected is not None and observed != expected):
                issues.append(f"PARAMETER_{name.upper().replace('.', '_')}_UNQUALIFIED")
        if (
            self._expected_firmware_version is not None
            and metadata.firmware_version != self._expected_firmware_version
        ):
            issues.append("FIRMWARE_UNQUALIFIED")
        try:
            installed_cflib = version("cflib")
        except PackageNotFoundError:
            issues.append("CFLIB_UNAVAILABLE")
        else:
            if installed_cflib != CFLIB_PIN:
                issues.append("CFLIB_VERSION_UNQUALIFIED")
        return tuple(issues)

    @staticmethod
    def _require_parameter_pin(
        metadata: CrazyflieConnectionMetadata,
        name: str,
        expected: str | None,
    ) -> None:
        observed = metadata.observed_parameters.get(name)
        if observed is None:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                f"required Crazyflie parameter is unavailable: {name}",
            )
        if expected is not None and observed != expected:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                f"Crazyflie parameter does not match the qualification pin: {name}",
                details={"parameter": name, "expected": expected, "observed": observed},
            )

    def _require_permit(self, command: CommandEnvelope) -> None:
        permit = self._permit
        if permit is None or not permit.allows(
            command.payload.kind,
            vehicle_id=self.identity.vehicle_id,
            selected_uri=self._selected_uri,
        ):
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "physical command requires a matching, unexpired hardware permit",
                details={"command": command.payload.kind.value},
            )

    @staticmethod
    def _unknown_outcome(
        command: CommandEnvelope,
        error: Exception,
    ) -> CrazySwarmError:
        return CrazySwarmError(
            ErrorCode.LINK_LOST,
            "physical command outcome is unknown; automatic retry is forbidden",
            details={
                "command_id": command.command_id,
                "command_outcome": AcknowledgementStatus.UNKNOWN_OUTCOME.value,
                "automatic_retry_safe": False,
                "error": str(error),
            },
        )

    async def _wait_for_supervisor(self, *, armed: bool, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            sample = await self.snapshot()
            if (
                "SUPERVISOR_STATE_UNKNOWN" not in sample.telemetry.faults
                and sample.telemetry.armed is armed
            ):
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("supervisor state did not confirm the command")
            await asyncio.sleep(0.02)

    async def _wait_duration_and_refresh(
        self,
        duration_s: float,
        *,
        stability_guard: _AirborneStabilityGuard | None = None,
    ) -> None:
        deadline = time.monotonic() + duration_s
        while True:
            sample = await self.snapshot()
            if stability_guard is not None:
                stability_guard.observe(sample)
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return
            await asyncio.sleep(min(self._telemetry_period_s, remaining))

    def _home_frame_displacement(self, payload: MoveRelativeCommand) -> tuple[float, float]:
        if payload.frame is CoordinateFrame.HOME:
            return payload.x_m, payload.y_m
        attitude = self._latest.telemetry.attitude
        if attitude is None:
            raise CrazySwarmError(
                ErrorCode.LOCALIZATION_INVALID,
                "BODY-frame move requires a fresh measured yaw",
            )
        yaw = attitude.yaw_rad
        return (
            payload.x_m * math.cos(yaw) - payload.y_m * math.sin(yaw),
            payload.x_m * math.sin(yaw) + payload.y_m * math.cos(yaw),
        )

    def _normalize(self, raw: CrazyflieRawSample) -> TelemetryEnvelope:
        if not raw.connected:
            raise CrazySwarmError(ErrorCode.LINK_LOST, "Crazyflie link reports disconnected")
        source_timestamp_s = self._source_time(raw.source_timestamp_ms)
        values = raw.values
        motor_names = tuple(f"motor.m{index}" for index in range(1, 5))
        motor_pwm = tuple(self._optional(values, name) for name in motor_names)
        motor_timestamps = raw.value_received_at_monotonic_s
        motor_values_are_fresh = not motor_timestamps or (
            all(name in motor_timestamps for name in motor_names)
            and time.monotonic()
            - min(motor_timestamps[name] for name in motor_names)
            <= self._telemetry_timeout_s
        )
        if all(value is not None for value in motor_pwm) and motor_values_are_fresh:
            m1, m2, m3, m4 = motor_pwm
            assert m1 is not None and m2 is not None and m3 is not None and m4 is not None
            self._latest_motor_pwm_percent = (
                m1 / 65_535.0 * 100.0,
                m2 / 65_535.0 * 100.0,
                m3 / 65_535.0 * 100.0,
                m4 / 65_535.0 * 100.0,
            )
        else:
            self._latest_motor_pwm_percent = None
        position = self._vector(values, "stateEstimate.x", "stateEstimate.y", "stateEstimate.z")
        velocity = self._vector(
            values,
            "stateEstimate.vx",
            "stateEstimate.vy",
            "stateEstimate.vz",
        )
        attitude = self._attitude(values)
        quaternion = self._quaternion(values)
        variances = self._vector(values, "kalman.varPX", "kalman.varPY", "kalman.varPZ")
        quality, converged = self._estimator_quality(variances)
        supervisor_known = raw.supervisor_bitfield is not None
        bitfield = 0 if raw.supervisor_bitfield is None else raw.supervisor_bitfield
        self._supervisor_auto_arming = bool(bitfield & (1 << 2)) if supervisor_known else None
        armed = bool(bitfield & (1 << 1))
        flying = bool(bitfield & (1 << 4))
        state = (
            VehicleState.FLYING
            if flying
            else VehicleState.READY
            if supervisor_known
            else VehicleState.FAULT
        )
        faults = list(raw.log_errors)
        if not supervisor_known:
            faults.append("SUPERVISOR_STATE_UNKNOWN")
        if bitfield & (1 << 5):
            faults.append("SUPERVISOR_TUMBLED")
        if bitfield & (1 << 6):
            faults.append("SUPERVISOR_LOCKED")
        if bitfield & (1 << 7):
            faults.append("SUPERVISOR_CRASHED")
        telemetry = VehicleTelemetry(
            state=state,
            armed=armed,
            flying=flying,
            position_m=position,
            velocity_m_s=velocity,
            attitude=attitude,
            quaternion=quaternion,
            frame=(CoordinateFrame.HOME if position is not None else None),
            position_is_estimate=(True if position is not None else None),
            localization_source=LocalizationSource.FLOW,
            localization_quality_percent=quality,
            battery_percent=self._optional(values, "pm.batteryLevel"),
            battery_voltage_v=self._optional(values, "pm.vbat"),
            link_quality_percent=raw.link_quality_percent,
            link_latency_ms=raw.link_latency_ms,
            packet_loss_percent=(
                None
                if raw.radio_transport is None
                else raw.radio_transport.packet_loss_percent
            ),
            transport=TransportReading(
                kind="physical_radio",
                source_class="MEASURED_REAL",
                delivery_quality_percent=(
                    None
                    if raw.radio_transport is None
                    or raw.radio_transport.packet_loss_percent is None
                    else 100.0 - raw.radio_transport.packet_loss_percent
                ),
                latency_ms=raw.link_latency_ms,
                packet_loss_percent=(
                    None
                    if raw.radio_transport is None
                    else raw.radio_transport.packet_loss_percent
                ),
                radio=raw.radio_transport,
            ),
            capabilities=self.capabilities,
            imu=self._imu(values),
            estimator=(
                EstimatorReading(
                    position_variance_m2=variances,
                    converged=converged,
                    quality_metric_id="kalman-position-variance-linear-v1",
                )
                if variances is not None
                else None
            ),
            flow=self._flow(values, velocity, attitude),
            ranges=self._ranges(values, source_timestamp_s),
            motor_pwm_percent=self._latest_motor_pwm_percent,
            motors=None,
            faults=tuple(faults),
        )
        received = max(raw.received_at_monotonic_s, source_timestamp_s)
        return TelemetryEnvelope(
            vehicle_id=self.identity.vehicle_id,
            sequence=self._sequence,
            source_timestamp_s=source_timestamp_s,
            received_timestamp_s=received,
            source_clock_id="crazyflie-firmware",
            source_clock_epoch=self._source_epoch,
            recorded_at_utc=datetime.now(UTC),
            telemetry=telemetry,
        )

    def _source_time(self, timestamp_ms: int) -> float:
        previous = self._last_source_timestamp_ms
        if previous is not None and timestamp_ms < previous:
            self._source_epoch += 1
            self._last_source_timestamp_s = 0.0
        source_s = timestamp_ms / 1_000.0
        self._last_source_timestamp_ms = timestamp_ms
        self._last_source_timestamp_s = source_s
        return source_s

    def _estimator_quality(self, variance: Vector3 | None) -> tuple[float | None, bool | None]:
        if variance is None:
            return None, None
        maximum = max(variance.x, variance.y, variance.z)
        quality = max(0.0, min(100.0, 100.0 * (1.0 - maximum / self._estimator_variance_limit_m2)))
        return quality, maximum <= self._estimator_variance_limit_m2

    @staticmethod
    def _optional(values: dict[str, float], name: str) -> float | None:
        value = values.get(name)
        return value if value is not None and math.isfinite(value) else None

    @classmethod
    def _vector(cls, values: dict[str, float], x: str, y: str, z: str) -> Vector3 | None:
        components = (cls._optional(values, x), cls._optional(values, y), cls._optional(values, z))
        if any(value is None for value in components):
            return None
        return Vector3(x=components[0], y=components[1], z=components[2])

    @classmethod
    def _attitude(cls, values: dict[str, float]) -> EulerAttitude | None:
        degrees = cls._vector(values, "stabilizer.roll", "stabilizer.pitch", "stabilizer.yaw")
        if degrees is None:
            return None
        return EulerAttitude(
            roll_rad=math.radians(degrees.x),
            pitch_rad=math.radians(degrees.y),
            yaw_rad=math.radians(degrees.z),
        )

    @classmethod
    def _quaternion(cls, values: dict[str, float]) -> QuaternionAttitude | None:
        names = ("stateEstimate.qw", "stateEstimate.qx", "stateEstimate.qy", "stateEstimate.qz")
        components = tuple(cls._optional(values, name) for name in names)
        if any(value is None for value in components):
            return None
        # The firmware log can publish one or more all-zero startup samples
        # before the estimator has initialized its quaternion. Zero is a
        # missing-value sentinel, not an orientation, and must not terminate
        # the otherwise healthy observer stream.
        if sum(value * value for value in components if value is not None) <= 1e-24:
            return None
        return QuaternionAttitude(
            w=components[0], x=components[1], y=components[2], z=components[3]
        )

    @classmethod
    def _imu(cls, values: dict[str, float]) -> ImuReading | None:
        acceleration_g = cls._vector(values, "acc.x", "acc.y", "acc.z")
        angular_degrees = cls._vector(values, "gyro.x", "gyro.y", "gyro.z")
        if acceleration_g is None or angular_degrees is None:
            return None
        return ImuReading(
            acceleration_body_m_s2=Vector3(
                x=acceleration_g.x * 9.80665,
                y=acceleration_g.y * 9.80665,
                z=acceleration_g.z * 9.80665,
            ),
            angular_velocity_body_rad_s=Vector3(
                x=math.radians(angular_degrees.x),
                y=math.radians(angular_degrees.y),
                z=math.radians(angular_degrees.z),
            ),
        )

    def _flow(
        self,
        values: dict[str, float],
        world_velocity: Vector3 | None,
        attitude: EulerAttitude | None,
    ) -> FlowReading | None:
        quality_raw = self._optional(values, "motion.squal")
        ground_mm = self._optional(values, "range.zrange")
        if quality_raw is None and ground_mm is None:
            return None
        body_velocity: Vector3 | None = None
        if world_velocity is not None and attitude is not None:
            yaw = attitude.yaw_rad
            body_velocity = Vector3(
                x=world_velocity.x * math.cos(yaw) + world_velocity.y * math.sin(yaw),
                y=-world_velocity.x * math.sin(yaw) + world_velocity.y * math.cos(yaw),
                z=world_velocity.z,
            )
        return FlowReading(
            velocity_body_m_s=body_velocity,
            ground_distance_m=None if ground_mm is None else ground_mm / 1_000.0,
            quality_percent=(
                0.0 if quality_raw is None else max(0.0, min(100.0, quality_raw / 255.0 * 100.0))
            ),
        )

    def _ranges(self, values: dict[str, float], source_timestamp_s: float) -> RangeReadings | None:
        names = {
            "front": "range.front",
            "back": "range.back",
            "left": "range.left",
            "right": "range.right",
            "up": "range.up",
            "down": "range.zrange",
        }
        measured = {direction: self._optional(values, name) for direction, name in names.items()}
        if all(value is None for value in measured.values()):
            return None
        distances: dict[str, float | None] = {}
        statuses: dict[str, RangeStatus] = {}
        for direction, millimeters in measured.items():
            if millimeters is None:
                distances[direction] = None
                statuses[direction] = RangeStatus.UNAVAILABLE
                continue
            meters = millimeters / 1_000.0
            if meters >= self._max_range_m:
                distances[direction] = None
                statuses[direction] = RangeStatus.NO_HIT
            else:
                distances[direction] = max(0.0, meters)
                statuses[direction] = RangeStatus.VALID
        return RangeReadings(
            front_m=distances["front"],
            back_m=distances["back"],
            left_m=distances["left"],
            right_m=distances["right"],
            up_m=distances["up"],
            down_m=distances["down"],
            max_range_m=self._max_range_m,
            statuses=statuses,
            source_timestamp_s=source_timestamp_s,
        )

    def _disconnected_sample(self) -> TelemetryEnvelope:
        now = time.monotonic()
        return TelemetryEnvelope(
            vehicle_id=self.identity.vehicle_id,
            sequence=self._sequence,
            source_timestamp_s=now,
            received_timestamp_s=now,
            source_clock_id=f"cf-host-{self.identity.vehicle_id}",
            source_clock_epoch=self._source_epoch,
            telemetry=VehicleTelemetry(state=VehicleState.DISCONNECTED),
        )
