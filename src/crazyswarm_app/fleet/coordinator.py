from __future__ import annotations

import asyncio
import math
import time
from contextlib import suppress
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from crazyswarm_app.domain.commands import FleetCommandBinding
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    CommandSource,
    ContractModel,
    Identifier,
    Vector3,
    VehicleState,
)
from crazyswarm_app.domain.simulation import (
    SHA256,
    FleetAuthorityTransition,
    FleetAuthorityTransitionReceipt,
    canonical_sha256,
)
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.domain.trajectory import AcceptedExecutionProgram, GroundWaitExecutionOperation
from crazyswarm_app.fleet.artifacts import (
    DeploymentManifest,
    DockDefinition,
    FleetFailurePolicy,
    FleetSessionIdentity,
)
from crazyswarm_app.fleet.coordination import assess_leader_follower
from crazyswarm_app.fleet.docks import (
    DockManager,
    DockOperationState,
    DockSnapshot,
)
from crazyswarm_app.fleet.metrics import (
    FleetMetricKind,
    FleetMetricsCollector,
    FleetMetricsReport,
)
from crazyswarm_app.fleet.persistent import (
    CoverageCandidate,
    CoverageVehicleState,
    HandoverPhase,
    HandoverRecord,
    PersistentCoverageCoordinator,
    PersistentCoverageResult,
)
from crazyswarm_app.fleet.preparation import (
    FleetPreparation,
    RegistrationState,
)
from crazyswarm_app.fleet.tasks import TaskLedger, TaskRecord, TaskState
from crazyswarm_app.missions.coordination import MissionCommandGate
from crazyswarm_app.missions.models import MissionPhase, MissionResult, MissionStatus
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.planning.contracts import (
    FleetPolicyDecision,
    RecoveryAction,
    RecoveryRequest,
    RecoveryTrigger,
)
from crazyswarm_app.planning.deconfliction import FleetDeconflictionPlan
from crazyswarm_app.planning.multidrone import MultiDroneConflictPlan
from crazyswarm_app.safety.supervisor import SafetySupervisor

if TYPE_CHECKING:
    from crazyswarm_app.planning.service import PlanningBundle


class FleetStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class SeparationLevel(StrEnum):
    CLEAR = "CLEAR"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


CROSSING_SEPARATION_POLICY_ID = "crossing-warning-hold-critical-abort-v2"
GENERIC_SEPARATION_POLICY_ID = "warning-abort-later-vehicle-v1"
LEADER_LOSS_POLICY_ID = "leader-loss-land-follower-v1"
FOLLOWER_LOSS_POLICY_ID = "follower-loss-land-leader-v1"
LEADER_FOLLOWER_TRACKING_POLICY_ID = "leader-follower-global-offset-v1"
COORDINATION_INTERVENTION_BOUND_S = 0.25
CROSSING_RELEASE_MARGIN_M = 0.2
MAX_COORDINATION_OBSERVATIONS = 2_000


class FleetEvent(ContractModel):
    schema_version: Literal[1] = 1
    fleet_session_id: Identifier
    fleet_run_id: Identifier
    deployment_sha256: SHA256
    sequence: int = Field(ge=1)
    event_type: Identifier
    timestamp_monotonic_s: float = Field(ge=0.0)
    vehicle_id: Identifier | None = None
    task_id: Identifier | None = None
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class SeparationObservation(ContractModel):
    fleet_session_id: Identifier
    fleet_run_id: Identifier
    first_vehicle_id: Identifier
    second_vehicle_id: Identifier
    distance_m: float = Field(ge=0.0)
    level: SeparationLevel
    action: str
    policy_id: Identifier
    first_source_clock_id: Identifier
    first_source_clock_epoch: int = Field(ge=0)
    first_source_sequence: int = Field(ge=0)
    second_source_clock_id: Identifier
    second_source_clock_epoch: int = Field(ge=0)
    second_source_sequence: int = Field(ge=0)
    intervention_latency_s: float | None = Field(default=None, ge=0.0)
    timestamp_monotonic_s: float = Field(ge=0.0)


class LeaderFollowerObservation(ContractModel):
    fleet_session_id: Identifier
    fleet_run_id: Identifier
    leader_vehicle_id: Identifier
    follower_vehicle_id: Identifier
    expected_offset_m: Vector3
    expected_follower_position_m: Vector3
    observed_offset_m: Vector3
    relative_velocity_m_s: Vector3
    tracking_error_m: float = Field(ge=0.0)
    speed_error_m_s: float = Field(ge=0.0)
    separation_m: float = Field(ge=0.0)
    boundary_margin_m: float = Field(ge=0.0)
    leader_source_clock_id: Identifier
    leader_source_clock_epoch: int = Field(ge=0)
    leader_source_sequence: int = Field(ge=0)
    follower_source_clock_id: Identifier
    follower_source_clock_epoch: int = Field(ge=0)
    follower_source_sequence: int = Field(ge=0)
    timestamp_monotonic_s: float = Field(ge=0.0)


class FleetChildResult(ContractModel):
    task_id: Identifier
    vehicle_id: Identifier
    lease_generation: int = Field(ge=1)
    mission_result: MissionResult


class FleetResult(ContractModel):
    schema_version: Literal[1] = 1
    fleet_session_id: Identifier
    fleet_run_id: Identifier
    fleet_identity_sha256: SHA256
    deployment_sha256: SHA256
    status: FleetStatus
    reason_code: Identifier
    message: str
    child_results: tuple[FleetChildResult, ...]
    tasks: tuple[TaskRecord, ...]
    minimum_separation_m: float | None = Field(default=None, ge=0.0)
    warning_violations: int = Field(default=0, ge=0)
    critical_violations: int = Field(default=0, ge=0)
    separation_observations: tuple[SeparationObservation, ...] = ()
    leader_follower_observations: tuple[LeaderFollowerObservation, ...] = ()
    leader_loss_intervention_latency_s: float | None = Field(default=None, ge=0.0)
    coordination_policy_ids: tuple[Identifier, ...] = ()
    events: tuple[FleetEvent, ...]
    normalized_trace: tuple[dict[str, str | int | float | bool | None], ...]
    normalized_outcome_sha256: SHA256
    persistent_coverage: PersistentCoverageResult | None = None
    dock_snapshots: tuple[DockSnapshot, ...] = ()
    metrics: FleetMetricsReport | None = None
    authority_transitions: tuple[FleetAuthorityTransitionReceipt, ...] = ()
    deconfliction_plan_sha256: SHA256 | None = None
    selected_deconfliction_strategy: Identifier | None = None
    nominal_deconfliction_executed: bool | None = None


class FleetCoordinator:
    """Coordinates task ownership above independent single-vehicle MissionRunner runs."""

    def __init__(
        self,
        *,
        identity: FleetSessionIdentity,
        deployment: DeploymentManifest,
        preparation: FleetPreparation,
        supervisor: SafetySupervisor,
        mission_runner: MissionRunner,
        policy_decision: FleetPolicyDecision | None = None,
        planning_bundle: PlanningBundle | None = None,
        accepted_plan_id: str | None = None,
        accepted_plan_sha256: str | None = None,
        accepted_execution_programs: dict[str, AcceptedExecutionProgram] | None = None,
        deconfliction_plan: FleetDeconflictionPlan | MultiDroneConflictPlan | None = None,
        task_lease_duration_s: float = 10.0,
        monitor_period_s: float = 0.01,
    ) -> None:
        if identity.deployment_sha256 != deployment.sha256:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "fleet deployment hash mismatch")
        if identity.fleet_session_id != preparation.execution_session_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "fleet execution session mismatch")
        if monitor_period_s <= 0.0:
            raise ValueError("fleet monitor period must be positive")
        self.identity = identity
        self.deployment = deployment
        self.preparation = preparation
        self.supervisor = supervisor
        self.mission_runner = mission_runner
        self.policy_decision = (
            policy_decision
            if policy_decision is not None
            else (planning_bundle.fleet_policy_decision if planning_bundle is not None else None)
        )
        self.planning_bundle = planning_bundle
        self.accepted_plan_id = accepted_plan_id
        self.accepted_plan_sha256 = accepted_plan_sha256
        self.accepted_execution_programs = dict(accepted_execution_programs or {})
        self.deconfliction_plan = deconfliction_plan
        self.monitor_period_s = monitor_period_s
        persistent = (
            len(deployment.fleet) >= 3
            and len(deployment.tasks) >= 2
            and any(member.initial_role.value == "RESERVE" for member in deployment.fleet)
            and all(task.task_type == "persistent-zone-coverage" for task in deployment.tasks)
        )
        self._persistent = (
            PersistentCoverageCoordinator(
                fleet_session_id=identity.fleet_session_id,
                fleet_run_id=identity.fleet_run_id,
                deployment=deployment,
                task_lease_duration_s=max(task_lease_duration_s, 120.0),
            )
            if persistent
            else None
        )
        self.tasks = (
            self._persistent.tasks
            if self._persistent is not None
            else TaskLedger(
                fleet_session_id=identity.fleet_session_id,
                fleet_run_id=identity.fleet_run_id,
                deployment_sha256=deployment.sha256,
                definitions=deployment.tasks,
                lease_duration_s=task_lease_duration_s,
            )
        )
        self._events: list[FleetEvent] = []
        self._children: dict[str, asyncio.Task[MissionResult]] = {}
        self._child_runs: dict[str, str] = {}
        self._bindings: dict[str, FleetCommandBinding] = {}
        self._separation: list[SeparationObservation] = []
        self._intervened_pairs: set[tuple[str, str]] = set()
        self._freshness_aborted_task_ids: set[str] = set()
        self._coordination_policy_ids: set[str] = set()
        crossing_task_ids = tuple(
            sorted(
                task.task_id
                for task in deployment.tasks
                if task.task_type.startswith("crossing-route")
            )
        )
        self._crossing_task_ids = (
            frozenset(crossing_task_ids) if len(crossing_task_ids) >= 2 else frozenset()
        )
        self._command_gate = (
            MissionCommandGate(tuple(member.vehicle_id for member in deployment.fleet))
            if self._crossing_task_ids
            else None
        )
        self._crossing_holds: dict[tuple[str, str], str] = {}
        self._crossing_hold_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._crossing_confirmed_pairs: set[tuple[str, str]] = set()
        self._critical_pairs: set[tuple[str, str]] = set()
        leader_task_ids = tuple(
            task.task_id for task in deployment.tasks if task.task_type == "leader-route"
        )
        follower_task_ids = tuple(
            task.task_id for task in deployment.tasks if task.task_type == "follower-route"
        )
        self._leader_follower_task_ids: tuple[str, str] | None = (
            (leader_task_ids[0], follower_task_ids[0])
            if len(leader_task_ids) == 1 and len(follower_task_ids) == 1
            else None
        )
        self._leader_follower_observations: list[LeaderFollowerObservation] = []
        self._last_leader_follower_sources: tuple[int, int] | None = None
        self._leader_loss_policy_applied = False
        self._follower_loss_policy_applied = False
        self._leader_loss_intervention_latency_s: float | None = None
        if self._crossing_task_ids:
            self._coordination_policy_ids.add(CROSSING_SEPARATION_POLICY_ID)
        if self._leader_follower_task_ids is not None:
            self._coordination_policy_ids.update(
                {
                    LEADER_FOLLOWER_TRACKING_POLICY_ID,
                    LEADER_LOSS_POLICY_ID,
                    FOLLOWER_LOSS_POLICY_ID,
                }
            )
        self._allow_simulation_low_battery = False
        self._handover_children: dict[str, asyncio.Task[MissionResult]] = {}
        self._handover_runs: dict[str, str] = {}
        self._handover_bindings: dict[str, FleetCommandBinding] = {}
        self._handover_vehicle_ids: dict[str, str] = {}
        self._child_vehicle_ids: dict[str, str] = {}
        self._active_handover_id: str | None = None
        self._persistent_result: PersistentCoverageResult | None = None
        self._authority_transitions: list[FleetAuthorityTransitionReceipt] = []
        self._dock_manager = (
            DockManager(
                deployment.docks or (DockDefinition(dock_id="abstract-coverage-dock", capacity=1),)
            )
            if persistent
            else None
        )
        self._metrics = (
            FleetMetricsCollector(
                started_at_s=time.monotonic(),
                required_coverage_roles=len(deployment.tasks),
                warning_separation_m=deployment.constraints.warning_separation_m,
                critical_separation_m=deployment.constraints.critical_separation_m,
            )
            if persistent
            else None
        )
        for task in deployment.tasks:
            self._metric(
                FleetMetricKind.TASK_DECLARED,
                correlation_id=task.task_id,
                task_id=task.task_id,
            )
        self._emit(
            "FLEET_SESSION_CREATED",
            details=(
                {
                    "fleet_policy_plugin_id": policy_decision.policy.plugin_id,
                    "fleet_policy_version": policy_decision.policy.implementation_version,
                    "fleet_policy_decision_sha256": policy_decision.decision_sha256,
                }
                if policy_decision is not None
                else {}
            ),
        )

    async def run(
        self,
        assignments: dict[str, str],
        *,
        allow_simulation_low_battery: bool = False,
    ) -> FleetResult:
        """Run assigned deployment tasks while monitoring every child independently."""

        self._allow_simulation_low_battery = allow_simulation_low_battery
        launch_order = self._policy_launch_order(assignments)
        if self._persistent is not None:
            return await self._run_persistent(assignments)
        try:
            self.preparation.require_ready()
            self._validate_assignments(assignments)
            await self.enforce_separation(active_only=False)
            for task_id in launch_order:
                vehicle_id = assignments[task_id]
                lifecycle = self.preparation.vehicle(vehicle_id)
                telemetry = lifecycle.latest_telemetry
                record = self.tasks.assign(
                    task_id,
                    vehicle_id,
                    capabilities=self.supervisor.session(vehicle_id).vehicle.capabilities.features,
                    battery_percent=(
                        telemetry.telemetry.battery_percent if telemetry is not None else None
                    ),
                    allow_inadequate_energy=self._allow_simulation_low_battery,
                )
                observed_battery = (
                    telemetry.telemetry.battery_percent if telemetry is not None else None
                )
                required_battery = (
                    record.definition.estimated_energy_percent
                    + record.definition.energy_margin_percent
                )
                self._emit(
                    "TASK_ASSIGNED",
                    vehicle_id=vehicle_id,
                    task_id=task_id,
                    details={
                        "lease_generation": record.lease_generation,
                        "observed_battery_percent": observed_battery,
                        "required_battery_percent": required_battery,
                        "simulation_energy_override": bool(
                            self._allow_simulation_low_battery
                            and (observed_battery is None or observed_battery < required_battery)
                        ),
                    },
                )
            for task_id in launch_order:
                await self._start_child(task_id)
                program = self.accepted_execution_programs.get(task_id)
                ground_first = program is not None and isinstance(
                    program.operations[0], GroundWaitExecutionOperation
                )
                if not ground_first:
                    await self._await_sequential_launch_checkpoint(task_id)
            await self._monitor_children()
        except CrazySwarmError as error:
            self._emit(
                "FLEET_FAILED",
                details={"reason_code": error.code.value, "message": error.message},
            )
            await self._cancel_all("fleet coordination failed")
            return self._result(FleetStatus.FAILED, error.code.value, error.message)

        child_results = self._child_results()
        children_succeeded = all(
            item.mission_result.status is MissionStatus.SUCCEEDED for item in child_results
        )
        tasks_completed = all(
            record.state is TaskState.COMPLETED for record in self.tasks.records()
        )
        if children_succeeded and tasks_completed:
            status = FleetStatus.SUCCEEDED
            reason = "FLEET_COMPLETED"
            message = "all required fleet tasks completed"
        elif any(record.state is TaskState.COMPLETED for record in self.tasks.records()):
            status = FleetStatus.DEGRADED
            reason = "FLEET_PARTIAL"
            message = "healthy fleet members completed while another member stopped"
        elif any(item.mission_result.status is MissionStatus.ABORTED for item in child_results):
            status = FleetStatus.ABORTED
            reason = "FLEET_ABORTED"
            message = "fleet tasks were aborted"
        else:
            status = FleetStatus.FAILED
            reason = "FLEET_CHILD_FAILED"
            message = "fleet task execution failed"
        self._emit("FLEET_TERMINAL", details={"status": status.value})
        return self._result(status, reason, message)

    async def cancel(self, reason: str = "fleet campaign cancellation requested") -> None:
        """Cancel every child through the runner's supervised recovery path."""

        await self._cancel_all(reason)

    async def _run_persistent(self, assignments: dict[str, str]) -> FleetResult:
        assert self._persistent is not None
        try:
            self.preparation.require_ready()
            self._validate_assignments(assignments)
            await self.enforce_separation(active_only=False)
            candidates = await self._coverage_candidates()
            decisions = self._persistent.allocate_initial(
                candidates,
                allow_inadequate_energy=self._allow_simulation_low_battery,
                preferred_assignments=assignments,
            )
            allocated = {item.task_id: item.vehicle_id for item in decisions}
            if allocated != assignments:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "telemetry-derived coverage allocation changed the mission plan",
                    details={"planned": assignments, "allocated": allocated},
                )
            for decision in decisions:
                record = self.tasks.record(decision.task_id)
                required_battery = (
                    record.definition.estimated_energy_percent
                    + record.definition.energy_margin_percent
                )
                self._emit(
                    "TASK_ASSIGNED",
                    vehicle_id=decision.vehicle_id,
                    task_id=decision.task_id,
                    details={
                        "lease_generation": record.lease_generation,
                        "observed_battery_percent": decision.observed_battery_percent,
                        "required_battery_percent": required_battery,
                        "telemetry_derived": True,
                    },
                )
                self._metric(
                    FleetMetricKind.TASK_ASSIGNED,
                    correlation_id=decision.task_id,
                    vehicle_id=decision.vehicle_id,
                    task_id=decision.task_id,
                )
                self._metric(
                    FleetMetricKind.LEASE_ISSUED,
                    correlation_id=decision.task_id,
                    vehicle_id=decision.vehicle_id,
                    task_id=decision.task_id,
                )
                self._metric(
                    FleetMetricKind.ENERGY_MARGIN,
                    correlation_id=f"initial-{decision.task_id}",
                    vehicle_id=decision.vehicle_id,
                    task_id=decision.task_id,
                    value=decision.observed_battery_percent - required_battery,
                    details={"stage": "initial-allocation"},
                )
            for task_id in sorted(assignments):
                await self._start_child(task_id)
                await self._await_sequential_launch_checkpoint(task_id)

            trigger = await self._wait_for_rotation_trigger()
            if trigger is None:
                await self._monitor_children()
                self._persistent_result = self._persistent.result()
                child_results = self._child_results()
                tasks_completed = all(
                    record.state is TaskState.COMPLETED for record in self.tasks.records()
                )
                children_succeeded = all(
                    item.mission_result.status is MissionStatus.SUCCEEDED for item in child_results
                )
                if tasks_completed and children_succeeded:
                    status = FleetStatus.SUCCEEDED
                    reason = "FLEET_COMPLETED_NO_ROTATION"
                    message = "persistent coverage tasks completed without a rotation trigger"
                elif any(record.state is TaskState.COMPLETED for record in self.tasks.records()):
                    status = FleetStatus.DEGRADED
                    reason = "FLEET_PARTIAL"
                    message = "healthy coverage member completed after peer failure"
                elif any(
                    item.mission_result.status is MissionStatus.ABORTED for item in child_results
                ):
                    status = FleetStatus.ABORTED
                    reason = "FLEET_ABORTED"
                    message = "persistent coverage tasks were cancelled and stabilized"
                else:
                    status = FleetStatus.FAILED
                    reason = "FLEET_CHILD_FAILED"
                    message = "persistent coverage children failed before rotation"
                self._emit("FLEET_TERMINAL", details={"status": status.value})
                return self._result(
                    status,
                    reason,
                    message,
                )

            task_id, outgoing_vehicle_id, observed_battery = trigger
            self._record_recovery_proposal(
                RecoveryTrigger.LOW_BATTERY,
                task_id=task_id,
                vehicle_id=outgoing_vehicle_id,
                available_actions=frozenset({RecoveryAction.HANDOVER, RecoveryAction.LAND}),
                observation_current=True,
            )
            candidates = await self._coverage_candidates()
            handover = self._persistent.begin_handover(
                task_id,
                reason="LOW_ENERGY_MARGIN",
                candidates=candidates,
            )
            self._active_handover_id = handover.handover_id
            self._emit(
                "HANDOVER_DECISION",
                vehicle_id=outgoing_vehicle_id,
                task_id=task_id,
                details={
                    "handover_id": handover.handover_id,
                    "observed_battery_percent": observed_battery,
                    "phase": handover.phase.value,
                },
            )
            self._metric(
                FleetMetricKind.HANDOVER_DECISION,
                correlation_id=handover.handover_id,
                vehicle_id=outgoing_vehicle_id,
                task_id=task_id,
            )
            self._metric(
                FleetMetricKind.FAULT_DETECTED,
                correlation_id=handover.handover_id,
                vehicle_id=outgoing_vehicle_id,
                task_id=task_id,
                value=observed_battery,
                details={"reason": "LOW_ENERGY_MARGIN"},
            )
            triggered_task = self.tasks.record(task_id).definition
            self._metric(
                FleetMetricKind.ENERGY_MARGIN,
                correlation_id=handover.handover_id,
                vehicle_id=outgoing_vehicle_id,
                task_id=task_id,
                value=observed_battery
                - triggered_task.estimated_energy_percent
                - triggered_task.energy_margin_percent,
                details={"stage": "handover-trigger"},
            )
            if handover.phase is HandoverPhase.DEGRADED:
                self._metric(
                    FleetMetricKind.FAULT_DETECTED,
                    correlation_id=handover.handover_id,
                    vehicle_id=outgoing_vehicle_id,
                    task_id=task_id,
                    details={"reason": "NO_SERVICEABLE_RESERVE"},
                )
                await self._monitor_children()
                self._persistent_result = self._persistent.result()
                self._emit("FLEET_TERMINAL", details={"status": FleetStatus.DEGRADED.value})
                return self._result(
                    FleetStatus.DEGRADED,
                    "NO_SERVICEABLE_RESERVE",
                    "low energy was detected but no serviceable reserve was available",
                )

            await self._execute_persistent_handover(handover)
            self._persistent_result = self._persistent.result()
            children_succeeded = all(
                item.mission_result.status is MissionStatus.SUCCEEDED
                for item in self._child_results()
            )
            tasks_completed = all(
                record.state is TaskState.COMPLETED for record in self.tasks.records()
            )
            dock_ready = self._handover_dock_is_ready()
            status = (
                FleetStatus.SUCCEEDED
                if children_succeeded and tasks_completed and dock_ready
                else FleetStatus.FAILED
            )
            reason = (
                "PERSISTENT_HANDOVER_COMPLETED"
                if status is FleetStatus.SUCCEEDED
                else ("PERSISTENT_HANDOVER_FAILED")
            )
            message = (
                "telemetry-triggered reserve handover completed"
                if status is FleetStatus.SUCCEEDED
                else "persistent handover did not reach a safe completed state"
            )
            self._emit("FLEET_TERMINAL", details={"status": status.value})
            return self._result(status, reason, message)
        except CrazySwarmError as error:
            self._fail_active_handover(error)
            self._emit(
                "FLEET_FAILED",
                details={"reason_code": error.code.value, "message": error.message},
            )
            await self._cancel_all("persistent coverage coordination failed")
            self._persistent_result = self._persistent.result()
            return self._result(FleetStatus.FAILED, error.code.value, error.message)

    async def _wait_for_rotation_trigger(self) -> tuple[str, str, float] | None:
        while any(not child.done() for child in self._children.values()):
            await self.enforce_separation(active_only=True)
            candidates = {item.vehicle_id: item for item in await self._coverage_candidates()}
            triggered: list[tuple[float, str, str]] = []
            for record in self.tasks.records():
                task_id = record.definition.task_id
                vehicle_id = record.owner_vehicle_id
                child = self._children.get(task_id)
                if vehicle_id is None or child is None or child.done():
                    continue
                candidate = candidates[vehicle_id]
                required = (
                    record.definition.estimated_energy_percent
                    + record.definition.energy_margin_percent
                )
                threshold = min(100.0, required + 5.0)
                if candidate.armed and candidate.battery_percent <= threshold:
                    triggered.append((candidate.battery_percent, task_id, vehicle_id))
                if record.lease is not None:
                    self.tasks.renew(task_id, vehicle_id, record.lease.generation)
            if triggered:
                battery, task_id, vehicle_id = min(triggered)
                return task_id, vehicle_id, battery
            await asyncio.sleep(self.monitor_period_s)
        return None

    async def _execute_persistent_handover(self, handover: HandoverRecord) -> None:
        assert self._persistent is not None
        if handover.incoming_vehicle_id is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "handover has no selected reserve")
        task_id = handover.task_id
        incoming_vehicle_id = handover.incoming_vehicle_id
        outgoing_vehicle_id = handover.outgoing_vehicle_id
        candidates = {item.vehicle_id: item for item in await self._coverage_candidates()}
        incoming = candidates[incoming_vehicle_id]
        staging, zone_center = self._takeover_points(task_id, tuple(candidates.values()))
        run_hash = canonical_sha256(
            [self.identity.fleet_run_id, handover.handover_id, incoming_vehicle_id]
        )
        incoming_run_id = f"handover-{run_hash[:24]}"
        staging_binding = FleetCommandBinding(
            fleet_session_id=self.identity.fleet_session_id,
            fleet_run_id=self.identity.fleet_run_id,
            deployment_sha256=self.deployment.sha256,
            task_id=f"staging-{task_id}",
            task_lease_generation=1,
            backend_namespace=self.preparation.binding.binding(
                incoming_vehicle_id
            ).backend_identifier,
        )
        staging_distance = _distance(incoming.position_m, staging)
        takeover_distance = _distance(staging, zone_center)
        home = self.deployment.member(incoming_vehicle_id).home
        return_distance = _distance(zone_center, home)
        parameters = {
            "height_m": zone_center.z,
            "staging_x_m": staging.x - incoming.position_m.x,
            "staging_y_m": staging.y - incoming.position_m.y,
            "staging_move_duration_s": self._safe_move_duration(staging_distance),
            "staging_hold_s": 30.0,
            "takeover_x_m": zone_center.x - staging.x,
            "takeover_y_m": zone_center.y - staging.y,
            "takeover_move_duration_s": self._safe_move_duration(takeover_distance),
            "coverage_hold_s": 10.0,
            "return_x_m": home.x - zone_center.x,
            "return_y_m": home.y - zone_center.y,
            "return_move_duration_s": self._safe_move_duration(return_distance),
        }
        child = asyncio.create_task(
            self.mission_runner.run(
                "fleet-reserve-takeover",
                incoming_vehicle_id,
                parameters=parameters,
                mission_run_id=incoming_run_id,
                fleet_binding=staging_binding,
                mission_role_id=task_id,
                require_prepared=True,
            ),
            name=f"fleet-handover-{handover.handover_id}",
        )
        self._handover_children[handover.handover_id] = child
        self._handover_runs[handover.handover_id] = incoming_run_id
        self._handover_bindings[handover.handover_id] = staging_binding
        self._handover_vehicle_ids[handover.handover_id] = incoming_vehicle_id
        await self._wait_for_position(
            incoming_vehicle_id,
            staging,
            child,
            tolerance_m=0.12,
        )
        self._emit(
            "REPLACEMENT_LAUNCHED",
            vehicle_id=incoming_vehicle_id,
            task_id=task_id,
            details={"handover_id": handover.handover_id},
        )
        self._metric(
            FleetMetricKind.REPLACEMENT_LAUNCHED,
            correlation_id=handover.handover_id,
            vehicle_id=incoming_vehicle_id,
            task_id=task_id,
        )
        candidates_tuple = await self._coverage_candidates()
        pending = self._persistent.confirm_replacement_ready(
            handover.handover_id,
            candidates=candidates_tuple,
        )
        self._persistent.enforce_separation(candidates_tuple)
        self._emit(
            "TAKEOVER_POSITION_CONFIRMED",
            vehicle_id=incoming_vehicle_id,
            task_id=task_id,
            details={
                "handover_id": handover.handover_id,
                "x_m": staging.x,
                "y_m": staging.y,
                "z_m": staging.z,
                "separation_state": "CLEAR",
            },
        )

        outgoing_run_id = self._child_runs[task_id]
        outgoing_binding = self._bindings[task_id]
        outgoing_transition = FleetAuthorityTransition(
            transition_id=f"revoke-{handover.handover_id}",
            sequence=len(self.mission_runner.authority_receipts(outgoing_run_id)) + 1,
            vehicle_id=outgoing_vehicle_id,
            mission_run_id=outgoing_run_id,
            fleet_session_id=self.identity.fleet_session_id,
            fleet_run_id=self.identity.fleet_run_id,
            deployment_sha256=self.deployment.sha256,
            expected_task_id=outgoing_binding.task_id,
            expected_task_lease_generation=outgoing_binding.task_lease_generation,
            next_task_id=f"return-{task_id}",
            next_task_lease_generation=1,
            reason_code="TAKEOVER_READY_REVOKE_OUTGOING",
            authorization_sha256=pending.normalized_sha256,
        )
        outgoing_receipt = await self.mission_runner.transition_fleet_authority(
            outgoing_run_id,
            outgoing_transition,
        )
        self._authority_transitions.append(outgoing_receipt)
        self._metric(
            FleetMetricKind.RECOVERY_COMMAND,
            correlation_id=handover.handover_id,
            vehicle_id=outgoing_vehicle_id,
            task_id=task_id,
            details={"command": "REVOKE_TO_RETURN_AUTHORITY"},
        )
        current_outgoing = self.mission_runner.current_fleet_binding(outgoing_run_id)
        if current_outgoing is None:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "outgoing authority disappeared")
        self._bindings[task_id] = current_outgoing

        candidates_tuple = await self._coverage_candidates()
        confirmed = self._persistent.confirm_takeover(
            handover.handover_id,
            candidates=candidates_tuple,
        )
        if confirmed.incoming_lease_generation != 2:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "first reserve takeover did not issue lease generation 2",
            )
        self.tasks.start(
            task_id,
            incoming_vehicle_id,
            child_mission_run_id=incoming_run_id,
            generation=confirmed.incoming_lease_generation,
        )
        completed_handover = self._persistent.release_outgoing(handover.handover_id)
        self._emit(
            "TAKEOVER_CONFIRMED",
            vehicle_id=incoming_vehicle_id,
            task_id=task_id,
            details={
                "handover_id": handover.handover_id,
                "lease_generation": confirmed.incoming_lease_generation,
                "outgoing_vehicle_id": outgoing_vehicle_id,
            },
        )
        self._metric(
            FleetMetricKind.TAKEOVER_CONFIRMED,
            correlation_id=handover.handover_id,
            vehicle_id=incoming_vehicle_id,
            task_id=task_id,
        )
        self._metric(
            FleetMetricKind.REASSIGNED,
            correlation_id=handover.handover_id,
            vehicle_id=incoming_vehicle_id,
            task_id=task_id,
        )
        self._metric(
            FleetMetricKind.OUTGOING_RELEASED,
            correlation_id=handover.handover_id,
            vehicle_id=outgoing_vehicle_id,
            task_id=task_id,
        )
        self._metric(
            FleetMetricKind.COVERAGE_GAP_STARTED,
            correlation_id=handover.handover_id,
            task_id=task_id,
        )

        dock_reservation = None
        if self._dock_manager is not None:
            outgoing = next(
                item
                for item in await self._coverage_candidates()
                if item.vehicle_id == outgoing_vehicle_id
            )
            dock_reservation = self._dock_manager.reserve_after_handover(
                completed_handover,
                battery_percent=outgoing.battery_percent,
            )
            self._metric(
                FleetMetricKind.DOCK_QUEUED,
                correlation_id=dock_reservation.reservation_id,
                vehicle_id=outgoing_vehicle_id,
                details={"state": dock_reservation.state.value},
            )

        outgoing_result = await self._await_child_with_separation(self._children[task_id])
        if outgoing_result.status is not MissionStatus.SUCCEEDED:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "outgoing vehicle did not reach a safe landed state after revocation",
                details={
                    "mission_status": outgoing_result.status.value,
                    "reason_code": outgoing_result.reason_code,
                },
            )
        outgoing_telemetry = await self.observation_for(outgoing_vehicle_id)
        if (
            outgoing_telemetry.telemetry.armed
            or outgoing_telemetry.telemetry.flying
            or self.supervisor.session(outgoing_vehicle_id).state is not VehicleState.READY
        ):
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "outgoing vehicle did not confirm landed and disarmed",
            )
        self._emit(
            "OUTGOING_RETURNED_AND_LANDED",
            vehicle_id=outgoing_vehicle_id,
            task_id=task_id,
            details={"mission_status": outgoing_result.status.value},
        )
        self._metric(
            FleetMetricKind.STABILIZED,
            correlation_id=handover.handover_id,
            vehicle_id=outgoing_vehicle_id,
            task_id=task_id,
        )

        incoming_transition = FleetAuthorityTransition(
            transition_id=f"grant-{handover.handover_id}",
            sequence=len(self.mission_runner.authority_receipts(incoming_run_id)) + 1,
            vehicle_id=incoming_vehicle_id,
            mission_run_id=incoming_run_id,
            fleet_session_id=self.identity.fleet_session_id,
            fleet_run_id=self.identity.fleet_run_id,
            deployment_sha256=self.deployment.sha256,
            expected_task_id=staging_binding.task_id,
            expected_task_lease_generation=staging_binding.task_lease_generation,
            next_task_id=task_id,
            next_task_lease_generation=confirmed.incoming_lease_generation,
            reason_code="ATOMIC_TAKEOVER_CONFIRMED",
            authorization_sha256=confirmed.normalized_sha256,
        )
        incoming_receipt = await self.mission_runner.transition_fleet_authority(
            incoming_run_id,
            incoming_transition,
        )
        self._authority_transitions.append(incoming_receipt)
        current_incoming = self.mission_runner.current_fleet_binding(incoming_run_id)
        if current_incoming is None:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "incoming authority disappeared")
        self._handover_bindings[handover.handover_id] = current_incoming
        await self._wait_for_position(
            incoming_vehicle_id,
            zone_center,
            child,
            tolerance_m=0.15,
        )
        self._metric(
            FleetMetricKind.COVERAGE_GAP_ENDED,
            correlation_id=handover.handover_id,
            task_id=task_id,
        )

        while any(not item.done() for item in self._children.values()):
            await self.enforce_separation(active_only=True)
            await asyncio.sleep(self.monitor_period_s)
        initial_results = await asyncio.gather(*self._children.values())
        task_ids = list(self._children)
        for initial_task_id, result in zip(task_ids, initial_results, strict=True):
            if initial_task_id == task_id:
                continue
            await self._finish_task(initial_task_id, result)
        incoming_result = await child
        incoming_record = self.tasks.record(task_id)
        if incoming_result.status is MissionStatus.SUCCEEDED:
            self.tasks.update_progress(
                task_id,
                incoming_vehicle_id,
                confirmed.incoming_lease_generation,
                incoming_record.definition.completion_progress_percent,
            )
            self.tasks.complete(
                task_id,
                incoming_vehicle_id,
                confirmed.incoming_lease_generation,
            )
        else:
            self.tasks.abort(task_id, reason=incoming_result.reason_code)

        if dock_reservation is not None and self._dock_manager is not None:
            await self._complete_abstract_dock(
                dock_reservation.reservation_id,
                outgoing_vehicle_id,
            )
        self._metric(
            FleetMetricKind.HANDOVER_COMPLETED,
            correlation_id=handover.handover_id,
            vehicle_id=incoming_vehicle_id,
            task_id=task_id,
        )

    async def _complete_abstract_dock(
        self,
        reservation_id: str,
        outgoing_vehicle_id: str,
    ) -> None:
        assert self._dock_manager is not None
        reservation = self._dock_manager.reservation(reservation_id)
        if reservation.state is DockOperationState.QUEUED:
            self._emit(
                "DOCK_WAITING_FOR_CAPACITY",
                vehicle_id=outgoing_vehicle_id,
                details={"reservation_id": reservation_id},
            )
            self._metric(
                FleetMetricKind.FAULT_DETECTED,
                correlation_id=reservation_id,
                vehicle_id=outgoing_vehicle_id,
                details={"reason": "DOCK_OCCUPIED"},
            )
            return

        while reservation.state in {
            DockOperationState.RETURN_TO_DOCK_AREA,
            DockOperationState.RETRY_PENDING,
        }:
            self._dock_manager.transition(
                reservation_id,
                DockOperationState.APPROACH_REQUESTED,
                reason="Fast Sim outgoing vehicle is landed at its declared home",
            )
            self._dock_manager.transition(
                reservation_id,
                DockOperationState.DOCK_ATTEMPT,
                reason="abstract software dock attempt",
            )
            self._metric(
                FleetMetricKind.DOCK_ATTEMPT,
                correlation_id=reservation_id,
                vehicle_id=outgoing_vehicle_id,
            )
            telemetry = await self.observation_for(outgoing_vehicle_id)
            data = telemetry.telemetry
            landing_position = data.ground_truth_position_m or data.position_m
            modeled_contact = (
                landing_position is not None
                and landing_position.z <= 0.01
                and not data.armed
                and not data.flying
            )
            self._dock_manager.confirm_modeled_landing(
                reservation_id,
                modeled_contact=modeled_contact,
            )
            charging = self._dock_manager.confirm_modeled_charging(
                reservation_id,
                confirmed=(modeled_contact and "SENSOR_FAILURE" not in data.faults),
            )
            if charging.state in {
                DockOperationState.RETRY_PENDING,
                DockOperationState.FAILED,
            }:
                self._emit(
                    "DOCK_CHARGING_CONFIRMATION_FAILED",
                    vehicle_id=outgoing_vehicle_id,
                    details={
                        "reservation_id": reservation_id,
                        "state": charging.state.value,
                        "attempts": charging.attempts,
                    },
                )
                self._metric(
                    FleetMetricKind.FAULT_DETECTED,
                    correlation_id=reservation_id,
                    vehicle_id=outgoing_vehicle_id,
                    details={"reason": "CHARGING_CONFIRMATION_FAILED"},
                )
                reservation = charging
                continue
            self._metric(
                FleetMetricKind.DOCK_CHARGING,
                correlation_id=reservation_id,
                vehicle_id=outgoing_vehicle_id,
            )
            if charging.estimated_ready_at_monotonic_s is None:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "modeled charging confirmation did not provide a ready time",
                )
            self._dock_manager.update_modeled_charge(
                reservation_id,
                now_s=charging.estimated_ready_at_monotonic_s + 1.0,
            )
            self._metric(
                FleetMetricKind.DOCK_READY,
                correlation_id=reservation_id,
                vehicle_id=outgoing_vehicle_id,
            )
            return

    async def _coverage_candidates(self) -> tuple[CoverageCandidate, ...]:
        assert self._persistent is not None
        values: list[CoverageCandidate] = []
        now = time.monotonic()
        for member in self.deployment.fleet:
            session = self.supervisor.session(member.vehicle_id)
            observation_error: CrazySwarmError | None = None
            telemetry: TelemetryEnvelope | None
            try:
                telemetry = await self.observation_for(member.vehicle_id)
            except CrazySwarmError as error:
                if error.code is ErrorCode.IDENTITY_MISMATCH:
                    raise
                observation_error = error
                telemetry = session.telemetry
            if telemetry is None:
                values.append(
                    CoverageCandidate(
                        vehicle_id=member.vehicle_id,
                        capabilities=session.vehicle.capabilities.features,
                        battery_percent=0.0,
                        position_m=member.home,
                        state=self._persistent.vehicle_states[member.vehicle_id],
                        connected=False,
                        armed=False,
                        available=False,
                    )
                )
                self._emit(
                    "FLEET_OBSERVATION_UNAVAILABLE",
                    vehicle_id=member.vehicle_id,
                    details={
                        "reason_code": (
                            observation_error.code.value
                            if observation_error is not None
                            else ErrorCode.TELEMETRY_STALE.value
                        )
                    },
                )
                continue
            data = telemetry.telemetry
            received = session.telemetry_received_at_monotonic_s
            fresh = (
                observation_error is None
                and received is not None
                and now - received <= self.deployment.constraints.observation_freshness_s
            )
            position = data.position_m or member.home
            battery = data.battery_percent if data.battery_percent is not None else 0.0
            available = (
                observation_error is None
                and fresh
                and data.position_m is not None
                and data.battery_percent is not None
                and data.localization_quality_percent is not None
                and data.localization_quality_percent
                >= self.supervisor.policy.minimum_localization_quality_percent
                and session.state not in {VehicleState.DISCONNECTED, VehicleState.EMERGENCY}
            )
            values.append(
                CoverageCandidate(
                    vehicle_id=member.vehicle_id,
                    capabilities=session.vehicle.capabilities.features,
                    battery_percent=battery,
                    position_m=position,
                    state=self._persistent.vehicle_states[member.vehicle_id],
                    connected=(
                        observation_error is None
                        and session.state is not VehicleState.DISCONNECTED
                        and data.state is not VehicleState.DISCONNECTED
                    ),
                    armed=data.armed,
                    available=available,
                )
            )
            if observation_error is not None:
                self._emit(
                    "FLEET_OBSERVATION_UNAVAILABLE",
                    vehicle_id=member.vehicle_id,
                    details={"reason_code": observation_error.code.value},
                )
                self._metric(
                    FleetMetricKind.FAULT_DETECTED,
                    correlation_id=member.vehicle_id,
                    vehicle_id=member.vehicle_id,
                    details={"reason": observation_error.code.value},
                )
            self._metric(
                FleetMetricKind.TELEMETRY_SAMPLE,
                correlation_id=member.vehicle_id,
                vehicle_id=member.vehicle_id,
                value=battery,
                details={
                    "source_clock_id": telemetry.source_clock_id,
                    "source_clock_epoch": telemetry.source_clock_epoch,
                    "sequence": telemetry.sequence,
                },
            )
            if data.localization_quality_percent is not None:
                self._metric(
                    FleetMetricKind.POSITION_QUALITY,
                    correlation_id=member.vehicle_id,
                    vehicle_id=member.vehicle_id,
                    value=data.localization_quality_percent,
                )
        return tuple(values)

    def _takeover_points(
        self,
        task_id: str,
        candidates: tuple[CoverageCandidate, ...],
    ) -> tuple[Vector3, Vector3]:
        definition = self.tasks.record(task_id).definition
        zone = next(item for item in self.deployment.zones if item.zone_id == definition.zone_id)
        center = zone.geometry.center_m.model_copy(update={"z": 0.3})
        clearance = self.deployment.constraints.warning_separation_m + 0.1
        volume = self.supervisor.policy.flight_volume
        options = (
            Vector3(x=center.x, y=center.y - clearance, z=center.z),
            Vector3(x=center.x, y=center.y + clearance, z=center.z),
            Vector3(x=center.x - clearance, y=center.y, z=center.z),
            Vector3(x=center.x + clearance, y=center.y, z=center.z),
        )
        usable = [item for item in options if volume.contains(item)]
        if not usable:
            raise CrazySwarmError(
                ErrorCode.GEOFENCE_BREACH,
                "no safe takeover staging point fits the configured flight volume",
            )
        active_positions = [
            item.position_m
            for item in candidates
            if item.state is CoverageVehicleState.ACTIVE and item.available
        ]
        reserve = next(
            (
                item
                for item in candidates
                if item.state is CoverageVehicleState.HANDOVER and item.available
            ),
            None,
        )
        path_start = (
            reserve.position_m.model_copy(update={"z": center.z}) if reserve is not None else center
        )
        staging = max(
            usable,
            key=lambda point: min(
                (_point_segment_distance(active, path_start, point) for active in active_positions),
                default=float("inf"),
            ),
        )
        return staging, center

    def _safe_move_duration(self, distance_m: float) -> float:
        if distance_m <= 0.0:
            return 1.0
        speed_duration = 1.5 * distance_m / (self.supervisor.policy.max_horizontal_speed_m_s * 0.8)
        acceleration_duration = math.sqrt(
            6.0 * distance_m / (self.supervisor.policy.max_acceleration_m_s2 * 0.8)
        )
        return min(30.0, max(1.0, speed_duration, acceleration_duration))

    async def _wait_for_position(
        self,
        vehicle_id: str,
        target: Vector3,
        child: asyncio.Task[MissionResult],
        *,
        tolerance_m: float,
    ) -> None:
        while not child.done():
            await self.enforce_separation(active_only=True)
            telemetry = await self.observation_for(vehicle_id)
            position = telemetry.telemetry.position_m
            if (
                position is not None
                and telemetry.telemetry.flying
                and _distance(position, target) <= tolerance_m
            ):
                return
            await asyncio.sleep(self.monitor_period_s)
        result = await child
        raise CrazySwarmError(
            ErrorCode.INVALID_STATE,
            "reserve maneuver ended before reaching its confirmed position",
            details={"mission_status": result.status.value, "reason_code": result.reason_code},
        )

    async def _await_child_with_separation(
        self,
        child: asyncio.Task[MissionResult],
    ) -> MissionResult:
        while not child.done():
            await self.enforce_separation(active_only=True)
            await asyncio.sleep(self.monitor_period_s)
        return await child

    def _metric(
        self,
        kind: FleetMetricKind,
        *,
        correlation_id: str,
        vehicle_id: str | None = None,
        task_id: str | None = None,
        value: float | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        if self._metrics is None:
            return
        self._metrics.record(
            kind,
            timestamp_s=time.monotonic(),
            correlation_id=correlation_id,
            vehicle_id=vehicle_id,
            task_id=task_id,
            value=value,
            details=details,
        )

    def _handover_dock_is_ready(self) -> bool:
        if self._dock_manager is None:
            return False
        reservations = tuple(
            reservation
            for dock_id in sorted(self._dock_manager.definitions)
            for reservation in self._dock_manager.snapshot(dock_id).reservations
        )
        return bool(reservations) and all(
            item.state is DockOperationState.READY for item in reservations
        )

    async def abort_vehicle(self, vehicle_id: str, *, reason: str) -> None:
        """Abort exactly one active child without implicitly commanding any peer."""

        task_ids = [
            task_id
            for task_id, child_vehicle_id in self._child_vehicle_ids.items()
            if child_vehicle_id == vehicle_id and not self._children[task_id].done()
        ]
        for task_id in task_ids:
            run_id = self._child_runs.get(task_id)
            if run_id is not None:
                await self.mission_runner.cancel(run_id)
            self._emit(
                "VEHICLE_ABORT_REQUESTED",
                vehicle_id=vehicle_id,
                task_id=task_id,
                details={"reason": reason},
            )
        for handover_id, run_id in self._handover_runs.items():
            child = self._handover_children[handover_id]
            binding = self._handover_bindings[handover_id]
            if self._handover_vehicle_ids[handover_id] == vehicle_id and not child.done():
                await self.mission_runner.cancel(run_id)
                self._emit(
                    "VEHICLE_ABORT_REQUESTED",
                    vehicle_id=vehicle_id,
                    task_id=binding.task_id,
                    details={"reason": reason},
                )

    async def shutdown(self, *, reason: str = "application shutdown") -> None:
        """Terminate owned child runs without leaving command or task ownership behind."""

        if all(child.done() for child in self._children.values()) and all(
            child.done() for child in self._handover_children.values()
        ):
            return
        await self._cancel_all(reason)

    async def observation_for(self, vehicle_id: str) -> TelemetryEnvelope:
        lifecycle = self.preparation.vehicle(vehicle_id)
        if lifecycle.registration is not RegistrationState.VERIFIED:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "vehicle identity is not verified")
        telemetry = await self.supervisor.session(vehicle_id).vehicle.snapshot()
        if telemetry.vehicle_id != vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "fleet observation was cross-routed")
        self.supervisor.receive_telemetry(telemetry)
        return telemetry

    def operator_summary(self) -> dict[str, object]:
        """Return bounded, decision-free state for the high-frequency operator view."""

        distances = [item.distance_m for item in self._separation]
        persistent = self._persistent.result() if self._persistent is not None else None
        handovers = (
            [
                {
                    "handover_id": item.handover_id,
                    "task_id": item.task_id,
                    "outgoing_vehicle_id": item.outgoing_vehicle_id,
                    "incoming_vehicle_id": item.incoming_vehicle_id,
                    "phase": item.phase.value,
                    "incoming_lease_generation": item.incoming_lease_generation,
                    "takeover_confirmed": item.takeover_confirmed,
                    "reason": item.reason,
                    "release_reason": item.release_reason,
                }
                for item in persistent.handovers
            ]
            if persistent is not None
            else []
        )
        dock_snapshots = (
            [
                {
                    "dock_id": snapshot.dock_id,
                    "health": snapshot.health.value,
                    "reservations": [
                        {
                            "vehicle_id": reservation.vehicle_id,
                            "state": reservation.state.value,
                            "modeled_charging_confirmed": (reservation.modeled_charging_confirmed),
                            "terminal_reason": reservation.terminal_reason,
                        }
                        for reservation in snapshot.reservations
                    ],
                }
                for snapshot in (
                    self._dock_manager.snapshot(dock_id)
                    for dock_id in sorted(self._dock_manager.definitions)
                )
            ]
            if self._dock_manager is not None
            else []
        )
        return {
            "vehicle_states": (
                {
                    vehicle_id: state.value
                    for vehicle_id, state in sorted(self._persistent.vehicle_states.items())
                }
                if self._persistent is not None
                else {}
            ),
            "active_owners": persistent.active_owners if persistent is not None else {},
            "handovers": handovers,
            "minimum_separation_m": min(distances) if distances else None,
            "warning_violations": sum(
                item.level is SeparationLevel.WARNING for item in self._separation
            ),
            "critical_violations": sum(
                item.level is SeparationLevel.CRITICAL for item in self._separation
            ),
            "leader_follower_observation_count": len(self._leader_follower_observations),
            "leader_loss_intervention_latency_s": (self._leader_loss_intervention_latency_s),
            "coordination_policy_ids": sorted(self._coordination_policy_ids),
            "dock_snapshots": dock_snapshots,
            "authority_transition_count": len(self._authority_transitions),
        }

    async def enforce_separation(
        self, *, active_only: bool = True
    ) -> tuple[SeparationObservation, ...]:
        # Separation is a relationship between at least two vehicles. A one-drone
        # campaign previously sampled and republished a full telemetry envelope on
        # every 10 ms monitor pass even though no pair could be evaluated. Besides
        # serving no safety decision, that multiplied each retained run by roughly
        # five relative to the configured 20 Hz telemetry evidence cadence.
        if len(self.deployment.fleet) < 2:
            return ()
        samples: dict[str, TelemetryEnvelope] = {}
        launch_blocked = False
        for member in self.deployment.fleet:
            session = self.supervisor.session(member.vehicle_id)
            if active_only and session.state not in {
                VehicleState.ARMING,
                VehicleState.TAKING_OFF,
                VehicleState.FLYING,
                VehicleState.RETURNING,
                VehicleState.LANDING,
            }:
                continue
            try:
                telemetry = await self.observation_for(member.vehicle_id)
            except CrazySwarmError as error:
                if error.code is ErrorCode.IDENTITY_MISMATCH:
                    raise
                self._emit(
                    "FLEET_OBSERVATION_UNAVAILABLE",
                    vehicle_id=member.vehicle_id,
                    details={"reason_code": error.code.value},
                )
                self._metric(
                    FleetMetricKind.FAULT_DETECTED,
                    correlation_id=member.vehicle_id,
                    vehicle_id=member.vehicle_id,
                    details={"reason": error.code.value},
                )
                continue
            position = telemetry.telemetry.position_m
            if position is not None:
                samples[member.vehicle_id] = telemetry
        observations: list[SeparationObservation] = []
        vehicle_ids = sorted(samples)
        for index, first in enumerate(vehicle_ids):
            for second in vehicle_ids[index + 1 :]:
                first_sample = samples[first]
                second_sample = samples[second]
                first_position = first_sample.telemetry.position_m
                second_position = second_sample.telemetry.position_m
                if first_position is None or second_position is None:
                    continue
                distance = _distance(first_position, second_position)
                level = self._separation_level(distance)
                action = "NONE"
                policy_id = self._separation_policy_id(first, second)
                intervention_latency_s = None
                pair = (first, second)
                crossing_pair = policy_id == CROSSING_SEPARATION_POLICY_ID
                should_intervene = (
                    level is not SeparationLevel.CLEAR and pair not in self._intervened_pairs
                ) or (
                    crossing_pair
                    and level is SeparationLevel.CRITICAL
                    and pair not in self._critical_pairs
                )
                should_release = (
                    crossing_pair
                    and level is SeparationLevel.CLEAR
                    and pair in self._crossing_holds
                    and pair in self._crossing_confirmed_pairs
                    and distance
                    >= (
                        self.deployment.constraints.warning_separation_m + CROSSING_RELEASE_MARGIN_M
                    )
                )
                if should_intervene:
                    detected_at_s = time.monotonic()
                    action = await self._separation_intervention(
                        first,
                        second,
                        level,
                        policy_id=policy_id,
                    )
                    intervention_latency_s = time.monotonic() - detected_at_s
                    launch_blocked = launch_blocked or action == "BLOCK_LAUNCH"
                    self._intervened_pairs.add(pair)
                    if level is SeparationLevel.CRITICAL:
                        self._critical_pairs.add(pair)
                    self._coordination_policy_ids.add(policy_id)
                elif should_release:
                    detected_at_s = time.monotonic()
                    action = await self._release_crossing_hold(pair)
                    intervention_latency_s = time.monotonic() - detected_at_s
                    self._intervened_pairs.discard(pair)
                observation = SeparationObservation(
                    fleet_session_id=self.identity.fleet_session_id,
                    fleet_run_id=self.identity.fleet_run_id,
                    first_vehicle_id=first,
                    second_vehicle_id=second,
                    distance_m=distance,
                    level=level,
                    action=action,
                    policy_id=policy_id,
                    first_source_clock_id=first_sample.source_clock_id,
                    first_source_clock_epoch=first_sample.source_clock_epoch,
                    first_source_sequence=first_sample.sequence,
                    second_source_clock_id=second_sample.source_clock_id,
                    second_source_clock_epoch=second_sample.source_clock_epoch,
                    second_source_sequence=second_sample.sequence,
                    intervention_latency_s=intervention_latency_s,
                    timestamp_monotonic_s=time.monotonic(),
                )
                observations.append(observation)
                self._separation.append(observation)
                self._metric(
                    FleetMetricKind.SEPARATION_OBSERVED,
                    correlation_id=f"{first}:{second}",
                    value=distance,
                    details={"level": level.value, "action": action},
                )
                if action != "NONE":
                    self._emit(
                        (
                            "SEPARATION_RELEASED"
                            if action.startswith("RELEASE_")
                            else "SEPARATION_INTERVENTION"
                        ),
                        vehicle_id=second,
                        details={
                            "peer_vehicle_id": first,
                            "distance_m": distance,
                            "level": level.value,
                            "action": action,
                            "policy_id": policy_id,
                            "intervention_latency_s": intervention_latency_s,
                            "first_source_sequence": first_sample.sequence,
                            "second_source_sequence": second_sample.sequence,
                        },
                    )
        if launch_blocked:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "warning or critical separation prevents fleet launch",
            )
        return tuple(observations)

    def _validate_assignments(self, assignments: dict[str, str]) -> None:
        declared_tasks = {item.task_id for item in self.deployment.tasks}
        declared_vehicles = {item.vehicle_id for item in self.deployment.fleet}
        unknown_tasks = sorted(set(assignments) - declared_tasks)
        unknown_vehicles = sorted(set(assignments.values()) - declared_vehicles)
        duplicated_vehicles = sorted(
            vehicle_id
            for vehicle_id in set(assignments.values())
            if list(assignments.values()).count(vehicle_id) > 1
        )
        missing_tasks = sorted(declared_tasks - set(assignments))
        if (
            unknown_tasks
            or unknown_vehicles
            or duplicated_vehicles
            or (self.deployment.completion_policy.require_all_tasks and missing_tasks)
        ):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "fleet task assignments do not match the deployment",
                details={
                    "unknown_tasks": unknown_tasks,
                    "unknown_vehicles": unknown_vehicles,
                    "duplicated_vehicles": duplicated_vehicles,
                    "missing_tasks": missing_tasks,
                },
            )

    def _policy_launch_order(self, assignments: dict[str, str]) -> tuple[str, ...]:
        decision = self.policy_decision
        if decision is None:
            return tuple(sorted(assignments))
        active_roles = set(decision.active_role_ids)
        launch_roles = set(decision.launch_order)
        assignment_roles = set(assignments)
        if active_roles != assignment_roles or launch_roles != assignment_roles:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "fleet assignments do not match the accepted policy decision",
                details={
                    "assignment_roles": sorted(assignment_roles),
                    "policy_active_roles": sorted(active_roles),
                    "policy_launch_roles": sorted(launch_roles),
                },
            )
        return decision.launch_order

    def _record_recovery_proposal(
        self,
        trigger: RecoveryTrigger,
        *,
        task_id: str,
        vehicle_id: str,
        available_actions: frozenset[RecoveryAction],
        observation_current: bool,
    ) -> None:
        planning = self.planning_bundle
        if planning is None:
            return
        from crazyswarm_app.planning.builtins import default_recovery_registry
        from crazyswarm_app.planning.safety import SafetyKernel

        plugin_id = f"recovery.{trigger.value.lower().replace('_', '-')}"
        strategy = default_recovery_registry().resolve(plugin_id, "1.0.0")
        task_record = self.tasks.record(task_id)
        request = RecoveryRequest(
            request_id=f"recovery-{self.identity.fleet_run_id}-{len(self._events) + 1}",
            mission_id=self.identity.fleet_run_id,
            trigger=trigger,
            role_id=task_id,
            vehicle_id=vehicle_id,
            available_actions=available_actions,
            observation_current=observation_current,
            authority_current=task_record.owner_vehicle_id == vehicle_id,
            lease_generation=task_record.lease_generation,
            deadline_s=COORDINATION_INTERVENTION_BOUND_S,
        )
        proposal = strategy.propose(request)
        admission = SafetyKernel().authorize_recovery(
            self.supervisor.policy,
            planning.mission_intent.safety_declaration,
            request,
            proposal,
        )
        self._emit(
            "RECOVERY_PROPOSAL_EVALUATED",
            vehicle_id=vehicle_id,
            task_id=task_id,
            details={
                "trigger": trigger.value,
                "strategy_plugin_id": strategy.manifest.plugin_id,
                "strategy_version": strategy.manifest.implementation_version,
                "strategy_manifest_sha256": strategy.manifest.sha256,
                "proposal_sha256": proposal.proposal_sha256,
                "proposed_action": proposal.action.value,
                "fallback_action": proposal.fallback.value,
                "authorized": admission.authorized,
                "admission_reason": admission.reason,
            },
        )
        if not admission.authorized:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "Safety Kernel rejected the selected recovery proposal",
                details={
                    "trigger": trigger.value,
                    "strategy_plugin_id": strategy.manifest.plugin_id,
                    "reason": admission.reason,
                },
            )

    async def _start_child(self, task_id: str) -> None:
        record = self.tasks.record(task_id)
        vehicle_id = record.owner_vehicle_id
        lease = record.lease
        if vehicle_id is None or lease is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "assigned task has no current lease")
        child_hash = canonical_sha256([self.identity.fleet_run_id, task_id, lease.generation])
        child_run_id = f"child-{child_hash[:24]}"
        binding = FleetCommandBinding(
            fleet_session_id=self.identity.fleet_session_id,
            fleet_run_id=self.identity.fleet_run_id,
            deployment_sha256=self.deployment.sha256,
            task_id=task_id,
            task_lease_generation=lease.generation,
            backend_namespace=self.preparation.binding.binding(vehicle_id).backend_identifier,
        )
        self.tasks.start(
            task_id,
            vehicle_id,
            child_mission_run_id=child_run_id,
            generation=lease.generation,
        )
        self._child_runs[task_id] = child_run_id
        self._bindings[task_id] = binding
        self._child_vehicle_ids[task_id] = vehicle_id
        self._children[task_id] = asyncio.create_task(
            self.mission_runner.run(
                record.definition.mission_id,
                vehicle_id,
                parameters=record.definition.mission_parameters,
                mission_run_id=child_run_id,
                fleet_binding=binding,
                mission_role_id=task_id,
                command_gate=self._command_gate,
                require_prepared=True,
                allow_simulation_low_battery=self._allow_simulation_low_battery,
                accepted_plan_id=(
                    self.accepted_plan_id if task_id in self.accepted_execution_programs else None
                ),
                accepted_plan_sha256=(
                    self.accepted_plan_sha256
                    if task_id in self.accepted_execution_programs
                    else None
                ),
                accepted_execution_program=self.accepted_execution_programs.get(task_id),
            ),
            name=f"fleet-child-{task_id}",
        )
        self._emit(
            "CHILD_START_REQUESTED",
            vehicle_id=vehicle_id,
            task_id=task_id,
            details={"child_mission_run_id": child_run_id},
        )

    async def _await_sequential_launch_checkpoint(self, task_id: str) -> None:
        run_id = self._child_runs[task_id]
        child = self._children[task_id]
        while not child.done():
            try:
                snapshot = self.mission_runner.get_run(run_id)
            except CrazySwarmError:
                await asyncio.sleep(0)
                continue
            if snapshot.phase.value in {"TAKING_OFF", "EXECUTING", "LANDING", "COMPLETE"}:
                break
            await asyncio.sleep(0)
        self._emit("SEQUENTIAL_LAUNCH_CHECKPOINT", task_id=task_id)

    async def _monitor_children(self) -> None:
        pending = set(self._children)
        while pending:
            await self.enforce_separation(active_only=True)
            await self._monitor_leader_follower()
            await self._enforce_freshness()
            for task_id in sorted(tuple(pending)):
                child = self._children[task_id]
                record = self.tasks.record(task_id)
                if not child.done():
                    if record.owner_vehicle_id is not None and record.lease is not None:
                        now_s = time.monotonic()
                        # A 10 s task lease does not need a durable renewal event on
                        # every 10 ms fleet-monitor pass. That produced thousands of
                        # redundant records per one-drone run, retained large completed
                        # coordinator graphs, and eventually paused realtime telemetry
                        # long enough to trip the unchanged 0.25 s freshness watchdog.
                        # Renew at half-life so a blocked monitor still retains five
                        # seconds of authority margin without turning normal liveness
                        # into high-rate evidence traffic.
                        if (
                            record.lease.expires_at_monotonic_s - now_s
                            <= self.tasks.lease_duration_s / 2.0
                        ):
                            self.tasks.renew(
                                task_id,
                                record.owner_vehicle_id,
                                record.lease.generation,
                                now_s=now_s,
                            )
                    continue
                result = await child
                pending.remove(task_id)
                await self._finish_task(task_id, result)
            if pending:
                await asyncio.sleep(
                    0.0
                    if self._crossing_task_ids or self._leader_follower_task_ids is not None
                    else self.monitor_period_s
                )

    async def _enforce_freshness(self) -> None:
        now = time.monotonic()
        for task_id, child in self._children.items():
            if child.done():
                continue
            record = self.tasks.record(task_id)
            vehicle_id = record.owner_vehicle_id
            if vehicle_id is None:
                continue
            session = self.supervisor.session(vehicle_id)
            received = session.telemetry_received_at_monotonic_s
            stale = (
                received is None
                or now - received > self.deployment.constraints.observation_freshness_s
            )
            if stale and task_id not in self._freshness_aborted_task_ids:
                # The first authoritative stale decision owns recovery. Reissuing
                # abort on every 10 ms monitor pass produced dozens of competing
                # recovery commands and obscured the single watchdog cause.
                self._freshness_aborted_task_ids.add(task_id)
                await self.abort_vehicle(vehicle_id, reason="STALE_FLEET_OBSERVATION")
                self._emit(
                    "STALE_MEMBER_ABORTED",
                    vehicle_id=vehicle_id,
                    task_id=task_id,
                )

    async def _monitor_leader_follower(self) -> None:
        task_ids = self._leader_follower_task_ids
        if (
            task_ids is None
            or self._leader_loss_policy_applied
            or self._follower_loss_policy_applied
        ):
            return
        leader_task_id, follower_task_id = task_ids
        leader_record = self.tasks.record(leader_task_id)
        follower_record = self.tasks.record(follower_task_id)
        leader_vehicle_id = leader_record.owner_vehicle_id
        follower_vehicle_id = follower_record.owner_vehicle_id
        if leader_vehicle_id is None or follower_vehicle_id is None:
            return

        leader_sample, leader_reason = await self._coordination_observation(
            leader_task_id,
            leader_vehicle_id,
        )
        follower_sample, follower_reason = await self._coordination_observation(
            follower_task_id,
            follower_vehicle_id,
        )
        if leader_reason is not None and self._coordination_loss_requires_recovery(leader_task_id):
            await self._apply_leader_loss_policy(leader_reason, sample=leader_sample)
            return
        if follower_reason is not None and self._coordination_loss_requires_recovery(
            follower_task_id
        ):
            await self._apply_follower_loss_policy(follower_reason, sample=follower_sample)
            return
        if leader_sample is None or follower_sample is None:
            return
        leader_position = leader_sample.telemetry.position_m
        follower_position = follower_sample.telemetry.position_m
        if leader_position is None or follower_position is None:
            return
        source_pair = (leader_sample.sequence, follower_sample.sequence)
        if (
            source_pair == self._last_leader_follower_sources
            or len(self._leader_follower_observations) >= MAX_COORDINATION_OBSERVATIONS
        ):
            return
        self._last_leader_follower_sources = source_pair
        leader_home = self.deployment.member(leader_vehicle_id).home
        follower_home = self.deployment.member(follower_vehicle_id).home
        expected_offset = _subtract(follower_home, leader_home)
        assessment = assess_leader_follower(
            leader_position_m=leader_position,
            follower_position_m=follower_position,
            expected_offset_m=expected_offset,
            leader_velocity_m_s=leader_sample.telemetry.velocity_m_s,
            follower_velocity_m_s=follower_sample.telemetry.velocity_m_s,
        )
        observation = LeaderFollowerObservation(
            fleet_session_id=self.identity.fleet_session_id,
            fleet_run_id=self.identity.fleet_run_id,
            leader_vehicle_id=leader_vehicle_id,
            follower_vehicle_id=follower_vehicle_id,
            expected_offset_m=expected_offset,
            expected_follower_position_m=assessment.expected_follower_position_m,
            observed_offset_m=assessment.observed_offset_m,
            relative_velocity_m_s=assessment.relative_velocity_m_s,
            tracking_error_m=assessment.tracking_error_m,
            speed_error_m_s=assessment.speed_error_m_s,
            separation_m=assessment.separation_m,
            boundary_margin_m=min(
                _boundary_margin(leader_position, self.supervisor),
                _boundary_margin(follower_position, self.supervisor),
            ),
            leader_source_clock_id=leader_sample.source_clock_id,
            leader_source_clock_epoch=leader_sample.source_clock_epoch,
            leader_source_sequence=leader_sample.sequence,
            follower_source_clock_id=follower_sample.source_clock_id,
            follower_source_clock_epoch=follower_sample.source_clock_epoch,
            follower_source_sequence=follower_sample.sequence,
            timestamp_monotonic_s=time.monotonic(),
        )
        self._leader_follower_observations.append(observation)

    async def _coordination_observation(
        self,
        task_id: str,
        vehicle_id: str,
    ) -> tuple[TelemetryEnvelope | None, str | None]:
        child = self._children.get(task_id)
        if child is None or child.done():
            return None, None
        run_id = self._child_runs.get(task_id)
        if run_id is not None:
            with suppress(CrazySwarmError):
                phase = self.mission_runner.get_run(run_id).phase
                if phase in {MissionPhase.CLEANUP, MissionPhase.COMPLETE}:
                    return None, None
        try:
            sample = await self.observation_for(vehicle_id)
        except CrazySwarmError as error:
            if error.code is ErrorCode.IDENTITY_MISMATCH:
                raise
            return None, error.code.value
        if child.done():
            return None, None
        if run_id is not None:
            with suppress(CrazySwarmError):
                phase = self.mission_runner.get_run(run_id).phase
                if phase in {MissionPhase.CLEANUP, MissionPhase.COMPLETE}:
                    return None, None
        telemetry = sample.telemetry
        if telemetry.state is VehicleState.DISCONNECTED:
            return sample, ErrorCode.LINK_LOST.value
        if telemetry.state in {VehicleState.FAULT, VehicleState.EMERGENCY}:
            return sample, f"TERMINAL_STATE_{telemetry.state.value}"
        if (
            telemetry.localization_quality_percent is None
            or telemetry.localization_quality_percent
            < self.supervisor.policy.minimum_localization_quality_percent
        ):
            return sample, ErrorCode.LOCALIZATION_INVALID.value
        if telemetry.position_m is None:
            return sample, "POSITION_UNAVAILABLE"
        if not self.supervisor.policy.flight_volume.contains(telemetry.position_m):
            return sample, ErrorCode.GEOFENCE_BREACH.value
        received_at_s = self.supervisor.session(vehicle_id).telemetry_received_at_monotonic_s
        if (
            received_at_s is None
            or time.monotonic() - received_at_s
            > self.deployment.constraints.observation_freshness_s
        ):
            return sample, ErrorCode.TELEMETRY_STALE.value
        return sample, None

    def _coordination_loss_requires_recovery(self, task_id: str) -> bool:
        child = self._children.get(task_id)
        if child is None or child.done():
            return False
        run_id = self._child_runs.get(task_id)
        if run_id is None:
            return True
        try:
            phase = self.mission_runner.get_run(run_id).phase
        except CrazySwarmError:
            return not child.done()
        return phase not in {MissionPhase.CLEANUP, MissionPhase.COMPLETE}

    async def _apply_leader_loss_policy(
        self,
        reason: str,
        *,
        sample: TelemetryEnvelope | None = None,
    ) -> None:
        task_ids = self._leader_follower_task_ids
        if task_ids is None or self._leader_loss_policy_applied:
            return
        self._leader_loss_policy_applied = True
        self._coordination_policy_ids.add(LEADER_LOSS_POLICY_ID)
        detected_at_s = time.monotonic()
        leader_task_id, follower_task_id = task_ids
        leader_vehicle_id = self.tasks.record(leader_task_id).owner_vehicle_id
        follower_vehicle_id = self.tasks.record(follower_task_id).owner_vehicle_id
        details: dict[str, str | int | float | bool | None] = {
            "reason": reason,
            "policy_id": LEADER_LOSS_POLICY_ID,
            "intervention_bound_s": COORDINATION_INTERVENTION_BOUND_S,
        }
        if sample is not None:
            details.update(
                {
                    "source_clock_id": sample.source_clock_id,
                    "source_clock_epoch": sample.source_clock_epoch,
                    "source_sequence": sample.sequence,
                }
            )
        self._emit(
            "LEADER_LOSS_DETECTED",
            vehicle_id=leader_vehicle_id,
            task_id=leader_task_id,
            details=details,
        )
        if follower_vehicle_id is not None:
            self._record_recovery_proposal(
                RecoveryTrigger.LEADER_LOSS,
                task_id=follower_task_id,
                vehicle_id=follower_vehicle_id,
                available_actions=frozenset({RecoveryAction.LAND, RecoveryAction.ABORT_AND_LAND}),
                observation_current=True,
            )
        if follower_vehicle_id is not None:
            await self.abort_vehicle(
                follower_vehicle_id,
                reason=f"LEADER_LOSS_{reason}",
            )
        if leader_vehicle_id is not None:
            await self.abort_vehicle(leader_vehicle_id, reason=reason)
        latency_s = time.monotonic() - detected_at_s
        self._leader_loss_intervention_latency_s = latency_s
        self._emit(
            "LEADER_LOSS_POLICY_APPLIED",
            vehicle_id=follower_vehicle_id,
            task_id=follower_task_id,
            details={
                "reason": reason,
                "policy_id": LEADER_LOSS_POLICY_ID,
                "action": "LAND_FOLLOWER_AND_ABORT_LEADER",
                "intervention_latency_s": latency_s,
                "intervention_bound_s": COORDINATION_INTERVENTION_BOUND_S,
            },
        )

    async def _apply_follower_loss_policy(
        self,
        reason: str,
        *,
        sample: TelemetryEnvelope | None = None,
    ) -> None:
        task_ids = self._leader_follower_task_ids
        if task_ids is None or self._follower_loss_policy_applied:
            return
        self._follower_loss_policy_applied = True
        self._coordination_policy_ids.add(FOLLOWER_LOSS_POLICY_ID)
        detected_at_s = time.monotonic()
        leader_task_id, follower_task_id = task_ids
        leader_vehicle_id = self.tasks.record(leader_task_id).owner_vehicle_id
        follower_vehicle_id = self.tasks.record(follower_task_id).owner_vehicle_id
        details: dict[str, str | int | float | bool | None] = {
            "reason": reason,
            "policy_id": FOLLOWER_LOSS_POLICY_ID,
            "intervention_bound_s": COORDINATION_INTERVENTION_BOUND_S,
        }
        if sample is not None:
            details.update(
                {
                    "source_clock_id": sample.source_clock_id,
                    "source_clock_epoch": sample.source_clock_epoch,
                    "source_sequence": sample.sequence,
                }
            )
        self._emit(
            "FOLLOWER_LOSS_DETECTED",
            vehicle_id=follower_vehicle_id,
            task_id=follower_task_id,
            details=details,
        )
        if leader_vehicle_id is not None:
            await self.abort_vehicle(
                leader_vehicle_id,
                reason=f"FOLLOWER_LOSS_{reason}",
            )
        if follower_vehicle_id is not None:
            await self.abort_vehicle(follower_vehicle_id, reason=reason)
        latency_s = time.monotonic() - detected_at_s
        self._emit(
            "FOLLOWER_LOSS_POLICY_APPLIED",
            vehicle_id=leader_vehicle_id,
            task_id=leader_task_id,
            details={
                "reason": reason,
                "policy_id": FOLLOWER_LOSS_POLICY_ID,
                "action": "LAND_LEADER_AND_ABORT_FOLLOWER",
                "intervention_latency_s": latency_s,
                "intervention_bound_s": COORDINATION_INTERVENTION_BOUND_S,
            },
        )

    async def _finish_task(self, task_id: str, result: MissionResult) -> None:
        record = self.tasks.record(task_id)
        vehicle_id = record.owner_vehicle_id
        lease = record.lease
        if vehicle_id is None or lease is None:
            return
        if result.status is MissionStatus.SUCCEEDED:
            self.tasks.update_progress(
                task_id,
                vehicle_id,
                lease.generation,
                record.definition.completion_progress_percent,
            )
            self.tasks.complete(task_id, vehicle_id, lease.generation)
            event_type = "TASK_COMPLETED"
        elif result.status is MissionStatus.ABORTED:
            self.tasks.abort(task_id, reason=result.reason_code)
            event_type = "TASK_ABORTED"
        else:
            self.tasks.retry(task_id, reason=result.reason_code)
            event_type = "TASK_RETRY_REQUIRED"
        self._emit(
            event_type,
            vehicle_id=vehicle_id,
            task_id=task_id,
            details={"mission_status": result.status.value, "reason_code": result.reason_code},
        )
        if result.status is not MissionStatus.SUCCEEDED:
            if (
                self._leader_follower_task_ids is not None
                and task_id == self._leader_follower_task_ids[0]
                and not self._follower_loss_policy_applied
            ):
                await self._apply_leader_loss_policy(result.reason_code)
            elif (
                self._leader_follower_task_ids is not None
                and task_id == self._leader_follower_task_ids[1]
                and not self._leader_loss_policy_applied
            ):
                await self._apply_follower_loss_policy(result.reason_code)
            await self._apply_child_failure_policy(task_id)

    async def _apply_child_failure_policy(self, failed_task_id: str) -> None:
        policy = self.deployment.constraints.child_failure_policy
        if policy is FleetFailurePolicy.CONTINUE_HEALTHY:
            self._emit(
                "PEER_POLICY_CONTINUE",
                task_id=failed_task_id,
            )
            return
        for task_id, child in self._children.items():
            if task_id == failed_task_id or child.done():
                continue
            record = self.tasks.record(task_id)
            vehicle_id = record.owner_vehicle_id
            run_id = self._child_runs.get(task_id)
            if vehicle_id is None or run_id is None:
                continue
            if policy is FleetFailurePolicy.HOLD_ALL:
                session = self.supervisor.session(vehicle_id)
                if session.state is VehicleState.FLYING:
                    with suppress(CrazySwarmError):
                        await self.supervisor.stop_and_hold(
                            vehicle_id,
                            f"mission:{run_id}",
                            source=CommandSource.SUPERVISOR,
                            mission_run_id=run_id,
                            fleet_binding=self._bindings[task_id],
                        )
                self._emit(
                    "PEER_POLICY_HOLD",
                    vehicle_id=vehicle_id,
                    task_id=task_id,
                )
            else:
                self._emit(
                    "PEER_POLICY_LAND",
                    vehicle_id=vehicle_id,
                    task_id=task_id,
                )
            await self.mission_runner.cancel(run_id)

    async def _separation_intervention(
        self,
        first: str,
        second: str,
        level: SeparationLevel,
        *,
        policy_id: str,
    ) -> str:
        active = [
            vehicle_id
            for vehicle_id in (first, second)
            if self.supervisor.session(vehicle_id).state
            in {
                VehicleState.ARMING,
                VehicleState.TAKING_OFF,
                VehicleState.FLYING,
                VehicleState.RETURNING,
                VehicleState.LANDING,
            }
        ]
        if not active:
            return "BLOCK_LAUNCH"
        if policy_id == CROSSING_SEPARATION_POLICY_ID:
            pair = (min(first, second), max(first, second))
            if level is SeparationLevel.WARNING:
                victim = max(active)
                return self._request_crossing_hold(
                    pair,
                    victim,
                    reason="WARNING_CROSSING_SEPARATION",
                )
            await self._abort_crossing_pair(
                pair,
                active,
                reason="CRITICAL_CROSSING_SEPARATION",
            )
            return "ABORT_PAIR_" + "_".join(sorted(active))
        victim = max(active)
        await self.abort_vehicle(victim, reason=f"{level.value}_SEPARATION")
        return f"ABORT_{victim}"

    def _request_crossing_hold(
        self,
        pair: tuple[str, str],
        vehicle_id: str,
        *,
        reason: str,
    ) -> str:
        gate = self._require_crossing_command_gate()
        gate.hold(vehicle_id, reason=reason)
        self._crossing_holds[pair] = vehicle_id
        self._crossing_hold_tasks[pair] = asyncio.create_task(
            self._confirm_crossing_hold(pair, vehicle_id),
            name=f"crossing-hold-{vehicle_id}",
        )
        return f"HOLD_REQUESTED_{vehicle_id}"

    async def _confirm_crossing_hold(
        self,
        pair: tuple[str, str],
        vehicle_id: str,
    ) -> None:
        gate = self._require_crossing_command_gate()
        try:
            await gate.wait_until_blocked(vehicle_id, timeout_s=2.0)
            task_id = next(
                (
                    task_id
                    for task_id, child_vehicle_id in self._child_vehicle_ids.items()
                    if child_vehicle_id == vehicle_id
                ),
                None,
            )
            if task_id is None:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "crossing hold vehicle has no child mission task",
                )
            run_id = self._child_runs[task_id]
            binding = self.mission_runner.current_fleet_binding(run_id)
            if binding is None:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "crossing hold lost its serialized fleet command binding",
                )
            await self.supervisor.stop_and_hold(
                vehicle_id,
                f"mission:{run_id}",
                source=CommandSource.SUPERVISOR,
                mission_run_id=run_id,
                fleet_binding=binding,
            )
            self._crossing_confirmed_pairs.add(pair)
            self._emit(
                "SEPARATION_HOLD_CONFIRMED",
                vehicle_id=vehicle_id,
                task_id=task_id,
                details={
                    "peer_vehicle_id": pair[0] if vehicle_id == pair[1] else pair[1],
                    "policy_id": CROSSING_SEPARATION_POLICY_ID,
                    "task_lease_generation": binding.task_lease_generation,
                },
            )
            refresh_period_s = min(
                0.25,
                self.deployment.constraints.observation_freshness_s / 3.0,
            )
            while gate.held(vehicle_id):
                await asyncio.sleep(refresh_period_s)
                if (
                    not gate.held(vehicle_id)
                    or self.supervisor.session(vehicle_id).state is not VehicleState.FLYING
                ):
                    continue
                binding = self.mission_runner.current_fleet_binding(run_id)
                if binding is None:
                    raise CrazySwarmError(
                        ErrorCode.IDENTITY_MISMATCH,
                        "crossing hold lost its serialized fleet command binding",
                    )
                await self.supervisor.stop_and_hold(
                    vehicle_id,
                    f"mission:{run_id}",
                    source=CommandSource.SUPERVISOR,
                    mission_run_id=run_id,
                    fleet_binding=binding,
                )
        except (TimeoutError, CrazySwarmError) as error:
            self._emit(
                "SEPARATION_HOLD_FAILED",
                vehicle_id=vehicle_id,
                details={"reason": str(error)},
            )
            await self._abort_crossing_pair(
                pair,
                list(pair),
                reason="WARNING_CROSSING_HOLD_FAILED",
            )

    async def _release_crossing_hold(self, pair: tuple[str, str]) -> str:
        vehicle_id = self._crossing_holds.pop(pair)
        self._crossing_confirmed_pairs.discard(pair)
        hold_task = self._crossing_hold_tasks.pop(pair, None)
        if hold_task is not None and hold_task is not asyncio.current_task():
            hold_task.cancel()
            with suppress(asyncio.CancelledError):
                await hold_task
        gate = self._require_crossing_command_gate()
        gate.release(vehicle_id)
        return f"RELEASE_{vehicle_id}"

    def _require_crossing_command_gate(self) -> MissionCommandGate:
        gate = self._command_gate
        if gate is None:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "crossing separation policy has no mission command gate",
            )
        return gate

    async def _abort_crossing_pair(
        self,
        pair: tuple[str, str],
        active: list[str],
        *,
        reason: str,
    ) -> None:
        hold_task = self._crossing_hold_tasks.pop(pair, None)
        if hold_task is not None and hold_task is not asyncio.current_task():
            hold_task.cancel()
            with suppress(asyncio.CancelledError):
                await hold_task
        held_vehicle = self._crossing_holds.pop(pair, None)
        self._crossing_confirmed_pairs.discard(pair)
        if held_vehicle is not None and self._command_gate is not None:
            self._command_gate.release(held_vehicle)
        for vehicle_id in sorted(active):
            await self.abort_vehicle(vehicle_id, reason=reason)

    def _separation_policy_id(self, first: str, second: str) -> str:
        pair_task_ids = {
            task_id
            for task_id, vehicle_id in self._child_vehicle_ids.items()
            if vehicle_id in {first, second}
        }
        if self._crossing_task_ids and pair_task_ids == self._crossing_task_ids:
            return CROSSING_SEPARATION_POLICY_ID
        return GENERIC_SEPARATION_POLICY_ID

    def _separation_level(self, distance_m: float) -> SeparationLevel:
        constraints = self.deployment.constraints
        if distance_m <= constraints.critical_separation_m:
            return SeparationLevel.CRITICAL
        if distance_m <= constraints.warning_separation_m:
            return SeparationLevel.WARNING
        return SeparationLevel.CLEAR

    async def _cancel_all(self, reason: str) -> None:
        for hold_task in self._crossing_hold_tasks.values():
            if not hold_task.done():
                hold_task.cancel()
        if self._crossing_hold_tasks:
            await asyncio.gather(
                *self._crossing_hold_tasks.values(),
                return_exceptions=True,
            )
        self._crossing_hold_tasks.clear()
        self._crossing_holds.clear()
        self._crossing_confirmed_pairs.clear()
        if self._command_gate is not None:
            self._command_gate.release_all()
        for task_id, child in self._children.items():
            if not child.done():
                vehicle_id = self._child_vehicle_ids[task_id]
                if self.supervisor.session(vehicle_id).state is VehicleState.LANDING:
                    continue
                run_id = self._child_runs.get(task_id)
                if run_id is not None:
                    await self.mission_runner.cancel(run_id)
        if self._children:
            await asyncio.gather(*self._children.values(), return_exceptions=True)
        for handover_id, child in self._handover_children.items():
            if not child.done():
                vehicle_id = self._handover_vehicle_ids[handover_id]
                if self.supervisor.session(vehicle_id).state is VehicleState.LANDING:
                    continue
                child.cancel()
        if self._handover_children:
            await asyncio.gather(
                *self._handover_children.values(),
                return_exceptions=True,
            )
        await self._settle_interrupted_members(reason)
        for record in self.tasks.records():
            if record.state not in {TaskState.COMPLETED, TaskState.ABORTED}:
                self.tasks.abort(record.definition.task_id, reason=reason)

    async def _settle_interrupted_members(self, reason: str) -> None:
        command_contexts = {
            self._child_vehicle_ids[task_id]: (
                self._child_runs[task_id],
                self._bindings[task_id],
            )
            for task_id in self._child_runs
        }
        command_contexts.update(
            {
                self._handover_vehicle_ids[handover_id]: (
                    self._handover_runs[handover_id],
                    self._handover_bindings[handover_id],
                )
                for handover_id in self._handover_runs
            }
        )
        transitional = {
            VehicleState.ARMING,
            VehicleState.TAKING_OFF,
            VehicleState.FLYING,
            VehicleState.RETURNING,
            VehicleState.LANDING,
            VehicleState.ABORTING,
        }
        for vehicle_id, (mission_run_id, binding) in sorted(command_contexts.items()):
            session = self.supervisor.session(vehicle_id)
            telemetry: TelemetryEnvelope | None
            try:
                telemetry = await self.observation_for(vehicle_id)
            except CrazySwarmError as error:
                if error.code is ErrorCode.IDENTITY_MISMATCH:
                    raise
                telemetry = session.telemetry
                self._emit(
                    "BOUNDED_CLEANUP_OBSERVATION_UNAVAILABLE",
                    vehicle_id=vehicle_id,
                    task_id=binding.task_id,
                    details={"reason_code": error.code.value},
                )
            if (
                session.state not in transitional
                and telemetry is not None
                and not telemetry.telemetry.armed
                and not telemetry.telemetry.flying
            ):
                continue
            owner_id = (
                session.lease.owner_id
                if session.lease is not None
                else f"fleet-cleanup:{self.identity.fleet_run_id}"
            )
            if session.lease is None:
                self.supervisor.claim_control(vehicle_id, owner_id)
            cleanup_error: CrazySwarmError | None = None
            try:
                await self.supervisor.emergency_stop(
                    vehicle_id,
                    owner_id,
                    reason=f"bounded fleet cleanup: {reason}",
                    allow_expired_owner=True,
                    mission_run_id=mission_run_id,
                    fleet_binding=binding,
                )
            except CrazySwarmError as error:
                if error.code is ErrorCode.IDENTITY_MISMATCH:
                    raise
                cleanup_error = error
            if session.lease is not None and session.lease.owner_id == owner_id:
                try:
                    await self.supervisor.release_control(
                        vehicle_id,
                        owner_id,
                        allow_expired_owner=True,
                    )
                except CrazySwarmError as error:
                    if error.code is ErrorCode.IDENTITY_MISMATCH:
                        raise
                    cleanup_error = cleanup_error or error
            if cleanup_error is not None:
                self._emit(
                    "BOUNDED_CLEANUP_UNCONFIRMED",
                    vehicle_id=vehicle_id,
                    task_id=binding.task_id,
                    details={"reason_code": cleanup_error.code.value},
                )
                continue
            self._emit(
                "BOUNDED_CLEANUP_STABILIZED",
                vehicle_id=vehicle_id,
                task_id=binding.task_id,
                details={"reason": reason},
            )

    def _fail_active_handover(self, error: CrazySwarmError) -> None:
        if self._persistent is None or self._active_handover_id is None:
            return
        record = self._persistent.handover(self._active_handover_id)
        if record.phase in {HandoverPhase.DEGRADED, HandoverPhase.FAILED}:
            return
        reason = f"{error.code.value}: {error.message}"
        if record.takeover_confirmed or record.phase is HandoverPhase.COMPLETED:
            self._persistent.fail_handover(record.handover_id, reason=reason)
        else:
            self._persistent.terminate_handover(
                record.handover_id,
                reason=reason,
                failed=True,
            )
        self._metric(
            FleetMetricKind.FAULT_DETECTED,
            correlation_id=record.handover_id,
            vehicle_id=record.incoming_vehicle_id,
            task_id=record.task_id,
            details={"reason": error.code.value},
        )

    def _child_results(self) -> tuple[FleetChildResult, ...]:
        values: list[FleetChildResult] = []
        for task_id in sorted(self._children):
            child = self._children[task_id]
            if child.cancelled() or not child.done() or child.exception() is not None:
                continue
            mission_result = child.result()
            binding = self._bindings[task_id]
            values.append(
                FleetChildResult(
                    task_id=task_id,
                    vehicle_id=mission_result.vehicle_id,
                    lease_generation=binding.task_lease_generation,
                    mission_result=mission_result,
                )
            )
        for handover_id in sorted(self._handover_children):
            child = self._handover_children[handover_id]
            if child.cancelled() or not child.done() or child.exception() is not None:
                continue
            mission_result = child.result()
            binding = self._handover_bindings[handover_id]
            values.append(
                FleetChildResult(
                    task_id=binding.task_id,
                    vehicle_id=mission_result.vehicle_id,
                    lease_generation=binding.task_lease_generation,
                    mission_result=mission_result,
                )
            )
        return tuple(values)

    def _result(self, status: FleetStatus, reason_code: str, message: str) -> FleetResult:
        normalized = self._normalized_trace(status)
        distances = [item.distance_m for item in self._separation]
        child_results = self._child_results()
        nominal_deconfliction_executed = self._nominal_deconfliction_executed(child_results)
        dock_snapshots = (
            tuple(
                self._dock_manager.snapshot(dock_id)
                for dock_id in sorted(self._dock_manager.definitions)
            )
            if self._dock_manager is not None
            else ()
        )
        return FleetResult(
            fleet_session_id=self.identity.fleet_session_id,
            fleet_run_id=self.identity.fleet_run_id,
            fleet_identity_sha256=self.identity.sha256,
            deployment_sha256=self.deployment.sha256,
            status=status,
            reason_code=reason_code,
            message=message,
            child_results=child_results,
            tasks=self.tasks.records(),
            minimum_separation_m=min(distances) if distances else None,
            warning_violations=sum(
                item.level is SeparationLevel.WARNING for item in self._separation
            ),
            critical_violations=sum(
                item.level is SeparationLevel.CRITICAL for item in self._separation
            ),
            separation_observations=tuple(self._separation),
            leader_follower_observations=tuple(self._leader_follower_observations),
            leader_loss_intervention_latency_s=(self._leader_loss_intervention_latency_s),
            coordination_policy_ids=tuple(sorted(self._coordination_policy_ids)),
            events=tuple(self._events),
            normalized_trace=normalized,
            normalized_outcome_sha256=canonical_sha256(normalized),
            persistent_coverage=self._persistent_result,
            dock_snapshots=dock_snapshots,
            metrics=(
                self._metrics.report(ended_at_s=time.monotonic())
                if self._metrics is not None
                else None
            ),
            authority_transitions=tuple(self._authority_transitions),
            deconfliction_plan_sha256=(
                self.deconfliction_plan.plan_sha256 if self.deconfliction_plan is not None else None
            ),
            selected_deconfliction_strategy=(
                self.deconfliction_plan.selected_strategy.value
                if self.deconfliction_plan is not None
                and self.deconfliction_plan.selected_strategy is not None
                else None
            ),
            nominal_deconfliction_executed=nominal_deconfliction_executed,
        )

    def _nominal_deconfliction_executed(
        self,
        child_results: tuple[FleetChildResult, ...],
    ) -> bool | None:
        plan = self.deconfliction_plan
        if plan is None or plan.status.value == "NOT_REQUIRED":
            return None
        if plan.status.value != "RESOLVED":
            return False
        observed_hashes = tuple(
            sorted(
                result.mission_result.execution_program_sha256
                for result in child_results
                if result.mission_result.execution_program_sha256 is not None
            )
        )
        return (
            observed_hashes == tuple(sorted(plan.selected_program_sha256s))
            and len(child_results) == len(plan.selected_program_sha256s)
            and all(
                result.mission_result.status is MissionStatus.SUCCEEDED for result in child_results
            )
        )

    def _normalized_trace(
        self, status: FleetStatus
    ) -> tuple[dict[str, str | int | float | bool | None], ...]:
        trace: list[dict[str, str | int | float | bool | None]] = []
        for event in self._events:
            trace.append(
                {
                    "kind": "fleet_event",
                    "event_type": event.event_type,
                    "vehicle_id": event.vehicle_id,
                    "task_id": event.task_id,
                }
            )
        for record in self.tasks.records():
            trace.append(
                {
                    "kind": "task_terminal",
                    "task_id": record.definition.task_id,
                    "vehicle_id": record.owner_vehicle_id,
                    "state": record.state.value,
                    "progress_percent": record.progress_percent,
                    "lease_generation": record.lease_generation,
                }
            )
        for child in self._child_results():
            trace.append(
                {
                    "kind": "child_terminal",
                    "task_id": child.task_id,
                    "vehicle_id": child.vehicle_id,
                    "status": child.mission_result.status.value,
                    "reason_code": child.mission_result.reason_code,
                }
            )
        trace.append({"kind": "fleet_terminal", "status": status.value})
        return tuple(trace)

    def _emit(
        self,
        event_type: str,
        *,
        vehicle_id: str | None = None,
        task_id: str | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self._events.append(
            FleetEvent(
                fleet_session_id=self.identity.fleet_session_id,
                fleet_run_id=self.identity.fleet_run_id,
                deployment_sha256=self.deployment.sha256,
                sequence=len(self._events) + 1,
                event_type=event_type,
                timestamp_monotonic_s=time.monotonic(),
                vehicle_id=vehicle_id,
                task_id=task_id,
                details=details or {},
            )
        )


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )


def _subtract(first: Vector3, second: Vector3) -> Vector3:
    return Vector3(
        x=first.x - second.x,
        y=first.y - second.y,
        z=first.z - second.z,
    )


def _boundary_margin(position: Vector3, supervisor: SafetySupervisor) -> float:
    volume = supervisor.policy.flight_volume
    return max(
        0.0,
        min(
            position.x - volume.minimum_m.x,
            volume.maximum_m.x - position.x,
            position.y - volume.minimum_m.y,
            volume.maximum_m.y - position.y,
            position.z - volume.minimum_m.z,
            volume.maximum_m.z - position.z,
        ),
    )


def _point_segment_distance(point: Vector3, start: Vector3, end: Vector3) -> float:
    segment = Vector3(x=end.x - start.x, y=end.y - start.y, z=end.z - start.z)
    relative = Vector3(x=point.x - start.x, y=point.y - start.y, z=point.z - start.z)
    length_squared = segment.x**2 + segment.y**2 + segment.z**2
    if length_squared <= 0.0:
        return _distance(point, start)
    projection = (
        relative.x * segment.x + relative.y * segment.y + relative.z * segment.z
    ) / length_squared
    ratio = max(0.0, min(1.0, projection))
    closest = Vector3(
        x=start.x + segment.x * ratio,
        y=start.y + segment.y * ratio,
        z=start.z + segment.z * ratio,
    )
    return _distance(point, closest)
