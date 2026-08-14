from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, CoordinateFrame, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


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


class TwinAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    STALE = "STALE"
    REJECTED = "REJECTED"


class TwinQuality(StrEnum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"
    UNQUALIFIED = "UNQUALIFIED"


class TwinStreamSide(StrEnum):
    OBSERVED = "OBSERVED"
    PREDICTED = "PREDICTED"


class TwinChannelDefinition(ContractModel):
    channel_id: Identifier
    unit: str = Field(min_length=1, max_length=40)
    frame: str = Field(min_length=1, max_length=40)
    value_kind: Literal["SCALAR", "VECTOR3", "BOOLEAN", "IDENTIFIER"]
    required: bool = False


class TwinStreamSample(ContractModel):
    schema_version: Literal[1] = 1
    sample_id: Identifier
    session_id: Identifier
    side: TwinStreamSide
    vehicle_id: Identifier
    channel_id: Identifier
    sequence: int = Field(ge=1)
    source_timestamp_s: float = Field(ge=0.0)
    received_timestamp_s: float = Field(ge=0.0)
    availability: TwinAvailability
    quality: TwinQuality
    unit: str = Field(min_length=1, max_length=40)
    frame: str = Field(min_length=1, max_length=40)
    value: float | bool | str | Vector3 | None = None
    calibration_id: Identifier | None = None
    raw_payload_sha256: SHA256
    sample_sha256: SHA256

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"sample_sha256"})

    @model_validator(mode="after")
    def causal_hash_and_availability(self) -> TwinStreamSample:
        if self.received_timestamp_s < self.source_timestamp_s:
            raise ValueError("twin sample receipt predates source")
        if self.availability is TwinAvailability.AVAILABLE and self.value is None:
            raise ValueError("available twin sample requires a value")
        if self.availability is not TwinAvailability.AVAILABLE and self.value is not None:
            raise ValueError("unavailable twin sample cannot fabricate a value")
        if canonical_sha256(self.canonical_payload()) != self.sample_sha256:
            raise ValueError("twin sample hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TwinStreamSample:
        payload = {"schema_version": 1, "calibration_id": None, **values}
        return cls(**payload, sample_sha256=canonical_sha256(payload))


class TwinIngestionBatch(ContractModel):
    session_id: Identifier
    samples: tuple[TwinStreamSample, ...] = Field(min_length=1, max_length=512)


class TwinIngestionReceipt(ContractModel):
    session_id: Identifier
    accepted_count: int = Field(ge=0, le=512)
    idempotent_count: int = Field(ge=0, le=512)
    first_sequence: int = Field(ge=1)
    last_sequence: int = Field(ge=1)
    batch_sha256: SHA256


class TwinResidualSample(ContractModel):
    schema_version: Literal[1] = 1
    session_id: Identifier
    channel_id: Identifier
    observed_sample_sha256: SHA256
    predicted_sample_sha256: SHA256 | None = None
    source_timestamp_s: float = Field(ge=0.0)
    alignment_delta_s: float | None = Field(default=None, ge=0.0)
    availability: TwinAvailability
    quality: TwinQuality
    unit: str = Field(min_length=1, max_length=40)
    frame: str = Field(min_length=1, max_length=40)
    value: float | Vector3 | None = None
    residual_sha256: SHA256

    @model_validator(mode="after")
    def hash_and_availability_match(self) -> TwinResidualSample:
        if self.availability is TwinAvailability.AVAILABLE and self.value is None:
            raise ValueError("available twin residual requires a value")
        if self.availability is not TwinAvailability.AVAILABLE and self.value is not None:
            raise ValueError("unavailable twin residual cannot fabricate a value")
        payload = self.model_dump(mode="python", exclude={"residual_sha256"})
        if canonical_sha256(payload) != self.residual_sha256:
            raise ValueError("twin residual hash mismatch")
        return self


class TwinTimeline(ContractModel):
    session_id: Identifier
    samples: tuple[TwinStreamSample, ...]
    residuals: tuple[TwinResidualSample, ...] = ()
    next_after_source_s: float | None = None
    timeline_sha256: SHA256


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
    calibration_id: Identifier | None = None
    curriculum_stage_id: Identifier | None = None
    campaign_run_id: Identifier | None = None
    campaign_review_id: Identifier | None = None
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
    observed_source_class: TwinSourceClass = TwinSourceClass.CONFIGURED
    simulated_source_class: TwinSourceClass = TwinSourceClass.SIMULATED_MODEL
    observed_source_id: str | None = None
    simulated_source_id: str | None = None
    mission_id: Identifier
    mission_version: str
    mission_source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    physics_model_id: str | None = None
    physics_model_version: str | None = None
    physics_configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    calibration_id: Identifier | None = None
    curriculum_stage_id: Identifier | None = None
    campaign_run_id: Identifier | None = None
    campaign_review_id: Identifier | None = None
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
