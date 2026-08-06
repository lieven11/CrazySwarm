from __future__ import annotations

import pytest

from crazyswarm_app.simulation.clock import ClockMode, SimulationClock, SimulationPausedError


@pytest.mark.asyncio
async def test_clock_pause_step_resume_and_reset() -> None:
    clock = SimulationClock(fixed_step_s=0.1)
    await clock.advance(0.5)
    assert clock.now_s == pytest.approx(0.5)

    clock.pause()
    with pytest.raises(SimulationPausedError):
        await clock.advance(0.1)
    await clock.single_step()
    assert clock.now_s == pytest.approx(0.6)

    clock.resume()
    await clock.advance(0.4)
    assert clock.now_s == pytest.approx(1.0)
    clock.reset()
    assert clock.now_s == 0.0
    assert not clock.paused


@pytest.mark.asyncio
async def test_realtime_clock_compensates_for_fixed_step_processing_overhead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wall_time_s = 100.0
    requested_sleeps: list[float] = []

    async def advance_wall_time(delay_s: float) -> None:
        nonlocal wall_time_s
        requested_sleeps.append(delay_s)
        wall_time_s += delay_s

    monkeypatch.setattr("crazyswarm_app.simulation.clock.time.monotonic", lambda: wall_time_s)
    monkeypatch.setattr("crazyswarm_app.simulation.clock.asyncio.sleep", advance_wall_time)
    clock = SimulationClock(fixed_step_s=0.01, mode=ClockMode.REALTIME)

    for _ in range(100):
        await clock.advance(0.01)
        wall_time_s += 0.004

    assert clock.now_s == pytest.approx(1.0)
    assert wall_time_s == pytest.approx(101.004)
    assert requested_sleeps[0] == pytest.approx(0.01)
    assert max(requested_sleeps[1:]) == pytest.approx(0.006)


@pytest.mark.asyncio
async def test_realtime_clock_starts_a_new_deadline_after_idle_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wall_time_s = 200.0
    requested_sleeps: list[float] = []

    async def advance_wall_time(delay_s: float) -> None:
        nonlocal wall_time_s
        requested_sleeps.append(delay_s)
        wall_time_s += delay_s

    monkeypatch.setattr("crazyswarm_app.simulation.clock.time.monotonic", lambda: wall_time_s)
    monkeypatch.setattr("crazyswarm_app.simulation.clock.asyncio.sleep", advance_wall_time)
    clock = SimulationClock(fixed_step_s=0.01, mode=ClockMode.REALTIME)

    await clock.advance(0.01)
    wall_time_s += 1.0
    await clock.advance(0.01)

    assert requested_sleeps == pytest.approx([0.01, 0.01])
