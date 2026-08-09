from __future__ import annotations

import time

from pydantic import Field

from crazyswarm_app.domain.models import (
    ContractModel,
    CoordinateFrame,
    EulerAttitude,
    Identifier,
    Vector3,
    VehicleState,
)
from crazyswarm_app.domain.telemetry import RangeReadings, TelemetryEnvelope


class MissionObservation(ContractModel):
    """Canonical, source-aware observation exposed to mission Python."""

    vehicle_id: Identifier
    sequence: int = Field(ge=0)
    source_timestamp_s: float = Field(ge=0.0)
    received_timestamp_s: float = Field(ge=0.0)
    source_clock_id: Identifier
    source_clock_epoch: int = Field(ge=0)
    age_s: float = Field(ge=0.0)
    valid: bool
    frame: CoordinateFrame | None = None
    estimated_position_m: Vector3 | None = None
    velocity_m_s: Vector3 | None = None
    attitude: EulerAttitude | None = None
    localization_quality_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    ranges: RangeReadings | None = None
    battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    link_quality_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    health_flags: tuple[str, ...] = ()

    @classmethod
    def from_telemetry(
        cls,
        envelope: TelemetryEnvelope,
        *,
        now_s: float | None = None,
        received_at_monotonic_s: float | None = None,
    ) -> MissionObservation:
        data = envelope.telemetry
        observed_now = time.monotonic() if now_s is None else now_s
        transport_quality = (
            data.link_quality_percent
            if data.link_quality_percent is not None
            else (data.transport.delivery_quality_percent if data.transport is not None else None)
        )
        received_at = observed_now if received_at_monotonic_s is None else received_at_monotonic_s
        age = max(0.0, observed_now - received_at)
        valid = (
            data.position_m is not None
            and data.localization_quality_percent is not None
            and data.state is not VehicleState.DISCONNECTED
        )
        return cls(
            vehicle_id=envelope.vehicle_id,
            sequence=envelope.sequence,
            source_timestamp_s=envelope.source_timestamp_s,
            received_timestamp_s=envelope.received_timestamp_s,
            source_clock_id=envelope.source_clock_id,
            source_clock_epoch=envelope.source_clock_epoch,
            age_s=age,
            valid=valid,
            frame=data.frame,
            estimated_position_m=data.position_m,
            velocity_m_s=data.velocity_m_s,
            attitude=data.attitude,
            localization_quality_percent=data.localization_quality_percent,
            ranges=data.ranges,
            battery_percent=data.battery_percent,
            link_quality_percent=transport_quality,
            health_flags=data.faults,
        )
