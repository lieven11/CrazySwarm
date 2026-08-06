from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, Request

from crazyswarm_app.api.models import OperatorContext


class LocalAuthenticator:
    def __init__(self, token: str) -> None:
        if len(token) < 24:
            raise ValueError("local API token must contain at least 24 characters")
        self._token = token

    def valid(self, token: str | None) -> bool:
        return token is not None and hmac.compare_digest(token, self._token)


@dataclass(slots=True)
class IdempotencyEntry:
    fingerprint: str
    response: Any


class IdempotencyStore:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], IdempotencyEntry] = {}
        self._lock = asyncio.Lock()

    async def execute(
        self,
        context: OperatorContext,
        fingerprint: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> tuple[Any, bool]:
        key = (context.client_id, context.request_id)
        async with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "IDEMPOTENCY_KEY_REUSED",
                            "message": "request ID was already used for a different operation",
                        },
                    )
                return existing.response, True
            response = await operation()
            self._entries[key] = IdempotencyEntry(
                fingerprint=fingerprint,
                response=response,
            )
            return response, False


async def mutation_fingerprint(request: Request) -> str:
    body = await request.body()
    value = b"\0".join((request.method.encode(), request.url.path.encode(), body))
    return hashlib.sha256(value).hexdigest()


def operator_context(
    x_client_id: str = Header(..., alias="X-Client-ID"),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> OperatorContext:
    return OperatorContext(client_id=x_client_id, request_id=idempotency_key)
