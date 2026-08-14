from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from crazyswarm_app.campaign.geometry import structured_world_from_case
from crazyswarm_app.campaign.models import (
    CampaignCase,
    ReplanningAuthority,
)
from crazyswarm_app.campaign.perception import (
    PerceivedWorldState,
    PerceptionChangeKind,
    PerceptionObservation,
    PerceptionObservationSource,
)
from crazyswarm_app.campaign.replanning import (
    ChangedWorldSafetyMonitor,
    DynamicEventKind,
    DynamicReplanDisposition,
    InFlightEnvironmentEvent,
    InFlightReplanCoordinator,
    ReplanObservation,
    SafeFallbackCommand,
    SafePrefixCertificate,
    commit_changed_world_replacement,
    plan_changed_world_replacement,
)
from crazyswarm_app.campaign.submissions import PlanningSubmission
from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory
from crazyswarm_app.missions.base import MissionContext

_DYNAMIC_KIND_BY_PERCEPTION = {
    PerceptionChangeKind.SOLID_APPEARED: DynamicEventKind.OBSTACLE_ADDED,
    PerceptionChangeKind.SOLID_MOVED: DynamicEventKind.OBSTACLE_MOVED,
    PerceptionChangeKind.SOLID_DISAPPEARED: DynamicEventKind.OBSTACLE_REMOVED,
    PerceptionChangeKind.PASSAGE_CLOSED: DynamicEventKind.PASSAGE_CLOSED,
    PerceptionChangeKind.PASSAGE_OPENED: DynamicEventKind.PASSAGE_OPENED,
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
        perception_source: PerceptionObservationSource | None = None,
        mission_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.case = case
        self.planning_submission = planning_submission
        self.perception_source = perception_source
        self.mission_id = mission_id
        self.run_id = run_id
        self.role_ids = tuple(sorted(item.role_id for item in case.drones))
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._contexts: dict[str, MissionContext] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._trajectories: dict[str, TimeParameterizedTrajectory] = {}
        self._orchestration_task: asyncio.Task[None] | None = None
        self._records: list[dict[str, Any]] = []
        self._enabled = (
            self.perception_source is not None
            and self.perception_source.count > 0
            and 1 <= self.case.drone_count <= 3
            and self.case.replanning_authority is ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

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
            "planning_submission_sha256": (self.planning_submission.planning_submission_sha256),
            "observation_count": (
                len(self.perception_source.persisted_sha256s)
                if self.perception_source is not None
                else 0
            ),
            # Retain the v1 summary key for review/API consumers while records now
            # include the preceding perception and safety-certificate stages.
            "event_count": (
                len(self.perception_source.persisted_sha256s)
                if self.perception_source is not None
                else 0
            ),
            "records": tuple(self._records),
        }
        return {**payload, "trace_sha256": canonical_sha256(payload)}

    async def _orchestrate(self) -> None:
        current_case = self.case
        current_submission = self.planning_submission
        current_trajectories = dict(self._trajectories)
        current_tasks = {
            role_id: asyncio.create_task(
                self._contexts[role_id].execute_trajectory(current_trajectories[role_id]),
                name=f"campaign-old-epoch-{role_id}",
            )
            for role_id in self.role_ids
        }
        self._active_tasks = current_tasks
        coordinator = InFlightReplanCoordinator(self.case)
        epoch = 1
        reservation_sha = canonical_sha256(
            tuple(current_trajectories[role_id].sha256 for role_id in self.role_ids)
        )
        perceived_world = PerceivedWorldState.empty()
        source = self.perception_source
        if source is None:  # pragma: no cover - protected by enabled
            raise RuntimeError("enabled execution head has no perception source")
        while (pending_observation := source.peek()) is not None:
            if all(task.done() for task in current_tasks.values()):
                self._records.append(
                    {
                        "observation_id": pending_observation.observation_id,
                        "disposition": "NOT_IN_FLIGHT",
                        "reason": "the admitted route completed before perception receipt",
                    }
                )
                await self._finish_tasks(current_tasks, propagate=True)
                return
            source_now_s = await self._wait_for_source_time(
                pending_observation.received_timestamp_s
            )
            if all(task.done() for task in current_tasks.values()):
                self._records.append(
                    {
                        "observation_id": pending_observation.observation_id,
                        "disposition": "NOT_IN_FLIGHT",
                        "reason": "the admitted route completed before perception receipt",
                    }
                )
                await self._finish_tasks(current_tasks, propagate=True)
                return
            sensor_observation = source.pop_ready(source_now_s)
            if sensor_observation is None:
                raise RuntimeError("perception source did not release its due observation")
            self._validate_perception(sensor_observation, perceived_world.revision, source_now_s)
            persisted_record: dict[str, Any] = {
                "stage": "PERCEPTION_PERSISTED",
                "observation_id": sensor_observation.observation_id,
                "observation_sha256": sensor_observation.observation_sha256,
                "raw_payload_sha256": sensor_observation.raw_payload_sha256,
                "prior_perceived_world_sha256": perceived_world.state_sha256,
                "source_timestamp_s": sensor_observation.source_timestamp_s,
                "received_timestamp_s": sensor_observation.received_timestamp_s,
                "change_kind": sensor_observation.change_kind.value,
                "solid_id": sensor_observation.solid_id,
                "region": (
                    sensor_observation.region.model_dump(mode="json")
                    if sensor_observation.region is not None
                    else None
                ),
            }
            self._records.append(persisted_record)
            source.acknowledge_persisted(sensor_observation.observation_sha256)
            perceived_world = perceived_world.apply(sensor_observation)
            persisted_record["perceived_world_sha256"] = perceived_world.state_sha256
            persisted_record["perceived_world_revision"] = perceived_world.revision
            event = _runtime_event(sensor_observation, self.role_ids)
            try:
                await asyncio.gather(
                    *(
                        self._contexts[role_id].stop_and_hold_for_replan(
                            reason=f"perceived changed world {sensor_observation.observation_id}"
                        )
                        for role_id in self.role_ids
                    )
                )
                await self._finish_tasks(current_tasks, propagate=False)
                observations = await self._observe_fleet(sensor_observation)
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                self._records.append(
                    {
                        "event_id": event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "reason": f"cutover hold or observation failed: {error}",
                    }
                )
                await self._execute_unqualified_emergency_fallback(
                    f"changed-world cutover could not establish a certified hold: {error}"
                )
                raise RuntimeError("unqualified changed-world cutover fallback") from error
            safety_monitor = ChangedWorldSafetyMonitor(current_case)
            minimum_clearance_m = current_case.motion_contract_for(
                self.role_ids[0]
            ).minimum_clearance_m
            abort_route = safety_monitor.certify_abort_route(
                observations=tuple(observations.values()),
                perceived_world_sha256=perceived_world.state_sha256,
                perceived_solids=perceived_world.solids,
                minimum_clearance_m=minimum_clearance_m,
            )
            safe_prefix = safety_monitor.certify(
                event=event,
                observations=tuple(observations.values()),
                active_trajectories=current_trajectories,
                perceived_world_sha256=perceived_world.state_sha256,
                old_world_sha256=structured_world_from_case(current_case).world_sha256,
                minimum_clearance_m=minimum_clearance_m,
                abort_route_certificate=abort_route,
            )
            self._records.append(
                {
                    "stage": "SAFE_FALLBACK_CERTIFIED",
                    "event_id": event.event_id,
                    "fallback_command": safe_prefix.fallback_command.value,
                    "safe_prefix_certificate_sha256": safe_prefix.certificate_sha256,
                    "abort_route_certificate": abort_route.model_dump(mode="json"),
                    "supervisor_command_acknowledged_role_ids": self.role_ids,
                    "stopped_observation_sha256_by_role": {
                        role_id: observations[role_id].observation_sha256
                        for role_id in self.role_ids
                    },
                    "stopped_speed_m_s_by_role": {
                        role_id: _norm(observations[role_id].velocity_m_s)
                        for role_id in self.role_ids
                    },
                }
            )
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
                        "event_id": event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "safe_prefix_certificate": safe_prefix.model_dump(mode="json"),
                        "reason": str(error),
                    }
                )
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=f"changed-world planning failed: {error}",
                )
                return

            trajectory_by_role = {item.role_id: item for item in proposal.trajectories.trajectories}
            authority_by_role = {item.role_id: item for item in proposal.route_authorities}
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
                        "event_id": event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "proposal_sha256": proposal.proposal_sha256,
                        "safe_prefix_certificate": safe_prefix.model_dump(mode="json"),
                        "reason": f"replacement command validation failed: {error}",
                    }
                )
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=f"replacement command validation failed: {error}",
                )
                return
            acknowledgement_latency_s = time.perf_counter() - acknowledgement_started
            decision_source_s = max(item.captured_at_source_s for item in observations.values())
            try:
                decision = commit_changed_world_replacement(
                    proposal,
                    coordinator=coordinator,
                    decision_time_source_s=decision_source_s,
                    queue_latency_s=0.0,
                    acknowledgement_latency_s=acknowledgement_latency_s,
                    cutover_guard_s=0.10,
                    safe_prefix_certificate=safe_prefix,
                    old_epoch=epoch,
                    old_reservation_sha256=reservation_sha,
                    cancellation_acknowledged_role_ids=frozenset(self.role_ids),
                    replacement_acknowledged_role_ids=frozenset(self.role_ids),
                    fallback_acknowledged_role_ids=frozenset(self.role_ids),
                )
            except (TypeError, ValueError, RuntimeError) as error:
                self._records.append(
                    {
                        "event_id": event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "proposal_sha256": proposal.proposal_sha256,
                        "safe_prefix_certificate": safe_prefix.model_dump(mode="json"),
                        "reason": f"atomic replacement commit failed: {error}",
                    }
                )
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=f"atomic replacement commit failed: {error}",
                )
                return
            record: dict[str, Any] = {
                "event_id": event.event_id,
                "disposition": decision.disposition.value,
                "proposal_sha256": proposal.proposal_sha256,
                "decision_sha256": decision.decision_sha256,
                "plan_sha256": proposal.plan.plan_sha256,
                "replacement_world_sha256": proposal.replacement_world_sha256,
                "replacement_trajectory_sha256_by_role": {
                    role_id: trajectory_by_role[role_id].sha256 for role_id in self.role_ids
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
                "safe_prefix_certificate": safe_prefix.model_dump(mode="json"),
                "reason": decision.reason,
            }
            self._records.append(record)
            if decision.disposition is not DynamicReplanDisposition.ACCEPTED:
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=f"replacement rejected: {decision.reason}",
                )
                return
            try:
                await self._advance_fleet_to(decision.reaction_horizon.proposed_cutover_source_s)
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                record["execution_disposition"] = "POST_COMMIT_SAFE_FALLBACK"
                record["reason"] = f"shared cutover advance failed: {error}"
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=record["reason"],
                )
                return
            current_tasks = {
                role_id: asyncio.create_task(
                    self._contexts[role_id].execute_replanned_trajectory(
                        trajectory_by_role[role_id],
                        accepted_plan_id=plan_id,
                        accepted_plan_sha256=proposal.plan.plan_sha256,
                        replacement_authority_sha256=(authority_by_role[role_id].authority_sha256),
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
                record["reason"] = "replacement dispatch failed: " + str(immediate_failures[0])
                await self._finish_tasks(current_tasks, propagate=False)
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=record["reason"],
                )
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
            reservation_sha = fleet_decision.replacement_epoch.replacement_reservation_sha256
        await self._finish_tasks(current_tasks, propagate=True)

    def _validate_perception(
        self,
        observation: PerceptionObservation,
        prior_revision: int,
        source_now_s: float,
    ) -> None:
        if self.mission_id is not None and observation.mission_id != self.mission_id:
            raise ValueError("perception belongs to another mission")
        if self.run_id is not None and observation.run_id != self.run_id:
            raise ValueError("perception belongs to another run")
        if observation.vehicle_id not in self.role_ids:
            raise ValueError("perception belongs to a vehicle outside the active fleet")
        if observation.prior_perceived_world_revision != prior_revision:
            raise ValueError("perception prior-world revision is stale")
        if observation.received_timestamp_s > source_now_s + 1e-9:
            raise ValueError("future perception cannot enter planner world state")
        if source_now_s > observation.expires_source_s:
            raise ValueError("perception observation expired before planner receipt")
        if observation.confidence < 0.50:
            raise ValueError("perception confidence is below the bounded planning gate")

    async def _observe_fleet(
        self,
        observation: PerceptionObservation,
    ) -> dict[str, ReplanObservation]:
        samples = await asyncio.gather(
            *(self._contexts[role_id].observe(timeout_s=0.5) for role_id in self.role_ids)
        )
        observations: dict[str, ReplanObservation] = {}
        for role_id, sample in zip(self.role_ids, samples, strict=True):
            if not sample.valid or sample.estimated_position_m is None:
                raise ValueError(f"fresh cutover observation is unavailable for {role_id}")
            observations[role_id] = ReplanObservation.create(
                observation_id=(f"{observation.observation_id}.{role_id}.{sample.sequence}"),
                role_id=role_id,
                source_timestamp_s=sample.source_timestamp_s,
                captured_at_source_s=sample.source_timestamp_s,
                position_m=sample.estimated_position_m,
                velocity_m_s=sample.velocity_m_s or Vector3(),
                acceleration_m_s2=Vector3(),
            )
        return observations

    async def _wait_for_source_time(self, target_source_s: float) -> float:
        context = self._contexts[self.role_ids[0]]
        while True:
            sample = await context.observe(timeout_s=0.5)
            if sample.source_timestamp_s >= target_source_s:
                return sample.source_timestamp_s
            if all(task.done() for task in self._active_tasks.values()):
                return sample.source_timestamp_s
            await asyncio.sleep(0)

    async def _advance_fleet_to(self, target_source_s: float) -> None:
        await asyncio.gather(
            *(
                _advance_context_to(self._contexts[role_id], target_source_s)
                for role_id in self.role_ids
            )
        )

    async def _execute_certified_fallback(
        self,
        certificate: SafePrefixCertificate,
        *,
        reason: str,
    ) -> None:
        command = certificate.fallback_command
        if command is SafeFallbackCommand.UNQUALIFIED_EMERGENCY_FALLBACK:
            await self._execute_unqualified_emergency_fallback(reason)
            raise RuntimeError("changed-world fallback is unqualified")
        if command is SafeFallbackCommand.ABORT_AND_LAND:
            assert certificate.fallback_route_sha256 is not None
            landing_targets = {
                drone.role_id: drone.landing_region.center_m for drone in self.case.drones
            }
            await asyncio.gather(
                *(
                    self._contexts[role_id].certified_abort_and_land_for_replan(
                        target_position_m=landing_targets[role_id],
                        certificate_sha256=certificate.fallback_route_sha256,
                        reason=reason,
                    )
                    for role_id in self.role_ids
                )
            )
        observations = await asyncio.gather(
            *(self._contexts[role_id].observe(timeout_s=0.5) for role_id in self.role_ids)
        )
        stopped = all(
            observation.velocity_m_s is not None
            and _norm(observation.velocity_m_s)
            <= self.case.hard_constraints.dynamics.stop_speed_threshold_m_s + 1e-9
            for observation in observations
        )
        self._records.append(
            {
                "stage": "SAFE_FALLBACK_EXECUTED",
                "fallback_command": command.value,
                "safe_prefix_certificate_sha256": certificate.certificate_sha256,
                "supervisor_command_acknowledged_role_ids": self.role_ids,
                "observed_role_ids": self.role_ids,
                "stopped_or_landed_observation": stopped,
                "reason": reason,
            }
        )
        if not stopped:
            await self._execute_unqualified_emergency_fallback(
                "certified fallback acknowledgement lacked a stopped/landed observation"
            )
            raise RuntimeError("certified fallback could not be observed")

    async def _execute_unqualified_emergency_fallback(self, reason: str) -> None:
        results = await asyncio.gather(
            *(
                self._contexts[role_id].emergency_fallback_for_replan(reason=reason)
                for role_id in self.role_ids
            ),
            return_exceptions=True,
        )
        self._records.append(
            {
                "stage": "UNQUALIFIED_EMERGENCY_FALLBACK",
                "fallback_command": (SafeFallbackCommand.UNQUALIFIED_EMERGENCY_FALLBACK.value),
                "requested_role_ids": self.role_ids,
                "acknowledged_role_ids": tuple(
                    role_id
                    for role_id, result in zip(self.role_ids, results, strict=True)
                    if not isinstance(result, BaseException)
                ),
                "reason": reason,
            }
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
    observation: PerceptionObservation,
    role_ids: tuple[str, ...],
) -> InFlightEnvironmentEvent:
    return InFlightEnvironmentEvent(
        event_id=observation.source_event_id,
        kind=_DYNAMIC_KIND_BY_PERCEPTION[observation.change_kind],
        source_id=observation.sensor_id,
        sequence=observation.sequence,
        source_timestamp_s=observation.source_timestamp_s,
        received_source_s=observation.received_timestamp_s,
        effective_source_s=observation.effective_source_s,
        authenticated=True,
        affected_role_ids=role_ids,
        region_id=observation.solid_id,
        region=observation.region,
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


def _norm(value: Vector3) -> float:
    return (value.x * value.x + value.y * value.y + value.z * value.z) ** 0.5
