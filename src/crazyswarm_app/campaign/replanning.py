from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from enum import StrEnum
from itertools import pairwise
from typing import Any, Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.corridor import (
    GoalCorridorDisposition,
    GoalCorridorSearchResult,
    search_goal_corridor,
)
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
    plan_goal_corridor_candidate,
)
from crazyswarm_app.campaign.submissions import (
    CapabilityResolution,
    ExecutionProfileSubmission,
    ManeuverDimension,
    PlanningSubmission,
    SubmissionStatus,
    planning_vehicle_model,
    planning_world_definition,
    registry_row_for_case,
    resolve_package_capability_resolution,
    resolve_submission,
)
from crazyswarm_app.campaign.trajectory import (
    ContinuousCutoverTrajectory,
    SmoothTrajectorySet,
    audit_trajectory,
    generate_smooth_trajectories,
)
from crazyswarm_app.domain.commands import TrajectoryReplacementPreparationReceipt
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import (
    TimeParameterizedTrajectory,
    TrajectoryPoint,
    sample_trajectory,
)


class SafeFallback(StrEnum):
    CONTINUE_OLD_SAFE_EPOCH = "CONTINUE_OLD_SAFE_EPOCH"
    BOUNDED_HOLD = "BOUNDED_HOLD"
    ABORT_AND_LAND = "ABORT_AND_LAND"
    FLEET_ABORT_AND_LAND = "FLEET_ABORT_AND_LAND"


class SafeFallbackCommand(StrEnum):
    STOP_AND_HOLD = "STOP_AND_HOLD"
    ABORT_AND_LAND = "ABORT_AND_LAND"
    UNQUALIFIED_EMERGENCY_FALLBACK = "UNQUALIFIED_EMERGENCY_FALLBACK"


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
    world_generation: int | None = Field(default=None, ge=1)

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


class SafePrefixCertificate(ContractModel):
    schema_version: Literal[1] = 1
    case_sha256: SHA256
    event_sha256: SHA256
    observation_sha256s: tuple[SHA256, ...] = Field(min_length=1, max_length=3)
    perceived_world_sha256: SHA256
    old_world_sha256: SHA256
    active_trajectory_sha256s: tuple[SHA256, ...] = Field(min_length=1, max_length=3)
    safe_until_source_s: float = Field(ge=0.0)
    stopping_envelope_m: float = Field(ge=0.0)
    certified_clearance_m: float = Field(ge=0.0)
    observation_fresh_until_source_s: float = Field(ge=0.0)
    fallback_command: SafeFallbackCommand
    fallback_route_sha256: SHA256 | None = None
    passed: bool
    certificate_sha256: SHA256

    @model_validator(mode="after")
    def hash_and_fallback_are_complete(self) -> SafePrefixCertificate:
        if (self.fallback_command is SafeFallbackCommand.ABORT_AND_LAND) != (
            self.fallback_route_sha256 is not None
        ):
            raise ValueError("abort fallback requires one certified landing route")
        payload = self.model_dump(mode="python", exclude={"certificate_sha256"})
        if canonical_sha256(payload) != self.certificate_sha256:
            raise ValueError("safe-prefix certificate hash mismatch")
        return self


class AbortRouteCertificate(ContractModel):
    """Independent direct-to-accepted-landing fallback geometry certificate."""

    schema_version: Literal[1] = 1
    case_sha256: SHA256
    perceived_world_sha256: SHA256
    observation_sha256s: tuple[SHA256, ...] = Field(min_length=1, max_length=3)
    route_points_by_role: dict[Identifier, tuple[Vector3, Vector3]]
    minimum_sampled_clearance_m: float
    sample_step_fraction: float = Field(gt=0.0, le=0.10)
    passed: bool
    certificate_sha256: SHA256

    @model_validator(mode="after")
    def hash_matches_payload(self) -> AbortRouteCertificate:
        payload = self.model_dump(mode="python", exclude={"certificate_sha256"})
        if canonical_sha256(payload) != self.certificate_sha256:
            raise ValueError("abort-route certificate hash mismatch")
        return self


class ChangedWorldSafetyMonitor:
    """Derive old-prefix safety independently from planner and execution caller."""

    def __init__(self, case: CampaignCase) -> None:
        self.case = case

    def certify_abort_route(
        self,
        *,
        observations: Sequence[ReplanObservation],
        perceived_world_sha256: SHA256,
        perceived_solids: Mapping[str, Region3D],
        minimum_clearance_m: float,
        landing_targets_by_role: Mapping[str, Vector3] | None = None,
    ) -> AbortRouteCertificate:
        observations_by_role = {item.role_id: item for item in observations}
        landing_by_role = (
            dict(landing_targets_by_role)
            if landing_targets_by_role is not None
            else {
                item.role_id: Vector3(
                    x=item.landing_region.center_m.x,
                    y=item.landing_region.center_m.y,
                    z=0.0,
                )
                for item in self.case.drones
            }
        )
        if set(observations_by_role) != set(landing_by_role):
            raise ValueError("abort-route observations do not cover the accepted roles")
        routes = {
            role_id: (observations_by_role[role_id].position_m, landing_by_role[role_id])
            for role_id in sorted(landing_by_role)
        }
        sample_step_fraction = 1.0 / 64.0
        clearances = [
            _distance_to_region(_interpolate(start, end, index / 64.0), solid)
            - 0.055
            - self.case.hard_constraints.position_uncertainty_m
            for start, end in routes.values()
            for index in range(65)
            for solid in perceived_solids.values()
        ]
        minimum_sampled_clearance = min(clearances, default=1_000_000.0)
        volume = self.case.hard_constraints.flight_volume
        volume_passed = all(
            volume.contains(point)
            for start, end in routes.values()
            for point in (_interpolate(start, end, index / 64.0) for index in range(65))
        )
        payload: dict[str, Any] = {
            "schema_version": 1,
            "case_sha256": self.case.case_sha256,
            "perceived_world_sha256": perceived_world_sha256,
            "observation_sha256s": tuple(
                observations_by_role[role_id].observation_sha256
                for role_id in sorted(observations_by_role)
            ),
            "route_points_by_role": routes,
            "minimum_sampled_clearance_m": minimum_sampled_clearance,
            "sample_step_fraction": sample_step_fraction,
            "passed": volume_passed and minimum_sampled_clearance >= minimum_clearance_m,
        }
        return AbortRouteCertificate(
            **payload,
            certificate_sha256=canonical_sha256(payload),
        )

    def certify(
        self,
        *,
        event: InFlightEnvironmentEvent,
        observations: Sequence[ReplanObservation],
        active_trajectories: Mapping[str, TimeParameterizedTrajectory],
        perceived_world_sha256: SHA256,
        old_world_sha256: SHA256,
        minimum_clearance_m: float,
        abort_route_certificate: AbortRouteCertificate | None = None,
    ) -> SafePrefixCertificate:
        if set(event.affected_role_ids) != {item.role_id for item in observations}:
            raise ValueError("safe-prefix observations do not cover the affected roles")
        if set(event.affected_role_ids) != set(active_trajectories):
            raise ValueError("safe-prefix trajectories do not cover the affected roles")
        acceleration = self.case.hard_constraints.dynamics.maximum_acceleration_m_s2
        speed = max((_norm(item.velocity_m_s) for item in observations), default=0.0)
        stopping_envelope = (
            speed * speed / (2.0 * acceleration) + self.case.hard_constraints.position_uncertainty_m
        )
        obstacle_clearance = min(
            (
                _distance_to_region(item.position_m, event.region)
                for item in observations
                if event.region is not None
            ),
            default=1_000_000.0,
        )
        hold_clear = obstacle_clearance >= stopping_envelope + minimum_clearance_m
        if hold_clear:
            fallback = SafeFallbackCommand.STOP_AND_HOLD
            fallback_route = None
            certified_clearance = obstacle_clearance - stopping_envelope
            passed = True
        elif (
            abort_route_certificate is not None
            and abort_route_certificate.passed
            and abort_route_certificate.case_sha256 == self.case.case_sha256
            and abort_route_certificate.perceived_world_sha256 == perceived_world_sha256
            and abort_route_certificate.observation_sha256s
            == tuple(
                item.observation_sha256
                for item in sorted(observations, key=lambda item: item.role_id)
            )
        ):
            fallback = SafeFallbackCommand.ABORT_AND_LAND
            fallback_route = abort_route_certificate.certificate_sha256
            certified_clearance = abort_route_certificate.minimum_sampled_clearance_m
            passed = True
        else:
            fallback = SafeFallbackCommand.UNQUALIFIED_EMERGENCY_FALLBACK
            fallback_route = None
            certified_clearance = max(0.0, obstacle_clearance - stopping_envelope)
            passed = False
        fresh_until = min(
            item.captured_at_source_s + self.case.hard_constraints.observation_freshness_limit_s
            for item in observations
        )
        safe_until = (
            event.effective_source_s if passed else min(event.effective_source_s, fresh_until)
        )
        payload: dict[str, Any] = {
            "schema_version": 1,
            "case_sha256": self.case.case_sha256,
            "event_sha256": canonical_sha256(event),
            "observation_sha256s": tuple(
                item.observation_sha256
                for item in sorted(observations, key=lambda item: item.role_id)
            ),
            "perceived_world_sha256": perceived_world_sha256,
            "old_world_sha256": old_world_sha256,
            "active_trajectory_sha256s": tuple(
                active_trajectories[role_id].sha256 for role_id in sorted(active_trajectories)
            ),
            "safe_until_source_s": safe_until,
            "stopping_envelope_m": stopping_envelope,
            "certified_clearance_m": certified_clearance,
            "observation_fresh_until_source_s": fresh_until,
            "fallback_command": fallback,
            "fallback_route_sha256": fallback_route,
            "passed": passed,
        }
        return SafePrefixCertificate(**payload, certificate_sha256=canonical_sha256(payload))


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


class MovingCutoverCertificate(ContractModel):
    """Independent sampled authority for a fresh-state replacement splice."""

    schema_version: Literal[1] = 1
    verifier_id: Literal["independent-moving-cutover-v1"] = "independent-moving-cutover-v1"
    replacement_case_sha256: SHA256
    observation_sha256_by_role: dict[Identifier, SHA256]
    observation_source_timestamp_s_by_role: dict[Identifier, float]
    trajectory_sha256_by_role: dict[Identifier, SHA256]
    dynamics_audit_sha256_by_role: dict[Identifier, SHA256]
    sample_step_s: float = Field(gt=0.0, le=0.02)
    maximum_sample_spacing_m: float = Field(ge=0.0)
    maximum_start_position_error_m: float = Field(ge=0.0)
    maximum_start_velocity_error_m_s: float = Field(ge=0.0)
    maximum_start_acceleration_error_m_s2: float = Field(ge=0.0)
    minimum_solid_protected_clearance_m: float
    minimum_boundary_protected_clearance_m: float
    minimum_pairwise_protected_clearance_m: float
    violations: tuple[str, ...]
    passed: bool
    certificate_sha256: SHA256

    @model_validator(mode="after")
    def hash_and_verdict_match(self) -> MovingCutoverCertificate:
        payload = self.model_dump(mode="python", exclude={"certificate_sha256"})
        if self.certificate_sha256 != canonical_sha256(payload):
            raise ValueError("moving-cutover certificate hash mismatch")
        if self.passed != (not self.violations):
            raise ValueError("moving-cutover certificate verdict differs from violations")
        return self


class ChangedWorldReplanProposal(ContractModel):
    """Planner-produced replacement; acknowledgements are intentionally not guessed."""

    schema_version: Literal[1] = 1
    event: InFlightEnvironmentEvent
    original_case_sha256: SHA256
    replacement_case: CampaignCase
    old_world_sha256: SHA256
    replacement_world_sha256: SHA256
    planning_submission: PlanningSubmission
    execution_profile: ExecutionProfileSubmission
    capability_resolution: CapabilityResolution | None = None
    plan: BoundedPlanningResult
    goal_corridor_search: GoalCorridorSearchResult | None = None
    trajectories: SmoothTrajectorySet
    cutover_certificate: MovingCutoverCertificate
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
        if (
            self.execution_profile.case_id != self.replacement_case.case_id
            or self.execution_profile.case_sha256 != self.replacement_case.case_sha256
            or self.execution_profile.submission_id
            != self.planning_submission.execution_profile_submission_id
            or self.execution_profile.profile_sha256
            != self.planning_submission.execution_profile_sha256
        ):
            raise ValueError("changed-world proposal lost its resolved execution profile")
        expected_capability = resolve_package_capability_resolution(
            self.replacement_case,
            self.planning_submission,
            self.execution_profile,
        )
        if self.capability_resolution != expected_capability:
            raise ValueError("changed-world proposal capability resolution mismatch")
        if self.plan.status is not PlanningStatus.READY or self.plan.selected is None:
            raise ValueError("changed-world proposal requires a ready selected plan")
        certificate = self.plan.feasibility_certificate
        if certificate is None or not certificate.passed:
            raise ValueError("changed-world proposal lacks an independent certificate")
        if not self.cutover_certificate.passed:
            raise ValueError("changed-world proposal lacks a safe moving cutover")
        if self.replacement_case.family == "online_obstacle_replan" and (
            self.goal_corridor_search is None
            or self.goal_corridor_search.disposition is not GoalCorridorDisposition.SELECTED
            or self.plan.planner_id != self.goal_corridor_search.planner_id
            or self.event.world_generation is None
        ):
            raise ValueError("online obstacle proposal lacks selected goal-corridor authority")
        roles = tuple(item.role_id for item in self.route_authorities)
        if len(set(roles)) != len(roles) or set(roles) != set(self.event.affected_role_ids):
            raise ValueError("changed-world route authority does not cover affected roles exactly")
        trajectory_by_role = {item.role_id: item for item in self.trajectories.trajectories}
        if set(trajectory_by_role) != set(roles):
            raise ValueError("changed-world trajectory set differs from route authority")
        if self.cutover_certificate.trajectory_sha256_by_role != {
            role_id: trajectory_by_role[role_id].sha256 for role_id in sorted(roles)
        }:
            raise ValueError("moving-cutover certificate differs from replacement trajectories")
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
    execution_profile: ExecutionProfileSubmission | None = None,
    capability_resolution: CapabilityResolution | None = None,
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
    source_profile = execution_profile or resolve_submission(
        case,
        planning_submission.execution_profile_submission_id,
        require_executable=True,
    )
    rebound, rebound_profile, rebound_capability = _in_flight_planning_package(
        case,
        replacement_case,
        planning_submission,
        source_profile,
        capability_resolution,
    )
    goal_corridor_search: GoalCorridorSearchResult | None = None
    if replacement_case.family == "online_obstacle_replan":
        if replacement_case.drone_count != 1:
            raise ValueError("online goal-corridor replanning currently requires one role")
        role_id = next(iter(sorted(affected)))
        drone = next(item for item in replacement_case.drones if item.role_id == role_id)
        environment = replacement_case.semantics
        if environment is None:
            raise ValueError("online goal-corridor replanning requires world semantics")
        policy = rebound.clearance
        observation = observation_by_role[role_id]
        protected_inflation_m = (
            policy.nominal_vehicle_radius_m
            + policy.uncertainty_allowance_m
            + policy.required_solid_clearance_m
        )
        # The A* certificate is for its polyline, while the executable route is
        # a C2 spline through those knots. Reserve one lattice cell so corner
        # rounding cannot consume the required protected clearance.
        search_inflation_m = protected_inflation_m + 0.05
        search_start_m = _project_goal_corridor_start(
            observation,
            flight_volume=replacement_case.hard_constraints.flight_volume,
            obstacles=environment.environment_constraints.keep_out_regions,
            protected_inflation_m=search_inflation_m,
            boundary_horizontal_margin_m=(protected_inflation_m),
            stop_speed_threshold_m_s=(
                replacement_case.hard_constraints.dynamics.stop_speed_threshold_m_s
            ),
        )
        corridor_started_s = time.monotonic()
        goal_corridor_search = search_goal_corridor(
            start_m=search_start_m,
            goal_m=drone.goal_sequence[-1].center_m,
            flight_volume=replacement_case.hard_constraints.flight_volume,
            obstacles=environment.environment_constraints.keep_out_regions,
            inflation_m=search_inflation_m,
            boundary_horizontal_margin_m=(protected_inflation_m),
            expansion_limit=8192,
            wall_budget_s=0.5,
        )
        plan = plan_goal_corridor_candidate(
            replacement_case,
            rebound,
            goal_corridor_search,
            role_id=role_id,
            submission=rebound_profile,
            capability_resolution=rebound_capability,
        )
        if time.monotonic() - corridor_started_s >= goal_corridor_search.wall_budget_s:
            goal_corridor_search = _goal_corridor_budget_exhausted(goal_corridor_search)
            plan = plan_goal_corridor_candidate(
                replacement_case,
                rebound,
                goal_corridor_search,
                role_id=role_id,
                submission=rebound_profile,
                capability_resolution=rebound_capability,
            )
    else:
        plan = BoundedJointPlanner().plan(
            replacement_case,
            rebound_profile,
            planning_submission=rebound,
            capability_resolution=rebound_capability,
            first_certified_within_budget=True,
        )
    if plan.status is not PlanningStatus.READY or plan.selected is None:
        raise ValueError(plan.blocking_reason or "changed world has no admitted replacement")
    if plan.feasibility_certificate is None or not plan.feasibility_certificate.passed:
        raise ValueError("changed-world plan lacks independent feasibility authority")
    trajectories = generate_smooth_trajectories(
        replacement_case,
        plan.selected,
        submission=rebound_profile,
        planning_submission=rebound,
        capability_resolution=rebound_capability,
    )
    trajectories, cutover_certificate = _splice_trajectory_set_to_observations(
        replacement_case,
        rebound,
        trajectories,
        observation_by_role,
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
                [
                    certificate_sha,
                    cutover_certificate.certificate_sha256,
                    role_id,
                    replacement_by_role[role_id].sha256,
                ]
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
                    cutover_certificate.certificate_sha256,
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
        "execution_profile": rebound_profile,
        "capability_resolution": rebound_capability,
        "plan": plan,
        "goal_corridor_search": goal_corridor_search,
        "trajectories": trajectories,
        "cutover_certificate": cutover_certificate,
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
        "execution_profile": rebound_profile.model_dump(mode="python"),
        "capability_resolution": (
            rebound_capability.model_dump(mode="python") if rebound_capability is not None else None
        ),
        "plan": plan.model_dump(
            mode="python",
            exclude={"diagnostic_search_duration_s"},
        ),
        "goal_corridor_search": (
            goal_corridor_search.model_dump(mode="python")
            if goal_corridor_search is not None
            else None
        ),
        "trajectories": trajectories.model_dump(mode="python"),
        "cutover_certificate": cutover_certificate.model_dump(mode="python"),
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


def _project_goal_corridor_start(
    observation: ReplanObservation,
    *,
    flight_volume: Region3D,
    obstacles: Sequence[Region3D],
    protected_inflation_m: float,
    boundary_horizontal_margin_m: float,
    stop_speed_threshold_m_s: float,
) -> Vector3:
    """Choose a collision-checked short-horizon lattice start for moving flight.

    Planning directly from the measured point leaves the first snapped grid knot
    behind a vehicle that keeps moving during the bounded planning interval.  The
    resulting rebase can command a short reversal.  Projecting only as far as a
    protected free point preserves physical momentum; the moving-cutover
    certificate still checks the complete executable bridge from the exact sample.
    """

    if _norm(observation.velocity_m_s) <= stop_speed_threshold_m_s:
        return observation.position_m
    # Cover the isolated worker's bounded search/certification latency so the
    # first safe lattice knot is still ahead when the fresh-state rebase runs.
    # Every candidate remains subject to the exact boundary/solid checks below.
    for horizon_s in (1.00, 0.85, 0.70, 0.55, 0.40, 0.25, 0.10, 0.05):
        candidate = Vector3(
            x=observation.position_m.x + observation.velocity_m_s.x * horizon_s,
            y=observation.position_m.y + observation.velocity_m_s.y * horizon_s,
            z=observation.position_m.z + observation.velocity_m_s.z * horizon_s,
        )
        if not flight_volume.contains(candidate):
            continue
        if (
            _boundary_clearance(
                candidate,
                flight_volume,
                horizontal_margin_m=boundary_horizontal_margin_m,
                vertical_margin_m=0.0,
            )
            < 0.0
        ):
            continue
        if all(
            _distance_to_region(candidate, obstacle) + 1e-12 >= protected_inflation_m
            for obstacle in obstacles
        ):
            return candidate
    return observation.position_m


def rebase_changed_world_replacement(
    proposal: ChangedWorldReplanProposal,
    observations: Sequence[ReplanObservation],
) -> ChangedWorldReplanProposal:
    """Bind a completed plan to the newest measured position, velocity, and acceleration."""

    observation_by_role = {item.role_id: item for item in observations}
    expected_roles = {item.role_id for item in proposal.route_authorities}
    if len(observation_by_role) != len(observations) or set(observation_by_role) != expected_roles:
        raise ValueError("fresh cutover observations must cover the affected roles exactly")
    previous_observation_hashes = proposal.cutover_certificate.observation_sha256_by_role
    if any(
        observation_by_role[role_id].source_timestamp_s
        < proposal.cutover_certificate.observation_source_timestamp_s_by_role[role_id]
        for role_id in expected_roles
    ):
        raise ValueError("fresh cutover observation moved backwards in source time")
    if all(
        observation_by_role[role_id].observation_sha256 == previous_observation_hashes[role_id]
        for role_id in expected_roles
    ):
        return proposal

    started = time.perf_counter()
    trajectories, cutover_certificate = _splice_trajectory_set_to_observations(
        proposal.replacement_case,
        proposal.planning_submission,
        proposal.trajectories,
        observation_by_role,
    )
    trajectory_by_role = {item.role_id: item for item in trajectories.trajectories}
    plan_certificate = proposal.plan.feasibility_certificate
    assert plan_certificate is not None
    previous_authority_by_role = {item.role_id: item for item in proposal.route_authorities}
    authorities = tuple(
        ChangedWorldRouteAuthority(
            role_id=role_id,
            old_trajectory_sha256=(previous_authority_by_role[role_id].old_trajectory_sha256),
            replacement_trajectory_sha256=trajectory_by_role[role_id].sha256,
            replacement_plan_sha256=proposal.plan.plan_sha256,
            feasibility_certificate_sha256=canonical_sha256(
                [
                    plan_certificate.certificate_sha256,
                    cutover_certificate.certificate_sha256,
                    role_id,
                    trajectory_by_role[role_id].sha256,
                ]
            ),
            authority_sha256=canonical_sha256(
                [
                    proposal.original_case_sha256,
                    proposal.event,
                    proposal.planning_submission.planning_submission_sha256,
                    proposal.plan.plan_sha256,
                    role_id,
                    trajectory_by_role[role_id].sha256,
                    plan_certificate.certificate_sha256,
                    cutover_certificate.certificate_sha256,
                ]
            ),
        )
        for role_id in sorted(expected_roles)
    )
    payload = proposal.model_dump(
        mode="python",
        exclude={
            "planning_latency_s",
            "proposal_sha256",
            "trajectories",
            "cutover_certificate",
            "route_authorities",
        },
    )
    payload.update(
        {
            "trajectories": trajectories,
            "cutover_certificate": cutover_certificate,
            "route_authorities": authorities,
        }
    )
    planning_latency_s = proposal.planning_latency_s + (time.perf_counter() - started)
    if planning_latency_s > proposal.replacement_case.hard_constraints.planning_budget_s:
        raise ValueError("fresh-state cutover certification exceeded the planning budget")
    stable_payload = {
        **payload,
        "event": proposal.event.model_dump(mode="python"),
        "replacement_case": proposal.replacement_case.model_dump(mode="python"),
        "planning_submission": proposal.planning_submission.model_dump(mode="python"),
        "plan": proposal.plan.model_dump(
            mode="python",
            exclude={"diagnostic_search_duration_s"},
        ),
        "trajectories": trajectories.model_dump(mode="python"),
        "cutover_certificate": cutover_certificate.model_dump(mode="python"),
        "route_authorities": tuple(item.model_dump(mode="python") for item in authorities),
    }
    return ChangedWorldReplanProposal(
        **payload,
        planning_latency_s=planning_latency_s,
        proposal_sha256=canonical_sha256(stable_payload),
    )


def _splice_trajectory_set_to_observations(
    case: CampaignCase,
    planning_submission: PlanningSubmission,
    trajectory_set: SmoothTrajectorySet,
    observations: Mapping[str, ReplanObservation],
    *,
    _trim_stale_prefix: bool = True,
    _trim_failure: str | None = None,
    _maximum_prefix_index: int | None = None,
    _candidate_cache: dict[
        tuple[str, int],
        tuple[TimeParameterizedTrajectory, Any],
    ]
    | None = None,
) -> tuple[SmoothTrajectorySet, MovingCutoverCertificate]:
    if set(observations) != {item.role_id for item in trajectory_set.trajectories}:
        raise ValueError("moving cutover observations and trajectories differ")
    # The fresh-state splice invalidates any pre-cutover profile audit. The output
    # rebuild below deliberately clears those audits while retaining the exact
    # submission identity; dynamics and swept clearance are recertified here.

    candidate_cache = {} if _candidate_cache is None else _candidate_cache
    spliced: list[TimeParameterizedTrajectory] = []
    audits = []
    any_stale_prefix_trimmed = False
    for trajectory in sorted(trajectory_set.trajectories, key=lambda item: item.role_id):
        observation = observations[trajectory.role_id]
        accepted: TimeParameterizedTrajectory | None = None
        accepted_audit = None
        first_planned_index = 1
        maximum_prefix_index = min(
            _maximum_prefix_index or len(trajectory.points) - 1,
            len(trajectory.points) - 1,
        )
        observed_speed = _norm(observation.velocity_m_s)

        def initial_time_scale(
            index: int,
            *,
            observation: ReplanObservation = observation,
            trajectory: TimeParameterizedTrajectory = trajectory,
        ) -> float:
            if case.family != "online_obstacle_replan" or index >= len(trajectory.points) - 1:
                # A terminal-only leg already has a lead knot and goal capture.
                # Stretching that entire leg to absorb the initial heading change
                # turns a brief physical turn into a long, energy-heavy crawl.
                return 1.0
            return _cutover_turn_time_scale(
                observation,
                trajectory.points[index].position_m,
            )

        if (
            _trim_stale_prefix
            and case.family == "online_obstacle_replan"
            and observed_speed > case.hard_constraints.dynamics.stop_speed_threshold_m_s
        ):
            # Planning happens while the old authority remains live.  Drop every
            # non-terminal lattice knot that the fresh vehicle state has already
            # passed, including the distance covered by the 100 ms continuity
            # lead.  Keeping even one such knot commands a physical reversal.
            minimum_forward_projection = observed_speed**2 * 0.10
            while first_planned_index < maximum_prefix_index:
                planned = trajectory.points[first_planned_index].position_m
                forward_projection = _forward_projection_along_observation(
                    observation,
                    planned,
                )
                if forward_projection > minimum_forward_projection:
                    break
                first_planned_index += 1
            # A safety-certification backtrack can cap the removable prefix at
            # a knot that the vehicle has since passed.  That candidate is not
            # a physical fallback: it commands a short reversal before heading
            # toward the goal.  Fail closed so the caller can plan once from the
            # fresh observation instead of dispatching stale geometry.
            selected_projection = _forward_projection_along_observation(
                observation,
                trajectory.points[first_planned_index].position_m,
            )
            if selected_projection <= minimum_forward_projection:
                raise ValueError("fresh-state splice exhausted its forward-safe planned prefix")
            any_stale_prefix_trimmed = first_planned_index > 1
        time_scale = initial_time_scale(first_planned_index)
        # A short grid edge can leave very little time between the measured
        # moving-state lead and the first planned corridor knot.  Scale that
        # transition from the measured audit ratios instead of relying on a
        # fixed number of small retries; otherwise a valid replan can fail by a
        # few percent solely because the chosen corridor begins close by.
        for _ in range(16):
            cached = candidate_cache.get((trajectory.role_id, first_planned_index))
            if cached is not None:
                candidate, candidate_audit = cached
                robust_speed_floor_m_s = max(
                    0.06,
                    3.0 * case.hard_constraints.dynamics.stop_speed_threshold_m_s,
                )
                if (
                    _trim_stale_prefix
                    and case.family == "online_obstacle_replan"
                    and observed_speed >= robust_speed_floor_m_s
                    and candidate_audit.minimum_undeclared_internal_speed_m_s
                    < robust_speed_floor_m_s
                    and first_planned_index < maximum_prefix_index
                ):
                    first_planned_index += 1
                    any_stale_prefix_trimmed = True
                    time_scale = initial_time_scale(first_planned_index)
                    continue
                accepted, accepted_audit = candidate, candidate_audit
                break
            first_duration_s = trajectory.points[first_planned_index].time_from_start_s
            first_segment_extension_s = first_duration_s * (time_scale - 1.0)
            moving_start = (
                _norm(observation.velocity_m_s)
                > case.hard_constraints.dynamics.stop_speed_threshold_m_s
            )
            lead_duration_s = min(0.25, max(0.10, first_duration_s * 0.30)) if moving_start else 0.0
            lead_position = Vector3(
                x=(
                    observation.position_m.x
                    + observation.velocity_m_s.x * lead_duration_s
                    + 0.5 * observation.acceleration_m_s2.x * lead_duration_s**2
                ),
                y=(
                    observation.position_m.y
                    + observation.velocity_m_s.y * lead_duration_s
                    + 0.5 * observation.acceleration_m_s2.y * lead_duration_s**2
                ),
                z=(
                    observation.position_m.z
                    + observation.velocity_m_s.z * lead_duration_s
                    + 0.5 * observation.acceleration_m_s2.z * lead_duration_s**2
                ),
            )
            include_lead = moving_start and case.hard_constraints.flight_volume.contains(
                lead_position
            )
            sequence_offset = 1 if include_lead else 0
            time_offset_s = lead_duration_s if include_lead else 0.0
            sequence_trim = first_planned_index - 1
            first_planned_sequence = trajectory.points[first_planned_index].sequence
            later_points = tuple(
                point.model_copy(
                    update={
                        "sequence": point.sequence - sequence_trim + sequence_offset,
                        "time_from_start_s": (
                            point.time_from_start_s * time_scale
                            if point.sequence == first_planned_sequence
                            else point.time_from_start_s + first_segment_extension_s
                        )
                        + time_offset_s,
                    }
                )
                for point in trajectory.points[first_planned_index:]
            )
            first = trajectory.points[0].model_copy(
                update={
                    "position_m": observation.position_m,
                    "velocity_m_s": observation.velocity_m_s,
                    "acceleration_m_s2": observation.acceleration_m_s2,
                }
            )
            lead = (
                trajectory.points[0].model_copy(
                    update={
                        "sequence": 2,
                        "time_from_start_s": lead_duration_s,
                        "position_m": lead_position,
                        "velocity_m_s": Vector3(
                            x=(
                                observation.velocity_m_s.x
                                + observation.acceleration_m_s2.x * lead_duration_s
                            ),
                            y=(
                                observation.velocity_m_s.y
                                + observation.acceleration_m_s2.y * lead_duration_s
                            ),
                            z=(
                                observation.velocity_m_s.z
                                + observation.acceleration_m_s2.z * lead_duration_s
                            ),
                        ),
                        "acceleration_m_s2": observation.acceleration_m_s2,
                    }
                )
                if include_lead
                else None
            )
            points = (first, lead, *later_points) if lead is not None else (first, *later_points)
            start_is_stopped = (
                _norm(observation.velocity_m_s) <= trajectory.completion_velocity_tolerance_m_s
            )
            declared_stops = tuple(
                sorted(
                    ({1} if start_is_stopped else set())
                    | {
                        (1 if sequence == 1 else sequence - sequence_trim + sequence_offset)
                        for sequence in trajectory.declared_stop_sequences
                        if (sequence != 1 or start_is_stopped) and sequence > sequence_trim
                    }
                )
            )
            route_sha256 = canonical_sha256(
                [trajectory.route_sha256, observation.observation_sha256, points]
            )
            candidate = TimeParameterizedTrajectory(
                trajectory_id=f"moving-cutover-{route_sha256[:20]}",
                role_id=trajectory.role_id,
                vehicle_id=trajectory.vehicle_id,
                route_sha256=route_sha256,
                points=points,
                declared_stop_sequences=declared_stops,
                completion_position_tolerance_m=(trajectory.completion_position_tolerance_m),
                completion_velocity_tolerance_m_s=(trajectory.completion_velocity_tolerance_m_s),
            )
            candidate_audit = audit_trajectory(case, candidate, sample_step_s=0.01)
            if candidate_audit.passed:
                candidate_cache[(trajectory.role_id, first_planned_index)] = (
                    candidate,
                    candidate_audit,
                )
                robust_speed_floor_m_s = max(
                    0.06,
                    3.0 * case.hard_constraints.dynamics.stop_speed_threshold_m_s,
                )
                minimum_internal_speed_m_s = candidate_audit.minimum_undeclared_internal_speed_m_s
                if (
                    _trim_stale_prefix
                    and case.family == "online_obstacle_replan"
                    and observed_speed >= robust_speed_floor_m_s
                    and minimum_internal_speed_m_s < robust_speed_floor_m_s
                    and first_planned_index < maximum_prefix_index
                ):
                    first_planned_index += 1
                    any_stale_prefix_trimmed = True
                    time_scale = initial_time_scale(first_planned_index)
                    continue
                accepted = candidate
                accepted_audit = candidate_audit
                break
            if candidate_audit.failures == ("UNINTENDED_INTERNAL_STOP",):
                # Stretching time cannot remove a geometric reversal and only
                # makes its low-speed interval persist longer. For goal-seeking
                # motion, advance past one more stale prefix knot and re-audit;
                # the final swept-path certificate decides whether that
                # simplification is safe.
                if (
                    _trim_stale_prefix
                    and case.family == "online_obstacle_replan"
                    and first_planned_index < maximum_prefix_index
                ):
                    first_planned_index += 1
                    any_stale_prefix_trimmed = True
                    time_scale = initial_time_scale(first_planned_index)
                    continue
                break
            limits = case.hard_constraints.dynamics
            time_scale *= 1.01 * max(
                1.25,
                candidate_audit.maximum_horizontal_speed_m_s / limits.maximum_horizontal_speed_m_s,
                candidate_audit.maximum_vertical_speed_m_s / limits.maximum_vertical_speed_m_s,
                math.sqrt(
                    candidate_audit.maximum_acceleration_m_s2 / limits.maximum_acceleration_m_s2
                ),
                (candidate_audit.maximum_jerk_m_s3 / limits.maximum_jerk_m_s3) ** (1.0 / 3.0),
            )
        if accepted is None or accepted_audit is None:
            if any_stale_prefix_trimmed and _trim_stale_prefix:
                next_maximum_prefix_index = first_planned_index - 1
                if next_maximum_prefix_index <= 1:
                    raise ValueError(
                        "fresh-state splice exhausted every forward-safe prefix; "
                        "an untrimmed backtrack is not admissible"
                    )
                return _splice_trajectory_set_to_observations(
                    case,
                    planning_submission,
                    trajectory_set,
                    observations,
                    _trim_stale_prefix=True,
                    _trim_failure=(
                        f"trimmed_prefix_start_index={first_planned_index}; "
                        f"failures={candidate_audit.failures}; "
                        f"speed={candidate_audit.maximum_horizontal_speed_m_s:.6f}; "
                        f"acceleration={candidate_audit.maximum_acceleration_m_s2:.6f}; "
                        f"jerk={candidate_audit.maximum_jerk_m_s3:.6f}"
                    ),
                    _maximum_prefix_index=next_maximum_prefix_index,
                    _candidate_cache=candidate_cache,
                )
            raise ValueError(
                f"fresh-state splice for {trajectory.role_id} violates dynamics: "
                f"{candidate_audit.failures}; "
                f"speed={candidate_audit.maximum_horizontal_speed_m_s:.6f}, "
                f"acceleration={candidate_audit.maximum_acceleration_m_s2:.6f}, "
                f"jerk={candidate_audit.maximum_jerk_m_s3:.6f}"
                + (f"; prior_trim={_trim_failure}" if _trim_failure is not None else "")
            )
        spliced.append(accepted)
        audits.append(accepted_audit)

    set_payload = trajectory_set.model_dump(mode="python", exclude={"set_sha256"})
    set_payload.update(
        {
            "trajectories": tuple(spliced),
            "audits": tuple(audits),
            "profile_audits": (),
        }
    )
    draft_set = SmoothTrajectorySet(**set_payload, set_sha256="0" * 64)
    spliced_set = SmoothTrajectorySet(
        **set_payload,
        set_sha256=canonical_sha256(draft_set.canonical_payload()),
    )
    certificate = _certify_moving_cutover(
        case,
        planning_submission,
        spliced_set,
        observations,
    )
    if not certificate.passed:
        if any_stale_prefix_trimmed and _trim_stale_prefix:
            next_maximum_prefix_index = first_planned_index - 1
            if next_maximum_prefix_index <= 1:
                raise ValueError(
                    "fresh-state splice exhausted every forward-safe prefix; "
                    "an untrimmed backtrack is not admissible"
                )
            return _splice_trajectory_set_to_observations(
                case,
                planning_submission,
                trajectory_set,
                observations,
                _trim_stale_prefix=True,
                _trim_failure=(
                    "trimmed prefix failed swept-path certification: "
                    + ", ".join(certificate.violations)
                    + (
                        "; minimum_solid_protected_clearance_m="
                        f"{certificate.minimum_solid_protected_clearance_m:.6f}"
                    )
                ),
                _maximum_prefix_index=next_maximum_prefix_index,
                _candidate_cache=candidate_cache,
            )
        raise ValueError(
            "fresh-state splice failed independent swept-path certification: "
            + ", ".join(certificate.violations)
            + (
                "; minimum_solid_protected_clearance_m="
                f"{certificate.minimum_solid_protected_clearance_m:.6f}"
            )
            + (f"; prior_trim={_trim_failure}" if _trim_failure is not None else "")
            + "; route_knots="
            + repr(
                {
                    item.role_id: tuple(point.position_m for point in item.points)
                    for item in spliced_set.trajectories
                }
            )
        )
    return spliced_set, certificate


def _cutover_turn_time_scale(
    observation: ReplanObservation,
    first_planned_position_m: Vector3,
) -> float:
    """Retain momentum through easy turns and add time for a physically hard cutover."""

    speed = _norm(observation.velocity_m_s)
    direction = Vector3(
        x=first_planned_position_m.x - observation.position_m.x,
        y=first_planned_position_m.y - observation.position_m.y,
        z=first_planned_position_m.z - observation.position_m.z,
    )
    distance = _norm(direction)
    if speed <= 1e-9 or distance <= 1e-9:
        return 1.0
    cosine = (
        observation.velocity_m_s.x * direction.x
        + observation.velocity_m_s.y * direction.y
        + observation.velocity_m_s.z * direction.z
    ) / (speed * distance)
    turn_rad = math.acos(max(-1.0, min(1.0, cosine)))
    gentle_turn_rad = math.pi / 4.0
    if turn_rad <= gentle_turn_rad:
        return 1.0
    # A 180-degree reversal receives at most twice the transition time. The
    # continuous spline still carries the exact measured start velocity; this
    # retiming changes neither the corridor nor the safety/clearance authority.
    return 1.0 + (turn_rad - gentle_turn_rad) / (math.pi - gentle_turn_rad)


def _forward_projection_along_observation(
    observation: ReplanObservation,
    position_m: Vector3,
) -> float:
    delta = Vector3(
        x=position_m.x - observation.position_m.x,
        y=position_m.y - observation.position_m.y,
        z=position_m.z - observation.position_m.z,
    )
    return (
        delta.x * observation.velocity_m_s.x
        + delta.y * observation.velocity_m_s.y
        + delta.z * observation.velocity_m_s.z
    )


def _certify_moving_cutover(
    case: CampaignCase,
    planning_submission: PlanningSubmission,
    trajectory_set: SmoothTrajectorySet,
    observations: Mapping[str, ReplanObservation],
) -> MovingCutoverCertificate:
    """Sample the executable spline independently of route-search feasibility."""

    trajectories = {item.role_id: item for item in trajectory_set.trajectories}
    sample_step_s = min(
        0.01,
        0.01
        / max(
            case.hard_constraints.dynamics.maximum_horizontal_speed_m_s,
            case.hard_constraints.dynamics.maximum_vertical_speed_m_s,
            1e-9,
        ),
    )
    samples_by_role: dict[str, tuple[tuple[float, Any], ...]] = {}
    maximum_spacing = 0.0
    for role_id, trajectory in trajectories.items():
        sample_count = max(1, math.ceil(trajectory.duration_s / sample_step_s))
        samples = tuple(
            (
                trajectory.duration_s * index / sample_count,
                sample_trajectory(
                    trajectory,
                    trajectory.duration_s * index / sample_count,
                ),
            )
            for index in range(sample_count + 1)
        )
        samples_by_role[role_id] = samples
        maximum_spacing = max(
            maximum_spacing,
            *(
                _distance(before[1].position_m, after[1].position_m)
                for before, after in pairwise(samples)
            ),
        )

    start_position_error = max(
        (
            _distance(
                trajectories[role_id].points[0].position_m,
                observation.position_m,
            )
            for role_id, observation in observations.items()
        ),
        default=0.0,
    )
    start_velocity_error = max(
        (
            _distance(
                trajectories[role_id].points[0].velocity_m_s,
                observation.velocity_m_s,
            )
            for role_id, observation in observations.items()
        ),
        default=0.0,
    )
    start_acceleration_error = max(
        (
            _distance(
                trajectories[role_id].points[0].acceleration_m_s2,
                observation.acceleration_m_s2,
            )
            for role_id, observation in observations.items()
        ),
        default=0.0,
    )
    policy = planning_submission.clearance
    environment = case.semantics.environment_constraints if case.semantics is not None else None
    solids = environment.keep_out_regions if environment is not None else ()
    solid_protected = min(
        (
            _distance_to_region(sample.position_m, solid)
            - policy.nominal_vehicle_radius_m
            - policy.required_solid_clearance_m
            - policy.uncertainty_allowance_m
            for samples in samples_by_role.values()
            for _, sample in samples
            for solid in solids
        ),
        default=1_000_000.0,
    )
    volume = case.hard_constraints.flight_volume
    boundary_protected = min(
        (
            _boundary_clearance(
                sample.position_m,
                volume,
                horizontal_margin_m=(
                    policy.nominal_vehicle_radius_m + policy.uncertainty_allowance_m
                ),
                vertical_margin_m=(
                    policy.nominal_vehicle_half_height_m + policy.uncertainty_allowance_m
                ),
            )
            for samples in samples_by_role.values()
            for _, sample in samples
        ),
        default=1_000_000.0,
    )
    maximum_duration = max(
        (trajectory.duration_s for trajectory in trajectories.values()),
        default=0.0,
    )
    pairwise_protected = 1_000_000.0
    ordered_roles = sorted(trajectories)
    if len(ordered_roles) > 1:
        sample_count = max(1, math.ceil(maximum_duration / sample_step_s))
        for first_index, first_role in enumerate(ordered_roles[:-1]):
            for second_role in ordered_roles[first_index + 1 :]:
                pairwise_protected = min(
                    pairwise_protected,
                    *(
                        _distance(
                            sample_trajectory(
                                trajectories[first_role],
                                maximum_duration * index / sample_count,
                            ).position_m,
                            sample_trajectory(
                                trajectories[second_role],
                                maximum_duration * index / sample_count,
                            ).position_m,
                        )
                        - policy.required_pairwise_center_separation_m
                        for index in range(sample_count + 1)
                    ),
                )
    audit_by_role = {audit.trajectory_sha256: audit for audit in trajectory_set.audits}
    violations: list[str] = []
    if start_position_error > 1e-9:
        violations.append("CUTOVER_POSITION_DISCONTINUITY")
    if start_velocity_error > 1e-9:
        violations.append("CUTOVER_VELOCITY_DISCONTINUITY")
    if start_acceleration_error > 1e-9:
        violations.append("CUTOVER_ACCELERATION_DISCONTINUITY")
    if maximum_spacing > 0.01 + 1e-6:
        violations.append("SWEPT_SAMPLE_SPACING_EXCEEDED")
    if solid_protected < -1e-9:
        violations.append("SOLID_PROTECTED_CLEARANCE_VIOLATION")
    if boundary_protected < -1e-9:
        violations.append("BOUNDARY_PROTECTED_CLEARANCE_VIOLATION")
    if pairwise_protected < -1e-9:
        violations.append("PAIRWISE_PROTECTED_CLEARANCE_VIOLATION")
    for role_id, trajectory in trajectories.items():
        audit = audit_by_role.get(trajectory.sha256)
        if audit is None or not audit.passed:
            violations.append(f"DYNAMICS_AUDIT_FAILED:{role_id}")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "verifier_id": "independent-moving-cutover-v1",
        "replacement_case_sha256": case.case_sha256,
        "observation_sha256_by_role": {
            role_id: observations[role_id].observation_sha256 for role_id in sorted(observations)
        },
        "observation_source_timestamp_s_by_role": {
            role_id: observations[role_id].source_timestamp_s for role_id in sorted(observations)
        },
        "trajectory_sha256_by_role": {
            role_id: trajectories[role_id].sha256 for role_id in sorted(trajectories)
        },
        "dynamics_audit_sha256_by_role": {
            role_id: canonical_sha256(audit_by_role[trajectories[role_id].sha256])
            for role_id in sorted(trajectories)
        },
        "sample_step_s": sample_step_s,
        "maximum_sample_spacing_m": maximum_spacing,
        "maximum_start_position_error_m": start_position_error,
        "maximum_start_velocity_error_m_s": start_velocity_error,
        "maximum_start_acceleration_error_m_s2": start_acceleration_error,
        "minimum_solid_protected_clearance_m": solid_protected,
        "minimum_boundary_protected_clearance_m": boundary_protected,
        "minimum_pairwise_protected_clearance_m": pairwise_protected,
        "violations": tuple(sorted(set(violations))),
        "passed": not violations,
    }
    return MovingCutoverCertificate(
        **payload,
        certificate_sha256=canonical_sha256(payload),
    )


def _boundary_clearance(
    point: Vector3,
    volume: Region3D,
    *,
    horizontal_margin_m: float,
    vertical_margin_m: float,
) -> float:
    return min(
        point.x - volume.minimum_m.x - horizontal_margin_m,
        volume.maximum_m.x - point.x - horizontal_margin_m,
        point.y - volume.minimum_m.y - horizontal_margin_m,
        volume.maximum_m.y - point.y - horizontal_margin_m,
        point.z - volume.minimum_m.z - vertical_margin_m,
        volume.maximum_m.z - point.z - vertical_margin_m,
    )


def commit_changed_world_replacement(
    proposal: ChangedWorldReplanProposal,
    *,
    coordinator: InFlightReplanCoordinator,
    decision_time_source_s: float,
    queue_latency_s: float,
    acknowledgement_latency_s: float,
    cutover_guard_s: float,
    safe_prefix_certificate: SafePrefixCertificate,
    old_epoch: int,
    old_reservation_sha256: str,
    preparation_receipts: tuple[TrajectoryReplacementPreparationReceipt, ...],
) -> DynamicFleetReplanDecision:
    """Commit only with independently derived safety and exact Supervisor receipts."""

    role_ids = frozenset(item.role_id for item in proposal.route_authorities)
    expected_active = tuple(
        item.old_trajectory_sha256
        for item in sorted(proposal.route_authorities, key=lambda item: item.role_id)
    )
    if safe_prefix_certificate.case_sha256 != proposal.original_case_sha256:
        raise ValueError("safe-prefix certificate belongs to another case")
    if safe_prefix_certificate.event_sha256 != canonical_sha256(proposal.event):
        raise ValueError("safe-prefix certificate event identity mismatch")
    if safe_prefix_certificate.old_world_sha256 != proposal.old_world_sha256:
        raise ValueError("safe-prefix certificate old-world identity mismatch")
    if safe_prefix_certificate.active_trajectory_sha256s != expected_active:
        raise ValueError("safe-prefix certificate active trajectory mismatch")
    if not safe_prefix_certificate.passed or (
        safe_prefix_certificate.fallback_command
        is SafeFallbackCommand.UNQUALIFIED_EMERGENCY_FALLBACK
    ):
        raise ValueError("safe-prefix certificate has no qualified fallback")
    receipt_by_role = {receipt.role_id: receipt for receipt in preparation_receipts}
    if len(receipt_by_role) != len(preparation_receipts) or frozenset(receipt_by_role) != role_ids:
        raise ValueError("exactly one preparation receipt is required for every affected role")
    authority_by_role = {item.role_id: item for item in proposal.route_authorities}
    for role_id in sorted(role_ids):
        authority = authority_by_role[role_id]
        receipt = receipt_by_role[role_id]
        if (
            receipt.proposal_sha256 != proposal.proposal_sha256
            or receipt.safe_prefix_certificate_sha256 != safe_prefix_certificate.certificate_sha256
            or receipt.active_trajectory_sha256 != authority.old_trajectory_sha256
            or receipt.replacement_trajectory_sha256 != authority.replacement_trajectory_sha256
            or receipt.replacement_plan_sha256 != authority.replacement_plan_sha256
            or receipt.replacement_authority_sha256 != authority.authority_sha256
            or not receipt.cancellation_acknowledged
            or not receipt.replacement_acknowledged
            or not receipt.fallback_acknowledged
            or receipt.dispatch_started
        ):
            raise ValueError(f"preparation receipt identity mismatch for {role_id}")

    replacements = tuple(
        FleetRouteReplacement(
            role_id=item.role_id,
            old_trajectory_sha256=item.old_trajectory_sha256,
            replacement_trajectory_sha256=item.replacement_trajectory_sha256,
            replacement_plan_sha256=item.replacement_plan_sha256,
            feasible=True,
            cancellation_acknowledged=receipt_by_role[item.role_id].cancellation_acknowledged,
            replacement_acknowledged=receipt_by_role[item.role_id].replacement_acknowledged,
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
        old_epoch_safe_until_source_s=safe_prefix_certificate.safe_until_source_s,
        old_epoch_still_safe=(
            safe_prefix_certificate.fallback_command is SafeFallbackCommand.STOP_AND_HOLD
        ),
        old_epoch=old_epoch,
        old_reservation_sha256=old_reservation_sha256,
        old_world_sha256=proposal.old_world_sha256,
        replacement_world_sha256=proposal.replacement_world_sha256,
        replacements=replacements,
        feasibility_certificate_sha256s=tuple(
            canonical_sha256(
                [item.feasibility_certificate_sha256, safe_prefix_certificate.certificate_sha256]
            )
            for item in proposal.route_authorities
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
        if not 1 <= case.drone_count <= 3:
            raise ValueError("dynamic replanning requires one through three drones")
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


def _in_flight_planning_package(
    source_case: CampaignCase,
    case: CampaignCase,
    submission: PlanningSubmission,
    execution_profile: ExecutionProfileSubmission,
    capability_resolution: CapabilityResolution | None,
) -> tuple[PlanningSubmission, ExecutionProfileSubmission, CapabilityResolution | None]:
    if (
        source_case.case_id != submission.case_id
        or source_case.case_sha256 != submission.case_sha256
    ):
        raise ValueError("in-flight authority source case differs from the admitted package")
    if (
        case.parent_case_sha256 != submission.case_sha256
        or "source_time_changed_world" not in case.named_variations
    ):
        raise ValueError("in-flight authority derivation requires an explicit changed-world child")
    registry_row_for_case(case)
    if case.execution.backend_profile_id not in submission.supported_backend_profile_ids:
        raise ValueError("in-flight child selected an unqualified backend")
    if (
        execution_profile.case_id != submission.case_id
        or execution_profile.case_sha256 != submission.case_sha256
        or execution_profile.submission_id != submission.execution_profile_submission_id
        or execution_profile.profile_sha256 != submission.execution_profile_sha256
    ):
        raise ValueError("in-flight authority does not match the resolved execution profile")
    if execution_profile.status is not SubmissionStatus.EXECUTABLE:
        raise ValueError("in-flight execution profile is not executable")
    if case.execution.backend_profile_id not in execution_profile.supported_backend_profile_ids:
        raise ValueError("in-flight execution profile does not support the child backend")
    expected_source_capability = resolve_package_capability_resolution(
        source_case,
        submission,
        execution_profile,
    )
    if capability_resolution is not None and capability_resolution != expected_source_capability:
        raise ValueError("in-flight capability resolution differs from the admitted package")
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
    rebound_profile = execution_profile.model_copy(
        update={
            "case_id": case.case_id,
            "case_sha256": case.case_sha256,
        }
    )
    required_solid_clearance_m = max(
        submission.clearance.required_solid_clearance_m,
        *(
            case.motion_contract_for(drone.role_id).minimum_clearance_m
            for drone in sorted(case.drones, key=lambda item: item.role_id)
        ),
    )
    rebound_submission = submission.model_copy(
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
            "execution_profile_sha256": rebound_profile.profile_sha256,
            "clearance": submission.clearance.model_copy(
                update={
                    "nominal_vehicle_radius_m": 0.055,
                    "required_solid_clearance_m": required_solid_clearance_m,
                    "uncertainty_allowance_m": max(
                        submission.clearance.uncertainty_allowance_m,
                        case.hard_constraints.position_uncertainty_m,
                    ),
                }
            ),
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
    rebound_capability = resolve_package_capability_resolution(
        case,
        rebound_submission,
        rebound_profile,
    )
    return rebound_submission, rebound_profile, rebound_capability


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
    # ``decision_time_source_s`` is sampled after queueing and planning have
    # completed.  Adding their wall latencies to the original event timestamp
    # again can push the source-clock cutover far beyond the state used to
    # certify the moving splice (especially in accelerated simulation).  Only
    # acknowledgement and the cutover guard remain after the decision sample.
    proposed_cutover_source_s = decision_time_source_s + acknowledgement_latency_s + cutover_guard_s
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


def _goal_corridor_budget_exhausted(
    result: GoalCorridorSearchResult,
) -> GoalCorridorSearchResult:
    payload = result.model_dump(mode="python", exclude={"result_sha256"})
    payload.update(
        {
            "disposition": GoalCorridorDisposition.BUDGET_EXHAUSTED,
            "path_points_m": (),
            "path_length_m": 0.0,
            "integrated_absolute_heading_change_rad": 0.0,
            "minimum_center_clearance_m": 1_000_000.0,
        }
    )
    return GoalCorridorSearchResult(
        **payload,
        result_sha256=canonical_sha256(payload),
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


def _distance_to_region(point: Vector3, region: Region3D) -> float:
    dx = max(region.minimum_m.x - point.x, 0.0, point.x - region.maximum_m.x)
    dy = max(region.minimum_m.y - point.y, 0.0, point.y - region.maximum_m.y)
    dz = max(region.minimum_m.z - point.z, 0.0, point.z - region.maximum_m.z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )


def _interpolate(start: Vector3, end: Vector3, fraction: float) -> Vector3:
    return Vector3(
        x=start.x + (end.x - start.x) * fraction,
        y=start.y + (end.y - start.y) * fraction,
        z=start.z + (end.z - start.z) * fraction,
    )
