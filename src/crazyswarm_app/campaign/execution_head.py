from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from crazyswarm_app.campaign.models import (
    CampaignCase,
    ReplanningAuthority,
    ScenarioEvent,
    ScenarioEventKind,
    ScenarioExpectedDisposition,
)
from crazyswarm_app.campaign.replanning import (
    DynamicEventKind,
    DynamicReplanDisposition,
    InFlightEnvironmentEvent,
    InFlightReplanCoordinator,
    ReplanObservation,
    commit_changed_world_replacement,
    plan_changed_world_replacement,
)
from crazyswarm_app.campaign.submissions import PlanningSubmission
from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory
from crazyswarm_app.missions.base import MissionContext

_ENVIRONMENT_EVENT_KINDS = frozenset(
    {
        ScenarioEventKind.OBSTACLE_ADDED,
        ScenarioEventKind.OBSTACLE_MOVED,
        ScenarioEventKind.OBSTACLE_REMOVED,
        ScenarioEventKind.PASSAGE_CLOSED,
        ScenarioEventKind.PASSAGE_OPENED,
    }
)

_DYNAMIC_KIND_BY_SCENARIO = {
    ScenarioEventKind.OBSTACLE_ADDED: DynamicEventKind.OBSTACLE_ADDED,
    ScenarioEventKind.OBSTACLE_MOVED: DynamicEventKind.OBSTACLE_MOVED,
    ScenarioEventKind.OBSTACLE_REMOVED: DynamicEventKind.OBSTACLE_REMOVED,
    ScenarioEventKind.PASSAGE_CLOSED: DynamicEventKind.PASSAGE_CLOSED,
    ScenarioEventKind.PASSAGE_OPENED: DynamicEventKind.PASSAGE_OPENED,
}


class CampaignExecutionHead:
    """Coordinate live changed-world replacement across one admitted fleet route.

    The head deliberately sits between an accepted trajectory operation and the
    supervisor.  It can cancel all old futures to a hold, observe one source-time
    state per role, plan/certify a changed world, validate every replacement command,
    commit exactly one fleet epoch, and only then dispatch the new trajectories.
    """

    def __init__(
        self,
        *,
        case: CampaignCase,
        planning_submission: PlanningSubmission,
    ) -> None:
        self.case = case
        self.planning_submission = planning_submission
        semantics = case.semantics
        self.events = tuple(
            event
            for event in (semantics.scenario_events if semantics is not None else ())
            if event.kind in _ENVIRONMENT_EVENT_KINDS
            and event.expected_disposition is ScenarioExpectedDisposition.ACCEPTED_UPDATE
        )
        self.role_ids = tuple(sorted(item.role_id for item in case.drones))
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._contexts: dict[str, MissionContext] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._trajectories: dict[str, TimeParameterizedTrajectory] = {}
        self._orchestration_task: asyncio.Task[None] | None = None
        self._records: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return (
            bool(self.events)
            and 2 <= self.case.drone_count <= 3
            and self.case.replanning_authority
            is ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS
        )

    async def execute(
        self,
        context: MissionContext,
        trajectory: TimeParameterizedTrajectory,
    ) -> None:
        if not self.enabled:
            await context.execute_trajectory(trajectory)
            return
        if context.role_id not in self.role_ids or trajectory.role_id != context.role_id:
            raise ValueError("execution-head role and trajectory identities differ")
        async with self._lock:
            if context.role_id in self._contexts:
                raise ValueError("execution head received a duplicate role route")
            self._contexts[context.role_id] = context
            self._trajectories[context.role_id] = trajectory
            if len(self._contexts) == len(self.role_ids):
                self._orchestration_task = asyncio.create_task(
                    self._orchestrate(),
                    name="campaign-changed-world-execution-head",
                )
                self._ready.set()
        await self._ready.wait()
        task = self._orchestration_task
        if task is None:  # pragma: no cover - protected by the registration barrier
            raise RuntimeError("execution head barrier opened without an orchestrator")
        await task

    def trace(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "enabled": self.enabled,
            "case_sha256": self.case.case_sha256,
            "planning_submission_sha256": (
                self.planning_submission.planning_submission_sha256
            ),
            "event_count": len(self.events),
            "records": tuple(self._records),
        }
        return {**payload, "trace_sha256": canonical_sha256(payload)}

    async def _orchestrate(self) -> None:
        current_case = self.case
        current_submission = self.planning_submission
        current_trajectories = dict(self._trajectories)
        current_tasks = {
            role_id: asyncio.create_task(
                self._contexts[role_id].execute_trajectory(
                    current_trajectories[role_id]
                ),
                name=f"campaign-old-epoch-{role_id}",
            )
            for role_id in self.role_ids
        }
        self._active_tasks = current_tasks
        coordinator = InFlightReplanCoordinator(self.case)
        epoch = 1
        reservation_sha = canonical_sha256(
            tuple(
                current_trajectories[role_id].sha256 for role_id in self.role_ids
            )
        )
        for authored_event in self.events:
            if all(task.done() for task in current_tasks.values()):
                self._records.append(
                    {
                        "event_id": authored_event.event_id,
                        "disposition": "NOT_IN_FLIGHT",
                        "reason": "the admitted route completed before the event trigger",
                    }
                )
                await self._finish_tasks(current_tasks, propagate=True)
                return
            await self._wait_for_source_time(authored_event.trigger_time_s)
            if all(task.done() for task in current_tasks.values()):
                self._records.append(
                    {
                        "event_id": authored_event.event_id,
                        "disposition": "NOT_IN_FLIGHT",
                        "reason": "the admitted route completed before the event trigger",
                    }
                )
                await self._finish_tasks(current_tasks, propagate=True)
                return
            try:
                await asyncio.gather(
                    *(
                        self._contexts[role_id].stop_and_hold_for_replan(
                            reason=f"changed world event {authored_event.event_id}"
                        )
                        for role_id in self.role_ids
                    )
                )
                await self._finish_tasks(current_tasks, propagate=False)
                observations = await self._observe_fleet(authored_event)
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                self._records.append(
                    {
                        "event_id": authored_event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "reason": f"cutover hold or observation failed: {error}",
                    }
                )
                return
            event = _runtime_event(authored_event, observations, self.role_ids)
            try:
                proposal = await asyncio.to_thread(
                    plan_changed_world_replacement,
                    case=current_case,
                    planning_submission=current_submission,
                    event=event,
                    observations=tuple(observations.values()),
                    old_trajectories=current_trajectories,
                )
            except (TypeError, ValueError, RuntimeError) as error:
                self._records.append(
                    {
                        "event_id": authored_event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "reason": str(error),
                    }
                )
                return

            trajectory_by_role = {
                item.role_id: item for item in proposal.trajectories.trajectories
            }
            authority_by_role = {
                item.role_id: item for item in proposal.route_authorities
            }
            plan_id = f"replan-{proposal.plan.plan_sha256[:20]}"
            acknowledgement_started = time.perf_counter()
            try:
                for role_id in self.role_ids:
                    authority = authority_by_role[role_id]
                    self._contexts[role_id].validate_replanned_trajectory(
                        trajectory_by_role[role_id],
                        accepted_plan_id=plan_id,
                        accepted_plan_sha256=proposal.plan.plan_sha256,
                        replacement_authority_sha256=authority.authority_sha256,
                    )
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                self._records.append(
                    {
                        "event_id": authored_event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "proposal_sha256": proposal.proposal_sha256,
                        "reason": f"replacement command validation failed: {error}",
                    }
                )
                return
            acknowledgement_latency_s = time.perf_counter() - acknowledgement_started
            decision_source_s = max(
                item.captured_at_source_s for item in observations.values()
            )
            try:
                decision = commit_changed_world_replacement(
                    proposal,
                    coordinator=coordinator,
                    decision_time_source_s=decision_source_s,
                    queue_latency_s=0.0,
                    acknowledgement_latency_s=acknowledgement_latency_s,
                    cutover_guard_s=0.10,
                    old_epoch_safe_until_source_s=event.effective_source_s,
                    old_epoch_still_safe=True,
                    old_epoch=epoch,
                    old_reservation_sha256=reservation_sha,
                    cancellation_acknowledged_role_ids=frozenset(self.role_ids),
                    replacement_acknowledged_role_ids=frozenset(self.role_ids),
                )
            except (TypeError, ValueError, RuntimeError) as error:
                self._records.append(
                    {
                        "event_id": authored_event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "proposal_sha256": proposal.proposal_sha256,
                        "reason": f"atomic replacement commit failed: {error}",
                    }
                )
                return
            record: dict[str, Any] = {
                "event_id": authored_event.event_id,
                "disposition": decision.disposition.value,
                "proposal_sha256": proposal.proposal_sha256,
                "decision_sha256": decision.decision_sha256,
                "plan_sha256": proposal.plan.plan_sha256,
                "replacement_world_sha256": proposal.replacement_world_sha256,
                "replacement_trajectory_sha256_by_role": {
                    role_id: trajectory_by_role[role_id].sha256
                    for role_id in self.role_ids
                },
                "replacement_authority_sha256_by_role": {
                    role_id: authority_by_role[role_id].authority_sha256
                    for role_id in self.role_ids
                },
                "replacement_prepared_role_ids": self.role_ids,
                "replacement_dispatch_started_role_ids": (),
                "execution_disposition": "NOT_DISPATCHED",
                "planning_latency_s": proposal.planning_latency_s,
                "reaction_horizon": decision.reaction_horizon.model_dump(mode="json"),
                "reason": decision.reason,
            }
            self._records.append(record)
            if decision.disposition is not DynamicReplanDisposition.ACCEPTED:
                return
            try:
                await self._advance_fleet_to(
                    decision.reaction_horizon.proposed_cutover_source_s
                )
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                record["execution_disposition"] = "POST_COMMIT_SAFE_FALLBACK"
                record["reason"] = f"shared cutover advance failed: {error}"
                return
            current_tasks = {
                role_id: asyncio.create_task(
                    self._contexts[role_id].execute_replanned_trajectory(
                        trajectory_by_role[role_id],
                        accepted_plan_id=plan_id,
                        accepted_plan_sha256=proposal.plan.plan_sha256,
                        replacement_authority_sha256=(
                            authority_by_role[role_id].authority_sha256
                        ),
                        proposal_sha256=proposal.proposal_sha256,
                    ),
                    name=f"campaign-replacement-epoch-{epoch + 1}-{role_id}",
                )
                for role_id in self.role_ids
            }
            self._active_tasks = current_tasks
            await asyncio.sleep(0)
            immediate_failures = [
                task.exception()
                for task in current_tasks.values()
                if task.done() and not task.cancelled() and task.exception() is not None
            ]
            if immediate_failures:
                record["execution_disposition"] = "POST_COMMIT_SAFE_FALLBACK"
                record["reason"] = (
                    "replacement dispatch failed: " + str(immediate_failures[0])
                )
                await self._finish_tasks(current_tasks, propagate=False)
                return
            record["replacement_dispatch_started_role_ids"] = self.role_ids
            record["execution_disposition"] = "DISPATCHED"
            current_case = proposal.replacement_case
            current_submission = proposal.planning_submission
            current_trajectories = trajectory_by_role
            epoch += 1
            fleet_decision = decision.fleet_decision
            if fleet_decision is None or fleet_decision.replacement_epoch is None:
                raise RuntimeError("accepted dynamic decision lacks a replacement epoch")
            reservation_sha = (
                fleet_decision.replacement_epoch.replacement_reservation_sha256
            )
        await self._finish_tasks(current_tasks, propagate=True)

    async def _observe_fleet(
        self,
        event: ScenarioEvent,
    ) -> dict[str, ReplanObservation]:
        samples = await asyncio.gather(
            *(self._contexts[role_id].observe(timeout_s=0.5) for role_id in self.role_ids)
        )
        observations: dict[str, ReplanObservation] = {}
        for role_id, sample in zip(self.role_ids, samples, strict=True):
            if not sample.valid or sample.estimated_position_m is None:
                raise ValueError(f"fresh cutover observation is unavailable for {role_id}")
            observations[role_id] = ReplanObservation.create(
                observation_id=f"{event.event_id}.{role_id}.{sample.sequence}",
                role_id=role_id,
                source_timestamp_s=sample.source_timestamp_s,
                captured_at_source_s=sample.source_timestamp_s,
                position_m=sample.estimated_position_m,
                velocity_m_s=sample.velocity_m_s or Vector3(),
                acceleration_m_s2=Vector3(),
            )
        return observations

    async def _wait_for_source_time(self, target_source_s: float) -> None:
        context = self._contexts[self.role_ids[0]]
        while True:
            sample = await context.observe(timeout_s=0.5)
            if sample.source_timestamp_s >= target_source_s:
                return
            if all(task.done() for task in self._active_tasks.values()):
                return
            await asyncio.sleep(0)

    async def _advance_fleet_to(self, target_source_s: float) -> None:
        await asyncio.gather(
            *(
                _advance_context_to(self._contexts[role_id], target_source_s)
                for role_id in self.role_ids
            )
        )

    @staticmethod
    async def _finish_tasks(
        tasks: Mapping[str, asyncio.Task[None]],
        *,
        propagate: bool,
    ) -> None:
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        if propagate:
            failure = next(
                (item for item in results if isinstance(item, BaseException)),
                None,
            )
            if failure is not None:
                raise failure


def _runtime_event(
    event: ScenarioEvent,
    observations: Mapping[str, ReplanObservation],
    role_ids: tuple[str, ...],
) -> InFlightEnvironmentEvent:
    if event.kind not in _DYNAMIC_KIND_BY_SCENARIO or event.duration_s is None:
        raise ValueError("scenario event is not executable changed-world authority")
    received_source_s = max(
        item.captured_at_source_s for item in observations.values()
    )
    region = event.environment_region
    region_id = (
        event.update_identity
        if event.kind is ScenarioEventKind.OBSTACLE_REMOVED
        else region.region_id if region is not None else None
    )
    return InFlightEnvironmentEvent(
        event_id=event.event_id,
        kind=_DYNAMIC_KIND_BY_SCENARIO[event.kind],
        source_id=event.source_id,
        sequence=event.sequence,
        source_timestamp_s=event.trigger_time_s,
        received_source_s=max(event.trigger_time_s, received_source_s),
        effective_source_s=event.trigger_time_s + event.duration_s,
        authenticated=event.authenticated,
        affected_role_ids=role_ids,
        region_id=region_id,
        region=region,
    )


async def _advance_context_to(
    context: MissionContext,
    target_source_s: float,
) -> None:
    while True:
        sample = await context.observe(timeout_s=0.5)
        remaining_s = target_source_s - sample.source_timestamp_s
        if remaining_s <= 0.0:
            return
        await context.hover(min(0.10, remaining_s))
