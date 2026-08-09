from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import Field, model_validator

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3, VehicleCapability
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class ExecutionBackend(StrEnum):
    FAST_SIM = "FAST_SIM"
    MOCK_ISAAC = "MOCK_ISAAC"
    ISAAC = "ISAAC"
    CRAZYFLIE = "CRAZYFLIE"


class InitialFleetRole(StrEnum):
    ACTIVE = "ACTIVE"
    RESERVE = "RESERVE"
    UNASSIGNED = "UNASSIGNED"


class FleetFailurePolicy(StrEnum):
    CONTINUE_HEALTHY = "CONTINUE_HEALTHY"
    HOLD_ALL = "HOLD_ALL"
    LAND_ALL = "LAND_ALL"


class ZoneGeometry(ContractModel):
    minimum_m: Vector3
    maximum_m: Vector3

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> ZoneGeometry:
        if not (
            self.minimum_m.x < self.maximum_m.x
            and self.minimum_m.y < self.maximum_m.y
            and self.minimum_m.z <= self.maximum_m.z
        ):
            raise ValueError("zone minimum must be below maximum on x/y and not exceed z")
        return self

    @property
    def center_m(self) -> Vector3:
        return Vector3(
            x=(self.minimum_m.x + self.maximum_m.x) / 2.0,
            y=(self.minimum_m.y + self.maximum_m.y) / 2.0,
            z=(self.minimum_m.z + self.maximum_m.z) / 2.0,
        )


class ZoneDefinition(ContractModel):
    zone_id: Identifier
    geometry: ZoneGeometry


class FleetMemberDefinition(ContractModel):
    vehicle_id: Identifier
    display_name: str = Field(min_length=1, max_length=120)
    home: Vector3
    initial_role: InitialFleetRole = InitialFleetRole.UNASSIGNED
    required: bool = True
    required_capabilities: frozenset[VehicleCapability] = Field(default_factory=frozenset)


class DeploymentTaskDefinition(ContractModel):
    task_id: Identifier
    task_type: Identifier
    zone_id: Identifier
    priority: int = Field(default=100, ge=0, le=1000)
    mission_id: Identifier
    mission_parameters: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: frozenset[VehicleCapability] = Field(default_factory=frozenset)
    completion_progress_percent: float = Field(default=100.0, gt=0.0, le=100.0)
    estimated_duration_s: float = Field(gt=0.0)
    estimated_energy_percent: float = Field(gt=0.0, le=100.0)
    energy_margin_percent: float = Field(default=10.0, ge=0.0, le=100.0)


class DockDefinition(ContractModel):
    dock_id: Identifier
    capacity: int = Field(default=1, ge=1)
    supported_charging_capability: Identifier = "modeled-charge-v1"
    modeled_charge_rate_percent_per_min: float = Field(default=10.0, gt=0.0)


class FleetConstraints(ContractModel):
    warning_separation_m: float = Field(default=0.75, gt=0.0)
    critical_separation_m: float = Field(default=0.5, gt=0.0)
    observation_freshness_s: float = Field(default=1.0, gt=0.0)
    child_failure_policy: FleetFailurePolicy = FleetFailurePolicy.CONTINUE_HEALTHY

    @model_validator(mode="after")
    def separation_thresholds_are_ordered(self) -> FleetConstraints:
        if self.warning_separation_m <= self.critical_separation_m:
            raise ValueError("warning separation must exceed critical separation")
        return self


class CompletionPolicy(ContractModel):
    require_all_tasks: bool = True
    allow_partial_fleet: bool = False


class MissionArtifact(ContractModel):
    schema_version: Literal[1] = 1
    mission_id: Identifier
    mission_version: str = Field(min_length=1, max_length=64)
    source_sha256: SHA256

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


class DeploymentManifest(ContractModel):
    schema_version: Literal[1] = 1
    deployment_id: Identifier
    fleet: tuple[FleetMemberDefinition, ...]
    zones: tuple[ZoneDefinition, ...]
    tasks: tuple[DeploymentTaskDefinition, ...]
    constraints: FleetConstraints = Field(default_factory=FleetConstraints)
    docks: tuple[DockDefinition, ...] = ()
    completion_policy: CompletionPolicy = Field(default_factory=CompletionPolicy)

    @model_validator(mode="after")
    def references_are_unique_and_complete(self) -> DeploymentManifest:
        _require_unique((item.vehicle_id for item in self.fleet), "fleet vehicle")
        _require_unique((item.zone_id for item in self.zones), "zone")
        _require_unique((item.task_id for item in self.tasks), "task")
        _require_unique((item.dock_id for item in self.docks), "dock")
        if not self.fleet:
            raise ValueError("deployment requires at least one fleet member")
        zones = {item.zone_id for item in self.zones}
        unknown_zones = sorted({item.zone_id for item in self.tasks} - zones)
        if unknown_zones:
            raise ValueError(f"tasks reference unknown zones: {unknown_zones}")
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)

    @property
    def required_vehicle_ids(self) -> frozenset[str]:
        return frozenset(item.vehicle_id for item in self.fleet if item.required)

    def member(self, vehicle_id: str) -> FleetMemberDefinition:
        for member in self.fleet:
            if member.vehicle_id == vehicle_id:
                return member
        raise CrazySwarmError(
            ErrorCode.IDENTITY_MISMATCH,
            f"vehicle is not declared by deployment: {vehicle_id}",
        )


class BackendVehicleBinding(ContractModel):
    vehicle_id: Identifier
    backend_identifier: str = Field(min_length=1, max_length=500)
    expected_vehicle_id: Identifier
    operator_selected: bool = False


class BackendBindingProfile(ContractModel):
    schema_version: Literal[1] = 1
    binding_id: Identifier
    backend: ExecutionBackend
    vehicles: tuple[BackendVehicleBinding, ...]
    backend_options: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bindings_are_unique_and_not_crossed(self) -> BackendBindingProfile:
        _require_unique((item.vehicle_id for item in self.vehicles), "logical binding")
        _require_unique((item.backend_identifier for item in self.vehicles), "backend binding")
        crossed = [
            item.vehicle_id for item in self.vehicles if item.expected_vehicle_id != item.vehicle_id
        ]
        if crossed:
            raise ValueError(f"cross-bound vehicle identities are forbidden: {crossed}")
        if self.backend is ExecutionBackend.CRAZYFLIE and any(
            not item.operator_selected for item in self.vehicles
        ):
            raise ValueError("every physical binding must be selected explicitly by an operator")
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)

    def validate_for(self, deployment: DeploymentManifest) -> None:
        declared = {item.vehicle_id for item in deployment.fleet}
        bound = {item.vehicle_id for item in self.vehicles}
        missing = sorted(deployment.required_vehicle_ids - bound)
        unexpected = sorted(bound - declared)
        if missing or unexpected:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "binding profile does not match the deployment fleet",
                details={"missing": missing, "unexpected": unexpected},
            )

    def binding(self, vehicle_id: str) -> BackendVehicleBinding:
        for binding in self.vehicles:
            if binding.vehicle_id == vehicle_id:
                return binding
        raise CrazySwarmError(
            ErrorCode.IDENTITY_MISMATCH,
            f"vehicle has no backend binding: {vehicle_id}",
        )


class FleetSessionIdentity(ContractModel):
    schema_version: Literal[1] = 1
    fleet_session_id: Identifier
    fleet_run_id: Identifier
    backend: ExecutionBackend
    mission_sha256: SHA256
    deployment_sha256: SHA256
    binding_sha256: SHA256
    model_id: Identifier
    scenario_id: Identifier
    initial_state_sha256: SHA256

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)

    @classmethod
    def create(
        cls,
        *,
        fleet_session_id: str,
        fleet_run_id: str,
        backend: ExecutionBackend,
        mission: MissionArtifact,
        deployment: DeploymentManifest,
        binding: BackendBindingProfile,
        model_id: str,
        scenario_id: str,
        initial_state: Any,
    ) -> FleetSessionIdentity:
        binding.validate_for(deployment)
        if binding.backend is not backend:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "session backend mismatch")
        return cls(
            fleet_session_id=fleet_session_id,
            fleet_run_id=fleet_run_id,
            backend=backend,
            mission_sha256=mission.sha256,
            deployment_sha256=deployment.sha256,
            binding_sha256=binding.sha256,
            model_id=model_id,
            scenario_id=scenario_id,
            initial_state_sha256=canonical_sha256(initial_state),
        )


VersionedContractT = TypeVar("VersionedContractT", bound=ContractModel)


def load_versioned_contract(path: Path, model_type: type[VersionedContractT]) -> VersionedContractT:
    """Load an immutable v1 contract; later schemas fail closed until migrated."""

    with path.open(encoding="utf-8") as contract_file:
        if path.suffix.lower() == ".json":
            raw = json.load(contract_file)
        else:
            raw = yaml.safe_load(contract_file)
    if not isinstance(raw, dict):
        raise ValueError("versioned contract must be a mapping")
    version = raw.get("schema_version")
    if version != 1:
        direction = "newer" if isinstance(version, int) and version > 1 else "older or absent"
        raise ValueError(
            f"unsupported {direction} schema version {version!r}; explicit migration is required"
        )
    return model_type.model_validate(raw)


def _require_unique(values: Any, label: str) -> None:
    sequence = list(values)
    if len(sequence) != len(set(sequence)):
        raise ValueError(f"{label} identities must be unique")
