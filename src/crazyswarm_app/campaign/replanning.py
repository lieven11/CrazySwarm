from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import CampaignCase, Region3D, ReplanningAuthority
from crazyswarm_app.campaign.trajectory import ContinuousCutoverTrajectory, audit_trajectory
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import TrajectoryPoint


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
            duplicate_payload = duplicate.model_dump(
                mode="python", exclude={"decision_sha256"}
            )
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
    ordered_replacements = tuple(sorted(replacements, key=lambda item: item.role_id))
    role_ids = tuple(item.role_id for item in ordered_replacements)
    if len(set(role_ids)) != len(role_ids) or len(role_ids) > case.drone_count:
        raise ValueError("affected fleet replacement roles are invalid")
    complete = all(
        item.feasible and item.cancellation_acknowledged and item.replacement_acknowledged
        for item in ordered_replacements
    )
    update_ids = tuple(item.update_id for item in ordered_updates)
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
