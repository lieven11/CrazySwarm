from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, CoordinateFrame, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.safety.policy import SafetyPolicyOverride


class PluginKind(StrEnum):
    ROUTE_PLANNER = "ROUTE_PLANNER"
    FLEET_POLICY = "FLEET_POLICY"
    RECOVERY_STRATEGY = "RECOVERY_STRATEGY"


class QualificationState(StrEnum):
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class PluginManifest(ContractModel):
    schema_version: Literal[1] = 1
    plugin_id: Identifier
    kind: PluginKind
    implementation_version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )
    input_schema_version: Literal[1] = 1
    output_schema_version: Literal[1] = 1
    control_contract_minimum: str = Field(pattern=r"^1\.[0-9]+\.[0-9]+$")
    control_contract_maximum: str = Field(pattern=r"^1\.[0-9]+\.[0-9]+$")
    capabilities: frozenset[Identifier]
    required_observations: frozenset[Identifier] = frozenset()
    deterministic: Literal[True] = True
    bounded: Literal[True] = True
    implementation_sha256: SHA256
    qualification: QualificationState = QualificationState.QUALIFIED

    @model_validator(mode="after")
    def valid_capabilities(self) -> PluginManifest:
        if not self.capabilities:
            raise ValueError("plugin manifest requires at least one capability")
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


class PluginSelection(ContractModel):
    plugin_id: Identifier
    kind: PluginKind
    implementation_version: str
    capabilities_used: frozenset[Identifier]
    manifest_sha256: SHA256
    implementation_sha256: SHA256

    @classmethod
    def from_manifest(
        cls,
        manifest: PluginManifest,
        *,
        capabilities_used: frozenset[str],
    ) -> PluginSelection:
        if not capabilities_used.issubset(manifest.capabilities):
            raise ValueError("selection requests an undeclared plugin capability")
        return cls(
            plugin_id=manifest.plugin_id,
            kind=manifest.kind,
            implementation_version=manifest.implementation_version,
            capabilities_used=capabilities_used,
            manifest_sha256=manifest.sha256,
            implementation_sha256=manifest.implementation_sha256,
        )


class RouteCapability(StrEnum):
    DIRECT = "DIRECT"
    ZONE = "ZONE"
    COVERAGE = "COVERAGE"
    OBSTACLE_AWARE = "OBSTACLE_AWARE"
    TEMPORAL_SEPARATION = "TEMPORAL_SEPARATION"
    DOCK_APPROACH = "DOCK_APPROACH"
    LEADER_FOLLOWER = "LEADER_FOLLOWER"


class RouteObstacle(ContractModel):
    obstacle_id: Identifier
    minimum_m: Vector3
    maximum_m: Vector3

    @model_validator(mode="after")
    def ordered_bounds(self) -> RouteObstacle:
        if not (
            self.minimum_m.x <= self.maximum_m.x
            and self.minimum_m.y <= self.maximum_m.y
            and self.minimum_m.z <= self.maximum_m.z
        ):
            raise ValueError("route obstacle bounds are reversed")
        return self


class RouteTarget(ContractModel):
    position_m: Vector3
    hold_s: float = Field(default=0.0, ge=0.0)


class TemporalReservation(ContractModel):
    reservation_id: Identifier
    role_id: Identifier
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(gt=0.0)
    minimum_m: Vector3
    maximum_m: Vector3

    @model_validator(mode="after")
    def ordered(self) -> TemporalReservation:
        if self.ends_at_s <= self.starts_at_s:
            raise ValueError("reservation must have positive duration")
        if not (
            self.minimum_m.x <= self.maximum_m.x
            and self.minimum_m.y <= self.maximum_m.y
            and self.minimum_m.z <= self.maximum_m.z
        ):
            raise ValueError("reservation spatial bounds are reversed")
        return self


class RoutePlanRequest(ContractModel):
    schema_version: Literal[1] = 1
    request_id: Identifier
    role_id: Identifier
    capability: RouteCapability
    start_m: Vector3
    targets: tuple[RouteTarget, ...]
    zone_minimum_m: Vector3 | None = None
    zone_maximum_m: Vector3 | None = None
    coverage_spacing_m: float = Field(default=0.25, gt=0.0)
    flight_volume_minimum_m: Vector3
    flight_volume_maximum_m: Vector3
    obstacles: tuple[RouteObstacle, ...] = ()
    existing_reservations: tuple[TemporalReservation, ...] = ()
    cruise_speed_m_s: float = Field(gt=0.0)
    maximum_duration_s: float = Field(gt=0.0)
    energy_percent_per_m: float = Field(default=1.0, gt=0.0)
    minimum_separation_m: float = Field(default=0.5, gt=0.0)
    maximum_hold_s: float = Field(default=30.0, ge=0.0)
    frame: CoordinateFrame = CoordinateFrame.WORLD
    supersedes_route_sha256: SHA256 | None = None

    @model_validator(mode="after")
    def bounded_request(self) -> RoutePlanRequest:
        if self.frame is not CoordinateFrame.WORLD:
            raise ValueError("route planning requires the world frame")
        if not self.targets:
            raise ValueError("route planning requires at least one target")
        if (self.zone_minimum_m is None) != (self.zone_maximum_m is None):
            raise ValueError("route zone requires both minimum and maximum bounds")
        if (
            self.zone_minimum_m is not None
            and self.zone_maximum_m is not None
            and not (
                self.zone_minimum_m.x < self.zone_maximum_m.x
                and self.zone_minimum_m.y < self.zone_maximum_m.y
                and self.zone_minimum_m.z <= self.zone_maximum_m.z
            )
        ):
            raise ValueError("route zone bounds are invalid")
        if not (
            self.flight_volume_minimum_m.x < self.flight_volume_maximum_m.x
            and self.flight_volume_minimum_m.y < self.flight_volume_maximum_m.y
            and self.flight_volume_minimum_m.z < self.flight_volume_maximum_m.z
        ):
            raise ValueError("route flight volume is invalid")
        return self


class RouteWaypoint(ContractModel):
    sequence: int = Field(ge=0)
    position_m: Vector3
    arrival_s: float = Field(ge=0.0)
    departure_s: float = Field(ge=0.0)

    @model_validator(mode="after")
    def departure_after_arrival(self) -> RouteWaypoint:
        if self.departure_s < self.arrival_s:
            raise ValueError("waypoint departure precedes arrival")
        return self


class RoutePlanStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class RoutePlanArtifact(ContractModel):
    schema_version: Literal[1] = 1
    request_id: Identifier
    role_id: Identifier
    planner: PluginSelection
    capability: RouteCapability
    status: RoutePlanStatus
    waypoints: tuple[RouteWaypoint, ...]
    reservations: tuple[TemporalReservation, ...]
    route_length_m: float = Field(ge=0.0)
    expected_energy_percent: float = Field(ge=0.0)
    expected_duration_s: float = Field(ge=0.0)
    expected_minimum_separation_m: float = Field(ge=0.0)
    completion_conditions: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    findings: tuple[Identifier, ...] = ()
    supersedes_route_sha256: SHA256 | None = None
    route_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"route_sha256"})


class RouteReplanRequest(ContractModel):
    schema_version: Literal[1] = 1
    previous_route_sha256: SHA256
    changed_observation_sha256: SHA256
    replacement_request: RoutePlanRequest
    planning_budget_s: float = Field(gt=0.0, le=10.0)

    @model_validator(mode="after")
    def binds_previous_authority(self) -> RouteReplanRequest:
        if self.replacement_request.supersedes_route_sha256 != self.previous_route_sha256:
            raise ValueError("replan request does not supersede the current route authority")
        return self


class RouteReplanResult(ContractModel):
    schema_version: Literal[1] = 1
    previous_route_sha256: SHA256
    stale_route_sha256: SHA256
    replacement_route: RoutePlanArtifact
    changed_observation_sha256: SHA256
    replan_sha256: SHA256

    @model_validator(mode="after")
    def replacement_supersedes_previous(self) -> RouteReplanResult:
        if self.previous_route_sha256 != self.stale_route_sha256:
            raise ValueError("replan result must explicitly stale the previous route")
        if self.replacement_route.supersedes_route_sha256 != self.previous_route_sha256:
            raise ValueError("replacement route does not bind the previous route")
        return self

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"replan_sha256"})


class RecoveryTrigger(StrEnum):
    LOW_BATTERY = "LOW_BATTERY"
    LEADER_LOSS = "LEADER_LOSS"
    LINK_LOSS = "LINK_LOSS"
    LOCALIZATION_LOSS = "LOCALIZATION_LOSS"
    RESERVE_LOSS = "RESERVE_LOSS"
    DOCK_UNAVAILABLE = "DOCK_UNAVAILABLE"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    ACKNOWLEDGEMENT_LOSS = "ACKNOWLEDGEMENT_LOSS"


class RecoveryAction(StrEnum):
    HOLD = "HOLD"
    REPLAN = "REPLAN"
    RETURN_HOME = "RETURN_HOME"
    HANDOVER = "HANDOVER"
    LAND = "LAND"
    ABORT_AND_LAND = "ABORT_AND_LAND"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class FleetPolicyRequest(ContractModel):
    schema_version: Literal[1] = 1
    request_id: Identifier
    mission_id: Identifier
    policy_capability: Identifier
    role_ids: tuple[Identifier, ...]
    active_role_ids: tuple[Identifier, ...]
    reserve_role_ids: tuple[Identifier, ...] = ()
    route_sha256s: tuple[SHA256, ...] = ()
    warning_separation_m: float = Field(gt=0.0)
    critical_separation_m: float = Field(gt=0.0)


class FleetPolicyDecision(ContractModel):
    schema_version: Literal[1] = 1
    request_id: Identifier
    policy: PluginSelection
    launch_order: tuple[Identifier, ...]
    held_role_ids: tuple[Identifier, ...] = ()
    active_role_ids: tuple[Identifier, ...]
    reserve_role_ids: tuple[Identifier, ...] = ()
    rationale: tuple[str, ...]
    decision_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"decision_sha256"})


class RecoveryRequest(ContractModel):
    schema_version: Literal[1] = 1
    request_id: Identifier
    mission_id: Identifier
    trigger: RecoveryTrigger
    role_id: Identifier
    vehicle_id: Identifier
    available_actions: frozenset[RecoveryAction]
    observation_current: bool
    authority_current: bool
    lease_generation: int | None = Field(default=None, ge=1)
    deadline_s: float = Field(gt=0.0)


class RecoveryProposal(ContractModel):
    schema_version: Literal[1] = 1
    request_id: Identifier
    strategy: PluginSelection
    action: RecoveryAction
    role_id: Identifier
    vehicle_id: Identifier
    reason: str = Field(min_length=1, max_length=500)
    preconditions: tuple[str, ...]
    deadline_s: float = Field(gt=0.0)
    fallback: RecoveryAction
    required_evidence: tuple[Identifier, ...]
    proposal_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"proposal_sha256"})


class MissionSafetyDeclaration(ContractModel):
    schema_version: Literal[1] = 1
    declaration_id: Identifier
    policy_override: SafetyPolicyOverride = Field(default_factory=SafetyPolicyOverride)
    required_observations: frozenset[Identifier] = frozenset()
    environmental_assumptions: tuple[str, ...] = ()
    allowed_recovery_actions: frozenset[RecoveryAction]


class SafetyCaseFinding(ContractModel):
    code: Identifier
    blocking: bool
    message: str = Field(min_length=1, max_length=500)
    owner: Identifier
    mitigation: str = Field(min_length=1, max_length=500)


class SafetyCaseReceipt(ContractModel):
    schema_version: Literal[1] = 1
    declaration_sha256: SHA256
    global_policy_sha256: SHA256
    effective_policy_sha256: SHA256
    selected_plugin_manifest_sha256s: tuple[SHA256, ...]
    hazards: tuple[Identifier, ...]
    mitigations: tuple[str, ...]
    findings: tuple[SafetyCaseFinding, ...]
    safety_case_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"safety_case_sha256"})


class SafetyAdmission(ContractModel):
    authorized: bool
    action: RecoveryAction
    reason: str
    effective_policy_sha256: SHA256
    proposal_sha256: SHA256


class RoutePlanner(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def plan(self, request: RoutePlanRequest) -> RoutePlanArtifact: ...


class FleetPolicy(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def decide(self, request: FleetPolicyRequest) -> FleetPolicyDecision: ...


class RecoveryStrategy(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def propose(self, request: RecoveryRequest) -> RecoveryProposal: ...
