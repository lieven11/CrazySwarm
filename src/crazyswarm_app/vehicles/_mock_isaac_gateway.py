"""Deterministic out-of-process gateway double; does not import Isaac or ROS."""

from __future__ import annotations

import hmac
import json
import math
import os
import sys
import time
from typing import Any

PROTOCOL_VERSION = "1.3.0"
LEGACY_MODEL_ID = "mock-isaac-crazyflie"


def _limits() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    except (ImportError, OSError, ValueError):
        pass


class Gateway:
    def __init__(self) -> None:
        self.vehicle_id: str | None = None
        self.backend_identifier: str | None = None
        self.model_id = LEGACY_MODEL_ID
        self.model_version = "1.0.0"
        self.state = "DISCONNECTED"
        self.armed = False
        self.flying = False
        self.position = [0.0, 0.0, 0.0]
        self.yaw = 0.0
        self.source_time = 0.0
        self.sequence = 0
        self.epoch = 0
        self.faults: list[str] = []
        self.gateway_instance_id = "mock-gateway-instance-1"
        self.session_id: str | None = None
        self.run_binding: dict[str, Any] | None = None

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        legacy = "operation" not in request
        operation = str(request.get("operation") or request.get("type"))
        payload = dict(request.get("payload") or {})
        if operation == "connect":
            self._authenticate(request)
            self.vehicle_id = str(request["vehicle_id"])
            self.backend_identifier = str(
                request.get("backend_identifier") or payload.get("backend_identifier") or ""
            )
            self.faults = [str(item) for item in request.get("faults", [])]
            initial_position = request.get("initial_position_m") or payload.get(
                "initial_position_m"
            )
            if initial_position is not None:
                self.position = [
                    float(initial_position["x"]),
                    float(initial_position["y"]),
                    float(initial_position["z"]),
                ]
            self.model_id = str(payload.get("expected_model_id") or LEGACY_MODEL_ID)
            self.model_version = str(payload.get("expected_model_version") or "1.0.0")
            self.session_id = f"session-{self.vehicle_id}"
            self.run_binding = None
            self.state = "READY"
            result = {
                "ok": True,
                "capabilities": self.capabilities(),
                "health": self.health(),
                "telemetry": self.telemetry(legacy=legacy),
            }
            return result
        self._identity(request)
        if operation == "bind_run":
            binding = dict(payload["binding"])
            if binding.get("model_id") != self.model_id:
                raise RuntimeError("run binding model mismatch")
            if (
                binding.get("backend_namespace") is not None
                and binding.get("backend_namespace") != self.backend_identifier
            ):
                raise RuntimeError("run binding namespace mismatch")
            self.run_binding = binding
            return {
                "ok": True,
                "health": self.health(),
                "telemetry": self.telemetry(legacy=legacy),
            }
        if operation == "snapshot":
            return {"ok": True, "health": self.health(), "telemetry": self.telemetry(legacy=legacy)}
        if operation == "health":
            return {"ok": True, "health": self.health()}
        if operation == "step":
            steps = payload.get("steps", 1)
            if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 10_000:
                raise RuntimeError("step count must be an integer from 1 through 10000")
            self.source_time += 0.01 * steps
            return {
                "ok": True,
                "health": self.health(),
                "telemetry": self.telemetry(legacy=legacy),
            }
        if operation == "reset_clock":
            self.source_time = 0.0
            self.sequence = 0
            self.epoch += 1
            return {"ok": True, "health": self.health(), "telemetry": self.telemetry(legacy=legacy)}
        if operation == "disconnect":
            self.state = "DISCONNECTED"
            self.armed = False
            self.flying = False
            return {"ok": True, "health": self.health(), "telemetry": self.telemetry(legacy=legacy)}
        if operation != "command":
            raise RuntimeError("unknown gateway request")
        command = dict(request["command"] if legacy else payload["command"])
        command_payload = dict(command["payload"])
        if legacy and self.run_binding is not None:
            if request.get("run_identity_sha256") != self.run_binding["run_identity_sha256"]:
                raise RuntimeError("command run identity mismatch")
            if not self._command_matches_bound_run(command, command_payload):
                raise RuntimeError("command mission identity mismatch")
        if not legacy:
            if payload.get("authority") != "SIMULATION":
                raise RuntimeError("gateway accepts simulation authority only")
            if self.run_binding is not None:
                if payload.get("run_identity_sha256") != self.run_binding["run_identity_sha256"]:
                    raise RuntimeError("command run identity mismatch")
                if not self._command_matches_bound_run(command, command_payload):
                    raise RuntimeError("command mission identity mismatch")
        kind = str(command_payload["kind"])
        if kind == "arm":
            self._require("READY")
            self.armed = True
        elif kind == "disarm":
            self._require("READY")
            if self.flying:
                raise RuntimeError("cannot disarm while flying")
            self.armed = False
        elif kind == "takeoff":
            self._require("READY")
            if not self.armed:
                raise RuntimeError("takeoff requires arm")
            self.state = "FLYING"
            self.flying = True
            self.position[2] = float(command_payload["height_m"])
        elif kind in {"hover", "stop_and_hold"}:
            self._require("FLYING")
        elif kind == "move_relative":
            self._require("FLYING")
            dx, dy = float(command_payload["x_m"]), float(command_payload["y_m"])
            if command_payload.get("frame") == "body":
                dx, dy = (
                    dx * math.cos(self.yaw) - dy * math.sin(self.yaw),
                    dx * math.sin(self.yaw) + dy * math.cos(self.yaw),
                )
            self.position[0] += dx
            self.position[1] += dy
            self.position[2] += float(command_payload["z_m"])
            self.yaw += float(command_payload["yaw_rad"])
        elif kind == "execute_trajectory":
            self._require("FLYING")
            trajectory = dict(command_payload["trajectory"])
            points = list(trajectory["points"])
            if len(points) < 2:
                raise RuntimeError("trajectory requires at least two points")
            terminal = dict(points[-1])
            terminal_position = dict(terminal["position_m"])
            self.position = [
                float(terminal_position["x"]),
                float(terminal_position["y"]),
                float(terminal_position["z"]),
            ]
            self.yaw = float(terminal["yaw_rad"])
        elif kind in {"land", "abort"}:
            if not self.flying:
                raise RuntimeError("landing requires flight")
            self.position[2] = 0.0
            self.state = "READY"
            self.flying = False
            self.armed = False
        elif kind == "emergency_stop":
            self.state = "EMERGENCY"
            self.flying = False
            self.armed = False
        else:
            raise RuntimeError(f"unsupported command: {kind}")
        duration_s = command_payload.get("duration_s")
        if kind == "execute_trajectory":
            duration_s = command_payload["trajectory"]["points"][-1]["time_from_start_s"]
        self.source_time += float(duration_s or 0.01)
        return {
            "ok": True,
            "command_id": command["command_id"],
            "health": self.health(),
            "telemetry": self.telemetry(legacy=legacy),
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "authority": "SIMULATION",
            "commands": [
                "arm",
                "disarm",
                "takeoff",
                "hover",
                "move_relative",
                "execute_trajectory",
                "stop_and_hold",
                "land",
                "abort",
                "emergency_stop",
            ],
            "vehicle_capabilities": [
                "arming",
                "relative_positioning",
                "high_level_commands",
                "range_sensing",
                "emergency_stop",
                "time_parameterized_trajectory",
            ],
            "signals": ["position", "ground-truth-position", "imu", "flow", "ranges"],
            "maximum_vehicles": 1,
            "telemetry_queue_bound": 100,
            "supports_headless": True,
            "supports_manual_step": True,
            "supports_clock_reset": True,
            "supports_reconnect_after_unknown_command": False,
            "cameras_enabled": False,
            "rtx_lidar_enabled": False,
            "digital_twin_enabled": False,
        }

    def health(self) -> dict[str, Any]:
        lifecycle = "RUN_BOUND" if self.run_binding is not None else "READY"
        if self.state == "DISCONNECTED":
            lifecycle = "STOPPING"
        return {
            "lifecycle": lifecycle,
            "simulator_process": "READY",
            "ready": self.state != "DISCONNECTED",
            "gateway_instance_id": self.gateway_instance_id,
            "session_id": self.session_id,
            "telemetry_queue_depth": 0,
            "telemetry_dropped_total": 0,
            "issues": [],
        }

    def telemetry(self, *, legacy: bool) -> dict[str, Any]:
        basic = {
            "vehicle_id": self.vehicle_id,
            "sequence": self.sequence,
            "source_timestamp_s": self.source_time,
            "source_clock_epoch": self.epoch,
            "state": self.state,
            "armed": self.armed,
            "flying": self.flying,
            "position": self.position,
            "yaw": self.yaw,
        }
        self.sequence += 1
        if legacy:
            basic["run_identity_sha256"] = (
                self.run_binding.get("run_identity_sha256") if self.run_binding else None
            )
            return basic
        z = max(0.0, self.position[2])
        run_hash = self.run_binding.get("run_identity_sha256") if self.run_binding else None
        return {
            "vehicle_id": self.vehicle_id,
            "sequence": basic["sequence"],
            "source_timestamp_s": self.source_time,
            "source_clock_id": f"mock-isaac-{self.vehicle_id}",
            "source_clock_epoch": self.epoch,
            "simulation_timestamp_s": self.source_time,
            "source_class": "SIMULATED_MODEL",
            "model_id": self.model_id,
            "model_version": self.model_version,
            "frame": "home",
            "linear_unit": "m",
            "angular_unit": "rad",
            "run_identity_sha256": run_hash,
            "telemetry": {
                "state": self.state,
                "armed": self.armed,
                "flying": self.flying,
                "position_m": {"x": self.position[0], "y": self.position[1], "z": z},
                "ground_truth_position_m": {
                    "x": self.position[0],
                    "y": self.position[1],
                    "z": z,
                },
                "velocity_m_s": {"x": 0.0, "y": 0.0, "z": 0.0},
                "attitude": {"roll_rad": 0.0, "pitch_rad": 0.0, "yaw_rad": self.yaw},
                "frame": "home",
                "position_is_estimate": True,
                "localization_source": "simulated",
                "localization_quality_percent": 100.0,
                "battery_percent": 100.0,
                "transport": {
                    "kind": "modeled_transport",
                    "source_class": "SIMULATED_MODEL",
                    "delivery_quality_percent": 100.0,
                    "latency_ms": 0.0,
                    "packet_loss_percent": 0.0,
                },
                "capabilities": {
                    "features": self.capabilities()["vehicle_capabilities"],
                    "decks": [],
                },
                "imu": {
                    "acceleration_body_m_s2": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "angular_velocity_body_rad_s": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                "flow": {
                    "velocity_body_m_s": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "ground_distance_m": z,
                    "quality_percent": 100.0 if z > 0.0 else 0.0,
                },
                "ranges": {
                    "front_m": max(0.0, 2.0 - self.position[0]),
                    "back_m": max(0.0, 2.0 + self.position[0]),
                    "left_m": max(0.0, 2.0 - self.position[1]),
                    "right_m": max(0.0, 2.0 + self.position[1]),
                    "up_m": max(0.0, 2.5 - z),
                    "down_m": z,
                    "max_range_m": 4.0,
                    "statuses": {
                        "front": "VALID",
                        "back": "VALID",
                        "left": "VALID",
                        "right": "VALID",
                        "up": "VALID",
                        "down": "VALID",
                    },
                    "source_timestamp_s": self.source_time,
                },
                "faults": [],
            },
        }

    def _authenticate(self, request: dict[str, Any]) -> None:
        expected = os.environ.get("CRAZYSWARM_ISAAC_GATEWAY_TOKEN")
        if expected is None:
            return
        supplied = request.get("authentication_token")
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
            raise RuntimeError("gateway authentication failed")

    def _identity(self, request: dict[str, Any]) -> None:
        if request.get("vehicle_id") != self.vehicle_id:
            raise RuntimeError("gateway vehicle identity mismatch")
        session_id = request.get("session_id")
        if session_id is not None and session_id != self.session_id:
            raise RuntimeError("gateway session identity mismatch")

    def _require(self, state: str) -> None:
        if self.state != state:
            raise RuntimeError(f"command requires {state}")

    def _command_matches_bound_run(
        self,
        command: dict[str, Any],
        command_payload: dict[str, Any],
    ) -> bool:
        if self.run_binding is None:
            return True
        if command.get("mission_run_id") == self.run_binding["mission_run_id"]:
            fleet_session_id = self.run_binding.get("fleet_session_id")
            if fleet_session_id is None:
                return command.get("fleet") is None
            fleet = command.get("fleet")
            return isinstance(fleet, dict) and all(
                fleet.get(field) == self.run_binding.get(field)
                for field in (
                    "fleet_session_id",
                    "fleet_run_id",
                    "deployment_sha256",
                    "task_id",
                    "task_lease_generation",
                    "backend_namespace",
                    "preparation_state",
                )
            )
        kind = command_payload.get("kind")
        source = command.get("source")
        supervised_recovery = source == "SUPERVISOR" and kind in {
            "stop_and_hold",
            "land",
            "abort",
            "emergency_stop",
        }
        mission_cleanup = source == "MISSION" and kind == "disarm"
        return supervised_recovery or mission_cleanup

    def pop_fault(self) -> str | None:
        return self.faults.pop(0) if self.faults else None

    def restart(self) -> None:
        self.state = "DISCONNECTED"
        self.armed = False
        self.flying = False
        self.position = [0.0, 0.0, 0.0]
        self.yaw = 0.0
        self.source_time = 0.0
        self.sequence = 0
        self.epoch += 1
        self.run_binding = None


def _metadata(
    gateway: Gateway,
    request: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    operation = str(request.get("operation") or request.get("type") or "snapshot")
    return {
        **response,
        "request_id": request.get("request_id"),
        "operation": operation,
        "protocol_version": PROTOCOL_VERSION,
        "vehicle_id": gateway.vehicle_id or str(request.get("vehicle_id") or "unknown"),
        "gateway_instance_id": gateway.gateway_instance_id,
        "session_id": gateway.session_id,
        "model_id": gateway.model_id,
        "model_version": gateway.model_version,
        "frame": "home",
    }


def _apply_fault(
    gateway: Gateway,
    request: dict[str, Any],
    response: dict[str, Any],
    fault: str | None,
) -> tuple[dict[str, Any], str | None]:
    telemetry = response.get("telemetry")
    if fault == "wrong_id" and isinstance(telemetry, dict):
        telemetry["vehicle_id"] = "wrong-vehicle"
    elif fault == "wrong_frame":
        response["frame"] = "map"
    elif fault == "wrong_model":
        response["model_id"] = "wrong-model"
    elif fault == "stale" and isinstance(telemetry, dict):
        telemetry["sequence"] = max(0, int(telemetry["sequence"]) - 1)
        telemetry["source_timestamp_s"] = max(0.0, float(telemetry["source_timestamp_s"]) - 1.0)
    elif fault == "disconnected" and isinstance(telemetry, dict):
        nested = telemetry.get("telemetry")
        target: dict[str, Any] = nested if isinstance(nested, dict) else telemetry
        target.update({"state": "DISCONNECTED", "armed": False, "flying": False})
    elif fault == "reordered":
        response["request_id"] = int(request["request_id"]) - 1
    return response, fault


def main() -> int:
    _limits()
    gateway = Gateway()
    for raw in sys.stdin.buffer:
        request: Any = {}
        try:
            request = json.loads(raw)
            operation = request.get("operation") or request.get("type")
            fault = None if operation == "connect" else gateway.pop_fault()
            if fault == "delayed":
                time.sleep(0.05)
            if fault == "crashed":
                os._exit(17)
            if fault == "restarted":
                gateway.restart()
            response = _metadata(gateway, request, gateway.handle(request))
            response, fault = _apply_fault(gateway, request, response, fault)
            if fault == "acknowledgement_lost":
                os._exit(18)
        except BaseException as error:
            response = _metadata(
                gateway,
                request if isinstance(request, dict) else {},
                {
                    "ok": False,
                    "error_code": "GATEWAY_REJECTED",
                    "error": f"{type(error).__name__}: {error}",
                },
            )
            fault = None
        if fault == "malformed":
            sys.stdout.write("not-json\n")
        else:
            line = json.dumps(response, separators=(",", ":")) + "\n"
            sys.stdout.write(line)
            if fault == "duplicate":
                sys.stdout.write(line)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
