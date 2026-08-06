from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from crazyswarm_app.observability.events import BusStats, EvidenceEvent, EvidenceKind


@dataclass(eq=False, slots=True)
class TelemetrySubscription:
    _bus: TelemetryBus
    queue: asyncio.Queue[EvidenceEvent]
    kinds: frozenset[EvidenceKind] | None
    vehicle_ids: frozenset[str] | None
    minimum_telemetry_interval_s: float
    dropped_events: int = 0
    _last_telemetry_at: dict[str, float] = field(default_factory=dict)
    _closed: bool = False

    def accepts(self, event: EvidenceEvent) -> bool:
        if self._closed:
            return False
        if self.kinds is not None and event.kind not in self.kinds:
            return False
        if self.vehicle_ids is not None and event.vehicle_id not in self.vehicle_ids:
            return False
        if event.kind is EvidenceKind.TELEMETRY and self.minimum_telemetry_interval_s > 0.0:
            previous = self._last_telemetry_at.get(event.vehicle_id)
            if previous is not None and (
                event.received_timestamp_s - previous < self.minimum_telemetry_interval_s
            ):
                return False
            self._last_telemetry_at[event.vehicle_id] = event.received_timestamp_s
        return True

    async def get(self) -> EvidenceEvent:
        event = await self.queue.get()
        self.queue.task_done()
        return event

    def get_nowait(self) -> EvidenceEvent:
        event = self.queue.get_nowait()
        self.queue.task_done()
        return event

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._bus.unsubscribe(self)

    def __aiter__(self) -> AsyncIterator[EvidenceEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[EvidenceEvent]:
        try:
            while not self._closed:
                yield await self.get()
        finally:
            self.close()


class TelemetryBus:
    """In-memory non-blocking fan-out with bounded per-client buffers."""

    def __init__(self) -> None:
        self._sequence = 0
        self._subscriptions: set[TelemetrySubscription] = set()
        self._published_events = 0
        self._dropped_events = 0

    def subscribe(
        self,
        *,
        buffer_size: int = 256,
        max_telemetry_rate_hz: float | None = None,
        kinds: frozenset[EvidenceKind] | None = None,
        vehicle_ids: frozenset[str] | None = None,
    ) -> TelemetrySubscription:
        if buffer_size <= 0:
            raise ValueError("buffer_size must be positive")
        if max_telemetry_rate_hz is not None and max_telemetry_rate_hz <= 0.0:
            raise ValueError("max_telemetry_rate_hz must be positive")
        subscription = TelemetrySubscription(
            _bus=self,
            queue=asyncio.Queue(maxsize=buffer_size),
            kinds=kinds,
            vehicle_ids=vehicle_ids,
            minimum_telemetry_interval_s=(
                0.0 if max_telemetry_rate_hz is None else 1.0 / max_telemetry_rate_hz
            ),
        )
        self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: TelemetrySubscription) -> None:
        self._subscriptions.discard(subscription)

    def publish_nowait(self, event: EvidenceEvent) -> EvidenceEvent:
        self._sequence += 1
        sequenced = event.model_copy(update={"sequence": self._sequence})
        self._published_events += 1
        for subscription in tuple(self._subscriptions):
            if not subscription.accepts(sequenced):
                continue
            if subscription.queue.full():
                try:
                    subscription.queue.get_nowait()
                    subscription.queue.task_done()
                except asyncio.QueueEmpty:  # pragma: no cover - event-loop atomic operation
                    pass
                subscription.dropped_events += 1
                self._dropped_events += 1
            subscription.queue.put_nowait(sequenced)
        return sequenced

    @property
    def stats(self) -> BusStats:
        return BusStats(
            published_events=self._published_events,
            subscriber_count=len(self._subscriptions),
            dropped_events=self._dropped_events,
        )
