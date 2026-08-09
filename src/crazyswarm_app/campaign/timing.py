from __future__ import annotations

import threading
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from typing import Any, Literal

from pydantic import Field

from crazyswarm_app.campaign.analyzer import CauseClassification, RootCauseStage
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class TimingStage(StrEnum):
    SIMULATOR_STEP = "SIMULATOR_STEP"
    CONTROLLER_SAMPLE = "CONTROLLER_SAMPLE"
    COMMAND_COMPLETION = "COMMAND_COMPLETION"
    MODELED_VEHICLE_TRANSPORT = "MODELED_VEHICLE_TRANSPORT"
    RECORDER_COMMIT = "RECORDER_COMMIT"
    WEBSOCKET_ENQUEUE = "WEBSOCKET_ENQUEUE"
    WEBSOCKET_DELIVERY = "WEBSOCKET_DELIVERY"
    BROWSER_RECEIPT = "BROWSER_RECEIPT"
    RENDER_FRAME = "RENDER_FRAME"
    PLAYBACK_BUFFER = "PLAYBACK_BUFFER"


def timing_sample_correlation_id(
    source_clock_id: str, source_clock_epoch: int, sequence: int
) -> str:
    """Create the stable sample identity shared by recorder, delivery, and browser."""

    return f"sample-{canonical_sha256([source_clock_id, source_clock_epoch, sequence])[:32]}"


class TimingEvent(ContractModel):
    schema_version: Literal[1] = 1
    trace_id: Identifier
    correlation_id: Identifier
    stage: TimingStage
    sequence: int = Field(ge=1)
    source_timestamp_s: float = Field(ge=0.0)
    source_clock_id: str = Field(min_length=1, max_length=128)
    source_clock_epoch: int = Field(ge=0)
    observed_monotonic_s: float = Field(ge=0.0)
    recorded_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    playback_buffer_age_s: float | None = Field(default=None, ge=0.0)
    dropped_samples: int = Field(default=0, ge=0)
    coalesced_samples: int = Field(default=0, ge=0)
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class TimingTraceSnapshot(ContractModel):
    schema_version: Literal[1] = 1
    trace_id: Identifier
    retention_limit: int = Field(ge=1)
    total_seen: int = Field(ge=0)
    retention_dropped: int = Field(ge=0)
    events: tuple[TimingEvent, ...]
    stage_counts: dict[TimingStage, int]
    trace_sha256: SHA256

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"trace_sha256"})


class BoundedTimingTrace:
    """Thread-safe optional diagnostics; it neither grants nor changes flight authority."""

    def __init__(self, trace_id: str, *, retention_limit: int = 20_000) -> None:
        if retention_limit < 1 or retention_limit > 1_000_000:
            raise ValueError("timing trace retention_limit must be in 1..1,000,000")
        self.trace_id = trace_id
        self.retention_limit = retention_limit
        self._events: deque[TimingEvent] = deque(maxlen=retention_limit)
        self._total_seen = 0
        self._lock = threading.Lock()

    def record(
        self,
        *,
        correlation_id: str,
        stage: TimingStage,
        source_timestamp_s: float,
        source_clock_id: str,
        source_clock_epoch: int,
        observed_monotonic_s: float,
        playback_buffer_age_s: float | None = None,
        dropped_samples: int = 0,
        coalesced_samples: int = 0,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> TimingEvent:
        with self._lock:
            self._total_seen += 1
            event = TimingEvent(
                trace_id=self.trace_id,
                correlation_id=correlation_id,
                stage=stage,
                sequence=self._total_seen,
                source_timestamp_s=source_timestamp_s,
                source_clock_id=source_clock_id,
                source_clock_epoch=source_clock_epoch,
                observed_monotonic_s=observed_monotonic_s,
                playback_buffer_age_s=playback_buffer_age_s,
                dropped_samples=dropped_samples,
                coalesced_samples=coalesced_samples,
                details=details or {},
            )
            self._events.append(event)
            return event

    def snapshot(self) -> TimingTraceSnapshot:
        with self._lock:
            events = tuple(self._events)
            payload: dict[str, Any] = {
                "trace_id": self.trace_id,
                "retention_limit": self.retention_limit,
                "total_seen": self._total_seen,
                "retention_dropped": max(0, self._total_seen - len(events)),
                "events": events,
                "stage_counts": dict(Counter(item.stage for item in events)),
            }
        return TimingTraceSnapshot(**payload, trace_sha256=canonical_sha256(payload))


class LandingCoordinateDiagnostic(ContractModel):
    role_id: Identifier
    frame: Literal["world"] = "world"
    accepted_center_m: Vector3
    actual_touchdown_m: Vector3 | None = None
    displayed_marker_m: Vector3 | None = None
    conversion_chain: tuple[str, ...]


def classify_timing_trace(trace: TimingTraceSnapshot) -> CauseClassification:
    by_correlation: dict[str, dict[TimingStage, TimingEvent]] = defaultdict(dict)
    by_stage: dict[TimingStage, list[TimingEvent]] = defaultdict(list)
    for event in trace.events:
        by_correlation[event.correlation_id][event.stage] = event
        by_stage[event.stage].append(event)

    simulator = sorted(by_stage[TimingStage.SIMULATOR_STEP], key=lambda item: item.sequence)
    if len(simulator) >= 3:
        factors = []
        for before, after in pairwise(simulator):
            wall = after.observed_monotonic_s - before.observed_monotonic_s
            source = after.source_timestamp_s - before.source_timestamp_s
            if wall > 0.0 and source >= 0.0:
                factors.append(source / wall)
        if factors and _percentile(factors, 0.50) < 0.80:
            return CauseClassification(
                stage=RootCauseStage.SIM_TIMING,
                confidence=0.97,
                reason="simulator source time progressed below the admitted real-time factor",
                evidence_references=("timing:SIMULATOR_STEP",),
                counter_evidence=("classification does not use modeled vehicle transport",),
            )

    delivery_delays = _stage_delays(
        by_correlation,
        TimingStage.WEBSOCKET_ENQUEUE,
        TimingStage.WEBSOCKET_DELIVERY,
    )
    if delivery_delays and max(delivery_delays) >= 0.50:
        return CauseClassification(
            stage=RootCauseStage.EVIDENCE_DELIVERY,
            confidence=0.96,
            reason="a bounded WebSocket delivery burst accumulated after API enqueue",
            evidence_references=("timing:WEBSOCKET_ENQUEUE", "timing:WEBSOCKET_DELIVERY"),
            counter_evidence=("simulator production timestamps remained distinct",),
        )

    render_delays = _stage_delays(
        by_correlation,
        TimingStage.BROWSER_RECEIPT,
        TimingStage.RENDER_FRAME,
    )
    frames = sorted(by_stage[TimingStage.RENDER_FRAME], key=lambda item: item.observed_monotonic_s)
    frame_gaps = [
        after.observed_monotonic_s - before.observed_monotonic_s
        for before, after in pairwise(frames)
    ]
    if (render_delays and max(render_delays) >= 0.20) or (frame_gaps and max(frame_gaps) >= 0.20):
        return CauseClassification(
            stage=RootCauseStage.UI_RENDERING,
            confidence=0.96,
            reason="browser receipt continued while render cadence stalled",
            evidence_references=("timing:BROWSER_RECEIPT", "timing:RENDER_FRAME"),
            counter_evidence=("raw telemetry remains unchanged presentation evidence",),
        )

    return CauseClassification(
        stage=RootCauseStage.UNKNOWN,
        confidence=0.50,
        reason="the bounded timing trace contains no stage-localized threshold violation",
        evidence_references=("timing:trace",),
    )


def correlation_completeness(
    events: Iterable[TimingEvent],
) -> dict[str, tuple[TimingStage, ...]]:
    stages: dict[str, set[TimingStage]] = defaultdict(set)
    for event in events:
        stages[event.correlation_id].add(event.stage)
    return {
        correlation_id: tuple(sorted(values, key=lambda item: item.value))
        for correlation_id, values in sorted(stages.items())
    }


def _stage_delays(
    events: dict[str, dict[TimingStage, TimingEvent]],
    start: TimingStage,
    end: TimingStage,
) -> list[float]:
    return [
        stages[end].observed_monotonic_s - stages[start].observed_monotonic_s
        for stages in events.values()
        if start in stages and end in stages
    ]


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return ordered[index]
