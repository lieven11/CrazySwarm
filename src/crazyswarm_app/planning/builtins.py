from __future__ import annotations

import math
from dataclasses import dataclass

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.fleet.artifacts import (
    DeploymentTaskDefinition,
    ZoneDefinition,
    ZoneGeometry,
)
from crazyswarm_app.fleet.zones import ZoneObstacle, ZoneTaskPlanner
from crazyswarm_app.planning.contracts import (
    FleetPolicy,
    FleetPolicyDecision,
    FleetPolicyRequest,
    PluginKind,
    PluginManifest,
    PluginSelection,
    RecoveryAction,
    RecoveryProposal,
    RecoveryRequest,
    RecoveryStrategy,
    RecoveryTrigger,
    RouteCapability,
    RouteObstacle,
    RoutePlanArtifact,
    RoutePlanner,
    RoutePlanRequest,
    RoutePlanStatus,
    RouteWaypoint,
    TemporalReservation,
)
from crazyswarm_app.planning.registry import PluginRegistry


def _manifest(
    plugin_id: str,
    kind: PluginKind,
    capabilities: frozenset[str],
    *,
    required_observations: frozenset[str] = frozenset(),
) -> PluginManifest:
    version = "1.0.0"
    return PluginManifest(
        plugin_id=plugin_id,
        kind=kind,
        implementation_version=version,
        control_contract_minimum="1.0.0",
        control_contract_maximum="1.0.0",
        capabilities=capabilities,
        required_observations=required_observations,
        implementation_sha256=canonical_sha256(
            {
                "implementation": plugin_id,
                "version": version,
                "contract": "planning-plugin-v1",
            }
        ),
    )


class DirectRoutePlanner:
    manifest = _manifest(
        "route.direct",
        PluginKind.ROUTE_PLANNER,
        frozenset(
            {
                RouteCapability.DIRECT.value,
                RouteCapability.DOCK_APPROACH.value,
                RouteCapability.LEADER_FOLLOWER.value,
            }
        ),
    )

    def plan(self, request: RoutePlanRequest) -> RoutePlanArtifact:
        return _plan_polyline(
            self.manifest,
            request,
            tuple(item.position_m for item in request.targets),
        )


class ZoneRoutePlanner:
    """WP-13 adapter around the existing deterministic ZoneTaskPlanner."""

    manifest = _manifest(
        "route.zone",
        PluginKind.ROUTE_PLANNER,
        frozenset({RouteCapability.ZONE.value, RouteCapability.OBSTACLE_AWARE.value}),
    )

    def __init__(self) -> None:
        self._planner = ZoneTaskPlanner()

    def plan(self, request: RoutePlanRequest) -> RoutePlanArtifact:
        target = request.targets[-1].position_m
        minimum = request.zone_minimum_m or Vector3(
            x=target.x - 0.01,
            y=target.y - 0.01,
            z=target.z,
        )
        maximum = request.zone_maximum_m or Vector3(
            x=target.x + 0.01,
            y=target.y + 0.01,
            z=target.z,
        )
        zone = ZoneDefinition(
            zone_id=f"zone-{request.request_id}",
            geometry=ZoneGeometry(minimum_m=minimum, maximum_m=maximum),
        )
        task = DeploymentTaskDefinition(
            task_id=request.role_id,
            task_type="route-zone",
            zone_id=zone.zone_id,
            mission_id=request.request_id,
            estimated_duration_s=max(4.1, request.maximum_duration_s),
            estimated_energy_percent=0.01,
            energy_margin_percent=0.0,
        )
        route = self._planner.plan(
            task,
            zone,
            start_m=request.start_m,
            obstacles=tuple(
                ZoneObstacle(
                    obstacle_id=item.obstacle_id,
                    minimum_m=item.minimum_m,
                    maximum_m=item.maximum_m,
                )
                for item in request.obstacles
            ),
            flight_height_m=max(target.z, minimum.z),
        )
        return _plan_polyline(self.manifest, request, route.waypoints_m)


class CoverageRoutePlanner:
    manifest = _manifest(
        "route.coverage",
        PluginKind.ROUTE_PLANNER,
        frozenset({RouteCapability.COVERAGE.value}),
    )

    def plan(self, request: RoutePlanRequest) -> RoutePlanArtifact:
        minimum = request.zone_minimum_m
        maximum = request.zone_maximum_m
        if minimum is None or maximum is None:
            return _blocked(self.manifest, request, "COVERAGE_ZONE_UNAVAILABLE")
        z_m = request.targets[-1].position_m.z
        rows = max(1, math.ceil((maximum.y - minimum.y) / request.coverage_spacing_m))
        points: list[Vector3] = []
        for index in range(rows + 1):
            y_m = min(maximum.y, minimum.y + index * request.coverage_spacing_m)
            endpoints = (minimum.x, maximum.x) if index % 2 == 0 else (maximum.x, minimum.x)
            points.extend(Vector3(x=x_m, y=y_m, z=z_m) for x_m in endpoints)
        return _plan_polyline(self.manifest, request, tuple(points))


class TemporalRoutePlanner:
    manifest = _manifest(
        "route.temporal",
        PluginKind.ROUTE_PLANNER,
        frozenset({RouteCapability.TEMPORAL_SEPARATION.value}),
        required_observations=frozenset({"peer-route-reservations"}),
    )

    def plan(self, request: RoutePlanRequest) -> RoutePlanArtifact:
        base = _plan_polyline(
            self.manifest,
            request,
            tuple(item.position_m for item in request.targets),
            apply_temporal_shift=False,
        )
        if base.status is RoutePlanStatus.BLOCKED:
            return base
        shift_s = 0.0
        for current in base.reservations:
            for existing in request.existing_reservations:
                if _reservations_conflict(current, existing):
                    shift_s = max(shift_s, existing.ends_at_s - current.starts_at_s + 0.001)
        if shift_s > request.maximum_hold_s:
            return _blocked(self.manifest, request, "TEMPORAL_CORRIDOR_UNAVAILABLE")
        if shift_s <= 0.0:
            return base
        shifted_waypoints = tuple(
            item.model_copy(
                update={
                    "arrival_s": item.arrival_s + shift_s,
                    "departure_s": item.departure_s + shift_s,
                }
            )
            for item in base.waypoints
        )
        shifted_reservations = tuple(
            item.model_copy(
                update={
                    "starts_at_s": item.starts_at_s + shift_s,
                    "ends_at_s": item.ends_at_s + shift_s,
                }
            )
            for item in base.reservations
        )
        return _route_artifact(
            manifest=self.manifest,
            request=request,
            status=RoutePlanStatus.READY,
            waypoints=shifted_waypoints,
            reservations=shifted_reservations,
            route_length_m=base.route_length_m,
            duration_s=base.expected_duration_s + shift_s,
            limitations=(f"role held for {shift_s:.3f}s for temporal precedence",),
        )


@dataclass(frozen=True, slots=True)
class DeterministicFleetPolicy:
    manifest: PluginManifest

    def decide(self, request: FleetPolicyRequest) -> FleetPolicyDecision:
        active = tuple(sorted(request.active_role_ids))
        reserve = tuple(sorted(request.reserve_role_ids))
        launch_order = active
        held: tuple[str, ...] = ()
        rationale = [f"policy capability {request.policy_capability} selected"]
        if request.policy_capability == "crossing-route" and len(active) > 1:
            launch_order = tuple(sorted(active))
            held = launch_order[1:]
            rationale.append("lexical role precedence resolves the initial crossing")
        elif request.policy_capability == "persistent-coverage":
            rationale.append("reserve roles remain connected, ready, and disarmed")
        elif request.policy_capability == "leader-follower" and active:
            rationale.append(f"{active[0]} is the deterministic initial leader")
        payload = {
            "request_id": request.request_id,
            "policy": PluginSelection.from_manifest(
                self.manifest,
                capabilities_used=frozenset({request.policy_capability}),
            ),
            "launch_order": launch_order,
            "held_role_ids": held,
            "active_role_ids": active,
            "reserve_role_ids": reserve,
            "rationale": tuple(rationale),
        }
        return FleetPolicyDecision(
            **payload,
            decision_sha256=canonical_sha256(payload),
        )


@dataclass(frozen=True, slots=True)
class DeterministicRecoveryStrategy:
    manifest: PluginManifest
    trigger: RecoveryTrigger
    preferred_action: RecoveryAction
    fallback: RecoveryAction

    def propose(self, request: RecoveryRequest) -> RecoveryProposal:
        if request.trigger is not self.trigger:
            raise ValueError(f"strategy does not handle trigger {request.trigger}")
        action = (
            self.preferred_action
            if self.preferred_action in request.available_actions
            else self.fallback
        )
        if action not in request.available_actions:
            raise ValueError("no declared recovery action is available")
        payload = {
            "request_id": request.request_id,
            "strategy": PluginSelection.from_manifest(
                self.manifest,
                capabilities_used=frozenset({request.trigger.value}),
            ),
            "action": action,
            "role_id": request.role_id,
            "vehicle_id": request.vehicle_id,
            "reason": f"deterministic response to {request.trigger.value}",
            "preconditions": (
                "current vehicle and role identity",
                "current execution authority",
                "Safety Kernel admission",
            ),
            "deadline_s": request.deadline_s,
            "fallback": self.fallback,
            "required_evidence": (
                "trigger-observation",
                "authority-snapshot",
                "safety-admission",
            ),
        }
        return RecoveryProposal(
            **payload,
            proposal_sha256=canonical_sha256(payload),
        )


def default_route_planner_registry() -> PluginRegistry[RoutePlanner]:
    registry: PluginRegistry[RoutePlanner] = PluginRegistry(PluginKind.ROUTE_PLANNER)
    for plugin in (
        DirectRoutePlanner(),
        ZoneRoutePlanner(),
        CoverageRoutePlanner(),
        TemporalRoutePlanner(),
    ):
        registry.register(plugin)
    return registry


def default_fleet_policy_registry() -> PluginRegistry[FleetPolicy]:
    registry: PluginRegistry[FleetPolicy] = PluginRegistry(PluginKind.FLEET_POLICY)
    for capability in (
        "persistent-coverage",
        "crossing-route",
        "leader-follower",
        "independent-tasks",
    ):
        registry.register(
            DeterministicFleetPolicy(
                manifest=_manifest(
                    f"fleet.{capability}",
                    PluginKind.FLEET_POLICY,
                    frozenset({capability}),
                    required_observations=frozenset({"fleet-state", "route-reservations"}),
                )
            )
        )
    return registry


def default_recovery_registry() -> PluginRegistry[RecoveryStrategy]:
    registry: PluginRegistry[RecoveryStrategy] = PluginRegistry(PluginKind.RECOVERY_STRATEGY)
    actions = {
        RecoveryTrigger.LOW_BATTERY: (RecoveryAction.HANDOVER, RecoveryAction.LAND),
        RecoveryTrigger.LEADER_LOSS: (RecoveryAction.LAND, RecoveryAction.ABORT_AND_LAND),
        RecoveryTrigger.LINK_LOSS: (RecoveryAction.RETURN_HOME, RecoveryAction.LAND),
        RecoveryTrigger.LOCALIZATION_LOSS: (RecoveryAction.LAND, RecoveryAction.EMERGENCY_STOP),
        RecoveryTrigger.RESERVE_LOSS: (RecoveryAction.HOLD, RecoveryAction.LAND),
        RecoveryTrigger.DOCK_UNAVAILABLE: (RecoveryAction.REPLAN, RecoveryAction.LAND),
        RecoveryTrigger.COMMAND_TIMEOUT: (RecoveryAction.ABORT_AND_LAND, RecoveryAction.LAND),
        RecoveryTrigger.ACKNOWLEDGEMENT_LOSS: (
            RecoveryAction.ABORT_AND_LAND,
            RecoveryAction.LAND,
        ),
    }
    for trigger, (preferred, fallback) in actions.items():
        registry.register(
            DeterministicRecoveryStrategy(
                manifest=_manifest(
                    f"recovery.{trigger.value.lower().replace('_', '-')}",
                    PluginKind.RECOVERY_STRATEGY,
                    frozenset({trigger.value}),
                    required_observations=frozenset({"vehicle-health", "authority-state"}),
                ),
                trigger=trigger,
                preferred_action=preferred,
                fallback=fallback,
            )
        )
    return registry


def _plan_polyline(
    manifest: PluginManifest,
    request: RoutePlanRequest,
    targets: tuple[Vector3, ...],
    *,
    apply_temporal_shift: bool = True,
) -> RoutePlanArtifact:
    points = (request.start_m, *targets)
    if any(not _inside_volume(point, request) for point in points):
        return _blocked(manifest, request, "ROUTE_OUTSIDE_FLIGHT_VOLUME")
    if any(
        _segment_intersects_box(points[index - 1], point, obstacle)
        for index, point in enumerate(points[1:], start=1)
        for obstacle in request.obstacles
    ):
        return _blocked(manifest, request, "ROUTE_INTERSECTS_OBSTACLE")
    waypoints: list[RouteWaypoint] = [
        RouteWaypoint(sequence=0, position_m=request.start_m, arrival_s=0.0, departure_s=0.0)
    ]
    elapsed_s = 0.0
    length_m = 0.0
    for index, target in enumerate(targets, start=1):
        segment_m = _distance(points[index - 1], target)
        length_m += segment_m
        elapsed_s += segment_m / request.cruise_speed_m_s
        hold_s = request.targets[min(index - 1, len(request.targets) - 1)].hold_s
        waypoints.append(
            RouteWaypoint(
                sequence=index,
                position_m=target,
                arrival_s=elapsed_s,
                departure_s=elapsed_s + hold_s,
            )
        )
        elapsed_s += hold_s
    if elapsed_s > request.maximum_duration_s:
        return _blocked(manifest, request, "ROUTE_DURATION_EXCEEDS_BOUND")
    corridor = _reservation(request, tuple(waypoints), elapsed_s)
    if apply_temporal_shift and any(
        _reservations_conflict(corridor, existing) for existing in request.existing_reservations
    ):
        return _blocked(manifest, request, "TEMPORAL_RESERVATION_REQUIRED")
    return _route_artifact(
        manifest=manifest,
        request=request,
        status=RoutePlanStatus.READY,
        waypoints=tuple(waypoints),
        reservations=(corridor,),
        route_length_m=length_m,
        duration_s=elapsed_s,
    )


def _route_artifact(
    *,
    manifest: PluginManifest,
    request: RoutePlanRequest,
    status: RoutePlanStatus,
    waypoints: tuple[RouteWaypoint, ...],
    reservations: tuple[TemporalReservation, ...],
    route_length_m: float,
    duration_s: float,
    limitations: tuple[str, ...] = (),
    findings: tuple[str, ...] = (),
) -> RoutePlanArtifact:
    payload = {
        "request_id": request.request_id,
        "role_id": request.role_id,
        "planner": PluginSelection.from_manifest(
            manifest,
            capabilities_used=frozenset({request.capability.value}),
        ),
        "capability": request.capability,
        "status": status,
        "waypoints": waypoints,
        "reservations": reservations,
        "route_length_m": route_length_m,
        "expected_energy_percent": route_length_m * request.energy_percent_per_m,
        "expected_duration_s": duration_s,
        "expected_minimum_separation_m": request.minimum_separation_m,
        "completion_conditions": ("final waypoint reached", "role completion acknowledged"),
        "limitations": limitations,
        "findings": findings,
        "supersedes_route_sha256": request.supersedes_route_sha256,
    }
    return RoutePlanArtifact(**payload, route_sha256=canonical_sha256(payload))


def _blocked(
    manifest: PluginManifest,
    request: RoutePlanRequest,
    finding: str,
) -> RoutePlanArtifact:
    return _route_artifact(
        manifest=manifest,
        request=request,
        status=RoutePlanStatus.BLOCKED,
        waypoints=(),
        reservations=(),
        route_length_m=0.0,
        duration_s=0.0,
        findings=(finding,),
    )


def _reservation(
    request: RoutePlanRequest,
    waypoints: tuple[RouteWaypoint, ...],
    duration_s: float,
) -> TemporalReservation:
    margin = request.minimum_separation_m / 2.0
    return TemporalReservation(
        reservation_id=f"corridor-{request.request_id}",
        role_id=request.role_id,
        starts_at_s=0.0,
        ends_at_s=max(duration_s, 0.001),
        minimum_m=Vector3(
            x=min(item.position_m.x for item in waypoints) - margin,
            y=min(item.position_m.y for item in waypoints) - margin,
            z=min(item.position_m.z for item in waypoints) - margin,
        ),
        maximum_m=Vector3(
            x=max(item.position_m.x for item in waypoints) + margin,
            y=max(item.position_m.y for item in waypoints) + margin,
            z=max(item.position_m.z for item in waypoints) + margin,
        ),
    )


def _reservations_conflict(first: TemporalReservation, second: TemporalReservation) -> bool:
    temporal = first.starts_at_s < second.ends_at_s and second.starts_at_s < first.ends_at_s
    spatial = not (
        first.maximum_m.x < second.minimum_m.x
        or second.maximum_m.x < first.minimum_m.x
        or first.maximum_m.y < second.minimum_m.y
        or second.maximum_m.y < first.minimum_m.y
        or first.maximum_m.z < second.minimum_m.z
        or second.maximum_m.z < first.minimum_m.z
    )
    return temporal and spatial


def _inside_volume(point: Vector3, request: RoutePlanRequest) -> bool:
    return (
        request.flight_volume_minimum_m.x <= point.x <= request.flight_volume_maximum_m.x
        and request.flight_volume_minimum_m.y <= point.y <= request.flight_volume_maximum_m.y
        and request.flight_volume_minimum_m.z <= point.z <= request.flight_volume_maximum_m.z
    )


def _segment_intersects_box(
    start: Vector3,
    end: Vector3,
    obstacle: RouteObstacle,
) -> bool:
    lower = 0.0
    upper = 1.0
    for origin, target, low, high in (
        (start.x, end.x, obstacle.minimum_m.x, obstacle.maximum_m.x),
        (start.y, end.y, obstacle.minimum_m.y, obstacle.maximum_m.y),
        (start.z, end.z, obstacle.minimum_m.z, obstacle.maximum_m.z),
    ):
        delta = target - origin
        if abs(delta) <= 1e-12:
            if origin < low or origin > high:
                return False
            continue
        entry = (low - origin) / delta
        exit_ = (high - origin) / delta
        if entry > exit_:
            entry, exit_ = exit_, entry
        lower = max(lower, entry)
        upper = min(upper, exit_)
        if lower > upper:
            return False
    return True


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )
