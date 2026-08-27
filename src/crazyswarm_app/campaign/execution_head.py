from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from multiprocessing import get_context
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
    rebase_changed_world_replacement,
)
from crazyswarm_app.campaign.submissions import (
    CapabilityResolution,
    ExecutionProfileSubmission,
    PlanningSubmission,
    resolve_package_capability_resolution,
    resolve_submission,
)
from crazyswarm_app.domain.commands import TrajectoryReplacementPreparationReceipt
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
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


def _planner_worker_ready() -> None:
    """Import this module in the isolated planner process before flight events arrive."""


def _plan_changed_world_in_worker(
    case: CampaignCase,
    planning_submission: PlanningSubmission,
    execution_profile: ExecutionProfileSubmission,
    capability_resolution: CapabilityResolution | None,
    event: InFlightEnvironmentEvent,
    observations: tuple[ReplanObservation, ...],
    old_trajectories: dict[str, TimeParameterizedTrajectory],
) -> Any:
    return plan_changed_world_replacement(
        case=case,
        planning_submission=planning_submission,
        execution_profile=execution_profile,
        capability_resolution=capability_resolution,
        event=event,
        observations=observations,
        old_trajectories=old_trajectories,
    )


def _rebase_changed_world_in_worker(
    proposal: Any,
    observations: tuple[ReplanObservation, ...],
) -> Any:
    return rebase_changed_world_replacement(proposal, observations)


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
        execution_profile: ExecutionProfileSubmission | None = None,
        capability_resolution: CapabilityResolution | None = None,
        perception_source: PerceptionObservationSource | None = None,
        mission_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.case = case
        self.planning_submission = planning_submission
        self.execution_profile = execution_profile or resolve_submission(
            case,
            planning_submission.execution_profile_submission_id,
            require_executable=True,
        )
        if (
            self.execution_profile.submission_id
            != planning_submission.execution_profile_submission_id
            or self.execution_profile.profile_sha256 != planning_submission.execution_profile_sha256
        ):
            raise ValueError("execution head profile differs from its planning submission")
        expected_capability = resolve_package_capability_resolution(
            case,
            planning_submission,
            self.execution_profile,
        )
        if capability_resolution is not None and capability_resolution != expected_capability:
            raise ValueError("execution head capability differs from the resolved package")
        self.capability_resolution = capability_resolution or expected_capability
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
        self._perceived_world_state = PerceivedWorldState.empty()
        self._enabled = (
            self.perception_source is not None
            and self.perception_source.count > 0
            and 1 <= self.case.drone_count <= 3
            and self.case.replanning_authority is ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS
        )
        self._planner_executor = (
            ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
            if self._enabled
            else None
        )
        self._planner_ready: asyncio.Future[None] | None = None
        self._planner_closed = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def prepare(self) -> None:
        """Warm the isolated planner before a flying child enters freshness gates."""

        executor = self._planner_executor
        if executor is None:
            return
        if self._planner_ready is None:
            self._planner_ready = asyncio.get_running_loop().run_in_executor(
                executor,
                _planner_worker_ready,
            )
        await self._planner_ready

    async def close(self) -> None:
        """Release the isolated planner on every runtime terminal path."""

        if self._planner_closed:
            return
        self._planner_closed = True
        executor = self._planner_executor
        self._planner_executor = None
        if executor is not None:
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)

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
                    self._orchestrate_with_isolated_planner(),
                    name="campaign-changed-world-execution-head",
                )
                self._ready.set()
        await self._ready.wait()
        task = self._orchestration_task
        if task is None:  # pragma: no cover - protected by the registration barrier
            raise RuntimeError("execution head barrier opened without an orchestrator")
        try:
            await task
        finally:
            # A watchdog or outer mission cancellation may end orchestration between
            # source events. Always drain the current epoch so a late replacement
            # exception is retained instead of becoming an unobserved task failure.
            await self._finish_tasks(self._active_tasks, propagate=False)

    def trace(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "enabled": self.enabled,
            "case_sha256": self.case.case_sha256,
            "planning_submission_sha256": (self.planning_submission.planning_submission_sha256),
            "execution_profile_sha256": self.execution_profile.profile_sha256,
            "capability_resolution_sha256": (
                canonical_sha256(self.capability_resolution)
                if self.capability_resolution is not None
                else None
            ),
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

    async def _orchestrate_with_isolated_planner(self) -> None:
        executor = self._planner_executor
        if executor is None:  # pragma: no cover - protected by enabled
            raise RuntimeError("enabled execution head has no planner executor")
        # Pay the spawn/import cost while the initial admitted trajectory is already
        # being prepared, before a flying child enters the 0.25 s freshness gate.
        # CPU-heavy Pydantic validation, trajectory certification, hashing, and A*
        # then run outside the control process. ``asyncio.to_thread`` was not
        # sufficient because the GIL could starve telemetry after consecutive runs.
        await self.prepare()
        await self._orchestrate()

    async def _plan_changed_world(
        self,
        *,
        case: CampaignCase,
        planning_submission: PlanningSubmission,
        execution_profile: ExecutionProfileSubmission,
        capability_resolution: CapabilityResolution | None,
        event: InFlightEnvironmentEvent,
        observations: tuple[ReplanObservation, ...],
        old_trajectories: dict[str, TimeParameterizedTrajectory],
    ) -> Any:
        executor = self._planner_executor
        if executor is None:  # pragma: no cover - protected by enabled
            raise RuntimeError("enabled execution head has no planner executor")
        return await asyncio.get_running_loop().run_in_executor(
            executor,
            partial(
                _plan_changed_world_in_worker,
                case,
                planning_submission,
                execution_profile,
                capability_resolution,
                event,
                observations,
                old_trajectories,
            ),
        )

    async def _rebase_changed_world(
        self,
        proposal: Any,
        observations: tuple[ReplanObservation, ...],
    ) -> Any:
        executor = self._planner_executor
        if executor is None:  # pragma: no cover - protected by enabled
            raise RuntimeError("enabled execution head has no planner executor")
        return await asyncio.get_running_loop().run_in_executor(
            executor,
            partial(_rebase_changed_world_in_worker, proposal, observations),
        )

    async def _orchestrate(self) -> None:
        current_case = self.case
        current_submission = self.planning_submission
        current_profile = self.execution_profile
        current_capability = self.capability_resolution
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
            self._perceived_world_state = perceived_world
            persisted_record["perceived_world_sha256"] = perceived_world.state_sha256
            persisted_record["perceived_world_revision"] = perceived_world.revision
            event = _runtime_event(sensor_observation, self.role_ids)
            try:
                observations = await self._observe_fleet(sensor_observation)
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                self._records.append(
                    {
                        "event_id": event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "reason": f"moving cutover observation failed: {error}",
                    }
                )
                await self._execute_unqualified_emergency_fallback(
                    f"changed-world cutover could not establish a fresh observation: {error}"
                )
                raise RuntimeError("unqualified changed-world cutover fallback") from error
            safety_monitor = ChangedWorldSafetyMonitor(current_case)
            minimum_clearance_m = current_case.motion_contract_for(
                self.role_ids[0]
            ).minimum_clearance_m
            abort_route = await asyncio.to_thread(
                safety_monitor.certify_abort_route,
                observations=tuple(observations.values()),
                perceived_world_sha256=perceived_world.state_sha256,
                perceived_solids=perceived_world.solids,
                minimum_clearance_m=minimum_clearance_m,
            )
            safe_prefix = await asyncio.to_thread(
                safety_monitor.certify,
                event=event,
                observations=tuple(observations.values()),
                active_trajectories=current_trajectories,
                perceived_world_sha256=perceived_world.state_sha256,
                old_world_sha256=structured_world_from_case(current_case).world_sha256,
                minimum_clearance_m=minimum_clearance_m,
                abort_route_certificate=abort_route,
            )
            response = _response_urgency(
                observations=observations,
                perceived_solids=perceived_world.solids,
                vehicle_radius_m=0.055,
                position_uncertainty_m=current_case.hard_constraints.position_uncertainty_m,
                policy_clearance_m=minimum_clearance_m,
                maximum_acceleration_m_s2=(
                    current_case.hard_constraints.dynamics.maximum_acceleration_m_s2
                ),
                maximum_jerk_m_s3=current_case.hard_constraints.dynamics.maximum_jerk_m_s3,
            )
            self._records.append(
                {
                    "stage": "SAFE_FALLBACK_CERTIFIED",
                    "event_id": event.event_id,
                    "fallback_command": safe_prefix.fallback_command.value,
                    "safe_prefix_certificate_sha256": safe_prefix.certificate_sha256,
                    "abort_route_certificate": abort_route.model_dump(mode="json"),
                    "supervisor_command_acknowledged_role_ids": self.role_ids,
                    "cutover_observation_sha256_by_role": {
                        role_id: observations[role_id].observation_sha256
                        for role_id in self.role_ids
                    },
                    "observed_speed_m_s_by_role": {
                        role_id: _norm(observations[role_id].velocity_m_s)
                        for role_id in self.role_ids
                    },
                    "response_urgency": response,
                }
            )
            if response[
                "required_action"
            ] == "IMMEDIATE_CERTIFIED_FALLBACK" and _event_can_reduce_clearance(event.kind):
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=(
                        "perceived clearance is inside the complete protected response horizon"
                    ),
                )
                await self._finish_tasks(current_tasks, propagate=False)
                return
            try:
                proposal = await self._plan_changed_world(
                    case=current_case,
                    planning_submission=current_submission,
                    execution_profile=current_profile,
                    capability_resolution=current_capability,
                    event=event,
                    observations=tuple(observations.values()),
                    old_trajectories=dict(current_trajectories),
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

            try:
                observations = await self._observe_fleet(sensor_observation)
                try:
                    proposal = await self._rebase_changed_world(
                        proposal,
                        tuple(observations.values()),
                    )
                except ValueError as rebase_error:
                    if current_case.family != "online_obstacle_replan":
                        raise
                    stale_proposal = proposal
                    proposal = await self._plan_changed_world(
                        case=current_case,
                        planning_submission=current_submission,
                        execution_profile=current_profile,
                        capability_resolution=current_capability,
                        event=event,
                        observations=tuple(observations.values()),
                        old_trajectories=current_trajectories,
                    )
                    cumulative_planning_latency_s = (
                        stale_proposal.planning_latency_s + proposal.planning_latency_s
                    )
                    if (
                        cumulative_planning_latency_s
                        > current_case.hard_constraints.planning_budget_s
                    ):
                        raise ValueError(
                            "fresh-state replan retry exceeded the planning budget"
                        ) from rebase_error
                    proposal = proposal.model_copy(
                        update={
                            "planning_latency_s": cumulative_planning_latency_s,
                        }
                    )
                    self._records.append(
                        {
                            "stage": "FRESH_STATE_REPLAN_RETRY",
                            "event_id": event.event_id,
                            "reason": str(rebase_error),
                            "stale_proposal_sha256": stale_proposal.proposal_sha256,
                            "replacement_proposal_sha256": proposal.proposal_sha256,
                            "cumulative_planning_latency_s": (cumulative_planning_latency_s),
                        }
                    )
                abort_route = await asyncio.to_thread(
                    safety_monitor.certify_abort_route,
                    observations=tuple(observations.values()),
                    perceived_world_sha256=perceived_world.state_sha256,
                    perceived_solids=perceived_world.solids,
                    minimum_clearance_m=minimum_clearance_m,
                )
                safe_prefix = await asyncio.to_thread(
                    safety_monitor.certify,
                    event=event,
                    observations=tuple(observations.values()),
                    active_trajectories=current_trajectories,
                    perceived_world_sha256=perceived_world.state_sha256,
                    old_world_sha256=structured_world_from_case(current_case).world_sha256,
                    minimum_clearance_m=minimum_clearance_m,
                    abort_route_certificate=abort_route,
                )
                response = _response_urgency(
                    observations=observations,
                    perceived_solids=perceived_world.solids,
                    vehicle_radius_m=0.055,
                    position_uncertainty_m=(current_case.hard_constraints.position_uncertainty_m),
                    policy_clearance_m=minimum_clearance_m,
                    maximum_acceleration_m_s2=(
                        current_case.hard_constraints.dynamics.maximum_acceleration_m_s2
                    ),
                    maximum_jerk_m_s3=(current_case.hard_constraints.dynamics.maximum_jerk_m_s3),
                )
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                self._records.append(
                    {
                        "event_id": event.event_id,
                        "disposition": "SAFE_FALLBACK",
                        "proposal_sha256": proposal.proposal_sha256,
                        "safe_prefix_certificate": safe_prefix.model_dump(mode="json"),
                        "reason": f"fresh-state cutover certification failed: {error}",
                    }
                )
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=f"fresh-state cutover certification failed: {error}",
                )
                return
            self._records.append(
                {
                    "stage": "MOVING_CUTOVER_RECERTIFIED",
                    "event_id": event.event_id,
                    "proposal_sha256": proposal.proposal_sha256,
                    "moving_cutover_certificate": (
                        proposal.cutover_certificate.model_dump(mode="json")
                    ),
                    "replacement_trajectory_by_role": {
                        trajectory.role_id: trajectory.model_dump(mode="json")
                        for trajectory in proposal.trajectories.trajectories
                    },
                    "replacement_dynamics_audit_by_role": {
                        trajectory.role_id: audit.model_dump(mode="json")
                        for trajectory, audit in zip(
                            proposal.trajectories.trajectories,
                            proposal.trajectories.audits,
                            strict=True,
                        )
                    },
                    "safe_prefix_certificate_sha256": safe_prefix.certificate_sha256,
                    "cutover_observation_sha256_by_role": {
                        role_id: observations[role_id].observation_sha256
                        for role_id in self.role_ids
                    },
                    "response_urgency": response,
                }
            )
            if response[
                "required_action"
            ] == "IMMEDIATE_CERTIFIED_FALLBACK" and _event_can_reduce_clearance(event.kind):
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=("fresh cutover state entered the complete protected response horizon"),
                )
                await self._finish_tasks(current_tasks, propagate=False)
                return

            trajectory_by_role = {item.role_id: item for item in proposal.trajectories.trajectories}
            authority_by_role = {item.role_id: item for item in proposal.route_authorities}
            plan_id = f"replan-{proposal.plan.plan_sha256[:20]}"
            acknowledgement_started = time.perf_counter()
            preparation_receipts: tuple[TrajectoryReplacementPreparationReceipt, ...] = ()
            try:
                preparation_results = await asyncio.gather(
                    *(
                        self._contexts[role_id].prepare_replanned_trajectory(
                            trajectory_by_role[role_id],
                            accepted_plan_id=plan_id,
                            accepted_plan_sha256=proposal.plan.plan_sha256,
                            replacement_authority_sha256=(
                                authority_by_role[role_id].authority_sha256
                            ),
                            proposal_sha256=proposal.proposal_sha256,
                            safe_prefix_certificate_sha256=(safe_prefix.certificate_sha256),
                            active_trajectory_sha256=(current_trajectories[role_id].sha256),
                        )
                        for role_id in self.role_ids
                    ),
                    return_exceptions=True,
                )
                preparation_receipts = tuple(
                    result
                    for result in preparation_results
                    if not isinstance(result, BaseException)
                )
                preparation_errors = tuple(
                    result for result in preparation_results if isinstance(result, BaseException)
                )
                if preparation_errors:
                    raise RuntimeError(
                        f"Supervisor replacement preparation failed: {preparation_errors[0]}"
                    ) from preparation_errors[0]
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                self._discard_preparation_receipts(preparation_receipts)
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
                    preparation_receipts=preparation_receipts,
                )
            except (TypeError, ValueError, RuntimeError) as error:
                self._discard_preparation_receipts(preparation_receipts)
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
                "supervisor_preparation_receipt_by_role": {
                    receipt.role_id: {
                        **receipt.model_dump(mode="json"),
                        "receipt_sha256": receipt.receipt_sha256,
                    }
                    for receipt in preparation_receipts
                },
                "replacement_dispatch_started_role_ids": (),
                "execution_disposition": "NOT_DISPATCHED",
                "planning_latency_s": proposal.planning_latency_s,
                "reaction_horizon": decision.reaction_horizon.model_dump(mode="json"),
                "safe_prefix_certificate": safe_prefix.model_dump(mode="json"),
                "reason": decision.reason,
            }
            self._records.append(record)
            if decision.disposition is not DynamicReplanDisposition.ACCEPTED:
                self._discard_preparation_receipts(preparation_receipts)
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=f"replacement rejected: {decision.reason}",
                )
                return
            try:
                await self._advance_fleet_to(decision.reaction_horizon.proposed_cutover_source_s)
            except (CrazySwarmError, TypeError, ValueError, RuntimeError) as error:
                self._discard_preparation_receipts(preparation_receipts)
                record["execution_disposition"] = "POST_COMMIT_SAFE_FALLBACK"
                record["reason"] = f"shared cutover advance failed: {error}"
                await self._execute_certified_fallback(
                    safe_prefix,
                    reason=record["reason"],
                )
                return
            previous_tasks = current_tasks
            current_tasks = {
                role_id: asyncio.create_task(
                    self._contexts[role_id].execute_replanned_trajectory(
                        trajectory_by_role[role_id],
                        accepted_plan_id=plan_id,
                        accepted_plan_sha256=proposal.plan.plan_sha256,
                        replacement_authority_sha256=(authority_by_role[role_id].authority_sha256),
                        proposal_sha256=proposal.proposal_sha256,
                        preparation_receipt=next(
                            receipt
                            for receipt in preparation_receipts
                            if receipt.role_id == role_id
                        ),
                    ),
                    name=f"campaign-replacement-epoch-{epoch + 1}-{role_id}",
                )
                for role_id in self.role_ids
            }
            self._active_tasks = current_tasks
            await asyncio.sleep(0)
            await self._finish_tasks(previous_tasks, propagate=False)
            immediate_failures = [
                task.exception()
                for task in current_tasks.values()
                if task.done() and not task.cancelled() and task.exception() is not None
            ]
            if immediate_failures:
                self._discard_preparation_receipts(preparation_receipts)
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
            current_profile = proposal.execution_profile
            current_capability = proposal.capability_resolution
            current_trajectories = trajectory_by_role
            epoch += 1
            fleet_decision = decision.fleet_decision
            if fleet_decision is None or fleet_decision.replacement_epoch is None:
                raise RuntimeError("accepted dynamic decision lacks a replacement epoch")
            reservation_sha = fleet_decision.replacement_epoch.replacement_reservation_sha256
        await self._finish_tasks(current_tasks, propagate=True)

    def _discard_preparation_receipts(self, receipts: tuple[Any, ...]) -> None:
        for receipt in receipts:
            context = self._contexts.get(receipt.role_id)
            if context is not None:
                context.discard_replanned_trajectory_preparation(receipt)

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
            telemetry = context.supervisor.session(context.vehicle_id).telemetry
            if telemetry is None:
                sample = await context.observe(timeout_s=0.5)
                source_timestamp_s = sample.source_timestamp_s
            else:
                source_timestamp_s = telemetry.source_timestamp_s
            if source_timestamp_s >= target_source_s:
                return source_timestamp_s
            if all(task.done() for task in self._active_tasks.values()):
                return source_timestamp_s
            # Runtime telemetry and the mission watchdog already maintain this
            # canonical cache. Polling vehicle.snapshot() in a zero-sleep loop added
            # tens of thousands of duplicate full observations to each evidence
            # bundle and competed with the 100 Hz control path.
            await asyncio.sleep(min(0.01, max(0.001, target_source_s - source_timestamp_s)))

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
        if command is SafeFallbackCommand.STOP_AND_HOLD:
            await asyncio.gather(
                *(
                    self._contexts[role_id].stop_and_hold_for_replan(reason=reason)
                    for role_id in self.role_ids
                )
            )
        elif command is SafeFallbackCommand.ABORT_AND_LAND:
            assert certificate.fallback_route_sha256 is not None
            landing_targets = {
                drone.role_id: Vector3(
                    x=drone.landing_region.center_m.x,
                    y=drone.landing_region.center_m.y,
                    z=0.0,
                )
                for drone in self.case.drones
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
        terminal_route_certificate: Any | None = None
        if command is SafeFallbackCommand.STOP_AND_HOLD:
            replan_observations = tuple(
                ReplanObservation.create(
                    observation_id=(
                        f"terminal-hold.{certificate.certificate_sha256[:12]}."
                        f"{role_id}.{observation.sequence}"
                    ),
                    role_id=role_id,
                    source_timestamp_s=observation.source_timestamp_s,
                    captured_at_source_s=observation.source_timestamp_s,
                    position_m=observation.estimated_position_m,
                    velocity_m_s=observation.velocity_m_s or Vector3(),
                    acceleration_m_s2=Vector3(),
                )
                for role_id, observation in zip(self.role_ids, observations, strict=True)
                if observation.valid and observation.estimated_position_m is not None
            )
            if len(replan_observations) != len(self.role_ids):
                await self._execute_unqualified_emergency_fallback(
                    "certified hold lacked a fresh state for terminal-route certification"
                )
                raise RuntimeError("certified hold terminal observation is unavailable")
            terminal_targets = {
                item.role_id: Vector3(
                    x=item.position_m.x,
                    y=item.position_m.y,
                    z=0.0,
                )
                for item in replan_observations
            }
            terminal_route_certificate = ChangedWorldSafetyMonitor(self.case).certify_abort_route(
                observations=replan_observations,
                perceived_world_sha256=self._perceived_world_state.state_sha256,
                perceived_solids=self._perceived_world_state.solids,
                minimum_clearance_m=self.case.motion_contract_for(
                    self.role_ids[0]
                ).minimum_clearance_m,
                landing_targets_by_role=terminal_targets,
            )
            if not terminal_route_certificate.passed:
                self._records.append(
                    {
                        "stage": "TERMINAL_ROUTE_REJECTED",
                        "safe_prefix_certificate_sha256": certificate.certificate_sha256,
                        "terminal_route_certificate": terminal_route_certificate.model_dump(
                            mode="json"
                        ),
                        "reason": "stationary vertical landing route was not certified",
                    }
                )
                await self._execute_unqualified_emergency_fallback(
                    "stationary vertical landing route was not certified"
                )
                raise RuntimeError("certified hold has no terminal landing route")
            await asyncio.gather(
                *(
                    self._contexts[role_id].certified_abort_and_land_for_replan(
                        target_position_m=terminal_targets[role_id],
                        certificate_sha256=terminal_route_certificate.certificate_sha256,
                        reason=("accepted program terminated after certified changed-world hold"),
                    )
                    for role_id in self.role_ids
                )
            )
            self._records.append(
                {
                    "stage": "TERMINAL_CERTIFIED_VERTICAL_LANDING_EXECUTED",
                    "safe_prefix_certificate_sha256": certificate.certificate_sha256,
                    "terminal_route_certificate": terminal_route_certificate.model_dump(
                        mode="json"
                    ),
                    "target_position_m_by_role": {
                        role_id: target.model_dump(mode="json")
                        for role_id, target in terminal_targets.items()
                    },
                }
            )
        raise CrazySwarmError(
            ErrorCode.INVALID_STATE,
            "accepted execution program terminated by a certified changed-world fallback",
            details={
                "fallback_command": command.value,
                "safe_prefix_certificate_sha256": certificate.certificate_sha256,
                "terminal_route_certificate_sha256": (
                    terminal_route_certificate.certificate_sha256
                    if terminal_route_certificate is not None
                    else certificate.fallback_route_sha256
                ),
                "recovery_already_completed": True,
            },
        )

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
        world_generation=observation.world_revision,
    )


async def _advance_context_to(
    context: MissionContext,
    target_source_s: float,
) -> None:
    while True:
        telemetry = context.supervisor.session(context.vehicle_id).telemetry
        if telemetry is None:
            sample = await context.observe(timeout_s=0.5)
            source_timestamp_s = sample.source_timestamp_s
        else:
            source_timestamp_s = telemetry.source_timestamp_s
        remaining_s = target_source_s - source_timestamp_s
        if remaining_s <= 0.0:
            return
        await asyncio.sleep(min(0.01, max(0.001, remaining_s)))


def _event_can_reduce_clearance(kind: DynamicEventKind) -> bool:
    """Return whether the changed-world event can invalidate the active path.

    Removing an obstacle or opening a passage cannot make the already certified
    active trajectory less safe.  A close, unrelated retained solid must not turn
    that beneficial update into an emergency stop; it remains part of the world
    used for the normal replacement certificate.
    """

    return kind not in {
        DynamicEventKind.OBSTACLE_REMOVED,
        DynamicEventKind.PASSAGE_OPENED,
    }


def _response_urgency(
    *,
    observations: Mapping[str, ReplanObservation],
    perceived_solids: Mapping[str, Any],
    vehicle_radius_m: float,
    position_uncertainty_m: float,
    policy_clearance_m: float,
    maximum_acceleration_m_s2: float,
    maximum_jerk_m_s3: float,
) -> dict[str, Any]:
    speed_m_s = max((_norm(item.velocity_m_s) for item in observations.values()), default=0.0)
    surface_distance_m = min(
        (
            _distance_to_region(item.position_m, solid)
            for item in observations.values()
            for solid in perceived_solids.values()
        ),
        default=1_000_000.0,
    )
    stop_time_s, stop_distance_m = _jerk_limited_stop(
        speed_m_s,
        maximum_acceleration_m_s2,
        maximum_jerk_m_s3,
    )
    latency_s = 0.12 + 0.02 + 0.50 + 0.0006 + 0.0994
    response_distance_m = speed_m_s * latency_s + stop_distance_m
    required_distance_m = (
        vehicle_radius_m + position_uncertainty_m + policy_clearance_m + response_distance_m
    )
    margin_m = surface_distance_m - required_distance_m
    urgency = max(0.0, min(1.0, 1.0 - margin_m / 0.25))
    action = (
        "IMMEDIATE_CERTIFIED_FALLBACK"
        if margin_m < 0.0
        else "MOVING_DECELERATE_AND_TURN"
        if urgency > 0.0
        else "MOVING_REPLAN"
    )
    return {
        "speed_m_s": speed_m_s,
        "perceived_center_to_surface_distance_m": surface_distance_m,
        "complete_latency_s": latency_s,
        "jerk_limited_stop_time_s": stop_time_s,
        "jerk_limited_stop_distance_m": stop_distance_m,
        "response_distance_m": response_distance_m,
        "required_center_to_surface_distance_m": required_distance_m,
        "margin_m": margin_m,
        "urgency_0_to_1": urgency,
        "required_action": action,
    }


def _jerk_limited_stop(
    speed_m_s: float,
    maximum_acceleration_m_s2: float,
    maximum_jerk_m_s3: float,
) -> tuple[float, float]:
    if speed_m_s <= 0.0:
        return 0.0, 0.0
    ramp_s = maximum_acceleration_m_s2 / maximum_jerk_m_s3
    ramp_velocity_delta = 0.5 * maximum_acceleration_m_s2 * ramp_s
    if speed_m_s <= 2.0 * ramp_velocity_delta:
        triangular_ramp_s = math.sqrt(speed_m_s / maximum_jerk_m_s3)
        return 2.0 * triangular_ramp_s, speed_m_s * triangular_ramp_s
    hold_s = (speed_m_s - 2.0 * ramp_velocity_delta) / maximum_acceleration_m_s2
    first_distance = speed_m_s * ramp_s - maximum_jerk_m_s3 * ramp_s**3 / 6.0
    first_end_speed = speed_m_s - ramp_velocity_delta
    hold_distance = first_end_speed * hold_s - 0.5 * maximum_acceleration_m_s2 * hold_s**2
    final_distance = (
        ramp_velocity_delta * ramp_s
        - 0.5 * maximum_acceleration_m_s2 * ramp_s**2
        + maximum_jerk_m_s3 * ramp_s**3 / 6.0
    )
    return 2.0 * ramp_s + hold_s, first_distance + hold_distance + final_distance


def _distance_to_region(point: Vector3, region: Any) -> float:
    dx = max(region.minimum_m.x - point.x, 0.0, point.x - region.maximum_m.x)
    dy = max(region.minimum_m.y - point.y, 0.0, point.y - region.maximum_m.y)
    dz = max(region.minimum_m.z - point.z, 0.0, point.z - region.maximum_m.z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _norm(value: Vector3) -> float:
    return math.sqrt(value.x * value.x + value.y * value.y + value.z * value.z)
