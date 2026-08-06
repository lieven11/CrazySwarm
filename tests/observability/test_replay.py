from __future__ import annotations

from pathlib import Path

import pytest

from crazyswarm_app.observability.events import EvidenceKind
from crazyswarm_app.observability.replay import ReplayClock, ReplayVehicle
from tests.observability.test_storage import recorded_mission


@pytest.mark.asyncio
async def test_replay_clock_preserves_recorded_sequence_and_supports_seek_step(
    tmp_path: Path,
) -> None:
    store, run_id = await recorded_mission(tmp_path / "evidence.sqlite3")
    events = store.query_events(run_id=run_id)
    clock = ReplayClock(events, speed=1_000_000.0)
    first = clock.step()
    assert first == events[0]
    clock.seek(events[-1].recorded_at_utc.timestamp())
    assert clock.step() == events[-1]
    clock.seek(0.0)
    replayed = [event async for event in clock.stream()]
    assert [event.sequence for event in replayed] == [event.sequence for event in events]
    store.close()


@pytest.mark.asyncio
async def test_replay_vehicle_is_read_only_and_replays_telemetry(tmp_path: Path) -> None:
    store, run_id = await recorded_mission(tmp_path / "evidence.sqlite3")
    events = store.query_events(run_id=run_id, kind=EvidenceKind.TELEMETRY)
    replay = ReplayVehicle("sim01", events)
    assert not hasattr(replay, "execute")
    replay.clock.set_speed(1_000_000.0)
    await replay.connect()
    assert (await replay.snapshot()).vehicle_id == "sim01"
    samples = [sample async for sample in replay.telemetry_stream()]
    assert [sample.sequence for sample in samples] == [
        event.payload.telemetry.sequence  # type: ignore[union-attr]
        for event in events
    ]
    await replay.disconnect()
    store.close()
