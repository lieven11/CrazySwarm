from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import Identifier


class FaultType(StrEnum):
    COMMAND_DROP = "command_drop"
    TRAJECTORY_TIMEOUT = "trajectory_timeout"
    DISCONNECT = "disconnect"
    STALE_TELEMETRY = "stale_telemetry"
    SENSOR_FAILURE = "sensor_failure"
    LOCALIZATION_LOSS = "localization_loss"
    RANGE_STALE = "range_stale"
    RANGE_UNAVAILABLE = "range_unavailable"
    LOW_BATTERY = "low_battery"
    GEOFENCE_BREACH = "geofence_breach"
    COLLISION = "collision"
    NUMERICAL_FAILURE = "numerical_failure"
    ACTUATOR_DEGRADATION = "actuator_degradation"
    ACTUATOR_LOSS = "actuator_loss"


class FaultWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fault: FaultType
    start_s: float = Field(ge=0.0)
    end_s: float | None = Field(default=None, ge=0.0)
    vehicle_id: Identifier | None = None
    motor_index: int | None = Field(default=None, ge=0, le=3)
    actuator_health_scale: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def valid_window(self) -> FaultWindow:
        if self.end_s is not None and self.end_s < self.start_s:
            raise ValueError("fault end must not precede start")
        if (
            self.fault in {FaultType.ACTUATOR_DEGRADATION, FaultType.ACTUATOR_LOSS}
            and self.motor_index is None
        ):
            raise ValueError("actuator faults require a zero-based motor_index")
        if self.fault is FaultType.ACTUATOR_DEGRADATION and self.actuator_health_scale is None:
            raise ValueError("actuator degradation requires actuator_health_scale")
        if self.fault is FaultType.ACTUATOR_LOSS and self.actuator_health_scale not in {None, 0.0}:
            raise ValueError("actuator loss health scale is always zero")
        if self.actuator_health_scale is not None and self.fault not in {
            FaultType.ACTUATOR_DEGRADATION,
            FaultType.ACTUATOR_LOSS,
        }:
            raise ValueError("actuator_health_scale is valid only for actuator faults")
        return self

    def active(self, now_s: float) -> bool:
        return now_s >= self.start_s and (self.end_s is None or now_s <= self.end_s)


class FaultInjector:
    def __init__(
        self,
        windows: tuple[FaultWindow, ...] = (),
        *,
        vehicle_id: str | None = None,
    ) -> None:
        self._windows = windows
        self._vehicle_id = vehicle_id

    def active(self, fault: FaultType, now_s: float) -> bool:
        return any(
            window.fault is fault
            and window.active(now_s)
            and (window.vehicle_id is None or window.vehicle_id == self._vehicle_id)
            for window in self._windows
        )

    def actuator_health_scales(self, now_s: float) -> tuple[float, float, float, float]:
        """Return deterministic per-motor plant health without changing command intent."""

        health = [1.0, 1.0, 1.0, 1.0]
        for window in self._windows:
            if (
                window.fault not in {FaultType.ACTUATOR_DEGRADATION, FaultType.ACTUATOR_LOSS}
                or not window.active(now_s)
                or (window.vehicle_id is not None and window.vehicle_id != self._vehicle_id)
                or window.motor_index is None
            ):
                continue
            selected = (
                0.0 if window.fault is FaultType.ACTUATOR_LOSS else window.actuator_health_scale
            )
            if selected is None:
                raise RuntimeError("validated actuator fault is missing its health scale")
            health[window.motor_index] = min(health[window.motor_index], selected)
        return health[0], health[1], health[2], health[3]

    @property
    def windows(self) -> tuple[FaultWindow, ...]:
        return self._windows

    def inject(self, window: FaultWindow) -> None:
        self._windows = (*self._windows, window)

    def clear(self) -> None:
        self._windows = ()
