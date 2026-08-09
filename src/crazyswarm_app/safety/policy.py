from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Vector3


class FlightVolume(ContractModel):
    minimum_m: Vector3 = Field(default_factory=lambda: Vector3(x=-2.0, y=-2.0, z=0.0))
    maximum_m: Vector3 = Field(default_factory=lambda: Vector3(x=2.0, y=2.0, z=1.0))

    @model_validator(mode="after")
    def valid_bounds(self) -> FlightVolume:
        if not (
            self.minimum_m.x < self.maximum_m.x
            and self.minimum_m.y < self.maximum_m.y
            and self.minimum_m.z < self.maximum_m.z
        ):
            raise ValueError("flight volume minimum must be below maximum")
        return self

    def contains(self, point: Vector3) -> bool:
        return (
            self.minimum_m.x <= point.x <= self.maximum_m.x
            and self.minimum_m.y <= point.y <= self.maximum_m.y
            and self.minimum_m.z <= point.z <= self.maximum_m.z
        )


class SafetyPolicyOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_altitude_m: float | None = Field(default=None, gt=0.0)
    max_horizontal_speed_m_s: float | None = Field(default=None, gt=0.0)
    max_vertical_speed_m_s: float | None = Field(default=None, gt=0.0)
    max_acceleration_m_s2: float | None = Field(default=None, gt=0.0)
    max_yaw_rate_rad_s: float | None = Field(default=None, gt=0.0)
    max_mission_duration_s: float | None = Field(default=None, gt=0.0)
    command_timeout_s: float | None = Field(default=None, gt=0.0)
    telemetry_timeout_s: float | None = Field(default=None, gt=0.0)
    health_watchdog_period_s: float | None = Field(default=None, gt=0.0)
    control_lease_timeout_s: float | None = Field(default=None, gt=0.0)
    preflight_valid_s: float | None = Field(default=None, gt=0.0)
    minimum_takeoff_battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    critical_battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    minimum_link_quality_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    minimum_localization_quality_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    flight_volume: FlightVolume | None = None


class SafetyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_altitude_m: float = Field(default=1.0, gt=0.0)
    max_horizontal_speed_m_s: float = Field(default=0.5, gt=0.0)
    max_vertical_speed_m_s: float = Field(default=0.3, gt=0.0)
    max_acceleration_m_s2: float = Field(default=1.0, gt=0.0)
    max_yaw_rate_rad_s: float = Field(default=1.5707963268, gt=0.0)
    max_mission_duration_s: float = Field(default=300.0, gt=0.0)
    command_timeout_s: float = Field(default=10.0, gt=0.0)
    telemetry_timeout_s: float = Field(default=1.0, gt=0.0)
    health_watchdog_period_s: float = Field(default=0.02, gt=0.0, le=1.0)
    control_lease_timeout_s: float = Field(default=2.0, gt=0.0)
    preflight_valid_s: float = Field(default=30.0, gt=0.0)
    minimum_takeoff_battery_percent: float = Field(default=30.0, ge=0.0, le=100.0)
    critical_battery_percent: float = Field(default=10.0, ge=0.0, le=100.0)
    minimum_link_quality_percent: float = Field(default=70.0, ge=0.0, le=100.0)
    minimum_localization_quality_percent: float = Field(default=60.0, ge=0.0, le=100.0)
    flight_volume: FlightVolume = Field(default_factory=FlightVolume)

    @model_validator(mode="after")
    def thresholds_are_consistent(self) -> SafetyPolicy:
        if self.critical_battery_percent >= self.minimum_takeoff_battery_percent:
            raise ValueError("critical battery must be below takeoff battery minimum")
        if self.flight_volume.maximum_m.z > self.max_altitude_m:
            raise ValueError("flight volume cannot exceed maximum altitude")
        return self

    def tighten(self, override: SafetyPolicyOverride) -> SafetyPolicy:
        updates = override.model_dump(exclude_none=True)
        maximum_fields = {
            "max_altitude_m",
            "max_horizontal_speed_m_s",
            "max_vertical_speed_m_s",
            "max_acceleration_m_s2",
            "max_yaw_rate_rad_s",
            "max_mission_duration_s",
            "command_timeout_s",
            "telemetry_timeout_s",
            "health_watchdog_period_s",
            "control_lease_timeout_s",
            "preflight_valid_s",
        }
        minimum_fields = {
            "minimum_takeoff_battery_percent",
            "critical_battery_percent",
            "minimum_link_quality_percent",
            "minimum_localization_quality_percent",
        }
        for name in maximum_fields:
            value = updates.get(name)
            if value is not None and value > getattr(self, name):
                raise ValueError(f"{name} override would relax the safety envelope")
        for name in minimum_fields:
            value = updates.get(name)
            if value is not None and value < getattr(self, name):
                raise ValueError(f"{name} override would relax the safety envelope")
        volume = override.flight_volume
        if volume is not None and not self._contains_volume(volume):
            raise ValueError("flight_volume override would relax the safety envelope")
        values = self.model_dump()
        values.update(updates)
        return SafetyPolicy.model_validate(values)

    def _contains_volume(self, candidate: FlightVolume) -> bool:
        return self.flight_volume.contains(candidate.minimum_m) and self.flight_volume.contains(
            candidate.maximum_m
        )
