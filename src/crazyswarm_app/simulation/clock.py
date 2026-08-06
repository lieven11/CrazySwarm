from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum


class ClockMode(StrEnum):
    REALTIME = "realtime"
    ACCELERATED = "accelerated"


class SimulationPausedError(RuntimeError):
    pass


@dataclass(slots=True)
class SimulationClock:
    fixed_step_s: float = 0.05
    mode: ClockMode = ClockMode.ACCELERATED
    speed: float = 1.0
    now_s: float = 0.0
    paused: bool = False
    _wall_deadline_s: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.fixed_step_s <= 0.0:
            raise ValueError("fixed_step_s must be positive")
        if self.speed <= 0.0:
            raise ValueError("speed must be positive")

    def pause(self) -> None:
        self.paused = True
        self._wall_deadline_s = None

    def resume(self) -> None:
        self.paused = False
        self._wall_deadline_s = None

    def reset(self) -> None:
        self.now_s = 0.0
        self.paused = False
        self._wall_deadline_s = None

    async def advance(self, duration_s: float, *, force: bool = False) -> float:
        if duration_s < 0.0:
            raise ValueError("duration_s cannot be negative")
        if self.paused and not force:
            raise SimulationPausedError("simulation clock is paused")
        if self.mode is ClockMode.REALTIME and duration_s > 0.0:
            wall_now_s = time.monotonic()
            idle_reset_s = max(0.1, 5.0 * self.fixed_step_s / self.speed)
            if (
                self._wall_deadline_s is None
                or wall_now_s - self._wall_deadline_s > idle_reset_s
            ):
                self._wall_deadline_s = wall_now_s
            self._wall_deadline_s += duration_s / self.speed
            await asyncio.sleep(max(0.0, self._wall_deadline_s - time.monotonic()))
        else:
            self._wall_deadline_s = None
            await asyncio.sleep(0)
        self.now_s += duration_s
        return self.now_s

    async def single_step(self) -> float:
        return await self.advance(self.fixed_step_s, force=True)
