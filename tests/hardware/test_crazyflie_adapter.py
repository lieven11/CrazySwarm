from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pytest

from crazyswarm_app.domain.commands import (
    ArmCommand,
    BodyRateThrustCommand,
    BodyRateThrustSetpoint,
    CommandEnvelope,
    HoverCommand,
    MoveRelativeCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    AuthorityClass,
    BackendRole,
    CommandSource,
    CoordinateFrame,
    OperatingMode,
    VehicleCapability,
)
from crazyswarm_app.domain.telemetry import RadioFailureKind, RadioTransportDiagnostics
from crazyswarm_app.hardware.models import CommandPermit, PermitScope
from crazyswarm_app.vehicles import _cflib_link
from crazyswarm_app.vehicles._cflib_link import LOG_GROUPS
from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle
from crazyswarm_app.vehicles.crazyflie_link import (
    CrazyflieConnectionMetadata,
    CrazyflieRawSample,
)
from tests.vehicles.conformance import assert_vehicle_conformance

URI = "radio://0/80/2M/E7E7E7E701"
SHA = "a" * 64


def test_radio_log_groups_stay_within_the_observation_transport_budget() -> None:
    periods_ms = {name: period_ms for name, period_ms, _variables in LOG_GROUPS}
    assert set(periods_ms) == {
        "state",
        "attitude",
        "quaternion",
        "imu",
        "ranges",
        "health",
        "motors",
        "supervisor",
    }
    assert all(period_ms >= 100 for period_ms in periods_ms.values())
    assert periods_ms["supervisor"] == 100
    assert all(
        periods_ms[name] >= 200 for name in {"quaternion", "imu", "ranges", "health", "motors"}
    )


def test_stalled_log_blocks_restart_without_changing_the_radio_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Callbacks:
        def __init__(self) -> None:
            self.items: list[Callable[..., None]] = []

        def add_callback(self, callback: Callable[..., None]) -> None:
            self.items.append(callback)

    class FakeLogConfig:
        def __init__(self, *, name: str, period_in_ms: int) -> None:
            self.name = name
            self.period_in_ms = period_in_ms
            self.variables: list[str] = []
            self.data_received_cb = Callbacks()
            self.error_cb = Callbacks()
            self.started = False

        def add_variable(self, name: str) -> None:
            self.variables.append(name)

        def start(self) -> None:
            self.started = True
            for callback in self.data_received_cb.items:
                callback(123_000, {self.variables[0]: 4.1}, self)

        def stop(self) -> None:
            self.started = False

        def delete(self) -> None:
            pass

    class Toc:
        @staticmethod
        def get_element_by_complete_name(name: str) -> object | None:
            return object() if name == "pm.vbat" else None

    class Log:
        def __init__(self) -> None:
            self.toc = Toc()
            self.configs: list[FakeLogConfig] = []

        def add_config(self, config: FakeLogConfig) -> None:
            self.configs.append(config)

    class Crazyflie:
        def __init__(self) -> None:
            self.log = Log()

    class OldConfig:
        def __init__(self) -> None:
            self.stopped = False
            self.deleted = False

        def stop(self) -> None:
            self.stopped = True

        def delete(self) -> None:
            self.deleted = True

    events: list[tuple[str, RadioFailureKind, str]] = []
    old = OldConfig()
    crazyflie = Crazyflie()
    link = _cflib_link.CflibCrazyflieLink()
    link._cf = crazyflie
    link._connected = True
    link._connection_epoch = 4
    link._log_config_type = FakeLogConfig
    link._log_configs.append(old)
    monkeypatch.setattr(
        link,
        "_record_transport_event",
        lambda kind, failure, message: events.append((kind, failure, message)),
    )

    link.restart_observation_logs()

    assert old.stopped is True
    assert old.deleted is True
    assert link._connection_epoch == 4
    assert len(link._log_configs) == 1
    assert crazyflie.log.configs == link._log_configs
    assert link._received_at > 0.0
    assert link._values == {"pm.vbat": 4.1}
    assert [event[0] for event in events] == ["LOG_RESTART_ATTEMPT", "LOG_RESTARTED"]


def test_command_samples_use_cached_supervisor_log_without_synchronous_polling() -> None:
    class Supervisor:
        def read_bitfield(self) -> int:
            raise AssertionError("synchronous supervisor polling must not be used")

    class Crazyflie:
        supervisor = Supervisor()

    link = _cflib_link.CflibCrazyflieLink()
    link._cf = Crazyflie()
    link._connected = True
    link._values["supervisor.info"] = float((1 << 1) | (1 << 4))
    link._received_at = time.monotonic()
    link._supervisor_log_available = True
    link._log_data_event.set()
    link._supervisor_data_event.set()

    sample = link.read_sample()

    assert sample.supervisor_bitfield == (1 << 1) | (1 << 4)


def test_command_sample_waits_for_supervisor_specific_log() -> None:
    class Crazyflie:
        pass

    link = _cflib_link.CflibCrazyflieLink()
    link._cf = Crazyflie()
    link._connected = True
    link._received_at = time.monotonic()
    link._supervisor_log_available = True
    link._log_data_event.set()

    supervisor_arrival = threading.Timer(
        0.02,
        lambda: link._on_log_data(1_100, {"supervisor.info": float(1 << 1)}, None),
    )
    supervisor_arrival.start()
    try:
        sample = link.read_sample()
    finally:
        supervisor_arrival.join()

    assert sample.supervisor_bitfield == 1 << 1


@pytest.mark.asyncio
async def test_missing_supervisor_log_is_unknown_not_confirmed_disarmed() -> None:
    class MissingSupervisorLink(FakeCrazyflieLink):
        def read_sample(self) -> CrazyflieRawSample:
            sample = super().read_sample()
            return CrazyflieRawSample(
                source_timestamp_ms=sample.source_timestamp_ms,
                received_at_monotonic_s=sample.received_at_monotonic_s,
                values=sample.values,
                supervisor_bitfield=None,
                link_quality_percent=sample.link_quality_percent,
                link_latency_ms=sample.link_latency_ms,
                connected=sample.connected,
            )

    adapter = vehicle(MissingSupervisorLink())
    await adapter.connect()

    sample = await adapter.snapshot()

    assert sample.telemetry.state.value == "FAULT"
    assert "SUPERVISOR_STATE_UNKNOWN" in sample.telemetry.faults
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_supervisor_auto_arming_bit_is_retained_separately_from_armed() -> None:
    link = FakeCrazyflieLink()
    link.bitfield = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3)
    adapter = vehicle(link)

    await adapter.connect()
    sample = await adapter.snapshot()

    assert sample.telemetry.armed is True
    assert sample.telemetry.flying is False
    assert adapter.supervisor_auto_arming is True
    await adapter.disconnect()


def test_crtp_driver_initialization_is_process_wide_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCrtp:
        def __init__(self) -> None:
            self.calls = 0

        def init_drivers(self) -> None:
            self.calls += 1

    fake_crtp = FakeCrtp()
    monkeypatch.setattr(_cflib_link, "_CRTP_DRIVERS_INITIALIZED", False)

    _cflib_link._ensure_crtp_drivers_initialized(fake_crtp)
    _cflib_link._ensure_crtp_drivers_initialized(fake_crtp)

    assert fake_crtp.calls == 1


def test_cflib_ack_loss_threshold_defers_to_application_freshness_watchdog() -> None:
    configured: list[int] = []

    class FakeRadioDriverModule:
        @staticmethod
        def set_retries_before_disconnect(retries: int) -> None:
            configured.append(retries)

    _cflib_link._configure_radio_disconnect_policy(FakeRadioDriverModule)

    assert configured == [_cflib_link.RADIO_RETRIES_BEFORE_DISCONNECT]
    assert configured[0] >= 2**31 - 1


def test_cflib_connection_loss_reason_is_exposed_to_the_snapshot_path() -> None:
    link = _cflib_link.CflibCrazyflieLink()
    link._cf = object()
    link._connected = True

    link._on_connection_lost(URI, "Too many packets lost")

    with pytest.raises(RuntimeError, match="Too many packets lost"):
        link.read_observation_sample()


def test_radio_probe_measures_no_ack_and_contains_queue_saturation(tmp_path: Path) -> None:
    class Ack:
        def __init__(self, acknowledged: bool) -> None:
            self.ack = acknowledged

    acknowledgements = iter((Ack(False), Ack(False), Ack(True)))

    class Radio:
        def send_packet(self, _data: object) -> Ack:
            return next(acknowledgements)

    forwarded_errors: list[str] = []

    class Driver:
        def __init__(self) -> None:
            self._radio = Radio()
            self.out_queue: queue.Queue[object] = queue.Queue(1)
            self.link_error_callback = forwarded_errors.append

    class Crazyflie:
        def __init__(self) -> None:
            self.link = Driver()

    crazyflie = Crazyflie()
    link = _cflib_link.CflibCrazyflieLink(cache_directory=tmp_path / "cflib")
    link._connection_epoch = 1
    link._selected_uri_sha256 = "a" * 64
    link._cf = crazyflie
    link._connected = True
    link._install_radio_probe(crazyflie)

    crazyflie.link._radio.send_packet(b"first")
    crazyflie.link._radio.send_packet(b"second")
    crazyflie.link.link_error_callback(_cflib_link.QUEUE_SATURATION_MESSAGE)
    crazyflie.link._radio.send_packet(b"recovered")

    with link._lock:
        diagnostics = link._transport_snapshot_locked()
    assert diagnostics.acked_packet_count == 1
    assert diagnostics.lost_packet_count == 2
    assert diagnostics.packet_loss_percent == pytest.approx(200.0 / 3.0)
    assert diagnostics.maximum_consecutive_lost_packet_count == 2
    assert diagnostics.queue_saturation_count == 1
    assert diagnostics.failure_kind.value == "NONE"
    assert forwarded_errors == []
    link._stop_transport_journal()
    journal = tmp_path / "radio-transport-events.jsonl"
    assert journal.exists()
    assert URI not in journal.read_text(encoding="utf-8")

    crazyflie.link.link_error_callback("real USB failure")
    assert forwarded_errors == ["real USB failure"]
    link._restore_radio_probe()


def test_observation_latency_ping_is_disabled_before_connection_setup() -> None:
    class Latency:
        def __init__(self) -> None:
            self.start_calls = 0
            self.stop_calls = 0
            self._ping_thread_instance: threading.Thread | None = None
            self._stop_event = threading.Event()

        def start(self) -> None:
            self.start_calls += 1

        def stop(self) -> None:
            self.stop_calls += 1

    class LinkStatistics:
        latency = Latency()

    class Crazyflie:
        link_statistics = LinkStatistics()

    crazyflie = Crazyflie()
    link = _cflib_link.CflibCrazyflieLink(enable_latency_pings=False)

    link._configure_latency_statistics(crazyflie)
    crazyflie.link_statistics.latency.start()
    crazyflie.link_statistics.latency.stop()

    assert crazyflie.link_statistics.latency.start_calls == 0
    assert crazyflie.link_statistics.latency.stop_calls == 1


def test_latency_ping_thread_can_signal_its_own_stop_without_joining() -> None:
    class Latency:
        def __init__(self) -> None:
            self.stop_calls = 0
            self._ping_thread_instance = threading.current_thread()
            self._stop_event = threading.Event()

        def start(self) -> None:
            return

        def stop(self) -> None:
            self.stop_calls += 1
            raise AssertionError("the ping thread must not join itself")

    class LinkStatistics:
        latency = Latency()

    class Crazyflie:
        link_statistics = LinkStatistics()

    crazyflie = Crazyflie()
    link = _cflib_link.CflibCrazyflieLink(enable_latency_pings=True)

    link._configure_latency_statistics(crazyflie)
    crazyflie.link_statistics.latency.stop()

    assert crazyflie.link_statistics.latency._stop_event.is_set()
    assert crazyflie.link_statistics.latency.stop_calls == 0


def test_disconnect_keeps_queue_saturation_contained_until_link_is_closed(
    tmp_path: Path,
) -> None:
    forwarded_errors: list[str] = []

    class Radio:
        def send_packet(self, _data: object) -> object:
            return object()

    class Driver:
        def __init__(self) -> None:
            self._radio = Radio()
            self.out_queue: queue.Queue[object] = queue.Queue(1)
            self.link_error_callback = forwarded_errors.append

    class Crazyflie:
        def __init__(self) -> None:
            self.link = Driver()

    crazyflie = Crazyflie()

    class SyncCrazyflie:
        def __init__(self) -> None:
            self.cf = self
            self._disconnect_event: threading.Event | None = None
            self._params_updated_event = threading.Event()
            self._is_link_open = True
            self.callbacks_removed = False

        def is_link_open(self) -> bool:
            return self._is_link_open

        def close_link(self) -> None:
            crazyflie.link.link_error_callback(_cflib_link.QUEUE_SATURATION_MESSAGE)
            assert self._disconnect_event is not None
            self._disconnect_event.set()

        def _remove_callbacks(self) -> None:
            self.callbacks_removed = True

    scf = SyncCrazyflie()
    link = _cflib_link.CflibCrazyflieLink(cache_directory=tmp_path / "cflib")
    link._connection_epoch = 1
    link._selected_uri_sha256 = "a" * 64
    link._scf = scf
    link._cf = crazyflie
    link._connected = True
    link._install_radio_probe(crazyflie)

    link.disconnect()

    assert forwarded_errors == []
    assert link._queue_saturation_count == 1
    assert scf.callbacks_removed is True


def test_new_command_is_rejected_while_radio_queue_is_saturated() -> None:
    class Supervisor:
        def send_arming_request(self, _armed: bool) -> None:
            raise AssertionError("unhealthy command must not be dispatched")

    class Driver:
        def __init__(self) -> None:
            self.out_queue: queue.Queue[object] = queue.Queue(1)
            self.out_queue.put(object())

    class Crazyflie:
        supervisor = Supervisor()
        link = Driver()

    link = _cflib_link.CflibCrazyflieLink()
    link._cf = Crazyflie()
    link._connected = True

    with pytest.raises(RuntimeError, match="queue is saturated"):
        link.request_arm(True)


def test_cflib_reconnect_waits_for_asynchronous_radio_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSharedRadio:
        def __init__(self) -> None:
            self._lock = threading.Semaphore(1)
            self._radio: object | None = object()

    shared_radio = FakeSharedRadio()

    class FakeRadioDriver:
        @staticmethod
        def parse_uri(_uri: str) -> tuple[int, int, int, list[int], None]:
            return (0, 80, 2, [0xE7] * 5, None)

    class FakeRadioManager:
        _lock = threading.Semaphore(1)
        _radios: ClassVar[list[FakeSharedRadio]] = [shared_radio]

    class FakeRadioDriverModule:
        RadioDriver = FakeRadioDriver
        RadioManager = FakeRadioManager

    sleep_calls = 0

    def finish_queued_close(_duration_s: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        with shared_radio._lock:
            shared_radio._radio = None

    monkeypatch.setattr(_cflib_link.time, "sleep", finish_queued_close)

    _cflib_link._wait_for_shared_radio_release(
        FakeRadioDriverModule,
        URI,
        timeout_s=0.1,
    )

    assert sleep_calls == 1


def test_cflib_reconnect_clears_registration_leaked_by_failed_usb_reopen() -> None:
    class FakeSharedRadio:
        def __init__(self) -> None:
            self._lock = threading.Semaphore(1)
            self._radio = None
            self._rsp_queues = {7: queue.Queue()}

    shared_radio = FakeSharedRadio()

    class FakeRadioDriver:
        @staticmethod
        def parse_uri(_uri: str) -> tuple[int, int, int, list[int], None]:
            return (0, 80, 2, [0xE7] * 5, None)

    class FakeRadioManager:
        _lock = threading.Semaphore(1)
        _radios: ClassVar[list[FakeSharedRadio]] = [shared_radio]

    class FakeRadioDriverModule:
        RadioDriver = FakeRadioDriver
        RadioManager = FakeRadioManager

    _cflib_link._wait_for_shared_radio_release(
        FakeRadioDriverModule,
        URI,
        timeout_s=0.1,
    )

    assert shared_radio._rsp_queues == {}


def test_cflib_connection_handshake_has_a_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCrazyflie:
        def __init__(self) -> None:
            self.close_calls = 0

        def open_link(self, _uri: str) -> None:
            return

        def close_link(self) -> None:
            self.close_calls += 1

    class FakeSyncCrazyflie:
        def __init__(self) -> None:
            self.cf = FakeCrazyflie()
            self._link_uri = URI
            self._connect_event = threading.Event()
            self._params_updated_event = threading.Event()
            self._is_link_open = False
            self.callbacks_removed = False

        def is_link_open(self) -> bool:
            return False

        def _add_callbacks(self) -> None:
            return

        def _remove_callbacks(self) -> None:
            self.callbacks_removed = True

    scf = FakeSyncCrazyflie()
    monkeypatch.setattr(_cflib_link, "CONNECTION_TIMEOUT_S", 0.001)

    with pytest.raises(TimeoutError, match="did not finish"):
        _cflib_link.CflibCrazyflieLink._open_link_bounded(scf)

    assert scf.callbacks_removed is True
    assert scf.cf.close_calls == 1


def test_cflib_disconnect_callback_wait_has_a_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCrazyflie:
        def close_link(self) -> None:
            # Reproduce cflib's broken callback chain: the underlying close
            # returns, but SyncCrazyflie's disconnect event is never signalled.
            return

    class FakeSyncCrazyflie:
        def __init__(self) -> None:
            self.cf = FakeCrazyflie()
            self._disconnect_event: threading.Event | None = None
            self._params_updated_event = threading.Event()
            self._is_link_open = True
            self.callbacks_removed = False

        def is_link_open(self) -> bool:
            return self._is_link_open

        def _remove_callbacks(self) -> None:
            self.callbacks_removed = True

    scf = FakeSyncCrazyflie()
    monkeypatch.setattr(_cflib_link, "DISCONNECTION_CALLBACK_TIMEOUT_S", 0.001)

    cleanup_error = _cflib_link.CflibCrazyflieLink._close_link_bounded(scf)

    assert cleanup_error is not None
    assert "did not finish" in cleanup_error
    assert scf._is_link_open is False
    assert scf.callbacks_removed is True


class FakeCrazyflieLink:
    def __init__(
        self,
        *,
        flow: int = 1,
        multiranger: int = 1,
        high_level_enabled: str = "1",
    ) -> None:
        self.connect_calls: list[str] = []
        self.disconnect_calls = 0
        self.commands: list[tuple[object, ...]] = []
        self.flow = flow
        self.multiranger = multiranger
        self.high_level_enabled = high_level_enabled
        self.connected = False
        self.bitfield = 1 << 0
        self.timestamp_ms = 1_000
        self.fail_next_move = False
        self.estimator_reset_calls = 0
        self.crash_recovery_calls = 0
        self.motor_selection: str | None = None
        self.observation_reads = 0
        self.values = {
            "stateEstimate.x": 0.0,
            "stateEstimate.y": 0.0,
            "stateEstimate.z": 0.0,
            "stateEstimate.vx": 0.0,
            "stateEstimate.vy": 0.0,
            "stateEstimate.vz": 0.0,
            "stabilizer.roll": 0.0,
            "stabilizer.pitch": 0.0,
            "stabilizer.yaw": 90.0,
            "stateEstimate.qw": 1.0,
            "stateEstimate.qx": 0.0,
            "stateEstimate.qy": 0.0,
            "stateEstimate.qz": 0.0,
            "kalman.varPX": 0.001,
            "kalman.varPY": 0.002,
            "kalman.varPZ": 0.003,
            "range.front": 500.0,
            "range.back": 5_000.0,
            "range.left": 600.0,
            "range.right": 700.0,
            "range.up": 800.0,
            "range.zrange": 300.0,
            "pm.vbat": 4.0,
            "pm.batteryLevel": 80.0,
            "motion.squal": 204.0,
            "acc.x": 0.0,
            "acc.y": 0.0,
            "acc.z": 1.0,
            "gyro.x": 0.0,
            "gyro.y": 0.0,
            "gyro.z": 0.0,
            "motor.m1": 0.0,
            "motor.m2": 0.0,
            "motor.m3": 0.0,
            "motor.m4": 0.0,
        }

    def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata:
        self.connect_calls.append(selected_uri)
        self.connected = True
        return CrazyflieConnectionMetadata(
            selected_uri=selected_uri,
            connected_uri=selected_uri,
            protocol_version=12,
            firmware_version="2026.06",
            deck_parameters={
                "deck.bcFlow2": self.flow,
                "deck.bcMultiranger": self.multiranger,
            },
            observed_parameters={
                "commander.enHighLevel": self.high_level_enabled,
                "stabilizer.controller": "1",
                "stabilizer.estimator": "2",
            },
            available_log_variables=frozenset((*self.values, "supervisor.info")),
        )

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def read_sample(self) -> CrazyflieRawSample:
        return CrazyflieRawSample(
            source_timestamp_ms=self.timestamp_ms,
            received_at_monotonic_s=time.monotonic(),
            values=dict(self.values),
            supervisor_bitfield=self.bitfield,
            link_quality_percent=90.0,
            link_latency_ms=4.0,
            connected=self.connected,
        )

    def read_observation_sample(self) -> CrazyflieRawSample:
        self.observation_reads += 1
        return self.read_sample()

    def reset_estimator(self) -> None:
        self.estimator_reset_calls += 1
        self.values["kalman.varPX"] = 0.001
        self.values["kalman.varPY"] = 0.001
        self.values["kalman.varPZ"] = 0.001

    def recover_from_crash(self) -> None:
        self.crash_recovery_calls += 1
        self.bitfield &= ~((1 << 5) | (1 << 7))

    def begin_motor_power_override(self, motor_selection: str) -> None:
        self.motor_selection = motor_selection
        self.commands.append(("motor-bench-start", motor_selection))

    def set_motor_power_percent(self, motor_selection: str, percent: float) -> None:
        self.commands.append(("motor-power", motor_selection, percent))
        selected = ("m1", "m2", "m3", "m4") if motor_selection == "all" else (motor_selection,)
        for motor in ("m1", "m2", "m3", "m4"):
            self.values[f"motor.{motor}"] = percent / 100.0 * 65_535.0 if motor in selected else 0.0

    def feed_motor_watchdog(self) -> None:
        self.commands.append(("motor-watchdog",))

    def end_motor_power_override(self) -> None:
        self.commands.append(("motor-bench-stop",))
        self.motor_selection = None
        for motor in ("m1", "m2", "m3", "m4"):
            self.values[f"motor.{motor}"] = 0.0

    def request_arm(self, armed: bool) -> None:
        self.commands.append(("arm", armed))
        if armed:
            self.bitfield |= 1 << 1
        else:
            self.bitfield &= ~(1 << 1)

    def takeoff(self, height_m: float, duration_s: float, yaw_rad: float | None) -> None:
        self.commands.append(("takeoff", height_m, duration_s, yaw_rad))
        self.bitfield |= (1 << 1) | (1 << 4)
        self.values["stateEstimate.z"] = height_m

    def land(self, height_m: float, duration_s: float) -> None:
        self.commands.append(("land", height_m, duration_s))
        self.bitfield &= ~(1 << 4)
        self.values["stateEstimate.z"] = height_m

    def go_to_relative(
        self,
        x_m: float,
        y_m: float,
        z_m: float,
        yaw_rad: float,
        duration_s: float,
    ) -> None:
        self.commands.append(("move", x_m, y_m, z_m, yaw_rad, duration_s))
        if self.fail_next_move:
            raise RuntimeError("radio acknowledgement disappeared")
        self.values["stateEstimate.x"] += x_m
        self.values["stateEstimate.y"] += y_m
        self.values["stateEstimate.z"] += z_m

    def hold_position(self, duration_s: float) -> None:
        self.commands.append(("hold", duration_s))

    def stream_body_rate_thrust(
        self,
        setpoints: tuple[BodyRateThrustSetpoint, ...],
        sample_period_s: float,
    ) -> None:
        self.commands.append(("body-rate-thrust", setpoints, sample_period_s))

    def cancel_body_rate_thrust(self) -> None:
        self.commands.append(("body-rate-cancel",))

    def emergency_stop(self) -> None:
        self.commands.append(("emergency",))
        self.bitfield &= ~((1 << 1) | (1 << 4))


def vehicle(link: FakeCrazyflieLink | None = None) -> CrazyflieVehicle:
    return CrazyflieVehicle(vehicle_id="cf01", selected_uri=URI, link=link or FakeCrazyflieLink())


def permit(scope: PermitScope) -> CommandPermit:
    now = datetime.now(UTC)
    return CommandPermit(
        permit_id=f"permit-{scope.value.lower()}",
        vehicle_id="cf01",
        selected_uri=URI,
        operator_id="operator",
        scope=scope,
        issued_at_utc=now,
        expires_at_utc=now + timedelta(minutes=5),
        operator_present=True,
        props_removed=scope is PermitScope.PROPS_OFF_BENCH,
        physically_restrained=True,
        flight_entry_record_id=("flight-entry" if scope is PermitScope.CONTAINED_FLIGHT else None),
        flight_entry_evidence_sha256=(SHA if scope is PermitScope.CONTAINED_FLIGHT else None),
    )


def command(payload: object, command_id: str = "cmd-1") -> CommandEnvelope:
    return CommandEnvelope(
        vehicle_id="cf01",
        command_id=command_id,
        issued_at_monotonic_s=time.monotonic(),
        source=CommandSource.TEST,
        mode=OperatingMode.LIVE,
        payload=payload,
    )


def test_construction_is_inert_and_declares_physical_authority() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    assert link.connect_calls == []
    assert adapter.backend_profile.role is BackendRole.REAL_CRAZYFLIE
    assert adapter.backend_profile.authority is AuthorityClass.PHYSICAL
    assert VehicleCapability.RELATIVE_POSITIONING not in adapter.capabilities.features


@pytest.mark.asyncio
async def test_observation_conformance_measures_decks_and_never_arms() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    await assert_vehicle_conformance(adapter)
    assert link.connect_calls == [URI]
    assert not any(item[0] == "arm" for item in link.commands)


@pytest.mark.asyncio
async def test_connected_observer_link_can_be_borrowed_without_reconnecting() -> None:
    link = FakeCrazyflieLink()
    observer = CrazyflieVehicle(
        vehicle_id="observer",
        selected_uri=URI,
        link=link,
        observation_only=True,
    )
    await observer.connect()

    command_vehicle = observer.borrow_connected_command_adapter(vehicle_id="cf01")
    command_vehicle.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))
    await command_vehicle.execute(command(ArmCommand(), "borrowed-arm"))
    await command_vehicle.disconnect()

    assert link.connect_calls == [URI]
    assert link.disconnect_calls == 0
    assert ("arm", True) in link.commands
    assert (await observer.snapshot()).telemetry.armed is True

    await observer.disconnect()
    assert link.disconnect_calls == 1


@pytest.mark.asyncio
async def test_missing_required_deck_fails_closed_and_disconnects() -> None:
    link = FakeCrazyflieLink(multiranger=0)
    adapter = vehicle(link)
    with pytest.raises(CrazySwarmError) as rejected:
        await adapter.connect()
    assert rejected.value.code is ErrorCode.PREFLIGHT_FAILED
    assert rejected.value.details == {"missing_deck_parameters": ["deck.bcMultiranger"]}
    assert link.disconnect_calls == 1


@pytest.mark.asyncio
async def test_deprecated_high_level_commander_parameter_does_not_block_current_firmware() -> None:
    link = FakeCrazyflieLink(high_level_enabled="0")
    adapter = vehicle(link)
    await adapter.connect()
    assert link.commands == []
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_command_adapter_can_reset_and_confirm_estimator_convergence() -> None:
    link = FakeCrazyflieLink()
    link.values["kalman.varPX"] = 5.0
    adapter = vehicle(link)
    await adapter.connect()

    sample = await adapter.reset_estimator(timeout_s=1.0)

    assert link.estimator_reset_calls == 1
    assert sample.telemetry.estimator is not None
    assert sample.telemetry.estimator.converged is True
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_commands_require_permit_and_bench_scope_cannot_fly() -> None:
    adapter = vehicle()
    await adapter.connect()
    with pytest.raises(CrazySwarmError) as no_permit:
        await adapter.execute(command(ArmCommand()))
    assert no_permit.value.code is ErrorCode.MODE_NOT_AUTHORIZED
    adapter.install_command_permit(permit(PermitScope.PROPS_OFF_BENCH))
    await adapter.execute(command(ArmCommand(), "arm-bench"))
    with pytest.raises(CrazySwarmError) as flight_rejected:
        await adapter.execute(command(TakeoffCommand(height_m=0.2, duration_s=0.01)))
    assert flight_rejected.value.code is ErrorCode.MODE_NOT_AUTHORIZED
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_body_move_uses_latest_measured_yaw_and_preserves_home_mapping() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    await adapter.connect()
    adapter.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))
    await adapter.execute(
        command(
            MoveRelativeCommand(
                x_m=0.2,
                duration_s=0.01,
                frame=CoordinateFrame.BODY,
            ),
            "move-body",
        )
    )
    mapped = link.commands[-1]
    assert mapped[0] == "move"
    assert mapped[1] == pytest.approx(0.0, abs=1e-9)
    assert mapped[2] == pytest.approx(0.2)
    await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trigger", "configure"),
    (
        (
            "near_floor",
            lambda link: link.values.update(
                {"stateEstimate.z": 0.02, "range.zrange": 20.0}
            ),
        ),
        (
            "estimator_unconverged",
            lambda link: link.values.update(
                {"kalman.varPX": 1.0, "kalman.varPY": 1.0, "kalman.varPZ": 1.0}
            ),
        ),
        (
            "excessive_tilt",
            lambda link: link.values.update({"stabilizer.roll": 25.0}),
        ),
        (
            "actuator_saturation_with_voltage_sag",
            lambda link: link.values.update(
                {
                    "pm.vbat": 3.6,
                    "motor.m1": 0.98 * 65_535.0,
                    "motor.m2": 0.98 * 65_535.0,
                    "motor.m3": 0.98 * 65_535.0,
                    "motor.m4": 0.98 * 65_535.0,
                }
            ),
        ),
    ),
)
async def test_sustained_airborne_instability_fails_closed_with_measured_details(
    trigger: str,
    configure: Callable[[FakeCrazyflieLink], None],
) -> None:
    link = FakeCrazyflieLink()
    link.bitfield |= (1 << 1) | (1 << 4)
    link.values["stateEstimate.z"] = 0.3
    configure(link)
    adapter = CrazyflieVehicle(
        vehicle_id="cf01",
        selected_uri=URI,
        link=link,
        telemetry_period_s=0.01,
    )
    await adapter.connect()
    adapter.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))

    with pytest.raises(CrazySwarmError) as rejected:
        await adapter.execute(command(HoverCommand(duration_s=0.4), f"guard-{trigger}"))

    assert rejected.value.code is ErrorCode.PREFLIGHT_FAILED
    assert rejected.value.details["trigger"] == trigger
    assert rejected.value.details["command_kind"] == "hover"
    assert "observed" in rejected.value.details
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_isolated_packet_loss_does_not_trip_airborne_stability_guard() -> None:
    class IsolatedLossLink(FakeCrazyflieLink):
        def read_sample(self) -> CrazyflieRawSample:
            sample = super().read_sample()
            return CrazyflieRawSample(
                source_timestamp_ms=sample.source_timestamp_ms,
                received_at_monotonic_s=sample.received_at_monotonic_s,
                values=sample.values,
                supervisor_bitfield=sample.supervisor_bitfield,
                link_quality_percent=98.0,
                radio_transport=RadioTransportDiagnostics(
                    connection_epoch=1,
                    state="DEGRADED",
                    failure_kind=RadioFailureKind.RF_ACK_LOSS,
                    acked_packet_count=980,
                    lost_packet_count=20,
                    packet_loss_percent=2.0,
                    consecutive_lost_packet_count=1,
                    maximum_consecutive_lost_packet_count=1,
                    outbound_queue_depth=0,
                    outbound_queue_capacity=1,
                    last_ack_age_ms=2.0,
                ),
                connected=sample.connected,
            )

    link = IsolatedLossLink()
    link.bitfield |= (1 << 1) | (1 << 4)
    link.values["stateEstimate.z"] = 0.3
    adapter = CrazyflieVehicle(
        vehicle_id="cf01",
        selected_uri=URI,
        link=link,
        telemetry_period_s=0.01,
    )
    await adapter.connect()
    adapter.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))

    acknowledgement = await adapter.execute(
        command(HoverCommand(duration_s=0.05), "isolated-loss-hover")
    )

    assert acknowledgement.status.value == "COMPLETED"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_body_rate_stream_requires_flight_permit_and_dispatches_once() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    payload = BodyRateThrustCommand(
        profile_id="test-single-roll",
        sample_period_s=0.01,
        duration_s=0.02,
        setpoints=(
            BodyRateThrustSetpoint(roll_rate_deg_s=800.0, thrust_percent=80.0),
            BodyRateThrustSetpoint(thrust_percent=60.0),
        ),
    )
    await adapter.connect()
    adapter.install_command_permit(permit(PermitScope.PROPS_OFF_BENCH))
    with pytest.raises(CrazySwarmError) as rejected:
        await adapter.execute(command(payload, "bench-rate-stream"))
    assert rejected.value.code is ErrorCode.MODE_NOT_AUTHORIZED

    adapter.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))
    await adapter.execute(command(payload, "flight-rate-stream"))

    streams = [item for item in link.commands if item[0] == "body-rate-thrust"]
    assert streams == [("body-rate-thrust", payload.setpoints, 0.01)]
    assert VehicleCapability.BODY_RATE_THRUST in adapter.capabilities.features
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_body_rate_stream_is_interrupted_outside_its_measured_xy_box() -> None:
    class DriftingBodyRateLink(FakeCrazyflieLink):
        def __init__(self) -> None:
            super().__init__()
            self.release_stream = threading.Event()

        def stream_body_rate_thrust(
            self,
            setpoints: tuple[BodyRateThrustSetpoint, ...],
            sample_period_s: float,
        ) -> None:
            self.commands.append(("body-rate-thrust", setpoints, sample_period_s))
            self.values["stateEstimate.x"] = 0.51
            if not self.release_stream.wait(timeout=1.0):
                raise RuntimeError("test stream was not interrupted")

        def cancel_body_rate_thrust(self) -> None:
            self.commands.append(("body-rate-cancel",))
            self.release_stream.set()

    link = DriftingBodyRateLink()
    adapter = vehicle(link)
    payload = BodyRateThrustCommand(
        profile_id="bounded-single-roll",
        sample_period_s=0.01,
        duration_s=0.02,
        max_abs_xy_displacement_m=0.50,
        setpoints=(
            BodyRateThrustSetpoint(roll_rate_deg_s=800.0, thrust_percent=80.0),
            BodyRateThrustSetpoint(thrust_percent=60.0),
        ),
    )
    await adapter.connect()
    adapter.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))

    with pytest.raises(CrazySwarmError) as rejected:
        await adapter.execute(command(payload, "bounded-rate-stream"))

    assert rejected.value.code is ErrorCode.PREFLIGHT_FAILED
    assert rejected.value.details["dx_m"] == pytest.approx(0.51)
    assert [item[0] for item in link.commands][-2:] == [
        "body-rate-thrust",
        "body-rate-cancel",
    ]
    await adapter.disconnect()


def test_cflib_body_rate_stream_uses_rate_mode_and_releases_commander(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class Commander:
        def send_setpoint_manual(
            self,
            roll: float,
            pitch: float,
            yaw_rate: float,
            thrust: float,
            *,
            rate: bool,
        ) -> None:
            calls.append(("manual", roll, pitch, yaw_rate, thrust, rate))

        def send_notify_setpoint_stop(self) -> None:
            calls.append(("release",))

    class Crazyflie:
        commander = Commander()

    clock_s = 10.0

    def monotonic() -> float:
        return clock_s

    def sleep(duration_s: float) -> None:
        nonlocal clock_s
        clock_s += duration_s

    monkeypatch.setattr(_cflib_link.time, "monotonic", monotonic)  # type: ignore[attr-defined]
    monkeypatch.setattr(_cflib_link.time, "sleep", sleep)  # type: ignore[attr-defined]
    link = _cflib_link.CflibCrazyflieLink()
    link._cf = Crazyflie()
    link._connected = True
    setpoints = (
        BodyRateThrustSetpoint(roll_rate_deg_s=1_200.0, thrust_percent=100.0),
        BodyRateThrustSetpoint(thrust_percent=100.0),
    )

    link.stream_body_rate_thrust(setpoints, 0.01)

    assert calls == [
        ("manual", 1_200.0, 0.0, 0.0, 100.0, True),
        ("manual", 0.0, 0.0, 0.0, 100.0, True),
        ("release",),
    ]
    assert clock_s == pytest.approx(10.02)


def test_cflib_body_rate_stream_releases_priority_and_lock_after_send_failure() -> None:
    calls: list[str] = []

    class Commander:
        fail = True

        def send_setpoint_manual(self, *_args: object, **_kwargs: object) -> None:
            calls.append("manual")
            if self.fail:
                self.fail = False
                raise RuntimeError("radio queue rejected setpoint")

        def send_notify_setpoint_stop(self) -> None:
            calls.append("release")

    class Crazyflie:
        commander = Commander()

    link = _cflib_link.CflibCrazyflieLink()
    link._cf = Crazyflie()
    link._connected = True
    setpoints = (
        BodyRateThrustSetpoint(roll_rate_deg_s=800.0, thrust_percent=80.0),
        BodyRateThrustSetpoint(thrust_percent=60.0),
    )

    with pytest.raises(RuntimeError, match="radio queue rejected"):
        link.stream_body_rate_thrust(setpoints, 0.005)
    link.stream_body_rate_thrust(setpoints, 0.005)

    assert calls == ["manual", "release", "manual", "manual", "release"]


@pytest.mark.asyncio
async def test_real_telemetry_units_validity_and_unsupported_fields_are_explicit() -> None:
    adapter = vehicle()
    await adapter.connect()
    sample = await adapter.snapshot()
    telemetry = sample.telemetry
    assert telemetry.ground_truth_position_m is None
    assert telemetry.motors is None
    assert telemetry.motor_pwm_percent == pytest.approx((0.0, 0.0, 0.0, 0.0))
    assert telemetry.ranges is not None
    assert telemetry.ranges.front_m == pytest.approx(0.5)
    assert telemetry.ranges.back_m is None
    assert telemetry.ranges.statuses["back"].value == "NO_HIT"
    assert telemetry.imu is not None
    assert telemetry.imu.acceleration_body_m_s2.z == pytest.approx(9.80665)
    assert telemetry.estimator is not None
    assert telemetry.estimator.position_variance_m2 is not None
    assert telemetry.transport is not None
    assert telemetry.transport.source_class == "MEASURED_REAL"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_stale_motor_log_values_are_not_reported_as_current_pwm() -> None:
    class StaleMotorLink(FakeCrazyflieLink):
        def read_sample(self) -> CrazyflieRawSample:
            sample = super().read_sample()
            received_at = sample.received_at_monotonic_s
            value_timestamps = {name: received_at for name in sample.values}
            for index in range(1, 5):
                value_timestamps[f"motor.m{index}"] = received_at - 2.0
            return CrazyflieRawSample(
                source_timestamp_ms=sample.source_timestamp_ms,
                received_at_monotonic_s=received_at,
                values=sample.values,
                value_received_at_monotonic_s=value_timestamps,
                supervisor_bitfield=sample.supervisor_bitfield,
                link_quality_percent=sample.link_quality_percent,
                link_latency_ms=sample.link_latency_ms,
                connected=sample.connected,
            )

    adapter = vehicle(StaleMotorLink())
    await adapter.connect()

    sample = await adapter.snapshot()

    assert sample.telemetry.motor_pwm_percent is None
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_physical_packet_loss_counts_no_ack_outcomes_not_retry_quality() -> None:
    class DiagnosticLink(FakeCrazyflieLink):
        def read_sample(self) -> CrazyflieRawSample:
            sample = super().read_sample()
            return CrazyflieRawSample(
                source_timestamp_ms=sample.source_timestamp_ms,
                received_at_monotonic_s=sample.received_at_monotonic_s,
                values=sample.values,
                supervisor_bitfield=sample.supervisor_bitfield,
                link_quality_percent=92.0,
                radio_transport=RadioTransportDiagnostics(
                    connection_epoch=2,
                    state="DEGRADED",
                    failure_kind=RadioFailureKind.RF_ACK_LOSS,
                    acked_packet_count=75,
                    lost_packet_count=25,
                    packet_loss_percent=25.0,
                    retry_quality_percent=92.0,
                ),
                connected=sample.connected,
            )

    adapter = vehicle(DiagnosticLink())
    await adapter.connect()

    snapshot = await adapter.snapshot()

    assert snapshot.telemetry.link_quality_percent == 92.0
    assert snapshot.telemetry.packet_loss_percent == 25.0
    assert snapshot.telemetry.transport is not None
    assert snapshot.telemetry.transport.delivery_quality_percent == 75.0
    assert snapshot.telemetry.transport.radio is not None
    assert snapshot.telemetry.transport.radio.lost_packet_count == 25
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_zero_startup_quaternion_is_temporarily_unavailable_not_fatal() -> None:
    link = FakeCrazyflieLink()
    for component in ("qw", "qx", "qy", "qz"):
        link.values[f"stateEstimate.{component}"] = 0.0
    adapter = vehicle(link)

    await adapter.connect()
    startup = await adapter.snapshot()

    assert startup.telemetry.quaternion is None
    assert startup.telemetry.attitude is not None
    link.values["stateEstimate.qw"] = 1.0
    initialized = await adapter.snapshot()
    assert initialized.telemetry.quaternion is not None
    assert initialized.telemetry.quaternion.w == pytest.approx(1.0)
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_firmware_clock_small_rollback_starts_new_one_based_epoch() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    await adapter.connect()
    first = await adapter.snapshot()
    assert first.source_clock_id == "crazyflie-firmware"
    assert first.source_clock_epoch == 1
    assert first.source_timestamp_s == pytest.approx(1.0)

    link.timestamp_ms = 900
    reset = await adapter.snapshot()
    assert reset.source_clock_epoch == 2
    assert reset.source_timestamp_s == pytest.approx(0.9)
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lost_command_acknowledgement_is_unknown_and_never_retry_safe() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    await adapter.connect()
    adapter.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))
    link.fail_next_move = True
    with pytest.raises(CrazySwarmError) as unknown:
        await adapter.execute(
            command(MoveRelativeCommand(x_m=0.1, duration_s=0.01), "unknown-move")
        )
    assert unknown.value.code is ErrorCode.LINK_LOST
    assert unknown.value.details["command_outcome"] == "UNKNOWN_OUTCOME"
    assert unknown.value.details["automatic_retry_safe"] is False
    assert len([item for item in link.commands if item[0] == "move"]) == 1
    await adapter.disconnect()


def test_invalid_or_implicit_radio_uri_is_rejected_before_driver_access() -> None:
    with pytest.raises(ValueError, match="full explicit"):
        CrazyflieVehicle(
            vehicle_id="cf01",
            selected_uri="radio://0/80/2M",
            link=FakeCrazyflieLink(),
        )
