from __future__ import annotations

import time
from enum import StrEnum
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.fleet.artifacts import DockDefinition
from crazyswarm_app.fleet.persistent import HandoverPhase, HandoverRecord


class DockHealth(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class DockOperationState(StrEnum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    RETURN_TO_DOCK_AREA = "RETURN_TO_DOCK_AREA"
    APPROACH_REQUESTED = "APPROACH_REQUESTED"
    DOCK_ATTEMPT = "DOCK_ATTEMPT"
    LANDED_UNCONFIRMED = "LANDED_UNCONFIRMED"
    CHARGING_CONFIRMED = "CHARGING_CONFIRMED"
    CHARGING = "CHARGING"
    READY = "READY"
    FAILED = "FAILED"
    RETRY_PENDING = "RETRY_PENDING"
    DIVERTED = "DIVERTED"
    QUEUED = "QUEUED"


class DockEvent(ContractModel):
    sequence: int = Field(ge=1)
    reservation_id: Identifier
    dock_id: Identifier
    vehicle_id: Identifier
    state: DockOperationState
    timestamp_monotonic_s: float = Field(ge=0.0)
    event_type: Identifier
    reason: str
    evidence_class: Literal["SIMULATED_MODEL"] = "SIMULATED_MODEL"
    scheduling_model: Literal["dock-charge-scheduler-v1"] = "dock-charge-scheduler-v1"


class DockReservation(ContractModel):
    schema_version: Literal[1] = 1
    reservation_id: Identifier
    dock_id: Identifier
    vehicle_id: Identifier
    state: DockOperationState
    created_at_monotonic_s: float = Field(ge=0.0)
    expires_at_monotonic_s: float = Field(gt=0.0)
    queue_position: int | None = Field(default=None, ge=1)
    attempts: int = Field(default=0, ge=0)
    maximum_attempts: int = Field(default=2, ge=1)
    modeled_landing_observed: bool = False
    modeled_contact_observed: bool = False
    modeled_charging_confirmed: bool = False
    battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    target_battery_percent: float = Field(default=90.0, gt=0.0, le=100.0)
    charging_started_at_monotonic_s: float | None = Field(default=None, ge=0.0)
    estimated_ready_at_monotonic_s: float | None = Field(default=None, ge=0.0)
    terminal_reason: str | None = None
    events: tuple[DockEvent, ...] = ()


class DockSnapshot(ContractModel):
    dock_id: Identifier
    capacity: int = Field(ge=1)
    health: DockHealth
    supported_charging_capability: Identifier
    occupied_vehicle_ids: tuple[Identifier, ...]
    queued_vehicle_ids: tuple[Identifier, ...]
    reservations: tuple[DockReservation, ...]


class DockManager:
    """Software-only dock capacity, queue, retry, and modeled-charge scheduler."""

    def __init__(
        self,
        definitions: tuple[DockDefinition, ...],
        *,
        reservation_ttl_s: float = 120.0,
        maximum_attempts: int = 2,
        queue_limit: int = 8,
    ) -> None:
        if not definitions:
            raise ValueError("dock manager requires at least one dock")
        if reservation_ttl_s <= 0.0 or maximum_attempts < 1 or queue_limit < 1:
            raise ValueError("dock scheduler bounds must be positive")
        self.definitions = {item.dock_id: item for item in definitions}
        self.health = {item.dock_id: DockHealth.AVAILABLE for item in definitions}
        self.reservation_ttl_s = reservation_ttl_s
        self.maximum_attempts = maximum_attempts
        self.queue_limit = queue_limit
        self._reservations: dict[str, DockReservation] = {}
        self._sequence = 0

    def reserve(
        self,
        vehicle_id: str,
        *,
        preferred_dock_id: str | None = None,
        battery_percent: float | None = None,
        target_battery_percent: float = 90.0,
        now_s: float | None = None,
    ) -> DockReservation:
        if any(
            item.vehicle_id == vehicle_id and not _terminal(item.state)
            for item in self._reservations.values()
        ):
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle already has a dock request")
        candidates = (
            (self._definition(preferred_dock_id),)
            if preferred_dock_id is not None
            else tuple(self.definitions[key] for key in sorted(self.definitions))
        )
        usable = [
            item for item in candidates if self.health[item.dock_id] is not DockHealth.UNAVAILABLE
        ]
        if not usable:
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "no dock is available")
        selected = min(usable, key=lambda item: (self._occupancy(item.dock_id), item.dock_id))
        queued = self._occupancy(selected.dock_id) >= selected.capacity
        if queued and self._queue_length(selected.dock_id) >= self.queue_limit:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "dock queue capacity is exhausted")
        timestamp = _now(now_s)
        reservation_id = f"dock-{selected.dock_id}-{vehicle_id}"
        reservation = DockReservation(
            reservation_id=reservation_id,
            dock_id=selected.dock_id,
            vehicle_id=vehicle_id,
            state=DockOperationState.QUEUED if queued else DockOperationState.RESERVED,
            created_at_monotonic_s=timestamp,
            expires_at_monotonic_s=timestamp + self.reservation_ttl_s,
            queue_position=(self._queue_length(selected.dock_id) + 1 if queued else None),
            maximum_attempts=self.maximum_attempts,
            battery_percent=battery_percent,
            target_battery_percent=target_battery_percent,
        )
        event = "DOCK_QUEUED" if queued else "DOCK_RESERVED"
        reservation = self._event(reservation, event, "software dock allocation", timestamp)
        self._reservations[reservation_id] = reservation
        return reservation

    def reserve_after_handover(
        self,
        handover: HandoverRecord,
        *,
        battery_percent: float | None,
        now_s: float | None = None,
    ) -> DockReservation:
        if handover.phase is not HandoverPhase.COMPLETED or not handover.takeover_confirmed:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "dock return cannot start before confirmed takeover and release",
            )
        reservation = self.reserve(
            handover.outgoing_vehicle_id,
            battery_percent=battery_percent,
            now_s=now_s,
        )
        if reservation.state is DockOperationState.RESERVED:
            return self.transition(
                reservation.reservation_id,
                DockOperationState.RETURN_TO_DOCK_AREA,
                reason="outgoing vehicle released after takeover",
                now_s=now_s,
            )
        return reservation

    def transition(
        self,
        reservation_id: str,
        target: DockOperationState,
        *,
        reason: str,
        now_s: float | None = None,
    ) -> DockReservation:
        reservation = self.reservation(reservation_id)
        allowed = {
            DockOperationState.RESERVED: {DockOperationState.RETURN_TO_DOCK_AREA},
            DockOperationState.RETURN_TO_DOCK_AREA: {DockOperationState.APPROACH_REQUESTED},
            DockOperationState.APPROACH_REQUESTED: {DockOperationState.DOCK_ATTEMPT},
            DockOperationState.RETRY_PENDING: {
                DockOperationState.APPROACH_REQUESTED,
                DockOperationState.DIVERTED,
            },
        }
        if target not in allowed.get(reservation.state, set()):
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "invalid dock lifecycle transition")
        timestamp = _now(now_s)
        attempts = reservation.attempts + (1 if target is DockOperationState.DOCK_ATTEMPT else 0)
        updated = reservation.model_copy(update={"state": target, "attempts": attempts})
        updated = self._event(updated, f"DOCK_{target.value}", reason, timestamp)
        self._reservations[reservation_id] = updated
        return updated

    def confirm_modeled_landing(
        self,
        reservation_id: str,
        *,
        modeled_contact: bool,
        now_s: float | None = None,
    ) -> DockReservation:
        reservation = self.reservation(reservation_id)
        if reservation.state is not DockOperationState.DOCK_ATTEMPT:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "dock attempt is not active")
        timestamp = _now(now_s)
        updated = reservation.model_copy(
            update={
                "state": DockOperationState.LANDED_UNCONFIRMED,
                "modeled_landing_observed": True,
                "modeled_contact_observed": modeled_contact,
            }
        )
        updated = self._event(
            updated,
            "MODELED_LANDING_OBSERVED",
            "modeled contact observed" if modeled_contact else "modeled contact absent",
            timestamp,
        )
        self._reservations[reservation_id] = updated
        return updated

    def confirm_modeled_charging(
        self,
        reservation_id: str,
        *,
        confirmed: bool,
        now_s: float | None = None,
    ) -> DockReservation:
        reservation = self.reservation(reservation_id)
        if reservation.state is not DockOperationState.LANDED_UNCONFIRMED:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "modeled landing is not awaiting charge")
        timestamp = _now(now_s)
        if not confirmed or not reservation.modeled_contact_observed:
            terminal = reservation.attempts >= reservation.maximum_attempts
            target = DockOperationState.FAILED if terminal else DockOperationState.RETRY_PENDING
            updated = reservation.model_copy(
                update={
                    "state": target,
                    "terminal_reason": "LANDED_NOT_CHARGING" if terminal else None,
                }
            )
            updated = self._event(
                updated,
                "MODELED_CHARGING_CONFIRMATION_FAILED",
                "landed but modeled charging was not confirmed",
                timestamp,
            )
            self._reservations[reservation_id] = updated
            return updated
        definition = self._definition(reservation.dock_id)
        current = reservation.battery_percent or 0.0
        duration_s = max(
            0.0,
            (reservation.target_battery_percent - current)
            / definition.modeled_charge_rate_percent_per_min
            * 60.0,
        )
        updated = reservation.model_copy(
            update={
                "state": DockOperationState.CHARGING_CONFIRMED,
                "modeled_charging_confirmed": True,
                "charging_started_at_monotonic_s": timestamp,
                "estimated_ready_at_monotonic_s": timestamp + duration_s,
            }
        )
        updated = self._event(
            updated,
            "MODELED_CHARGING_CONFIRMED",
            "software scheduling model only; no physical charge claim",
            timestamp,
        )
        self._reservations[reservation_id] = updated
        return updated

    def update_modeled_charge(
        self,
        reservation_id: str,
        *,
        now_s: float | None = None,
    ) -> DockReservation:
        reservation = self.reservation(reservation_id)
        if reservation.state not in {
            DockOperationState.CHARGING_CONFIRMED,
            DockOperationState.CHARGING,
        }:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "modeled charging is not active")
        assert reservation.charging_started_at_monotonic_s is not None
        timestamp = _now(now_s)
        definition = self._definition(reservation.dock_id)
        elapsed_min = max(0.0, timestamp - reservation.charging_started_at_monotonic_s) / 60.0
        initial = reservation.battery_percent or 0.0
        battery = min(
            reservation.target_battery_percent,
            initial + elapsed_min * definition.modeled_charge_rate_percent_per_min,
        )
        ready = battery >= reservation.target_battery_percent
        target = DockOperationState.READY if ready else DockOperationState.CHARGING
        updated = reservation.model_copy(update={"state": target, "battery_percent": battery})
        updated = self._event(
            updated,
            "MODELED_CHARGE_READY" if ready else "MODELED_CHARGE_PROGRESS",
            "software scheduling model",
            timestamp,
        )
        self._reservations[reservation_id] = updated
        if ready:
            self._promote_queue(reservation.dock_id, timestamp)
        return updated

    def set_health(
        self,
        dock_id: str,
        health: DockHealth,
        *,
        now_s: float | None = None,
    ) -> DockSnapshot:
        self._definition(dock_id)
        self.health[dock_id] = health
        if health is DockHealth.UNAVAILABLE:
            timestamp = _now(now_s)
            for reservation in tuple(self._reservations.values()):
                if reservation.dock_id == dock_id and not _terminal(reservation.state):
                    target = (
                        DockOperationState.QUEUED
                        if reservation.state is DockOperationState.QUEUED
                        else DockOperationState.DIVERTED
                    )
                    updated = reservation.model_copy(
                        update={"state": target, "terminal_reason": "DOCK_UNAVAILABLE"}
                    )
                    self._reservations[reservation.reservation_id] = self._event(
                        updated,
                        "DOCK_UNAVAILABLE",
                        "dock health changed to unavailable",
                        timestamp,
                    )
        return self.snapshot(dock_id)

    def reservation(self, reservation_id: str) -> DockReservation:
        try:
            return self._reservations[reservation_id]
        except KeyError as error:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "unknown dock reservation") from error

    def snapshot(self, dock_id: str) -> DockSnapshot:
        definition = self._definition(dock_id)
        reservations = tuple(
            sorted(
                (item for item in self._reservations.values() if item.dock_id == dock_id),
                key=lambda item: item.reservation_id,
            )
        )
        return DockSnapshot(
            dock_id=dock_id,
            capacity=definition.capacity,
            health=self.health[dock_id],
            supported_charging_capability=definition.supported_charging_capability,
            occupied_vehicle_ids=tuple(
                item.vehicle_id for item in reservations if _occupies_capacity(item.state)
            ),
            queued_vehicle_ids=tuple(
                item.vehicle_id for item in reservations if item.state is DockOperationState.QUEUED
            ),
            reservations=reservations,
        )

    def _definition(self, dock_id: str | None) -> DockDefinition:
        if dock_id is None:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "dock identity is required")
        try:
            return self.definitions[dock_id]
        except KeyError as error:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "unknown dock") from error

    def _occupancy(self, dock_id: str) -> int:
        return sum(
            item.dock_id == dock_id and _occupies_capacity(item.state)
            for item in self._reservations.values()
        )

    def _queue_length(self, dock_id: str) -> int:
        return sum(
            item.dock_id == dock_id and item.state is DockOperationState.QUEUED
            for item in self._reservations.values()
        )

    def _promote_queue(self, dock_id: str, now_s: float) -> None:
        definition = self._definition(dock_id)
        if self._occupancy(dock_id) >= definition.capacity:
            return
        queued = sorted(
            (
                item
                for item in self._reservations.values()
                if item.dock_id == dock_id and item.state is DockOperationState.QUEUED
            ),
            key=lambda item: (item.created_at_monotonic_s, item.reservation_id),
        )
        if not queued:
            return
        selected = queued[0].model_copy(
            update={"state": DockOperationState.RESERVED, "queue_position": None}
        )
        self._reservations[selected.reservation_id] = self._event(
            selected,
            "DOCK_QUEUE_PROMOTED",
            "capacity released",
            now_s,
        )

    def _event(
        self,
        reservation: DockReservation,
        event_type: str,
        reason: str,
        timestamp_s: float,
    ) -> DockReservation:
        self._sequence += 1
        event = DockEvent(
            sequence=self._sequence,
            reservation_id=reservation.reservation_id,
            dock_id=reservation.dock_id,
            vehicle_id=reservation.vehicle_id,
            state=reservation.state,
            timestamp_monotonic_s=timestamp_s,
            event_type=event_type,
            reason=reason,
        )
        return reservation.model_copy(update={"events": (*reservation.events, event)})


def _occupies_capacity(state: DockOperationState) -> bool:
    return state not in {
        DockOperationState.AVAILABLE,
        DockOperationState.READY,
        DockOperationState.FAILED,
        DockOperationState.DIVERTED,
        DockOperationState.QUEUED,
    }


def _terminal(state: DockOperationState) -> bool:
    return state in {
        DockOperationState.READY,
        DockOperationState.FAILED,
        DockOperationState.DIVERTED,
    }


def _now(value: float | None) -> float:
    return time.monotonic() if value is None else value
