#!/usr/bin/env python3
"""Run an uploaded Python mission while profiling the live dashboard data path.

The script uses only the standard library. It measures application-layer network
traffic (response bytes), request latency, source-telemetry cadence, visible pose
cadence, and optional local process CPU/RSS samples. It never runs arbitrary source:
the mission must be an existing Python file accepted by the bounded mission loader.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:3001/control-api"
DEFAULT_MISSION = Path("missions/performance/smooth_motion_probe.py")


@dataclass(frozen=True, slots=True)
class HttpSample:
    payload: Any
    elapsed_ms: float
    response_bytes: int


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": max(values) if values else None,
    }


class ControlClient:
    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, path: str, *, method: str = "GET", body: Any = None) -> HttpSample:
        encoded = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        headers = {
            "Accept": "application/json",
            "X-Client-ID": "dashboard-performance-profiler",
        }
        if encoded is not None:
            headers["Content-Type"] = "application/json"
        if method != "GET":
            headers["Idempotency-Key"] = uuid.uuid4().hex
        if self.token:
            headers["X-Local-Token"] = self.token
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=encoded,
            headers=headers,
            method=method,
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                content = response.read()
        except urllib.error.HTTPError as error:
            content = error.read()
            try:
                details = json.loads(content)
            except json.JSONDecodeError:
                details = content.decode(errors="replace")
            raise RuntimeError(f"{method} {path} returned {error.code}: {details}") from error
        elapsed_ms = (time.perf_counter() - started) * 1_000.0
        return HttpSample(json.loads(content), elapsed_ms, len(content))


def upload_and_start(client: ControlClient, mission_path: Path) -> tuple[str, str]:
    source = mission_path.read_text(encoding="utf-8")
    uploaded = client.request(
        "/api/v1/mission-files",
        method="POST",
        body={
            "name": "Performance smooth motion probe",
            "filename": mission_path.name,
            "source": source,
        },
    ).payload
    mission_id = str(uploaded["mission_id"])
    preview = client.request(f"/api/v1/mission-files/{mission_id}/preview").payload
    plan = preview["plan"]
    acknowledged = [
        finding["code"]
        for finding in plan.get("findings", [])
        if finding.get("requires_confirmation") is True
    ]
    approved = client.request(
        f"/api/v1/mission-files/{mission_id}/approve",
        method="POST",
        body={
            "expected_plan_sha256": preview["plan_sha256"],
            "acknowledged_finding_codes": acknowledged,
        },
    ).payload
    started = client.request(
        f"/api/v1/mission-files/{mission_id}/start",
        method="POST",
        body={
            "execution_mode": "SIMULATION",
            "approval_id": approved["approval_id"],
            "expected_plan_sha256": approved["plan_sha256"],
        },
    ).payload
    return mission_id, str(started["mission_run_id"])


def process_sample(pids: tuple[int, ...]) -> dict[str, float] | None:
    if not pids:
        return None
    completed = subprocess.run(
        ["ps", "-o", "%cpu=,rss=", "-p", ",".join(map(str, pids))],
        capture_output=True,
        check=False,
        text=True,
    )
    rows = [line.split() for line in completed.stdout.splitlines() if line.strip()]
    parsed = [(float(row[0]), float(row[1])) for row in rows if len(row) >= 2]
    if not parsed:
        return None
    return {
        "cpu_percent": sum(cpu for cpu, _ in parsed),
        "rss_mib": sum(rss_kib for _, rss_kib in parsed) / 1024.0,
    }


def find_run(state: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in state.get("mission_runs", []) if item.get("mission_run_id") == run_id),
        None,
    )


def observed_vehicle(state: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    candidates = [
        item
        for item in state.get("vehicles", [])
        if isinstance(item.get("observation"), dict)
        and item["observation"].get("run_id") == run_id
    ]
    return candidates[0] if candidates else None


def telemetry_fields(
    vehicle: dict[str, Any] | None,
) -> tuple[float | None, tuple[float, float, float] | None]:
    envelope = None if vehicle is None else vehicle.get("telemetry")
    telemetry = None if not isinstance(envelope, dict) else envelope.get("telemetry")
    source_time = None if not isinstance(envelope, dict) else envelope.get("source_timestamp_s")
    position = None if not isinstance(telemetry, dict) else telemetry.get("position_m")
    if not isinstance(source_time, (int, float)) or not isinstance(position, dict):
        return None, None
    values = (position.get("x"), position.get("y"), position.get("z"))
    if not all(isinstance(value, (int, float)) for value in values):
        return float(source_time), None
    return float(source_time), (float(values[0]), float(values[1]), float(values[2]))


def profile(
    client: ControlClient,
    mission_path: Path,
    *,
    poll_period_s: float,
    timeout_s: float,
    pids: tuple[int, ...],
) -> dict[str, Any]:
    mission_id, run_id = upload_and_start(client, mission_path)
    started_wall = time.perf_counter()
    request_latency_ms: list[float] = []
    response_sizes: list[float] = []
    poll_intervals_ms: list[float] = []
    source_intervals_ms: list[float] = []
    pose_steps_m: list[float] = []
    process_cpu: list[float] = []
    process_rss: list[float] = []
    last_poll_wall: float | None = None
    last_source_time: float | None = None
    last_position: tuple[float, float, float] | None = None
    repeated_source_polls = 0
    terminal: dict[str, Any] | None = None

    try:
        while time.perf_counter() - started_wall < timeout_s:
            iteration_started = time.perf_counter()
            sample = client.request("/api/v1/state")
            now = time.perf_counter()
            request_latency_ms.append(sample.elapsed_ms)
            response_sizes.append(float(sample.response_bytes))
            if last_poll_wall is not None:
                poll_intervals_ms.append((now - last_poll_wall) * 1_000.0)
            last_poll_wall = now

            state = sample.payload
            run = find_run(state, run_id)
            vehicle = observed_vehicle(state, run_id)
            source_time, position = telemetry_fields(vehicle)
            if source_time is not None:
                if last_source_time is not None:
                    delta_s = source_time - last_source_time
                    if delta_s > 0:
                        source_intervals_ms.append(delta_s * 1_000.0)
                    else:
                        repeated_source_polls += 1
                last_source_time = source_time
            if position is not None and last_position is not None and position != last_position:
                pose_steps_m.append(math.dist(position, last_position))
            if position is not None:
                last_position = position

            resources = process_sample(pids)
            if resources:
                process_cpu.append(resources["cpu_percent"])
                process_rss.append(resources["rss_mib"])

            if run and run.get("result") is not None:
                terminal = run["result"]
                break
            remaining = poll_period_s - (time.perf_counter() - iteration_started)
            if remaining > 0:
                time.sleep(remaining)
        else:
            client.request(f"/api/v1/mission-runs/{run_id}/cancel", method="POST", body={})
            raise TimeoutError(f"mission {run_id} did not finish within {timeout_s:.1f}s")
    finally:
        elapsed_s = time.perf_counter() - started_wall

    total_bytes = int(sum(response_sizes))
    return {
        "schema_version": 1,
        "mission_file": str(mission_path),
        "mission_id": mission_id,
        "run_id": run_id,
        "result": terminal,
        "wall_duration_s": elapsed_s,
        "poll_period_target_ms": poll_period_s * 1_000.0,
        "state_requests": len(request_latency_ms),
        "state_request_latency_ms": summary(request_latency_ms),
        "state_poll_interval_ms": summary(poll_intervals_ms),
        "state_payload_bytes": summary(response_sizes),
        "state_payload_total_bytes": total_bytes,
        "state_payload_kib_per_s": total_bytes / 1024.0 / elapsed_s,
        "telemetry_source_interval_ms": summary(source_intervals_ms),
        "repeated_source_polls": repeated_source_polls,
        "visible_pose_step_m": summary(pose_steps_m),
        "process_pids": list(pids),
        "process_cpu_percent": summary(process_cpu),
        "process_rss_mib": summary(process_rss),
        "notes": {
            "network_scope": (
                "HTTP response bodies read by this profiler; protocol overhead is excluded"
            ),
            "cpu_scope": "sum of ps CPU percent for explicitly supplied PIDs",
            "renderer_scope": (
                "browser frame pacing and snapshot jank require the companion rendered test"
            ),
        },
    }


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=os.environ.get("CRAZYSWARM_LOCAL_TOKEN"))
    parser.add_argument("--mission", type=Path, default=DEFAULT_MISSION)
    parser.add_argument("--poll-period-ms", type=float, default=100.0)
    parser.add_argument("--timeout-s", type=float, default=45.0)
    parser.add_argument("--pid", type=int, action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = arguments()
    if args.poll_period_ms <= 0 or args.timeout_s <= 0:
        raise SystemExit("poll period and timeout must be positive")
    result = profile(
        ControlClient(args.base_url, args.token),
        args.mission,
        poll_period_s=args.poll_period_ms / 1_000.0,
        timeout_s=args.timeout_s,
        pids=tuple(args.pid),
    )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0 if result["result"] and result["result"].get("status") == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
