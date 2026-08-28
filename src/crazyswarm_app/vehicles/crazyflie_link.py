from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from crazyswarm_app.domain.commands import BodyRateThrustSetpoint
from crazyswarm_app.domain.telemetry import RadioTransportDiagnostics


@dataclass(frozen=True, slots=True)
class CrazyflieConnectionMetadata:
    selected_uri: str
    connected_uri: str
    protocol_version: int | None
    firmware_version: str | None
    deck_parameters: dict[str, int]
    observed_parameters: dict[str, str]
    available_log_variables: frozenset[str]


@dataclass(frozen=True, slots=True)
class CrazyflieRawSample:
    source_timestamp_ms: int
    received_at_monotonic_s: float
    values: dict[str, float] = field(default_factory=dict)
    value_received_at_monotonic_s: dict[str, float] = field(default_factory=dict)
    supervisor_bitfield: int | None = None
    link_quality_percent: float | None = None
    link_latency_ms: float | None = None
    radio_transport: RadioTransportDiagnostics | None = None
    connected: bool = True
    log_errors: tuple[str, ...] = ()


class CrazyflieLink(Protocol):
    """Blocking physical-link boundary; the async adapter owns thread handoff."""

    def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata: ...

    def disconnect(self) -> None: ...

    def read_sample(self) -> CrazyflieRawSample: ...

    def read_observation_sample(self) -> CrazyflieRawSample:
        """Read cached log telemetry without a synchronous supervisor request."""

        ...

    def restart_observation_logs(self) -> None:
        """Recreate firmware log blocks without closing the retained radio link."""

        ...

    def reset_estimator(self) -> None: ...

    def recover_from_crash(self) -> None: ...

    def begin_motor_power_override(self, motor_selection: str) -> None: ...

    def set_motor_power_percent(self, motor_selection: str, percent: float) -> None: ...

    def feed_motor_watchdog(self) -> None: ...

    def end_motor_power_override(self) -> None: ...

    def request_arm(self, armed: bool) -> None: ...

    def takeoff(self, height_m: float, duration_s: float, yaw_rad: float | None) -> None: ...

    def land(self, height_m: float, duration_s: float) -> None: ...

    def go_to_relative(
        self,
        x_m: float,
        y_m: float,
        z_m: float,
        yaw_rad: float,
        duration_s: float,
    ) -> None: ...

    def hold_position(self, duration_s: float) -> None: ...

    def stop_and_hold(self, z_distance_m: float, duration_s: float) -> None:
        """Actively replace current motion with a zero-velocity hover setpoint."""

        ...

    def release_stop_and_hold(self) -> None:
        """Release active hover priority immediately before a safe successor command."""

        ...

    def stream_body_rate_thrust(
        self,
        setpoints: tuple[BodyRateThrustSetpoint, ...],
        sample_period_s: float,
    ) -> None: ...

    def cancel_body_rate_thrust(self) -> None: ...

    def emergency_stop(self) -> None: ...
