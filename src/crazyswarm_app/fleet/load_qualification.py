from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi.testclient import TestClient
from pydantic import Field

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    load_versioned_contract,
)


class FleetLoadBudgets(ContractModel):
    schema_version: Literal[1] = 1
    budget_id: Identifier
    iterations: int = Field(ge=10, le=10000)
    state_api_p95_ms: float = Field(gt=0.0)
    replay_api_p95_ms: float = Field(gt=0.0)
    storage_query_p95_ms: float = Field(gt=0.0)
    maximum_state_payload_bytes: int = Field(gt=0)
    maximum_replay_payload_bytes: int = Field(gt=0)
    maximum_remaining_tasks: int = Field(ge=0)
    maximum_total_runtime_s: float = Field(gt=0.0)


class FleetLoadMeasurements(ContractModel):
    state_api_p95_ms: float = Field(ge=0.0)
    replay_api_p95_ms: float = Field(ge=0.0)
    storage_query_p95_ms: float = Field(ge=0.0)
    state_payload_bytes: int = Field(ge=0)
    replay_payload_bytes: int = Field(ge=0)
    remaining_fleet_tasks: int = Field(ge=0)
    remaining_mission_tasks: int = Field(ge=0)
    telemetry_tasks_after_shutdown: int = Field(ge=0)
    remaining_task_leases: int = Field(ge=0)
    bus_subscribers_after_shutdown: int = Field(ge=0)
    reserve_ready_disarmed_observed: bool
    total_runtime_s: float = Field(ge=0.0)


class FleetLoadQualificationReport(ContractModel):
    schema_version: Literal[1] = 1
    budget_id: Identifier
    decision: Literal["PASS_SOFTWARE_ONLY", "FAIL"]
    vehicle_count: int = Field(ge=3)
    state_iterations: int = Field(ge=1)
    replay_iterations: int = Field(ge=1)
    storage_iterations: int = Field(ge=1)
    measurements: FleetLoadMeasurements
    failures: tuple[str, ...]
    live_isaac: Literal["NOT_RUN"] = "NOT_RUN"
    physical_flight: Literal["NOT_RUN"] = "NOT_RUN"
    normalized_configuration_sha256: SHA256


def load_fleet_load_budgets(path: Path) -> FleetLoadBudgets:
    return FleetLoadBudgets.model_validate_json(path.read_text(encoding="utf-8"))


def run_fleet_load_qualification(root: Path) -> FleetLoadQualificationReport:
    started = time.perf_counter()
    budgets = load_fleet_load_budgets(root / "config/qualification/fleet-load-budgets-v1.json")
    deployment = load_versioned_contract(
        root / "config/fleet/three-drone-persistent-coverage-v1.yaml",
        DeploymentManifest,
    )
    binding = load_versioned_contract(
        root / "config/fleet/fast-sim-three-drone-binding-v1.yaml",
        BackendBindingProfile,
    )
    token = "fleet-load-qualification-token-00000000"
    state_samples: list[float] = []
    replay_samples: list[float] = []
    storage_samples: list[float] = []
    state_payload = b""
    replay_payload = b""
    remaining_fleet_tasks = 0
    remaining_mission_tasks = 0
    telemetry_after_shutdown = -1
    remaining_task_leases = -1
    bus_subscribers_after_shutdown = -1
    reserve_ready_disarmed_observed = False
    with tempfile.TemporaryDirectory(prefix="crazyswarm-fleet-load-") as temp:
        temp_path = Path(temp)
        config = load_config(root / "config/app.yaml").model_copy(
            update={"cache_directory": temp_path / "cache"}
        )
        runtime = create_runtime(
            config,
            root / "config/worlds/three_drone_fleet.yaml",
            evidence_path=temp_path / "evidence.sqlite3",
        )
        app = create_app(runtime, local_token=token)
        with TestClient(app) as client:
            create = client.post(
                "/api/v1/fleet/sessions",
                headers=_headers(token),
                json={
                    "execution_session_id": "load-session",
                    "fleet_run_id": "load-run",
                    "mission_id": "hover",
                    "deployment": deployment.model_dump(mode="json"),
                    "binding": binding.model_dump(mode="json"),
                },
            )
            create.raise_for_status()
            prepare = client.post(
                "/api/v1/fleet/sessions/load-session/prepare",
                headers=_headers(token),
            )
            prepare.raise_for_status()
            reserve = next(
                item
                for item in prepare.json()["session"]["vehicles"]
                if item["vehicle_id"] == "cf03"
            )
            reserve_telemetry = reserve["latest_telemetry"]["telemetry"]
            reserve_ready_disarmed_observed = (
                reserve["connection"] == "READY"
                and reserve["observation"] == "CURRENT"
                and reserve_telemetry["armed"] is False
                and reserve_telemetry["flying"] is False
            )
            launch = client.post(
                "/api/v1/fleet/runs/load-run/start",
                headers=_headers(token),
                json={
                    "assignments": {
                        "cover-zone-a": "cf01",
                        "cover-zone-b": "cf02",
                    }
                },
            )
            launch.raise_for_status()
            for _ in range(600):
                run = client.get("/api/v1/fleet/runs/load-run", headers=_headers(token))
                run.raise_for_status()
                if run.json()["result"] is not None:
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("three-vehicle load qualification run timed out")

            for _ in range(budgets.iterations):
                sample_started = time.perf_counter()
                response = client.get("/api/v1/state", headers=_headers(token))
                response.raise_for_status()
                state_samples.append((time.perf_counter() - sample_started) * 1000.0)
                state_payload = response.content
            for _ in range(budgets.iterations):
                sample_started = time.perf_counter()
                response = client.get("/api/v1/fleet/runs/load-run/replay", headers=_headers(token))
                response.raise_for_status()
                replay_samples.append((time.perf_counter() - sample_started) * 1000.0)
                replay_payload = response.content
            for _ in range(budgets.iterations):
                sample_started = time.perf_counter()
                runtime.store.query_events(limit=200)
                storage_samples.append((time.perf_counter() - sample_started) * 1000.0)
            remaining_fleet_tasks = len(runtime.fleet_tasks)
            remaining_mission_tasks = len(runtime.mission_tasks)
            remaining_task_leases = sum(
                item.lease is not None
                for coordinator in runtime.fleet_coordinators.values()
                for item in coordinator.tasks.records()
            )
        telemetry_after_shutdown = len(runtime.telemetry_tasks)
        bus_subscribers_after_shutdown = runtime.bus.stats.subscriber_count

    measurements = FleetLoadMeasurements(
        state_api_p95_ms=_percentile_95(state_samples),
        replay_api_p95_ms=_percentile_95(replay_samples),
        storage_query_p95_ms=_percentile_95(storage_samples),
        state_payload_bytes=len(state_payload),
        replay_payload_bytes=len(replay_payload),
        remaining_fleet_tasks=remaining_fleet_tasks,
        remaining_mission_tasks=remaining_mission_tasks,
        telemetry_tasks_after_shutdown=telemetry_after_shutdown,
        remaining_task_leases=remaining_task_leases,
        bus_subscribers_after_shutdown=bus_subscribers_after_shutdown,
        reserve_ready_disarmed_observed=reserve_ready_disarmed_observed,
        total_runtime_s=time.perf_counter() - started,
    )
    failures = _budget_failures(budgets, measurements)
    return FleetLoadQualificationReport(
        budget_id=budgets.budget_id,
        decision="PASS_SOFTWARE_ONLY" if not failures else "FAIL",
        vehicle_count=len(deployment.fleet),
        state_iterations=budgets.iterations,
        replay_iterations=budgets.iterations,
        storage_iterations=budgets.iterations,
        measurements=measurements,
        failures=tuple(failures),
        normalized_configuration_sha256=canonical_sha256(
            {
                "budgets": budgets,
                "deployment": deployment.sha256,
                "binding": binding.sha256,
            }
        ),
    )


def _headers(token: str) -> dict[str, str]:
    return {
        "X-Local-Token": token,
        "X-Client-ID": "fleet-load-qualification",
        "Idempotency-Key": str(uuid.uuid4()),
    }


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def _budget_failures(
    budgets: FleetLoadBudgets,
    measurements: FleetLoadMeasurements,
) -> list[str]:
    checks = {
        "state API p95": measurements.state_api_p95_ms <= budgets.state_api_p95_ms,
        "replay API p95": measurements.replay_api_p95_ms <= budgets.replay_api_p95_ms,
        "storage query p95": (measurements.storage_query_p95_ms <= budgets.storage_query_p95_ms),
        "state payload": (measurements.state_payload_bytes <= budgets.maximum_state_payload_bytes),
        "replay payload": (
            measurements.replay_payload_bytes <= budgets.maximum_replay_payload_bytes
        ),
        "fleet tasks": (measurements.remaining_fleet_tasks <= budgets.maximum_remaining_tasks),
        "mission tasks": (measurements.remaining_mission_tasks <= budgets.maximum_remaining_tasks),
        "telemetry tasks after shutdown": (
            measurements.telemetry_tasks_after_shutdown <= budgets.maximum_remaining_tasks
        ),
        "task leases": (measurements.remaining_task_leases <= budgets.maximum_remaining_tasks),
        "bus subscribers after shutdown": (
            measurements.bus_subscribers_after_shutdown <= budgets.maximum_remaining_tasks
        ),
        "reserve readiness": measurements.reserve_ready_disarmed_observed,
        "total runtime": (measurements.total_runtime_s <= budgets.maximum_total_runtime_s),
    }
    return [name for name, passed in checks.items() if not passed]
