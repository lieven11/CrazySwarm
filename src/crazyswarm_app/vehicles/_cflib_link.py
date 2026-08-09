from __future__ import annotations

import importlib
import threading
import time
from pathlib import Path
from typing import Any

from crazyswarm_app.vehicles.crazyflie_link import (
    CrazyflieConnectionMetadata,
    CrazyflieRawSample,
)

LOG_GROUPS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    (
        "state",
        20,
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
        20,
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
        20,
        (
            "stateEstimate.qw",
            "stateEstimate.qx",
            "stateEstimate.qy",
            "stateEstimate.qz",
        ),
    ),
    (
        "imu",
        20,
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
        100,
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
        100,
        (
            "pm.vbat",
            "pm.batteryLevel",
            "motion.deltaX",
            "motion.deltaY",
            "motion.squal",
        ),
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


class CflibCrazyflieLink:
    """cflib-only implementation isolated from generic contracts.

    Driver initialization and all radio access happen only in ``connect`` or the
    explicit ``discover`` method. Constructing this object is inert.
    """

    def __init__(self, *, cache_directory: Path = Path(".cache/crazyswarm/cflib")) -> None:
        self._cache_directory = cache_directory
        self._scf: Any | None = None
        self._cf: Any | None = None
        self._log_configs: list[Any] = []
        self._lock = threading.Lock()
        self._values: dict[str, float] = {}
        self._timestamp_ms = 0
        self._received_at = 0.0
        self._link_quality: float | None = None
        self._link_latency_ms: float | None = None
        self._log_errors: list[str] = []
        self._connected = False

    @staticmethod
    def discover() -> tuple[str, ...]:
        crtp = importlib.import_module("cflib.crtp")
        crtp.init_drivers()
        found = crtp.scan_interfaces()
        return tuple(sorted(str(item[0]) for item in found))

    def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata:
        if self._scf is not None:
            raise RuntimeError("Crazyflie link is already open")
        crtp = importlib.import_module("cflib.crtp")
        crazyflie_module = importlib.import_module("cflib.crazyflie")
        sync_module = importlib.import_module("cflib.crazyflie.syncCrazyflie")
        log_module = importlib.import_module("cflib.crazyflie.log")
        crtp.init_drivers()
        self._cache_directory.mkdir(parents=True, exist_ok=True)
        crazyflie = crazyflie_module.Crazyflie(rw_cache=str(self._cache_directory))
        scf = sync_module.SyncCrazyflie(selected_uri, cf=crazyflie)
        try:
            scf.open_link()
            scf.wait_for_params()
            self._scf = scf
            self._cf = crazyflie
            self._connected = True
            crazyflie.disconnected.add_callback(self._on_disconnected)
            crazyflie.connection_lost.add_callback(self._on_connection_lost)
            crazyflie.link_statistics.link_quality_updated.add_callback(self._on_link_quality)
            crazyflie.link_statistics.latency_updated.add_callback(self._on_link_latency)
            deck_parameters = {
                name: self._parameter_as_int(crazyflie, name) for name in REQUIRED_DECK_PARAMETERS
            }
            observed_parameters = {
                name: value
                for name in QUALIFICATION_PARAMETERS
                if (value := self._parameter_value(crazyflie, name)) is not None
            }
            available = self._start_logs(crazyflie, log_module.LogConfig)
            firmware = self._firmware_identity(observed_parameters)
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
            try:
                scf.close_link()
            finally:
                self._scf = None
                self._cf = None
            raise

    def disconnect(self) -> None:
        scf = self._scf
        if scf is None:
            self._connected = False
            return
        for config in tuple(self._log_configs):
            try:
                config.stop()
                config.delete()
            except Exception as error:
                with self._lock:
                    self._log_errors.append(f"log shutdown: {error}")
        self._log_configs.clear()
        try:
            scf.close_link()
        finally:
            self._connected = False
            self._scf = None
            self._cf = None

    def read_sample(self) -> CrazyflieRawSample:
        cf = self._require_connected()
        supervisor_bitfield = int(cf.supervisor.read_bitfield())
        with self._lock:
            return CrazyflieRawSample(
                source_timestamp_ms=self._timestamp_ms,
                received_at_monotonic_s=self._received_at or time.monotonic(),
                values=dict(self._values),
                supervisor_bitfield=supervisor_bitfield,
                link_quality_percent=self._link_quality,
                link_latency_ms=self._link_latency_ms,
                connected=self._connected,
                log_errors=tuple(self._log_errors),
            )

    def request_arm(self, armed: bool) -> None:
        self._require_connected().supervisor.send_arming_request(armed)

    def takeoff(self, height_m: float, duration_s: float, yaw_rad: float | None) -> None:
        self._require_connected().high_level_commander.takeoff(
            height_m,
            duration_s,
            yaw=yaw_rad,
        )

    def land(self, height_m: float, duration_s: float) -> None:
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
        self._require_connected().high_level_commander.go_to(
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

    def emergency_stop(self) -> None:
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
            raise RuntimeError("Crazyflie link is not connected")
        return self._cf

    def _on_log_data(self, timestamp: int, data: dict[str, float], _: Any) -> None:
        with self._lock:
            self._timestamp_ms = int(timestamp)
            self._received_at = time.monotonic()
            self._values.update({name: float(value) for name, value in data.items()})

    def _on_log_error(self, _: Any, message: str) -> None:
        with self._lock:
            self._log_errors.append(str(message))

    def _on_link_quality(self, quality: float) -> None:
        with self._lock:
            self._link_quality = float(quality)

    def _on_link_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._link_latency_ms = float(latency_ms)

    def _on_disconnected(self, _: str) -> None:
        self._connected = False

    def _on_connection_lost(self, _: str, message: str) -> None:
        self._connected = False
        with self._lock:
            self._log_errors.append(f"connection lost: {message}")
