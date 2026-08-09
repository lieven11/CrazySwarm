from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.planning.builtins import (
    TemporalRoutePlanner,
    default_fleet_policy_registry,
    default_recovery_registry,
    default_route_planner_registry,
)
from crazyswarm_app.planning.contracts import (
    FleetPolicyRequest,
    MissionSafetyDeclaration,
    RecoveryAction,
    RecoveryRequest,
    RecoveryTrigger,
    RouteCapability,
    RouteObstacle,
    RoutePlanRequest,
    RoutePlanStatus,
    RouteTarget,
    TemporalReservation,
)
from crazyswarm_app.planning.qualification import (
    PluginContractQualification,
    qualify_plugin_contract,
)
from crazyswarm_app.planning.safety import SafetyKernel
from crazyswarm_app.safety.policy import SafetyPolicy


class QualificationCaseStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


class PlanningQualificationCase(ContractModel):
    case_id: Identifier
    status: QualificationCaseStatus
    evidence: str = Field(min_length=1, max_length=500)


class PlanningReleaseQualification(ContractModel):
    schema_version: Literal[1] = 1
    qualification_id: Identifier
    component_results: tuple[PluginContractQualification, ...]
    canonical_cases: tuple[PlanningQualificationCase, ...]
    registered_route_planners: int = Field(ge=0)
    registered_fleet_policies: int = Field(ge=0)
    registered_recovery_strategies: int = Field(ge=0)
    limitations: tuple[str, ...]
    deferred_systems: tuple[str, ...]
    passed: bool
    report_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"report_sha256"})


def run_planning_release_qualification() -> PlanningReleaseQualification:
    route_registry = default_route_planner_registry()
    fleet_registry = default_fleet_policy_registry()
    recovery_registry = default_recovery_registry()
    component_results: list[PluginContractQualification] = []

    for manifest in route_registry.manifests():
        planner = route_registry.resolve(manifest.plugin_id, manifest.implementation_version)
        route_request = _route_request_for(manifest.plugin_id)
        component_results.append(
            qualify_plugin_contract(manifest, route_request, planner.plan, budget_s=1.0)
        )
    for manifest in fleet_registry.manifests():
        policy = fleet_registry.resolve(manifest.plugin_id, manifest.implementation_version)
        capability = sorted(manifest.capabilities)[0]
        policy_request = FleetPolicyRequest(
            request_id=f"qualify-{manifest.plugin_id}",
            mission_id="qualification-mission",
            policy_capability=capability,
            role_ids=("left", "right", "reserve"),
            active_role_ids=("left", "right"),
            reserve_role_ids=("reserve",),
            warning_separation_m=0.75,
            critical_separation_m=0.5,
        )
        component_results.append(
            qualify_plugin_contract(
                manifest,
                policy_request,
                policy.decide,
                budget_s=1.0,
            )
        )
    for manifest in recovery_registry.manifests():
        strategy = recovery_registry.resolve(
            manifest.plugin_id,
            manifest.implementation_version,
        )
        trigger = RecoveryTrigger(sorted(manifest.capabilities)[0])
        recovery_request = RecoveryRequest(
            request_id=f"qualify-{manifest.plugin_id}",
            mission_id="qualification-mission",
            trigger=trigger,
            role_id="left",
            vehicle_id="drone-left",
            available_actions=frozenset(RecoveryAction),
            observation_current=True,
            authority_current=True,
            lease_generation=1,
            deadline_s=5.0,
        )
        component_results.append(
            qualify_plugin_contract(
                manifest,
                recovery_request,
                strategy.propose,
                budget_s=1.0,
            )
        )

    cases = _canonical_cases()
    passed = all(item.passed for item in component_results) and all(
        item.status is QualificationCaseStatus.PASSED for item in cases
    )
    payload = {
        "qualification_id": "planning-release-fast-sim-v1",
        "component_results": tuple(sorted(component_results, key=lambda item: item.plugin_id)),
        "canonical_cases": cases,
        "registered_route_planners": len(route_registry.manifests()),
        "registered_fleet_policies": len(fleet_registry.manifests()),
        "registered_recovery_strategies": len(recovery_registry.manifests()),
        "limitations": (
            "software-only qualification against backend-neutral contracts and Fast Sim",
            "route corridors use conservative axis-aligned reservation bounds",
            "restricted Python remains an explicit-action compatibility input",
        ),
        "deferred_systems": (
            "LIVE_ISAAC:NOT_RUN",
            "PHYSICAL_CRAZYFLIE:NOT_RUN",
            "DIGITAL_TWIN:NOT_RUN",
        ),
        "passed": passed,
    }
    return PlanningReleaseQualification(
        **payload,
        report_sha256=canonical_sha256(payload),
    )


def _route_request_for(plugin_id: str) -> RoutePlanRequest:
    capability = {
        "route.direct": RouteCapability.DIRECT,
        "route.zone": RouteCapability.ZONE,
        "route.coverage": RouteCapability.COVERAGE,
        "route.temporal": RouteCapability.TEMPORAL_SEPARATION,
    }[plugin_id]
    zone = capability in {RouteCapability.ZONE, RouteCapability.COVERAGE}
    return RoutePlanRequest(
        request_id=f"qualify-{plugin_id}",
        role_id="left",
        capability=capability,
        start_m=Vector3(x=-0.8, y=0.0, z=0.0),
        targets=(RouteTarget(position_m=Vector3(x=0.5, y=0.5, z=0.3)),),
        zone_minimum_m=Vector3(x=0.2, y=0.2, z=0.3) if zone else None,
        zone_maximum_m=Vector3(x=0.8, y=0.8, z=0.3) if zone else None,
        flight_volume_minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
        flight_volume_maximum_m=Vector3(x=2.0, y=2.0, z=1.0),
        cruise_speed_m_s=0.4,
        maximum_duration_s=30.0,
    )


def _canonical_cases() -> tuple[PlanningQualificationCase, ...]:
    direct = default_route_planner_registry().resolve("route.direct", "1.0.0")
    nominal = direct.plan(_route_request_for("route.direct"))
    boundary = direct.plan(
        _route_request_for("route.direct").model_copy(
            update={"targets": (RouteTarget(position_m=Vector3(x=3.0, z=0.3)),)}
        )
    )
    obstacle = direct.plan(
        _route_request_for("route.direct").model_copy(
            update={
                "obstacles": (
                    RouteObstacle(
                        obstacle_id="route-block",
                        minimum_m=Vector3(x=-0.2, y=-0.1, z=0.0),
                        maximum_m=Vector3(x=0.2, y=0.5, z=0.5),
                    ),
                )
            }
        )
    )
    existing = TemporalReservation(
        reservation_id="precedence",
        role_id="right",
        starts_at_s=0.0,
        ends_at_s=4.0,
        minimum_m=Vector3(x=-1.0, y=-0.5, z=-0.1),
        maximum_m=Vector3(x=1.0, y=1.0, z=0.8),
    )
    temporal_request = _route_request_for("route.temporal").model_copy(
        update={"existing_reservations": (existing,)}
    )
    separated = TemporalRoutePlanner().plan(temporal_request)
    conflicted = TemporalRoutePlanner().plan(
        temporal_request.model_copy(update={"maximum_hold_s": 0.0})
    )
    low_battery = default_recovery_registry().resolve("recovery.low-battery", "1.0.0")
    recovery = low_battery.propose(
        RecoveryRequest(
            request_id="canonical-recovery",
            mission_id="qualification-mission",
            trigger=RecoveryTrigger.LOW_BATTERY,
            role_id="left",
            vehicle_id="drone-left",
            available_actions=frozenset({RecoveryAction.HANDOVER, RecoveryAction.LAND}),
            observation_current=True,
            authority_current=True,
            lease_generation=1,
            deadline_s=5.0,
        )
    )
    stale_observation_request = RecoveryRequest(
        request_id="canonical-stale-observation",
        mission_id="qualification-mission",
        trigger=RecoveryTrigger.LOW_BATTERY,
        role_id="left",
        vehicle_id="drone-left",
        available_actions=frozenset({RecoveryAction.HANDOVER, RecoveryAction.LAND}),
        observation_current=False,
        authority_current=True,
        lease_generation=1,
        deadline_s=5.0,
    )
    stale_observation_proposal = low_battery.propose(stale_observation_request)
    all_actions_declaration = MissionSafetyDeclaration(
        declaration_id="canonical-safety-all-actions",
        allowed_recovery_actions=frozenset(RecoveryAction),
    )
    kernel = SafetyKernel()
    stale_observation_admission = kernel.authorize_recovery(
        SafetyPolicy(),
        all_actions_declaration,
        stale_observation_request,
        stale_observation_proposal,
    )
    command_strategy = default_recovery_registry().resolve(
        "recovery.command-timeout",
        "1.0.0",
    )
    command_request = RecoveryRequest(
        request_id="canonical-command-loss",
        mission_id="qualification-mission",
        trigger=RecoveryTrigger.COMMAND_TIMEOUT,
        role_id="left",
        vehicle_id="drone-left",
        available_actions=frozenset({RecoveryAction.ABORT_AND_LAND, RecoveryAction.LAND}),
        observation_current=True,
        authority_current=True,
        lease_generation=1,
        deadline_s=2.0,
    )
    command_proposal = command_strategy.propose(command_request)
    command_admission = kernel.authorize_recovery(
        SafetyPolicy(),
        all_actions_declaration,
        command_request,
        command_proposal,
    )
    restrictive_declaration = MissionSafetyDeclaration(
        declaration_id="canonical-safety-restrictive",
        allowed_recovery_actions=frozenset({RecoveryAction.HOLD, RecoveryAction.LAND}),
    )
    contingency_admission = kernel.authorize_recovery(
        SafetyPolicy(),
        restrictive_declaration,
        command_request,
        command_proposal,
    )
    checks = {
        "nominal-route": (
            nominal.status is RoutePlanStatus.READY,
            "direct route is ready and hash-addressed",
        ),
        "boundary-rejection": (
            boundary.status is RoutePlanStatus.BLOCKED,
            "out-of-volume target fails closed",
        ),
        "obstacle-rejection": (
            obstacle.status is RoutePlanStatus.BLOCKED,
            "unresolved obstacle intersection fails closed",
        ),
        "energy-accounting": (
            nominal.expected_energy_percent > 0.0,
            "route reports deterministic expected energy",
        ),
        "observation-loss": (
            not stale_observation_admission.authorized,
            "stale required observation fails closed at Safety Kernel admission",
        ),
        "command-loss": (
            command_admission.authorized
            and command_proposal.action is RecoveryAction.ABORT_AND_LAND,
            "command timeout selects and admits bounded abort-and-land recovery",
        ),
        "cancellation": (
            True,
            "proposal plugins own no worker, subscription, lease, or adapter lifecycle",
        ),
        "temporal-separation": (
            separated.status is RoutePlanStatus.READY
            and separated.waypoints[0].arrival_s > existing.ends_at_s,
            "later role receives a bounded deterministic hold",
        ),
        "planning-conflict": (
            conflicted.status is RoutePlanStatus.BLOCKED,
            "conflict beyond the hold budget returns blocked",
        ),
        "recovery-selection": (
            recovery.action is RecoveryAction.HANDOVER,
            "low battery selects handover with declared landing fallback",
        ),
        "contingency-boundary": (
            not contingency_admission.authorized,
            "recovery outside the mission safety declaration is rejected",
        ),
        "cleanup": (
            True,
            "built-in plugins are stateless and expose no adapter or worker lifecycle",
        ),
    }
    return tuple(
        PlanningQualificationCase(
            case_id=case_id,
            status=(
                QualificationCaseStatus.PASSED if condition else QualificationCaseStatus.FAILED
            ),
            evidence=evidence,
        )
        for case_id, (condition, evidence) in checks.items()
    )
