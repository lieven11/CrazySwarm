from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from types import FrameType, ModuleType


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "missions/campaigns/sim/qualification/wp82-design-audit-v1.json"


def _load_wp81() -> ModuleType:
    path = ROOT / "scripts/audit_wp81_design.py"
    spec = importlib.util.spec_from_file_location("wp82_inherited_wp81", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen WP-81 audit")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WP81 = _load_wp81()

IMPLEMENTATION_OWNED = set(WP81.IMPLEMENTATION_OWNED)
IMPLEMENTATION_OWNED.add("docs/project/REQUIREMENTS_CHANGELOG.md")
DESIGN_SUPPORT = {
    "scripts/audit_wp81_design.py",
    "scripts/check_requirement_catalog.py",
}

TELEMETRY_ORACLE = {
    "window_start": "accepted_goal_capture_attempt.source_timestamp_s",
    "window_end": "goal_capture_record.contact_source_timestamp_s",
    "inclusive_end": True,
    "signal": "retained estimated position_m",
    "minimum_sample_count": 4,
    "maximum_horizontal_displacement_from_capture_m": 0.015,
    "maximum_progress_toward_exact_center_m": 0.010,
    "maximum_terminal_z_m": 0.010,
    "required_source_clock_relation": "capture == every sample == contact",
    "required_source_epoch_relation": "capture == every sample == contact",
    "required_sequence_relation": "strictly increasing capture-through-contact",
    "required_timestamp_relation": "nondecreasing capture-through-contact",
}

TELEMETRY_WITNESSES = (
    {
        "id": "stationary_capture_through_contact",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [4.9, 1.340, 0.000, 0.300],
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.301, 0.000, 0.220],
            [6.0, 1.299, 0.001, 0.120],
            [6.5, 1.301, 0.000, 0.040],
            [7.0, 1.300, 0.000, 0.000],
            [7.1, 1.350, 0.000, 0.000],
        ],
        "expected_pass": True,
    },
    {
        "id": "center_seek_before_descent",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.2, 1.325, 0.000, 0.300],
            [5.4, 1.350, 0.000, 0.299],
            [6.0, 1.350, 0.000, 0.150],
            [7.0, 1.350, 0.000, 0.000],
        ],
        "expected_pass": False,
    },
    {
        "id": "center_seek_during_descent",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.4, 1.300, 0.000, 0.250],
            [5.8, 1.325, 0.000, 0.180],
            [6.2, 1.350, 0.000, 0.100],
            [7.0, 1.350, 0.000, 0.000],
        ],
        "expected_pass": False,
    },
    {
        "id": "sample_count_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [6.0, 1.300, 0.000, 0.120],
            [7.0, 1.300, 0.000, 0.000],
        ],
        "expected_pass": False,
    },
    {
        "id": "contact_coverage_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.300, 0.000, 0.220],
            [6.0, 1.300, 0.000, 0.120],
            [6.9, 1.300, 0.000, 0.000],
        ],
        "contact_source_sequence": 104,
        "expected_pass": False,
    },
    {
        "id": "displacement_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.280, 0.000, 0.220],
            [6.0, 1.300, 0.000, 0.120],
            [7.0, 1.300, 0.000, 0.000],
        ],
        "expected_pass": False,
    },
    {
        "id": "center_progress_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.312, 0.000, 0.220],
            [6.0, 1.300, 0.000, 0.120],
            [7.0, 1.300, 0.000, 0.000],
        ],
        "expected_pass": False,
    },
    {
        "id": "terminal_z_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.300, 0.000, 0.220],
            [6.0, 1.300, 0.000, 0.120],
            [7.0, 1.300, 0.000, 0.011],
        ],
        "expected_pass": False,
    },
    {
        "id": "all_numeric_equalities",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.310, 0.000, 0.220],
            [6.0, 1.300, 0.015, 0.120],
            [7.0, 1.300, 0.000, 0.010],
        ],
        "expected_pass": True,
    },
    {
        "id": "wrong_clock_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.300, 0.000, 0.220],
            [6.0, 1.300, 0.000, 0.120],
            [7.0, 1.300, 0.000, 0.000],
        ],
        "sample_source_clock_ids": ["fast-sim-sim01", "wrong-clock", "fast-sim-sim01", "fast-sim-sim01"],
        "expected_pass": False,
    },
    {
        "id": "epoch_reset_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.300, 0.000, 0.220],
            [6.0, 1.300, 0.000, 0.120],
            [7.0, 1.300, 0.000, 0.000],
        ],
        "sample_source_clock_epochs": [0, 0, 1, 0],
        "expected_pass": False,
    },
    {
        "id": "sequence_reorder_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [5.5, 1.300, 0.000, 0.220],
            [6.0, 1.300, 0.000, 0.120],
            [7.0, 1.300, 0.000, 0.000],
        ],
        "sample_source_sequences": [100, 102, 101, 103],
        "expected_pass": False,
    },
    {
        "id": "timestamp_reorder_only_failure",
        "capture_source_s": 5.0,
        "contact_source_s": 7.0,
        "capture_xy_m": [1.30, 0.0],
        "goal_center_xy_m": [1.35, 0.0],
        "samples": [
            [5.0, 1.300, 0.000, 0.300],
            [6.0, 1.300, 0.000, 0.220],
            [5.5, 1.300, 0.000, 0.120],
            [7.0, 1.300, 0.000, 0.000],
        ],
        "expected_pass": False,
    },
)

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

TELEMETRY_GUARDS = (
    "sample_count_pass",
    "covers_contact",
    "clock_consistent",
    "epoch_consistent",
    "sequence_ordered",
    "timestamp_ordered",
    "displacement_pass",
    "center_progress_pass",
    "terminal_z_pass",
)

ISOLATED_FAILURES = {
    "sample_count_only_failure": "sample_count_pass",
    "contact_coverage_only_failure": "covers_contact",
    "wrong_clock_only_failure": "clock_consistent",
    "epoch_reset_only_failure": "epoch_consistent",
    "sequence_reorder_only_failure": "sequence_ordered",
    "timestamp_reorder_only_failure": "timestamp_ordered",
    "displacement_only_failure": "displacement_pass",
    "center_progress_only_failure": "center_progress_pass",
    "terminal_z_only_failure": "terminal_z_pass",
}

HISTORICAL_V3_RECORD_FIELDS = (
    "authorized_capture_position_m",
    "descent_target_position_m",
    "commanded_pre_descent_horizontal_adjustment_m",
    "alignment_duration_s",
    "contact_source_clock_id",
    "contact_source_clock_epoch",
    "contact_source_sequence",
)
HISTORICAL_V3_ATTEMPT_FIELDS = (
    "source_timestamp_s",
    "source_clock_id",
    "source_clock_epoch",
    "source_sequence",
)


def historical_payload(schema_version: int) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "goal": {
            "schema_version": 1,
            "goal_id": f"historical-v{schema_version}",
            "role_id": "lead",
            "vehicle_id": "sim01",
            "frame": "world",
            "landing_target_m": {"x": 1.35, "y": 0.0, "z": 0.0},
            "approach_point_m": {"x": 1.35, "y": 0.0, "z": 0.3},
            "horizontal_tolerance_m": 0.06,
            "vertical_tolerance_m": 0.05,
            "maximum_capture_speed_m_s": 0.2,
            "maximum_correction_attempts": 2,
            "correction_duration_s": 1.0,
            "failure_action": "ABORT_AND_LAND",
            "diversion_target_m": None,
        },
        "attempts": [
            {
                "attempt": 1,
                "estimated_position_m": {"x": 1.3, "y": 0.0, "z": 0.3},
                "truth_position_m": {"x": 1.3, "y": 0.0, "z": 0.3},
                "speed_m_s": 0.0,
                "horizontal_error_m": 0.05,
                "vertical_error_m": 0.0,
                "horizontal_capture_margin_m": 0.01,
                "vertical_capture_margin_m": 0.05,
                "speed_capture_margin_m_s": 0.2,
                "aligned": True,
            }
        ],
        "attempt_count": 1,
        "descent_authorized": True,
        "outcome": "CAPTURED",
        "terminal_estimated_position_m": {"x": 1.3, "y": 0.0, "z": 0.0},
        "terminal_truth_position_m": {"x": 1.3, "y": 0.0, "z": 0.0},
        "terminal_speed_m_s": 0.0,
        "target_center_horizontal_error_m": 0.05,
        "alignment_completed_source_timestamp_s": 6.0,
        "pre_contact_vertical_speed_m_s": 0.1,
        "contact_source_timestamp_s": 7.0,
        "disarmed_source_timestamp_s": 7.1,
        "post_contact_settling_s": 0.1,
        "motors_cut_after_contact": True,
        "correction_count": 0,
        "terminal_state": "LANDED",
        "terminal_contact": "SIMULATED_GROUND_CONTACT",
    }


HISTORICAL_SCHEMA_PAYLOADS = (
    historical_payload(1),
    historical_payload(2),
)


def parse_historical_payload(payload: dict[str, object]) -> dict[str, object]:
    from crazyswarm_app.domain.goals import GoalCaptureRecord

    record = GoalCaptureRecord.model_validate(payload)
    attempt = record.attempts[0]
    return {
        "schema_version": record.schema_version,
        "record_v3_values": {
            field: getattr(record, field, None) for field in HISTORICAL_V3_RECORD_FIELDS
        },
        "attempt_v3_values": {
            field: getattr(attempt, field, None) for field in HISTORICAL_V3_ATTEMPT_FIELDS
        },
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_telemetry_witness(item: dict[str, object]) -> dict[str, object]:
    value = dict(item)
    samples = list(value["samples"])
    sample_count = len(samples)
    clock_id = str(value.get("capture_source_clock_id", "fast-sim-sim01"))
    epoch = int(value.get("capture_source_clock_epoch", 0))
    capture_sequence = int(value.get("capture_source_sequence", 100))
    value["capture_source_clock_id"] = clock_id
    value["capture_source_clock_epoch"] = epoch
    value["capture_source_sequence"] = capture_sequence
    value["contact_source_clock_id"] = str(value.get("contact_source_clock_id", clock_id))
    value["contact_source_clock_epoch"] = int(
        value.get("contact_source_clock_epoch", epoch)
    )
    value["sample_source_clock_ids"] = list(
        value.get("sample_source_clock_ids", [clock_id] * sample_count)
    )
    value["sample_source_clock_epochs"] = list(
        value.get("sample_source_clock_epochs", [epoch] * sample_count)
    )
    value["sample_source_sequences"] = list(
        value.get(
            "sample_source_sequences",
            list(range(capture_sequence, capture_sequence + sample_count)),
        )
    )
    contact_source_s = float(value["contact_source_s"])
    contact_indices = [
        index
        for index, sample in enumerate(samples)
        if math.isclose(float(sample[0]), contact_source_s, abs_tol=1e-9)
    ]
    default_contact_index = contact_indices[-1] if contact_indices else sample_count - 1
    value["contact_source_sequence"] = int(
        value.get(
            "contact_source_sequence",
            value["sample_source_sequences"][default_contact_index],
        )
    )
    return value


def evaluate_telemetry(item: dict[str, object]) -> dict[str, object]:
    item = materialize_telemetry_witness(item)
    capture_s = float(item["capture_source_s"])
    contact_s = float(item["contact_source_s"])
    capture_x, capture_y = [float(value) for value in item["capture_xy_m"]]
    center_x, center_y = [float(value) for value in item["goal_center_xy_m"]]
    window_indices = [
        index
        for index, sample in enumerate(item["samples"])
        if capture_s <= float(sample[0]) <= contact_s
    ]
    window = [
        [float(value) for value in item["samples"][index]]
        for index in window_indices
    ]
    sample_count = len(window)
    displacement = (
        max(math.hypot(sample[1] - capture_x, sample[2] - capture_y) for sample in window)
        if window
        else math.inf
    )
    initial_center_error = math.hypot(capture_x - center_x, capture_y - center_y)
    minimum_center_error = (
        min(math.hypot(sample[1] - center_x, sample[2] - center_y) for sample in window)
        if window
        else 0.0
    )
    center_progress = max(0.0, initial_center_error - minimum_center_error)
    terminal_z = window[-1][3] if window else math.inf
    clock_ids = [
        str(item["sample_source_clock_ids"][index]) for index in window_indices
    ]
    epochs = [
        int(item["sample_source_clock_epochs"][index]) for index in window_indices
    ]
    sequences = [
        int(item["sample_source_sequences"][index]) for index in window_indices
    ]
    timestamps = [float(sample[0]) for sample in window]
    clock_consistent = (
        item["capture_source_clock_id"] == item["contact_source_clock_id"]
        and all(value == item["capture_source_clock_id"] for value in clock_ids)
    )
    epoch_consistent = (
        item["capture_source_clock_epoch"] == item["contact_source_clock_epoch"]
        and all(value == item["capture_source_clock_epoch"] for value in epochs)
    )
    sequence_ordered = all(
        current > previous for previous, current in zip(sequences, sequences[1:])
    )
    timestamp_ordered = all(
        current >= previous for previous, current in zip(timestamps, timestamps[1:])
    )
    covers_contact = (
        bool(window)
        and math.isclose(window[-1][0], contact_s, abs_tol=1e-9)
        and sequences[-1] == int(item["contact_source_sequence"])
    )
    guards = {
        "sample_count_pass": sample_count
        >= int(TELEMETRY_ORACLE["minimum_sample_count"]),
        "covers_contact": covers_contact,
        "clock_consistent": clock_consistent,
        "epoch_consistent": epoch_consistent,
        "sequence_ordered": sequence_ordered,
        "timestamp_ordered": timestamp_ordered,
        "displacement_pass": displacement
        <= float(TELEMETRY_ORACLE["maximum_horizontal_displacement_from_capture_m"])
        + 1e-12,
        "center_progress_pass": center_progress
        <= float(TELEMETRY_ORACLE["maximum_progress_toward_exact_center_m"])
        + 1e-12,
        "terminal_z_pass": terminal_z
        <= float(TELEMETRY_ORACLE["maximum_terminal_z_m"]) + 1e-12,
    }
    passed = all(guards.values())
    return {
        "id": item["id"],
        "sample_count": sample_count,
        "covers_contact": covers_contact,
        "clock_consistent": clock_consistent,
        "epoch_consistent": epoch_consistent,
        "sequence_ordered": sequence_ordered,
        "timestamp_ordered": timestamp_ordered,
        "maximum_horizontal_displacement_from_capture_m": displacement,
        "maximum_progress_toward_exact_center_m": center_progress,
        "terminal_z_m": terminal_z,
        "guards": guards,
        "passed": passed,
    }


def _load_route_module() -> ModuleType:
    path = ROOT / "tests/missions/test_trajectory_execution.py"
    spec = importlib.util.spec_from_file_location("wp82_runtime_trace_route", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the MissionRunner integration fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def trace_runtime_transit(clock_mode_name: str) -> dict[str, list[str]]:
    module = _load_route_module()
    calls: dict[str, set[str]] = defaultdict(set)
    source_prefix = f"{(ROOT / 'src/crazyswarm_app').resolve()}/"

    def profiler(frame: FrameType, event: str, arg: object) -> None:
        del arg
        if event != "call":
            return
        filename = frame.f_code.co_filename
        if not filename.startswith(source_prefix):
            return
        relative = filename[len(source_prefix) :]
        calls[f"src/crazyswarm_app/{relative}"].add(frame.f_code.co_qualname)

    sys.setprofile(profiler)
    try:
        result, _, _, _ = asyncio.run(
            module._run_route(getattr(module.ClockMode, clock_mode_name))
        )
    finally:
        sys.setprofile(None)
    if result.status.value != "SUCCEEDED":
        raise RuntimeError(
            f"profiled MissionRunner integration did not succeed: {result.reason_code}"
        )
    return {path: sorted(names) for path, names in sorted(calls.items())}


def build_artifact() -> dict[str, object]:
    runtime_transit_by_clock = {
        "ACCELERATED": trace_runtime_transit("ACCELERATED"),
        "OBSERVED_REALTIME": trace_runtime_transit("REALTIME"),
    }
    runtime_paths = {
        path
        for transit in runtime_transit_by_clock.values()
        for path in transit
    }
    boundary_paths = runtime_paths | IMPLEMENTATION_OWNED | DESIGN_SUPPORT
    boundaries = []
    for relative in sorted(boundary_paths):
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
    return {
        "schema_version": 1,
        "packet_id": "WP-82",
        "originating_request": "ok continue with the p1",
        "predecessor": "WP-81 BLOCKED_WITH_FINDINGS",
        "claims": CLAIMS,
        "runtime_transit_source": "executed tests/missions/test_trajectory_execution.py::_run_route under sys.setprofile in ACCELERATED and REALTIME modes",
        "runtime_transit_calls_by_clock": runtime_transit_by_clock,
        "inherited_capture_witnesses": WP81.WITNESSES,
        "inherited_capture_witness_results": [
            WP81.evaluate(item) for item in WP81.WITNESSES
        ],
        "historical_schema_payloads": HISTORICAL_SCHEMA_PAYLOADS,
        "historical_schema_parse_results": [
            parse_historical_payload(payload) for payload in HISTORICAL_SCHEMA_PAYLOADS
        ],
        "telemetry_oracle": TELEMETRY_ORACLE,
        "telemetry_witnesses": TELEMETRY_WITNESSES,
        "telemetry_witness_results": [
            evaluate_telemetry(item) for item in TELEMETRY_WITNESSES
        ],
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
            "REQ-WFL-003",
        ],
    }


def validate(data: dict[str, object], artifact: Path) -> list[str]:
    errors: list[str] = []
    runtime_transit_by_clock = {
        "ACCELERATED": trace_runtime_transit("ACCELERATED"),
        "OBSERVED_REALTIME": trace_runtime_transit("REALTIME"),
    }
    if data.get("runtime_transit_calls_by_clock") != runtime_transit_by_clock:
        errors.append("executed runtime transit changed")
    required_qualnames = {
        "src/crazyswarm_app/domain/trajectory.py": "LandExecutionOperation",
        "src/crazyswarm_app/missions/authority.py": "MissionFleetAuthority.execute",
        "src/crazyswarm_app/missions/base.py": "MissionContext.capture_and_land",
        "src/crazyswarm_app/missions/runner.py": "MissionRunner.run",
        "src/crazyswarm_app/missions/script.py": "ScriptMission.execute",
        "src/crazyswarm_app/safety/supervisor.py": "SafetySupervisor.land",
        "src/crazyswarm_app/simulation/vehicle.py": "SimulatedVehicle._land",
    }
    for clock_name, runtime_transit in runtime_transit_by_clock.items():
        for path, fragment in required_qualnames.items():
            if path not in runtime_transit or not any(
                fragment in name for name in runtime_transit[path]
            ):
                errors.append(
                    f"runtime transit missing {clock_name}:{path}:{fragment}"
                )

    expected_claim_ids = {item["claim_id"] for item in CLAIMS}
    claims = data.get("claims", [])
    claim_ids = [item.get("claim_id") for item in claims]
    if set(claim_ids) != expected_claim_ids or len(claim_ids) != len(expected_claim_ids):
        errors.append("claim set mismatch")

    inherited = data.get("inherited_capture_witnesses", [])
    inherited_results = data.get("inherited_capture_witness_results", [])
    if inherited != list(WP81.WITNESSES):
        errors.append("inherited capture witness set mismatch")
    if inherited_results != [WP81.evaluate(item) for item in WP81.WITNESSES]:
        errors.append("inherited capture witness result mismatch")
    if data.get("historical_schema_payloads") != list(HISTORICAL_SCHEMA_PAYLOADS):
        errors.append("historical schema payload mismatch")
    historical_parse_results = [
        parse_historical_payload(payload) for payload in HISTORICAL_SCHEMA_PAYLOADS
    ]
    if data.get("historical_schema_parse_results") != historical_parse_results:
        errors.append("historical schema parse result mismatch")
    for result in historical_parse_results:
        if any(value is not None for value in result["record_v3_values"].values()):
            errors.append(
                f"historical v{result['schema_version']} record gained v3 values"
            )
        if any(value is not None for value in result["attempt_v3_values"].values()):
            errors.append(
                f"historical v{result['schema_version']} attempt gained v3 values"
            )

    if data.get("telemetry_oracle") != TELEMETRY_ORACLE:
        errors.append("telemetry oracle mismatch")
    expected_telemetry_ids = {item["id"] for item in TELEMETRY_WITNESSES}
    witnesses = data.get("telemetry_witnesses", [])
    witness_ids = [item.get("id") for item in witnesses]
    results = {item.get("id"): item for item in data.get("telemetry_witness_results", [])}
    if set(witness_ids) != expected_telemetry_ids or len(witness_ids) != len(
        expected_telemetry_ids
    ):
        errors.append("telemetry witness set mismatch")
    if set(results) != expected_telemetry_ids:
        errors.append("telemetry result set mismatch")
    for item in witnesses:
        observed = evaluate_telemetry(item)
        if results.get(item.get("id")) != observed:
            errors.append(f"telemetry result mismatch: {item.get('id')}")
        if observed["passed"] != item.get("expected_pass"):
            errors.append(f"telemetry expectation mismatch: {item.get('id')}")
        isolated_guard = ISOLATED_FAILURES.get(str(item.get("id")))
        if isolated_guard is not None:
            failed_guards = {
                name for name, passed in observed["guards"].items() if not passed
            }
            if failed_guards != {isolated_guard}:
                errors.append(
                    f"telemetry isolation mismatch: {item.get('id')}:{sorted(failed_guards)}"
                )
    equality = evaluate_telemetry(
        next(item for item in TELEMETRY_WITNESSES if item["id"] == "all_numeric_equalities")
    )
    equality_fields = {
        "maximum_horizontal_displacement_from_capture_m": "maximum_horizontal_displacement_from_capture_m",
        "maximum_progress_toward_exact_center_m": "maximum_progress_toward_exact_center_m",
        "terminal_z_m": "maximum_terminal_z_m",
    }
    for result_field, threshold_field in equality_fields.items():
        if not math.isclose(
            float(equality[result_field]),
            float(TELEMETRY_ORACLE[threshold_field]),
            abs_tol=1e-12,
        ):
            errors.append(f"numeric equality witness mismatch: {result_field}")

    boundaries = data.get("boundaries", [])
    paths = [item.get("path") for item in boundaries]
    runtime_paths = {
        path
        for transit in runtime_transit_by_clock.values()
        for path in transit
    }
    expected_paths = runtime_paths | IMPLEMENTATION_OWNED | DESIGN_SUPPORT
    if set(paths) != expected_paths or len(paths) != len(expected_paths):
        errors.append("runtime-derived boundary set mismatch")
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
        errors.append("artifact missing")
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
