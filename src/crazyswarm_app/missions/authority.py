from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from crazyswarm_app.domain.commands import FleetCommandBinding
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.simulation import (
    FleetAuthorityTransition,
    FleetAuthorityTransitionReceipt,
)
from crazyswarm_app.vehicles.base import Vehicle

ResultT = TypeVar("ResultT")


class MissionFleetAuthority:
    """One serialized fleet binding shared by every command path in a child run."""

    def __init__(
        self,
        vehicle: Vehicle,
        binding: FleetCommandBinding | None,
    ) -> None:
        self.vehicle = vehicle
        self._binding = binding
        self._guard = asyncio.Lock()
        self._health_guard = asyncio.Lock()
        self._receipts: list[FleetAuthorityTransitionReceipt] = []

    @property
    def current_binding(self) -> FleetCommandBinding | None:
        return self._binding

    @property
    def receipts(self) -> tuple[FleetAuthorityTransitionReceipt, ...]:
        return tuple(self._receipts)

    async def execute(
        self,
        operation: Callable[[FleetCommandBinding | None], Awaitable[ResultT]],
    ) -> ResultT:
        """Run one command/recovery operation against an indivisible binding snapshot."""

        async with self._guard:
            return await operation(self._binding)

    async def evaluate_health(
        self,
        operation: Callable[[FleetCommandBinding | None], Awaitable[ResultT]],
    ) -> ResultT:
        """Allow watchdog recovery to preempt a command while blocking transitions."""

        async with self._health_guard:
            return await operation(self._binding)

    async def transition(
        self,
        transition: FleetAuthorityTransition,
    ) -> FleetAuthorityTransitionReceipt:
        """Change adapter and command-context authority under the same serialization lock."""

        async with self._guard, self._health_guard:
            binding = self._binding
            if binding is None:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "mission run has no fleet authority to transition",
                )
            if (
                binding.fleet_session_id,
                binding.fleet_run_id,
                binding.deployment_sha256,
                binding.task_id,
                binding.task_lease_generation,
            ) != (
                transition.fleet_session_id,
                transition.fleet_run_id,
                transition.deployment_sha256,
                transition.expected_task_id,
                transition.expected_task_lease_generation,
            ):
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "mission command context does not own the expected task lease",
                )
            receipt = await self.vehicle.transition_fleet_authority(transition)
            if (
                receipt.current_task_id,
                receipt.current_task_lease_generation,
            ) != (
                transition.next_task_id,
                transition.next_task_lease_generation,
            ):
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "adapter authority receipt does not match the requested task lease",
                )
            self._binding = binding.model_copy(
                update={
                    "task_id": receipt.current_task_id,
                    "task_lease_generation": receipt.current_task_lease_generation,
                }
            )
            self._receipts.append(receipt)
            return receipt
