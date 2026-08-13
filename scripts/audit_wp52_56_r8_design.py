#!/usr/bin/env python3
"""Prototype and audit the exact WP-52--56 R8 relation overlay."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_submission_runtime as runtime_qualifier

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.service import CampaignRunMode, CampaignService
from crazyswarm_app.campaign.submissions import (
    AdmissionLifecycle,
    SubmissionStatus,
    load_admission_registry,
    load_case_submission_registry,
)
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory, sample_trajectory
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "docs/work-packages/WP52_56_R8_RELATION_PREDRAFT_AUDIT_2026-08-12.json"
)
TARGET_RELATIONS = {
    (
        "1d.takeoff_hover_land.canonical_nominal",
        "vertical_cycle.minimum_duration",
    ): (
        "MIN_RUNTIME_SOURCE_TIME(TM_DURATION),PASS(DY_VERTICAL_TRACKING),"
        "PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)"
    ),
    (
        "1d.takeoff_hover_land.canonical_nominal",
        "vertical_cycle.precision_first",
    ): "OPEN(INCONCLUSIVE_RUNTIME_DELTA_BELOW_DISTINCTNESS)",
    (
        "3d.constrained_volume.canonical_nominal",
        "constrained.timing_makespan",
    ): (
        "MIN_RUNTIME_SOURCE_TIME(TM_DURATION),CAT(DS_MANEUVER=timing),"
        "PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})"
    ),
    (
        "3d.constrained_volume.canonical_nominal",
        "constrained.robust_schedule",
    ): "OPEN(INCONCLUSIVE_AXIS_INVARIANT_METRIC)",
}
DISABLED_KEYS = {
    (
        "1d.takeoff_hover_land.canonical_nominal",
        "vertical_cycle.precision_first",
    ),
    (
        "3d.constrained_volume.canonical_nominal",
        "constrained.robust_schedule",
    ),
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fleet_source_time_observation(bundle: dict[str, Any]) -> dict[str, Any]:
    fleet_events = bundle["context"]["fleet_events"]
    starts = [
        item
        for item in fleet_events
        if item["event_type"] == "CHILD_START_REQUESTED"
    ]
    completed = [
        item for item in fleet_events if item["event_type"] == "TASK_COMPLETED"
    ]
    terminals = [
        item for item in fleet_events if item["event_type"] == "FLEET_TERMINAL"
    ]
    if not starts or len(completed) != len(starts) or len(terminals) != 1:
        raise ValueError("fleet source-time interval lacks exact start/completion/terminal events")
    if terminals[0].get("details", {}).get("status") != "SUCCEEDED":
        raise ValueError("fleet source-time interval did not end SUCCEEDED")
    telemetry = [
        item["payload"]["telemetry"]
        for item in bundle["events"]
        if item.get("kind") == "telemetry"
        and isinstance(item.get("payload", {}).get("telemetry"), dict)
    ]
    if not telemetry or any(item.get("simulation_timestamp_s") is None for item in telemetry):
        raise ValueError("fleet source-time interval lacks shared simulation timestamps")
    start_s = min(float(item["simulation_timestamp_s"]) for item in telemetry)
    terminal_s = max(float(item["simulation_timestamp_s"]) for item in telemetry)
    if terminal_s <= start_s:
        raise ValueError("fleet source-time interval is non-positive")
    roles = tuple(sorted(str(item["task_id"]) for item in completed))
    payload = {
        "clock": "shared-fast-sim-simulation_timestamp_s",
        "start_event": "FIRST_RETAINED_CHILD_TELEMETRY_AFTER_ADMISSION",
        "terminal_event": "LAST_RETAINED_CHILD_TELEMETRY_BEFORE_FLEET_TERMINAL_SUCCEEDED",
        "start_source_s": start_s,
        "terminal_source_s": terminal_s,
        "duration_s": terminal_s - start_s,
        "completed_roles": roles,
        "telemetry_envelope_vector_sha256": canonical_sha256(telemetry),
        "fleet_event_vector_sha256": canonical_sha256(fleet_events),
    }
    return {**payload, "observation_sha256": canonical_sha256(payload)}


def _vector_z(value: Any) -> float | None:
    if not isinstance(value, dict) or not isinstance(value.get("z"), int | float):
        return None
    return float(value["z"])


def _vertical_tracking_observation(bundle: dict[str, Any]) -> dict[str, Any]:
    by_vehicle: dict[str, list[dict[str, Any]]] = {}
    for event in bundle["events"]:
        vehicle_id = event.get("vehicle_id")
        if vehicle_id:
            by_vehicle.setdefault(str(vehicle_id), []).append(event)
    role_results = []
    all_errors: list[float] = []
    for vehicle_id, events in sorted(by_vehicle.items()):
        vehicle_errors: list[float] = []
        command_ids: list[str] = []
        for command_index, event in enumerate(events):
            if event.get("kind") != "command":
                continue
            command = event.get("payload", {}).get("command", {})
            command_payload = command.get("payload", {})
            if command_payload.get("kind") != "execute_trajectory":
                continue
            command_id = str(command["command_id"])
            acknowledgement_index = next(
                (
                    index
                    for index in range(command_index + 1, len(events))
                    if events[index].get("kind") == "acknowledgement"
                    and events[index]
                    .get("payload", {})
                    .get("acknowledgement", {})
                    .get("command_id")
                    == command_id
                ),
                None,
            )
            if acknowledgement_index is None:
                raise ValueError(f"trajectory command {command_id} has no acknowledgement")
            samples = [
                item
                for item in events[command_index + 1 : acknowledgement_index]
                if item.get("kind") == "telemetry"
            ]
            if not samples:
                raise ValueError(f"trajectory command {command_id} has no route telemetry")
            trajectory = TimeParameterizedTrajectory.model_validate(
                command_payload["trajectory"]
            )
            source_start_s = float(samples[0]["payload"]["telemetry"]["source_timestamp_s"])
            for sample in samples:
                envelope = sample["payload"]["telemetry"]
                actual_payload = envelope["telemetry"]
                actual_z = _vector_z(actual_payload.get("ground_truth_position_m"))
                if actual_z is None:
                    actual_z = _vector_z(actual_payload.get("position_m"))
                if actual_z is None:
                    continue
                elapsed_s = float(envelope["source_timestamp_s"]) - source_start_s
                desired_z = sample_trajectory(trajectory, elapsed_s).position_m.z
                vehicle_errors.append(abs(actual_z - desired_z))
            command_ids.append(command_id)
        if vehicle_errors:
            all_errors.extend(vehicle_errors)
            role_results.append(
                {
                    "vehicle_id": vehicle_id,
                    "command_ids": command_ids,
                    "sample_count": len(vehicle_errors),
                    "rms_vertical_position_error_m": math.sqrt(
                        sum(value * value for value in vehicle_errors) / len(vehicle_errors)
                    ),
                    "maximum_vertical_position_error_m": max(vehicle_errors),
                    "error_vector_sha256": canonical_sha256(vehicle_errors),
                }
            )
    if not all_errors:
        raise ValueError("no commanded-versus-observed vertical route samples")
    payload = {
        "metric_id": "DY_VERTICAL_TRACKING",
        "boundary": "EXECUTE_TRAJECTORY_COMMAND_TO_MATCHING_ACKNOWLEDGEMENT",
        "actual_signal": "ground_truth_position_m.z_or_position_m.z",
        "commanded_signal": "sampled_accepted_trajectory.position_m.z",
        "roles": role_results,
        "sample_count": len(all_errors),
        "rms_vertical_position_error_m": math.sqrt(
            sum(value * value for value in all_errors) / len(all_errors)
        ),
        "maximum_vertical_position_error_m": max(all_errors),
        "error_vector_sha256": canonical_sha256(all_errors),
    }
    return {**payload, "observation_sha256": canonical_sha256(payload)}


def _clearance_observation(bundle: dict[str, Any]) -> dict[str, Any]:
    plan = bundle["context"]["campaign_plan"]
    certificate = plan["feasibility_certificate"]
    if not certificate["passed"] or certificate["violations"]:
        raise ValueError("runtime accepted plan lacks a passing clearance certificate")
    pairwise = float(certificate["minimum_pairwise_protected_clearance_m"])
    solid = float(certificate["minimum_solid_protected_clearance_m"])
    payload = {
        "metric_id": "SP_CLEARANCE",
        "verifier_id": certificate["verifier_id"],
        "plan_sha256": plan["plan_sha256"],
        "candidate_sha256": certificate["candidate_sha256"],
        "certificate_sha256": certificate["certificate_sha256"],
        "minimum_pairwise_protected_clearance_m": pairwise,
        "minimum_solid_protected_clearance_m": solid,
        "minimum_protected_clearance_m": min(pairwise, solid),
    }
    return {**payload, "observation_sha256": canonical_sha256(payload)}


async def _execute_and_observe(
    selection: runtime_qualifier.RuntimeSelection,
    repetition: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="wp52-56-r8-design-audit-") as raw:
        temporary = Path(raw)
        config = load_config(ROOT / "config/app.yaml").model_copy(
            update={"cache_directory": temporary / "cache"}
        )
        scenario = load_scenario(ROOT / "config/worlds/one_drone.yaml")
        scenario = scenario.model_copy(
            update={
                "simulation": scenario.simulation.model_copy(
                    update={"clock_mode": ClockMode.ACCELERATED}
                )
            }
        )
        runtime = create_runtime(
            config,
            scenario,
            evidence_path=temporary / "evidence.sqlite3",
        )
        service = CampaignService(
            catalog=CampaignCatalog(ROOT / "missions/campaigns/sim/cases"),
            state_directory=temporary / "campaign",
            executor=FastSimCampaignExecutor(runtime),
        )
        await runtime.start()
        try:
            row = await runtime_qualifier._execute_selection(
                service,
                selection,
                mode=CampaignRunMode.AUTOMATED_ACCELERATED,
                repetition=repetition,
            )
            if not row["passed"]:
                raise ValueError(f"runtime row failed: {selection.key}")
            bundle_path = (
                service.state_directory
                / "evidence"
                / row["mission_execution_id"]
                / "execution-bundle.json"
            )
            bundle = _json(bundle_path)
            plan = bundle["context"]["campaign_plan"]
            if plan["plan_sha256"] != row["plan_sha256"]:
                raise ValueError("bundle/retained runtime plan identity mismatch")
            return {
                "selection_key": row["selection_key"],
                "case_id": row["case_id"],
                "selection_id": row["selection_id"],
                "baseline": row["baseline"],
                "repetition": repetition,
                "resolved_planning_package_sha256": row[
                    "resolved_planning_package_sha256"
                ],
                "plan_sha256": row["plan_sha256"],
                "schedule_sha256": row["schedule_sha256"],
                "trajectory_set_sha256": row["trajectory_set_sha256"],
                "artifact_set_sha256": row["artifact_set_sha256"],
                "evaluation_sha256": row["artifacts"]["evaluation_sha256"],
                "telemetry_csv_sha256": row["artifacts"]["telemetry_csv_sha256"],
                "execution_bundle_file_sha256": _file_sha256(bundle_path),
                "execution_bundle_internal_sha256": bundle["bundle_sha256"],
                "fleet_source_time": _fleet_source_time_observation(bundle),
                "vertical_tracking": _vertical_tracking_observation(bundle),
                "clearance": _clearance_observation(bundle),
                "contact_settle_s": row["artifacts"]["numeric_vehicle_summary"][
                    "post_contact_settling_s"
                ],
                "hard_runtime_gates_passed": True,
            }
        finally:
            await runtime.stop()


def _overlay_audit() -> dict[str, Any]:
    registry = load_case_submission_registry()
    admissions = load_admission_registry()
    proposal_map = {
        (row.case_id, proposal.submission_id): proposal
        for row in registry.rows
        for proposal in row.submissions
    }
    admission_map = {
        (row.case_id, proposal.submission_id): (row, proposal)
        for row in admissions.rows
        for proposal in row.proposals
    }
    if set(proposal_map) != set(admission_map):
        raise ValueError("registry/admission proposal key mismatch")
    if not set(TARGET_RELATIONS).issubset(proposal_map):
        raise ValueError("R8 overlay names a missing proposal")
    for key, relation in TARGET_RELATIONS.items():
        row, proposal = admission_map[key]
        if proposal.comparator_id != f"BASELINE({key[0]})":
            raise ValueError(f"R8 target has a non-exact comparator: {key}")
        relation_metrics = {
            metric for metric in row.metric_ids if f"({metric}" in relation
        }
        if not relation_metrics.issubset(row.metric_ids):
            raise ValueError(f"R8 relation uses an out-of-row metric: {key}")
    dependent_key = (
        "3d.constrained_volume.canonical_nominal",
        "constrained.priority_order",
    )
    dependent_spec = proposal_map[dependent_key]
    _, dependent_oracle = admission_map[dependent_key]
    expected_peer = (
        "PEER(3d.constrained_volume.canonical_nominal/"
        "constrained.timing_makespan)"
    )
    dependent_collapse_passed = (
        not dependent_spec.catalog_visible
        and dependent_spec.status is SubmissionStatus.PLANNED_NOT_EXECUTABLE
        and dependent_oracle.qualifying_relation == "COLLAPSE_ALL"
        and dependent_oracle.comparator_id == expected_peer
        and (
            "3d.constrained_volume.canonical_nominal",
            "constrained.timing_makespan",
        )
        not in DISABLED_KEYS
    )
    current_status = Counter(item.status.value for item in proposal_map.values())
    proposed_status = Counter(current_status)
    for key in DISABLED_KEYS:
        if proposal_map[key].status is not SubmissionStatus.EXECUTABLE:
            raise ValueError(f"R8 disabled overlay target is not currently executable: {key}")
        proposed_status[SubmissionStatus.EXECUTABLE.value] -= 1
        proposed_status[SubmissionStatus.PLANNED_NOT_EXECUTABLE.value] += 1
    lifecycle = Counter(item.lifecycle.value for item in admissions.rows)
    visible_hidden = Counter(
        "visible" if item.catalog_visible else "hidden"
        for item in proposal_map.values()
    )
    payload = {
        "case_count": len(registry.rows),
        "proposal_count": len(proposal_map),
        "unique_proposal_count": len(set(proposal_map)),
        "lifecycle_counts": dict(sorted(lifecycle.items())),
        "visibility_counts": dict(sorted(visible_hidden.items())),
        "current_status_counts": dict(sorted(current_status.items())),
        "proposed_status_counts": dict(sorted(proposed_status.items())),
        "target_relations": {
            f"{case_id}/{submission_id}": relation
            for (case_id, submission_id), relation in sorted(TARGET_RELATIONS.items())
        },
        "disabled_keys": sorted(f"{case_id}/{submission_id}" for case_id, submission_id in DISABLED_KEYS),
        "unchanged_key_count": len(proposal_map) - len(TARGET_RELATIONS),
        "no_duplicate_missing_or_extra_key": len(proposal_map) == 111,
        "metric_membership_passed": True,
        "exact_comparators_passed": True,
        "dependent_peer_collapse": {
            "proposal_key": "/".join(dependent_key),
            "comparator_id": dependent_oracle.comparator_id,
            "target_relation": TARGET_RELATIONS[
                (
                    "3d.constrained_volume.canonical_nominal",
                    "constrained.timing_makespan",
                )
            ],
            "target_remains_executable_in_overlay": True,
            "passed": dependent_collapse_passed,
        },
        "passed": (
            len(registry.rows) == 54
            and len(proposal_map) == 111
            and lifecycle
            == Counter(
                {
                    AdmissionLifecycle.SUBMISSIONS.value: 43,
                    AdmissionLifecycle.BASELINE_ONLY.value: 9,
                    AdmissionLifecycle.RETAIN_EXISTING_ONLY.value: 2,
                }
            )
            and visible_hidden == Counter({"visible": 83, "hidden": 28})
            and proposed_status
            == Counter(
                {
                    SubmissionStatus.EXECUTABLE.value: 23,
                    SubmissionStatus.PLANNED_NOT_EXECUTABLE.value: 88,
                }
            )
            and dependent_collapse_passed
        ),
    }
    return {**payload, "audit_sha256": canonical_sha256(payload)}


def _median(rows: list[dict[str, Any]], path: tuple[str, ...]) -> float:
    values: list[float] = []
    for row in rows:
        value: Any = row
        for key in path:
            value = value[key]
        values.append(float(value))
    return statistics.median(values)


def _relation_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_selection: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_selection.setdefault((row["case_id"], row["selection_id"]), []).append(row)
    output = []
    for (case_id, submission_id), relation in sorted(TARGET_RELATIONS.items()):
        baseline = by_selection[(case_id, "case_baseline")]
        subject = by_selection[(case_id, submission_id)]
        baseline_duration = _median(baseline, ("fleet_source_time", "duration_s"))
        subject_duration = _median(subject, ("fleet_source_time", "duration_s"))
        baseline_vertical = _median(
            baseline, ("vertical_tracking", "rms_vertical_position_error_m")
        )
        subject_vertical = _median(
            subject, ("vertical_tracking", "rms_vertical_position_error_m")
        )
        baseline_clearance = _median(
            baseline, ("clearance", "minimum_protected_clearance_m")
        )
        subject_clearance = _median(
            subject, ("clearance", "minimum_protected_clearance_m")
        )
        baseline_settle = _median(baseline, ("contact_settle_s",))
        subject_settle = _median(subject, ("contact_settle_s",))
        if submission_id in {
            "vertical_cycle.minimum_duration",
            "constrained.timing_makespan",
        }:
            relation_passed = baseline_duration - subject_duration >= 0.10
            disposition = "QUALIFY_RELATION"
        elif submission_id == "vertical_cycle.precision_first":
            relation_passed = (
                baseline_vertical - subject_vertical >= 0.005
                and baseline_settle - subject_settle >= 0.10
            )
            disposition = "OPEN(INCONCLUSIVE_RUNTIME_DELTA_BELOW_DISTINCTNESS)"
        else:
            relation_passed = subject_clearance - baseline_clearance >= 0.01
            disposition = "OPEN(INCONCLUSIVE_AXIS_INVARIANT_METRIC)"
        output.append(
            {
                "proposal_key": f"{case_id}/{submission_id}",
                "relation": relation,
                "baseline_source_time_duration_s": baseline_duration,
                "subject_source_time_duration_s": subject_duration,
                "duration_delta_baseline_minus_subject_s": (
                    baseline_duration - subject_duration
                ),
                "baseline_vertical_tracking_rms_m": baseline_vertical,
                "subject_vertical_tracking_rms_m": subject_vertical,
                "vertical_tracking_delta_baseline_minus_subject_m": (
                    baseline_vertical - subject_vertical
                ),
                "baseline_contact_settle_s": baseline_settle,
                "subject_contact_settle_s": subject_settle,
                "baseline_protected_clearance_m": baseline_clearance,
                "subject_protected_clearance_m": subject_clearance,
                "clearance_delta_subject_minus_baseline_m": (
                    subject_clearance - baseline_clearance
                ),
                "three_repeats_each": len(baseline) == len(subject) == 3,
                "hard_runtime_gates_passed": all(
                    row["hard_runtime_gates_passed"] for row in (*baseline, *subject)
                ),
                "directional_relation_passed": relation_passed,
                "proposed_disposition": disposition,
                "passed": (
                    relation_passed
                    if disposition == "QUALIFY_RELATION"
                    else not relation_passed
                ),
            }
        )
    return output


async def _run(output: Path) -> dict[str, Any]:
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    matrix = runtime_qualifier._matrix(catalog)
    target_cases = {case_id for case_id, _ in TARGET_RELATIONS}
    target_ids = {submission_id for _, submission_id in TARGET_RELATIONS}
    selections = tuple(
        item
        for item in matrix
        if item.case_id in target_cases
        and (item.baseline or item.selection_id in target_ids)
    )
    if len(selections) != 6 or sum(item.baseline for item in selections) != 2:
        raise ValueError("R8 runtime prototype must contain two baselines and four subjects")
    rows = []
    for selection in selections:
        for repetition in range(1, 4):
            row = await _execute_and_observe(selection, repetition)
            rows.append(row)
            print(selection.key, repetition, "PASS", flush=True)
    overlay = _overlay_audit()
    relations = _relation_results(rows)
    payload = {
        "schema_version": 1,
        "audit_id": "wp52-56-r8-relation-predraft-v1",
        "base_commit": "4bec32a827785f5c25cb32a4f2084ced8045f3b3",
        "accepted_r7_design_payload_sha256": (
            "4a394f58ecda69b07fce919c009e090aacb20a9ef65bd44a3a7b794fb16ad0a5"
        ),
        "claim_boundary": (
            "Normal CampaignService.run_active deterministic accelerated Fast Sim; "
            "independent JSON/event/trajectory/certificate observations; no live-Isaac, "
            "digital-twin, hardware, or physical-flight claim."
        ),
        "run_count": len(rows),
        "selection_count": len(selections),
        "repetitions_per_selection": 3,
        "overlay_audit": overlay,
        "relation_results": relations,
        "runs": rows,
        "passed": (
            len(rows) == 18
            and overlay["passed"]
            and all(item["passed"] for item in relations)
        ),
    }
    payload["audit_sha256"] = canonical_sha256(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    arguments = _arguments()
    payload = asyncio.run(_run(arguments.output))
    if arguments.check and not payload["passed"]:
        return 1
    print(payload["audit_sha256"], flush=True)
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
