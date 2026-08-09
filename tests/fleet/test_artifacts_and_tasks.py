from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import VehicleCapability
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    ExecutionBackend,
    load_versioned_contract,
)
from crazyswarm_app.fleet.tasks import TaskLedger, TaskState, replay_task

from .conftest import binding_for


def test_artifacts_are_strict_versioned_and_deterministic(
    two_drone_deployment: DeploymentManifest,
    tmp_path: Path,
) -> None:
    first = two_drone_deployment.sha256
    second = DeploymentManifest.model_validate(
        json.loads(two_drone_deployment.model_dump_json())
    ).sha256
    assert first == second
    assert len(first) == 64

    path = tmp_path / "deployment.json"
    path.write_text(two_drone_deployment.model_dump_json(), encoding="utf-8")
    assert load_versioned_contract(path, DeploymentManifest) == two_drone_deployment

    raw = two_drone_deployment.model_dump(mode="json")
    raw["schema_version"] = 2
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="explicit migration"):
        load_versioned_contract(path, DeploymentManifest)

    path.write_text(two_drone_deployment.model_dump_json(), encoding="utf-8")
    command = (
        "from pathlib import Path; "
        "from crazyswarm_app.fleet.artifacts import DeploymentManifest,load_versioned_contract; "
        f"print(load_versioned_contract(Path({str(path)!r}),DeploymentManifest).sha256)"
    )
    environment = {**os.environ, "PYTHONHASHSEED": "random"}
    hashes = {
        subprocess.check_output(
            [sys.executable, "-c", command],
            text=True,
            env=environment,
        ).strip()
        for _ in range(4)
    }
    assert hashes == {first}


def test_binding_rejects_cross_bound_or_missing_identity(
    two_drone_deployment: DeploymentManifest,
) -> None:
    raw = binding_for(two_drone_deployment, backend=ExecutionBackend.FAST_SIM).model_dump(
        mode="json"
    )
    raw["vehicles"][0]["expected_vehicle_id"] = "cf02"
    with pytest.raises(ValidationError, match="cross-bound"):
        BackendBindingProfile.model_validate(raw)

    full_binding = binding_for(two_drone_deployment, backend=ExecutionBackend.FAST_SIM)
    incomplete = full_binding.model_copy(update={"vehicles": full_binding.vehicles[:1]})
    with pytest.raises(CrazySwarmError) as captured:
        incomplete.validate_for(two_drone_deployment)
    assert captured.value.code is ErrorCode.IDENTITY_MISMATCH
    assert captured.value.details["missing"] == ["cf02"]


def test_task_ledger_enforces_energy_capability_and_lease_generation(
    two_drone_deployment: DeploymentManifest,
) -> None:
    ledger = TaskLedger(
        fleet_session_id="session-1",
        fleet_run_id="run-1",
        deployment_sha256=two_drone_deployment.sha256,
        definitions=two_drone_deployment.tasks,
        lease_duration_s=5.0,
    )
    capabilities = frozenset(
        {
            VehicleCapability.RELATIVE_POSITIONING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
        }
    )
    with pytest.raises(CrazySwarmError) as captured:
        ledger.assign(
            "inspect-a",
            "cf01",
            capabilities=capabilities,
            battery_percent=5.0,
            now_s=1.0,
        )
    assert captured.value.code is ErrorCode.CRITICAL_BATTERY

    simulation_override = TaskLedger(
        fleet_session_id="session-simulation-override",
        fleet_run_id="run-simulation-override",
        deployment_sha256=two_drone_deployment.sha256,
        definitions=two_drone_deployment.tasks,
        lease_duration_s=5.0,
    )
    overridden = simulation_override.assign(
        "inspect-a",
        "cf01",
        capabilities=capabilities,
        battery_percent=5.0,
        allow_inadequate_energy=True,
        now_s=1.0,
    )
    assert overridden.state is TaskState.ASSIGNED

    assigned = ledger.assign(
        "inspect-a",
        "cf01",
        capabilities=capabilities,
        battery_percent=100.0,
        now_s=1.0,
    )
    ledger.start(
        "inspect-a",
        "cf01",
        child_mission_run_id="child-1",
        generation=assigned.lease_generation,
        now_s=1.1,
    )
    ledger.update_progress("inspect-a", "cf01", 1, 40.0, now_s=1.2)
    ledger.pause("inspect-a", "cf01", 1, reason="operator hold", now_s=1.3)
    ledger.resume("inspect-a", "cf01", 1, now_s=1.4)
    reassigned = ledger.reassign(
        "inspect-a",
        "cf02",
        capabilities=capabilities,
        battery_percent=100.0,
        reason="cf01 unavailable",
        now_s=2.0,
    )
    assert reassigned.lease_generation == 2
    assert reassigned.owner_vehicle_id == "cf02"
    with pytest.raises(CrazySwarmError) as stale_owner:
        ledger.update_progress("inspect-a", "cf01", 1, 50.0, now_s=2.1)
    assert stale_owner.value.code is ErrorCode.MODE_NOT_AUTHORIZED

    ledger.start(
        "inspect-a",
        "cf02",
        child_mission_run_id="child-2",
        generation=2,
        now_s=2.1,
    )
    ledger.update_progress("inspect-a", "cf02", 2, 100.0, now_s=2.2)
    completed = ledger.complete("inspect-a", "cf02", 2, now_s=2.3)
    replayed = replay_task(completed.definition, completed.events)
    assert completed.state is TaskState.COMPLETED
    assert replayed.state is TaskState.COMPLETED
    assert replayed.owner_vehicle_id == "cf02"
    assert replayed.progress_percent == 100.0
