from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.geometry import structured_world_from_case
from crazyswarm_app.campaign.models import (
    CampaignCase,
    DroneCase,
    EnvironmentConstraints,
    PlannerStrategy,
    Region3D,
    ReplanningAuthority,
    RouteNodeIntent,
    RouteNodeMode,
)
from crazyswarm_app.campaign.planner import (
    BoundedJointPlanner,
    BoundedPlanningResult,
    PlanningStatus,
)
from crazyswarm_app.campaign.submissions import (
    ManeuverDimension,
    PlanningSubmission,
    planning_vehicle_model,
    planning_world_definition,
    registry_row_for_case,
    resolve_submission,
)
from crazyswarm_app.campaign.trajectory import (
    ContinuousCutoverTrajectory,
    SmoothTrajectorySet,
    audit_trajectory,
    generate_smooth_trajectories,
)
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory, TrajectoryPoint


class SafeFallback(StrEnum):
    CONTINUE_OLD_SAFE_EPOCH = "CONTINUE_OLD_SAFE_EPOCH"
    BOUNDED_HOLD = "BOUNDED_HOLD"
    ABORT_AND_LAND = "ABORT_AND_LAND"
    FLEET_ABORT_AND_LAND = "FLEET_ABORT_AND_LAND"


class GoalUpdateDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE_IDEMPOTENT = "DUPLICATE_IDEMPOTENT"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_RATE_LIMIT = "REJECTED_RATE_LIMIT"
    REJECTED_AUTHORITY = "REJECTED_AUTHORITY"
    BLOCKED = "BLOCKED"


class DynamicEventKind(StrEnum):
    OBSTACLE_ADDED = "OBSTACLE_ADDED"
    OBSTACLE_MOVED = "OBSTACLE_MOVED"
    OBSTACLE_REMOVED = "OBSTACLE_REMOVED"
    PASSAGE_CLOSED = "PASSAGE_CLOSED"
    PASSAGE_OPENED = "PASSAGE_OPENED"
    PEER_TRAJECTORY_UPDATED = "PEER_TRAJECTORY_UPDATED"
    POSITION_UNCERTAINTY_CHANGED = "POSITION_UNCERTAINTY_CHANGED"


class DynamicReplanDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE_IDEMPOTENT = "DUPLICATE_IDEMPOTENT"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_AUTHORITY = "REJECTED_AUTHORITY"
    BLOCKED_REACTION_HORIZON = "BLOCKED_REACTION_HORIZON"
    BLOCKED_ATOMIC_COMMIT = "BLOCKED_ATOMIC_COMMIT"


class InFlightEnvironmentEvent(ContractModel):
    event_id: Identifier
    kind: DynamicEventKind
    source_id: Identifier
    sequence: int = Field(ge=1)
    source_timestamp_s: float = Field(ge=0.0)
    received_source_s: float = Field(ge=0.0)
    effective_source_s: float = Field(ge=0.0)
    authenticated: bool = True
    affected_role_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=3)
    region_id: Identifier | None = None
    region: Region3D | None = None
    peer_trajectory_sha256: SHA256 | None = None
    position_uncertainty_m: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def payload_matches_kind(self) -> InFlightEnvironmentEvent:
        if self.received_source_s < self.source_timestamp_s:
            raise ValueError("dynamic event cannot be received before it was observed")
        if self.effective_source_s < self.source_timestamp_s:
            raise ValueError("dynamic event effective time predates its observation")
        region_kinds = {
            DynamicEventKind.OBSTACLE_ADDED,
            DynamicEventKind.OBSTACLE_MOVED,
            DynamicEventKind.PASSAGE_CLOSED,
            DynamicEventKind.PASSAGE_OPENED,
        }
        if self.kind in region_kinds and (self.region_id is None or self.region is None):
            raise ValueError("dynamic obstacle/passage event requires a named region")
        if self.kind is DynamicEventKind.OBSTACLE_REMOVED and self.region_id is None:
            raise ValueError("obstacle removal requires region_id")
        if (
            self.kind is DynamicEventKind.PEER_TRAJECTORY_UPDATED
            and self.peer_trajectory_sha256 is None
        ):
            raise ValueError("peer update requires a trajectory hash")
        if (
            self.kind is DynamicEventKind.POSITION_UNCERTAINTY_CHANGED
            and self.position_uncertainty_m is None
        ):
            raise ValueError("uncertainty event requires position_uncertainty_m")
        return self


class ReactionHorizonAudit(ContractModel):
    observation_latency_s: float = Field(ge=0.0)
    queue_latency_s: float = Field(ge=0.0)
    planning_latency_s: float = Field(ge=0.0)
    acknowledgement_latency_s: float = Field(ge=0.0)
    cutover_guard_s: float = Field(ge=0.0)
    total_reaction_s: float = Field(ge=0.0)
    available_event_lead_s: float
    available_old_epoch_horizon_s: float
    reaction_deadline_source_s: float = Field(ge=0.0)
    proposed_cutover_source_s: float = Field(ge=0.0)
    passed: bool


class GoalUpdate(ContractModel):
    source_id: Identifier
    sequence: int = Field(ge=1)
    update_id: Identifier
    source_timestamp_s: float = Field(ge=0.0)
    requested_effective_time_s: float = Field(ge=0.0)
    goal_revision: int = Field(ge=1)
    goal_region: Region3D


class BoundedGoalUpdateQueue:
    """Retain only the newest pending revision for each bounded authority source."""

    def __init__(self, *, maximum_sources: int = 16) -> None:
        if not 1 <= maximum_sources <= 256:
            raise ValueError("goal update source limit must be in 1..256")
        self.maximum_sources = maximum_sources
        self._pending: dict[str, GoalUpdate] = {}
        self._seen_update_ids: set[str] = set()

    def submit(self, update: GoalUpdate) -> GoalUpdateDisposition:
        if update.update_id in self._seen_update_ids:
            return GoalUpdateDisposition.DUPLICATE_IDEMPOTENT
        existing = self._pending.get(update.source_id)
        if existing is not None and (
            update.sequence <= existing.sequence or update.goal_revision <= existing.goal_revision
        ):
            return GoalUpdateDisposition.REJECTED_STALE
        if existing is None and len(self._pending) >= self.maximum_sources:
            return GoalUpdateDisposition.BLOCKED
        self._pending[update.source_id] = update
        self._seen_update_ids.add(update.update_id)
        return GoalUpdateDisposition.ACCEPTED

    def pending(self) -> tuple[GoalUpdate, ...]:
        return tuple(
            sorted(
                self._pending.values(),
                key=lambda item: (
                    item.source_timestamp_s,
                    item.source_id,
                    item.sequence,
                    item.update_id,
                ),
            )
        )

    def pop(self, source_id: str) -> GoalUpdate | None:
        return self._pending.pop(source_id, None)


class ReplanObservation(ContractModel):
    observation_id: Identifier
    role_id: Identifier
    source_timestamp_s: float = Field(ge=0.0)
    captured_at_source_s: float = Field(ge=0.0)
    position_m: Vector3
    velocity_m_s: Vector3
    acceleration_m_s2: Vector3 = Vector3()
    observation_sha256: SHA256

    @classmethod
    def create(
        cls,
        *,
        observation_id: str,
        role_id: str,
        source_timestamp_s: float,
        captured_at_source_s: float,
        position_m: Vector3,
        velocity_m_s: Vector3,
        acceleration_m_s2: Vector3 | None = None,
    ) -> ReplanObservation:
        payload = {
            "observation_id": observation_id,
            "role_id": role_id,
            "source_timestamp_s": source_timestamp_s,
            "captured_at_source_s": captured_at_source_s,
            "position_m": position_m,
            "velocity_m_s": velocity_m_s,
            "acceleration_m_s2": acceleration_m_s2 or Vector3(),
        }
        return cls(**payload, observation_sha256=canonical_sha256(payload))


class CutoverAcknowledgements(ContractModel):
    old_future_cancelled: bool
    old_future_cancellation_acknowledged: bool
    replacement_command_acknowledged: bool
    replacement_authority_acknowledged: bool

    @property
    def complete(self) -> bool:
        return all(self.model_dump(mode="python").values())


class SingleReplanDecision(ContractModel):
    schema_version: Literal[1] = 1
    update_id: Identifier
    disposition: GoalUpdateDisposition
    reason: str
    old_plan_sha256: SHA256
    old_trajectory_sha256: SHA256
    old_reservation_sha256: SHA256
    observation_sha256: SHA256
    goal_update_sha256: SHA256
    replacement_plan_sha256: SHA256 | None = None
    replacement_trajectory: ContinuousCutoverTrajectory | None = None
    replacement_reservation_sha256: SHA256 | None = None
    source_clock_cutover_s: float | None = Field(default=None, ge=0.0)
    authority_policy: ReplanningAuthority
    authority_sha256: SHA256
    acknowledgements: CutoverAcknowledgements | None = None
    fallback: SafeFallback | None = None
    decision_sha256: SHA256

    @model_validator(mode="after")
    def accepted_is_atomic(self) -> SingleReplanDecision:
        if self.disposition is GoalUpdateDisposition.ACCEPTED and (
            self.replacement_trajectory is None
            or self.replacement_plan_sha256 is None
            or self.replacement_reservation_sha256 is None
            or self.source_clock_cutover_s is None
            or self.acknowledgements is None
            or not self.acknowledgements.complete
        ):
            raise ValueError("accepted replacement lacks atomic cutover authority")
        return self


class SingleDroneReplanner:
    def __init__(self, case: CampaignCase, *, role_id: str) -> None:
        if case.drone_count != 1:
            raise ValueError("single-drone replanner requires an exact one-drone case")
        if case.drones[0].role_id != role_id:
            raise ValueError("replanning role does not match the case")
        self.case = case
        self.role_id = role_id
        self._accepted_update_ids: dict[str, SingleReplanDecision] = {}
        self._latest_sequence: dict[str, int] = {}
        self._latest_revision: dict[str, int] = {}
        self._latest_accepted_timestamp: dict[str, float] = {}

    def replan(
        self,
        update: GoalUpdate,
        observation: ReplanObservation,
        *,
        decision_time_source_s: float,
        old_plan_sha256: str,
        old_trajectory_sha256: str,
        old_reservation_sha256: str,
        acknowledgements: CutoverAcknowledgements,
        planning_elapsed_s: float = 0.0,
        old_future_safe_until_s: float | None = None,
        operator_approved: bool = False,
    ) -> SingleReplanDecision:
        duplicate = self._accepted_update_ids.get(update.update_id)
        if duplicate is not None:
            duplicate_payload = duplicate.model_dump(mode="python", exclude={"decision_sha256"})
            duplicate_payload.update(
                {
                    "disposition": GoalUpdateDisposition.DUPLICATE_IDEMPOTENT,
                    "reason": "duplicate update ID returned the existing replacement authority",
                }
            )
            return SingleReplanDecision(
                **duplicate_payload,
                decision_sha256=canonical_sha256(duplicate_payload),
            )
        common = {
            "update_id": update.update_id,
            "old_plan_sha256": old_plan_sha256,
            "old_trajectory_sha256": old_trajectory_sha256,
            "old_reservation_sha256": old_reservation_sha256,
            "observation_sha256": observation.observation_sha256,
            "goal_update_sha256": canonical_sha256(update),
            "authority_policy": self.case.replanning_authority,
        }
        if update.sequence <= self._latest_sequence.get(
            update.source_id, 0
        ) or update.goal_revision <= self._latest_revision.get(update.source_id, 0):
            return _single_rejection(
                common,
                GoalUpdateDisposition.REJECTED_STALE,
                "stale sequence or goal revision",
                SafeFallback.CONTINUE_OLD_SAFE_EPOCH,
            )
        latest = self._latest_accepted_timestamp.get(update.source_id)
        if (
            latest is not None
            and update.source_timestamp_s - latest
            < self.case.hard_constraints.minimum_goal_update_interval_s
        ):
            return _single_rejection(
                common,
                GoalUpdateDisposition.REJECTED_RATE_LIMIT,
                "goal source exceeded the admitted update rate",
                SafeFallback.CONTINUE_OLD_SAFE_EPOCH,
            )
        if self.case.replanning_authority is ReplanningAuthority.ABORT_ONLY:
            return _single_rejection(
                common,
                GoalUpdateDisposition.REJECTED_AUTHORITY,
                "case grants abort-only replanning authority",
                SafeFallback.ABORT_AND_LAND,
            )
        if (
            self.case.replanning_authority is ReplanningAuthority.OPERATOR_APPROVAL_REQUIRED
            and not operator_approved
        ):
            return _single_rejection(
                common,
                GoalUpdateDisposition.REJECTED_AUTHORITY,
                "operator approval is required",
                SafeFallback.CONTINUE_OLD_SAFE_EPOCH,
            )
        observation_age = decision_time_source_s - observation.source_timestamp_s
        if (
            observation_age < 0.0
            or observation_age > self.case.hard_constraints.observation_freshness_limit_s
        ):
            return _single_rejection(
                common,
                GoalUpdateDisposition.BLOCKED,
                "triggering observation is stale",
                SafeFallback.ABORT_AND_LAND,
            )
        if planning_elapsed_s > self.case.hard_constraints.planning_budget_s:
            return _single_rejection(
                common,
                GoalUpdateDisposition.BLOCKED,
                "planning budget expired",
                SafeFallback.BOUNDED_HOLD,
            )
        cutover = max(decision_time_source_s + 0.10, update.requested_effective_time_s)
        if old_future_safe_until_s is not None and cutover > old_future_safe_until_s:
            return _single_rejection(
                common,
                GoalUpdateDisposition.BLOCKED,
                "no safe old-trajectory cutover window remains",
                SafeFallback.ABORT_AND_LAND,
            )
        if not acknowledgements.complete:
            return _single_rejection(
                common,
                GoalUpdateDisposition.BLOCKED,
                "cutover cancellation or replacement acknowledgement is incomplete",
                SafeFallback.CONTINUE_OLD_SAFE_EPOCH,
            )
        trajectory = _replacement_trajectory(self.case, observation, update)
        audit = audit_trajectory(self.case, trajectory)
        if not audit.passed:
            return _single_rejection(
                common,
                GoalUpdateDisposition.BLOCKED,
                "replacement trajectory violates dynamics",
                SafeFallback.ABORT_AND_LAND,
            )
        replacement_plan_sha = canonical_sha256(
            [old_plan_sha256, update, observation, trajectory.sha256]
        )
        reservation_sha = canonical_sha256([self.role_id, trajectory.sha256, cutover])
        authority_sha = canonical_sha256(
            [self.case.case_sha256, replacement_plan_sha, reservation_sha, cutover]
        )
        payload: dict[str, Any] = {
            **common,
            "disposition": GoalUpdateDisposition.ACCEPTED,
            "reason": "bounded replacement validated and acknowledged for one source-clock cutover",
            "replacement_plan_sha256": replacement_plan_sha,
            "replacement_trajectory": trajectory,
            "replacement_reservation_sha256": reservation_sha,
            "source_clock_cutover_s": cutover,
            "authority_sha256": authority_sha,
            "acknowledgements": acknowledgements,
        }
        decision = SingleReplanDecision(**payload, decision_sha256=canonical_sha256(payload))
        self._accepted_update_ids[update.update_id] = decision
        self._latest_sequence[update.source_id] = update.sequence
        self._latest_revision[update.source_id] = update.goal_revision
        self._latest_accepted_timestamp[update.source_id] = update.source_timestamp_s
        return decision


class FleetRouteReplacement(ContractModel):
    role_id: Identifier
    old_trajectory_sha256: SHA256
    replacement_trajectory_sha256: SHA256
    replacement_plan_sha256: SHA256
    feasible: bool
    cancellation_acknowledged: bool
    replacement_acknowledged: bool


class FleetReservationEpoch(ContractModel):
    epoch: int = Field(ge=1)
    affected_role_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=3)
    old_reservation_sha256: SHA256
    replacement_reservation_sha256: SHA256
    shared_cutover_source_s: float = Field(ge=0.0)
    validation_passed: bool
    replacements: tuple[FleetRouteReplacement, ...]
    commit_sha256: SHA256


class FleetReplanDecision(ContractModel):
    disposition: GoalUpdateDisposition
    ordered_update_ids: tuple[Identifier, ...]
    old_epoch: int = Field(ge=1)
    replacement_epoch: FleetReservationEpoch | None = None
    committed_route_count: int = Field(ge=0, le=3)
    fallback: SafeFallback | None = None
    reason: str
    authority_sha256: SHA256
    decision_sha256: SHA256

    @model_validator(mode="after")
    def no_partial_commit(self) -> FleetReplanDecision:
        if self.disposition is GoalUpdateDisposition.ACCEPTED:
            if self.replacement_epoch is None or self.committed_route_count != len(
                self.replacement_epoch.replacements
            ):
                raise ValueError("fleet replacement must commit the entire epoch")
        elif self.committed_route_count != 0:
            raise ValueError("failed atomic replanning committed a route subset")
        return self


class DynamicFleetReplanDecision(ContractModel):
    schema_version: Literal[1] = 1
    event_id: Identifier
    event_sha256: SHA256
    disposition: DynamicReplanDisposition
    old_world_sha256: SHA256
    replacement_world_sha256: SHA256
    old_epoch: int = Field(ge=1)
    reaction_horizon: ReactionHorizonAudit
    feasibility_certificate_sha256s: tuple[SHA256, ...]
    fleet_decision: FleetReplanDecision | None = None
    fallback: SafeFallback | None = None
    reason: str
    authority_sha256: SHA256
    decision_sha256: SHA256

    @model_validator(mode="after")
    def accepted_commits_one_epoch(self) -> DynamicFleetReplanDecision:
        if self.disposition is DynamicReplanDisposition.ACCEPTED:
            if (
                self.fleet_decision is None
                or self.fleet_decision.disposition is not GoalUpdateDisposition.ACCEPTED
                or not self.reaction_horizon.passed
            ):
                raise ValueError("accepted dynamic replanning lacks a safe atomic fleet commit")
        elif self.fleet_decision is not None and self.fleet_decision.committed_route_count:
            raise ValueError("blocked dynamic replanning committed replacement routes")
        return self


class ChangedWorldRouteAuthority(ContractModel):
    """One real replacement trajectory and its independently derived authority."""

    role_id: Identifier
    old_trajectory_sha256: SHA256
    replacement_trajectory_sha256: SHA256
    replacement_plan_sha256: SHA256
    feasibility_certificate_sha256: SHA256
    authority_sha256: SHA256


class ChangedWorldReplanProposal(ContractModel):
    """Planner-produced replacement; acknowledgements are intentionally not guessed."""

    schema_version: Literal[1] = 1
    event: InFlightEnvironmentEvent
    original_case_sha256: SHA256
    replacement_case: CampaignCase
    old_world_sha256: SHA256
    replacement_world_sha256: SHA256
    planning_submission: PlanningSubmission
    plan: BoundedPlanningResult
    trajectories: SmoothTrajectorySet
    route_authorities: tuple[ChangedWorldRouteAuthority, ...]
    planning_latency_s: float = Field(ge=0.0)
    proposal_sha256: SHA256

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(
            mode="python",
            exclude={"planning_latency_s", "proposal_sha256"},
        )
        payload["plan"] = self.plan.model_dump(
            mode="python",
            exclude={"diagnostic_search_duration_s"},
        )
        return payload

    @model_validator(mode="after")
    def executable_authority_is_complete(self) -> ChangedWorldReplanProposal:
        if self.plan.status is not PlanningStatus.READY or self.plan.selected is None:
            raise ValueError("changed-world proposal requires a ready selected plan")
        certificate = self.plan.feasibility_certificate
        if certificate is None or not certificate.passed:
            raise ValueError("changed-world proposal lacks an independent certificate")
        roles = tuple(item.role_id for item in self.route_authorities)
        if len(set(roles)) != len(roles) or set(roles) != set(self.event.affected_role_ids):
            raise ValueError("changed-world route authority does not cover affected roles exactly")
        trajectory_by_role = {item.role_id: item for item in self.trajectories.trajectories}
        if set(trajectory_by_role) != set(roles):
            raise ValueError("changed-world trajectory set differs from route authority")
        if any(
            item.replacement_trajectory_sha256 != trajectory_by_role[item.role_id].sha256
            or item.replacement_plan_sha256 != self.plan.plan_sha256
            for item in self.route_authorities
        ):
            raise ValueError("changed-world authority hashes differ from planned trajectories")
        if self.proposal_sha256 != canonical_sha256(self.canonical_payload()):
            raise ValueError("changed-world proposal hash mismatch")
        return self


def plan_changed_world_replacement(
    *,
    case: CampaignCase,
    planning_submission: PlanningSubmission,
    event: InFlightEnvironmentEvent,
    observations: Sequence[ReplanObservation],
    old_trajectories: Mapping[str, TimeParameterizedTrajectory],
) -> ChangedWorldReplanProposal:
    """Apply one authenticated event and plan actual replacement trajectories.

    This is the missing bridge between the WP-48 transaction model and the planner:
    callers no longer get to assert ``feasible=True`` while supplying arbitrary hashes.
    The changed world, current fleet observations, selected candidate, exact generated
    trajectories, and certificate are all retained in one hash-bound proposal.
    """

    if not event.authenticated:
        raise ValueError("unauthenticated dynamic events cannot enter replanning")
    if case.replanning_authority is ReplanningAuthority.ABORT_ONLY:
        raise ValueError("case grants abort-only authority")
    observation_by_role = {item.role_id: item for item in observations}
    if len(observation_by_role) != len(observations):
        raise ValueError("replan observations contain duplicate roles")
    affected = set(event.affected_role_ids)
    if affected != set(observation_by_role) or affected != set(old_trajectories):
        raise ValueError("event, observations, and old trajectories must cover identical roles")
    case_roles = {item.role_id for item in case.drones}
    if not affected.issubset(case_roles):
        raise ValueError("dynamic event names a role outside the immutable case")
    if case.drone_count > 1 and affected != case_roles:
        raise ValueError("multi-drone changed-world planning requires the complete active fleet")

    started = time.perf_counter()
    replacement_case = _changed_world_case(
        case,
        event,
        observation_by_role,
        old_trajectories,
    )
    rebound = _in_flight_planning_submission(replacement_case, planning_submission)
    plan = BoundedJointPlanner().plan(
        replacement_case,
        planning_submission=rebound,
        first_certified_within_budget=True,
    )
    if plan.status is not PlanningStatus.READY or plan.selected is None:
        raise ValueError(plan.blocking_reason or "changed world has no admitted replacement")
    if plan.feasibility_certificate is None or not plan.feasibility_certificate.passed:
        raise ValueError("changed-world plan lacks independent feasibility authority")
    trajectories = generate_smooth_trajectories(
        replacement_case,
        plan.selected,
        planning_submission=rebound,
    )
    replacement_by_role = {item.role_id: item for item in trajectories.trajectories}
    if set(replacement_by_role) != affected:
        raise ValueError("changed-world planner returned an incomplete affected fleet")
    for role_id, trajectory in replacement_by_role.items():
        observation = observation_by_role[role_id]
        if _distance(trajectory.points[0].position_m, observation.position_m) > 0.15:
            raise ValueError(f"replacement trajectory for {role_id} is discontinuous at cutover")
    certificate_sha = plan.feasibility_certificate.certificate_sha256
    authorities = tuple(
        ChangedWorldRouteAuthority(
            role_id=role_id,
            old_trajectory_sha256=old_trajectories[role_id].sha256,
            replacement_trajectory_sha256=replacement_by_role[role_id].sha256,
            replacement_plan_sha256=plan.plan_sha256,
            feasibility_certificate_sha256=canonical_sha256(
                [certificate_sha, role_id, replacement_by_role[role_id].sha256]
            ),
            authority_sha256=canonical_sha256(
                [
                    case.case_sha256,
                    event,
                    rebound.planning_submission_sha256,
                    plan.plan_sha256,
                    role_id,
                    replacement_by_role[role_id].sha256,
                    certificate_sha,
                ]
            ),
        )
        for role_id in sorted(affected)
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "event": event,
        "original_case_sha256": case.case_sha256,
        "replacement_case": replacement_case,
        "old_world_sha256": structured_world_from_case(case).world_sha256,
        "replacement_world_sha256": structured_world_from_case(replacement_case).world_sha256,
        "planning_submission": rebound,
        "plan": plan,
        "trajectories": trajectories,
        "route_authorities": authorities,
    }
    # Hash the same plain outer snapshot produced by the proposal model.  Passing
    # nested models directly to canonical_sha256 would invoke each model's own
    # canonical_payload and unintentionally omit nested identity hashes.
    stable_payload = {
        "schema_version": 1,
        "event": event.model_dump(mode="python"),
        "original_case_sha256": case.case_sha256,
        "replacement_case": replacement_case.model_dump(mode="python"),
        "old_world_sha256": payload["old_world_sha256"],
        "replacement_world_sha256": payload["replacement_world_sha256"],
        "planning_submission": rebound.model_dump(mode="python"),
        "plan": plan.model_dump(
            mode="python",
            exclude={"diagnostic_search_duration_s"},
        ),
        "trajectories": trajectories.model_dump(mode="python"),
        "route_authorities": tuple(item.model_dump(mode="python") for item in authorities),
    }
    planning_latency_s = time.perf_counter() - started
    if planning_latency_s > case.hard_constraints.planning_budget_s:
        raise ValueError("changed-world proposal exceeded the frozen planning budget")
    return ChangedWorldReplanProposal(
        **payload,
        planning_latency_s=planning_latency_s,
        proposal_sha256=canonical_sha256(stable_payload),
    )


def commit_changed_world_replacement(
    proposal: ChangedWorldReplanProposal,
    *,
    coordinator: InFlightReplanCoordinator,
    decision_time_source_s: float,
    queue_latency_s: float,
    acknowledgement_latency_s: float,
    cutover_guard_s: float,
    old_epoch_safe_until_source_s: float,
    old_epoch_still_safe: bool,
    old_epoch: int,
    old_reservation_sha256: str,
    cancellation_acknowledged_role_ids: frozenset[str],
    replacement_acknowledged_role_ids: frozenset[str],
) -> DynamicFleetReplanDecision:
    """Commit a planned proposal using acknowledgements observed by the execution head."""

    replacements = tuple(
        FleetRouteReplacement(
            role_id=item.role_id,
            old_trajectory_sha256=item.old_trajectory_sha256,
            replacement_trajectory_sha256=item.replacement_trajectory_sha256,
            replacement_plan_sha256=item.replacement_plan_sha256,
            feasible=True,
            cancellation_acknowledged=(item.role_id in cancellation_acknowledged_role_ids),
            replacement_acknowledged=(item.role_id in replacement_acknowledged_role_ids),
        )
        for item in proposal.route_authorities
    )
    return coordinator.replan(
        proposal.event,
        decision_time_source_s=decision_time_source_s,
        queue_latency_s=queue_latency_s,
        planning_latency_s=proposal.planning_latency_s,
        acknowledgement_latency_s=acknowledgement_latency_s,
        cutover_guard_s=cutover_guard_s,
        old_epoch_safe_until_source_s=old_epoch_safe_until_source_s,
        old_epoch_still_safe=old_epoch_still_safe,
        old_epoch=old_epoch,
        old_reservation_sha256=old_reservation_sha256,
        old_world_sha256=proposal.old_world_sha256,
        replacement_world_sha256=proposal.replacement_world_sha256,
        replacements=replacements,
        feasibility_certificate_sha256s=tuple(
            item.feasibility_certificate_sha256 for item in proposal.route_authorities
        ),
    )


def atomic_fleet_replan(
    *,
    case: CampaignCase,
    old_epoch: int,
    old_reservation_sha256: str,
    updates: tuple[GoalUpdate, ...],
    replacements: tuple[FleetRouteReplacement, ...],
    shared_cutover_source_s: float,
    old_epoch_still_safe: bool,
) -> FleetReplanDecision:
    if not 2 <= case.drone_count <= 3:
        raise ValueError("atomic fleet replanning supports exactly two or three drones")
    ordered_updates = tuple(
        sorted(
            updates,
            key=lambda item: (
                item.source_timestamp_s,
                item.source_id,
                item.sequence,
                item.update_id,
            ),
        )
    )
    return _atomic_fleet_commit(
        case=case,
        old_epoch=old_epoch,
        old_reservation_sha256=old_reservation_sha256,
        ordered_update_ids=tuple(item.update_id for item in ordered_updates),
        replacements=replacements,
        shared_cutover_source_s=shared_cutover_source_s,
        old_epoch_still_safe=old_epoch_still_safe,
    )


def _atomic_fleet_commit(
    *,
    case: CampaignCase,
    old_epoch: int,
    old_reservation_sha256: str,
    ordered_update_ids: tuple[str, ...],
    replacements: tuple[FleetRouteReplacement, ...],
    shared_cutover_source_s: float,
    old_epoch_still_safe: bool,
) -> FleetReplanDecision:
    ordered_replacements = tuple(sorted(replacements, key=lambda item: item.role_id))
    role_ids = tuple(item.role_id for item in ordered_replacements)
    if not role_ids or len(set(role_ids)) != len(role_ids) or len(role_ids) > case.drone_count:
        raise ValueError("affected fleet replacement roles are invalid")
    complete = all(
        item.feasible and item.cancellation_acknowledged and item.replacement_acknowledged
        for item in ordered_replacements
    )
    update_ids = ordered_update_ids
    if not complete:
        fallback = (
            SafeFallback.CONTINUE_OLD_SAFE_EPOCH
            if old_epoch_still_safe
            else SafeFallback.FLEET_ABORT_AND_LAND
        )
        authority_sha = canonical_sha256([case.case_sha256, old_epoch, "NO_COMMIT", fallback])
        payload = {
            "disposition": GoalUpdateDisposition.BLOCKED,
            "ordered_update_ids": update_ids,
            "old_epoch": old_epoch,
            "committed_route_count": 0,
            "fallback": fallback,
            "reason": (
                "partial feasibility, cancellation, or acknowledgement failure "
                "committed zero routes"
            ),
            "authority_sha256": authority_sha,
        }
        return FleetReplanDecision(**payload, decision_sha256=canonical_sha256(payload))
    reservation_sha = canonical_sha256(
        [
            old_epoch + 1,
            role_ids,
            tuple(item.replacement_trajectory_sha256 for item in ordered_replacements),
            shared_cutover_source_s,
        ]
    )
    epoch_payload = {
        "epoch": old_epoch + 1,
        "affected_role_ids": role_ids,
        "old_reservation_sha256": old_reservation_sha256,
        "replacement_reservation_sha256": reservation_sha,
        "shared_cutover_source_s": shared_cutover_source_s,
        "validation_passed": True,
        "replacements": ordered_replacements,
    }
    epoch = FleetReservationEpoch(**epoch_payload, commit_sha256=canonical_sha256(epoch_payload))
    authority_sha = canonical_sha256([case.case_sha256, epoch.commit_sha256, update_ids])
    payload = {
        "disposition": GoalUpdateDisposition.ACCEPTED,
        "ordered_update_ids": update_ids,
        "old_epoch": old_epoch,
        "replacement_epoch": epoch,
        "committed_route_count": len(ordered_replacements),
        "reason": "all affected routes and one replacement reservation epoch committed atomically",
        "authority_sha256": authority_sha,
    }
    return FleetReplanDecision(**payload, decision_sha256=canonical_sha256(payload))


class InFlightReplanCoordinator:
    """Sequence dynamic world/peer events and commit one fleet reservation epoch."""

    def __init__(self, case: CampaignCase) -> None:
        if not 2 <= case.drone_count <= 3:
            raise ValueError("dynamic fleet replanning requires two or three drones")
        self.case = case
        self._latest_sequence_by_source: dict[str, int] = {}
        self._decision_by_event_id: dict[str, DynamicFleetReplanDecision] = {}

    def replan(
        self,
        event: InFlightEnvironmentEvent,
        *,
        decision_time_source_s: float,
        queue_latency_s: float,
        planning_latency_s: float,
        acknowledgement_latency_s: float,
        cutover_guard_s: float,
        old_epoch_safe_until_source_s: float,
        old_epoch_still_safe: bool,
        old_epoch: int,
        old_reservation_sha256: str,
        old_world_sha256: str,
        replacement_world_sha256: str,
        replacements: tuple[FleetRouteReplacement, ...],
        feasibility_certificate_sha256s: tuple[str, ...],
        operator_approved: bool = False,
    ) -> DynamicFleetReplanDecision:
        existing = self._decision_by_event_id.get(event.event_id)
        if existing is not None:
            return _dynamic_rejection(
                event=event,
                disposition=DynamicReplanDisposition.DUPLICATE_IDEMPOTENT,
                reason="duplicate event ID returned without creating another epoch",
                old_world_sha256=old_world_sha256,
                replacement_world_sha256=replacement_world_sha256,
                old_epoch=old_epoch,
                reaction_horizon=existing.reaction_horizon,
                certificate_sha256s=feasibility_certificate_sha256s,
                fallback=existing.fallback or SafeFallback.CONTINUE_OLD_SAFE_EPOCH,
            )
        if event.sequence <= self._latest_sequence_by_source.get(event.source_id, 0):
            decision = _dynamic_rejection(
                event=event,
                disposition=DynamicReplanDisposition.REJECTED_STALE,
                reason="dynamic event source sequence is stale",
                old_world_sha256=old_world_sha256,
                replacement_world_sha256=replacement_world_sha256,
                old_epoch=old_epoch,
                reaction_horizon=_reaction_horizon(
                    event,
                    decision_time_source_s=decision_time_source_s,
                    queue_latency_s=queue_latency_s,
                    planning_latency_s=planning_latency_s,
                    acknowledgement_latency_s=acknowledgement_latency_s,
                    cutover_guard_s=cutover_guard_s,
                    old_epoch_safe_until_source_s=old_epoch_safe_until_source_s,
                    planning_budget_s=self.case.hard_constraints.planning_budget_s,
                    freshness_limit_s=self.case.hard_constraints.observation_freshness_limit_s,
                ),
                certificate_sha256s=feasibility_certificate_sha256s,
                fallback=(
                    SafeFallback.CONTINUE_OLD_SAFE_EPOCH
                    if old_epoch_still_safe
                    else SafeFallback.FLEET_ABORT_AND_LAND
                ),
            )
            self._decision_by_event_id[event.event_id] = decision
            return decision
        reaction = _reaction_horizon(
            event,
            decision_time_source_s=decision_time_source_s,
            queue_latency_s=queue_latency_s,
            planning_latency_s=planning_latency_s,
            acknowledgement_latency_s=acknowledgement_latency_s,
            cutover_guard_s=cutover_guard_s,
            old_epoch_safe_until_source_s=old_epoch_safe_until_source_s,
            planning_budget_s=self.case.hard_constraints.planning_budget_s,
            freshness_limit_s=self.case.hard_constraints.observation_freshness_limit_s,
        )
        self._latest_sequence_by_source[event.source_id] = event.sequence
        if not event.authenticated:
            decision = _dynamic_rejection(
                event=event,
                disposition=DynamicReplanDisposition.REJECTED_AUTHORITY,
                reason="dynamic event is not authenticated",
                old_world_sha256=old_world_sha256,
                replacement_world_sha256=replacement_world_sha256,
                old_epoch=old_epoch,
                reaction_horizon=reaction,
                certificate_sha256s=feasibility_certificate_sha256s,
                fallback=SafeFallback.CONTINUE_OLD_SAFE_EPOCH,
            )
        elif self.case.replanning_authority is ReplanningAuthority.ABORT_ONLY or (
            self.case.replanning_authority is ReplanningAuthority.OPERATOR_APPROVAL_REQUIRED
            and not operator_approved
        ):
            decision = _dynamic_rejection(
                event=event,
                disposition=DynamicReplanDisposition.REJECTED_AUTHORITY,
                reason="case/operator authority does not admit autonomous dynamic replanning",
                old_world_sha256=old_world_sha256,
                replacement_world_sha256=replacement_world_sha256,
                old_epoch=old_epoch,
                reaction_horizon=reaction,
                certificate_sha256s=feasibility_certificate_sha256s,
                fallback=(
                    SafeFallback.CONTINUE_OLD_SAFE_EPOCH
                    if old_epoch_still_safe
                    else SafeFallback.FLEET_ABORT_AND_LAND
                ),
            )
        elif not reaction.passed:
            decision = _dynamic_rejection(
                event=event,
                disposition=DynamicReplanDisposition.BLOCKED_REACTION_HORIZON,
                reason="replacement cannot be acknowledged before the event/safety horizon",
                old_world_sha256=old_world_sha256,
                replacement_world_sha256=replacement_world_sha256,
                old_epoch=old_epoch,
                reaction_horizon=reaction,
                certificate_sha256s=feasibility_certificate_sha256s,
                fallback=(
                    SafeFallback.CONTINUE_OLD_SAFE_EPOCH
                    if old_epoch_still_safe
                    else SafeFallback.FLEET_ABORT_AND_LAND
                ),
            )
        elif len(feasibility_certificate_sha256s) != len(replacements) or set(
            event.affected_role_ids
        ) != {item.role_id for item in replacements}:
            decision = _dynamic_rejection(
                event=event,
                disposition=DynamicReplanDisposition.BLOCKED_ATOMIC_COMMIT,
                reason="affected routes lack one independently certified replacement each",
                old_world_sha256=old_world_sha256,
                replacement_world_sha256=replacement_world_sha256,
                old_epoch=old_epoch,
                reaction_horizon=reaction,
                certificate_sha256s=feasibility_certificate_sha256s,
                fallback=(
                    SafeFallback.CONTINUE_OLD_SAFE_EPOCH
                    if old_epoch_still_safe
                    else SafeFallback.FLEET_ABORT_AND_LAND
                ),
            )
        else:
            fleet = _atomic_fleet_commit(
                case=self.case,
                old_epoch=old_epoch,
                old_reservation_sha256=old_reservation_sha256,
                ordered_update_ids=(event.event_id,),
                replacements=replacements,
                shared_cutover_source_s=reaction.proposed_cutover_source_s,
                old_epoch_still_safe=old_epoch_still_safe,
            )
            if fleet.disposition is GoalUpdateDisposition.ACCEPTED:
                payload: dict[str, Any] = {
                    "event_id": event.event_id,
                    "event_sha256": canonical_sha256(event),
                    "disposition": DynamicReplanDisposition.ACCEPTED,
                    "old_world_sha256": old_world_sha256,
                    "replacement_world_sha256": replacement_world_sha256,
                    "old_epoch": old_epoch,
                    "reaction_horizon": reaction,
                    "feasibility_certificate_sha256s": feasibility_certificate_sha256s,
                    "fleet_decision": fleet,
                    "reason": "replacement world and all affected routes committed atomically",
                    "authority_sha256": canonical_sha256(
                        [event, replacement_world_sha256, fleet.authority_sha256]
                    ),
                }
                decision = DynamicFleetReplanDecision(
                    **payload,
                    decision_sha256=canonical_sha256(payload),
                )
            else:
                decision = _dynamic_rejection(
                    event=event,
                    disposition=DynamicReplanDisposition.BLOCKED_ATOMIC_COMMIT,
                    reason=fleet.reason,
                    old_world_sha256=old_world_sha256,
                    replacement_world_sha256=replacement_world_sha256,
                    old_epoch=old_epoch,
                    reaction_horizon=reaction,
                    certificate_sha256s=feasibility_certificate_sha256s,
                    fallback=fleet.fallback or SafeFallback.FLEET_ABORT_AND_LAND,
                    fleet_decision=fleet,
                )
        self._decision_by_event_id[event.event_id] = decision
        return decision


def _changed_world_case(
    case: CampaignCase,
    event: InFlightEnvironmentEvent,
    observations: Mapping[str, ReplanObservation],
    old_trajectories: Mapping[str, TimeParameterizedTrajectory],
) -> CampaignCase:
    semantics = case.semantics
    if semantics is None:
        raise ValueError("changed-world replanning requires explicit case semantics")
    environment = _environment_after_event(semantics.environment_constraints, event)
    hard_constraints = case.hard_constraints
    if event.kind is DynamicEventKind.POSITION_UNCERTAINTY_CHANGED:
        assert event.position_uncertainty_m is not None
        # A source-time uncertainty update may tighten protection.  Reducing the
        # frozen allowance would weaken the original safety case and is rejected.
        if event.position_uncertainty_m < hard_constraints.position_uncertainty_m:
            raise ValueError("dynamic uncertainty cannot weaken the frozen allowance")
        hard_constraints = hard_constraints.model_copy(
            update={"position_uncertainty_m": event.position_uncertainty_m}
        )
    if event.kind is DynamicEventKind.PEER_TRAJECTORY_UPDATED:
        raise ValueError(
            "peer trajectory hashes alone cannot produce executable geometry; "
            "a source-time trajectory payload is required"
        )

    drone_by_role = {item.role_id: item for item in case.drones}
    replacement_drones: list[DroneCase] = []
    route_intent: dict[str, tuple[RouteNodeIntent, ...]] = {}
    for role_id in sorted(event.affected_role_ids):
        drone = drone_by_role[role_id]
        observation = observations[role_id]
        old_trajectory = old_trajectories[role_id]
        remaining_goals = _remaining_goals(drone, old_trajectory, observation.position_m)
        replacement_drones.append(
            drone.model_copy(
                update={
                    "start_region": _observation_region(
                        role_id,
                        observation.position_m,
                        hard_constraints.flight_volume,
                    ),
                    "goal_sequence": remaining_goals,
                }
            )
        )
        source_intent = {item.region_id: item for item in case.route_nodes_for(role_id)}
        route_intent[role_id] = tuple(
            source_intent.get(
                goal.region_id,
                RouteNodeIntent(region_id=goal.region_id, mode=RouteNodeMode.CAPTURE),
            )
            for goal in remaining_goals
        )

    coordination = semantics.coordination_constraints
    if coordination.maximum_formation_error_m is not None:
        if set(event.affected_role_ids) != set(drone_by_role):
            raise ValueError("a formation replan must include the complete formation")
        # Preserve the declared formation contract for a full-fleet replacement.
        replacement_coordination = coordination
    else:
        replacement_coordination = coordination.model_copy(
            update={
                "synchronized_route_start_required": True,
                "maximum_route_start_skew_s": 0.0,
                "minimum_simultaneous_flight_s": 0.0,
            }
        )
    behavior_oracles = tuple(
        oracle
        for oracle in semantics.behavior_oracles
        if not oracle.role_ids or set(oracle.role_ids).issubset(event.affected_role_ids)
    )
    if not behavior_oracles:
        behavior_oracles = (
            semantics.behavior_oracles[0].model_copy(
                update={"role_ids": tuple(sorted(event.affected_role_ids))}
            ),
        )
    replacement_semantics = semantics.model_copy(
        update={
            "route_intent_by_role": route_intent,
            "environment_constraints": environment,
            "coordination_constraints": replacement_coordination,
            "scenario_events": (),
            "behavior_oracles": behavior_oracles,
            "semantic_baseline_case_id": case.case_id,
            "intended_delta": (
                f"Source-time {event.kind.value} event {event.event_id} applied to "
                "the still-authoritative remainder of the route."
            ),
        }
    )
    in_flight_strategies = tuple(
        strategy
        for strategy in case.allowed_strategies
        if strategy
        in {
            PlannerStrategy.DIRECT,
            PlannerStrategy.SPEED_RETIMING,
            PlannerStrategy.HORIZONTAL_DETOUR,
            PlannerStrategy.VERTICAL_LAYER,
        }
    )
    if not in_flight_strategies:
        raise ValueError("original case grants no in-flight planning dimension")
    identity = canonical_sha256(
        [
            case.case_sha256,
            event,
            tuple(observations[role_id].observation_sha256 for role_id in sorted(observations)),
        ]
    )
    payload = case.model_dump(mode="python")
    payload.update(
        {
            "case_id": f"replan.{identity[:24]}",
            "parent_case_sha256": case.case_sha256,
            "baseline_sha256": case.case_sha256,
            "purpose": "Execute a bounded source-time changed-world fleet replacement.",
            "behavior_under_test": (
                "Fresh observations and changed immutable world generation produce a "
                "new independently certified trajectory epoch."
            ),
            "expected_outcome": (
                "All affected roles receive one feasible generation or no role commits."
            ),
            "drone_count": len(replacement_drones),
            "drones": tuple(replacement_drones),
            "hard_constraints": hard_constraints,
            "allowed_strategies": in_flight_strategies,
            "search": case.search.model_copy(
                update={
                    "maximum_candidate_count": min(
                        case.search.maximum_candidate_count,
                        16,
                    ),
                    "planning_budget_s": min(
                        case.search.planning_budget_s,
                        hard_constraints.planning_budget_s,
                    ),
                }
            ),
            "semantics": replacement_semantics,
            "named_variations": ("source_time_changed_world",),
        }
    )
    return CampaignCase.model_validate(payload)


def _environment_after_event(
    environment: EnvironmentConstraints,
    event: InFlightEnvironmentEvent,
) -> EnvironmentConstraints:
    solids = list(environment.keep_out_regions)
    passages = list(environment.required_corridors)

    def replace_named(values: list[Region3D], region_id: str, region: Region3D) -> None:
        matches = [index for index, value in enumerate(values) if value.region_id == region_id]
        if len(matches) != 1:
            raise ValueError(f"dynamic region {region_id!r} does not identify one object")
        values[matches[0]] = region

    if event.kind is DynamicEventKind.OBSTACLE_ADDED:
        assert event.region is not None and event.region_id is not None
        if any(item.region_id == event.region_id for item in (*solids, *passages)):
            raise ValueError("dynamic obstacle ID already exists")
        solids.append(event.region)
    elif event.kind is DynamicEventKind.OBSTACLE_MOVED:
        assert event.region is not None and event.region_id is not None
        replace_named(solids, event.region_id, event.region)
    elif event.kind is DynamicEventKind.OBSTACLE_REMOVED:
        assert event.region_id is not None
        retained = [item for item in solids if item.region_id != event.region_id]
        if len(retained) == len(solids):
            raise ValueError("dynamic obstacle removal names an unknown object")
        solids = retained
    elif event.kind is DynamicEventKind.PASSAGE_CLOSED:
        assert event.region is not None and event.region_id is not None
        passages = [item for item in passages if item.region_id != event.region_id]
        if any(item.region_id == event.region_id for item in solids):
            raise ValueError("closed passage ID collides with an existing solid")
        solids.append(event.region)
    elif event.kind is DynamicEventKind.PASSAGE_OPENED:
        assert event.region is not None and event.region_id is not None
        solids = [item for item in solids if item.region_id != event.region_id]
        if any(item.region_id == event.region_id for item in passages):
            raise ValueError("opened passage ID already exists")
        passages.append(event.region)
    return environment.model_copy(
        update={
            "keep_out_regions": tuple(solids),
            "required_corridors": tuple(passages),
        }
    )


def _in_flight_planning_submission(
    case: CampaignCase,
    submission: PlanningSubmission,
) -> PlanningSubmission:
    if (
        case.parent_case_sha256 != submission.case_sha256
        or "source_time_changed_world" not in case.named_variations
    ):
        raise ValueError("in-flight authority derivation requires an explicit changed-world child")
    registry_row_for_case(case)
    if case.execution.backend_profile_id not in submission.supported_backend_profile_ids:
        raise ValueError("in-flight child selected an unqualified backend")
    authority = tuple(
        strategy
        for strategy in submission.strategy_authority
        if strategy in case.allowed_strategies
    )
    dimensions = tuple(
        dimension
        for dimension in submission.maneuver_dimensions
        if dimension
        in {
            ManeuverDimension.SPEED,
            ManeuverDimension.LATERAL,
            ManeuverDimension.VERTICAL,
        }
    )
    if not dimensions:
        dimensions = (ManeuverDimension.TIMING,)
    if not authority:
        raise ValueError("changed-world child has no explicitly retained in-flight authority")
    profile = resolve_submission(
        case,
        submission.execution_profile_submission_id,
        require_executable=True,
    )
    return submission.model_copy(
        update={
            "planning_submission_id": (
                submission.planning_submission_id
                if submission.planning_submission_id.startswith("in_flight.")
                else f"in_flight.{submission.planning_submission_id}"[:96]
            ),
            "strategy_authority": authority,
            "maneuver_dimensions": dimensions,
            "case_id": case.case_id,
            "case_sha256": case.case_sha256,
            "world_definition_sha256": canonical_sha256(planning_world_definition(case)),
            "vehicle_model_sha256": canonical_sha256(planning_vehicle_model()),
            "execution_profile_sha256": profile.profile_sha256,
            "coordination": submission.coordination.model_copy(
                update={
                    "synchronized_launch_required": False,
                    "synchronized_route_start_required": True,
                    "minimum_simultaneous_flight_s": 0.0,
                    "maximum_release_delay_s": 0.0,
                }
            ),
        }
    )


def _remaining_goals(
    drone: DroneCase,
    trajectory: TimeParameterizedTrajectory,
    position: Vector3,
) -> tuple[Region3D, ...]:
    current_index = min(
        range(len(trajectory.points)),
        key=lambda index: _distance(trajectory.points[index].position_m, position),
    )
    remaining = tuple(
        goal
        for goal in drone.goal_sequence
        if min(
            range(len(trajectory.points)),
            key=lambda index: _distance(
                trajectory.points[index].position_m,
                goal.center_m,
            ),
        )
        >= current_index
    )
    return remaining or (drone.goal_sequence[-1],)


def _observation_region(
    role_id: str,
    position: Vector3,
    volume: Region3D,
) -> Region3D:
    radius = 0.002

    def bounds(value: float, minimum: float, maximum: float) -> tuple[float, float]:
        low = max(minimum, value - radius)
        high = min(maximum, value + radius)
        if high - low < radius:
            low = max(minimum, high - radius)
            high = min(maximum, low + radius)
        return low, high

    x0, x1 = bounds(position.x, volume.minimum_m.x, volume.maximum_m.x)
    y0, y1 = bounds(position.y, volume.minimum_m.y, volume.maximum_m.y)
    z0, z1 = bounds(position.z, volume.minimum_m.z, volume.maximum_m.z)
    return Region3D(
        region_id=f"{role_id}.replan-start",
        minimum_m=Vector3(x=x0, y=y0, z=z0),
        maximum_m=Vector3(x=x1, y=y1, z=z1),
    )


def _reaction_horizon(
    event: InFlightEnvironmentEvent,
    *,
    decision_time_source_s: float,
    queue_latency_s: float,
    planning_latency_s: float,
    acknowledgement_latency_s: float,
    cutover_guard_s: float,
    old_epoch_safe_until_source_s: float,
    planning_budget_s: float,
    freshness_limit_s: float,
) -> ReactionHorizonAudit:
    values = (
        decision_time_source_s,
        queue_latency_s,
        planning_latency_s,
        acknowledgement_latency_s,
        cutover_guard_s,
        old_epoch_safe_until_source_s,
    )
    if any(value < 0.0 for value in values):
        raise ValueError("reaction timing values must be non-negative")
    observation_latency_s = event.received_source_s - event.source_timestamp_s
    total_reaction_s = (
        observation_latency_s
        + queue_latency_s
        + planning_latency_s
        + acknowledgement_latency_s
        + cutover_guard_s
    )
    proposed_cutover_source_s = max(
        event.source_timestamp_s + total_reaction_s,
        decision_time_source_s + acknowledgement_latency_s + cutover_guard_s,
    )
    deadline = min(event.effective_source_s, old_epoch_safe_until_source_s)
    passed = (
        observation_latency_s <= freshness_limit_s
        and planning_latency_s <= planning_budget_s
        and proposed_cutover_source_s <= deadline + 1e-9
    )
    return ReactionHorizonAudit(
        observation_latency_s=observation_latency_s,
        queue_latency_s=queue_latency_s,
        planning_latency_s=planning_latency_s,
        acknowledgement_latency_s=acknowledgement_latency_s,
        cutover_guard_s=cutover_guard_s,
        total_reaction_s=total_reaction_s,
        available_event_lead_s=event.effective_source_s - event.source_timestamp_s,
        available_old_epoch_horizon_s=(old_epoch_safe_until_source_s - event.source_timestamp_s),
        reaction_deadline_source_s=deadline,
        proposed_cutover_source_s=proposed_cutover_source_s,
        passed=passed,
    )


def _dynamic_rejection(
    *,
    event: InFlightEnvironmentEvent,
    disposition: DynamicReplanDisposition,
    reason: str,
    old_world_sha256: str,
    replacement_world_sha256: str,
    old_epoch: int,
    reaction_horizon: ReactionHorizonAudit,
    certificate_sha256s: tuple[str, ...],
    fallback: SafeFallback,
    fleet_decision: FleetReplanDecision | None = None,
) -> DynamicFleetReplanDecision:
    authority_sha = canonical_sha256([event, old_epoch, "NO_DYNAMIC_COMMIT", fallback])
    payload: dict[str, Any] = {
        "event_id": event.event_id,
        "event_sha256": canonical_sha256(event),
        "disposition": disposition,
        "old_world_sha256": old_world_sha256,
        "replacement_world_sha256": replacement_world_sha256,
        "old_epoch": old_epoch,
        "reaction_horizon": reaction_horizon,
        "feasibility_certificate_sha256s": certificate_sha256s,
        "fleet_decision": fleet_decision,
        "fallback": fallback,
        "reason": reason,
        "authority_sha256": authority_sha,
    }
    return DynamicFleetReplanDecision(
        **payload,
        decision_sha256=canonical_sha256(payload),
    )


def _single_rejection(
    common: dict[str, Any],
    disposition: GoalUpdateDisposition,
    reason: str,
    fallback: SafeFallback,
) -> SingleReplanDecision:
    authority_sha = canonical_sha256(
        [common["old_plan_sha256"], common["old_reservation_sha256"], fallback]
    )
    payload = {
        **common,
        "disposition": disposition,
        "reason": reason,
        "authority_sha256": authority_sha,
        "fallback": fallback,
    }
    return SingleReplanDecision(**payload, decision_sha256=canonical_sha256(payload))


def _replacement_trajectory(
    case: CampaignCase,
    observation: ReplanObservation,
    update: GoalUpdate,
) -> ContinuousCutoverTrajectory:
    target = update.goal_region.center_m
    distance = _distance(observation.position_m, target)
    duration = max(
        1.0, distance / min(0.20, case.hard_constraints.dynamics.maximum_horizontal_speed_m_s * 0.5)
    )
    for _ in range(12):
        points = (
            TrajectoryPoint(
                sequence=1,
                time_from_start_s=0.0,
                position_m=observation.position_m,
                velocity_m_s=observation.velocity_m_s,
                acceleration_m_s2=observation.acceleration_m_s2,
            ),
            TrajectoryPoint(
                sequence=2,
                time_from_start_s=duration,
                position_m=target,
                velocity_m_s=Vector3(),
                acceleration_m_s2=Vector3(),
            ),
        )
        trajectory = ContinuousCutoverTrajectory(
            trajectory_id=f"replacement-{canonical_sha256([update, observation, duration])[:20]}",
            role_id=observation.role_id,
            vehicle_id=observation.role_id,
            route_sha256=canonical_sha256([observation.position_m, target, update.goal_revision]),
            points=points,
            completion_position_tolerance_m=0.05,
            completion_velocity_tolerance_m_s=0.05,
        )
        audit = audit_trajectory(case, trajectory)
        if audit.passed:
            return trajectory
        duration *= 1.5
    raise ValueError("no bounded C2 replacement trajectory satisfies dynamics")


def _norm(value: Vector3) -> float:
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )
