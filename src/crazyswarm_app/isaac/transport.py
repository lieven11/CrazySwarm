from __future__ import annotations

import asyncio
import json
import os
import ssl
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.isaac.protocol import (
    MAX_GATEWAY_MESSAGE_BYTES,
    GatewayLifecycleState,
)


class GatewayTransport(Protocol):
    @property
    def state(self) -> GatewayLifecycleState: ...

    async def start(self) -> None: ...

    async def request(self, value: dict[str, Any]) -> dict[str, Any]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LocalProcessEndpoint:
    argv: tuple[str, ...]
    working_directory: Path
    environment: dict[str, str] = field(default_factory=dict)
    request_timeout_s: float = 5.0
    shutdown_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if not self.argv or not Path(self.argv[0]).is_absolute():
            raise ValueError("gateway executable must be an explicit absolute path")
        if self.request_timeout_s <= 0.0 or self.shutdown_timeout_s <= 0.0:
            raise ValueError("gateway process timeouts must be positive")


@dataclass(frozen=True, slots=True)
class TlsGatewayEndpoint:
    host: str
    port: int
    server_name: str
    ca_certificate: Path
    request_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if not self.host or not self.server_name:
            raise ValueError("TLS gateway host and server name are required")
        if not 1 <= self.port <= 65535:
            raise ValueError("TLS gateway port is invalid")
        if self.request_timeout_s <= 0.0:
            raise ValueError("TLS gateway timeout must be positive")


class ManagedProcessTransport:
    """One-request-at-a-time JSON-lines transport with explicit child lifecycle."""

    def __init__(self, endpoint: LocalProcessEndpoint) -> None:
        self.endpoint = endpoint
        self._state = GatewayLifecycleState.NEW
        self._process: asyncio.subprocess.Process | None = None
        self._request_lock = asyncio.Lock()
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=100)

    @property
    def state(self) -> GatewayLifecycleState:
        if self._process is not None and self._process.returncode is not None:
            return GatewayLifecycleState.FAILED
        return self._state

    @property
    def process(self) -> asyncio.subprocess.Process | None:
        return self._process

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return tuple(self._stderr_tail)

    async def start(self) -> None:
        if self._state not in {GatewayLifecycleState.NEW, GatewayLifecycleState.STOPPED}:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "gateway process is already started")
        self._state = GatewayLifecycleState.STARTING
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            **self.endpoint.environment,
        }
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.endpoint.argv,
                cwd=self.endpoint.working_directory,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=MAX_GATEWAY_MESSAGE_BYTES + 1,
            )
        except (OSError, ValueError) as error:
            self._state = GatewayLifecycleState.FAILED
            raise CrazySwarmError(
                ErrorCode.LINK_LOST,
                "Isaac gateway process could not start",
                details={"error_type": type(error).__name__},
            ) from error
        self._stderr_task = asyncio.create_task(self._drain_stderr(), name="isaac-gateway-stderr")
        self._state = GatewayLifecycleState.READY

    async def request(self, value: dict[str, Any]) -> dict[str, Any]:
        async with self._request_lock:
            process = self._process
            if (
                process is None
                or process.stdin is None
                or process.stdout is None
                or process.returncode is not None
            ):
                self._state = GatewayLifecycleState.FAILED
                raise CrazySwarmError(
                    ErrorCode.LINK_LOST,
                    "Isaac gateway process is unavailable",
                    details={**self._exit_details(process), "automatic_retry_safe": False},
                )
            encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode() + b"\n"
            if len(encoded) > MAX_GATEWAY_MESSAGE_BYTES:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND, "Isaac gateway request is too large"
                )
            process.stdin.write(encoded)
            try:
                await process.stdin.drain()
                raw = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=self.endpoint.request_timeout_s,
                )
            except (BrokenPipeError, ConnectionError, TimeoutError, ValueError) as error:
                self._state = GatewayLifecycleState.FAILED
                raise CrazySwarmError(
                    ErrorCode.LINK_LOST,
                    "Isaac gateway request outcome is unknown",
                    details={**self._exit_details(process), "automatic_retry_safe": False},
                ) from error
            if not raw or len(raw) > MAX_GATEWAY_MESSAGE_BYTES:
                self._state = GatewayLifecycleState.FAILED
                raise CrazySwarmError(
                    ErrorCode.LINK_LOST,
                    "Isaac gateway returned no bounded response",
                    details={**self._exit_details(process), "automatic_retry_safe": False},
                )
            return _decode_object(raw)

    async def close(self) -> None:
        process = self._process
        if process is None:
            self._state = GatewayLifecycleState.STOPPED
            return
        self._state = GatewayLifecycleState.STOPPING
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=self.endpoint.shutdown_timeout_s)
        except TimeoutError:
            process.kill()
            await process.wait()
        if self._stderr_task is not None:
            with suppress(asyncio.CancelledError):
                await self._stderr_task
        self._process = None
        self._stderr_task = None
        self._state = GatewayLifecycleState.STOPPED

    async def force_terminate(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        self._state = GatewayLifecycleState.FAILED

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while line := await process.stderr.readline():
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

    def _exit_details(self, process: asyncio.subprocess.Process | None) -> dict[str, object]:
        return {
            "process_returncode": process.returncode if process is not None else None,
            "stderr_tail": self.stderr_tail,
        }


class TlsGatewayTransport:
    """Cloud/local-network transport requiring certificate validation and no plaintext mode."""

    def __init__(self, endpoint: TlsGatewayEndpoint) -> None:
        self.endpoint = endpoint
        self._state = GatewayLifecycleState.NEW
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._request_lock = asyncio.Lock()

    @property
    def state(self) -> GatewayLifecycleState:
        return self._state

    async def start(self) -> None:
        if self._state not in {GatewayLifecycleState.NEW, GatewayLifecycleState.STOPPED}:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "TLS gateway is already started")
        self._state = GatewayLifecycleState.STARTING
        context = ssl.create_default_context(cafile=str(self.endpoint.ca_certificate))
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.endpoint.host,
                    self.endpoint.port,
                    ssl=context,
                    server_hostname=self.endpoint.server_name,
                    limit=MAX_GATEWAY_MESSAGE_BYTES + 1,
                ),
                timeout=self.endpoint.request_timeout_s,
            )
        except (OSError, TimeoutError, ssl.SSLError) as error:
            self._state = GatewayLifecycleState.FAILED
            raise CrazySwarmError(ErrorCode.LINK_LOST, "TLS Isaac gateway unavailable") from error
        self._state = GatewayLifecycleState.READY

    async def request(self, value: dict[str, Any]) -> dict[str, Any]:
        async with self._request_lock:
            if self._reader is None or self._writer is None:
                raise CrazySwarmError(ErrorCode.LINK_LOST, "TLS Isaac gateway is not connected")
            encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode() + b"\n"
            if len(encoded) > MAX_GATEWAY_MESSAGE_BYTES:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND, "Isaac gateway request is too large"
                )
            self._writer.write(encoded)
            try:
                await self._writer.drain()
                raw = await asyncio.wait_for(
                    self._reader.readline(), timeout=self.endpoint.request_timeout_s
                )
            except (ConnectionError, TimeoutError, ValueError) as error:
                self._state = GatewayLifecycleState.FAILED
                raise CrazySwarmError(
                    ErrorCode.LINK_LOST,
                    "TLS Isaac request outcome is unknown",
                    details={"automatic_retry_safe": False},
                ) from error
            if not raw or len(raw) > MAX_GATEWAY_MESSAGE_BYTES:
                self._state = GatewayLifecycleState.FAILED
                raise CrazySwarmError(ErrorCode.LINK_LOST, "TLS Isaac response is unavailable")
            return _decode_object(raw)

    async def close(self) -> None:
        self._state = GatewayLifecycleState.STOPPING
        writer = self._writer
        if writer is not None:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
        self._reader = None
        self._writer = None
        self._state = GatewayLifecycleState.STOPPED


def _decode_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND, "malformed Isaac gateway response"
        ) from error
    if not isinstance(value, dict):
        raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "Isaac gateway response must be an object")
    return value
