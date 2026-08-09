from __future__ import annotations

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.planning.builtins import (
    CoverageRoutePlanner,
    DirectRoutePlanner,
    TemporalRoutePlanner,
    ZoneRoutePlanner,
    default_recovery_registry,
    default_route_planner_registry,
)
from crazyswarm_app.planning.contracts import (
    PluginKind,
    RecoveryAction,
    RecoveryRequest,
    RecoveryTrigger,
    RouteCapability,
    RouteObstacle,
    RoutePlanRequest,
    RoutePlanStatus,
    RouteReplanRequest,
    RouteTarget,
    TemporalReservation,
)
from crazyswarm_app.planning.qualification import qualify_plugin_contract
from crazyswarm_app.planning.registry import PluginRegistry
from crazyswarm_app.planning.service import replan_route


def _route_request(
    *,
    capability: RouteCapability = RouteCapability.DIRECT,
    reservations: tuple[TemporalReservation, ...] = (),
) -> RoutePlanRequest:
    return RoutePlanRequest(
        request_id="canonical-route",
        role_id="survey",
        capability=capability,
        start_m=Vector3(),
        targets=(RouteTarget(position_m=Vector3(x=1.0, y=0.0, z=0.3)),),
        flight_volume_minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
        flight_volume_maximum_m=Vector3(x=2.0, y=2.0, z=1.0),
        existing_reservations=reservations,
        cruise_speed_m_s=0.4,
        maximum_duration_s=30.0,
    )


def test_registry_is_explicit_versioned_and_rejects_duplicates() -> None:
    registry = PluginRegistry(PluginKind.ROUTE_PLANNER, (DirectRoutePlanner(),))

    with pytest.raises(ValueError, match="duplicate plugin"):
        registry.register(DirectRoutePlanner())
    with pytest.raises(CrazySwarmError, match="not registered"):
        registry.resolve("route.direct", "2.0.0")
    with pytest.raises(CrazySwarmError, match="required capabilities"):
        registry.resolve(
            "route.direct",
            "1.0.0",
            required_capabilities=frozenset({RouteCapability.COVERAGE.value}),
        )


def test_route_plugin_contract_is_deterministic_and_bounded() -> None:
    planner = DirectRoutePlanner()

    result = qualify_plugin_contract(planner.manifest, _route_request(), planner.plan)

    assert result.passed is True
    assert result.invocation_count == 2


def test_temporal_planner_gives_existing_corridor_precedence() -> None:
    existing = TemporalReservation(
        reservation_id="existing",
        role_id="leader",
        starts_at_s=0.0,
        ends_at_s=4.0,
        minimum_m=Vector3(x=-0.2, y=-0.2, z=0.0),
        maximum_m=Vector3(x=1.2, y=0.2, z=0.6),
    )

    route = TemporalRoutePlanner().plan(
        _route_request(
            capability=RouteCapability.TEMPORAL_SEPARATION,
            reservations=(existing,),
        )
    )

    assert route.status is RoutePlanStatus.READY
    assert route.waypoints[0].arrival_s > existing.ends_at_s
    assert "temporal precedence" in route.limitations[0]


def test_zone_adapter_preserves_obstacle_aware_deterministic_detour() -> None:
    request = _route_request(capability=RouteCapability.ZONE).model_copy(
        update={
            "targets": (RouteTarget(position_m=Vector3(x=1.0, y=0.0, z=0.3)),),
            "obstacles": (
                RouteObstacle(
                    obstacle_id="center-box",
                    minimum_m=Vector3(x=0.3, y=-0.1, z=0.1),
                    maximum_m=Vector3(x=0.7, y=0.1, z=0.5),
                ),
            ),
        }
    )

    first = ZoneRoutePlanner().plan(request)
    second = ZoneRoutePlanner().plan(request)

    assert first.status is RoutePlanStatus.READY
    assert first.route_sha256 == second.route_sha256
    assert len(first.waypoints) > 3
    assert any(abs(item.position_m.y) > 0.1 for item in first.waypoints)


def test_coverage_planner_returns_bounded_lawnmower_route() -> None:
    request = _route_request(capability=RouteCapability.COVERAGE).model_copy(
        update={
            "targets": (RouteTarget(position_m=Vector3(x=0.5, y=0.5, z=0.3)),),
            "zone_minimum_m": Vector3(x=0.0, y=0.0, z=0.3),
            "zone_maximum_m": Vector3(x=1.0, y=1.0, z=0.3),
            "maximum_duration_s": 60.0,
        }
    )

    route = CoverageRoutePlanner().plan(request)

    assert route.status is RoutePlanStatus.READY
    assert len(route.waypoints) >= 8
    assert route.expected_duration_s <= request.maximum_duration_s


def test_replan_explicitly_stales_previous_route_authority() -> None:
    planner = DirectRoutePlanner()
    previous = planner.plan(_route_request())
    changed_observation_sha256 = canonical_sha256({"obstacle": "new"})
    request = RouteReplanRequest(
        previous_route_sha256=previous.route_sha256,
        changed_observation_sha256=changed_observation_sha256,
        replacement_request=_route_request().model_copy(
            update={
                "request_id": "replacement-route",
                "targets": (RouteTarget(position_m=Vector3(x=0.5, y=0.5, z=0.3)),),
                "supersedes_route_sha256": previous.route_sha256,
            }
        ),
        planning_budget_s=1.0,
    )

    result = replan_route(planner, request)

    assert result.stale_route_sha256 == previous.route_sha256
    assert result.replacement_route.route_sha256 != previous.route_sha256
    assert result.replacement_route.supersedes_route_sha256 == previous.route_sha256

    with pytest.raises(ValueError, match="does not supersede"):
        RouteReplanRequest(
            previous_route_sha256=previous.route_sha256,
            changed_observation_sha256=changed_observation_sha256,
            replacement_request=_route_request(),
            planning_budget_s=1.0,
        )


def test_all_declared_route_capabilities_are_allow_listed() -> None:
    capabilities = {
        capability
        for manifest in default_route_planner_registry().manifests()
        for capability in manifest.capabilities
    }

    assert capabilities == {item.value for item in RouteCapability}


def test_recovery_strategy_never_commands_and_returns_hash_bound_proposal() -> None:
    strategy = default_recovery_registry().resolve(
        "recovery.low-battery",
        "1.0.0",
        required_capabilities=frozenset({RecoveryTrigger.LOW_BATTERY.value}),
    )
    request = RecoveryRequest(
        request_id="recover-low-battery",
        mission_id="mission",
        trigger=RecoveryTrigger.LOW_BATTERY,
        role_id="survey",
        vehicle_id="drone-1",
        available_actions=frozenset({RecoveryAction.HANDOVER, RecoveryAction.LAND}),
        observation_current=True,
        authority_current=True,
        lease_generation=1,
        deadline_s=5.0,
    )

    proposal = strategy.propose(request)

    assert proposal.action is RecoveryAction.HANDOVER
    assert proposal.strategy.implementation_sha256 == strategy.manifest.implementation_sha256
    assert not hasattr(strategy, "vehicle")
