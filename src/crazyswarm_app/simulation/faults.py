from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import Identifier


class FaultType(StrEnum):
    COMMAND_DROP = "command_drop"
    DISCONNECT = "disconnect"
    STALE_TELEMETRY = "stale_telemetry"
    SENSOR_FAILURE = "sensor_failure"
    LOCALIZATION_LOSS = "localization_loss"
    LOW_BATTERY = "low_battery"
    GEOFENCE_BREACH = "geofence_breach"
    COLLISION = "collision"
    NUMERICAL_FAILURE = "numerical_failure"


class FaultWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fault: FaultType
    start_s: float = Field(ge=0.0)
    end_s: float | None = Field(default=None, ge=0.0)
    vehicle_id: Identifier | None = None

    @model_validator(mode="after")
    def valid_window(self) -> FaultWindow:
        if self.end_s is not None and self.end_s < self.start_s:
            raise ValueError("fault end must not precede start")
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

    @property
    def windows(self) -> tuple[FaultWindow, ...]:
        return self._windows

    def inject(self, window: FaultWindow) -> None:
        self._windows = (*self._windows, window)

    def clear(self) -> None:
        self._windows = ()
