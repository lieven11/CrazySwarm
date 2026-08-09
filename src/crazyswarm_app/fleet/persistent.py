from __future__ import annotations

import math
import time
from enum import StrEnum
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3, VehicleCapability
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.fleet.artifacts import DeploymentManifest
from crazyswarm_app.fleet.tasks import TaskLedger


class CoverageVehicleState(StrEnum):
    ACTIVE = "ACTIVE"
    RESERVE = "RESERVE"
    HANDOVER = "HANDOVER"
    RETURNING = "RETURNING"
    UNAVAILABLE = "UNAVAILABLE"


class HandoverPhase(StrEnum):
    REQUESTED = "REQUESTED"
    REPLACEMENT_SELECTED = "REPLACEMENT_SELECTED"
    PREPARING = "PREPARING"
    TAKEOVER_PENDING = "TAKEOVER_PENDING"
    TAKEOVER_CONFIRMED = "TAKEOVER_CONFIRMED"
    OUTGOING_RELEASED = "OUTGOING_RELEASED"
    COMPLETED = "COMPLETED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class CoverageCandidate(ContractModel):
    vehicle_id: Identifier
    capabilities: frozenset[VehicleCapability]
    battery_percent: float = Field(ge=0.0, le=100.0)
    position_m: Vector3
    state: CoverageVehicleState
    connected: bool = True
    armed: bool = False
    available: bool = True

    @property
    def reserve_ready(self) -> bool:
        return (
            self.available
            and self.connected
            and not self.armed
            and self.state is CoverageVehicleState.RESERVE
        )


class AllocationDecision(ContractModel):
    task_id: Identifier
    vehicle_id: Identifier
    task_priority: int
    distance_m: float = Field(ge=0.0)
    observed_battery_percent: float = Field(ge=0.0, le=100.0)
    predicted_energy_margin_percent: float
    score: float
    reason: str


class CoverageSeparation(ContractModel):
    first_vehicle_id: Identifier
    second_vehicle_id: Identifier
    distance_m: float = Field(ge=0.0)
    threshold: Literal["CLEAR", "WARNING", "CRITICAL"]
    action: Literal["NONE", "HOLD", "BLOCK_HANDOVER"]


class HandoverEvent(ContractModel):
    sequence: int = Field(ge=1)
    handover_id: Identifier
    task_id: Identifier
    phase: HandoverPhase
    timestamp_monotonic_s: float = Field(ge=0.0)
    outgoing_vehicle_id: Identifier
    incoming_vehicle_id: Identifier | None = None
    lease_generation: int = Field(ge=1)
    reason: str


class HandoverRecord(ContractModel):
    schema_version: Literal[1] = 1
    handover_id: Identifier
    task_id: Identifier
    outgoing_vehicle_id: Identifier
    incoming_vehicle_id: Identifier | None = None
    reason: str
    phase: HandoverPhase
    outgoing_lease_generation: int = Field(ge=1)
    incoming_lease_generation: int | None = Field(default=None, ge=2)
    requested_at_monotonic_s: float = Field(ge=0.0)
    replacement_ready_at_monotonic_s: float | None = Field(default=None, ge=0.0)
    takeover_confirmed_at_monotonic_s: float | None = Field(default=None, ge=0.0)
    outgoing_released_at_monotonic_s: float | None = Field(default=None, ge=0.0)
    predicted_energy_margin_percent: float | None = None
    takeover_confirmed: bool = False
    release_reason: str | None = None
    events: tuple[HandoverEvent, ...] = ()

    @property
    def normalized_sha256(self) -> SHA256:
        return canonical_sha256(
            {
                "handover_id": self.handover_id,
                "task_id": self.task_id,
                "outgoing": self.outgoing_vehicle_id,
                "incoming": self.incoming_vehicle_id,
                "phase": self.phase,
                "outgoing_generation": self.outgoing_lease_generation,
                "incoming_generation": self.incoming_lease_generation,
                "takeover_confirmed": self.takeover_confirmed,
                "release_reason": self.release_reason,
            }
        )


class PersistentCoverageResult(ContractModel):
    status: Literal["SUCCEEDED", "DEGRADED", "FAILED"]
    reason_code: Identifier
    active_owners: dict[Identifier, Identifier]
    handovers: tuple[HandoverRecord, ...]
    separation: tuple[CoverageSeparation, ...]
    normalized_outcome_sha256: SHA256


class PersistentCoverageCoordinator:
    """Backend-neutral allocator and atomic reserve handover state machine."""

    def __init__(
        self,
        *,
        fleet_session_id: str,
        fleet_run_id: str,
        deployment: DeploymentManifest,
        task_lease_duration_s: float = 30.0,
    ) -> None:
        if len(deployment.fleet) < 3 or len(deployment.tasks) < 2:
            raise ValueError("persistent coverage requires at least three vehicles and two tasks")
        self.deployment = deployment
        self.tasks = TaskLedger(
            fleet_session_id=fleet_session_id,
            fleet_run_id=fleet_run_id,
            deployment_sha256=deployment.sha256,
            definitions=deployment.tasks,
            lease_duration_s=task_lease_duration_s,
        )
        self.vehicle_states: dict[str, CoverageVehicleState] = {
            member.vehicle_id: (
                CoverageVehicleState.RESERVE
                if member.initial_role.value == "RESERVE"
                else CoverageVehicleState.ACTIVE
            )
            for member in deployment.fleet
        }
        self._handovers: dict[str, HandoverRecord] = {}
        self._handover_sequence = 0
        self._separation: list[CoverageSeparation] = []

    def allocate_initial(
        self,
        candidates: tuple[CoverageCandidate, ...],
        *,
        allow_inadequate_energy: bool = False,
        preferred_assignments: dict[str, str] | None = None,
        now_s: float | None = None,
    ) -> tuple[AllocationDecision, ...]:
        available = {candidate.vehicle_id: candidate for candidate in candidates}
        decisions: list[AllocationDecision] = []
        claimed: set[str] = set()
        for definition in sorted(
            self.deployment.tasks,
            key=lambda item: (-item.priority, item.task_id),
        ):
            eligible = tuple(
                item
                for item in available.values()
                if item.vehicle_id not in claimed
                and item.available
                and item.connected
                and item.state is CoverageVehicleState.ACTIVE
                and (
                    preferred_assignments is None
                    or item.vehicle_id == preferred_assignments.get(definition.task_id)
                )
            )
            decision = self._select(
                definition.task_id,
                eligible,
                allow_inadequate_energy=allow_inadequate_energy,
            )
            self.tasks.assign(
                definition.task_id,
                decision.vehicle_id,
                capabilities=available[decision.vehicle_id].capabilities,
                battery_percent=available[decision.vehicle_id].battery_percent,
                allow_inadequate_energy=allow_inadequate_energy,
                now_s=now_s,
            )
            claimed.add(decision.vehicle_id)
            decisions.append(decision)
        if len(decisions) != len(self.deployment.tasks):
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "coverage allocation is incomplete")
        return tuple(decisions)

    def begin_handover(
        self,
        task_id: str,
        *,
        reason: str,
        candidates: tuple[CoverageCandidate, ...],
        now_s: float | None = None,
    ) -> HandoverRecord:
        task = self.tasks.record(task_id)
        if task.owner_vehicle_id is None or task.lease is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task has no current owner")
        if any(
            item.task_id == task_id
            and item.phase
            not in {
                HandoverPhase.COMPLETED,
                HandoverPhase.DEGRADED,
                HandoverPhase.FAILED,
            }
            for item in self._handovers.values()
        ):
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "task already has an active handover")
        timestamp = _now(now_s)
        handover_id = f"handover-{task_id}-{task.lease_generation + 1}"
        record = HandoverRecord(
            handover_id=handover_id,
            task_id=task_id,
            outgoing_vehicle_id=task.owner_vehicle_id,
            reason=reason,
            phase=HandoverPhase.REQUESTED,
            outgoing_lease_generation=task.lease_generation,
            requested_at_monotonic_s=timestamp,
        )
        record = self._event(record, HandoverPhase.REQUESTED, reason, timestamp)
        current_owners = {
            item.owner_vehicle_id for item in self.tasks.records() if item.owner_vehicle_id
        }
        reserved_for_other_handover = {
            item.incoming_vehicle_id
            for item in self._handovers.values()
            if item.phase
            not in {
                HandoverPhase.COMPLETED,
                HandoverPhase.DEGRADED,
                HandoverPhase.FAILED,
            }
        }
        eligible = tuple(
            item
            for item in candidates
            if item.reserve_ready
            and item.vehicle_id not in current_owners
            and item.vehicle_id not in reserved_for_other_handover
        )
        try:
            decision = self._select(task_id, eligible)
        except CrazySwarmError:
            record = self._event(
                record.model_copy(update={"phase": HandoverPhase.DEGRADED}),
                HandoverPhase.DEGRADED,
                "NO_SERVICEABLE_RESERVE",
                timestamp,
            )
            self._handovers[handover_id] = record
            return record
        record = record.model_copy(
            update={
                "incoming_vehicle_id": decision.vehicle_id,
                "phase": HandoverPhase.PREPARING,
                "predicted_energy_margin_percent": decision.predicted_energy_margin_percent,
            }
        )
        record = self._event(record, HandoverPhase.REPLACEMENT_SELECTED, reason, timestamp)
        record = self._event(
            record,
            HandoverPhase.PREPARING,
            "replacement preparation started",
            timestamp,
        )
        self.vehicle_states[decision.vehicle_id] = CoverageVehicleState.HANDOVER
        self._handovers[handover_id] = record
        return record

    def confirm_replacement_ready(
        self,
        handover_id: str,
        *,
        candidates: tuple[CoverageCandidate, ...],
        now_s: float | None = None,
    ) -> HandoverRecord:
        record = self.handover(handover_id)
        if record.phase is not HandoverPhase.PREPARING or record.incoming_vehicle_id is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "handover is not preparing")
        incoming = _candidate(candidates, record.incoming_vehicle_id)
        if not incoming.connected or not incoming.available:
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "replacement is unavailable")
        timestamp = _now(now_s)
        updated = record.model_copy(
            update={
                "phase": HandoverPhase.TAKEOVER_PENDING,
                "replacement_ready_at_monotonic_s": timestamp,
            }
        )
        updated = self._event(
            updated,
            HandoverPhase.TAKEOVER_PENDING,
            "replacement ready; outgoing lease retained",
            timestamp,
        )
        self._handovers[handover_id] = updated
        return updated

    def confirm_takeover(
        self,
        handover_id: str,
        *,
        candidates: tuple[CoverageCandidate, ...],
        now_s: float | None = None,
    ) -> HandoverRecord:
        record = self.handover(handover_id)
        if record.phase is not HandoverPhase.TAKEOVER_PENDING or record.incoming_vehicle_id is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "replacement is not ready for takeover")
        incoming = _candidate(candidates, record.incoming_vehicle_id)
        self.enforce_separation(candidates)
        timestamp = _now(now_s)
        transferred = self.tasks.transfer(
            record.task_id,
            record.outgoing_vehicle_id,
            incoming.vehicle_id,
            expected_generation=record.outgoing_lease_generation,
            capabilities=incoming.capabilities,
            battery_percent=incoming.battery_percent,
            reason=record.reason,
            now_s=timestamp,
        )
        updated = record.model_copy(
            update={
                "phase": HandoverPhase.TAKEOVER_CONFIRMED,
                "incoming_lease_generation": transferred.lease_generation,
                "takeover_confirmed_at_monotonic_s": timestamp,
                "takeover_confirmed": True,
            }
        )
        updated = self._event(
            updated,
            HandoverPhase.TAKEOVER_CONFIRMED,
            "atomic task lease transfer confirmed",
            timestamp,
        )
        self.vehicle_states[incoming.vehicle_id] = CoverageVehicleState.ACTIVE
        self.vehicle_states[record.outgoing_vehicle_id] = CoverageVehicleState.RETURNING
        self._handovers[handover_id] = updated
        return updated

    def release_outgoing(
        self,
        handover_id: str,
        *,
        reason: str = "takeover confirmed; outgoing released to return",
        now_s: float | None = None,
    ) -> HandoverRecord:
        record = self.handover(handover_id)
        if record.phase is not HandoverPhase.TAKEOVER_CONFIRMED or not record.takeover_confirmed:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "outgoing vehicle cannot be released before confirmed takeover",
            )
        timestamp = _now(now_s)
        updated = record.model_copy(
            update={
                "phase": HandoverPhase.OUTGOING_RELEASED,
                "outgoing_released_at_monotonic_s": timestamp,
                "release_reason": reason,
            }
        )
        updated = self._event(updated, HandoverPhase.OUTGOING_RELEASED, reason, timestamp)
        updated = updated.model_copy(update={"phase": HandoverPhase.COMPLETED})
        updated = self._event(updated, HandoverPhase.COMPLETED, "handover completed", timestamp)
        self._handovers[handover_id] = updated
        return updated

    def terminate_handover(
        self,
        handover_id: str,
        *,
        reason: str,
        failed: bool = False,
        now_s: float | None = None,
    ) -> HandoverRecord:
        """End an unconfirmed handover explicitly while retaining the outgoing lease."""

        record = self.handover(handover_id)
        if record.takeover_confirmed or record.phase is HandoverPhase.COMPLETED:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "confirmed or completed handover cannot be terminated as unconfirmed",
            )
        timestamp = _now(now_s)
        phase = HandoverPhase.FAILED if failed else HandoverPhase.DEGRADED
        updated = record.model_copy(update={"phase": phase, "release_reason": reason})
        updated = self._event(updated, phase, reason, timestamp)
        if record.incoming_vehicle_id is not None:
            self.vehicle_states[record.incoming_vehicle_id] = CoverageVehicleState.RESERVE
        self._handovers[handover_id] = updated
        return updated

    def fail_handover(
        self,
        handover_id: str,
        *,
        reason: str,
        now_s: float | None = None,
    ) -> HandoverRecord:
        """Record a terminal failure after ownership may already have transferred."""

        record = self.handover(handover_id)
        if record.phase is HandoverPhase.FAILED:
            return record
        timestamp = _now(now_s)
        updated = record.model_copy(
            update={"phase": HandoverPhase.FAILED, "release_reason": reason}
        )
        updated = self._event(updated, HandoverPhase.FAILED, reason, timestamp)
        if record.incoming_vehicle_id is not None:
            self.vehicle_states[record.incoming_vehicle_id] = CoverageVehicleState.UNAVAILABLE
        self._handovers[handover_id] = updated
        return updated

    def enforce_separation(
        self, candidates: tuple[CoverageCandidate, ...]
    ) -> tuple[CoverageSeparation, ...]:
        observations: list[CoverageSeparation] = []
        positioned = sorted(
            (item for item in candidates if item.available),
            key=lambda item: item.vehicle_id,
        )
        for index, first in enumerate(positioned):
            for second in positioned[index + 1 :]:
                distance = _distance(first.position_m, second.position_m)
                if distance <= self.deployment.constraints.critical_separation_m:
                    threshold: Literal["CLEAR", "WARNING", "CRITICAL"] = "CRITICAL"
                    action: Literal["NONE", "HOLD", "BLOCK_HANDOVER"] = "BLOCK_HANDOVER"
                elif distance <= self.deployment.constraints.warning_separation_m:
                    threshold = "WARNING"
                    action = "HOLD"
                else:
                    threshold = "CLEAR"
                    action = "NONE"
                observations.append(
                    CoverageSeparation(
                        first_vehicle_id=first.vehicle_id,
                        second_vehicle_id=second.vehicle_id,
                        distance_m=distance,
                        threshold=threshold,
                        action=action,
                    )
                )
        self._separation.extend(observations)
        if any(item.threshold == "CRITICAL" for item in observations):
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "critical separation blocks handover",
            )
        return tuple(observations)

    def handover(self, handover_id: str) -> HandoverRecord:
        try:
            return self._handovers[handover_id]
        except KeyError as error:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "unknown handover") from error

    def result(self) -> PersistentCoverageResult:
        handovers = tuple(self._handovers[key] for key in sorted(self._handovers))
        degraded = any(item.phase is HandoverPhase.DEGRADED for item in handovers)
        failed = any(item.phase is HandoverPhase.FAILED for item in handovers)
        status: Literal["SUCCEEDED", "DEGRADED", "FAILED"] = (
            "FAILED" if failed else "DEGRADED" if degraded else "SUCCEEDED"
        )
        owners = {
            item.definition.task_id: item.owner_vehicle_id
            for item in self.tasks.records()
            if item.owner_vehicle_id is not None
        }
        normalized = {
            "status": status,
            "owners": owners,
            "handovers": [item.normalized_sha256 for item in handovers],
            "separation": [
                {
                    "pair": [item.first_vehicle_id, item.second_vehicle_id],
                    "threshold": item.threshold,
                    "action": item.action,
                    "distance_m": round(item.distance_m, 6),
                }
                for item in self._separation
            ],
        }
        return PersistentCoverageResult(
            status=status,
            reason_code={
                "SUCCEEDED": "COVERAGE_MAINTAINED",
                "DEGRADED": "NO_SERVICEABLE_RESERVE",
                "FAILED": "HANDOVER_FAILED",
            }[status],
            active_owners=owners,
            handovers=handovers,
            separation=tuple(self._separation),
            normalized_outcome_sha256=canonical_sha256(normalized),
        )

    def _select(
        self,
        task_id: str,
        candidates: tuple[CoverageCandidate, ...],
        *,
        allow_inadequate_energy: bool = False,
    ) -> AllocationDecision:
        definition = self.tasks.record(task_id).definition
        zone = next(item for item in self.deployment.zones if item.zone_id == definition.zone_id)
        required_energy = definition.estimated_energy_percent + definition.energy_margin_percent
        decisions: list[AllocationDecision] = []
        for candidate in candidates:
            if not definition.required_capabilities.issubset(candidate.capabilities):
                continue
            margin = candidate.battery_percent - required_energy
            if margin < 0.0 and not allow_inadequate_energy:
                continue
            distance = _distance(candidate.position_m, zone.geometry.center_m)
            score = definition.priority * 1000.0 + margin - distance * 10.0
            decisions.append(
                AllocationDecision(
                    task_id=task_id,
                    vehicle_id=candidate.vehicle_id,
                    task_priority=definition.priority,
                    distance_m=distance,
                    observed_battery_percent=candidate.battery_percent,
                    predicted_energy_margin_percent=margin,
                    score=score,
                    reason="capability, availability, energy margin, distance, and priority",
                )
            )
        if not decisions:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "no serviceable vehicle satisfies coverage allocation",
            )
        return max(decisions, key=lambda item: (item.score, item.vehicle_id))

    def _event(
        self,
        record: HandoverRecord,
        phase: HandoverPhase,
        reason: str,
        timestamp_s: float,
    ) -> HandoverRecord:
        self._handover_sequence += 1
        event = HandoverEvent(
            sequence=self._handover_sequence,
            handover_id=record.handover_id,
            task_id=record.task_id,
            phase=phase,
            timestamp_monotonic_s=timestamp_s,
            outgoing_vehicle_id=record.outgoing_vehicle_id,
            incoming_vehicle_id=record.incoming_vehicle_id,
            lease_generation=record.incoming_lease_generation or record.outgoing_lease_generation,
            reason=reason,
        )
        return record.model_copy(update={"phase": phase, "events": (*record.events, event)})


def _candidate(candidates: tuple[CoverageCandidate, ...], vehicle_id: str) -> CoverageCandidate:
    for candidate in candidates:
        if candidate.vehicle_id == vehicle_id:
            return candidate
    raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "handover vehicle is unavailable")


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )


def _now(value: float | None) -> float:
    return time.monotonic() if value is None else value
