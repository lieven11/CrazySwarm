from __future__ import annotations

import hashlib
import importlib
import json
import math
import queue
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crazyswarm_app.domain.commands import BodyRateThrustSetpoint
from crazyswarm_app.domain.telemetry import (
    RadioFailureKind,
    RadioTransportDiagnostics,
)
from crazyswarm_app.hardware.ownership import require_hardware_runtime
from crazyswarm_app.vehicles.crazyflie_link import (
    CrazyflieConnectionMetadata,
    CrazyflieRawSample,
)

LOG_GROUPS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    (
        "state",
        100,
        (
            "stateEstimate.x",
            "stateEstimate.y",
            "stateEstimate.z",
            "stateEstimate.vx",
            "stateEstimate.vy",
            "stateEstimate.vz",
        ),
    ),
    (
        "attitude",
        100,
        (
            "stabilizer.roll",
            "stabilizer.pitch",
            "stabilizer.yaw",
            "kalman.varPX",
            "kalman.varPY",
            "kalman.varPZ",
        ),
    ),
    (
        "quaternion",
        200,
        (
            "stateEstimate.qw",
            "stateEstimate.qx",
            "stateEstimate.qy",
            "stateEstimate.qz",
        ),
    ),
    (
        "imu",
        200,
        (
            "acc.x",
            "acc.y",
            "acc.z",
            "gyro.x",
            "gyro.y",
            "gyro.z",
        ),
    ),
    (
        "ranges",
        200,
        (
            "range.front",
            "range.back",
            "range.left",
            "range.right",
            "range.up",
            "range.zrange",
        ),
    ),
    (
        "health",
        200,
        (
            "pm.vbat",
            "pm.batteryLevel",
            "motion.deltaX",
            "motion.deltaY",
            "motion.squal",
        ),
    ),
    (
        "motors",
        200,
        (
            "motor.m1",
            "motor.m2",
            "motor.m3",
            "motor.m4",
        ),
    ),
    (
        "supervisor",
        100,
        ("supervisor.info",),
    ),
)

REQUIRED_DECK_PARAMETERS = ("deck.bcFlow2", "deck.bcMultiranger")
QUALIFICATION_PARAMETERS = (
    "commander.enHighLevel",
    "stabilizer.controller",
    "stabilizer.estimator",
    "firmware.tag",
    "firmware.revision0",
    "firmware.revision1",
    "firmware.modified",
)

_CRTP_DRIVER_INIT_LOCK = threading.Lock()
_CRTP_DRIVERS_INITIALIZED = False
CONNECTION_TIMEOUT_S = 12.0
PARAMETER_DOWNLOAD_TIMEOUT_S = 12.0
DISCONNECTION_CALLBACK_TIMEOUT_S = 2.0
SUPERVISOR_LOG_TIMEOUT_S = 2.0
LOG_RESTART_FRESH_TIMEOUT_S = 2.0
RADIO_RELEASE_TIMEOUT_S = 1.0
RADIO_RELEASE_POLL_S = 0.01
RADIO_LOSS_WINDOW_PACKETS = 500
RADIO_DEGRADED_LOSS_PERCENT = 5.0
COMMAND_MAXIMUM_ACK_AGE_S = 1.0
COMMAND_MAXIMUM_CONSECUTIVE_LOSS = 3
QUEUE_SATURATION_MESSAGE = "RadioDriver: Could not send packet to copter"
# cflib's consecutive-missed-ACK counter closes the transport instead of leaving
# it available to recover when an idle drone starts answering again. Keep that
# library counter effectively disabled and let the application's measured
# telemetry watchdog own freshness/failure timing. This does not extend command
# authority: stale telemetry still fails closed in ``CrazyflieVehicle.snapshot``.
RADIO_RETRIES_BEFORE_DISCONNECT = 2_147_483_647


def _ensure_crtp_drivers_initialized(crtp: Any) -> None:
    """Initialize cflib's process-global driver registry exactly once.

    ``cflib.crtp.init_drivers`` appends to its global ``CLASSES`` list on every
    call. Reinitializing during discovery or a connection retry therefore adds
    duplicate Crazyradio drivers that contend for the same USB device.
    """

    global _CRTP_DRIVERS_INITIALIZED
    with _CRTP_DRIVER_INIT_LOCK:
        if _CRTP_DRIVERS_INITIALIZED:
            return
        crtp.init_drivers()
        _CRTP_DRIVERS_INITIALIZED = True


def _wait_for_shared_radio_release(
    radio_driver_module: Any,
    selected_uri: str,
    *,
    timeout_s: float = RADIO_RELEASE_TIMEOUT_S,
) -> None:
    """Wait for cflib's asynchronous Crazyradio close to reach the USB device.

    cflib 0.1.32 queues ``STOP`` for its shared radio thread and returns from
    ``RadioDriver.close()`` before that command is processed. Reopening in that
    window can create a new logical instance just before the queued stop closes
    its USB transport. The new connection then receives no acknowledgements and
    times out. Physical operations intentionally use one radio connection at a
    time, so wait for the previous instance to finish releasing the dongle.
    """

    device_id = int(radio_driver_module.RadioDriver.parse_uri(selected_uri)[0])
    manager = radio_driver_module.RadioManager
    deadline = time.monotonic() + timeout_s
    while True:
        with manager._lock:
            shared_radio = (
                manager._radios[device_id] if 0 <= device_id < len(manager._radios) else None
            )
        if shared_radio is None:
            return
        with shared_radio._lock:
            # cflib registers a response queue before it tries to reopen the
            # USB dongle. If Crazyradio construction fails (for example while
            # the dongle is unplugged), ``open_instance`` raises without
            # removing that queue. No instance is returned and therefore no
            # later STOP command can remove it. Clear only this impossible
            # no-radio/non-empty state; registrations beside an open radio may
            # belong to a live connection and must never be inferred stale.
            response_queues = getattr(shared_radio, "_rsp_queues", None)
            if shared_radio._radio is None and response_queues:
                response_queues.clear()
            released = shared_radio._radio is None
        if released:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Crazyradio {device_id} did not finish releasing within {timeout_s:g} s"
            )
        time.sleep(RADIO_RELEASE_POLL_S)


def _configure_radio_disconnect_policy(radio_driver_module: Any) -> None:
    """Keep cflib's ACK-loss threshold behind the telemetry watchdog."""

    radio_driver_module.set_retries_before_disconnect(
        RADIO_RETRIES_BEFORE_DISCONNECT
    )


class CflibCrazyflieLink:
    """cflib-only implementation isolated from generic contracts.

    Driver initialization and all radio access happen only in ``connect`` or the
    explicit ``discover`` method. Constructing this object is inert.
    """

    def __init__(
        self,
        *,
        cache_directory: Path = Path(".cache/crazyswarm/cflib"),
        enable_latency_pings: bool = True,
    ) -> None:
        self._cache_directory = cache_directory
        self._enable_latency_pings = enable_latency_pings
        self._scf: Any | None = None
        self._cf: Any | None = None
        self._log_configs: list[Any] = []
        self._log_config_type: Any | None = None
        self._log_lifecycle_lock = threading.Lock()
        self._lock = threading.Lock()
        self._values: dict[str, float] = {}
        self._value_received_at_monotonic_s: dict[str, float] = {}
        self._timestamp_ms = 0
        self._received_at = 0.0
        self._link_quality: float | None = None
        self._link_latency_ms: float | None = None
        self._log_errors: list[str] = []
        self._connection_error: str | None = None
        self._connected = False
        self._connection_epoch = 0
        self._selected_uri_sha256: str | None = None
        self._ack_window: deque[bool] = deque(maxlen=RADIO_LOSS_WINDOW_PACKETS)
        self._acked_packet_count = 0
        self._lost_packet_count = 0
        self._consecutive_lost_packet_count = 0
        self._maximum_consecutive_lost_packet_count = 0
        self._queue_saturation_count = 0
        self._usb_error_count = 0
        self._last_ack_monotonic_s: float | None = None
        self._transport_failure_kind = RadioFailureKind.NONE
        self._transport_last_event_at_utc: datetime | None = None
        self._transport_last_event_message: str | None = None
        self._uplink_rssi_raw: float | None = None
        self._uplink_rate_hz: float | None = None
        self._downlink_rate_hz: float | None = None
        self._uplink_congestion_percent: float | None = None
        self._downlink_congestion_percent: float | None = None
        self._radio_probe_owner: Any | None = None
        self._original_radio_send_packet: Any | None = None
        self._driver_probe_owner: Any | None = None
        self._original_driver_link_error_callback: Any | None = None
        self._transport_journal_lock = threading.Lock()
        self._transport_journal_queue: queue.SimpleQueue[dict[str, object] | None] | None = None
        self._transport_journal_thread: threading.Thread | None = None
        self._log_data_event = threading.Event()
        self._supervisor_data_event = threading.Event()
        self._supervisor_log_available = False
        self._motor_selection: str | None = None
        self._body_rate_lock = threading.Lock()
        self._body_rate_stop = threading.Event()
        self._body_rate_idle = threading.Event()
        self._body_rate_idle.set()
        self._hover_hold_lock = threading.Lock()
        self._hover_hold_stop = threading.Event()
        self._hover_hold_idle = threading.Event()
        self._hover_hold_idle.set()
        self._hover_hold_active = False

    @staticmethod
    def discover() -> tuple[str, ...]:
        require_hardware_runtime()
        crtp = importlib.import_module("cflib.crtp")
        _ensure_crtp_drivers_initialized(crtp)
        found = crtp.scan_interfaces()
        return tuple(sorted(str(item[0]) for item in found))

    def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata:
        if self._scf is not None:
            raise RuntimeError("Crazyflie link is already open")
        require_hardware_runtime()
        crtp = importlib.import_module("cflib.crtp")
        crazyflie_module = importlib.import_module("cflib.crazyflie")
        sync_module = importlib.import_module("cflib.crazyflie.syncCrazyflie")
        log_module = importlib.import_module("cflib.crazyflie.log")
        radio_driver_module = importlib.import_module("cflib.crtp.radiodriver")
        _ensure_crtp_drivers_initialized(crtp)
        _configure_radio_disconnect_policy(radio_driver_module)
        _wait_for_shared_radio_release(radio_driver_module, selected_uri)
        self._connection_epoch += 1
        self._selected_uri_sha256 = hashlib.sha256(selected_uri.encode()).hexdigest()
        self._reset_transport_epoch()
        self._record_transport_event("CONNECT_ATTEMPT", RadioFailureKind.NONE, "opening radio link")
        self._log_data_event.clear()
        self._supervisor_data_event.clear()
        self._supervisor_log_available = False
        with self._lock:
            self._values.clear()
            self._value_received_at_monotonic_s.clear()
            self._timestamp_ms = 0
            self._received_at = 0.0
            self._link_quality = None
            self._link_latency_ms = None
            self._log_errors.clear()
            self._connection_error = None
        self._cache_directory.mkdir(parents=True, exist_ok=True)
        crazyflie = crazyflie_module.Crazyflie(rw_cache=str(self._cache_directory))
        scf = sync_module.SyncCrazyflie(selected_uri, cf=crazyflie)
        self._configure_latency_statistics(crazyflie)

        # The driver does not exist until the first aircraft response establishes
        # the CRTP link. Install queue containment at that earliest callback,
        # before TOC and parameter traffic can fill cflib's one-slot queue.
        def install_radio_probe(_: str) -> None:
            self._install_radio_probe(crazyflie)

        crazyflie.link_established.add_callback(install_radio_probe)
        try:
            try:
                self._open_link_bounded(scf)
            finally:
                crazyflie.link_established.remove_callback(install_radio_probe)
            self._install_radio_probe(crazyflie)
            if not scf._params_updated_event.wait(PARAMETER_DOWNLOAD_TIMEOUT_S):
                raise TimeoutError(
                    "Crazyflie parameter download did not finish within "
                    f"{PARAMETER_DOWNLOAD_TIMEOUT_S:.0f} s"
                )
            self._scf = scf
            self._cf = crazyflie
            self._connected = True
            crazyflie.disconnected.add_callback(self._on_disconnected)
            crazyflie.connection_lost.add_callback(self._on_connection_lost)
            crazyflie.link_statistics.link_quality_updated.add_callback(self._on_link_quality)
            crazyflie.link_statistics.latency_updated.add_callback(self._on_link_latency)
            crazyflie.link_statistics.uplink_rssi_updated.add_callback(self._on_uplink_rssi)
            crazyflie.link_statistics.uplink_rate_updated.add_callback(self._on_uplink_rate)
            crazyflie.link_statistics.downlink_rate_updated.add_callback(self._on_downlink_rate)
            crazyflie.link_statistics.uplink_congestion_updated.add_callback(
                self._on_uplink_congestion
            )
            crazyflie.link_statistics.downlink_congestion_updated.add_callback(
                self._on_downlink_congestion
            )
            deck_parameters = {
                name: self._parameter_as_int(crazyflie, name) for name in REQUIRED_DECK_PARAMETERS
            }
            observed_parameters = {
                name: value
                for name in QUALIFICATION_PARAMETERS
                if (value := self._parameter_value(crazyflie, name)) is not None
            }
            self._log_config_type = log_module.LogConfig
            available = self._start_logs(crazyflie, self._log_config_type)
            self._supervisor_log_available = "supervisor.info" in available
            firmware = self._firmware_identity(observed_parameters)
            self._record_transport_event("LINK_READY", RadioFailureKind.NONE, "radio link ready")
            return CrazyflieConnectionMetadata(
                selected_uri=selected_uri,
                connected_uri=str(crazyflie.link_uri),
                protocol_version=int(crazyflie.platform.get_protocol_version()),
                firmware_version=firmware,
                deck_parameters=deck_parameters,
                observed_parameters=observed_parameters,
                available_log_variables=frozenset(available),
            )
        except Exception:
            self._connected = False
            self._record_transport_event(
                "PROTOCOL_SETUP_FAILED",
                RadioFailureKind.PROTOCOL_SETUP_FAILED,
                "radio protocol setup failed",
            )
            try:
                cleanup_error = self._close_link_bounded(scf)
                if cleanup_error is not None:
                    with self._lock:
                        self._log_errors.append(cleanup_error)
            finally:
                self._restore_radio_probe()
                self._stop_transport_journal()
                self._scf = None
                self._cf = None
                self._log_config_type = None
            raise

    @staticmethod
    def _open_link_bounded(scf: Any) -> None:
        """Pinned cflib 0.1.32 handshake with explicit deadlines.

        SyncCrazyflie waits forever for both its connection event and parameter
        event. Keeping the same callback lifecycle here prevents a lost radio from
        leaving the API permanently in CONNECTING.
        """

        if scf.is_link_open():
            raise RuntimeError("Crazyflie link is already open")
        scf._add_callbacks()
        scf._connect_event = threading.Event()
        scf._params_updated_event.clear()
        scf.cf.open_link(scf._link_uri)
        if not scf._connect_event.wait(CONNECTION_TIMEOUT_S):
            scf._connect_event = None
            scf._remove_callbacks()
            scf._params_updated_event.clear()
            scf.cf.close_link()
            raise TimeoutError(
                f"Crazyflie connection did not finish within {CONNECTION_TIMEOUT_S:.0f} s"
            )
        scf._connect_event = None
        if not scf._is_link_open:
            scf._remove_callbacks()
            scf._params_updated_event.clear()
            scf.cf.close_link()
            raise RuntimeError(scf._error_message)

    @staticmethod
    def _close_link_bounded(scf: Any) -> str | None:
        """Close cflib without trusting its unbounded synchronous wait.

        cflib's callback dispatcher stops at the first callback exception. If
        its latency thread tries to disconnect itself, SyncCrazyflie's later
        disconnect callback never sets the event and ``close_link`` waits
        forever. Drive the underlying close directly, wait only for the bounded
        callback interval, and always reset the sync wrapper for the next retry.
        """

        if not scf.is_link_open():
            return None
        disconnected = threading.Event()
        scf._disconnect_event = disconnected
        close_error: Exception | None = None
        try:
            scf.cf.close_link()
        except Exception as error:
            close_error = error
        callback_completed = disconnected.wait(DISCONNECTION_CALLBACK_TIMEOUT_S)
        scf._disconnect_event = None
        scf._params_updated_event.clear()
        scf._is_link_open = False
        scf._remove_callbacks()
        if close_error is not None:
            return f"cflib link cleanup raised {type(close_error).__name__}: {close_error}"
        if not callback_completed:
            return (
                "cflib disconnect callback did not finish within "
                f"{DISCONNECTION_CALLBACK_TIMEOUT_S:.0f} s"
            )
        return None

    def disconnect(self) -> None:
        self._body_rate_stop.set()
        self._body_rate_idle.wait(timeout=0.1)
        self._hover_hold_stop.set()
        self._hover_hold_idle.wait(timeout=0.1)
        self._hover_hold_active = False
        scf = self._scf
        if scf is None:
            self._connected = False
            return
        with self._log_lifecycle_lock:
            for error in self._stop_log_configs():
                with self._lock:
                    self._log_errors.append(f"log shutdown: {error}")
            self._log_config_type = None
        try:
            cleanup_error = self._close_link_bounded(scf)
            if cleanup_error is not None:
                with self._lock:
                    self._log_errors.append(cleanup_error)
        finally:
            # Keep queue saturation non-fatal until every cflib producer has
            # stopped. Restoring earlier recreates the ping-thread self-join
            # race while the link is closing.
            self._restore_radio_probe()
            self._connected = False
            self._record_transport_event("LINK_CLOSED", RadioFailureKind.NONE, "radio link closed")
            self._stop_transport_journal()
            self._scf = None
            self._cf = None

    def restart_observation_logs(self) -> None:
        """Repair stalled firmware logging without cycling the Crazyradio link."""

        self._require_connected()
        with self._log_lifecycle_lock:
            crazyflie = self._require_connected()
            log_config_type = self._log_config_type
            if log_config_type is None:
                raise RuntimeError("Crazyflie log configuration type is unavailable")
            self._record_transport_event(
                "LOG_RESTART_ATTEMPT",
                RadioFailureKind.TELEMETRY_STALE,
                "restarting stalled firmware log blocks on the retained radio link",
            )
            shutdown_errors = self._stop_log_configs()
            if shutdown_errors:
                message = "; ".join(shutdown_errors)
                self._record_transport_event(
                    "LOG_RESTART_FAILED",
                    RadioFailureKind.PROTOCOL_SETUP_FAILED,
                    f"stalled log blocks could not be removed: {message}",
                )
                raise RuntimeError(f"stalled Crazyflie log blocks could not be removed: {message}")

            self._log_data_event.clear()
            self._supervisor_data_event.clear()
            self._supervisor_log_available = False
            with self._lock:
                self._values.clear()
                self._value_received_at_monotonic_s.clear()
                self._timestamp_ms = 0
                self._received_at = 0.0
                self._log_errors.clear()
            try:
                available = self._start_logs(crazyflie, log_config_type)
            except Exception as error:
                self._stop_log_configs()
                self._record_transport_event(
                    "LOG_RESTART_FAILED",
                    RadioFailureKind.PROTOCOL_SETUP_FAILED,
                    f"firmware log block recreation failed: {error}",
                )
                raise RuntimeError(f"Crazyflie log block recreation failed: {error}") from error
            self._supervisor_log_available = "supervisor.info" in available
            if not self._log_data_event.wait(LOG_RESTART_FRESH_TIMEOUT_S):
                self._stop_log_configs()
                self._record_transport_event(
                    "LOG_RESTART_FAILED",
                    RadioFailureKind.TELEMETRY_STALE,
                    "recreated firmware log blocks produced no fresh telemetry",
                )
                raise TimeoutError(
                    "recreated Crazyflie log blocks produced no fresh telemetry within "
                    f"{LOG_RESTART_FRESH_TIMEOUT_S:g} s"
                )
            self._record_transport_event(
                "LOG_RESTARTED",
                RadioFailureKind.NONE,
                "firmware log delivery resumed without closing the radio link",
            )

    def _stop_log_configs(self) -> tuple[str, ...]:
        errors: list[str] = []
        for config in tuple(self._log_configs):
            try:
                config.stop()
                config.delete()
            except Exception as error:
                errors.append(str(error))
        self._log_configs.clear()
        return tuple(errors)

    def _reset_transport_epoch(self) -> None:
        with self._lock:
            self._ack_window.clear()
            self._acked_packet_count = 0
            self._lost_packet_count = 0
            self._consecutive_lost_packet_count = 0
            self._maximum_consecutive_lost_packet_count = 0
            self._queue_saturation_count = 0
            self._usb_error_count = 0
            self._last_ack_monotonic_s = None
            self._transport_failure_kind = RadioFailureKind.NONE
            self._transport_last_event_at_utc = None
            self._transport_last_event_message = None
            self._uplink_rssi_raw = None
            self._uplink_rate_hz = None
            self._downlink_rate_hz = None
            self._uplink_congestion_percent = None
            self._downlink_congestion_percent = None

    def _install_radio_probe(self, crazyflie: Any) -> None:
        """Measure all Crazyradio ACK outcomes and contain cflib queue amplification.

        cflib 0.1.32 skips its output-queue drain whenever a packet has no ACK.
        A second producer then reports queue saturation through the same fatal
        callback used for USB failures, which closes the whole link. Keep that
        condition observable but non-fatal; the measured telemetry watchdog owns
        the eventual stale-link reconnect. Every physical exchange is wrapped so
        the application records the no-ACK outcomes omitted by cflib statistics.
        """

        driver = getattr(crazyflie, "link", None)
        radio = None if driver is None else getattr(driver, "_radio", None)
        if driver is None or radio is None:
            return
        if self._driver_probe_owner is driver:
            return
        original_send_packet = radio.send_packet
        original_link_error_callback = driver.link_error_callback

        def measured_send_packet(data: Any) -> Any:
            try:
                acknowledgment = original_send_packet(data)
            except Exception as error:
                self._record_usb_error(error)
                raise
            self._record_ack_outcome(acknowledgment)
            return acknowledgment

        def classified_link_error(message: str) -> None:
            if str(message) == QUEUE_SATURATION_MESSAGE:
                self._record_queue_saturation()
                return
            original_link_error_callback(message)

        radio.send_packet = measured_send_packet
        driver.link_error_callback = classified_link_error
        self._radio_probe_owner = radio
        self._original_radio_send_packet = original_send_packet
        self._driver_probe_owner = driver
        self._original_driver_link_error_callback = original_link_error_callback

    def _configure_latency_statistics(self, crazyflie: Any) -> None:
        """Apply the pinned cflib latency-thread safety policy before opening.

        Observation obtains delivery statistics directly from the radio driver,
        so it must never start cflib's optional 10 Hz echo producer. For command
        links that retain latency pings, make a disconnect initiated on that
        thread signal-only instead of attempting to join the current thread.
        """

        latency = crazyflie.link_statistics.latency
        original_stop = latency.stop

        def safe_stop() -> None:
            if getattr(latency, "_ping_thread_instance", None) is threading.current_thread():
                latency._stop_event.set()
                return
            original_stop()

        latency.stop = safe_stop
        if not self._enable_latency_pings:
            latency.start = lambda: None

    def _restore_radio_probe(self) -> None:
        if self._radio_probe_owner is not None and self._original_radio_send_packet is not None:
            self._radio_probe_owner.send_packet = self._original_radio_send_packet
        if (
            self._driver_probe_owner is not None
            and self._original_driver_link_error_callback is not None
        ):
            self._driver_probe_owner.link_error_callback = (
                self._original_driver_link_error_callback
            )
        self._radio_probe_owner = None
        self._original_radio_send_packet = None
        self._driver_probe_owner = None
        self._original_driver_link_error_callback = None

    def _record_ack_outcome(self, acknowledgment: Any) -> None:
        acknowledged = bool(acknowledgment is not None and acknowledgment.ack)
        recovered_streak = 0
        loss_started = False
        with self._lock:
            self._ack_window.append(acknowledged)
            if acknowledged:
                self._acked_packet_count += 1
                recovered_streak = self._consecutive_lost_packet_count
                self._consecutive_lost_packet_count = 0
                self._last_ack_monotonic_s = time.monotonic()
                if self._transport_failure_kind in {
                    RadioFailureKind.RF_ACK_LOSS,
                    RadioFailureKind.TARGET_OFFLINE,
                    RadioFailureKind.OUTBOUND_QUEUE_SATURATED,
                }:
                    self._transport_failure_kind = RadioFailureKind.NONE
            else:
                self._lost_packet_count += 1
                self._consecutive_lost_packet_count += 1
                self._maximum_consecutive_lost_packet_count = max(
                    self._maximum_consecutive_lost_packet_count,
                    self._consecutive_lost_packet_count,
                )
                loss_started = self._consecutive_lost_packet_count == 1
                self._transport_failure_kind = RadioFailureKind.RF_ACK_LOSS
        if loss_started:
            self._record_transport_event(
                "ACK_LOSS_STARTED",
                RadioFailureKind.RF_ACK_LOSS,
                "Crazyradio exchange received no aircraft ACK",
            )
        elif recovered_streak:
            self._record_transport_event(
                "ACK_RECOVERED",
                RadioFailureKind.NONE,
                f"radio ACK recovered after {recovered_streak} consecutive losses",
            )

    def _record_queue_saturation(self) -> None:
        with self._lock:
            self._queue_saturation_count += 1
            self._transport_failure_kind = RadioFailureKind.OUTBOUND_QUEUE_SATURATED
        self._record_transport_event(
            "QUEUE_SATURATED",
            RadioFailureKind.OUTBOUND_QUEUE_SATURATED,
            "cflib outbound queue saturated during a no-ACK interval",
        )

    def _record_usb_error(self, error: Exception) -> None:
        with self._lock:
            self._usb_error_count += 1
            self._transport_failure_kind = RadioFailureKind.USB_UNAVAILABLE
        self._record_transport_event(
            "USB_ERROR",
            RadioFailureKind.USB_UNAVAILABLE,
            f"Crazyradio USB exchange failed: {type(error).__name__}",
        )

    def _record_transport_event(
        self,
        event_kind: str,
        failure_kind: RadioFailureKind,
        message: str,
    ) -> None:
        occurred_at = datetime.now(UTC)
        safe_message = message[:240]
        with self._lock:
            self._transport_failure_kind = failure_kind
            self._transport_last_event_at_utc = occurred_at
            self._transport_last_event_message = safe_message
            packet_count = len(self._ack_window)
            loss_percent = (
                None
                if packet_count == 0
                else 100.0 * sum(not item for item in self._ack_window) / packet_count
            )
            payload = {
                "schema_version": 1,
                "occurred_at_utc": occurred_at.isoformat(),
                "connection_epoch": self._connection_epoch,
                "event_kind": event_kind,
                "failure_kind": failure_kind.value,
                "uri_sha256": self._selected_uri_sha256,
                "acked_packet_count": self._acked_packet_count,
                "lost_packet_count": self._lost_packet_count,
                "packet_loss_percent": loss_percent,
                "consecutive_lost_packet_count": self._consecutive_lost_packet_count,
                "queue_saturation_count": self._queue_saturation_count,
                "usb_error_count": self._usb_error_count,
                "message": safe_message,
            }
        self._enqueue_transport_event(payload)

    def _enqueue_transport_event(self, payload: dict[str, object]) -> None:
        with self._transport_journal_lock:
            thread = self._transport_journal_thread
            if thread is None or not thread.is_alive():
                events: queue.SimpleQueue[dict[str, object] | None] = queue.SimpleQueue()
                self._transport_journal_queue = events
                thread = threading.Thread(
                    target=self._transport_journal_worker,
                    args=(events,),
                    name="CrazyradioTransportJournal",
                    daemon=True,
                )
                self._transport_journal_thread = thread
                thread.start()
            assert self._transport_journal_queue is not None
            self._transport_journal_queue.put(payload)

    def _transport_journal_worker(
        self,
        events: queue.SimpleQueue[dict[str, object] | None],
    ) -> None:
        journal_path = self._cache_directory.parent / "radio-transport-events.jsonl"
        while True:
            payload = events.get()
            if payload is None:
                return
            try:
                journal_path.parent.mkdir(parents=True, exist_ok=True)
                with journal_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
                    stream.write("\n")
            except OSError as error:
                with self._lock:
                    self._log_errors.append(f"transport journal: {error}")

    def _stop_transport_journal(self) -> None:
        with self._transport_journal_lock:
            events = self._transport_journal_queue
            thread = self._transport_journal_thread
            self._transport_journal_queue = None
            self._transport_journal_thread = None
            if events is not None:
                events.put(None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)

    def _transport_snapshot_locked(self) -> RadioTransportDiagnostics:
        packet_count = len(self._ack_window)
        loss_percent = (
            None
            if packet_count == 0
            else 100.0 * sum(not item for item in self._ack_window) / packet_count
        )
        driver = None if self._cf is None else getattr(self._cf, "link", None)
        queue = None if driver is None else getattr(driver, "out_queue", None)
        queue_depth = 0 if queue is None else queue.qsize()
        queue_capacity = max(1, int(getattr(queue, "maxsize", 1) or 1))
        last_ack_age_ms = (
            None
            if self._last_ack_monotonic_s is None
            else max(0.0, (time.monotonic() - self._last_ack_monotonic_s) * 1000.0)
        )
        if not self._connected:
            state = "DISCONNECTED"
        elif last_ack_age_ms is not None and last_ack_age_ms > 1000.0:
            state = "STALE"
        elif (
            self._consecutive_lost_packet_count > 0
            or queue_depth >= queue_capacity
            or (loss_percent is not None and loss_percent >= RADIO_DEGRADED_LOSS_PERCENT)
        ):
            state = "DEGRADED"
        else:
            state = "HEALTHY"
        return RadioTransportDiagnostics(
            connection_epoch=max(1, self._connection_epoch),
            state=state,
            failure_kind=self._transport_failure_kind,
            acked_packet_count=self._acked_packet_count,
            lost_packet_count=self._lost_packet_count,
            packet_loss_percent=loss_percent,
            consecutive_lost_packet_count=self._consecutive_lost_packet_count,
            maximum_consecutive_lost_packet_count=(
                self._maximum_consecutive_lost_packet_count
            ),
            retry_quality_percent=self._link_quality,
            uplink_rssi_raw=self._uplink_rssi_raw,
            uplink_rate_hz=self._uplink_rate_hz,
            downlink_rate_hz=self._downlink_rate_hz,
            uplink_congestion_percent=self._uplink_congestion_percent,
            downlink_congestion_percent=self._downlink_congestion_percent,
            outbound_queue_depth=queue_depth,
            outbound_queue_capacity=queue_capacity,
            queue_saturation_count=self._queue_saturation_count,
            usb_error_count=self._usb_error_count,
            last_ack_age_ms=last_ack_age_ms,
            last_event_at_utc=self._transport_last_event_at_utc,
            last_event_message=self._transport_last_event_message,
        )

    def read_sample(self) -> CrazyflieRawSample:
        """Return cached log telemetry without adding a synchronous CRTP request.

        ``supervisor.info`` is part of the firmware log stream. Reading the same
        state through ``cf.supervisor.read_bitfield()`` on every command refresh
        added up to fifty blocking CRTP transactions per second and could saturate
        cflib's queue after packet loss.
        """

        self._require_connected()
        if not self._log_data_event.wait(timeout=1.0):
            raise TimeoutError("no Crazyflie log telemetry received within 1.0 s")
        if self._supervisor_log_available and not self._supervisor_data_event.wait(
            timeout=SUPERVISOR_LOG_TIMEOUT_S
        ):
            raise TimeoutError(
                f"no supervisor.info log telemetry received within {SUPERVISOR_LOG_TIMEOUT_S:.1f} s"
            )
        with self._lock:
            value = self._values.get("supervisor.info")
        return self._cached_sample(
            supervisor_bitfield=None if value is None else int(value),
        )

    def read_observation_sample(self) -> CrazyflieRawSample:
        """Return log-driven telemetry without polling the command supervisor.

        Observation has no command authority. Polling the supervisor on every
        presentation frame can block for seconds after RF loss and saturate
        cflib's radio queue. The log callbacks already provide the sensor values
        and transport timestamps required by this path.
        """

        self._require_connected()
        if not self._log_data_event.wait(timeout=1.0):
            raise TimeoutError("no Crazyflie log telemetry received within 1.0 s")
        with self._lock:
            value = self._values.get("supervisor.info")
        return self._cached_sample(
            supervisor_bitfield=None if value is None else int(value),
        )

    def _cached_sample(self, *, supervisor_bitfield: int | None) -> CrazyflieRawSample:
        with self._lock:
            return CrazyflieRawSample(
                source_timestamp_ms=self._timestamp_ms,
                received_at_monotonic_s=self._received_at or time.monotonic(),
                values=dict(self._values),
                value_received_at_monotonic_s=dict(
                    self._value_received_at_monotonic_s
                ),
                supervisor_bitfield=supervisor_bitfield,
                link_quality_percent=self._link_quality,
                link_latency_ms=self._link_latency_ms,
                radio_transport=self._transport_snapshot_locked(),
                connected=self._connected,
                log_errors=tuple(self._log_errors),
            )

    def request_arm(self, armed: bool) -> None:
        self._require_command_transport_healthy().supervisor.send_arming_request(armed)

    def reset_estimator(self) -> None:
        cf = self._require_command_transport_healthy()
        cf.param.set_value("kalman.resetEstimation", "1")
        time.sleep(0.1)
        cf.param.set_value("kalman.resetEstimation", "0")

    def recover_from_crash(self) -> None:
        self._require_command_transport_healthy().supervisor.send_crash_recovery_request()

    def begin_motor_power_override(self, motor_selection: str) -> None:
        if motor_selection not in {"all", "m1", "m2", "m3", "m4"}:
            raise ValueError(f"unknown motor selection: {motor_selection}")
        cf = self._require_command_transport_healthy()
        cf.param.set_value("motorPowerSet.enable", "0")
        for motor in ("m1", "m2", "m3", "m4"):
            cf.param.set_value(f"motorPowerSet.{motor}", "0")
        cf.param.set_value("motorPowerSet.enable", "2" if motor_selection == "all" else "1")
        self._motor_selection = motor_selection

    def set_motor_power_percent(self, motor_selection: str, percent: float) -> None:
        if motor_selection != self._motor_selection:
            raise RuntimeError("motor selection does not match the active override")
        if not 0.0 <= percent <= 70.0:
            raise ValueError("motor power must be between 0 and 70 percent")
        cf = self._require_command_transport_healthy()
        pwm = round(percent / 100.0 * 65_535.0)
        parameter = (
            "motorPowerSet.m1" if motor_selection == "all" else f"motorPowerSet.{motor_selection}"
        )
        cf.param.set_value(parameter, str(pwm))

    def feed_motor_watchdog(self) -> None:
        self._require_command_transport_healthy().supervisor.send_emergency_stop_watchdog()

    def end_motor_power_override(self) -> None:
        cf = self._require_connected()
        try:
            for motor in ("m1", "m2", "m3", "m4"):
                cf.param.set_value(f"motorPowerSet.{motor}", "0")
        finally:
            cf.param.set_value("motorPowerSet.enable", "0")
            self._motor_selection = None

    def takeoff(self, height_m: float, duration_s: float, yaw_rad: float | None) -> None:
        self._require_command_transport_healthy().high_level_commander.takeoff(
            height_m,
            duration_s,
            yaw=yaw_rad,
        )

    def land(self, height_m: float, duration_s: float) -> None:
        self._body_rate_stop.set()
        if not self._body_rate_idle.wait(timeout=0.1):
            raise TimeoutError("body-rate stream did not release before landing")
        self.release_stop_and_hold()
        self._require_connected().high_level_commander.land(
            height_m,
            duration_s,
            yaw=None,
        )

    def go_to_relative(
        self,
        x_m: float,
        y_m: float,
        z_m: float,
        yaw_rad: float,
        duration_s: float,
    ) -> None:
        self._require_command_transport_healthy().high_level_commander.go_to(
            x_m,
            y_m,
            z_m,
            yaw_rad,
            duration_s,
            relative=True,
        )

    def hold_position(self, duration_s: float) -> None:
        # The selected high-level strategy holds the last planner setpoint onboard.
        # No packet is sent here: changing commander priority would change semantics.
        if duration_s <= 0.0:
            raise ValueError("hold duration must be positive")
        self._require_connected()

    def stop_and_hold(self, z_distance_m: float, duration_s: float) -> None:
        """Override an active HLC trajectory with a bounded zero-velocity hover stream."""

        if not math.isfinite(z_distance_m) or z_distance_m <= 0.0:
            raise ValueError("hold height must be finite and positive")
        if not math.isfinite(duration_s) or duration_s <= 0.0:
            raise ValueError("hold duration must be finite and positive")
        if not self._hover_hold_lock.acquire(blocking=False):
            raise RuntimeError("another stop-and-hold stream is already active")
        if not self._body_rate_idle.wait(timeout=0.1):
            self._hover_hold_lock.release()
            raise TimeoutError("body-rate stream did not release before stop-and-hold")
        self._hover_hold_stop.clear()
        self._hover_hold_idle.clear()
        deadline = time.monotonic() + duration_s
        try:
            commander = self._require_command_transport_healthy().commander
            while True:
                commander.send_hover_setpoint(0.0, 0.0, 0.0, z_distance_m)
                self._hover_hold_active = True
                remaining_s = deadline - time.monotonic()
                if remaining_s <= 0.0:
                    return
                if self._hover_hold_stop.wait(timeout=min(0.02, remaining_s)):
                    return
        finally:
            self._hover_hold_idle.set()
            self._hover_hold_lock.release()

    def release_stop_and_hold(self) -> None:
        self._hover_hold_stop.set()
        if not self._hover_hold_idle.wait(timeout=0.1):
            raise TimeoutError("stop-and-hold stream did not release")
        if not self._hover_hold_active:
            return
        self._require_connected().commander.send_notify_setpoint_stop(0)
        self._hover_hold_active = False

    def stream_body_rate_thrust(
        self,
        setpoints: tuple[BodyRateThrustSetpoint, ...],
        sample_period_s: float,
    ) -> None:
        """Stream rate-mode setpoints and deterministically release HLC priority."""

        if not setpoints:
            raise ValueError("body-rate stream requires at least one setpoint")
        if not 0.005 <= sample_period_s <= 0.02:
            raise ValueError("body-rate stream period must be between 5 and 20 ms")
        cf = self._require_command_transport_healthy()
        if not self._body_rate_lock.acquire(blocking=False):
            raise RuntimeError("another body-rate stream is already active")
        commander = cf.commander
        self._body_rate_stop.clear()
        self._body_rate_idle.clear()
        next_deadline_s = time.monotonic()
        maximum_lag_s = max(0.02, 3.0 * sample_period_s)
        try:
            for setpoint in setpoints:
                if self._body_rate_stop.is_set():
                    raise RuntimeError("body-rate stream interrupted by recovery command")
                self._require_command_transport_healthy()
                remaining_s = next_deadline_s - time.monotonic()
                if remaining_s > 0.0:
                    time.sleep(remaining_s)
                elif -remaining_s > maximum_lag_s:
                    raise TimeoutError("body-rate stream missed its real-time send deadline")
                commander.send_setpoint_manual(
                    setpoint.roll_rate_deg_s,
                    setpoint.pitch_rate_deg_s,
                    setpoint.yaw_rate_deg_s,
                    setpoint.thrust_percent,
                    rate=True,
                )
                next_deadline_s += sample_period_s
            remaining_s = next_deadline_s - time.monotonic()
            if remaining_s > 0.0:
                time.sleep(remaining_s)
        finally:
            try:
                # Manual commander packets outrank the high-level commander. This
                # meta packet is required so the prior hover/takeoff setpoint can
                # regain control without a motor-cut command.
                commander.send_notify_setpoint_stop()
            finally:
                self._body_rate_idle.set()
                self._body_rate_lock.release()

    def cancel_body_rate_thrust(self) -> None:
        """Interrupt an active finite rate stream without issuing a motor cut."""

        self._body_rate_stop.set()

    def emergency_stop(self) -> None:
        self._body_rate_stop.set()
        self._hover_hold_stop.set()
        self._hover_hold_active = False
        self._require_connected().supervisor.send_emergency_stop()

    def _start_logs(self, crazyflie: Any, log_config_type: Any) -> set[str]:
        available: set[str] = set()
        for name, period_ms, variables in LOG_GROUPS:
            present = tuple(
                variable
                for variable in variables
                if crazyflie.log.toc.get_element_by_complete_name(variable) is not None
            )
            if not present:
                continue
            config = log_config_type(name=f"reality-{name}", period_in_ms=period_ms)
            for variable in present:
                config.add_variable(variable)
            config.data_received_cb.add_callback(self._on_log_data)
            config.error_cb.add_callback(self._on_log_error)
            crazyflie.log.add_config(config)
            config.start()
            self._log_configs.append(config)
            available.update(present)
        return available

    @staticmethod
    def _parameter_as_int(crazyflie: Any, name: str) -> int:
        try:
            return int(crazyflie.param.get_value(name))
        except (KeyError, TypeError, ValueError):
            return 0

    @staticmethod
    def _parameter_value(crazyflie: Any, name: str) -> str | None:
        try:
            value = crazyflie.param.get_value(name)
        except (KeyError, TypeError, ValueError):
            return None
        return None if value in (None, "") else str(value)

    @staticmethod
    def _firmware_identity(parameters: dict[str, str]) -> str | None:
        tag = parameters.get("firmware.tag")
        if tag:
            return tag
        revision = tuple(
            parameters.get(name) for name in ("firmware.revision0", "firmware.revision1")
        )
        if all(item is not None for item in revision):
            return "-".join(item for item in revision if item is not None)
        return None

    def _require_connected(self) -> Any:
        if self._cf is None or not self._connected:
            detail = (
                ""
                if self._connection_error is None
                else f": {self._connection_error}"
            )
            raise RuntimeError(f"Crazyflie link is not connected{detail}")
        return self._cf

    def _require_command_transport_healthy(self) -> Any:
        """Reject new command dispatch while its single-send outcome is unsafe."""

        cf = self._require_connected()
        with self._lock:
            diagnostics = self._transport_snapshot_locked()
        if diagnostics.outbound_queue_depth >= diagnostics.outbound_queue_capacity:
            raise RuntimeError("Crazyflie command transport queue is saturated")
        if diagnostics.consecutive_lost_packet_count >= COMMAND_MAXIMUM_CONSECUTIVE_LOSS:
            raise RuntimeError(
                "Crazyflie command transport has "
                f"{diagnostics.consecutive_lost_packet_count} consecutive packet losses"
            )
        if (
            diagnostics.last_ack_age_ms is not None
            and diagnostics.last_ack_age_ms > COMMAND_MAXIMUM_ACK_AGE_S * 1000.0
        ):
            raise RuntimeError(
                "Crazyflie command transport has no recent aircraft acknowledgement"
            )
        return cf

    def _on_log_data(self, timestamp: int, data: dict[str, float], _: Any) -> None:
        received_at = time.monotonic()
        with self._lock:
            self._timestamp_ms = int(timestamp)
            self._received_at = received_at
            self._values.update({name: float(value) for name, value in data.items()})
            self._value_received_at_monotonic_s.update(
                {name: received_at for name in data}
            )
        self._log_data_event.set()
        if "supervisor.info" in data:
            self._supervisor_data_event.set()

    def _on_log_error(self, _: Any, message: str) -> None:
        with self._lock:
            self._log_errors.append(str(message))

    def _on_link_quality(self, quality: float) -> None:
        with self._lock:
            self._link_quality = float(quality)

    def _on_link_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._link_latency_ms = float(latency_ms)

    def _on_uplink_rssi(self, value: float) -> None:
        with self._lock:
            self._uplink_rssi_raw = float(value)

    def _on_uplink_rate(self, value: float) -> None:
        with self._lock:
            self._uplink_rate_hz = max(0.0, float(value))

    def _on_downlink_rate(self, value: float) -> None:
        with self._lock:
            self._downlink_rate_hz = max(0.0, float(value))

    def _on_uplink_congestion(self, value: float) -> None:
        with self._lock:
            self._uplink_congestion_percent = min(100.0, max(0.0, 100.0 * float(value)))

    def _on_downlink_congestion(self, value: float) -> None:
        with self._lock:
            self._downlink_congestion_percent = min(100.0, max(0.0, 100.0 * float(value)))

    def _on_disconnected(self, _: str) -> None:
        self._connected = False

    def _on_connection_lost(self, _: str, message: str) -> None:
        self._connected = False
        normalized = str(message).lower()
        failure_kind = (
            RadioFailureKind.USB_UNAVAILABLE
            if "unplugged" in normalized
            or "crazyradio dongle" in normalized
            or "cannot find radio" in normalized
            else RadioFailureKind.RF_ACK_LOSS
            if "packet" in normalized or "ack" in normalized
            else RadioFailureKind.UNKNOWN
        )
        with self._lock:
            self._connection_error = str(message)
            self._log_errors.append(f"connection lost: {message}")
        self._record_transport_event("LINK_LOST", failure_kind, str(message))
