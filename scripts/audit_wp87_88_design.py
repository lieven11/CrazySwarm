from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/work-packages/ACTIVE.md"
ARTIFACT = (
    ROOT
    / "missions/campaigns/real/qualification/wp87-88-design-audit-v1.json"
)
PAYLOAD_BEGIN = "<!-- WP87-88-DESIGN-PAYLOAD-BEGIN -->"
PAYLOAD_END = "<!-- WP87-88-DESIGN-PAYLOAD-END -->"
CONTRACT_BEGIN = "<!-- WP87-88-MACHINE-CONTRACT-BEGIN -->"
CONTRACT_END = "<!-- WP87-88-MACHINE-CONTRACT-END -->"

EXPECTED_PACKET_IDS = {"WP-87", "WP-88"}
EXPECTED_GUARD_CATEGORIES = {
    "arming",
    "battery",
    "flight_limits",
    "containment",
    "abort",
    "landing",
    "emergency",
}
EXPECTED_MISSION_KEYS = {
    "ground.arm_disarm_props_off",
    "ground.official_motor_sequence_props_off",
    "ground.collective_30_percent_props_off",
    "ground.collective_40_percent_props_off",
    "takeoff.takeoff_0_30_hold_3_land",
    "hover.hover_0_30_10",
    "hover.hover_0_30_30",
    "vertical.vertical_step_0_30_0_40_0_30",
    "translation.x_out_back_0_10",
    "translation.y_out_back_0_10",
    "turn.yaw_plus_minus_30",
    "turn.yaw_full_360_slow",
    "shape.square_side_0_10",
    "shape.circle_radius_0_10",
    "battery.start_below_admission_reject",
    "safety.controlled_abort_from_hover",
    "safety.containment_boundary_reject",
}
EXPECTED_CLAIMS = {
    "non_bypassable_flight_safety",
    "digital_twin_cluster_hierarchy",
    "basic_flight_progression",
    "battery_band_comparison",
    "props_off_motor_diagnostics",
    "served_safety_controls",
}
ALLOWED_DISPOSITIONS = {"EXECUTABLE_AFTER_GATE", "PLANNED_NOT_EXECUTABLE"}

# These categories are independently derived from the operator request and routed
# requirements rather than copied from the packet's guard registry.
SOURCE_CATEGORY_MAP = {
    "operator_explicit": {
        "arming",
        "battery",
        "flight_limits",
        "containment",
        "abort",
        "landing",
        "emergency",
    },
    "REQ-XFR-008": {"arming", "flight_limits", "containment", "abort", "landing", "emergency"},
    "REQ-MOT-005": {"flight_limits", "containment"},
    "REQ-MIS-002": {"battery"},
    "MISSION_SAFETY_GUIDE": {"arming", "battery", "flight_limits", "abort", "landing", "emergency"},
    "SAFETY_KERNEL": {"arming", "battery", "flight_limits", "containment", "abort", "landing", "emergency"},
}

PYTHON_SEEDS = {
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/api/runtime.py",
    "src/crazyswarm_app/campaign/api_models.py",
    "src/crazyswarm_app/campaign/catalog.py",
    "src/crazyswarm_app/campaign/service.py",
    "src/crazyswarm_app/hardware/observation_twin.py",
    "src/crazyswarm_app/observability/recorder.py",
    "src/crazyswarm_app/qualification/physical.py",
    "src/crazyswarm_app/safety/supervisor.py",
    "src/crazyswarm_app/vehicles/crazyflie.py",
}
UI_SEEDS = {
    "ui/app/components/CampaignLab.tsx",
    "ui/app/components/ControlCenter.tsx",
    "ui/app/components/TelemetryDock.tsx",
    "ui/app/lib/api.ts",
    "ui/app/lib/models.ts",
}
FIXED_BOUNDARIES = {
    "design.md",
    "docs/guides/MISSION_SAFETY_GUIDE.md",
    "docs/project/DESIGN.md",
    "docs/project/requirements/EVIDENCE_AND_REVIEW.md",
    "docs/project/requirements/FIDELITY_AND_TRANSFER.md",
    "docs/project/requirements/MISSION_AND_CURRICULUM.md",
    "docs/project/requirements/MOTION_AND_CONTROL.md",
    "docs/project/requirements/PLANNING_AND_GEOMETRY.md",
    "docs/project/requirements/workflow/COST_SCOPE_AND_HANDOFF.md",
    "docs/project/requirements/workflow/PREFREEZE_AND_ORACLES.md",
    "docs/project/requirements/workflow/WORK_PACKET_GATES.md",
    "docs/reference/LANDING_GOAL_REGION_V1.md",
    "docs/system/PLANNING_AND_RECOVERY_PLUGINS.md",
    "docs/system/README.md",
    "missions/campaigns/real/authorized_cases/basic-flight-and-route-following/real-mirrors-v1.yaml",
    "scripts/audit_wp87_88_design.py",
    "scripts/export_openapi.py",
    "tests/api/test_physical_twin.py",
    "tests/campaign/test_campaign_service.py",
    "tests/hardware/test_crazyflie_adapter.py",
    "tests/safety/test_supervisor.py",
    "ui/package.json",
    "ui/tests/api-adapter.test.ts",
    "ui/tests/campaign-lab.test.tsx",
    "ui/tests/physical-twin.test.tsx",
}
INTENDED_NEW_PATHS = {
    "missions/campaigns/real/cases/basic-flight-commissioning/1d-cases-v1.yaml",
    "missions/campaigns/real/curriculum/digital-twin-basic-flight-v1.yaml",
    "src/crazyswarm_app/hardware/flight_authority.py",
    "tests/hardware/test_flight_authority.py",
    "ui/tests/digital-twin-campaign-lab.test.tsx",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def delimited(text: str, begin: str, end: str) -> str:
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    return text[start:finish]


def load_contract() -> tuple[dict[str, Any], bytes]:
    ledger = LEDGER.read_text(encoding="utf-8")
    payload = delimited(ledger, PAYLOAD_BEGIN, PAYLOAD_END).encode()
    contract_block = delimited(ledger, CONTRACT_BEGIN, CONTRACT_END)
    json_start = contract_block.index("```json") + len("```json")
    json_end = contract_block.index("```", json_start)
    return json.loads(contract_block[json_start:json_end]), payload


def module_name(path: str) -> str:
    relative = Path(path).relative_to("src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def python_module_path(module: str) -> str | None:
    if not module.startswith("crazyswarm_app"):
        return None
    relative = Path("src") / Path(*module.split("."))
    for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
        if (ROOT / candidate).is_file():
            return str(candidate)
    return None


def python_imports(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    current = module_name(path)
    package = current if path.endswith("/__init__.py") else current.rsplit(".", 1)[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                prefix = ".".join(parts[: len(parts) - node.level + 1])
                target = ".".join(part for part in (prefix, node.module or "") if part)
            else:
                target = node.module or ""
            targets.append(target)
            targets.extend(f"{target}.{alias.name}" for alias in node.names)
        for target in targets:
            resolved = python_module_path(target)
            if resolved:
                found.add(resolved)
    return found


def recursive_python_closure() -> set[str]:
    closure = set(PYTHON_SEEDS)
    pending = list(PYTHON_SEEDS)
    while pending:
        path = pending.pop()
        for imported in python_imports(path):
            if imported not in closure:
                closure.add(imported)
                pending.append(imported)
    return closure


def resolve_ui_import(source: str, specifier: str) -> str | None:
    if specifier.startswith("@/"):
        base = Path("ui/app") / specifier[2:]
    elif specifier.startswith("."):
        base = Path(source).parent / specifier
    else:
        return None
    candidates = (
        base,
        base.with_suffix(".ts"),
        base.with_suffix(".tsx"),
        base.with_suffix(".css"),
        base / "index.ts",
        base / "index.tsx",
    )
    for candidate in candidates:
        if (ROOT / candidate).is_file():
            return os.path.normpath(str(candidate))
    return None


def ui_imports(path: str) -> set[str]:
    source = (ROOT / path).read_text(encoding="utf-8")
    specifiers = re.findall(r"(?:from\s+|import\s*\(|import\s+)[\s]*[\"']([^\"']+)[\"']", source)
    return {
        resolved
        for specifier in specifiers
        if (resolved := resolve_ui_import(path, specifier)) is not None
    }


def recursive_ui_closure() -> set[str]:
    closure = set(UI_SEEDS)
    pending = list(UI_SEEDS)
    while pending:
        path = pending.pop()
        for imported in ui_imports(path):
            if imported not in closure:
                closure.add(imported)
                pending.append(imported)
    return closure


def generated_outputs() -> set[str]:
    package = json.loads((ROOT / "ui/package.json").read_text(encoding="utf-8"))
    command = package["scripts"]["generate:api"]
    outputs: set[str] = set()
    if "--output ui/openapi.json" in command:
        outputs.add("ui/openapi.json")
    if "-o app/lib/api.generated.ts" in command:
        outputs.add("ui/app/lib/api.generated.ts")
    return outputs


def discovered_boundaries() -> set[str]:
    return recursive_python_closure() | recursive_ui_closure() | FIXED_BOUNDARIES | generated_outputs()


def current_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    packets = contract.get("packets", [])
    packet_ids = [row.get("packet_id") for row in packets]
    if set(packet_ids) != EXPECTED_PACKET_IDS or len(packet_ids) != len(set(packet_ids)):
        errors.append(f"packet set mismatch: {packet_ids!r}")

    derived_categories = set().union(*SOURCE_CATEGORY_MAP.values())
    registry = contract.get("guard_registry", [])
    categories = [row.get("category") for row in registry]
    if derived_categories != EXPECTED_GUARD_CATEGORIES:
        errors.append(f"internal source-category derivation mismatch: {sorted(derived_categories)}")
    if set(categories) != derived_categories or len(categories) != len(set(categories)):
        errors.append(f"guard category mismatch: {categories!r}")
    for row in registry:
        if not row.get("metric") or not row.get("pass_relation") or not row.get("isolated_failure"):
            errors.append(f"incomplete guard row: {row.get('category')}")

    missions = contract.get("mission_inventory", [])
    mission_keys = [row.get("key") for row in missions]
    if set(mission_keys) != EXPECTED_MISSION_KEYS or len(mission_keys) != len(set(mission_keys)):
        errors.append(f"mission inventory mismatch: {sorted(str(key) for key in mission_keys)}")
    known = set(mission_keys)
    stages: dict[str, int] = {}
    for row in missions:
        key = str(row.get("key"))
        disposition = row.get("disposition")
        if disposition not in ALLOWED_DISPOSITIONS:
            errors.append(f"{key}: invalid disposition {disposition!r}")
        stage = row.get("stage")
        if type(stage) is not int or stage < 0:  # exact integer; booleans are rejected
            errors.append(f"{key}: stage must be an exact non-negative integer")
            continue
        stages[key] = stage
        for dependency in row.get("prerequisites", []):
            if dependency not in known:
                errors.append(f"{key}: unknown prerequisite {dependency}")
        if not row.get("causal_question") or not row.get("oracle"):
            errors.append(f"{key}: missing causal question or oracle")
    for row in missions:
        key = str(row.get("key"))
        for dependency in row.get("prerequisites", []):
            if key in stages and dependency in stages and stages[dependency] >= stages[key]:
                errors.append(f"{key}: prerequisite {dependency} is not from an earlier stage")

    motor_rows = {row["key"]: row for row in missions if row.get("major") == "Ground checks"}
    for key in ("ground.collective_30_percent_props_off", "ground.collective_40_percent_props_off"):
        row = motor_rows.get(key, {})
        if row.get("disposition") != "PLANNED_NOT_EXECUTABLE":
            errors.append(f"{key}: arbitrary collective must remain disabled at design freeze")
        gates = set(row.get("enablement_gates", []))
        required = {"props_removed", "restrained", "calibrated_mapping", "current_thermal_bound"}
        if not required.issubset(gates):
            errors.append(f"{key}: missing enablement gates {sorted(required - gates)}")

    claims = contract.get("claims", [])
    claim_ids = [row.get("claim_id") for row in claims]
    if set(claim_ids) != EXPECTED_CLAIMS or len(claim_ids) != len(set(claim_ids)):
        errors.append(f"claim set mismatch: {claim_ids!r}")
    for row in claims:
        if row.get("boundary") != "PRODUCTION_ENTRY":
            errors.append(f"{row.get('claim_id')}: claim is not production-entry")
        for field in ("trigger", "effect", "observation", "oracle", "counterexample"):
            if not row.get(field):
                errors.append(f"{row.get('claim_id')}: missing {field}")

    battery = contract.get("battery_policy", {})
    if battery.get("physical_override_allowed") is not False:
        errors.append("physical battery override must be forbidden")
    if battery.get("case_identity_rule") != "same_case_grouped_by_observed_start_band":
        errors.append("battery bands must not clone mission identity")

    sensor_scope = contract.get("sensor_scope", {})
    if sensor_scope.get("perception_missions") is not False or sensor_scope.get("automatic_calibration") is not False:
        errors.append("Cluster 1 must exclude perception missions and automatic calibration")

    witness = contract.get("numerical_witness", {})
    horizontal = witness.get("horizontal", {})
    nominal_protected = sum(
        float(horizontal[name])
        for name in ("route_center_radius_m", "vehicle_swept_radius_m", "position_uncertainty_m")
    )
    stopping = (
        float(horizontal["maximum_speed_m_s"]) * float(horizontal["response_budget_s"])
        + float(horizontal["maximum_speed_m_s"]) ** 2
        / (2.0 * float(horizontal["minimum_deceleration_m_s2"]))
    )
    intervention_room = float(horizontal["hard_center_radius_m"]) - float(horizontal["warning_center_radius_m"])
    if abs(nominal_protected - float(horizontal["expected_nominal_protected_radius_m"])) > 1e-12:
        errors.append("horizontal nominal protected-radius witness mismatch")
    if stopping > intervention_room:
        errors.append("horizontal stopping witness is infeasible")
    late_stopping = (
        float(horizontal["maximum_speed_m_s"]) * float(horizontal["late_response_budget_s"])
        + float(horizontal["maximum_speed_m_s"]) ** 2
        / (2.0 * float(horizontal["minimum_deceleration_m_s2"]))
    )
    if late_stopping <= intervention_room:
        errors.append("late-response perturbation is not sensitive")
    if nominal_protected > float(horizontal["physical_containment_radius_m"]):
        errors.append("nominal protected occupancy exceeds physical containment")

    vertical = witness.get("vertical", {})
    vertical_total = sum(
        float(vertical[name]) for name in ("maximum_commanded_height_m", "overshoot_budget_m", "height_uncertainty_m")
    )
    if vertical_total > float(vertical["hard_height_m"]):
        errors.append("vertical witness is infeasible")
    perturbed_vertical = float(vertical["perturbed_commanded_height_m"]) + float(vertical["overshoot_budget_m"]) + float(vertical["height_uncertainty_m"])
    if perturbed_vertical <= float(vertical["hard_height_m"]):
        errors.append("vertical perturbation is not sensitive")

    battery_witness = witness.get("battery", {})
    floor = max(
        float(battery_witness["configured_takeoff_minimum_percent"]),
        float(battery_witness["mission_need_percent"]) + float(battery_witness["reserve_percent"]),
        float(battery_witness["validated_voltage_floor_as_percent"]),
    )
    if float(battery_witness["passing_start_percent"]) < floor:
        errors.append("battery passing witness is below the derived floor")
    if float(battery_witness["failing_start_percent"]) >= floor:
        errors.append("battery failure perturbation is not sensitive")

    return errors


def build_artifact(contract: dict[str, Any], payload: bytes) -> dict[str, Any]:
    boundaries = discovered_boundaries()
    generated = generated_outputs()
    return {
        "schema_version": 1,
        "packet_ids": sorted(EXPECTED_PACKET_IDS),
        "base_commit": current_commit(),
        "payload_sha256": sha256_bytes(payload),
        "payload_bytes": len(payload),
        "source_category_map": {key: sorted(value) for key, value in SOURCE_CATEGORY_MAP.items()},
        "contract": contract,
        "generated_outputs": sorted(generated),
        "boundaries": [
            {
                "path": path,
                "classification": "GENERATED" if path in generated else "SCOPED_EXISTING",
                "preimage_sha256": sha256(ROOT / path),
            }
            for path in sorted(boundaries)
        ],
        "intended_new_paths": [
            {"path": path, "preimage": "ABSENT"} for path in sorted(INTENDED_NEW_PATHS)
        ],
        "production_trace": [
            "served Digital twin cluster selection",
            "authenticated API request and exact plan/permit identity",
            "campaign or mission execution owner",
            "SafetySupervisor and physical flight-authority gate",
            "Crazyflie adapter and pinned Crazyradio link",
            "source-qualified telemetry and supervisor state",
            "recorder/export/evaluator",
            "Campaign Review and safety audit",
        ],
        "errors": validate_contract(contract),
    }


def validate_artifact(expected: dict[str, Any], observed: dict[str, Any]) -> list[str]:
    errors = list(expected.get("errors", []))
    if observed != expected:
        errors.append("artifact differs from the exact current payload/preimages; rerun with --write")
    for row in expected["intended_new_paths"]:
        if (ROOT / row["path"]).exists():
            errors.append(f"intended new path already exists: {row['path']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    contract, payload = load_contract()
    expected = build_artifact(contract, payload)
    if args.write:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not ARTIFACT.is_file():
        print(json.dumps({"errors": [f"missing artifact: {ARTIFACT.relative_to(ROOT)}"]}, indent=2))
        return 1
    observed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    errors = validate_artifact(expected, observed)
    print(
        json.dumps(
            {
                "artifact": str(ARTIFACT.relative_to(ROOT)),
                "artifact_sha256": sha256(ARTIFACT),
                "payload_sha256": expected["payload_sha256"],
                "payload_bytes": expected["payload_bytes"],
                "boundary_count": len(expected["boundaries"]),
                "mission_count": len(contract.get("mission_inventory", [])),
                "guard_count": len(contract.get("guard_registry", [])),
                "claim_count": len(contract.get("claims", [])),
                "errors": errors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
