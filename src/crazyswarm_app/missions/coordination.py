from __future__ import annotations

import asyncio


class MissionCommandGate:
    """In-process command permission shared by a fleet coordinator and child missions.

    The gate never creates or changes command authority. It only prevents a mission
    context from starting its next ordinary flight-path command while a production
    fleet policy owns a bounded hold decision.
    """

    def __init__(self, vehicle_ids: tuple[str, ...]) -> None:
        self._permitted: dict[str, asyncio.Event] = {}
        self._blocked: dict[str, asyncio.Event] = {}
        self._reasons: dict[str, str] = {}
        for vehicle_id in vehicle_ids:
            permitted = asyncio.Event()
            permitted.set()
            self._permitted[vehicle_id] = permitted
            self._blocked[vehicle_id] = asyncio.Event()

    def hold(self, vehicle_id: str, *, reason: str) -> None:
        self._require_vehicle(vehicle_id)
        self._reasons[vehicle_id] = reason
        self._blocked[vehicle_id].clear()
        self._permitted[vehicle_id].clear()

    def release(self, vehicle_id: str) -> None:
        self._require_vehicle(vehicle_id)
        self._reasons.pop(vehicle_id, None)
        self._permitted[vehicle_id].set()
        self._blocked[vehicle_id].clear()

    def release_all(self) -> None:
        for vehicle_id in self._permitted:
            self.release(vehicle_id)

    def held(self, vehicle_id: str) -> bool:
        self._require_vehicle(vehicle_id)
        return not self._permitted[vehicle_id].is_set()

    def reason(self, vehicle_id: str) -> str | None:
        self._require_vehicle(vehicle_id)
        return self._reasons.get(vehicle_id)

    async def wait_for_permission(self, vehicle_id: str) -> None:
        self._require_vehicle(vehicle_id)
        permitted = self._permitted[vehicle_id]
        if not permitted.is_set():
            self._blocked[vehicle_id].set()
        await permitted.wait()
        self._blocked[vehicle_id].clear()

    async def wait_until_blocked(self, vehicle_id: str, *, timeout_s: float) -> None:
        self._require_vehicle(vehicle_id)
        if timeout_s <= 0.0:
            raise ValueError("command-gate timeout must be positive")
        await asyncio.wait_for(self._blocked[vehicle_id].wait(), timeout=timeout_s)

    def _require_vehicle(self, vehicle_id: str) -> None:
        if vehicle_id not in self._permitted:
            raise KeyError(f"vehicle is not registered with the command gate: {vehicle_id}")
