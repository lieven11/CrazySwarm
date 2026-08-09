from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class FleetMetricKind(StrEnum):
    TASK_DECLARED = "TASK_DECLARED"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    LEASE_ISSUED = "LEASE_ISSUED"
    HANDOVER_DECISION = "HANDOVER_DECISION"
    REPLACEMENT_LAUNCHED = "REPLACEMENT_LAUNCHED"
    TAKEOVER_CONFIRMED = "TAKEOVER_CONFIRMED"
    OUTGOING_RELEASED = "OUTGOING_RELEASED"
    HANDOVER_COMPLETED = "HANDOVER_COMPLETED"
    COVERAGE_GAP_STARTED = "COVERAGE_GAP_STARTED"
    COVERAGE_GAP_ENDED = "COVERAGE_GAP_ENDED"
    SEPARATION_OBSERVED = "SEPARATION_OBSERVED"
    ENERGY_MARGIN = "ENERGY_MARGIN"
    DOCK_QUEUED = "DOCK_QUEUED"
    DOCK_ATTEMPT = "DOCK_ATTEMPT"
    DOCK_CHARGING = "DOCK_CHARGING"
    DOCK_READY = "DOCK_READY"
    FAULT_DETECTED = "FAULT_DETECTED"
    RECOVERY_COMMAND = "RECOVERY_COMMAND"
    STABILIZED = "STABILIZED"
    REASSIGNED = "REASSIGNED"
    DROP_COUNT = "DROP_COUNT"
    TELEMETRY_SAMPLE = "TELEMETRY_SAMPLE"
    COMMAND_SENT = "COMMAND_SENT"
    COMMAND_ACKNOWLEDGED = "COMMAND_ACKNOWLEDGED"
    POSITION_QUALITY = "POSITION_QUALITY"


class FleetMetricEvent(ContractModel):
    sequence: int = Field(ge=1)
    kind: FleetMetricKind
    timestamp_s: float = Field(ge=0.0)
    correlation_id: Identifier
    vehicle_id: Identifier | None = None
    task_id: Identifier | None = None
    value: float | None = None
    count: int | None = Field(default=None, ge=0)
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class HandoverTiming(ContractModel):
    handover_id: Identifier
    decision_to_launch_s: float | None = Field(default=None, ge=0.0)
    decision_to_takeover_s: float | None = Field(default=None, ge=0.0)
    takeover_to_release_s: float | None = Field(default=None, ge=0.0)
    total_handover_s: float | None = Field(default=None, ge=0.0)


class FaultRecoveryTiming(ContractModel):
    fault_id: Identifier
    detection_to_command_s: float | None = Field(default=None, ge=0.0)
    detection_to_stabilization_s: float | None = Field(default=None, ge=0.0)
    detection_to_reassignment_s: float | None = Field(default=None, ge=0.0)


class DockTiming(ContractModel):
    reservation_id: Identifier
    queue_time_s: float = Field(ge=0.0)
    attempts: int = Field(ge=0)
    modeled_charge_time_s: float = Field(ge=0.0)
    total_ready_time_s: float = Field(ge=0.0)


class EnergyMarginMetric(ContractModel):
    correlation_id: Identifier
    vehicle_id: Identifier | None = None
    stage: str
    margin_percent: float


class FleetMetricsReport(ContractModel):
    schema_version: Literal[1] = 1
    source_class: Literal["DERIVED"] = "DERIVED"
    scheduling_model: Literal["fleet-metrics-v1"] = "fleet-metrics-v1"
    duration_s: float = Field(ge=0.0)
    coverage_gap_duration_s: float = Field(ge=0.0)
    coverage_gap_percent: float = Field(ge=0.0, le=100.0)
    mission_availability_percent: float = Field(ge=0.0, le=100.0)
    minimum_separation_m: float | None = Field(default=None, ge=0.0)
    warning_separation_violations: int = Field(ge=0)
    critical_separation_violations: int = Field(ge=0)
    task_assignment_latency_s: dict[Identifier, float]
    ownership_lease_latency_s: dict[Identifier, float]
    handovers: tuple[HandoverTiming, ...]
    energy_margins: tuple[EnergyMarginMetric, ...]
    docks: tuple[DockTiming, ...]
    faults: tuple[FaultRecoveryTiming, ...]
    drop_counts: dict[Identifier, int]
    telemetry_update_rate_hz: dict[Identifier, float]
    command_latency_ms: dict[Identifier, float]
    mean_position_quality_percent: dict[Identifier, float]
    event_count: int = Field(ge=0)
    normalized_metrics_sha256: SHA256


class FleetMetricsCollector:
    """Derives fleet metrics from timestamped semantic events, never simulator internals."""

    def __init__(
        self,
        *,
        started_at_s: float,
        required_coverage_roles: int,
        warning_separation_m: float,
        critical_separation_m: float,
    ) -> None:
        if started_at_s < 0.0 or required_coverage_roles < 1:
            raise ValueError("metrics clock and required coverage roles must be valid")
        self.started_at_s = started_at_s
        self.required_coverage_roles = required_coverage_roles
        self.warning_separation_m = warning_separation_m
        self.critical_separation_m = critical_separation_m
        self._events: list[FleetMetricEvent] = []

    def record(
        self,
        kind: FleetMetricKind,
        *,
        timestamp_s: float,
        correlation_id: str,
        vehicle_id: str | None = None,
        task_id: str | None = None,
        value: float | None = None,
        count: int | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> FleetMetricEvent:
        event = FleetMetricEvent(
            sequence=len(self._events) + 1,
            kind=kind,
            timestamp_s=timestamp_s,
            correlation_id=correlation_id,
            vehicle_id=vehicle_id,
            task_id=task_id,
            value=value,
            count=count,
            details=details or {},
        )
        self._events.append(event)
        return event

    def report(self, *, ended_at_s: float) -> FleetMetricsReport:
        duration = max(0.0, ended_at_s - self.started_at_s)
        ordered = sorted(self._events, key=lambda item: (item.timestamp_s, item.sequence))
        gaps = self._interval_total(
            ordered,
            FleetMetricKind.COVERAGE_GAP_STARTED,
            FleetMetricKind.COVERAGE_GAP_ENDED,
            ended_at_s,
        )
        role_time = duration * self.required_coverage_roles
        gap_percent = min(100.0, 0.0 if role_time <= 0.0 else gaps / role_time * 100.0)
        separation = [
            item.value
            for item in ordered
            if item.kind is FleetMetricKind.SEPARATION_OBSERVED and item.value is not None
        ]
        assignment = self._latencies(
            ordered,
            FleetMetricKind.TASK_DECLARED,
            FleetMetricKind.TASK_ASSIGNED,
        )
        leases = self._latencies(
            ordered,
            FleetMetricKind.TASK_DECLARED,
            FleetMetricKind.LEASE_ISSUED,
        )
        handovers = tuple(
            self._handover_timing(key, values)
            for key, values in sorted(_group(ordered, _is_handover).items())
        )
        faults = tuple(
            self._fault_timing(key, values)
            for key, values in sorted(_group(ordered, _is_fault).items())
        )
        docks = tuple(
            self._dock_timing(key, values)
            for key, values in sorted(_group(ordered, _is_dock).items())
        )
        energy = tuple(
            EnergyMarginMetric(
                correlation_id=item.correlation_id,
                vehicle_id=item.vehicle_id,
                stage=str(item.details.get("stage", "unknown")),
                margin_percent=item.value,
            )
            for item in ordered
            if item.kind is FleetMetricKind.ENERGY_MARGIN and item.value is not None
        )
        drop_counts: dict[str, int] = defaultdict(int)
        for item in ordered:
            if item.kind is FleetMetricKind.DROP_COUNT:
                drop_counts[item.correlation_id] += item.count or 0
        update_rates = _update_rates(ordered)
        command_latency = {
            key: value * 1000.0
            for key, value in self._latencies(
                ordered,
                FleetMetricKind.COMMAND_SENT,
                FleetMetricKind.COMMAND_ACKNOWLEDGED,
            ).items()
        }
        position_quality = _mean_values(ordered, FleetMetricKind.POSITION_QUALITY)
        normalized = {
            "duration_s": round(duration, 6),
            "coverage_gap_duration_s": round(gaps, 6),
            "coverage_gap_percent": round(gap_percent, 6),
            "minimum_separation_m": None if not separation else round(min(separation), 6),
            "warning": sum(
                value <= self.warning_separation_m and value > self.critical_separation_m
                for value in separation
            ),
            "critical": sum(value <= self.critical_separation_m for value in separation),
            "assignment": assignment,
            "leases": leases,
            "handovers": [item.model_dump(mode="json") for item in handovers],
            "energy": [item.model_dump(mode="json") for item in energy],
            "docks": [item.model_dump(mode="json") for item in docks],
            "faults": [item.model_dump(mode="json") for item in faults],
            "drops": dict(sorted(drop_counts.items())),
            "update_rates": update_rates,
            "command_latency_ms": command_latency,
            "position_quality": position_quality,
        }
        return FleetMetricsReport(
            duration_s=duration,
            coverage_gap_duration_s=gaps,
            coverage_gap_percent=gap_percent,
            mission_availability_percent=100.0 - gap_percent,
            minimum_separation_m=min(separation) if separation else None,
            warning_separation_violations=normalized["warning"],
            critical_separation_violations=normalized["critical"],
            task_assignment_latency_s=assignment,
            ownership_lease_latency_s=leases,
            handovers=handovers,
            energy_margins=energy,
            docks=docks,
            faults=faults,
            drop_counts=dict(sorted(drop_counts.items())),
            telemetry_update_rate_hz=update_rates,
            command_latency_ms=command_latency,
            mean_position_quality_percent=position_quality,
            event_count=len(ordered),
            normalized_metrics_sha256=canonical_sha256(normalized),
        )

    @staticmethod
    def _interval_total(
        events: list[FleetMetricEvent],
        start_kind: FleetMetricKind,
        end_kind: FleetMetricKind,
        ended_at_s: float,
    ) -> float:
        opened: dict[str, float] = {}
        total = 0.0
        for event in events:
            if event.kind is start_kind:
                opened.setdefault(event.correlation_id, event.timestamp_s)
            elif event.kind is end_kind and event.correlation_id in opened:
                total += max(0.0, event.timestamp_s - opened.pop(event.correlation_id))
        total += sum(max(0.0, ended_at_s - start) for start in opened.values())
        return total

    @staticmethod
    def _latencies(
        events: list[FleetMetricEvent],
        start_kind: FleetMetricKind,
        end_kind: FleetMetricKind,
    ) -> dict[str, float]:
        started: dict[str, float] = {}
        result: dict[str, float] = {}
        for event in events:
            if event.kind is start_kind:
                started.setdefault(event.correlation_id, event.timestamp_s)
            elif event.kind is end_kind and event.correlation_id in started:
                result[event.correlation_id] = max(
                    0.0, event.timestamp_s - started[event.correlation_id]
                )
        return dict(sorted(result.items()))

    @staticmethod
    def _handover_timing(correlation_id: str, events: list[FleetMetricEvent]) -> HandoverTiming:
        times = {item.kind: item.timestamp_s for item in events}
        decision = times.get(FleetMetricKind.HANDOVER_DECISION)
        launch = times.get(FleetMetricKind.REPLACEMENT_LAUNCHED)
        takeover = times.get(FleetMetricKind.TAKEOVER_CONFIRMED)
        release = times.get(FleetMetricKind.OUTGOING_RELEASED)
        complete = times.get(FleetMetricKind.HANDOVER_COMPLETED)
        return HandoverTiming(
            handover_id=correlation_id,
            decision_to_launch_s=_delta(decision, launch),
            decision_to_takeover_s=_delta(decision, takeover),
            takeover_to_release_s=_delta(takeover, release),
            total_handover_s=_delta(decision, complete),
        )

    @staticmethod
    def _fault_timing(correlation_id: str, events: list[FleetMetricEvent]) -> FaultRecoveryTiming:
        times = {item.kind: item.timestamp_s for item in events}
        detected = times.get(FleetMetricKind.FAULT_DETECTED)
        return FaultRecoveryTiming(
            fault_id=correlation_id,
            detection_to_command_s=_delta(detected, times.get(FleetMetricKind.RECOVERY_COMMAND)),
            detection_to_stabilization_s=_delta(detected, times.get(FleetMetricKind.STABILIZED)),
            detection_to_reassignment_s=_delta(detected, times.get(FleetMetricKind.REASSIGNED)),
        )

    @staticmethod
    def _dock_timing(correlation_id: str, events: list[FleetMetricEvent]) -> DockTiming:
        times = {item.kind: item.timestamp_s for item in events}
        queued = times.get(FleetMetricKind.DOCK_QUEUED)
        first_attempt = times.get(FleetMetricKind.DOCK_ATTEMPT)
        charging = times.get(FleetMetricKind.DOCK_CHARGING)
        ready = times.get(FleetMetricKind.DOCK_READY)
        return DockTiming(
            reservation_id=correlation_id,
            queue_time_s=_delta(queued, first_attempt) or 0.0,
            attempts=sum(item.kind is FleetMetricKind.DOCK_ATTEMPT for item in events),
            modeled_charge_time_s=_delta(charging, ready) or 0.0,
            total_ready_time_s=_delta(queued, ready) or 0.0,
        )


HANDOVER_KINDS = frozenset(
    {
        FleetMetricKind.HANDOVER_DECISION,
        FleetMetricKind.REPLACEMENT_LAUNCHED,
        FleetMetricKind.TAKEOVER_CONFIRMED,
        FleetMetricKind.OUTGOING_RELEASED,
        FleetMetricKind.HANDOVER_COMPLETED,
    }
)
FAULT_KINDS = frozenset(
    {
        FleetMetricKind.FAULT_DETECTED,
        FleetMetricKind.RECOVERY_COMMAND,
        FleetMetricKind.STABILIZED,
        FleetMetricKind.REASSIGNED,
    }
)
DOCK_KINDS = frozenset(
    {
        FleetMetricKind.DOCK_QUEUED,
        FleetMetricKind.DOCK_ATTEMPT,
        FleetMetricKind.DOCK_CHARGING,
        FleetMetricKind.DOCK_READY,
    }
)


def _group(events: list[FleetMetricEvent], predicate: object) -> dict[str, list[FleetMetricEvent]]:
    selected: dict[str, list[FleetMetricEvent]] = defaultdict(list)
    for event in events:
        if callable(predicate) and predicate(event):
            selected[event.correlation_id].append(event)
    return selected


def _is_handover(event: FleetMetricEvent) -> bool:
    return event.kind in HANDOVER_KINDS


def _is_fault(event: FleetMetricEvent) -> bool:
    return event.kind in FAULT_KINDS


def _is_dock(event: FleetMetricEvent) -> bool:
    return event.kind in DOCK_KINDS


def _delta(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, end - start)


def _update_rates(events: list[FleetMetricEvent]) -> dict[str, float]:
    timestamps: dict[str, list[float]] = defaultdict(list)
    for event in events:
        if event.kind is FleetMetricKind.TELEMETRY_SAMPLE:
            key = event.vehicle_id or event.correlation_id
            timestamps[key].append(event.timestamp_s)
    rates: dict[str, float] = {}
    for key, values in timestamps.items():
        ordered = sorted(values)
        span = ordered[-1] - ordered[0]
        if len(ordered) > 1 and span > 0.0:
            rates[key] = (len(ordered) - 1) / span
    return dict(sorted(rates.items()))


def _mean_values(events: list[FleetMetricEvent], kind: FleetMetricKind) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for event in events:
        if event.kind is kind and event.value is not None:
            key = event.vehicle_id or event.correlation_id
            values[key].append(event.value)
    return {key: sum(samples) / len(samples) for key, samples in sorted(values.items()) if samples}
