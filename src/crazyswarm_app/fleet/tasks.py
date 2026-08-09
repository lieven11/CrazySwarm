from __future__ import annotations

import time
from enum import StrEnum
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import ContractModel, Identifier, VehicleCapability
from crazyswarm_app.domain.simulation import SHA256
from crazyswarm_app.fleet.artifacts import DeploymentTaskDefinition


class TaskState(StrEnum):
    DECLARED = "DECLARED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    RETRY_PENDING = "RETRY_PENDING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class TaskDecision(StrEnum):
    COMPLETE = "COMPLETE"
    RETRY = "RETRY"
    REASSIGN = "REASSIGN"
    ABORT = "ABORT"


class TaskLease(ContractModel):
    schema_version: Literal[1] = 1
    fleet_session_id: Identifier
    fleet_run_id: Identifier
    deployment_sha256: SHA256
    task_id: Identifier
    vehicle_id: Identifier
    generation: int = Field(ge=1)
    issued_at_monotonic_s: float = Field(ge=0.0)
    expires_at_monotonic_s: float = Field(gt=0.0)


class TaskEvidenceEvent(ContractModel):
    schema_version: Literal[1] = 1
    fleet_session_id: Identifier
    fleet_run_id: Identifier
    deployment_sha256: SHA256
    sequence: int = Field(ge=1)
    task_id: Identifier
    event_type: Identifier
    state: TaskState
    timestamp_monotonic_s: float = Field(ge=0.0)
    owner_vehicle_id: Identifier | None = None
    lease_generation: int = Field(default=0, ge=0)
    progress_percent: float = Field(ge=0.0, le=100.0)
    reason: str | None = Field(default=None, max_length=500)
    child_mission_run_id: Identifier | None = None


class TaskRecord(ContractModel):
    definition: DeploymentTaskDefinition
    state: TaskState = TaskState.DECLARED
    owner_vehicle_id: Identifier | None = None
    lease: TaskLease | None = None
    lease_generation: int = Field(default=0, ge=0)
    progress_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    attempts: int = Field(default=0, ge=0)
    decision: TaskDecision | None = None
    terminal_reason: str | None = None
    child_mission_run_id: Identifier | None = None
    events: tuple[TaskEvidenceEvent, ...] = ()


class TaskLedger:
    """Owns task state independently from any one vehicle mission run."""

    def __init__(
        self,
        *,
        fleet_session_id: str,
        fleet_run_id: str,
        deployment_sha256: str,
        definitions: tuple[DeploymentTaskDefinition, ...],
        lease_duration_s: float = 10.0,
    ) -> None:
        if lease_duration_s <= 0.0:
            raise ValueError("task lease duration must be positive")
        self.fleet_session_id = fleet_session_id
        self.fleet_run_id = fleet_run_id
        self.deployment_sha256 = deployment_sha256
        self.lease_duration_s = lease_duration_s
        self._records = {item.task_id: TaskRecord(definition=item) for item in definitions}
        if len(self._records) != len(definitions):
            raise ValueError("task identities must be unique")
        self._event_sequence = 0
        for task_id in sorted(self._records):
            self._emit(task_id, "TASK_DECLARED")

    def records(self) -> tuple[TaskRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def record(self, task_id: str) -> TaskRecord:
        try:
            return self._records[task_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, f"unknown fleet task: {task_id}"
            ) from error

    def assign(
        self,
        task_id: str,
        vehicle_id: str,
        *,
        capabilities: frozenset[VehicleCapability],
        battery_percent: float | None,
        allow_inadequate_energy: bool = False,
        now_s: float | None = None,
    ) -> TaskRecord:
        record = self.record(task_id)
        if record.state not in {TaskState.DECLARED, TaskState.RETRY_PENDING}:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task is not available for assignment")
        missing = record.definition.required_capabilities - capabilities
        if missing:
            raise CrazySwarmError(
                ErrorCode.CAPABILITY_MISSING,
                "vehicle does not satisfy task capabilities",
                details={"missing": sorted(item.value for item in missing)},
            )
        required_energy = (
            record.definition.estimated_energy_percent + record.definition.energy_margin_percent
        )
        if (
            battery_percent is None or battery_percent < required_energy
        ) and not allow_inadequate_energy:
            raise CrazySwarmError(
                ErrorCode.CRITICAL_BATTERY,
                "task assignment has inadequate observed energy margin",
                details={"observed": battery_percent, "required": required_energy},
            )
        now = _now(now_s)
        generation = record.lease_generation + 1
        lease = TaskLease(
            fleet_session_id=self.fleet_session_id,
            fleet_run_id=self.fleet_run_id,
            deployment_sha256=self.deployment_sha256,
            task_id=task_id,
            vehicle_id=vehicle_id,
            generation=generation,
            issued_at_monotonic_s=now,
            expires_at_monotonic_s=now + self.lease_duration_s,
        )
        self._records[task_id] = record.model_copy(
            update={
                "state": TaskState.ASSIGNED,
                "owner_vehicle_id": vehicle_id,
                "lease": lease,
                "lease_generation": generation,
                "attempts": record.attempts + 1,
                "decision": None,
                "terminal_reason": None,
            }
        )
        return self._emit(task_id, "TASK_ASSIGNED")

    def start(
        self,
        task_id: str,
        vehicle_id: str,
        *,
        child_mission_run_id: str,
        generation: int,
        now_s: float | None = None,
    ) -> TaskRecord:
        record = self._require_current_lease(task_id, vehicle_id, generation, now_s)
        if record.state is not TaskState.ASSIGNED:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "only an assigned task can start")
        self._records[task_id] = record.model_copy(
            update={
                "state": TaskState.IN_PROGRESS,
                "child_mission_run_id": child_mission_run_id,
            }
        )
        return self._emit(task_id, "TASK_STARTED")

    def renew(
        self,
        task_id: str,
        vehicle_id: str,
        generation: int,
        *,
        now_s: float | None = None,
    ) -> TaskLease:
        now = _now(now_s)
        record = self._require_current_lease(task_id, vehicle_id, generation, now)
        assert record.lease is not None
        lease = record.lease.model_copy(
            update={"expires_at_monotonic_s": now + self.lease_duration_s}
        )
        self._records[task_id] = record.model_copy(update={"lease": lease})
        self._emit(task_id, "TASK_LEASE_RENEWED")
        return lease

    def update_progress(
        self,
        task_id: str,
        vehicle_id: str,
        generation: int,
        progress_percent: float,
        *,
        now_s: float | None = None,
    ) -> TaskRecord:
        record = self._require_current_lease(task_id, vehicle_id, generation, now_s)
        if record.state is not TaskState.IN_PROGRESS:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task is not in progress")
        if progress_percent < record.progress_percent or progress_percent > 100.0:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "task progress must be monotonic")
        self._records[task_id] = record.model_copy(update={"progress_percent": progress_percent})
        return self._emit(task_id, "TASK_PROGRESS")

    def pause(
        self,
        task_id: str,
        vehicle_id: str,
        generation: int,
        *,
        reason: str,
        now_s: float | None = None,
    ) -> TaskRecord:
        record = self._require_current_lease(task_id, vehicle_id, generation, now_s)
        if record.state is not TaskState.IN_PROGRESS:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task is not in progress")
        self._records[task_id] = record.model_copy(update={"state": TaskState.PAUSED})
        return self._emit(task_id, "TASK_PAUSED", reason=reason)

    def resume(
        self,
        task_id: str,
        vehicle_id: str,
        generation: int,
        *,
        now_s: float | None = None,
    ) -> TaskRecord:
        record = self._require_current_lease(task_id, vehicle_id, generation, now_s)
        if record.state is not TaskState.PAUSED:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task is not paused")
        self._records[task_id] = record.model_copy(update={"state": TaskState.IN_PROGRESS})
        return self._emit(task_id, "TASK_RESUMED")

    def retry(self, task_id: str, *, reason: str) -> TaskRecord:
        record = self.record(task_id)
        if record.state not in {TaskState.ASSIGNED, TaskState.IN_PROGRESS, TaskState.PAUSED}:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task cannot enter retry")
        self._records[task_id] = record.model_copy(
            update={
                "state": TaskState.RETRY_PENDING,
                "owner_vehicle_id": None,
                "lease": None,
                "decision": TaskDecision.RETRY,
                "terminal_reason": reason,
                "child_mission_run_id": None,
            }
        )
        return self._emit(task_id, "TASK_RETRY_PENDING", reason=reason)

    def reassign(
        self,
        task_id: str,
        vehicle_id: str,
        *,
        capabilities: frozenset[VehicleCapability],
        battery_percent: float | None,
        reason: str,
        now_s: float | None = None,
    ) -> TaskRecord:
        record = self.record(task_id)
        if record.state in {TaskState.COMPLETED, TaskState.ABORTED, TaskState.DECLARED}:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task cannot be reassigned")
        self.retry(task_id, reason=reason)
        reassigned = self.assign(
            task_id,
            vehicle_id,
            capabilities=capabilities,
            battery_percent=battery_percent,
            now_s=now_s,
        )
        self._records[task_id] = reassigned.model_copy(update={"decision": TaskDecision.REASSIGN})
        return self._emit(task_id, "TASK_REASSIGNED", reason=reason)

    def transfer(
        self,
        task_id: str,
        outgoing_vehicle_id: str,
        incoming_vehicle_id: str,
        *,
        expected_generation: int,
        capabilities: frozenset[VehicleCapability],
        battery_percent: float | None,
        reason: str,
        now_s: float | None = None,
    ) -> TaskRecord:
        """Atomically replace the current owner and invalidate every older lease."""

        if outgoing_vehicle_id == incoming_vehicle_id:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "handover requires a new owner")
        record = self._require_current_lease(
            task_id,
            outgoing_vehicle_id,
            expected_generation,
            now_s,
        )
        if record.state not in {TaskState.ASSIGNED, TaskState.IN_PROGRESS, TaskState.PAUSED}:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task cannot be transferred")
        self._validate_assignment_energy_and_capability(
            record,
            capabilities=capabilities,
            battery_percent=battery_percent,
        )
        now = _now(now_s)
        generation = record.lease_generation + 1
        lease = TaskLease(
            fleet_session_id=self.fleet_session_id,
            fleet_run_id=self.fleet_run_id,
            deployment_sha256=self.deployment_sha256,
            task_id=task_id,
            vehicle_id=incoming_vehicle_id,
            generation=generation,
            issued_at_monotonic_s=now,
            expires_at_monotonic_s=now + self.lease_duration_s,
        )
        self._records[task_id] = record.model_copy(
            update={
                "state": TaskState.ASSIGNED,
                "owner_vehicle_id": incoming_vehicle_id,
                "lease": lease,
                "lease_generation": generation,
                "attempts": record.attempts + 1,
                "decision": TaskDecision.REASSIGN,
                "terminal_reason": reason,
                "child_mission_run_id": None,
            }
        )
        return self._emit(task_id, "TASK_OWNERSHIP_TRANSFERRED", reason=reason)

    def complete(
        self,
        task_id: str,
        vehicle_id: str,
        generation: int,
        *,
        reason: str = "completion criteria met",
        now_s: float | None = None,
    ) -> TaskRecord:
        record = self._require_current_lease(task_id, vehicle_id, generation, now_s)
        if record.state is not TaskState.IN_PROGRESS:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task is not in progress")
        if record.progress_percent < record.definition.completion_progress_percent:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "task completion criteria are not satisfied",
            )
        self._records[task_id] = record.model_copy(
            update={
                "state": TaskState.COMPLETED,
                "lease": None,
                "decision": TaskDecision.COMPLETE,
                "terminal_reason": reason,
            }
        )
        return self._emit(task_id, "TASK_COMPLETED", reason=reason)

    def abort(self, task_id: str, *, reason: str) -> TaskRecord:
        record = self.record(task_id)
        if record.state in {TaskState.COMPLETED, TaskState.ABORTED}:
            return record
        self._records[task_id] = record.model_copy(
            update={
                "state": TaskState.ABORTED,
                "lease": None,
                "decision": TaskDecision.ABORT,
                "terminal_reason": reason,
            }
        )
        return self._emit(task_id, "TASK_ABORTED", reason=reason)

    def _require_current_lease(
        self,
        task_id: str,
        vehicle_id: str,
        generation: int,
        now_s: float | None,
    ) -> TaskRecord:
        record = self.record(task_id)
        lease = record.lease
        now = _now(now_s)
        if (
            lease is None
            or lease.vehicle_id != vehicle_id
            or lease.generation != generation
            or record.owner_vehicle_id != vehicle_id
        ):
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED, "current task ownership is required"
            )
        if lease.expires_at_monotonic_s <= now:
            raise CrazySwarmError(ErrorCode.MODE_NOT_AUTHORIZED, "task lease has expired")
        return record

    @staticmethod
    def _validate_assignment_energy_and_capability(
        record: TaskRecord,
        *,
        capabilities: frozenset[VehicleCapability],
        battery_percent: float | None,
    ) -> None:
        missing = record.definition.required_capabilities - capabilities
        if missing:
            raise CrazySwarmError(
                ErrorCode.CAPABILITY_MISSING,
                "vehicle does not satisfy task capabilities",
                details={"missing": sorted(item.value for item in missing)},
            )
        required_energy = (
            record.definition.estimated_energy_percent + record.definition.energy_margin_percent
        )
        if battery_percent is None or battery_percent < required_energy:
            raise CrazySwarmError(
                ErrorCode.CRITICAL_BATTERY,
                "task assignment has inadequate observed energy margin",
                details={"observed": battery_percent, "required": required_energy},
            )

    def _emit(self, task_id: str, event_type: str, *, reason: str | None = None) -> TaskRecord:
        record = self.record(task_id)
        self._event_sequence += 1
        event = TaskEvidenceEvent(
            fleet_session_id=self.fleet_session_id,
            fleet_run_id=self.fleet_run_id,
            deployment_sha256=self.deployment_sha256,
            sequence=self._event_sequence,
            task_id=task_id,
            event_type=event_type,
            state=record.state,
            timestamp_monotonic_s=time.monotonic(),
            owner_vehicle_id=record.owner_vehicle_id,
            lease_generation=record.lease_generation,
            progress_percent=record.progress_percent,
            reason=reason,
            child_mission_run_id=record.child_mission_run_id,
        )
        updated = record.model_copy(update={"events": (*record.events, event)})
        self._records[task_id] = updated
        return updated


def replay_task(
    definition: DeploymentTaskDefinition,
    events: tuple[TaskEvidenceEvent, ...],
) -> TaskRecord:
    """Reconstruct the observable ownership/progress terminal state from evidence."""

    if any(event.task_id != definition.task_id for event in events):
        raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "task evidence identity mismatch")
    ordered = sorted(events, key=lambda item: item.sequence)
    if not ordered:
        return TaskRecord(definition=definition)
    latest = ordered[-1]
    decision = {
        TaskState.COMPLETED: TaskDecision.COMPLETE,
        TaskState.ABORTED: TaskDecision.ABORT,
        TaskState.RETRY_PENDING: TaskDecision.RETRY,
    }.get(latest.state)
    return TaskRecord(
        definition=definition,
        state=latest.state,
        owner_vehicle_id=latest.owner_vehicle_id,
        lease_generation=latest.lease_generation,
        progress_percent=latest.progress_percent,
        decision=decision,
        terminal_reason=latest.reason,
        child_mission_run_id=latest.child_mission_run_id,
        events=tuple(ordered),
    )


def _now(value: float | None) -> float:
    return time.monotonic() if value is None else value
