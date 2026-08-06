from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, CoordinateFrame, Identifier, Vector3


class TwinSourceClass(StrEnum):
    MEASURED_REAL = "MEASURED_REAL"
    SIMULATED_MODEL = "SIMULATED_MODEL"
    CONFIGURED = "CONFIGURED"
    TEST = "TEST"


class TwinValidity(StrEnum):
    VALID = "VALID"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPATIBLE = "INCOMPATIBLE"


class TwinSessionStatus(StrEnum):
    READY = "READY"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class TwinInitialState(ContractModel):
    source_class: TwinSourceClass
    source_id: str
    frame: CoordinateFrame
    position_m: Vector3 | None = None
    velocity_m_s: Vector3 | None = None
    yaw_rad: float | None = None
    battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)


class TwinSessionConfig(ContractModel):
    observed_vehicle_id: Identifier
    simulated_vehicle_id: Identifier
    mission_id: Identifier
    mission_version: str
    mission_source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    physics_model_id: str | None = None
    physics_model_version: str | None = None
    physics_configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_initial_state: TwinInitialState
    simulated_initial_state: TwinInitialState
    alignment_tolerance_s: float = Field(default=0.15, gt=0.0, le=5.0)
    ground_truth_available: bool = False
    test_only: bool = False


class CanonicalMissionIntent(ContractModel):
    intent_id: Identifier
    mission_id: Identifier
    mission_version: str
    mission_source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    physics_model_id: str | None = None
    physics_model_version: str | None = None
    physics_configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    issued_at_monotonic_s: float = Field(ge=0.0)


class TwinIntentAcknowledgement(ContractModel):
    side: str
    accepted: bool
    received_at_monotonic_s: float = Field(ge=0.0)
    completed_at_monotonic_s: float | None = Field(default=None, ge=0.0)
    message: str | None = None


class TwinObservation(ContractModel):
    vehicle_id: Identifier
    source_class: TwinSourceClass
    source_id: str
    source_timestamp_s: float = Field(ge=0.0)
    received_timestamp_s: float = Field(ge=0.0)
    frame: CoordinateFrame
    valid: bool = True
    position_m: Vector3 | None = None
    velocity_m_s: Vector3 | None = None
    yaw_rad: float | None = None
    battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)


class TwinDeviation(ContractModel):
    observed_source_timestamp_s: float = Field(ge=0.0)
    simulated_source_timestamp_s: float = Field(ge=0.0)
    source_timestamp_s: float = Field(ge=0.0)
    observed_latency_ms: float = Field(ge=0.0)
    simulated_latency_ms: float = Field(ge=0.0)
    alignment_delta_ms: float = Field(ge=0.0)
    frame: str
    validity: TwinValidity
    position_m: float | None = Field(default=None, ge=0.0)
    altitude_m: float | None = Field(default=None, ge=0.0)
    velocity_m_s: float | None = Field(default=None, ge=0.0)
    yaw_rad: float | None = Field(default=None, ge=0.0)
    battery_percent: float | None = Field(default=None, ge=0.0)
    ground_truth_available: bool
    observed_source_class: TwinSourceClass
    simulated_source_class: TwinSourceClass


class TwinSessionRecord(ContractModel):
    session_id: Identifier
    status: TwinSessionStatus
    observed_vehicle_id: Identifier
    simulated_vehicle_id: Identifier
    mission_id: Identifier
    mission_version: str
    mission_source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    physics_model_id: str | None = None
    physics_model_version: str | None = None
    physics_configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    created_at_monotonic_s: float = Field(ge=0.0)
    ground_truth_available: bool
    test_only: bool
    latest_deviation: TwinDeviation | None = None
    intent_acknowledgements: tuple[TwinIntentAcknowledgement, ...] = ()
    deviation_count: int = Field(default=0, ge=0)


class TwinComparisonReport(ContractModel):
    session_id: Identifier
    sample_count: int = Field(ge=0)
    valid_sample_count: int = Field(ge=0)
    ground_truth_available: bool
    mean_position_m: float | None = Field(default=None, ge=0.0)
    max_position_m: float | None = Field(default=None, ge=0.0)
    mean_altitude_m: float | None = Field(default=None, ge=0.0)
    mean_observed_latency_ms: float | None = Field(default=None, ge=0.0)
    mean_simulated_latency_ms: float | None = Field(default=None, ge=0.0)


class ModelCalibration(ContractModel):
    calibration_id: Identifier
    session_id: Identifier
    base_model_id: str
    base_model_version: str
    model_version: str
    created_at_monotonic_s: float = Field(ge=0.0)
    sample_count: int = Field(ge=1)
    parameters: dict[str, float]
