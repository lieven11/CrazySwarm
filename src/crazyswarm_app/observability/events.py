from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field

from crazyswarm_app.domain.commands import CommandAcknowledgement, CommandEnvelope
from crazyswarm_app.domain.models import ContractModel, CoordinateFrame, Identifier, OperatingMode
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.missions.models import MissionResult, MissionRunEvent, MissionRunSnapshot
from crazyswarm_app.safety.models import SafetyEvent


class EvidenceKind(StrEnum):
    TELEMETRY = "telemetry"
    COMMAND = "command"
    ACKNOWLEDGEMENT = "acknowledgement"
    STATE = "state"
    FAULT = "fault"
    OPERATOR_ACTION = "operator_action"
    MISSION_STARTED = "mission_started"
    MISSION_EVENT = "mission_event"
    MISSION_RESULT = "mission_result"


class TelemetryPayload(ContractModel):
    payload_type: Literal[EvidenceKind.TELEMETRY] = EvidenceKind.TELEMETRY
    telemetry: TelemetryEnvelope


class CommandPayload(ContractModel):
    payload_type: Literal[EvidenceKind.COMMAND] = EvidenceKind.COMMAND
    command: CommandEnvelope


class AcknowledgementPayload(ContractModel):
    payload_type: Literal[EvidenceKind.ACKNOWLEDGEMENT] = EvidenceKind.ACKNOWLEDGEMENT
    acknowledgement: CommandAcknowledgement


class StatePayload(ContractModel):
    payload_type: Literal[EvidenceKind.STATE] = EvidenceKind.STATE
    event: SafetyEvent


class FaultPayload(ContractModel):
    payload_type: Literal[EvidenceKind.FAULT] = EvidenceKind.FAULT
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class OperatorActionPayload(ContractModel):
    payload_type: Literal[EvidenceKind.OPERATOR_ACTION] = EvidenceKind.OPERATOR_ACTION
    client_id: Identifier
    action: str
    request_id: Identifier
    details: dict[str, Any] = Field(default_factory=dict)


class MissionStartedPayload(ContractModel):
    payload_type: Literal[EvidenceKind.MISSION_STARTED] = EvidenceKind.MISSION_STARTED
    run: MissionRunSnapshot
    software_version: str
    configuration_schema_version: int = Field(ge=1)


class MissionEventPayload(ContractModel):
    payload_type: Literal[EvidenceKind.MISSION_EVENT] = EvidenceKind.MISSION_EVENT
    event: MissionRunEvent


class MissionResultPayload(ContractModel):
    payload_type: Literal[EvidenceKind.MISSION_RESULT] = EvidenceKind.MISSION_RESULT
    result: MissionResult


EvidencePayload: TypeAlias = Annotated[
    TelemetryPayload
    | CommandPayload
    | AcknowledgementPayload
    | StatePayload
    | FaultPayload
    | OperatorActionPayload
    | MissionStartedPayload
    | MissionEventPayload
    | MissionResultPayload,
    Field(discriminator="payload_type"),
]


class EvidenceEvent(ContractModel):
    schema_version: Literal[1] = 1
    event_id: Identifier
    sequence: int = Field(ge=0)
    kind: EvidenceKind
    vehicle_id: Identifier
    run_id: Identifier
    mode: OperatingMode
    source: Identifier
    source_timestamp_s: float = Field(ge=0.0)
    received_timestamp_s: float = Field(ge=0.0)
    recorded_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    unit: str = Field(min_length=1)
    frame: CoordinateFrame | None
    payload: EvidencePayload


class BusStats(ContractModel):
    published_events: int = Field(ge=0)
    subscriber_count: int = Field(ge=0)
    dropped_events: int = Field(ge=0)


def event_kind_for_payload(payload: EvidencePayload) -> EvidenceKind:
    return payload.payload_type
