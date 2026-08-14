from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.twin.ingestion import default_twin_channels
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinChannelDefinition,
    TwinQuality,
    TwinSourceClass,
    TwinStreamSample,
)

REQUIRED_PROPS_OFF_CHANNELS = frozenset(
    {
        "pose.position",
        "imu.acceleration",
        "imu.angular_velocity",
        "battery.voltage",
        "estimator.health",
        *(f"motor.m{index}.state" for index in range(1, 5)),
    }
)


class PhysicalTwinHandoffRequest(ContractModel):
    session_id: Identifier
    connected: bool
    observed_source_class: TwinSourceClass
    now_received_s: float = Field(ge=0.0)
    maximum_age_s: float = Field(default=0.25, gt=0.0, le=2.0)
    channels: tuple[TwinChannelDefinition, ...] = Field(min_length=1, max_length=32)
    latest_samples: tuple[TwinStreamSample, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def one_latest_sample_per_channel(self) -> PhysicalTwinHandoffRequest:
        if any(sample.session_id != self.session_id for sample in self.latest_samples):
            raise ValueError("physical handoff sample belongs to another session")
        channel_ids = [item.channel_id for item in self.channels]
        sample_channels = [item.channel_id for item in self.latest_samples]
        if len(channel_ids) != len(set(channel_ids)) or len(sample_channels) != len(
            set(sample_channels)
        ):
            raise ValueError("physical handoff requires one definition/sample per channel")
        return self


class PhysicalTwinHandoffAssessment(ContractModel):
    schema_version: Literal[1] = 1
    stage_id: Literal["physical.props_off_stream"] = "physical.props_off_stream"
    execution_status: Literal["NOT_RUN"] = "NOT_RUN"
    readiness: Literal["READY_FOR_SEPARATE_OPERATOR_AUTHORIZATION", "BLOCKED"]
    blockers: tuple[Identifier, ...]
    command_issued: Literal[False] = False
    assessment_sha256: SHA256


def assess_physical_twin_handoff(
    request: PhysicalTwinHandoffRequest,
) -> PhysicalTwinHandoffAssessment:
    """Qualify schema readiness without opening a radio or granting flight authority."""

    blockers: list[str] = []
    if not request.connected:
        blockers.append("DISCONNECTED")
    if request.observed_source_class is not TwinSourceClass.MEASURED_REAL:
        blockers.append("SOURCE_NOT_MEASURED_REAL")
    definitions = {item.channel_id: item for item in request.channels}
    expected = {item.channel_id: item for item in default_twin_channels()}
    samples = {item.channel_id: item for item in request.latest_samples}
    missing = sorted(REQUIRED_PROPS_OFF_CHANNELS - set(samples))
    if missing:
        blockers.append("PARTIAL_REQUIRED_SENSORS")
    for channel_id in sorted(REQUIRED_PROPS_OFF_CHANNELS & set(samples)):
        sample = samples[channel_id]
        definition = definitions.get(channel_id)
        contract = expected[channel_id]
        if definition is None:
            blockers.append(f"MISSING_CHANNEL_DEFINITION.{channel_id}")
            continue
        if definition.unit != contract.unit or sample.unit != contract.unit:
            blockers.append(f"BAD_UNIT.{channel_id}")
        if definition.frame != contract.frame or sample.frame != contract.frame:
            blockers.append(f"BAD_FRAME.{channel_id}")
        if request.now_received_s - sample.received_timestamp_s > request.maximum_age_s:
            blockers.append(f"STALE.{channel_id}")
        if sample.availability is not TwinAvailability.AVAILABLE or sample.quality not in {
            TwinQuality.GOOD,
            TwinQuality.DEGRADED,
        }:
            blockers.append(f"UNAVAILABLE.{channel_id}")
    unique_blockers = tuple(dict.fromkeys(blockers))
    payload = {
        "schema_version": 1,
        "stage_id": "physical.props_off_stream",
        "execution_status": "NOT_RUN",
        "readiness": (
            "BLOCKED"
            if unique_blockers
            else "READY_FOR_SEPARATE_OPERATOR_AUTHORIZATION"
        ),
        "blockers": unique_blockers,
        "command_issued": False,
    }
    return PhysicalTwinHandoffAssessment(
        **payload,
        assessment_sha256=canonical_sha256(payload),
    )
