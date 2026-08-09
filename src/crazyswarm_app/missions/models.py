from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier, OperatingMode, VehicleCapability
from crazyswarm_app.domain.simulation import FleetAuthorityTransitionReceipt


class MissionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class MissionPhase(StrEnum):
    VALIDATING = "VALIDATING"
    CLAIMING_CONTROL = "CLAIMING_CONTROL"
    CONNECTING = "CONNECTING"
    PREFLIGHT = "PREFLIGHT"
    ARMING = "ARMING"
    TAKING_OFF = "TAKING_OFF"
    EXECUTING = "EXECUTING"
    LANDING = "LANDING"
    CLEANUP = "CLEANUP"
    COMPLETE = "COMPLETE"


class MissionMetadata(ContractModel):
    mission_id: Identifier
    mission_version: str
    name: str
    description: str
    required_capabilities: frozenset[VehicleCapability]
    parameter_schema: dict[str, Any]
    presets: dict[str, dict[str, Any]]
    source_kind: str = "BUILT_IN"
    source_filename: str | None = None
    source_sha256: str | None = None
    planned_commands: tuple[dict[str, Any], ...] = ()
    package_schema_version: int = Field(default=1, ge=1, le=2)
    logical_roles: tuple[dict[str, Any], ...] = ()


class MissionRunEvent(ContractModel):
    mission_run_id: Identifier
    sequence: int = Field(ge=1)
    phase: MissionPhase
    timestamp_monotonic_s: float = Field(ge=0.0)
    message: str


class MissionResult(ContractModel):
    mission_run_id: Identifier
    mission_execution_id: Identifier | None = None
    mission_id: Identifier
    mission_name: str | None = None
    mission_version: str
    vehicle_id: Identifier
    mode: OperatingMode
    status: MissionStatus
    reason_code: str
    message: str = ""
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    mission_source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    mission_runtime_id: str = "UNKNOWN"
    mission_runtime_version: str = "UNKNOWN"
    vehicle_adapter: str = "UNKNOWN"
    backend_role: str = "UNKNOWN"
    authority_class: str = "UNKNOWN"
    repository_commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40,64}$")
    repository_dirty: bool = False
    physics_model_id: str | None = None
    physics_model_version: str | None = None
    physics_configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    scenario_id: str | None = None
    scenario_schema_version: str | None = None
    scenario_configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    simulation_seed: int | None = None
    simulation_fixed_step_s: float | None = Field(default=None, gt=0.0)
    initial_state_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    run_identity_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    accepted_plan_id: Identifier | None = None
    accepted_plan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    execution_program_id: Identifier | None = None
    execution_program_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    accepted_trajectory_sha256s: tuple[str, ...] = ()
    execution_clock_policy: str | None = None
    parameters: dict[str, Any]
    started_at_monotonic_s: float = Field(ge=0.0)
    finished_at_monotonic_s: float = Field(ge=0.0)
    started_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    events: tuple[MissionRunEvent, ...] = ()
    normalized_intent_trace: tuple[dict[str, Any], ...] = ()
    observations_read: tuple[dict[str, Any], ...] = ()
    fleet_authority_transitions: tuple[FleetAuthorityTransitionReceipt, ...] = ()
    goal_captures: tuple[dict[str, Any], ...] = ()


class MissionRunSnapshot(ContractModel):
    mission_run_id: Identifier
    mission_execution_id: Identifier | None = None
    mission_id: Identifier
    mission_name: str | None = None
    mission_version: str
    vehicle_id: Identifier
    mode: OperatingMode
    phase: MissionPhase
    configuration_hash: str
    mission_source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    mission_runtime_id: str
    mission_runtime_version: str
    vehicle_adapter: str
    backend_role: str = "UNKNOWN"
    authority_class: str = "UNKNOWN"
    repository_commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40,64}$")
    repository_dirty: bool = False
    physics_model_id: str | None = None
    physics_model_version: str | None = None
    physics_configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    scenario_id: str | None = None
    scenario_schema_version: str | None = None
    scenario_configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    simulation_seed: int | None = None
    simulation_fixed_step_s: float | None = Field(default=None, gt=0.0)
    initial_state_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    run_identity_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    accepted_plan_id: Identifier | None = None
    accepted_plan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    execution_program_id: Identifier | None = None
    execution_program_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    accepted_trajectory_sha256s: tuple[str, ...] = ()
    execution_clock_policy: str | None = None
    parameters: dict[str, Any]
    started_at_monotonic_s: float
    cancellation_requested: bool = False
    result: MissionResult | None = None
    normalized_intent_trace: tuple[dict[str, Any], ...] = ()
    observations_read: tuple[dict[str, Any], ...] = ()
    goal_captures: tuple[dict[str, Any], ...] = ()
