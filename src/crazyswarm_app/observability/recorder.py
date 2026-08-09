from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import TYPE_CHECKING

from crazyswarm_app.observability.bus import TelemetryBus, TelemetrySubscription
from crazyswarm_app.observability.events import (
    AcknowledgementPayload,
    EvidenceEvent,
    MissionResultPayload,
    MissionStartedPayload,
    TelemetryPayload,
)
from crazyswarm_app.observability.storage import EvidenceStore

if TYPE_CHECKING:
    from crazyswarm_app.campaign.timing import BoundedTimingTrace

TIMING_TELEMETRY_SAMPLE_EVERY = 20


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
        self.shutdown_dropped_events = 0
        self.last_error: str | None = None
        self.timing_trace: BoundedTimingTrace | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self.subscription = self.bus.subscribe(buffer_size=self.buffer_size)
        self._task = asyncio.create_task(self._record_loop())

    async def flush(self) -> None:
        if self.subscription is not None:
            await self.subscription.queue.join()

    async def stop(self, *, flush_timeout_s: float = 5.0) -> None:
        if self._task is None:
            return
        task = self._task
        if task.done() and not task.cancelled():
            error = task.exception()
            if error is not None:
                self.last_error = f"{type(error).__name__}: {error}"
        else:
            try:
                await asyncio.wait_for(self.flush(), timeout=flush_timeout_s)
            except TimeoutError:
                if self.subscription is not None:
                    self.shutdown_dropped_events += self.subscription.queue.qsize()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._task = None
        if self.subscription is not None:
            self.subscription.close()
            self.subscription = None

    async def _record_loop(self) -> None:
        assert self.subscription is not None
        while True:
            event = await self.subscription.queue.get()
            try:
                if isinstance(event.payload, MissionResultPayload):
                    await asyncio.to_thread(self._record, event)
                else:
                    self._record(event)
                self.persisted_events += 1
                self._record_timing(event)
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {error}"
                raise
            finally:
                self.subscription.queue.task_done()
            await asyncio.sleep(0)

    def _record(self, event: EvidenceEvent) -> None:
        if isinstance(event.payload, MissionStartedPayload):
            self.store.begin_run(event.payload.run)
        self.store.append_event(event)
        if isinstance(event.payload, MissionResultPayload):
            self.store.complete_run(event.payload.result)
            self.store.materialize_run_files_for_run(event.payload.result.mission_run_id)

    def _record_timing(self, event: EvidenceEvent) -> None:
        trace = self.timing_trace
        if trace is None:
            return
        if (
            isinstance(event.payload, TelemetryPayload)
            and event.sequence % TIMING_TELEMETRY_SAMPLE_EVERY != 0
        ):
            return
        from crazyswarm_app.campaign.timing import (
            TimingStage,
            timing_sample_correlation_id,
        )

        clock_id = event.source
        clock_epoch = 0
        correlation_id = event.event_id
        if isinstance(event.payload, TelemetryPayload):
            telemetry = event.payload.telemetry
            clock_id = telemetry.source_clock_id
            clock_epoch = telemetry.source_clock_epoch
            correlation_id = timing_sample_correlation_id(
                clock_id, clock_epoch, telemetry.sequence
            )
            if clock_id.startswith("fast-sim"):
                trace.record(
                    correlation_id=correlation_id,
                    stage=TimingStage.SIMULATOR_STEP,
                    source_timestamp_s=event.source_timestamp_s,
                    source_clock_id=clock_id,
                    source_clock_epoch=clock_epoch,
                    observed_monotonic_s=event.received_timestamp_s,
                )
            transport = telemetry.telemetry.transport
            if transport is not None and transport.source_class == "SIMULATED_MODEL":
                trace.record(
                    correlation_id=correlation_id,
                    stage=TimingStage.MODELED_VEHICLE_TRANSPORT,
                    source_timestamp_s=event.source_timestamp_s,
                    source_clock_id=clock_id,
                    source_clock_epoch=clock_epoch,
                    observed_monotonic_s=event.received_timestamp_s,
                    details={"source_class": "SIMULATED_MODEL"},
                )
        if isinstance(event.payload, AcknowledgementPayload):
            trace.record(
                correlation_id=event.event_id,
                stage=TimingStage.COMMAND_COMPLETION,
                source_timestamp_s=event.source_timestamp_s,
                source_clock_id=clock_id,
                source_clock_epoch=clock_epoch,
                observed_monotonic_s=event.received_timestamp_s,
            )
        trace.record(
            correlation_id=correlation_id,
            stage=TimingStage.RECORDER_COMMIT,
            source_timestamp_s=event.source_timestamp_s,
            source_clock_id=clock_id,
            source_clock_epoch=clock_epoch,
            observed_monotonic_s=time.monotonic(),
        )
