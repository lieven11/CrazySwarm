from __future__ import annotations

import asyncio
from contextlib import suppress

from crazyswarm_app.observability.bus import TelemetryBus, TelemetrySubscription
from crazyswarm_app.observability.events import (
    EvidenceEvent,
    MissionResultPayload,
    MissionStartedPayload,
)
from crazyswarm_app.observability.storage import EvidenceStore


class EvidenceRecorder:
    """Asynchronous recorder so producers and UI consumers never perform disk I/O."""

    def __init__(
        self,
        bus: TelemetryBus,
        store: EvidenceStore,
        *,
        buffer_size: int = 8192,
    ) -> None:
        self.bus = bus
        self.store = store
        self.buffer_size = buffer_size
        self.subscription: TelemetrySubscription | None = None
        self._task: asyncio.Task[None] | None = None
        self.persisted_events = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        self.subscription = self.bus.subscribe(buffer_size=self.buffer_size)
        self._task = asyncio.create_task(self._record_loop())

    async def flush(self) -> None:
        if self.subscription is not None:
            await self.subscription.queue.join()

    async def stop(self) -> None:
        if self._task is None:
            return
        await self.flush()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        if self.subscription is not None:
            self.subscription.close()
            self.subscription = None

    async def _record_loop(self) -> None:
        assert self.subscription is not None
        while True:
            event = await self.subscription.queue.get()
            try:
                self._record(event)
                self.persisted_events += 1
            finally:
                self.subscription.queue.task_done()
            await asyncio.sleep(0)

    def _record(self, event: EvidenceEvent) -> None:
        if isinstance(event.payload, MissionStartedPayload):
            self.store.begin_run(event.payload.run)
        self.store.append_event(event)
        if isinstance(event.payload, MissionResultPayload):
            self.store.complete_run(event.payload.result)
