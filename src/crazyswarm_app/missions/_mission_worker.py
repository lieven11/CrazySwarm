"""Isolated request/response runtime for an already statically validated mission."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from typing import Any, cast


def _apply_resource_limits() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    except (ImportError, OSError, ValueError):
        # The parent also enforces wall timeout, validated syntax, and message budgets.
        pass


class AttrView:
    """Read-only attribute view over canonical JSON observations."""

    __slots__ = ("_values",)

    def __init__(self, values: dict[str, Any]) -> None:
        object.__setattr__(
            self,
            "_values",
            {
                key: AttrView(value) if isinstance(value, dict) else value
                for key, value in values.items()
            },
        )

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name: str, value: Any) -> None:
        del name, value
        raise TypeError("mission observations are immutable")


class ProtocolDrone:
    def __init__(self, *, command_budget: int, observation_budget: int, role: str) -> None:
        self.role = role
        self.command_budget = command_budget
        self.observation_budget = observation_budget
        self.commands = 0
        self.observations = 0
        self.request_id = 0

    async def _request(self, action: str, arguments: dict[str, Any]) -> Any:
        if action == "observe":
            self.observations += 1
            if self.observations > self.observation_budget:
                raise RuntimeError("mission observation budget exceeded")
        elif action != "checkpoint":
            self.commands += 1
            if self.commands > self.command_budget:
                raise RuntimeError("mission command budget exceeded")
        self.request_id += 1
        request = {
            "type": "call",
            "id": self.request_id,
            "action": action,
            "arguments": arguments,
        }
        sys.stdout.write(json.dumps(request, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        raw = sys.stdin.buffer.readline(1024 * 1024)
        if not raw:
            raise RuntimeError("mission parent closed the protocol")
        response = json.loads(raw)
        if response.get("id") != self.request_id:
            raise RuntimeError("mission protocol response identity mismatch")
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "mission call failed"))
        return response.get("result")

    async def takeoff(self, **arguments: Any) -> None:
        await self._request("takeoff", arguments)

    async def hover(self, **arguments: Any) -> None:
        await self._request("hover", arguments)

    async def move_relative(self, **arguments: Any) -> None:
        await self._request("move_relative", arguments)

    async def land(self, **arguments: Any) -> None:
        await self._request("land", arguments)

    async def observe(self, **arguments: Any) -> AttrView:
        value = await self._request("observe", arguments)
        if not isinstance(value, dict):
            raise RuntimeError("mission observation response is malformed")
        return AttrView(value)

    async def wait(self, **arguments: Any) -> None:
        await self._request("wait", arguments)

    async def checkpoint(self) -> None:
        await self._request("checkpoint", {})


class RecorderDrone:
    def __init__(self, *, role: str = "primary") -> None:
        self.role = role
        self.steps: list[dict[str, Any]] = []

    async def takeoff(self, **arguments: Any) -> None:
        self.steps.append({"action": "takeoff", "arguments": arguments})

    async def hover(self, **arguments: Any) -> None:
        self.steps.append({"action": "hover", "arguments": arguments})

    async def move_relative(self, **arguments: Any) -> None:
        self.steps.append({"action": "move_relative", "arguments": arguments})

    async def land(self, **arguments: Any) -> None:
        self.steps.append({"action": "land", "arguments": arguments})

    async def observe(self, **arguments: Any) -> AttrView:
        del arguments
        return AttrView({})

    async def wait(self, **arguments: Any) -> None:
        self.steps.append({"action": "hover", "arguments": arguments})

    async def checkpoint(self) -> None:
        return


def _namespace() -> dict[str, Any]:
    return {
        "__builtins__": {
            "range": range,
            "min": min,
            "max": max,
            "abs": abs,
            "len": len,
        }
    }


async def _entrypoint(source: str, drone: Any) -> None:
    namespace = _namespace()
    exec(compile(source, "<mission-artifact>", "exec"), namespace, namespace)
    mission = namespace.get("mission")
    if mission is None:
        raise RuntimeError("mission entry point missing")
    await mission(drone)


def _initial_request() -> dict[str, Any]:
    raw = sys.stdin.buffer.readline(256 * 1024)
    if not raw:
        raise RuntimeError("mission start request missing")
    request = cast(dict[str, Any], json.loads(raw))
    source = str(request["source"])
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest != request["source_sha256"]:
        raise RuntimeError("mission artifact hash mismatch")
    request["source"] = source
    return request


def main() -> int:
    _apply_resource_limits()
    try:
        request = _initial_request()
        source = request["source"]
        # Requests from the previous parent runtime did not include a mode.
        # Preserve their record-and-replay behavior so a worker upgrade cannot
        # break an already-running control service.
        if request.get("mode", "record") == "record":
            recorder_drone = RecorderDrone(role=str(request.get("role_id", "primary")))
            asyncio.run(_entrypoint(source, recorder_drone))
            response = {
                "type": "result",
                "ok": True,
                "source_sha256": request["source_sha256"],
                "steps": recorder_drone.steps,
            }
        else:
            protocol_drone = ProtocolDrone(
                command_budget=int(request["command_budget"]),
                observation_budget=int(request["observation_budget"]),
                role=str(request.get("role_id", "primary")),
            )
            asyncio.run(_entrypoint(source, protocol_drone))
            response = {
                "type": "result",
                "ok": True,
                "source_sha256": request["source_sha256"],
                "commands": protocol_drone.commands,
                "observations": protocol_drone.observations,
            }
    except BaseException as error:
        response = {"type": "result", "ok": False, "error": f"{type(error).__name__}: {error}"}
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
