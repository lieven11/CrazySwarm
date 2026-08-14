from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.geometry import structured_world_from_case
from crazyswarm_app.campaign.models import (
    CampaignCase,
    PlannerStrategy,
    Region3D,
    ReplanningAuthority,
    ScenarioEvent,
    ScenarioEventKind,
    ScenarioExpectedDisposition,
)
from crazyswarm_app.campaign.planner import BoundedJointPlanner
from crazyswarm_app.campaign.replanning import (
    ChangedWorldSafetyMonitor,
    DynamicEventKind,
    DynamicReplanDisposition,
    FleetRouteReplacement,
    InFlightEnvironmentEvent,
    InFlightReplanCoordinator,
    ReplanObservation,
    SafeFallback,
    commit_changed_world_replacement,
    plan_changed_world_replacement,
)
from crazyswarm_app.campaign.submissions import resolve_planning_submission
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.trajectory import sample_trajectory


@pytest.fixture(scope="module")
def dynamic_case():
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    source = catalog.get("2d.merge.canonical_nominal")
    return source.model_copy(
        update={"replanning_authority": ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS}
    )


def _region() -> Region3D:
    return Region3D(
        region_id="dynamic-obstacle",
        minimum_m=Vector3(x=-0.2, y=-0.2, z=0.0),
        maximum_m=Vector3(x=0.2, y=0.2, z=1.0),
    )


def test_accepted_environment_event_requires_planning_and_cutover_lead() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    source = catalog.get("2d.head_on_conflict.canonical_nominal")
    assert source.semantics is not None
    event = ScenarioEvent(
        event_id="too-late-object",
        kind=ScenarioEventKind.OBSTACLE_ADDED,
        trigger_time_s=5.0,
        replacement_goal=_region(),
        duration_s=source.hard_constraints.planning_budget_s,
        expected_disposition=ScenarioExpectedDisposition.ACCEPTED_UPDATE,
    )
    payload = source.model_dump(mode="python")
    payload.update(
        {
            "case_id": "2d.head_on_conflict.too_late_object",
            "parent_case_sha256": source.case_sha256,
            "replanning_authority": ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS,
            "semantics": source.semantics.model_copy(update={"scenario_events": (event,)}),
        }
    )

    with pytest.raises(ValueError, match="planning plus cutover lead"):
        CampaignCase.model_validate(payload)


def _event(
    *,
    event_id: str = "environment-update-1",
    sequence: int = 1,
    effective_source_s: float = 11.0,
    kind: DynamicEventKind = DynamicEventKind.OBSTACLE_ADDED,
) -> InFlightEnvironmentEvent:
    common = {
        "event_id": event_id,
        "kind": kind,
        "source_id": "world-observer",
        "sequence": sequence,
        "source_timestamp_s": 10.0,
        "received_source_s": 10.05,
        "effective_source_s": effective_source_s,
        "affected_role_ids": ("Alpha", "Beta"),
    }
    if kind is DynamicEventKind.PEER_TRAJECTORY_UPDATED:
        common["peer_trajectory_sha256"] = "9" * 64
    else:
        common.update({"region_id": "dynamic-obstacle", "region": _region()})
    return InFlightEnvironmentEvent(**common)


def _replacements(*, complete: bool = True) -> tuple[FleetRouteReplacement, ...]:
    return tuple(
        FleetRouteReplacement(
            role_id=role_id,
            old_trajectory_sha256=str(index) * 64,
            replacement_trajectory_sha256=str(index + 2) * 64,
            replacement_plan_sha256=str(index + 4) * 64,
            feasible=True,
            cancellation_acknowledged=True,
            replacement_acknowledged=complete or role_id == "Alpha",
        )
        for index, role_id in enumerate(("Alpha", "Beta"), start=1)
    )


def _replan(coordinator, event, replacements=None, **updates):
    arguments = {
        "decision_time_source_s": 10.30,
        "queue_latency_s": 0.05,
        "planning_latency_s": 0.20,
        "acknowledgement_latency_s": 0.05,
        "cutover_guard_s": 0.10,
        "old_epoch_safe_until_source_s": 11.20,
        "old_epoch_still_safe": True,
        "old_epoch": 1,
        "old_reservation_sha256": "a" * 64,
        "old_world_sha256": "b" * 64,
        "replacement_world_sha256": "c" * 64,
        "replacements": replacements or _replacements(),
        "feasibility_certificate_sha256s": ("d" * 64, "e" * 64),
    }
    arguments.update(updates)
    return coordinator.replan(event, **arguments)


@pytest.mark.parametrize(
    "kind",
    [DynamicEventKind.OBSTACLE_ADDED, DynamicEventKind.PEER_TRAJECTORY_UPDATED],
)
def test_dynamic_environment_and_peer_update_commit_one_atomic_epoch(
    dynamic_case,
    kind: DynamicEventKind,
) -> None:
    coordinator = InFlightReplanCoordinator(dynamic_case)

    decision = _replan(coordinator, _event(kind=kind))

    assert decision.disposition is DynamicReplanDisposition.ACCEPTED
    assert decision.reaction_horizon.passed
    assert decision.fleet_decision is not None
    assert decision.fleet_decision.committed_route_count == 2
    epoch = decision.fleet_decision.replacement_epoch
    assert epoch is not None
    assert epoch.epoch == 2
    assert epoch.shared_cutover_source_s == pytest.approx(10.45)
    assert epoch.affected_role_ids == ("Alpha", "Beta")


def test_reaction_horizon_failure_commits_nothing_and_uses_contingency(
    dynamic_case,
) -> None:
    coordinator = InFlightReplanCoordinator(dynamic_case)

    decision = _replan(
        coordinator,
        _event(effective_source_s=10.20),
        old_epoch_safe_until_source_s=10.20,
        old_epoch_still_safe=False,
    )

    assert decision.disposition is DynamicReplanDisposition.BLOCKED_REACTION_HORIZON
    assert not decision.reaction_horizon.passed
    assert decision.fleet_decision is None
    assert decision.fallback is SafeFallback.FLEET_ABORT_AND_LAND


def test_partial_acknowledgement_commits_zero_routes(dynamic_case) -> None:
    coordinator = InFlightReplanCoordinator(dynamic_case)

    decision = _replan(coordinator, _event(), replacements=_replacements(complete=False))

    assert decision.disposition is DynamicReplanDisposition.BLOCKED_ATOMIC_COMMIT
    assert decision.fleet_decision is not None
    assert decision.fleet_decision.committed_route_count == 0
    assert decision.fallback is SafeFallback.CONTINUE_OLD_SAFE_EPOCH


def test_dynamic_events_are_idempotent_and_source_ordered(dynamic_case) -> None:
    coordinator = InFlightReplanCoordinator(dynamic_case)
    newest = _event(event_id="environment-update-2", sequence=2)
    accepted = _replan(coordinator, newest)

    duplicate = _replan(coordinator, newest)
    stale = _replan(
        coordinator,
        _event(event_id="environment-update-stale", sequence=1),
    )

    assert accepted.disposition is DynamicReplanDisposition.ACCEPTED
    assert duplicate.disposition is DynamicReplanDisposition.DUPLICATE_IDEMPOTENT
    assert stale.disposition is DynamicReplanDisposition.REJECTED_STALE


def test_changed_world_object_in_line_produces_real_certified_atomic_replacement() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    source = catalog.get("2d.head_on_conflict.canonical_nominal")
    case = source.model_copy(
        update={
            "case_id": "2d.head_on_conflict.changed_world_replan_test",
            "parent_case_sha256": source.case_sha256,
            "baseline_sha256": source.case_sha256,
            "replanning_authority": ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS,
        }
    )
    submission = resolve_planning_submission(
        case,
        "constraint_directed.head_on.same_path",
    )
    initial_plan = BoundedJointPlanner().plan(case, planning_submission=submission)
    assert initial_plan.selected is not None
    initial = generate_smooth_trajectories(
        case,
        initial_plan.selected,
        planning_submission=submission,
    )
    old_trajectories = {item.role_id: item for item in initial.trajectories}
    observations = []
    for trajectory in initial.trajectories:
        sampled = sample_trajectory(trajectory, trajectory.duration_s / 3.0)
        observations.append(
            ReplanObservation.create(
                observation_id=f"line-object-{trajectory.role_id}",
                role_id=trajectory.role_id,
                source_timestamp_s=5.0,
                captured_at_source_s=5.0,
                position_m=sampled.position_m,
                velocity_m_s=sampled.velocity_m_s,
                acceleration_m_s2=sampled.acceleration_m_s2,
            )
        )
    obstacle = Region3D(
        region_id="line-object",
        minimum_m=Vector3(x=0.1, y=-0.2, z=0.1),
        maximum_m=Vector3(x=0.4, y=0.2, z=0.6),
    )
    event = InFlightEnvironmentEvent(
        event_id="line-object-detected",
        kind=DynamicEventKind.OBSTACLE_ADDED,
        source_id="world-observer",
        sequence=1,
        source_timestamp_s=5.0,
        received_source_s=5.05,
        effective_source_s=8.0,
        affected_role_ids=("Alpha", "Beta"),
        region_id=obstacle.region_id,
        region=obstacle,
    )

    proposal = plan_changed_world_replacement(
        case=case,
        planning_submission=submission,
        event=event,
        observations=observations,
        old_trajectories=old_trajectories,
    )

    assert proposal.plan.selected is not None
    assert proposal.plan.selected.strategy is PlannerStrategy.HORIZONTAL_DETOUR
    assert proposal.plan.selected.generator_id == "fleet-solid-lanes-v1"
    assert proposal.plan.feasibility_certificate is not None
    assert proposal.plan.feasibility_certificate.passed
    assert proposal.planning_latency_s <= case.hard_constraints.planning_budget_s
    assert not proposal.plan.bounded_search_complete
    assert "no optimality claim" in proposal.plan.optimality_claim
    assert proposal.proposal_sha256 == canonical_sha256(proposal.canonical_payload())
    assert {item.role_id for item in proposal.route_authorities} == {"Alpha", "Beta"}
    assert all(
        item.old_trajectory_sha256 != item.replacement_trajectory_sha256
        for item in proposal.route_authorities
    )

    safe_prefix = ChangedWorldSafetyMonitor(case).certify(
        event=event,
        observations=observations,
        active_trajectories=old_trajectories,
        perceived_world_sha256="b" * 64,
        old_world_sha256=structured_world_from_case(case).world_sha256,
        minimum_clearance_m=0.15,
    )

    decision = commit_changed_world_replacement(
        proposal,
        coordinator=InFlightReplanCoordinator(case),
        decision_time_source_s=5.30,
        queue_latency_s=0.0,
        acknowledgement_latency_s=0.02,
        cutover_guard_s=0.10,
        safe_prefix_certificate=safe_prefix,
        old_epoch=1,
        old_reservation_sha256="a" * 64,
        cancellation_acknowledged_role_ids=frozenset({"Alpha", "Beta"}),
        replacement_acknowledged_role_ids=frozenset({"Alpha", "Beta"}),
        fallback_acknowledged_role_ids=frozenset({"Alpha", "Beta"}),
    )
    assert decision.disposition is DynamicReplanDisposition.ACCEPTED
    assert decision.fleet_decision is not None
    assert decision.fleet_decision.committed_route_count == 2
