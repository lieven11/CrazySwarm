from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import VehicleCapabilities, VehicleIdentity
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.observability.events import EvidenceEvent, TelemetryPayload


class ReplayClock:
    def __init__(self, events: Sequence[EvidenceEvent], *, speed: float = 1.0) -> None:
        if speed <= 0.0:
            raise ValueError("replay speed must be positive")
        self.events = tuple(sorted(events, key=lambda item: item.sequence))
        self.speed = speed
        self.index = 0
        self.paused = False

    @property
    def now_s(self) -> float:
        if not self.events:
            return 0.0
        if self.index == 0:
            return self._timeline_s(self.events[0])
        return self._timeline_s(self.events[min(self.index - 1, len(self.events) - 1)])

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def set_speed(self, speed: float) -> None:
        if speed <= 0.0:
            raise ValueError("replay speed must be positive")
        self.speed = speed

    def seek(self, timestamp_s: float) -> None:
        if timestamp_s < 0.0:
            raise ValueError("replay timestamp cannot be negative")
        self.index = next(
            (
                index
                for index, event in enumerate(self.events)
                if self._timeline_s(event) >= timestamp_s
            ),
            len(self.events),
        )

    def step(self) -> EvidenceEvent | None:
        if self.index >= len(self.events):
            return None
        event = self.events[self.index]
        self.index += 1
        return event

    async def stream(self) -> AsyncIterator[EvidenceEvent]:
        previous_s: float | None = None
        while self.index < len(self.events):
            while self.paused:
                await asyncio.sleep(0.01)
            event = self.events[self.index]
            if previous_s is not None:
                await asyncio.sleep(max(0.0, self._timeline_s(event) - previous_s) / self.speed)
            self.index += 1
            previous_s = self._timeline_s(event)
            yield event

    @staticmethod
    def _timeline_s(event: EvidenceEvent) -> float:
        return event.recorded_at_utc.timestamp()


class ReplayVehicle:
    """Read-only vehicle-shaped adapter; intentionally has no execute method."""

    def __init__(self, vehicle_id: str, events: Sequence[EvidenceEvent]) -> None:
        telemetry_events = tuple(
            event
            for event in events
            if event.vehicle_id == vehicle_id and isinstance(event.payload, TelemetryPayload)
        )
        if not telemetry_events:
            raise ValueError(f"no telemetry is available for replay vehicle {vehicle_id}")
        self._identity = VehicleIdentity(
            vehicle_id=vehicle_id,
            display_name=f"Replay {vehicle_id}",
            adapter="replay",
        )
        first_payload = telemetry_events[0].payload
        assert isinstance(first_payload, TelemetryPayload)
        self._capabilities = (
            first_payload.telemetry.telemetry.capabilities or VehicleCapabilities()
        )
        self.clock = ReplayClock(telemetry_events)
        self._connected = False
        self._latest = first_payload.telemetry

    @property
    def identity(self) -> VehicleIdentity:
        return self._identity

    @property
    def capabilities(self) -> VehicleCapabilities:
        return self._capabilities

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def snapshot(self) -> TelemetryEnvelope:
        if not self._connected:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "replay vehicle is not connected")
        return self._latest

    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryEnvelope]:
        if not self._connected:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "replay vehicle is not connected")
        async for event in self.clock.stream():
            payload = event.payload
            assert isinstance(payload, TelemetryPayload)
            self._latest = payload.telemetry
            yield self._latest
