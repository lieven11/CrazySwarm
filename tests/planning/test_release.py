from __future__ import annotations

import json
import subprocess
import sys

from crazyswarm_app.planning.release import (
    PlanningReleaseQualification,
    run_planning_release_qualification,
)


def test_release_qualification_covers_every_registered_component() -> None:
    report = run_planning_release_qualification()

    assert report.passed is True
    assert report.registered_route_planners == 4
    assert report.registered_fleet_policies == 4
    assert report.registered_recovery_strategies == 8
    assert len(report.component_results) == 16
    assert all(item.passed for item in report.component_results)
    assert all(item.status == "PASSED" for item in report.canonical_cases)
    assert report.deferred_systems == (
        "LIVE_ISAAC:NOT_RUN",
        "PHYSICAL_CRAZYFLIE:NOT_RUN",
        "DIGITAL_TWIN:NOT_RUN",
    )


def test_release_receipt_is_stable_across_processes_and_round_trip() -> None:
    command = (
        "from crazyswarm_app.planning.release import "
        "run_planning_release_qualification as run; print(run().report_sha256)"
    )
    first = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    second = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    report = run_planning_release_qualification()
    restored = PlanningReleaseQualification.model_validate_json(
        json.dumps(report.model_dump(mode="json"))
    )

    assert first == second == report.report_sha256
    assert restored == report


def test_repeated_qualification_has_no_mutable_registry_state() -> None:
    hashes = {run_planning_release_qualification().report_sha256 for _ in range(100)}

    assert hashes == {run_planning_release_qualification().report_sha256}
