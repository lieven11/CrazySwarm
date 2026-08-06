#!/usr/bin/env python3
"""Run release scenarios twice in isolated processes and compare stable outcomes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crazyswarm_app.domain.simulation import canonical_sha256  # noqa: E402
from crazyswarm_app.missions.registry import default_registry  # noqa: E402
from crazyswarm_app.missions.runner import MissionRunner  # noqa: E402
from crazyswarm_app.safety.supervisor import SafetySupervisor  # noqa: E402
from crazyswarm_app.simulation.factory import vehicles_from_scenario  # noqa: E402
from crazyswarm_app.simulation.world import load_scenario  # noqa: E402

MANIFEST_PATH = ROOT / "config/qualification/canonical-scenarios-v1.json"


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def scenario_spec(scenario_id: str) -> dict[str, Any]:
    for item in load_manifest()["scenarios"]:
        if item["id"] == scenario_id:
            return item
    raise ValueError(f"unknown canonical scenario: {scenario_id}")


async def run_worker(spec: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / spec["config"]
    scenario = load_scenario(path)
    vehicles = sorted(vehicles_from_scenario(scenario), key=lambda item: item.identity.vehicle_id)
    selected = vehicles if spec["all_vehicles"] else vehicles[:1]
    supervisor = SafetySupervisor()
    for vehicle in vehicles:
        supervisor.register_vehicle(vehicle)
    runner = MissionRunner(supervisor, default_registry())
    results = await asyncio.gather(
        *(
            runner.run(
                spec["mission_id"],
                vehicle.identity.vehicle_id,
                parameters=spec["parameters"],
                mission_run_id=f"canonical-{spec['id']}-{vehicle.identity.vehicle_id}",
            )
            for vehicle in selected
        )
    )
    outcomes: list[dict[str, Any]] = []
    for vehicle, result in zip(selected, results, strict=True):
        snapshot = await vehicle.snapshot()
        truth = snapshot.telemetry.ground_truth_position_m
        outcomes.append(
            {
                "vehicle_id": vehicle.identity.vehicle_id,
                "status": result.status.value,
                "reason_code": result.reason_code,
                "configuration_hash": result.configuration_hash,
                "physics_model_id": result.physics_model_id,
                "physics_model_version": result.physics_model_version,
                "physics_configuration_sha256": result.physics_configuration_sha256,
                "scenario_configuration_sha256": result.scenario_configuration_sha256,
                "final_state": snapshot.telemetry.state.value,
                "final_ground_truth_m": (
                    None
                    if truth is None
                    else {axis: round(getattr(truth, axis), 9) for axis in ("x", "y", "z")}
                ),
            }
        )
    record = {
        "scenario_id": spec["id"],
        "scenario_configuration_sha256": canonical_sha256(scenario),
        "outcomes": outcomes,
    }
    record["outcome_sha256"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return record


def run_isolated(scenario_id: str) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", scenario_id],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def verify_release() -> None:
    manifest = load_manifest()
    repetitions = int(manifest["process_repetitions"])
    if repetitions < 2:
        raise ValueError("canonical scenarios require at least two clean-process repetitions")
    for spec in manifest["scenarios"]:
        records = [run_isolated(spec["id"]) for _ in range(repetitions)]
        if any(record != records[0] for record in records[1:]):
            raise AssertionError(f"non-deterministic canonical outcome: {spec['id']}")
        record = records[0]
        if record["scenario_configuration_sha256"] != spec["expected_scenario_sha256"]:
            raise AssertionError(f"scenario hash changed: {spec['id']}")
        if record["outcome_sha256"] != spec["expected_outcome_sha256"]:
            raise AssertionError(f"canonical outcome changed: {spec['id']}")
        for outcome in record["outcomes"]:
            if outcome["status"] != spec["expected_status"]:
                raise AssertionError(f"unexpected status for {spec['id']}: {outcome['status']}")
            if outcome["reason_code"] != spec["expected_reason_code"]:
                raise AssertionError(
                    f"unexpected reason for {spec['id']}: {outcome['reason_code']}"
                )
        print(
            f"PASS {spec['id']}: scenario={record['scenario_configuration_sha256']} "
            f"outcome={record['outcome_sha256']} repetitions={repetitions}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", metavar="SCENARIO_ID")
    arguments = parser.parse_args()
    if arguments.worker:
        print(json.dumps(asyncio.run(run_worker(scenario_spec(arguments.worker))), sort_keys=True))
        return
    verify_release()


if __name__ == "__main__":
    main()
