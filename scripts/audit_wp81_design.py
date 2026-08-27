from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "missions/campaigns/sim/qualification/wp81-design-audit-v1.json"

IMPLEMENTATION_OWNED = {
    "docs/project/requirements/EVIDENCE_AND_REVIEW.md",
    "docs/reference/LANDING_GOAL_REGION_V1.md",
    "src/crazyswarm_app/domain/commands.py",
    "src/crazyswarm_app/domain/goals.py",
    "src/crazyswarm_app/missions/base.py",
    "src/crazyswarm_app/simulation/vehicle.py",
    "tests/missions/test_trajectory_execution.py",
}

RELIED_UPON = {
    "src/crazyswarm_app/domain/trajectory.py",
    "src/crazyswarm_app/missions/models.py",
    "src/crazyswarm_app/missions/observation.py",
    "src/crazyswarm_app/missions/authority.py",
    "src/crazyswarm_app/missions/runner.py",
    "src/crazyswarm_app/missions/script.py",
    "src/crazyswarm_app/safety/policy.py",
    "src/crazyswarm_app/safety/supervisor.py",
}

TRANSIT_CLASS_SYMBOLS = {
    "GoalCaptureRecord",
    "LandCommand",
    "MissionContext",
    "MissionFleetAuthority",
    "MissionResult",
    "MissionRunner",
    "SafetySupervisor",
    "ScriptMission",
    "SimulatedVehicle",
}

CAPTURE_CONTRACT = {
    "approach_z_m": 0.30,
    "vertical_tolerance_m": 0.05,
    "observation_valid": True,
}

CLAIMS = (
    {
        "claim_id": "region_native_landing_accelerated",
        "execution_boundary": "INTEGRATION",
        "environment": "FAST_SIM",
        "clock_evidence": "ACCELERATED",
    },
    {
        "claim_id": "region_native_landing_realtime",
        "execution_boundary": "INTEGRATION",
        "environment": "FAST_SIM",
        "clock_evidence": "OBSERVED_REALTIME",
    },
)

WITNESSES = (
    {
        "id": "accepted_offset",
        "kind": "NOMINAL_REGION",
        "center": [1.35, 0.0, 0.0],
        "capture": [1.30, 0.0, 0.30],
        "target": [1.30, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.10,
        "expected_command_valid": True,
        "expected_descent_authorized": True,
        "expected_capture_to_target_xy_m": 0.0,
    },
    {
        "id": "inclusive_edge",
        "kind": "NOMINAL_REGION",
        "center": [1.35, 0.0, 0.0],
        "capture": [1.45, 0.0, 0.30],
        "target": [1.45, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.10,
        "expected_command_valid": True,
        "expected_descent_authorized": True,
        "expected_capture_to_target_xy_m": 0.0,
    },
    {
        "id": "outside_edge",
        "kind": "NOMINAL_REGION",
        "center": [1.35, 0.0, 0.0],
        "capture": [1.450001, 0.0, 0.30],
        "target": [1.450001, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.10,
        "expected_command_valid": False,
        "expected_descent_authorized": False,
        "expected_capture_to_target_xy_m": 0.0,
    },
    {
        "id": "overspeed",
        "kind": "NOMINAL_REGION",
        "center": [1.35, 0.0, 0.0],
        "capture": [1.30, 0.0, 0.30],
        "target": [1.30, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.100001,
        "expected_command_valid": True,
        "expected_descent_authorized": False,
        "expected_capture_to_target_xy_m": 0.0,
    },
    {
        "id": "wrong_landing_height",
        "kind": "NOMINAL_REGION",
        "center": [1.35, 0.0, 0.0],
        "capture": [1.30, 0.0, 0.30],
        "target": [1.30, 0.0, 0.000001],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.0,
        "expected_command_valid": False,
        "expected_descent_authorized": True,
        "expected_capture_to_target_xy_m": 0.0,
    },
    {
        "id": "declared_diversion_point",
        "kind": "DIVERSION_POINT",
        "center": [1.35, 0.0, 0.0],
        "capture": [0.25, 0.0, 0.30],
        "target": [0.25, 0.0, 0.0],
        "diversion": [0.25, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.0,
        "expected_command_valid": True,
        "expected_descent_authorized": True,
        "expected_capture_to_target_xy_m": 0.0,
    },
    {
        "id": "off_diversion_point",
        "kind": "DIVERSION_POINT",
        "center": [1.35, 0.0, 0.0],
        "capture": [0.25, 0.0, 0.30],
        "target": [0.249999, 0.0, 0.0],
        "diversion": [0.25, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.0,
        "expected_command_valid": False,
        "expected_descent_authorized": True,
        "expected_capture_to_target_xy_m": 0.000001,
    },
    {
        "id": "vertical_outside",
        "kind": "NOMINAL_REGION",
        "center": [1.35, 0.0, 0.0],
        "capture": [1.30, 0.0, 0.350001],
        "target": [1.30, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.0,
        "expected_command_valid": True,
        "expected_descent_authorized": False,
        "expected_capture_to_target_xy_m": 0.0,
    },
    {
        "id": "invalid_observation",
        "kind": "NOMINAL_REGION",
        "center": [1.35, 0.0, 0.0],
        "capture": [1.30, 0.0, 0.30],
        "target": [1.30, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.0,
        "observation_valid": False,
        "expected_command_valid": True,
        "expected_descent_authorized": False,
        "expected_capture_to_target_xy_m": 0.0,
    },
    {
        "id": "divert_goal_nominal_region_capture",
        "kind": "DIVERT_GOAL_NOMINAL_REGION",
        "center": [1.35, 0.0, 0.0],
        "capture": [1.30, 0.0, 0.30],
        "target": [1.30, 0.0, 0.0],
        "diversion": [0.25, 0.0, 0.0],
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.0,
        "expected_command_valid": True,
        "expected_descent_authorized": True,
        "expected_capture_to_target_xy_m": 0.0,
    },
)

TELEMETRY_WITNESSES = (
    {
        "id": "stationary_region_handoff",
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "capture_z_m": 0.30,
        "samples": [
            [0.00, 1.300, 0.000, 0.300],
            [0.02, 1.301, 0.000, 0.299],
            [0.04, 1.299, 0.001, 0.296],
            [0.06, 1.300, 0.000, 0.294],
        ],
        "expected_pass": True,
    },
    {
        "id": "hidden_center_seek",
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "capture_z_m": 0.30,
        "samples": [
            [0.00, 1.300, 0.000, 0.300],
            [0.10, 1.325, 0.000, 0.300],
            [0.20, 1.350, 0.000, 0.299],
            [0.22, 1.350, 0.000, 0.294],
        ],
        "expected_pass": False,
    },
)

TELEMETRY_ORACLE = {
    "descent_start_drop_m": 0.005,
    "maximum_pre_descent_horizontal_displacement_m": 0.010,
    "maximum_pre_descent_progress_toward_center_m": 0.010,
    "signal": "retained estimated position_m",
}

SCHEMA_FIXTURES = (
    {"schema_version": 1, "v3_fields_present": False, "expected_v3_values": None},
    {"schema_version": 2, "v3_fields_present": False, "expected_v3_values": None},
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(item: dict[str, object]) -> dict[str, object]:
    center = [float(value) for value in item["center"]]
    capture = [float(value) for value in item["capture"]]
    target = [float(value) for value in item["target"]]
    tolerance = float(item["horizontal_tolerance_m"])
    speed = float(item["observed_speed_m_s"])
    maximum_speed = float(item["maximum_capture_speed_m_s"])
    horizontal_error = math.hypot(capture[0] - center[0], capture[1] - center[1])
    vertical_error = abs(
        capture[2] - float(item.get("approach_z_m", CAPTURE_CONTRACT["approach_z_m"]))
    )
    vertical_tolerance = float(
        item.get("vertical_tolerance_m", CAPTURE_CONTRACT["vertical_tolerance_m"])
    )
    observation_valid = bool(
        item.get("observation_valid", CAPTURE_CONTRACT["observation_valid"])
    )
    capture_to_target = math.hypot(capture[0] - target[0], capture[1] - target[1])
    descent_authorized = (
        observation_valid
        and horizontal_error <= tolerance + 1e-12
        and vertical_error <= vertical_tolerance + 1e-12
        and speed <= maximum_speed
    )
    if item["kind"] in {"NOMINAL_REGION", "DIVERT_GOAL_NOMINAL_REGION"}:
        command_valid = (
            math.hypot(target[0] - center[0], target[1] - center[1])
            <= tolerance + 1e-12
            and math.isclose(target[2], center[2], abs_tol=1e-9)
        )
    else:
        diversion = [float(value) for value in item["diversion"]]
        command_valid = all(
            math.isclose(actual, expected, abs_tol=1e-9)
            for actual, expected in zip(target, diversion, strict=True)
        )
        descent_authorized = observation_valid and speed <= maximum_speed
    return {
        "id": item["id"],
        "command_valid": command_valid,
        "descent_authorized": descent_authorized,
        "capture_to_target_xy_m": capture_to_target,
    }


def evaluate_telemetry(item: dict[str, object]) -> dict[str, object]:
    capture_x, capture_y = [float(value) for value in item["capture_xy_m"]]
    center_x, center_y = [float(value) for value in item["goal_center_xy_m"]]
    capture_z = float(item["capture_z_m"])
    drop = float(TELEMETRY_ORACLE["descent_start_drop_m"])
    window = [
        [float(value) for value in sample]
        for sample in item["samples"]
        if float(sample[3]) >= capture_z - drop
    ]
    displacement = max(
        math.hypot(sample[1] - capture_x, sample[2] - capture_y) for sample in window
    )
    initial_center_error = math.hypot(capture_x - center_x, capture_y - center_y)
    minimum_center_error = min(
        math.hypot(sample[1] - center_x, sample[2] - center_y) for sample in window
    )
    progress = max(0.0, initial_center_error - minimum_center_error)
    passed = (
        displacement
        <= float(TELEMETRY_ORACLE["maximum_pre_descent_horizontal_displacement_m"])
        and progress
        <= float(TELEMETRY_ORACLE["maximum_pre_descent_progress_toward_center_m"])
    )
    return {
        "id": item["id"],
        "sample_count": len(window),
        "maximum_pre_descent_horizontal_displacement_m": displacement,
        "maximum_pre_descent_progress_toward_center_m": progress,
        "passed": passed,
    }


def discover_transit_class_owners() -> dict[str, str]:
    owners: dict[str, list[str]] = {name: [] for name in TRANSIT_CLASS_SYMBOLS}
    for path in (ROOT / "src/crazyswarm_app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in owners:
                owners[node.name].append(str(path.relative_to(ROOT)))
    ambiguous = {name: paths for name, paths in owners.items() if len(paths) != 1}
    if ambiguous:
        raise ValueError(f"transit class ownership is not unique: {ambiguous}")
    return {name: paths[0] for name, paths in owners.items()}


def build_artifact() -> dict[str, object]:
    transit_owners = discover_transit_class_owners()
    paths = sorted(IMPLEMENTATION_OWNED | RELIED_UPON | set(transit_owners.values()))
    boundaries = []
    for relative in paths:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(relative)
        boundaries.append(
            {
                "path": relative,
                "classification": (
                    "IMPLEMENTATION_OWNED"
                    if relative in IMPLEMENTATION_OWNED
                    else "RELIED_UPON_UNCHANGED"
                ),
                "preimage_sha256": sha256(path),
            }
        )
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "schema_version": 1,
        "packet_id": "WP-81",
        "base_commit": base_commit,
        "originating_request": "ok implement",
        "predecessor": "WP-76 through WP-79 BLOCKED_WITH_FINDINGS",
        "scope": "region-native terminal capture and landing handoff only",
        "claims": CLAIMS,
        "witnesses": WITNESSES,
        "witness_results": [evaluate(item) for item in WITNESSES],
        "capture_contract": CAPTURE_CONTRACT,
        "telemetry_oracle": TELEMETRY_ORACLE,
        "telemetry_witnesses": TELEMETRY_WITNESSES,
        "telemetry_witness_results": [
            evaluate_telemetry(item) for item in TELEMETRY_WITNESSES
        ],
        "schema_fixtures": SCHEMA_FIXTURES,
        "transit_class_owners": transit_owners,
        "boundaries": boundaries,
        "requirements": [
            "REQ-EVI-005",
            "REQ-MOT-010",
            "REQ-MOT-011",
            "REQ-WFL-014",
            "REQ-WFL-017",
            "REQ-WFL-018",
            "REQ-WFL-020",
            "REQ-WFL-023",
            "REQ-WFL-029",
            "REQ-WFL-034",
            "REQ-WFL-036",
            "REQ-WFL-039",
            "REQ-WFL-042",
            "REQ-WFL-046",
            "REQ-WFL-047",
        ],
        "non_goals": [
            "public Campaign API or served UI qualification",
            "catalog/recovery/replanning reorganization",
            "new capture-freshness policy",
            "controller-gain tuning",
            "diversion behavior redesign",
        ],
    }


def validate(data: dict[str, object], artifact: Path) -> list[str]:
    errors: list[str] = []
    expected_claim_ids = {item["claim_id"] for item in CLAIMS}
    claims = data.get("claims", [])
    claim_ids = [item.get("claim_id") for item in claims]
    if set(claim_ids) != expected_claim_ids or len(claim_ids) != len(expected_claim_ids):
        errors.append("claim set mismatch")
    for item in claims:
        if item.get("execution_boundary") != "INTEGRATION":
            errors.append(f"claim boundary mismatch: {item.get('claim_id')}")
        if item.get("environment") != "FAST_SIM":
            errors.append(f"claim environment mismatch: {item.get('claim_id')}")
        if item.get("clock_evidence") not in {"ACCELERATED", "OBSERVED_REALTIME"}:
            errors.append(f"claim clock mismatch: {item.get('claim_id')}")

    expected_witness_ids = {item["id"] for item in WITNESSES}
    witnesses = data.get("witnesses", [])
    witness_ids = [item.get("id") for item in witnesses]
    results = {item.get("id"): item for item in data.get("witness_results", [])}
    if set(witness_ids) != expected_witness_ids or len(witness_ids) != len(
        expected_witness_ids
    ):
        errors.append("witness set mismatch")
    if set(results) != expected_witness_ids:
        errors.append("witness result set mismatch")
    for item in witnesses:
        observed = evaluate(item)
        retained = results.get(item.get("id"))
        if retained != observed:
            errors.append(f"witness result mismatch: {item.get('id')}")
            continue
        if observed["command_valid"] != item.get("expected_command_valid"):
            errors.append(f"command expectation mismatch: {item.get('id')}")
        if observed["descent_authorized"] != item.get("expected_descent_authorized"):
            errors.append(f"authority expectation mismatch: {item.get('id')}")
        if not math.isclose(
            float(observed["capture_to_target_xy_m"]),
            float(item["expected_capture_to_target_xy_m"]),
            abs_tol=1e-12,
        ):
            errors.append(f"handoff expectation mismatch: {item.get('id')}")

    if data.get("capture_contract") != CAPTURE_CONTRACT:
        errors.append("capture contract mismatch")
    if data.get("telemetry_oracle") != TELEMETRY_ORACLE:
        errors.append("telemetry oracle mismatch")
    expected_telemetry_ids = {item["id"] for item in TELEMETRY_WITNESSES}
    telemetry_witnesses = data.get("telemetry_witnesses", [])
    telemetry_ids = [item.get("id") for item in telemetry_witnesses]
    telemetry_results = {
        item.get("id"): item for item in data.get("telemetry_witness_results", [])
    }
    if set(telemetry_ids) != expected_telemetry_ids or len(telemetry_ids) != len(
        expected_telemetry_ids
    ):
        errors.append("telemetry witness set mismatch")
    if set(telemetry_results) != expected_telemetry_ids:
        errors.append("telemetry witness result set mismatch")
    for item in telemetry_witnesses:
        observed = evaluate_telemetry(item)
        if telemetry_results.get(item.get("id")) != observed:
            errors.append(f"telemetry witness mismatch: {item.get('id')}")
        if observed["passed"] != item.get("expected_pass"):
            errors.append(f"telemetry expectation mismatch: {item.get('id')}")
    if data.get("schema_fixtures") != list(SCHEMA_FIXTURES):
        errors.append("schema fixture mismatch")

    transit_owners = discover_transit_class_owners()
    if data.get("transit_class_owners") != transit_owners:
        errors.append("transit class ownership changed")

    boundaries = data.get("boundaries", [])
    paths = [item.get("path") for item in boundaries]
    expected_paths = IMPLEMENTATION_OWNED | RELIED_UPON | set(transit_owners.values())
    if set(paths) != expected_paths or len(paths) != len(expected_paths):
        errors.append("boundary set mismatch")
    for item in boundaries:
        relative = str(item.get("path"))
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing boundary: {relative}")
        elif sha256(path) != item.get("preimage_sha256"):
            errors.append(f"preimage mismatch: {relative}")
        expected_classification = (
            "IMPLEMENTATION_OWNED"
            if relative in IMPLEMENTATION_OWNED
            else "RELIED_UPON_UNCHANGED"
        )
        if item.get("classification") != expected_classification:
            errors.append(f"classification mismatch: {relative}")
    if not artifact.is_file():
        errors.append("artifact is missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", nargs="?", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    artifact = args.artifact if args.artifact.is_absolute() else ROOT / args.artifact
    if args.write:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(build_artifact(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    data = json.loads(artifact.read_text(encoding="utf-8"))
    errors = validate(data, artifact)
    result = {
        "artifact": str(artifact.relative_to(ROOT)),
        "artifact_sha256": sha256(artifact),
        "boundary_count": len(data.get("boundaries", [])),
        "claim_count": len(data.get("claims", [])),
        "witness_count": len(data.get("witnesses", [])),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
