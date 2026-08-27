import asyncio
from typing import cast

import pytest

from crazyswarm_app.domain.commands import FleetCommandBinding
from crazyswarm_app.missions.authority import MissionFleetAuthority
from crazyswarm_app.vehicles.base import Vehicle


@pytest.mark.asyncio
async def test_long_command_does_not_block_health_evaluation() -> None:
    authority = MissionFleetAuthority(cast(Vehicle, object()), None)
    command_started = asyncio.Event()
    release_command = asyncio.Event()

    async def command(binding: FleetCommandBinding | None) -> str:
        assert binding is None
        command_started.set()
        await release_command.wait()
        return "complete"

    task = asyncio.create_task(authority.execute_preemptible(command))
    await command_started.wait()

    health = await asyncio.wait_for(
        authority.evaluate_health(lambda binding: asyncio.sleep(0, result=binding)),
        timeout=0.1,
    )
    assert health is None

    release_command.set()
    assert await task == "complete"


@pytest.mark.asyncio
async def test_new_replacement_cancels_and_drains_prior_command() -> None:
    authority = MissionFleetAuthority(cast(Vehicle, object()), None)
    first_started = asyncio.Event()
    first_cancelled = asyncio.Event()

    async def first(binding: FleetCommandBinding | None) -> str:
        assert binding is None
        first_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            first_cancelled.set()
        return "unreachable"

    first_task = asyncio.create_task(authority.execute_preemptible(first))
    await first_started.wait()
    second_result = await authority.execute_preemptible(
        lambda binding: asyncio.sleep(0, result="replacement"),
    )

    assert second_result == "replacement"
    assert first_cancelled.is_set()
    with pytest.raises(asyncio.CancelledError):
        await first_task
