from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from crazyswarm_app.hardware.ownership import (
    HARDWARE_ENABLED_ENV,
    HardwareRuntimeBusy,
    HardwareRuntimeLease,
    PhysicalOperationAdmissionBusy,
    claim_hardware_deployment,
    claim_hardware_runtime,
    claim_physical_operation_admission,
    hardware_runtime_owned,
    read_hardware_runtime_owner,
    require_hardware_runtime,
)


def test_runtime_lease_is_exclusive_and_reports_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "hardware.lock"
    first = HardwareRuntimeLease("operator-dashboard", path=lock_path, checkout=tmp_path)
    acquired = first.acquire()

    assert acquired.owner == "operator-dashboard"
    assert read_hardware_runtime_owner(lock_path) == acquired
    with pytest.raises(HardwareRuntimeBusy, match="operator-dashboard"):
        HardwareRuntimeLease("background-task", path=lock_path).acquire()

    first.release()
    with HardwareRuntimeLease("background-task", path=lock_path):
        owner = read_hardware_runtime_owner(lock_path)
        assert owner is not None
        assert owner.owner == "background-task"


def test_claim_enables_access_only_for_lease_lifetime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HARDWARE_ENABLED_ENV, raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        require_hardware_runtime()

    with claim_hardware_runtime("operator", path=tmp_path / "hardware.lock"):
        assert hardware_runtime_owned() is True
        require_hardware_runtime()

    assert hardware_runtime_owned() is False
    assert HARDWARE_ENABLED_ENV not in os.environ


def test_owner_file_contains_no_runtime_secret(tmp_path: Path) -> None:
    path = tmp_path / "hardware.lock"
    with HardwareRuntimeLease("operator", path=path):
        payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"acquired_at_utc", "checkout", "hostname", "owner", "pid"}


def test_deployment_gate_excludes_physical_operation_admission(tmp_path: Path) -> None:
    with (
        claim_hardware_deployment(tmp_path),
        pytest.raises(PhysicalOperationAdmissionBusy, match="deployment is in progress"),
        claim_physical_operation_admission(tmp_path),
    ):
        pass


def test_physical_operation_admission_excludes_deployment(tmp_path: Path) -> None:
    with (
        claim_physical_operation_admission(tmp_path),
        pytest.raises(PhysicalOperationAdmissionBusy, match="physical action"),
        claim_hardware_deployment(tmp_path),
    ):
        pass


def test_parallel_physical_operation_admissions_share_the_gate(tmp_path: Path) -> None:
    with claim_physical_operation_admission(tmp_path), claim_physical_operation_admission(
        tmp_path
    ):
        pass
