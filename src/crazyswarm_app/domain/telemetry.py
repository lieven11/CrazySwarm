from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import (
    ContractModel,
    CoordinateFrame,
    EulerAttitude,
    Identifier,
    NonNegativeSeconds,
    Vector3,
    VehicleCapabilities,
    VehicleState,
)

Percentage = Annotated[float, Field(ge=0.0, le=100.0)]


class LocalizationSource(StrEnum):
    NONE = "none"
    FLOW = "flow"
    LIGHTHOUSE = "lighthouse"
    LOCO = "loco"
    MOTION_CAPTURE = "motion_capture"
    SIMULATED = "simulated"


class RangeStatus(StrEnum):
    VALID = "VALID"
    NO_HIT = "NO_HIT"
    CLIPPED = "CLIPPED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class FlowStatus(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class RangeReadings(ContractModel):
    front_m: float | None = Field(default=None, ge=0.0)
    back_m: float | None = Field(default=None, ge=0.0)
    left_m: float | None = Field(default=None, ge=0.0)
    right_m: float | None = Field(default=None, ge=0.0)
    up_m: float | None = Field(default=None, ge=0.0)
    down_m: float | None = Field(default=None, ge=0.0)
    max_range_m: Annotated[float, Field(gt=0.0)] = 4.0
    statuses: dict[str, RangeStatus] = Field(default_factory=dict)
    source_timestamp_s: NonNegativeSeconds | None = None


class FlowReading(ContractModel):
    velocity_body_m_s: Vector3 | None = None
    ground_distance_m: float | None = Field(default=None, ge=0.0)
    quality_percent: Percentage = 0.0
    status: FlowStatus = FlowStatus.VALID
    source_timestamp_s: NonNegativeSeconds | None = None


class ImuReading(ContractModel):
    acceleration_body_m_s2: Vector3 = Field(default_factory=Vector3)
    angular_velocity_body_rad_s: Vector3 = Field(default_factory=Vector3)
    source_timestamp_s: NonNegativeSeconds | None = None


class QuaternionAttitude(ContractModel):
    """Hamilton quaternion in explicit ``w, x, y, z`` order."""

    w: float
    x: float
    y: float
    z: float

    @model_validator(mode="after")
    def finite_nonzero(self) -> QuaternionAttitude:
        components = (self.w, self.x, self.y, self.z)
        if not all(math.isfinite(value) for value in components):
            raise ValueError("quaternion components must be finite")
        if sum(value * value for value in components) <= 1e-24:
            raise ValueError("quaternion norm cannot be zero")
        return self


class EstimatorReading(ContractModel):
    position_variance_m2: Vector3 | None = None
    converged: bool | None = None
    quality_metric_id: str | None = None

    @model_validator(mode="after")
    def variance_is_nonnegative(self) -> EstimatorReading:
        if self.position_variance_m2 is not None and any(
            value < 0.0 or not math.isfinite(value)
            for value in (
                self.position_variance_m2.x,
                self.position_variance_m2.y,
                self.position_variance_m2.z,
            )
        ):
            raise ValueError("estimator position variance must be finite and nonnegative")
        return self


class MotorReading(ContractModel):
    motor_id: Literal["M1", "M2", "M3", "M4"]
    command_percent: Percentage
    # These electrical-model fields were added after telemetry-v1 evidence already
    # existed.  Missing means "not recorded by that producer", not zero.
    requested_thrust_n: Annotated[float, Field(ge=0.0)] | None = None
    applied_pwm_percent: Percentage | None = None
    motor_voltage_v: Annotated[float, Field(ge=0.0)] | None = None
    thrust_n: Annotated[float, Field(ge=0.0)]
    available_thrust_n: Annotated[float, Field(ge=0.0)] | None = None
    current_a: Annotated[float, Field(ge=0.0)]
    saturated: bool = False
    health_percent: Percentage = 100.0
    faulted: bool = False


class MotorTelemetry(ContractModel):
    model_id: str
    model_version: str
    readings: tuple[MotorReading, MotorReading, MotorReading, MotorReading]


class TransportReading(ContractModel):
    """Command-transport evidence without implying that every adapter is a radio."""

    kind: Literal["physical_radio", "modeled_transport", "replay"]
    source_class: Literal["MEASURED_REAL", "SIMULATED_MODEL", "REPLAYED"]
    delivery_quality_percent: Percentage | None = None
    latency_ms: Annotated[float, Field(ge=0.0)] | None = None
    packet_loss_percent: Percentage | None = None


class VehicleTelemetry(ContractModel):
    state: VehicleState
    armed: bool = False
    flying: bool = False
    position_m: Vector3 | None = None
    ground_truth_position_m: Vector3 | None = None
    velocity_m_s: Vector3 | None = None
    attitude: EulerAttitude | None = None
    quaternion: QuaternionAttitude | None = None
    frame: CoordinateFrame | None = None
    position_is_estimate: bool | None = None
    localization_source: LocalizationSource | None = None
    localization_quality_percent: Percentage | None = None
    battery_percent: Percentage | None = None
    battery_open_circuit_voltage_v: Annotated[float, Field(ge=0.0)] | None = None
    battery_voltage_v: Annotated[float, Field(ge=0.0)] | None = None
    battery_current_a: float | None = None
    battery_cutoff_active: bool | None = None
    battery_cutoff_reason: Literal["DEPLETED", "UNDERVOLTAGE", "INVALID_CELL_STATE"] | None = None
    powertrain_current_limited: bool | None = None
    # Legacy physical-radio fields are optional. A simulator must never populate them.
    link_quality_percent: Percentage | None = None
    link_latency_ms: Annotated[float, Field(ge=0.0)] | None = None
    packet_loss_percent: Percentage | None = None
    transport: TransportReading | None = None
    capabilities: VehicleCapabilities | None = None
    imu: ImuReading | None = None
    estimator: EstimatorReading | None = None
    flow: FlowReading | None = None
    ranges: RangeReadings | None = None
    motors: MotorTelemetry | None = None
    faults: tuple[str, ...] = ()

    @model_validator(mode="after")
    def spatial_values_require_frame(self) -> VehicleTelemetry:
        if (
            any(
                value is not None
                for value in (
                    self.position_m,
                    self.ground_truth_position_m,
                    self.velocity_m_s,
                    self.attitude,
                    self.quaternion,
                )
            )
            and self.frame is None
        ):
            raise ValueError("spatial telemetry requires an explicit coordinate frame")
        if self.position_m is None and self.position_is_estimate is not None:
            raise ValueError("position estimate classification requires a position value")
        return self


class TelemetryEnvelope(ContractModel):
    schema_version: Literal[1] = 1
    vehicle_id: Identifier
    sequence: Annotated[int, Field(ge=0)]
    source_timestamp_s: NonNegativeSeconds
    received_timestamp_s: NonNegativeSeconds
    simulation_timestamp_s: NonNegativeSeconds | None = None
    replay_timestamp_s: NonNegativeSeconds | None = None
    source_clock_id: Identifier = "adapter-monotonic"
    source_clock_epoch: Annotated[int, Field(ge=0)] = 0
    recorded_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    telemetry: VehicleTelemetry

    @model_validator(mode="after")
    def receive_time_is_ordered(self) -> TelemetryEnvelope:
        if self.received_timestamp_s < self.source_timestamp_s:
            raise ValueError("received timestamp cannot precede source timestamp")
        return self
