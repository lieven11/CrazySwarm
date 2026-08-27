from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_requirement_catalog_is_complete_and_selectively_routed() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_requirement_catalog.py", "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["valid"] is True
    assert result["definition_count"] == 150
    assert result["prefix_counts"]["WFL"] == 54

    compatibility = (ROOT / "docs/project/WORKFLOW_AND_REQUIREMENTS.md").read_text(encoding="utf-8")
    assert "requirements/README.md" in compatibility
    assert "| `REQ-" not in compatibility


def test_project_map_references_live_entrypoints_and_tests() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_project_map.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["valid"] is True
    assert result["mapped_path_count"] >= 20


def test_run_summarizer_combines_artifacts_and_respects_clock_epochs(tmp_path: Path) -> None:
    csv_path = tmp_path / "demo-telemetry.csv"
    fieldnames = [
        "csv_schema_version",
        "run_id",
        "mission_id",
        "configuration_sha256",
        "event_id",
        "vehicle_id",
        "operating_mode",
        "source_timestamp_s",
        "telemetry_sequence",
        "simulation_timestamp_s",
        "source_clock_id",
        "source_clock_epoch",
        "state",
        "position_x_m",
        "position_y_m",
        "position_z_m",
        "ground_truth_x_m",
        "ground_truth_y_m",
        "ground_truth_z_m",
        "velocity_x_m_s",
        "velocity_y_m_s",
        "velocity_z_m_s",
        "battery_percent",
        "battery_voltage_v",
        "battery_current_a",
        "range_front_m",
        "motor_m1_applied_pwm_percent",
        "motor_m1_saturated",
        "faults_json",
    ]
    rows = [
        {
            "csv_schema_version": "1",
            "run_id": "run-1",
            "mission_id": "mission-1",
            "configuration_sha256": "a" * 64,
            "event_id": "event-1",
            "vehicle_id": "Alpha",
            "operating_mode": "SIM",
            "source_timestamp_s": "1.0",
            "telemetry_sequence": "1",
            "simulation_timestamp_s": "1.0",
            "source_clock_id": "fast-sim-Alpha",
            "source_clock_epoch": "0",
            "state": "FLYING",
            "position_x_m": "0",
            "position_y_m": "0",
            "position_z_m": "0.5",
            "ground_truth_x_m": "0",
            "ground_truth_y_m": "0",
            "ground_truth_z_m": "0.5",
            "velocity_x_m_s": "0.3",
            "velocity_y_m_s": "0.4",
            "velocity_z_m_s": "0",
            "battery_percent": "90",
            "battery_voltage_v": "4.0",
            "battery_current_a": "1.2",
            "range_front_m": "0.8",
            "motor_m1_applied_pwm_percent": "55",
            "motor_m1_saturated": "false",
            "faults_json": "[]",
        },
        {
            "csv_schema_version": "1",
            "run_id": "run-1",
            "mission_id": "mission-1",
            "configuration_sha256": "a" * 64,
            "event_id": "event-2",
            "vehicle_id": "Alpha",
            "operating_mode": "SIM",
            "source_timestamp_s": "0.1",
            "telemetry_sequence": "2",
            "simulation_timestamp_s": "0.1",
            "source_clock_id": "fast-sim-Alpha",
            "source_clock_epoch": "1",
            "state": "READY",
            "position_x_m": "0",
            "position_y_m": "0",
            "position_z_m": "0",
            "ground_truth_x_m": "0",
            "ground_truth_y_m": "0",
            "ground_truth_z_m": "0",
            "velocity_x_m_s": "0",
            "velocity_y_m_s": "0",
            "velocity_z_m_s": "0",
            "battery_percent": "89",
            "battery_voltage_v": "3.9",
            "battery_current_a": "0.2",
            "range_front_m": "1.0",
            "motor_m1_applied_pwm_percent": "0",
            "motor_m1_saturated": "false",
            "faults_json": '["RESET_OBSERVED"]',
        },
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    (tmp_path / "demo-manifest.json").write_text(
        json.dumps({"mission_execution_id": "execution-1", "status": "SUCCEEDED"}),
        encoding="utf-8",
    )
    (tmp_path / "demo-evaluation.json").write_text(
        json.dumps(
            {
                "mission_execution_id": "execution-1",
                "status": "COMPLETE",
                "evidence": {"complete": True, "missing": []},
                "summary": ["Evidence is complete."],
                "vehicles": [{"vehicle_id": "Alpha", "terminal_state": "READY"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "demo-analysis.json").write_text(
        json.dumps(
            {
                "mission_execution_id": "execution-1",
                "mission_outcome": "SUCCEEDED",
                "evidence_complete": True,
                "all_required_behavior_oracles_passed": True,
                "motion_quality": [],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "scripts/summarize_run.py", str(csv_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    telemetry = result["telemetry"]
    vehicle = telemetry["vehicles"][0]
    assert telemetry["row_count"] == 2
    assert vehicle["speed_m_s"]["max"] == 0.5
    assert vehicle["battery_percent"] == {"start": 90.0, "end": 89.0}
    assert len(vehicle["source_time_windows"]) == 2
    assert "RESET_OBSERVED" in vehicle["faults"]
    assert "MULTIPLE_CLOCK_EPOCHS_OR_SOURCES_ANALYZE_SEPARATELY" in telemetry["anomalies"]
    assert result["cross_artifact_anomalies"] == []
