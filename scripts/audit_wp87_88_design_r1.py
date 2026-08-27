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
ARTIFACT = ROOT / "missions/campaigns/real/qualification/wp87-88-r1-design-audit-v2.json"
INITIAL_ARTIFACT = ROOT / "missions/campaigns/real/qualification/wp87-88-design-audit-v1.json"
INITIAL_ARTIFACT_SHA256 = "78cfdd69628cf44a92f5496e23617a59a335972b5274d5f2b84e3e82987971e9"
INITIAL_BEGIN = "<!-- WP87-88-DESIGN-PAYLOAD-BEGIN -->"
INITIAL_END = "<!-- WP87-88-DESIGN-PAYLOAD-END -->"
R1_BEGIN = "<!-- WP87-88-R1-DESIGN-PAYLOAD-BEGIN -->"
R1_END = "<!-- WP87-88-R1-DESIGN-PAYLOAD-END -->"
CONTRACT_BEGIN = "<!-- WP87-88-R1-MACHINE-CONTRACT-BEGIN -->"
CONTRACT_END = "<!-- WP87-88-R1-MACHINE-CONTRACT-END -->"
LEDGER_PREIMAGE_SHA256 = "39a90e2d66b7a520e61e791d1388195e3013f506b190154441576ac2d0e99776"


STAGE_ORDER = {
    "GROUND_CHECKS": 0,
    "FIRST_LIFT": 1,
    "HOVER_AND_ABORT": 2,
    "ONE_AXIS": 3,
    "COMBINED_BASICS": 4,
}

CATALOG_EXPECTED = {
    "ground.arm_disarm_props_off": ("ground-checks", "arm-disarm-props-off", "motion.arm-disarm", "GROUND_CHECKS", 3),
    "ground.official_motor_sequence_props_off": ("ground-checks", "official-motor-sequence-props-off", "motion.official-motor-sequence", "GROUND_CHECKS", 3),
    "ground.collective_30_percent_props_off": ("ground-checks", "collective-30-percent-props-off", "motion.collective-30", "GROUND_CHECKS", 0),
    "ground.collective_40_percent_props_off": ("ground-checks", "collective-40-percent-props-off", "motion.collective-40", "GROUND_CHECKS", 0),
    "takeoff.takeoff_0_30_hold_3_land": ("takeoff-and-landing", "takeoff-030-hold-3-land", "motion.takeoff-030-hold-3-land", "FIRST_LIFT", 3),
    "hover.hover_0_30_10": ("hover", "hover-030-10", "motion.hover-030-10", "HOVER_AND_ABORT", 2),
    "hover.hover_0_30_30": ("hover", "hover-030-30", "motion.hover-030-30", "HOVER_AND_ABORT", 2),
    "vertical.vertical_step_0_30_0_35_0_30": ("vertical-motion", "vertical-030-035-030", "motion.vertical-030-035-030", "ONE_AXIS", 2),
    "translation.x_out_back_0_10": ("translation", "x-out-back-010", "motion.x-out-back-010", "ONE_AXIS", 2),
    "translation.y_out_back_0_10": ("translation", "y-out-back-010", "motion.y-out-back-010", "ONE_AXIS", 2),
    "turn.yaw_plus_minus_30": ("turn", "yaw-plus-minus-30", "motion.yaw-plus-minus-30", "ONE_AXIS", 2),
    "turn.yaw_full_360_slow": ("turn", "yaw-full-360-slow", "motion.yaw-360", "COMBINED_BASICS", 2),
    "shape.square_side_0_10": ("shapes", "square-side-010", "motion.square-side-010", "COMBINED_BASICS", 2),
    "shape.circle_radius_0_10": ("shapes", "circle-radius-010", "motion.circle-radius-010", "COMBINED_BASICS", 2),
    "battery.start_below_admission_reject": ("battery-behavior", "start-below-admission-reject", "motion.no-command", "GROUND_CHECKS", 1),
    "safety.controlled_abort_from_hover": ("safety-drills", "controlled-abort-from-hover", "motion.abort-from-hover", "HOVER_AND_ABORT", 3),
    "safety.containment_boundary_reject": ("safety-drills", "containment-boundary-reject", "motion.no-command", "GROUND_CHECKS", 1),
}

MOTION_SPECS: dict[str, dict[str, Any]] = {
    "motion.no-command": {"frame": "HOME", "kind": "NEGATIVE_NO_COMMAND", "traversal": "NOT_APPLICABLE"},
    "motion.arm-disarm": {"frame": "HOME", "kind": "PROPS_OFF_ARM_DISARM", "airborne": False, "traversal": "NOT_APPLICABLE"},
    "motion.official-motor-sequence": {"frame": "BODY", "kind": "OFFICIAL_PROPS_OFF_MOTOR_DIAGNOSTIC", "airborne": False, "traversal": "NOT_APPLICABLE"},
    "motion.collective-30": {"frame": "BODY", "kind": "DISABLED_PROPS_OFF_COLLECTIVE", "collective_percent": 30, "duration_s": 1.0, "airborne": False},
    "motion.collective-40": {"frame": "BODY", "kind": "DISABLED_PROPS_OFF_COLLECTIVE", "collective_percent": 40, "duration_s": 1.0, "airborne": False},
    "motion.takeoff-030-hold-3-land": {"frame": "HOME", "kind": "TAKEOFF_HOLD_LAND", "height_m": 0.30, "hold_s": 3.0, "landing_xy_m": [0.0, 0.0], "traversal": "CHECKPOINT"},
    "motion.hover-030-10": {"frame": "HOME", "kind": "TAKEOFF_HOLD_LAND", "height_m": 0.30, "hold_s": 10.0, "landing_xy_m": [0.0, 0.0], "traversal": "CHECKPOINT"},
    "motion.hover-030-30": {"frame": "HOME", "kind": "TAKEOFF_HOLD_LAND", "height_m": 0.30, "hold_s": 30.0, "landing_xy_m": [0.0, 0.0], "traversal": "CHECKPOINT"},
    "motion.vertical-030-035-030": {"frame": "HOME", "kind": "VERTICAL_STEP", "z_sequence_m": [0.30, 0.35, 0.30], "hold_each_s": 2.0, "traversal": "CHECKPOINT"},
    "motion.x-out-back-010": {"frame": "HOME", "kind": "SIGNED_TRANSLATION", "points_m": [[0.0, 0.0, 0.30], [0.10, 0.0, 0.30], [0.0, 0.0, 0.30]], "hold_turn_s": 2.0, "traversal": "CHECKPOINT"},
    "motion.y-out-back-010": {"frame": "HOME", "kind": "SIGNED_TRANSLATION", "points_m": [[0.0, 0.0, 0.30], [0.0, 0.10, 0.30], [0.0, 0.0, 0.30]], "hold_turn_s": 2.0, "traversal": "CHECKPOINT"},
    "motion.yaw-plus-minus-30": {"frame": "HOME", "kind": "UNWRAPPED_YAW", "yaw_sequence_deg": [0.0, 30.0, 0.0, -30.0, 0.0], "height_m": 0.30, "traversal": "CHECKPOINT"},
    "motion.yaw-360": {"frame": "HOME", "kind": "UNWRAPPED_YAW", "yaw_delta_deg": 360.0, "direction": "CCW", "height_m": 0.30, "traversal": "CONTINUOUS_FLY_THROUGH"},
    "motion.square-side-010": {"frame": "HOME", "kind": "POLYLINE_LOOP", "vertices_m": [[0.05, -0.05, 0.30], [0.05, 0.05, 0.30], [-0.05, 0.05, 0.30], [-0.05, -0.05, 0.30], [0.05, -0.05, 0.30]], "traversal": "CONTINUOUS_FLY_THROUGH"},
    "motion.circle-radius-010": {"frame": "HOME", "geometry": "ANALYTIC_CIRCLE", "center_m": [0.0, 0.0, 0.30], "radius_m": 0.10, "direction": "CCW", "turns": 1, "traversal": "CONTINUOUS_FLY_THROUGH", "canonical_preview_samples": 32, "sample_invariance": [16, 32, 64]},
    "motion.abort-from-hover": {"frame": "HOME", "kind": "TAKEOFF_HOVER_OPERATOR_ABORT", "height_m": 0.30, "abort_source_time_s": 3.0, "expected_terminal": "PHYSICAL_LANDED_DISARMED"},
}

ACCEPTANCE_SPECS: dict[str, dict[str, Any]] = {
    "acceptance.ground-authority": {"zero_airborne_samples": True, "terminal_armed": False, "command_identity_exact": True},
    "acceptance.disabled-collective": {"executable": False, "required_new_design": True},
    "acceptance.first-lift": {"maximum_z_error_m": 0.05, "maximum_xy_drift_m": 0.08, "maximum_overshoot_m": 0.03, "terminal_contract": "physical-landing-terminal-v1"},
    "acceptance.hover": {"maximum_xy_drift_m": 0.08, "maximum_position_rms_m": 0.05, "maximum_steady_speed_p95_m_s": 0.10, "maximum_abs_roll_pitch_deg": 15.0, "maximum_body_rate_p95_rad_s": 1.0, "motor_saturation_count": 0, "terminal_contract": "physical-landing-terminal-v1"},
    "acceptance.vertical": {"minimum_signed_progress_m": 0.04, "maximum_z_error_m": 0.05, "maximum_overshoot_m": 0.03, "settling_time_s": 2.0, "terminal_contract": "physical-landing-terminal-v1"},
    "acceptance.translation": {"minimum_signed_progress_m": 0.08, "maximum_endpoint_error_m": 0.05, "maximum_cross_axis_drift_m": 0.05, "maximum_overshoot_m": 0.03, "terminal_contract": "physical-landing-terminal-v1"},
    "acceptance.yaw": {"maximum_yaw_endpoint_error_deg": 5.0, "maximum_xy_drift_m": 0.08, "maximum_yaw_rate_rad_s": 0.5235987756, "terminal_contract": "physical-landing-terminal-v1"},
    "acceptance.square": {"maximum_route_tube_error_m": 0.05, "maximum_closure_error_m": 0.05, "undeclared_stop_count": 0, "terminal_contract": "physical-landing-terminal-v1"},
    "acceptance.circle": {"maximum_radial_rms_error_m": 0.05, "maximum_radial_error_m": 0.08, "maximum_closure_error_m": 0.05, "undeclared_stop_count": 0, "terminal_contract": "physical-landing-terminal-v1"},
    "acceptance.negative-zero-dispatch": {"arm_dispatch_count": 0, "takeoff_dispatch_count": 0, "expected_disposition": "REJECTED_BEFORE_ARM"},
    "acceptance.abort": {"superseded_dispatch_count": 0, "maximum_future_cancel_s": 0.10, "terminal_contract": "physical-landing-terminal-v1", "mission_success": False},
}

ACCEPTANCE_BY_KEY = {
    "ground.arm_disarm_props_off": "acceptance.ground-authority",
    "ground.official_motor_sequence_props_off": "acceptance.ground-authority",
    "ground.collective_30_percent_props_off": "acceptance.disabled-collective",
    "ground.collective_40_percent_props_off": "acceptance.disabled-collective",
    "takeoff.takeoff_0_30_hold_3_land": "acceptance.first-lift",
    "hover.hover_0_30_10": "acceptance.hover",
    "hover.hover_0_30_30": "acceptance.hover",
    "vertical.vertical_step_0_30_0_35_0_30": "acceptance.vertical",
    "translation.x_out_back_0_10": "acceptance.translation",
    "translation.y_out_back_0_10": "acceptance.translation",
    "turn.yaw_plus_minus_30": "acceptance.yaw",
    "turn.yaw_full_360_slow": "acceptance.yaw",
    "shape.square_side_0_10": "acceptance.square",
    "shape.circle_radius_0_10": "acceptance.circle",
    "battery.start_below_admission_reject": "acceptance.negative-zero-dispatch",
    "safety.controlled_abort_from_hover": "acceptance.abort",
    "safety.containment_boundary_reject": "acceptance.negative-zero-dispatch",
}

# This map is independently derived from the frozen request, routed requirements,
# claim matrix, and exit gates. The contract registry must be exactly equal to it.
SOURCE_METRIC_MAP = {
    "operator.arming": {
        "identity_exact", "preflight_age_s", "permit_case_exact", "permit_unconsumed",
        "firmware_can_arm", "landed_disarmed_before_arm", "operator_observer_present",
        "position_observation_age_s",
    },
    "operator.battery": {"battery_start_margin_percent", "battery_voltage_margin_v", "battery_terminal_reserve_percent"},
    "operator.limits": {
        "maximum_height_m", "height_protected_margin_m", "maximum_horizontal_speed_m_s",
        "maximum_vertical_speed_m_s", "maximum_yaw_rate_rad_s", "maximum_acceleration_m_s2",
        "maximum_jerk_m_s3", "maximum_airborne_duration_s", "motor_saturation_count",
        "motor_current_margin_a",
    },
    "operator.containment": {
        "nominal_physical_margin_m", "hard_physical_margin_m", "stopping_margin_m",
        "independent_containment_record_present",
    },
    "operator.abort": {"abort_future_cancel_s", "superseded_dispatch_count", "abort_terminal_observed"},
    "operator.landing": {
        "landing_capture_age_s", "terminal_height_m", "terminal_speed_m_s",
        "terminal_armed", "terminal_flying", "observer_settled", "simulated_contact_used",
    },
    "operator.emergency": {
        "emergency_input_to_link_s", "emergency_dispatch_count", "emergency_ack_claimed",
        "watchdog_max_gap_s", "reboot_required", "emergency_lease_independent",
    },
    "requirements.cleanup_priority": {
        "live_permit_count", "live_lease_count", "pending_command_count", "restart_observation_only",
    },
}

METRIC_SPECS: dict[str, tuple[str, str, Any, Any, Any, str]] = {
    "identity_exact": ("arming", "TRUE", True, True, False, "link_spy+binding_record"),
    "preflight_age_s": ("arming", "LE", 5.0, 4.0, 5.001, "source_clock_recompute"),
    "permit_case_exact": ("arming", "TRUE", True, True, False, "canonical_hash_recompute"),
    "permit_unconsumed": ("arming", "TRUE", True, True, False, "permit_store_replay"),
    "firmware_can_arm": ("arming", "TRUE", True, True, False, "raw_supervisor_bitfield"),
    "landed_disarmed_before_arm": ("arming", "TRUE", True, True, False, "raw_supervisor_bitfield+observer_record"),
    "operator_observer_present": ("arming", "TRUE", True, True, False, "signed_session_record"),
    "position_observation_age_s": ("arming", "LE", 0.15, 0.10, 0.151, "source_receive_clock_recompute"),
    "battery_start_margin_percent": ("battery", "GE", 5.0, 5.0, 4.999, "raw_voltage_soc_floor_recompute"),
    "battery_voltage_margin_v": ("battery", "GT", 0.0, 0.10, 0.0, "raw_voltage_floor_recompute"),
    "battery_terminal_reserve_percent": ("battery", "GE", 20.0, 22.0, 19.999, "raw_battery_recompute"),
    "maximum_height_m": ("flight_limits", "LE", 0.35, 0.34, 0.351, "external_reference_or_cage_limited_estimate"),
    "height_protected_margin_m": ("flight_limits", "GT", 0.0, 0.14, 0.0, "geometry_recompute"),
    "maximum_horizontal_speed_m_s": ("flight_limits", "LE", 0.15, 0.14, 0.151, "source_time_position_recompute"),
    "maximum_vertical_speed_m_s": ("flight_limits", "LE", 0.20, 0.18, 0.201, "source_time_height_recompute"),
    "maximum_yaw_rate_rad_s": ("flight_limits", "LE", 0.5235987756, 0.50, 0.524, "unwrapped_attitude_recompute"),
    "maximum_acceleration_m_s2": ("flight_limits", "LE", 0.50, 0.45, 0.501, "source_time_velocity_recompute"),
    "maximum_jerk_m_s3": ("flight_limits", "LE", 2.0, 1.8, 2.001, "source_time_acceleration_recompute"),
    "maximum_airborne_duration_s": ("flight_limits", "LE", 45.0, 44.0, 45.001, "source_clock_recompute"),
    "motor_saturation_count": ("flight_limits", "EQ", 0, 0, 1, "raw_per_motor_evidence"),
    "motor_current_margin_a": ("flight_limits", "GT", 0.0, 0.05, 0.0, "raw_current_calibrated_limit"),
    "nominal_physical_margin_m": ("containment", "GE", 0.27, 0.27, 0.269, "cage_geometry_recompute"),
    "hard_physical_margin_m": ("containment", "GE", 0.03, 0.03, 0.029, "cage_geometry_recompute"),
    "stopping_margin_m": ("containment", "GT", 0.0, 0.0825, -0.001, "jerk_clock_geometry_recompute"),
    "independent_containment_record_present": ("containment", "TRUE", True, True, False, "signed_cage_inspection"),
    "abort_future_cancel_s": ("abort", "LE", 0.10, 0.08, 0.101, "monotonic_link_trace"),
    "superseded_dispatch_count": ("abort", "EQ", 0, 0, 1, "link_spy"),
    "abort_terminal_observed": ("abort", "TRUE", True, True, False, "physical_terminal_record"),
    "landing_capture_age_s": ("landing", "LE", 0.15, 0.10, 0.151, "source_receive_clock_recompute"),
    "terminal_height_m": ("landing", "LE", 0.05, 0.03, 0.051, "raw_downward_range+observer_record"),
    "terminal_speed_m_s": ("landing", "LE", 0.05, 0.03, 0.051, "source_time_position_recompute"),
    "terminal_armed": ("landing", "FALSE", False, False, True, "raw_supervisor_bitfield"),
    "terminal_flying": ("landing", "FALSE", False, False, True, "raw_supervisor_bitfield"),
    "observer_settled": ("landing", "TRUE", True, True, False, "independent_observer_record"),
    "simulated_contact_used": ("landing", "FALSE", False, False, True, "evidence_provenance_check"),
    "emergency_input_to_link_s": ("emergency", "LE", 0.10, 0.08, 0.101, "monotonic_browser_server_link_trace"),
    "emergency_dispatch_count": ("emergency", "EQ", 1, 1, 0, "link_spy"),
    "emergency_ack_claimed": ("emergency", "FALSE", False, False, True, "event_schema_replay"),
    "watchdog_max_gap_s": ("emergency", "LT", 0.50, 0.45, 0.50, "monotonic_link_trace"),
    "reboot_required": ("emergency", "TRUE", True, True, False, "session_state_replay"),
    "emergency_lease_independent": ("emergency", "TRUE", True, True, False, "active_lease_link_spy"),
    "live_permit_count": ("cleanup", "EQ", 0, 0, 1, "permit_store_replay"),
    "live_lease_count": ("cleanup", "EQ", 0, 0, 1, "lease_store_replay"),
    "pending_command_count": ("cleanup", "EQ", 0, 0, 1, "link_dispatch_replay"),
    "restart_observation_only": ("cleanup", "TRUE", True, True, False, "fresh_runtime_route_probe"),
}

PYTHON_ROOTS = {
    "src/crazyswarm_app/cli.py",
    "src/crazyswarm_app/dashboard.py",
    "src/crazyswarm_app/dashboard_service.py",
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/api/runtime.py",
}
UI_ROOTS = {
    "ui/app/page.tsx",
    "ui/app/layout.tsx",
    "ui/worker/index.ts",
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
    "scripts/audit_wp87_88_design_r1.py",
    "scripts/export_openapi.py",
    "scripts/generate_campaign_catalog.py",
    "src/crazyswarm_app/campaign/analyzer.py",
    "src/crazyswarm_app/observability/csv_export.py",
    "src/crazyswarm_app/observability/storage.py",
    "src/crazyswarm_app/qualification/physical.py",
    "tests/api/test_physical_twin.py",
    "tests/campaign/test_campaign_service.py",
    "tests/hardware/test_crazyflie_adapter.py",
    "tests/safety/test_supervisor.py",
    "ui/package.json",
    "ui/vite.config.ts",
    "ui/tests/api-adapter.test.ts",
    "ui/tests/campaign-lab.test.tsx",
    "ui/tests/physical-twin.test.tsx",
}
INTENDED_NEW_PATHS = {
    "docs/reference/PHYSICAL_LANDING_TERMINAL_V1.md",
    "missions/campaigns/real/cases/basic-flight-commissioning/1d-cases-v1.yaml",
    "missions/campaigns/real/curriculum/digital-twin-basic-flight-v1.yaml",
    "src/crazyswarm_app/hardware/flight_authority.py",
    "tests/hardware/test_flight_authority.py",
    "ui/tests/digital-twin-campaign-lab.test.tsx",
}
CLAIM_OWNER_MAP = {
    "served_entry": {"src/crazyswarm_app/api/app.py", "src/crazyswarm_app/api/runtime.py", "ui/app/page.tsx", "ui/app/components/ControlCenter.tsx", "ui/app/components/CampaignLab.tsx"},
    "safety_authority": {"src/crazyswarm_app/safety/supervisor.py", "src/crazyswarm_app/safety/policy.py", "src/crazyswarm_app/safety/audit.py", "src/crazyswarm_app/hardware/models.py"},
    "adapter_link": {"src/crazyswarm_app/vehicles/crazyflie.py", "src/crazyswarm_app/vehicles/crazyflie_link.py", "src/crazyswarm_app/vehicles/_cflib_link.py"},
    "persistence_export_review": {"src/crazyswarm_app/observability/recorder.py", "src/crazyswarm_app/observability/storage.py", "src/crazyswarm_app/observability/csv_export.py", "src/crazyswarm_app/campaign/analyzer.py", "ui/app/components/TelemetryDock.tsx"},
    "serving": {"src/crazyswarm_app/cli.py", "src/crazyswarm_app/dashboard.py", "src/crazyswarm_app/dashboard_service.py", "ui/worker/index.ts", "ui/vite.config.ts"},
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def delimited(data: bytes, begin: str, end: str) -> bytes:
    start = data.index(begin.encode())
    finish = data.index(end.encode(), start) + len(end)
    return data[start:finish]


def load_contract() -> tuple[dict[str, Any], bytes, bytes, bytes]:
    ledger = LEDGER.read_bytes()
    initial = delimited(ledger, INITIAL_BEGIN, INITIAL_END)
    r1 = delimited(ledger, R1_BEGIN, R1_END)
    block = delimited(ledger, CONTRACT_BEGIN, CONTRACT_END).decode()
    json_start = block.index("```json") + len("```json")
    json_end = block.index("```", json_start)
    prefix = ledger[: ledger.index(INITIAL_BEGIN.encode())]
    if not prefix.endswith(b"\n"):
        raise ValueError("initial payload is not preceded by the frozen delimiter newline")
    preimage = prefix[:-1]
    return json.loads(block[json_start:json_end]), initial, r1, preimage


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
    imports: set[str] = set()
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
            if resolved := python_module_path(target):
                imports.add(resolved)
    return imports


def python_closure() -> set[str]:
    closure = set(PYTHON_ROOTS)
    pending = list(PYTHON_ROOTS)
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
    for candidate in (base, base.with_suffix(".ts"), base.with_suffix(".tsx"), base.with_suffix(".css"), base / "index.ts", base / "index.tsx"):
        if (ROOT / candidate).is_file():
            return os.path.normpath(str(candidate))
    return None


def ui_imports(path: str) -> set[str]:
    source = (ROOT / path).read_text(encoding="utf-8")
    specifiers = re.findall(r"(?:from\s+|import\s*\(|import\s+)[\s]*[\"']([^\"']+)[\"']", source)
    return {resolved for specifier in specifiers if (resolved := resolve_ui_import(path, specifier))}


def ui_closure() -> set[str]:
    closure = set(UI_ROOTS)
    pending = list(UI_ROOTS)
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
    outputs = set()
    if "--output ui/openapi.json" in command:
        outputs.add("ui/openapi.json")
    if "-o app/lib/api.generated.ts" in command:
        outputs.add("ui/app/lib/api.generated.ts")
    return outputs


def discovered_boundaries() -> set[str]:
    return python_closure() | ui_closure() | FIXED_BOUNDARIES | generated_outputs()


def compare(value: Any, relation: str, threshold: Any) -> bool:
    if relation == "TRUE":
        return value is True
    if relation == "FALSE":
        return value is False
    if relation == "LE":
        return value <= threshold
    if relation == "LT":
        return value < threshold
    if relation == "GE":
        return value >= threshold
    if relation == "GT":
        return value > threshold
    if relation == "EQ":
        return type(value) is type(threshold) and value == threshold
    raise ValueError(relation)


def exact_integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("supersedes") != ["WP-71", "WP-72", "WP-73", "WP-74", "WP-75"]:
        errors.append("blocked predecessor scope is not explicitly superseded")

    expected_metrics = set().union(*SOURCE_METRIC_MAP.values())
    if expected_metrics != set(METRIC_SPECS):
        errors.append("independent source metric derivation differs from exact metric specifications")
    metric_ids = contract.get("guard_metric_ids", [])
    if len(metric_ids) != len(set(metric_ids)) or set(metric_ids) != expected_metrics:
        errors.append("guard metric registry is missing, duplicate, or extra")
    for metric_id, spec in METRIC_SPECS.items():
        _category, relation, threshold, pass_value, fail_value, _oracle = spec
        if not compare(pass_value, relation, threshold):
            errors.append(f"{metric_id}: passing vector does not pass")
        if compare(fail_value, relation, threshold):
            errors.append(f"{metric_id}: isolated failure does not fail")
    if contract.get("guard_registry_identity") != "wp87-flight-safety-guard-registry-v2":
        errors.append("guard registry identity mismatch")

    catalog = contract.get("catalog_projection", [])
    keys = [row.get("key") for row in catalog]
    if len(keys) != len(set(keys)) or set(keys) != set(CATALOG_EXPECTED):
        errors.append("catalog projection does not contain the exact 17 unique cases")
    motion_ids = set(contract.get("motion_ids", []))
    if motion_ids != set(MOTION_SPECS) or len(contract.get("motion_ids", [])) != len(motion_ids):
        errors.append("motion registry is missing, duplicate, or extra")
    if contract.get("motion_registry_identity") != "wp88-basic-flight-motion-registry-v2":
        errors.append("motion registry identity mismatch")
    row_by_key = {row.get("key"): row for row in catalog}
    for key, expected in CATALOG_EXPECTED.items():
        major_id, variant_id, motion_id, stage, repeats = expected
        row = row_by_key.get(key, {})
        if row.get("cluster_id") != "basic-flight-commissioning":
            errors.append(f"{key}: wrong cluster")
        for field, value in (("major_id", major_id), ("variant_id", variant_id), ("motion_id", motion_id), ("stage", stage), ("stage_order", STAGE_ORDER[stage]), ("repeat_count", repeats)):
            if row.get(field) != value or (field in {"stage_order", "repeat_count"} and type(row.get(field)) is not int):
                errors.append(f"{key}: {field} mismatch")
        if motion_id not in motion_ids:
            errors.append(f"{key}: unknown motion {motion_id}")
        if row.get("acceptance_profile") != ACCEPTANCE_BY_KEY[key]:
            errors.append(f"{key}: acceptance profile mismatch")
        if row.get("promotion_rule") not in {"ALL_REPEATS_PASS_AND_MANUAL_PROMOTION", "DISABLED_UNTIL_NEW_DESIGN", "NEGATIVE_CASE_PASSES_ON_ZERO_DISPATCH"}:
            errors.append(f"{key}: invalid promotion rule")

    graph = {row["key"]: set(row.get("prerequisites", [])) for row in catalog if row.get("key") in CATALOG_EXPECTED}
    if any(not dependencies.issubset(graph) for dependencies in graph.values()):
        errors.append("catalog contains an unknown prerequisite")
    pending = {key: set(value) for key, value in graph.items()}
    removed: set[str] = set()
    while pending:
        ready = {key for key, dependencies in pending.items() if dependencies.issubset(removed)}
        if not ready:
            errors.append("catalog prerequisite graph is cyclic")
            break
        removed |= ready
        pending = {key: value for key, value in pending.items() if key not in ready}

    battery = contract.get("battery_comparison", {})
    if battery.get("case_key") != "hover.hover_0_30_10" or battery.get("qualification_bearing") is not False:
        errors.append("battery comparison must name hover-10 and remain descriptive")
    if battery.get("required_repeats_per_required_band") != 2 or battery.get("required_bands") != ["HIGH", "MID"]:
        errors.append("battery comparison repeat/context semantics mismatch")

    geometry = contract.get("safety_geometry", {})
    if geometry.get("physical_enclosure") != "NETTED_CYLINDER" or geometry.get("independent_source") != "SIGNED_CAGE_INSPECTION_WITH_MEASUREMENT_AND_PHOTO_HASH":
        errors.append("physical containment is not independently frozen")
    horizontal = contract.get("clock_and_stopping_witness", {})
    budget = sum(float(value) for value in horizontal.get("sense_to_effect_budget_s", {}).values())
    if abs(budget - 0.22) > 1e-12 or budget >= float(horizontal.get("admitted_budget_s", 0.0)):
        errors.append("sense-to-effect budget or reserve mismatch")
    speed = float(horizontal.get("speed_m_s", 0.0))
    response = float(horizontal.get("admitted_budget_s", 0.0))
    jerk = float(horizontal.get("jerk_m_s3", 0.0))
    deceleration = float(horizontal.get("deceleration_m_s2", 0.0))
    ramp_time = deceleration / jerk
    velocity_after_ramp = speed - 0.5 * jerk * ramp_time**2
    stopping = speed * response + speed * ramp_time - jerk * ramp_time**3 / 6.0 + velocity_after_ramp**2 / (2.0 * deceleration)
    interval = float(geometry.get("hard_center_radius_m", 0.0)) - float(geometry.get("warning_center_radius_m", 0.0))
    if stopping >= interval or interval - stopping <= 0.0:
        errors.append("jerk-aware stopping witness lacks strict positive margin")
    late = speed * float(horizontal.get("late_source_gap_s", 0.0)) + speed * ramp_time - jerk * ramp_time**3 / 6.0 + velocity_after_ramp**2 / (2.0 * deceleration)
    if late <= interval:
        errors.append("late-source perturbation does not fail")
    expected_reactions = {
        "nominal_warning": "STOP_AND_HOLD_THEN_LAND",
        "certified_land": "CONTROLLED_LAND",
        "stale_active_state": "EMERGENCY_STOP",
        "tampered_prearm_certificate": "REJECT_ZERO_COMMAND",
        "late_active_observation": "EMERGENCY_STOP",
        "insufficient_active_clearance": "EMERGENCY_STOP",
        "missing_prearm_certificate": "REJECT_ZERO_COMMAND",
        "lost_active_certificate": "EMERGENCY_STOP",
    }
    reaction_rows = contract.get("reaction_vectors", [])
    observed_reactions = {row.get("vector_id"): row.get("resulting_command") for row in reaction_rows}
    if observed_reactions != expected_reactions or len(reaction_rows) != len(expected_reactions):
        errors.append("reaction/certificate vector set mismatch")

    vertical = contract.get("vertical_witness", {})
    protected = sum(float(vertical[name]) for name in ("commanded_height_m", "overshoot_m", "uncertainty_m", "vehicle_half_height_m"))
    margin = float(geometry.get("enclosure_height_m", 0.0)) - protected
    if margin <= 0.0 or abs(margin - float(vertical.get("expected_positive_margin_m", -1.0))) > 1e-12:
        errors.append("vertical witness lacks the exact positive physical margin")
    perturbed = float(vertical.get("perturbed_commanded_height_m", 0.0)) + float(vertical.get("overshoot_m", 0.0)) + float(vertical.get("uncertainty_m", 0.0))
    if perturbed <= float(vertical.get("hard_estimated_center_height_m", 0.0)):
        errors.append("vertical command perturbation does not fail the software hard center")

    watchdog = contract.get("watchdog_contract", {})
    if watchdog != {
        "keepalive_period_s": 0.25,
        "scheduler_jitter_budget_s": 0.10,
        "link_stall_budget_s": 0.10,
        "maximum_accepted_gap_s": 0.50,
        "firmware_timeout_s": 1.0,
        "gap_relation": "STRICTLY_LESS_THAN",
        "emergency_input_to_link_deadline_s": 0.10,
        "software_repeat_count": 100,
        "normal_end_state": "REBOOT_REQUIRED_AFTER_COMMAND_SESSION",
        "timeout_end_state": "LOCKED_REBOOT_REQUIRED",
        "no_response_state": "DISPATCHED_UNCONFIRMED_REBOOT_REQUIRED",
    }:
        errors.append("watchdog/emergency lifecycle contract mismatch")

    landing = contract.get("physical_landing_terminal", {})
    required_landing = {"raw_supervisor_disarmed", "raw_supervisor_not_flying", "fresh_downward_range_at_or_below_0_05_m", "independent_observer_settled", "no_simulated_contact_claim"}
    if set(landing.get("required_clauses", [])) != required_landing or landing.get("contract_path") != "docs/reference/PHYSICAL_LANDING_TERMINAL_V1.md":
        errors.append("physical landing terminal contract is incomplete")

    domains = contract.get("typed_integer_domains", [])
    expected_domains = {"stage_order": (0, 4), "repeat_count": (0, 10), "route_sample_count": (8, 128), "emergency_vector_count": (100, 100)}
    if {row.get("name") for row in domains} != set(expected_domains):
        errors.append("typed integer domain set mismatch")
    alias_values = [True, 1.0, 1.5, "1", None]
    for row in domains:
        name = row.get("name")
        if name not in expected_domains:
            continue
        minimum, maximum = expected_domains[name]
        if row.get("minimum") != minimum or row.get("maximum") != maximum:
            errors.append(f"{name}: bounds mismatch")
        if any(exact_integer(value, minimum, maximum) for value in alias_values):
            errors.append(f"{name}: a language-level alias was accepted")
        if exact_integer(minimum - 1, minimum, maximum) or exact_integer(maximum + 1, minimum, maximum):
            errors.append(f"{name}: an endpoint perturbation was accepted")

    perturbations = set(contract.get("semantic_perturbations", []))
    required_perturbations = {"renamed_child", "reordered_catalog", "circle_samples_16", "circle_samples_64", "square_collinear_densification", "axis_sign_flip", "incompatible_child", "yaw_modulo_shortcut"}
    if perturbations != required_perturbations:
        errors.append("semantic perturbation set mismatch")

    return errors


def current_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def build_artifact(contract: dict[str, Any], initial: bytes, r1: bytes, preimage: bytes) -> dict[str, Any]:
    boundaries = discovered_boundaries()
    required = set().union(*CLAIM_OWNER_MAP.values())
    boundary_errors = []
    if not required.issubset(boundaries):
        boundary_errors.append(f"missing claim/serving owners: {sorted(required - boundaries)}")
    if sha256_bytes(preimage) != LEDGER_PREIMAGE_SHA256:
        boundary_errors.append("ledger preimage reconstruction mismatch")
    if sha256(INITIAL_ARTIFACT) != INITIAL_ARTIFACT_SHA256:
        boundary_errors.append("initial audit artifact changed")
    generated = generated_outputs()
    errors = validate_contract(contract) + boundary_errors
    vector_results = {
        metric_id: {
            "pass": compare(spec[3], spec[1], spec[2]),
            "isolated_failure": not compare(spec[4], spec[1], spec[2]),
        }
        for metric_id, spec in METRIC_SPECS.items()
    }
    whole_repeat_pass = {metric_id: spec[3] for metric_id, spec in sorted(METRIC_SPECS.items())}
    whole_repeat_sha256 = sha256_bytes(
        json.dumps(whole_repeat_pass, sort_keys=True, separators=(",", ":")).encode()
    )
    isolated_failure_vectors = {
        metric_id: {
            "base_whole_repeat_sha256": whole_repeat_sha256,
            "only_changed_metric": metric_id,
            "changed_value": spec[4],
            "changed_metric_fails": not compare(spec[4], spec[1], spec[2]),
            "all_other_metrics_remain_passing": True,
        }
        for metric_id, spec in sorted(METRIC_SPECS.items())
    }
    return {
        "schema_version": 2,
        "base_commit": current_commit(),
        "initial_payload_sha256": sha256_bytes(initial),
        "initial_payload_bytes": len(initial),
        "r1_payload_sha256": sha256_bytes(r1),
        "r1_payload_bytes": len(r1),
        "ledger_preimage_sha256": sha256_bytes(preimage),
        "ledger_preimage_reconstruction": "perl -0pe 's/\\n<!-- WP87-88-DESIGN-PAYLOAD-BEGIN -->[\\s\\S]*\\z//' docs/work-packages/ACTIVE.md | shasum -a 256",
        "initial_artifact_sha256": sha256(INITIAL_ARTIFACT),
        "source_metric_map": {key: sorted(value) for key, value in SOURCE_METRIC_MAP.items()},
        "metric_specs": {
            metric_id: {
                "category": spec[0],
                "relation": spec[1],
                "threshold": spec[2],
                "pass_value": spec[3],
                "isolated_fail_value": spec[4],
                "oracle": spec[5],
                "numeric_tolerance": 1e-9,
                "repeat_semantics": "EVERY_REPEAT_MUST_PASS",
                "aggregate_semantics": "NO_AVERAGE_MAY_HIDE_A_FAILED_REPEAT",
            }
            for metric_id, spec in sorted(METRIC_SPECS.items())
        },
        "motion_specs": MOTION_SPECS,
        "acceptance_specs": ACCEPTANCE_SPECS,
        "acceptance_by_key": ACCEPTANCE_BY_KEY,
        "guard_vector_results": vector_results,
        "passing_whole_repeat": whole_repeat_pass,
        "passing_whole_repeat_sha256": whole_repeat_sha256,
        "isolated_failure_vectors": isolated_failure_vectors,
        "contract": contract,
        "claim_owner_map": {key: sorted(value) for key, value in CLAIM_OWNER_MAP.items()},
        "generated_outputs": sorted(generated),
        "boundaries": [
            {"path": path, "classification": "GENERATED" if path in generated else "SCOPED_EXISTING", "preimage_sha256": sha256(ROOT / path)}
            for path in sorted(boundaries)
        ],
        "intended_new_paths": [{"path": path, "preimage": "ABSENT"} for path in sorted(INTENDED_NEW_PATHS)],
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    contract, initial, r1, preimage = load_contract()
    expected = build_artifact(contract, initial, r1, preimage)
    if args.write:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = list(expected["errors"])
    if not ARTIFACT.is_file():
        errors.append(f"missing artifact: {ARTIFACT.relative_to(ROOT)}")
    else:
        observed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        if observed != expected:
            errors.append("artifact differs from current exact payload/preimages")
    for row in expected["intended_new_paths"]:
        if (ROOT / row["path"]).exists():
            errors.append(f"intended new path already exists: {row['path']}")
    print(json.dumps({
        "artifact": str(ARTIFACT.relative_to(ROOT)),
        "artifact_sha256": sha256(ARTIFACT) if ARTIFACT.is_file() else None,
        "initial_payload_sha256": expected["initial_payload_sha256"],
        "r1_payload_sha256": expected["r1_payload_sha256"],
        "boundary_count": len(expected["boundaries"]),
        "metric_count": len(contract.get("guard_metric_ids", [])),
        "catalog_count": len(contract.get("catalog_projection", [])),
        "errors": errors,
    }, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
