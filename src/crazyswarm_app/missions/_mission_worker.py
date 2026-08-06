"""Restricted subprocess used to evaluate an already validated mission artifact."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from typing import Any


def _apply_resource_limits() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    except (ImportError, OSError, ValueError):
        # The parent still enforces an execution timeout and the validated DSL.
        pass


class RecorderDrone:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    async def takeoff(self, **arguments: Any) -> None:
        self.steps.append({"action": "takeoff", "arguments": arguments})

    async def hover(self, **arguments: Any) -> None:
        self.steps.append({"action": "hover", "arguments": arguments})

    async def move_relative(self, **arguments: Any) -> None:
        self.steps.append({"action": "move_relative", "arguments": arguments})

    async def land(self, **arguments: Any) -> None:
        self.steps.append({"action": "land", "arguments": arguments})


async def _run(source: str) -> list[dict[str, Any]]:
    namespace: dict[str, Any] = {"__builtins__": {}}
    exec(compile(source, "<uploaded-mission>", "exec"), namespace, namespace)
    mission = namespace.get("mission")
    if mission is None:
        raise RuntimeError("mission entry point missing")
    drone = RecorderDrone()
    await mission(drone)
    return drone.steps


def main() -> int:
    _apply_resource_limits()
    try:
        request = json.loads(sys.stdin.buffer.read(256 * 1024))
        source = str(request["source"])
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if source_sha256 != request["source_sha256"]:
            raise RuntimeError("mission artifact hash mismatch")
        steps = asyncio.run(_run(source))
        response = {"ok": True, "source_sha256": source_sha256, "steps": steps}
    except Exception as error:
        response = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    sys.stdout.write(json.dumps(response, separators=(",", ":")))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
