from __future__ import annotations

import math
import time
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.fleet.artifacts import DeploymentManifest, InitialFleetRole
from crazyswarm_app.planning.builtins import (
    default_fleet_policy_registry,
    default_recovery_registry,
    default_route_planner_registry,
)
from crazyswarm_app.planning.contracts import (
    FleetPolicyDecision,
    FleetPolicyRequest,
    MissionSafetyDeclaration,
    PluginManifest,
    PluginSelection,
    RecoveryAction,
    RouteCapability,
    RouteObstacle,
    RoutePlanArtifact,
    RoutePlanner,
    RoutePlanRequest,
    RouteReplanRequest,
    RouteReplanResult,
    RouteTarget,
    SafetyCaseReceipt,
    TemporalReservation,
)
from crazyswarm_app.planning.intent import (
    ExecutionGraph,
    IntentPhase,
    IntentTransition,
    MissionIntent,
    TransitionKind,
    compile_execution_graph,
)
from crazyswarm_app.planning.safety import SafetyKernel
from crazyswarm_app.safety.policy import SafetyPolicy


class OperationalRouteInput(ContractModel):
    role_id: Identifier
    vehicle_id: Identifier
    initial_role: InitialFleetRole
    start_m: Vector3
    targets_m: tuple[Vector3, ...]
    planned_duration_s: float = Field(ge=0.0)


class PlanningBundle(ContractModel):
    schema_version: Literal[1] = 1
    plugin_selections: tuple[PluginSelection, ...]
    route_plans: tuple[RoutePlanArtifact, ...]
    fleet_policy_decision: FleetPolicyDecision
    mission_intent: MissionIntent
    execution_graph: ExecutionGraph
    safety_case: SafetyCaseReceipt
    bundle_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"bundle_sha256"})


def replan_route(
    planner: RoutePlanner,
    request: RouteReplanRequest,
) -> RouteReplanResult:
    started = time.monotonic()
    replacement = planner.plan(request.replacement_request)
    if time.monotonic() - started > request.planning_budget_s:
        raise TimeoutError("route replan exceeded its declared planning budget")
    payload = {
        "previous_route_sha256": request.previous_route_sha256,
        "stale_route_sha256": request.previous_route_sha256,
        "replacement_route": replacement,
        "changed_observation_sha256": request.changed_observation_sha256,
    }
    return RouteReplanResult(**payload, replan_sha256=canonical_sha256(payload))


def compile_operational_planning_bundle(
    *,
    mission_id: str,
    deployment: DeploymentManifest,
    roles: tuple[OperationalRouteInput, ...],
    policy: SafetyPolicy,
    obstacles: tuple[RouteObstacle, ...] = (),
) -> PlanningBundle:
    route_registry = default_route_planner_registry()
    policy_registry = default_fleet_policy_registry()
    recovery_registry = default_recovery_registry()
    active_roles = tuple(
        sorted(
            (role for role in roles if role.initial_role is InitialFleetRole.ACTIVE),
            key=lambda item: item.role_id,
        )
    )
    route_capability = (
        RouteCapability.TEMPORAL_SEPARATION if len(active_roles) > 1 else RouteCapability.DIRECT
    )
    route_plugin_id = "route.temporal" if len(active_roles) > 1 else "route.direct"
    route_planner = route_registry.resolve(
        route_plugin_id,
        "1.0.0",
        required_capabilities=frozenset({route_capability.value}),
    )
    route_plans: list[RoutePlanArtifact] = []
    reservations: tuple[TemporalReservation, ...] = ()
    for role in active_roles:
        targets = role.targets_m or (role.start_m,)
        route_length = _path_length((role.start_m, *targets))
        transit_duration = route_length / min(0.4, policy.max_horizontal_speed_m_s)
        final_hold = max(0.0, role.planned_duration_s - transit_duration)
        route_targets = tuple(
            RouteTarget(
                position_m=target,
                hold_s=final_hold if index == len(targets) - 1 else 0.0,
            )
            for index, target in enumerate(targets)
        )
        request = RoutePlanRequest(
            request_id=f"route-{mission_id}-{role.role_id}",
            role_id=role.role_id,
            capability=route_capability,
            start_m=role.start_m,
            targets=route_targets,
            flight_volume_minimum_m=policy.flight_volume.minimum_m,
            flight_volume_maximum_m=policy.flight_volume.maximum_m,
            obstacles=obstacles,
            existing_reservations=reservations,
            cruise_speed_m_s=min(0.4, policy.max_horizontal_speed_m_s),
            maximum_duration_s=policy.max_mission_duration_s,
            minimum_separation_m=deployment.constraints.critical_separation_m,
            maximum_hold_s=min(30.0, policy.max_mission_duration_s / 4.0),
        )
        route = route_planner.plan(request)
        route_plans.append(route)
        reservations = (*reservations, *route.reservations)

    policy_capability = _policy_capability(deployment)
    fleet_policy = policy_registry.resolve(
        f"fleet.{policy_capability}",
        "1.0.0",
        required_capabilities=frozenset({policy_capability}),
    )
    active_role_ids = tuple(item.role_id for item in active_roles)
    reserve_role_ids = tuple(
        sorted(role.role_id for role in roles if role.initial_role is InitialFleetRole.RESERVE)
    )
    fleet_decision = fleet_policy.decide(
        FleetPolicyRequest(
            request_id=f"fleet-policy-{mission_id}",
            mission_id=mission_id,
            policy_capability=policy_capability,
            role_ids=tuple(sorted(role.role_id for role in roles)),
            active_role_ids=active_role_ids,
            reserve_role_ids=reserve_role_ids,
            route_sha256s=tuple(item.route_sha256 for item in route_plans),
            warning_separation_m=deployment.constraints.warning_separation_m,
            critical_separation_m=deployment.constraints.critical_separation_m,
        )
    )

    recovery_manifests = recovery_registry.manifests()
    declaration = MissionSafetyDeclaration(
        declaration_id=f"safety-{mission_id}",
        required_observations=frozenset(
            {"vehicle-health", "authority-state", "localization", "link", "battery"}
        ),
        environmental_assumptions=(
            "configured world geometry is current",
            "simulation observations retain source and freshness",
        ),
        allowed_recovery_actions=frozenset(RecoveryAction),
    )
    manifests = (
        route_planner.manifest,
        fleet_policy.manifest,
        *recovery_manifests,
    )
    selections = _selections(manifests)
    intent = MissionIntent(
        intent_id=f"intent-{mission_id}",
        mission_id=mission_id,
        objective="execute the restricted Python mission's declared actions exactly",
        success_criteria=("all required roles complete their accepted action sequence",),
        role_ids=active_role_ids,
        phases=(
            IntentPhase(
                phase_id="explicit-actions",
                objective="execute accepted backend-neutral role actions",
                role_ids=active_role_ids,
                route_capability=route_capability,
                completion_conditions=("all active roles report terminal success",),
                maximum_duration_s=policy.max_mission_duration_s,
            ),
        ),
        entry_phase_id="explicit-actions",
        transitions=(
            IntentTransition(
                transition_id="explicit-actions-complete",
                from_phase_id="explicit-actions",
                kind=TransitionKind.COMPLETE,
            ),
        ),
        safety_declaration=declaration,
        source_compatibility="RESTRICTED_PYTHON_EXPLICIT_ACTIONS",
    )
    graph = compile_execution_graph(intent, tuple(route_plans), selections)
    safety_case = SafetyKernel().compile_safety_case(policy, declaration, manifests)
    payload = {
        "plugin_selections": selections,
        "route_plans": tuple(route_plans),
        "fleet_policy_decision": fleet_decision,
        "mission_intent": intent,
        "execution_graph": graph,
        "safety_case": safety_case,
    }
    return PlanningBundle(**payload, bundle_sha256=canonical_sha256(payload))


def _selections(manifests: tuple[PluginManifest, ...]) -> tuple[PluginSelection, ...]:
    return tuple(
        PluginSelection.from_manifest(
            manifest,
            capabilities_used=manifest.capabilities,
        )
        for manifest in sorted(manifests, key=lambda item: (item.kind.value, item.plugin_id))
    )


def _policy_capability(deployment: DeploymentManifest) -> str:
    task_types = {task.task_type for task in deployment.tasks}
    if any("persistent" in task_type or "coverage" in task_type for task_type in task_types):
        return "persistent-coverage"
    if any("crossing" in task_type for task_type in task_types):
        return "crossing-route"
    if any("leader" in task_type or "follower" in task_type for task_type in task_types):
        return "leader-follower"
    return "independent-tasks"


def _path_length(points: tuple[Vector3, ...]) -> float:
    return sum(
        math.sqrt(
            (point.x - points[index - 1].x) ** 2
            + (point.y - points[index - 1].y) ** 2
            + (point.z - points[index - 1].z) ** 2
        )
        for index, point in enumerate(points[1:], start=1)
    )
