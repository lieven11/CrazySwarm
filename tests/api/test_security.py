from __future__ import annotations

import asyncio

import pytest

from crazyswarm_app.api.models import OperatorContext
from crazyswarm_app.api.security import IdempotencyStore


@pytest.mark.asyncio
async def test_concurrent_duplicate_requests_execute_operation_once() -> None:
    store = IdempotencyStore()
    context = OperatorContext(client_id="client-1", request_id="request-1")
    executions = 0

    async def operation() -> dict[str, int]:
        nonlocal executions
        executions += 1
        await asyncio.sleep(0.01)
        return {"execution": executions}

    responses = await asyncio.gather(
        *(store.execute(context, "same-fingerprint", operation) for _ in range(20))
    )
    assert executions == 1
    assert all(
        response == ({"execution": 1}, index > 0) for index, response in enumerate(responses)
    )
