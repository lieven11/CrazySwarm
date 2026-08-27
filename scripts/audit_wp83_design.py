from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "missions/campaigns/sim/qualification/wp83-design-audit-v1.json"


def _load_wp82() -> ModuleType:
    path = ROOT / "scripts/audit_wp82_design.py"
    spec = importlib.util.spec_from_file_location("wp83_inherited_wp82", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen WP-82 audit")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WP82 = _load_wp82()
ORIGINAL_EVALUATE = WP82.evaluate_telemetry

TELEMETRY_ORACLE = dict(WP82.TELEMETRY_ORACLE)
TELEMETRY_ORACLE["required_capture_endpoint_relation"] = (
    "first selected timestamp and sequence equal accepted capture"
)

MISSING_CAPTURE_ENDPOINT = {
    "id": "capture_coverage_only_failure",
    "capture_source_s": 5.0,
    "contact_source_s": 7.0,
    "capture_xy_m": [1.30, 0.0],
    "goal_center_xy_m": [1.35, 0.0],
    "capture_source_sequence": 100,
    "samples": [
        [5.1, 1.300, 0.000, 0.300],
        [5.7, 1.300, 0.000, 0.220],
        [6.3, 1.300, 0.000, 0.120],
        [7.0, 1.300, 0.000, 0.000],
    ],
    "sample_source_sequences": [101, 102, 103, 104],
    "contact_source_sequence": 104,
    "expected_pass": False,
}

STATIONARY_CAPTURE_THROUGH_CONTACT = dict(WP82.TELEMETRY_WITNESSES[0])
STATIONARY_CAPTURE_THROUGH_CONTACT["sample_source_sequences"] = [
    99,
    100,
    101,
    102,
    103,
    104,
    105,
]
STATIONARY_CAPTURE_THROUGH_CONTACT["contact_source_sequence"] = 104

TELEMETRY_WITNESSES = (
    STATIONARY_CAPTURE_THROUGH_CONTACT,
    *WP82.TELEMETRY_WITNESSES[1:],
    MISSING_CAPTURE_ENDPOINT,
)
ISOLATED_FAILURES = dict(WP82.ISOLATED_FAILURES)
ISOLATED_FAILURES["capture_coverage_only_failure"] = "covers_capture"
TELEMETRY_GUARDS = (*WP82.TELEMETRY_GUARDS, "covers_capture")


def evaluate_telemetry(item: dict[str, object]) -> dict[str, object]:
    materialized = WP82.materialize_telemetry_witness(item)
    result = ORIGINAL_EVALUATE(materialized)
    capture_s = float(materialized["capture_source_s"])
    contact_s = float(materialized["contact_source_s"])
    window_indices = [
        index
        for index, sample in enumerate(materialized["samples"])
        if capture_s <= float(sample[0]) <= contact_s
    ]
    covers_capture = bool(window_indices)
    if covers_capture:
        first = window_indices[0]
        covers_capture = math.isclose(
            float(materialized["samples"][first][0]), capture_s, abs_tol=1e-9
        ) and int(materialized["sample_source_sequences"][first]) == int(
            materialized["capture_source_sequence"]
        )
    guards = dict(result["guards"])
    guards["covers_capture"] = covers_capture
    result["covers_capture"] = covers_capture
    result["guards"] = guards
    result["passed"] = all(guards.values())
    return result


WP82.TELEMETRY_ORACLE = TELEMETRY_ORACLE
WP82.TELEMETRY_WITNESSES = TELEMETRY_WITNESSES
WP82.ISOLATED_FAILURES = ISOLATED_FAILURES
WP82.TELEMETRY_GUARDS = TELEMETRY_GUARDS
WP82.evaluate_telemetry = evaluate_telemetry
WP82.DESIGN_SUPPORT = set(WP82.DESIGN_SUPPORT) | {"scripts/audit_wp82_design.py"}


def build_artifact() -> dict[str, object]:
    data = WP82.build_artifact()
    data["packet_id"] = "WP-83"
    data["originating_request"] = "ok continue with the p1"
    data["predecessor"] = "WP-82 BLOCKED_WITH_FINDINGS"
    return data


def validate(data: dict[str, object], artifact: Path) -> list[str]:
    errors = WP82.validate(data, artifact)
    if data.get("packet_id") != "WP-83":
        errors.append("packet identity mismatch")
    if data.get("originating_request") != "ok continue with the p1":
        errors.append("originating request mismatch")
    if data.get("predecessor") != "WP-82 BLOCKED_WITH_FINDINGS":
        errors.append("predecessor mismatch")
    capture_failure = evaluate_telemetry(MISSING_CAPTURE_ENDPOINT)
    failed_guards = {
        name for name, passed in capture_failure["guards"].items() if not passed
    }
    if failed_guards != {"covers_capture"}:
        errors.append(
            f"capture endpoint isolation mismatch: {sorted(failed_guards)}"
        )
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
        "artifact_sha256": WP82.sha256(artifact),
        "runtime_boundary_count": len(data.get("boundaries", [])),
        "runtime_transit_file_count_by_clock": {
            name: len(transit)
            for name, transit in data.get("runtime_transit_calls_by_clock", {}).items()
        },
        "telemetry_witness_count": len(data.get("telemetry_witnesses", [])),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
