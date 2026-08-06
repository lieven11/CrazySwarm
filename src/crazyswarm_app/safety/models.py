from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from crazyswarm_app.domain.models import (
    CommandSource,
    ContractModel,
    Identifier,
    OperatingMode,
    VehicleState,
)


class PreflightCheck(ContractModel):
    code: str
    passed: bool
    message: str
    observed: str | float | bool | None = None
    required: str | float | bool | None = None


class PreflightReport(ContractModel):
    report_id: Identifier
    vehicle_id: Identifier
    mode: OperatingMode
    operator_id: Identifier
    created_at_monotonic_s: float = Field(ge=0.0)
    expires_at_monotonic_s: float = Field(ge=0.0)
    approved: bool
    checks: tuple[PreflightCheck, ...]


class RecoveryAction(StrEnum):
    NONE = "NONE"
    REJECT_NEW_COMMANDS = "REJECT_NEW_COMMANDS"
    ABORT_AND_LAND = "ABORT_AND_LAND"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class HealthIssue(ContractModel):
    code: str
    message: str
    action: RecoveryAction


class HealthAssessment(ContractModel):
    vehicle_id: Identifier
    healthy: bool
    action: RecoveryAction
    issues: tuple[HealthIssue, ...] = ()


class SafetyEvent(ContractModel):
    sequence: int = Field(ge=0)
    timestamp_monotonic_s: float = Field(ge=0.0)
    vehicle_id: Identifier
    event_type: str
    source: CommandSource
    message: str
    from_state: VehicleState | None = None
    to_state: VehicleState | None = None
    command_id: Identifier | None = None
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ControlLease(ContractModel):
    owner_id: Identifier
    expires_at_monotonic_s: float = Field(ge=0.0)


class LiveModeAuthorization(ContractModel):
    vehicle_id: Identifier
    operator_id: Identifier
    mode: OperatingMode
    confirmed: bool
    authorized_at_monotonic_s: float = Field(ge=0.0)
