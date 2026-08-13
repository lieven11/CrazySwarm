#!/usr/bin/env python3
"""Execute the visible WP-52--56 submission matrix through normal Fast Sim runtime."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.submission_measurement import (
    _authored_points,
    _independent_samples,
    _point_polyline_distance,
)
from crazyswarm_app.campaign.service import (
    CampaignRunMode,
    CampaignRunStatus,
    CampaignService,
)
from crazyswarm_app.campaign.submissions import (
    ENERGY_AWARE_RETIMING_CAPABILITY_ID,
    ROUTE_FIDELITY_CAPABILITY_ID,
    ExecutionCapabilityRequest,
    ExecutionProfileParameters,
    PlanningCapabilityRequest,
    SubmissionLayer,
    SubmissionStatus,
    load_case_submission_registry,
    proposal_oracle_for_case,
)
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "missions/campaigns/sim/qualification/selective-submission-runtime-v2.json"
REGISTRY_QUALIFICATION = (
    ROOT / "missions/campaigns/sim/qualification/selective-submission-registry-v1.json"
)


@dataclass(frozen=True)
class RuntimeSelection:
    case_id: str
    selection_id: str
    planning_submission_id: str | None = None
    execution_profile_submission_id: str | None = None
    comparison_context_id: str | None = None
    proposal_key: str | None = None
    baseline: bool = False
    planning_capability_id: str | None = None
    execution_capability_id: str | None = None
    parent_case_id: str | None = None

    @property
    def key(self) -> str:
        context = self.comparison_context_id or "case-default"
        return f"{self.case_id}/{self.selection_id}@{context}"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the complete visible executable submission matrix in Fast Sim"
    )
    parser.add_argument("--mode", choices=("accelerated", "both"), default="accelerated")
    parser.add_argument("--repetitions", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--selection", action="append", default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _matrix(catalog: CampaignCatalog) -> tuple[RuntimeSelection, ...]:
    registry = load_case_submission_registry()
    subjects: list[RuntimeSelection] = []
    baselines: dict[tuple[str, str | None], RuntimeSelection] = {}
    for row in registry.rows:
        case = catalog.get(row.case_id)
        for spec in row.submissions:
            if not spec.catalog_visible or spec.status is not SubmissionStatus.EXECUTABLE:
                continue
            oracle = proposal_oracle_for_case(case, spec.submission_id)
            context_id = oracle.comparison_context_id
            baselines.setdefault(
                (row.case_id, context_id),
                RuntimeSelection(
                    case_id=row.case_id,
                    selection_id="case_baseline",
                    comparison_context_id=context_id,
                    baseline=True,
                ),
            )
            if spec.layer in {
                SubmissionLayer.EXECUTION_PROFILE,
                SubmissionLayer.CORE_CAPABILITY,
            }:
                subjects.append(
                    RuntimeSelection(
                        case_id=row.case_id,
                        selection_id=spec.submission_id,
                        execution_profile_submission_id=spec.submission_id,
                        comparison_context_id=context_id,
                        proposal_key=f"{row.case_id}/{spec.submission_id}",
                    )
                )
            else:
                subjects.append(
                    RuntimeSelection(
                        case_id=row.case_id,
                        selection_id=spec.submission_id,
                        planning_submission_id=spec.submission_id,
                        comparison_context_id=context_id,
                        proposal_key=f"{row.case_id}/{spec.submission_id}",
                    )
                )
    capability_subjects = (
        RuntimeSelection(
            case_id="1d.curved_route.canonical_nominal",
            selection_id=ROUTE_FIDELITY_CAPABILITY_ID,
            proposal_key=f"capability/{ROUTE_FIDELITY_CAPABILITY_ID}/canonical",
            planning_capability_id=ROUTE_FIDELITY_CAPABILITY_ID,
        ),
        RuntimeSelection(
            case_id="1d.curved_route.runtime-compatible-child",
            parent_case_id="1d.curved_route.canonical_nominal",
            selection_id=ROUTE_FIDELITY_CAPABILITY_ID,
            proposal_key=f"capability/{ROUTE_FIDELITY_CAPABILITY_ID}/renamed-child",
            planning_capability_id=ROUTE_FIDELITY_CAPABILITY_ID,
        ),
        RuntimeSelection(
            case_id="1d.point_to_point_relocation.canonical_nominal",
            selection_id=ENERGY_AWARE_RETIMING_CAPABILITY_ID,
            proposal_key=f"capability/{ENERGY_AWARE_RETIMING_CAPABILITY_ID}/canonical",
            execution_capability_id=ENERGY_AWARE_RETIMING_CAPABILITY_ID,
        ),
        RuntimeSelection(
            case_id="1d.point_to_point_relocation.runtime-compatible-child",
            parent_case_id="1d.point_to_point_relocation.canonical_nominal",
            selection_id=ENERGY_AWARE_RETIMING_CAPABILITY_ID,
            proposal_key=f"capability/{ENERGY_AWARE_RETIMING_CAPABILITY_ID}/renamed-child",
            execution_capability_id=ENERGY_AWARE_RETIMING_CAPABILITY_ID,
        ),
        RuntimeSelection(
            case_id="2d.parallel_routes.canonical_nominal",
            selection_id=ENERGY_AWARE_RETIMING_CAPABILITY_ID,
            proposal_key=f"capability/{ENERGY_AWARE_RETIMING_CAPABILITY_ID}/two-role",
            execution_capability_id=ENERGY_AWARE_RETIMING_CAPABILITY_ID,
        ),
    )
    for subject in capability_subjects:
        baselines.setdefault(
            (subject.case_id, None),
            RuntimeSelection(
                case_id=subject.case_id,
                parent_case_id=subject.parent_case_id,
                selection_id="capability_baseline",
                baseline=True,
            ),
        )
    subjects.extend(capability_subjects)
    return tuple(sorted(baselines.values(), key=lambda item: item.key) + sorted(subjects, key=lambda item: item.key))


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object at {path}")
    return value


def _numeric_vehicle_summary(evaluation: dict[str, Any]) -> dict[str, float]:
    ignored = {"vehicle_id", "profile_submission_id", "profile_submission_sha256"}
    values: dict[str, list[float]] = {}
    for vehicle in evaluation.get("vehicles", ()):
        if not isinstance(vehicle, dict):
            continue
        for key, value in vehicle.items():
            if key in ignored or isinstance(value, bool) or not isinstance(value, int | float):
                continue
            values.setdefault(key, []).append(float(value))
    return {
        key: sum(metric_values) / len(metric_values)
        for key, metric_values in sorted(values.items())
        if metric_values
    }


def _telemetry_energy_summary(path: Path) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, str]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            grouped.setdefault(row["vehicle_id"], []).append(row)
    vehicles = []
    for vehicle_id, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: float(row["source_timestamp_s"]))
        active = [
            index
            for index, row in enumerate(rows)
            if float(row.get("battery_current_a") or 0.0) > 0.0
            or any(
                float(row.get(f"motor_m{motor}_command_percent") or 0.0) > 0.0
                for motor in range(1, 5)
            )
        ]
        if not active:
            vehicles.append(
                {
                    "vehicle_id": vehicle_id,
                    "evidence_complete": False,
                    "reason": "no nonzero-thrust telemetry interval",
                }
            )
            continue
        window = rows[active[0] : active[-1] + 1]
        energy_wh = 0.0
        for before, after in zip(window, window[1:], strict=False):
            delta_s = float(after["source_timestamp_s"]) - float(
                before["source_timestamp_s"]
            )
            if delta_s <= 0.0:
                continue
            before_power = float(before["battery_voltage_v"]) * max(
                0.0, float(before["battery_current_a"])
            )
            after_power = float(after["battery_voltage_v"]) * max(
                0.0, float(after["battery_current_a"])
            )
            energy_wh += (before_power + after_power) * 0.5 * delta_s / 3600.0
        vehicles.append(
            {
                "vehicle_id": vehicle_id,
                "window_start_source_s": float(window[0]["source_timestamp_s"]),
                "window_end_source_s": float(window[-1]["source_timestamp_s"]),
                "energy_wh": energy_wh,
                "battery_used_percentage_points": (
                    float(window[0]["battery_percent"])
                    - float(window[-1]["battery_percent"])
                ),
                "terminal_reserve_percent": float(window[-1]["battery_percent"]),
                "evidence_complete": True,
            }
        )
    return {
        "integration": "TRAPEZOIDAL_VOLTAGE_TIMES_NONNEGATIVE_CURRENT",
        "window": "FIRST_NONZERO_THRUST_THROUGH_LAST_NONZERO_THRUST",
        "vehicles": vehicles,
        "fleet_energy_wh": sum(
            float(item.get("energy_wh", 0.0)) for item in vehicles
        ),
        "evidence_complete": bool(vehicles)
        and all(item["evidence_complete"] for item in vehicles),
    }


def _commanded_trajectory_summary(
    service: CampaignService,
    context: dict[str, Any],
) -> dict[str, Any]:
    case = service.active_case
    values = context.get("campaign_trajectories", {}).get("trajectories", ())
    roles = []
    for value in values:
        trajectory = TimeParameterizedTrajectory.model_validate(value)
        samples = _independent_samples(trajectory)
        authored = _authored_points(case, trajectory.role_id)
        roles.append(
            {
                "role_id": trajectory.role_id,
                "duration_s": trajectory.duration_s,
                "maximum_reference_deviation_m": max(
                    _point_polyline_distance(sample["position_m"], authored)
                    for sample in samples
                ),
                "declared_internal_stop_count": max(
                    0, len(trajectory.declared_stop_sequences) - 2
                ),
                "samples_sha256": canonical_sha256(samples),
            }
        )
    return {
        "sample_step_s": 0.01,
        "roles": roles,
        "maximum_reference_deviation_m": max(
            (item["maximum_reference_deviation_m"] for item in roles),
            default=float("inf"),
        ),
        "maximum_duration_s": max(
            (item["duration_s"] for item in roles),
            default=0.0,
        ),
    }


def _artifact_record(
    service: CampaignService,
    mission_execution_id: str,
) -> dict[str, Any]:
    directory = service.state_directory / "evidence" / mission_execution_id
    manifest_path = directory / "manifest.json"
    bundle_path = directory / "execution-bundle.json"
    evaluation_path = directory / "evaluation.json"
    analysis_path = directory / "analysis.json"
    telemetry_path = directory / "telemetry.csv"
    manifest = _json(manifest_path)
    bundle = _json(bundle_path)
    evaluation = _json(evaluation_path)
    analysis = _json(analysis_path)
    context = bundle.get("context", {})
    return {
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "execution_bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "evaluation_sha256": hashlib.sha256(evaluation_path.read_bytes()).hexdigest(),
        "analysis_file_sha256": hashlib.sha256(analysis_path.read_bytes()).hexdigest(),
        "telemetry_csv_sha256": hashlib.sha256(telemetry_path.read_bytes()).hexdigest(),
        "telemetry_csv_size_bytes": telemetry_path.stat().st_size,
        "manifest": manifest,
        "evaluation": evaluation,
        "analysis": analysis,
        "execution_head_trace": context.get("campaign_execution_head_trace"),
        "fleet_result": context.get("fleet_result"),
        "fleet_events": context.get("fleet_events"),
        "timing_trace": context.get("timing_trace"),
        "numeric_vehicle_summary": _numeric_vehicle_summary(evaluation),
        "commanded_trajectory_summary": _commanded_trajectory_summary(service, context),
        "telemetry_energy_summary": _telemetry_energy_summary(telemetry_path),
    }


async def _execute_selection(
    service: CampaignService,
    selection: RuntimeSelection,
    *,
    mode: CampaignRunMode,
    repetition: int,
) -> dict[str, Any]:
    service.set_active(
        selection.case_id,
        actor_id="wp52-56-submission-runtime-qualifier",
        reason="isolated exact submission runtime qualification",
    )
    idempotency = f"wp52-56-runtime-v2:{mode.value}:{selection.key}:repeat-{repetition}"
    try:
        review = await service.run_active(
            mode,
            idempotency_key=idempotency,
            submission_id=selection.execution_profile_submission_id,
            planning_submission_id=selection.planning_submission_id,
            comparison_context_id=selection.comparison_context_id,
            planning_capability_request=(
                PlanningCapabilityRequest(
                    capability_id=selection.planning_capability_id,
                )
                if selection.planning_capability_id is not None
                else None
            ),
            execution_capability_request=(
                ExecutionCapabilityRequest(
                    capability_id=selection.execution_capability_id,
                    parameters=ExecutionProfileParameters(),
                )
                if selection.execution_capability_id is not None
                else None
            ),
        )
    except Exception as error:  # retain the exact runtime failure rather than abort the matrix
        return {
            "selection_key": selection.key,
            "case_id": selection.case_id,
            "selection_id": selection.selection_id,
            "proposal_key": selection.proposal_key,
            "baseline": selection.baseline,
            "mode": mode.value,
            "repetition": repetition,
            "status": "FAILED_BEFORE_REVIEW",
            "failure_type": type(error).__name__,
            "failure_reason": str(error),
            "passed": False,
        }
    run = next(item for item in service.state.runs if item.run_id == review.run_id)
    if run.mission_execution_id is None:
        raise RuntimeError("completed runtime qualification row has no execution ID")
    artifacts = _artifact_record(service, run.mission_execution_id)
    evaluation = artifacts["evaluation"]
    profile_conformance = all(
        vehicle.get("planned_profile_conformance_passed") is not False
        for vehicle in evaluation.get("vehicles", ())
        if isinstance(vehicle, dict)
    )
    passed = (
        review.status is CampaignRunStatus.SUCCEEDED
        and review.analysis.evidence_complete
        and review.analysis.all_required_behavior_oracles_passed
        and evaluation.get("status") == "COMPLETE"
        and evaluation.get("evidence", {}).get("complete") is True
        and profile_conformance
        and (review.mode_comparison is None or review.mode_comparison.all_gates_passed)
    )
    return {
        "selection_key": selection.key,
        "case_id": selection.case_id,
        "case_sha256": run.locked_inputs.case_sha256,
        "selection_id": selection.selection_id,
        "proposal_key": selection.proposal_key,
        "baseline": selection.baseline,
        "planning_submission_id": run.locked_inputs.planning_submission_id,
        "planning_submission_sha256": run.locked_inputs.planning_submission_sha256,
        "execution_profile_submission_id": run.locked_inputs.submission_id,
        "execution_profile_sha256": run.locked_inputs.submission_sha256,
        "resolved_planning_package_sha256": (run.locked_inputs.resolved_planning_package_sha256),
        "comparison_context_id": selection.comparison_context_id,
        "planning_capability_id": selection.planning_capability_id,
        "execution_capability_id": selection.execution_capability_id,
        "parent_case_id": selection.parent_case_id,
        "mode": mode.value,
        "repetition": repetition,
        "status": review.status.value,
        "run_id": run.run_id,
        "mission_execution_id": run.mission_execution_id,
        "plan_sha256": run.plan_sha256,
        "schedule_sha256": run.schedule_sha256,
        "trajectory_set_sha256": run.trajectory_set_sha256,
        "artifact_set_sha256": review.artifact_set_sha256,
        "analysis_sha256": review.analysis.analysis_sha256,
        "review_sha256": review.review_sha256,
        "evidence_complete": review.analysis.evidence_complete,
        "all_required_behavior_oracles_passed": (
            review.analysis.all_required_behavior_oracles_passed
        ),
        "behavior_oracles": [
            item.model_dump(mode="json") for item in review.analysis.behavior_oracles
        ],
        "profile_conformance_passed": profile_conformance,
        "mode_comparison": (
            review.mode_comparison.model_dump(mode="json")
            if review.mode_comparison is not None
            else None
        ),
        "artifacts": artifacts,
        "passed": passed,
    }


async def _execute_isolated(
    selection: RuntimeSelection,
    *,
    mode: CampaignRunMode,
    repetition: int,
) -> dict[str, Any]:
    """Execute one matrix row without inheriting state from another row."""

    with tempfile.TemporaryDirectory(prefix="wp52-56-submission-runtime-row-") as raw:
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
        if selection.parent_case_id is not None:
            service.set_active(
                selection.parent_case_id,
                actor_id="wp52-56-submission-runtime-qualifier",
                reason="prepare isolated renamed-compatible capability child",
            )
            service.create_child(child_case_id=selection.case_id, updates={})
        await runtime.start()
        try:
            return await _execute_selection(
                service,
                selection,
                mode=mode,
                repetition=repetition,
            )
        finally:
            await runtime.stop()


def _repeat_gates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row["mode"] != CampaignRunMode.AUTOMATED_ACCELERATED.value:
            continue
        groups.setdefault((row["selection_key"], row["mode"]), []).append(row)
    output = []
    for (selection_key, mode), repeats in sorted(groups.items()):
        repeat_passed = all(item["passed"] for item in repeats)
        deterministic = repeat_passed and (
            len({item.get("plan_sha256") for item in repeats}) == 1
            and len({item.get("trajectory_set_sha256") for item in repeats}) == 1
            and len({item.get("resolved_planning_package_sha256") for item in repeats}) == 1
        )
        output.append(
            {
                "selection_key": selection_key,
                "mode": mode,
                "repeat_count": len(repeats),
                "all_repeats_passed": repeat_passed,
                "plan_package_trajectory_deterministic": deterministic,
                "passed": repeat_passed and deterministic,
            }
        )
    return output


def _subject_baseline_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baselines: dict[tuple[str, str | None, int], dict[str, Any]] = {}
    for row in rows:
        if row.get("baseline") and row["mode"] == CampaignRunMode.AUTOMATED_ACCELERATED.value:
            baselines[(row["case_id"], row.get("comparison_context_id"), row["repetition"])] = row
    output = []
    for subject in rows:
        if (
            subject.get("baseline")
            or subject["mode"] != CampaignRunMode.AUTOMATED_ACCELERATED.value
        ):
            continue
        baseline = baselines.get(
            (
                subject["case_id"],
                subject.get("comparison_context_id"),
                subject["repetition"],
            )
        )
        if baseline is None or not subject["passed"] or not baseline["passed"]:
            output.append(
                {
                    "proposal_key": subject.get("proposal_key"),
                    "repetition": subject["repetition"],
                    "passed": False,
                    "reason": "exact runtime baseline or subject is unavailable",
                }
            )
            continue
        before = baseline["artifacts"]["numeric_vehicle_summary"]
        after = subject["artifacts"]["numeric_vehicle_summary"]
        common = sorted(set(before) & set(after))
        output.append(
            {
                "proposal_key": subject["proposal_key"],
                "repetition": subject["repetition"],
                "baseline_run_id": baseline["run_id"],
                "subject_run_id": subject["run_id"],
                "numeric_vehicle_delta": {key: after[key] - before[key] for key in common},
                "passed": True,
            }
        )
    return output


def _capability_gates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accelerated = [
        row
        for row in rows
        if row["mode"] == CampaignRunMode.AUTOMATED_ACCELERATED.value
    ]
    baselines = {
        (row["case_id"], row["repetition"]): row
        for row in accelerated
        if row.get("baseline")
    }
    output = []
    route_rows = [
        row
        for row in accelerated
        if row.get("planning_capability_id") == ROUTE_FIDELITY_CAPABILITY_ID
    ]
    for row in route_rows:
        baseline = baselines.get((row["case_id"], row["repetition"]))
        subject_deviation = row.get("artifacts", {}).get(
            "commanded_trajectory_summary", {}
        ).get("maximum_reference_deviation_m")
        baseline_deviation = (
            baseline.get("artifacts", {})
            .get("commanded_trajectory_summary", {})
            .get("maximum_reference_deviation_m")
            if baseline is not None
            else None
        )
        passed = (
            row["passed"]
            and baseline is not None
            and baseline["passed"]
            and isinstance(subject_deviation, int | float)
            and isinstance(baseline_deviation, int | float)
            and subject_deviation <= 1e-6 + 1e-9
            and baseline_deviation - subject_deviation >= 0.01
        )
        output.append(
            {
                "capability_id": ROUTE_FIDELITY_CAPABILITY_ID,
                "case_id": row["case_id"],
                "repetition": row["repetition"],
                "baseline_maximum_reference_deviation_m": baseline_deviation,
                "subject_maximum_reference_deviation_m": subject_deviation,
                "passed": passed,
            }
        )

    energy_rows = [
        row
        for row in accelerated
        if row.get("execution_capability_id") == ENERGY_AWARE_RETIMING_CAPABILITY_ID
    ]
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in energy_rows:
        by_case.setdefault(row["case_id"], []).append(row)
    for case_id, subjects in sorted(by_case.items()):
        comparisons = []
        for subject in sorted(subjects, key=lambda item: item["repetition"]):
            baseline = baselines.get((case_id, subject["repetition"]))
            subject_energy = subject.get("artifacts", {}).get(
                "telemetry_energy_summary", {}
            )
            baseline_energy = (
                baseline.get("artifacts", {}).get("telemetry_energy_summary", {})
                if baseline is not None
                else {}
            )
            subject_commanded = subject.get("artifacts", {}).get(
                "commanded_trajectory_summary", {}
            )
            baseline_commanded = (
                baseline.get("artifacts", {}).get("commanded_trajectory_summary", {})
                if baseline is not None
                else {}
            )
            before_wh = baseline_energy.get("fleet_energy_wh")
            after_wh = subject_energy.get("fleet_energy_wh")
            before_duration = baseline_commanded.get("maximum_duration_s")
            after_duration = subject_commanded.get("maximum_duration_s")
            before_numeric = (
                baseline.get("artifacts", {}).get("numeric_vehicle_summary", {})
                if baseline is not None
                else {}
            )
            after_numeric = subject.get("artifacts", {}).get(
                "numeric_vehicle_summary", {}
            )
            per_repeat_passed = (
                subject["passed"]
                and baseline is not None
                and baseline["passed"]
                and subject_energy.get("evidence_complete") is True
                and baseline_energy.get("evidence_complete") is True
                and isinstance(before_wh, int | float)
                and isinstance(after_wh, int | float)
                and before_wh - after_wh >= 0.0002
                and isinstance(before_duration, int | float)
                and isinstance(after_duration, int | float)
                and before_duration - after_duration >= 0.10
                and after_numeric.get("tracking_rms_error_m", float("inf"))
                <= before_numeric.get("tracking_rms_error_m", float("-inf")) + 0.01
                and after_numeric.get("minimum_motor_thrust_headroom_n", -1.0) >= 0.0
                and all(
                    after["terminal_reserve_percent"]
                    >= before["terminal_reserve_percent"] - 1e-9
                    for before, after in zip(
                        baseline_energy.get("vehicles", ()),
                        subject_energy.get("vehicles", ()),
                        strict=True,
                    )
                )
            )
            comparisons.append(
                {
                    "repetition": subject["repetition"],
                    "baseline_energy_wh": before_wh,
                    "subject_energy_wh": after_wh,
                    "baseline_duration_s": before_duration,
                    "subject_duration_s": after_duration,
                    "passed": per_repeat_passed,
                }
            )
        before_values = [item["baseline_energy_wh"] for item in comparisons]
        after_values = [item["subject_energy_wh"] for item in comparisons]
        complete_values = all(
            isinstance(value, int | float) for value in (*before_values, *after_values)
        )
        before_median = statistics.median(before_values) if complete_values else None
        after_median = statistics.median(after_values) if complete_values else None
        required_improvement = (
            max(0.0005, 0.02 * before_median)
            if isinstance(before_median, int | float)
            else None
        )
        passed = (
            len(comparisons) == 3
            and all(item["passed"] for item in comparisons)
            and isinstance(before_median, int | float)
            and isinstance(after_median, int | float)
            and isinstance(required_improvement, float)
            and before_median - after_median >= required_improvement
        )
        output.append(
            {
                "capability_id": ENERGY_AWARE_RETIMING_CAPABILITY_ID,
                "case_id": case_id,
                "comparisons": comparisons,
                "baseline_median_energy_wh": before_median,
                "subject_median_energy_wh": after_median,
                "required_median_improvement_wh": required_improvement,
                "passed": passed,
            }
        )
    return output


async def _run(arguments: argparse.Namespace) -> int:
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    matrix = _matrix(catalog)
    if arguments.selection:
        selected_subjects = tuple(
            item
            for item in matrix
            if not item.baseline
            and any(token in item.key for token in arguments.selection)
        )
        required_baselines = {
            (item.case_id, item.comparison_context_id) for item in selected_subjects
        }
        matrix = tuple(
            item
            for item in matrix
            if item in selected_subjects
            or (
                item.baseline
                and (item.case_id, item.comparison_context_id) in required_baselines
            )
        )
    if not matrix:
        raise ValueError("runtime selection filter produced an empty matrix")

    rows: list[dict[str, Any]] = []
    for selection in matrix:
        for repetition in range(1, arguments.repetitions + 1):
            row = await _execute_isolated(
                selection,
                mode=CampaignRunMode.AUTOMATED_ACCELERATED,
                repetition=repetition,
            )
            rows.append(row)
            print(
                row["selection_key"],
                row["mode"],
                f"repeat={repetition}",
                "PASS" if row["passed"] else "FAIL",
                flush=True,
            )
    # The rounded-square profile pair is the R2 motion realtime anchor. The
    # source-time 2D and 3D fleet anchors are appended when their normal catalog
    # execution entries are implemented; absence remains fail-closed.
    if arguments.mode == "both":
        realtime_keys = {
            "1d.planar_shape_loop.rounded_square/case_baseline@case-default",
            "1d.planar_shape_loop.rounded_square/"
            "corner_transition.lookahead_0_60s@case-default",
        }
        for selection in matrix:
            if selection.key not in realtime_keys:
                continue
            row = await _execute_isolated(
                selection,
                mode=CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
                repetition=1,
            )
            rows.append(row)
            print(
                row["selection_key"],
                row["mode"],
                "PASS" if row["passed"] else "FAIL",
                flush=True,
            )

    repeat_gates = _repeat_gates(rows)
    deltas = _subject_baseline_deltas(rows)
    capability_gates = _capability_gates(rows)
    expected_subjects = sum(not item.baseline for item in matrix)
    expected_baselines = sum(item.baseline for item in matrix)
    accelerated_passed = (
        len([row for row in rows if row["mode"] == "AUTOMATED_ACCELERATED"])
        == len(matrix) * arguments.repetitions
        and all(row["passed"] for row in rows if row["mode"] == "AUTOMATED_ACCELERATED")
        and all(item["passed"] for item in repeat_gates)
        and all(item["passed"] for item in deltas)
        and all(item["passed"] for item in capability_gates)
    )
    realtime_rows = [row for row in rows if row["mode"] == "OPERATOR_OBSERVED_REALTIME"]
    motion_realtime_passed = len(realtime_rows) == 2 and all(row["passed"] for row in realtime_rows)
    realtime_anchors_passed = (
        arguments.mode == "both"
        and motion_realtime_passed
        and False  # fail closed until the 2D and 3D public runtime anchors are retained
    )
    passed = accelerated_passed and (arguments.mode == "accelerated" or realtime_anchors_passed)
    registry_qualification = _json(REGISTRY_QUALIFICATION)
    payload = {
        "schema_version": 2,
        "qualification_id": "selective-submission-runtime-v2",
        "claim_boundary": (
            "Normal CampaignService.run_active execution in deterministic Fast Sim. "
            "No live-Isaac, digital-twin, perception, hardware, or physical-flight claim."
        ),
        "accepted_r7_design_payload_sha256": (
            "4a394f58ecda69b07fce919c009e090aacb20a9ef65bd44a3a7b794fb16ad0a5"
        ),
        "registry_qualification_sha256": registry_qualification["report_sha256"],
        "requested_mode": arguments.mode,
        "repetitions": arguments.repetitions,
        "selection_filter": arguments.selection,
        "subject_selection_count": expected_subjects,
        "baseline_selection_count": expected_baselines,
        "run_count": len(rows),
        "accelerated_matrix_passed": accelerated_passed,
        "motion_realtime_anchor_passed": motion_realtime_passed,
        "two_dimensional_source_time_anchor_passed": False,
        "three_dimensional_atomic_fallback_anchor_passed": False,
        "realtime_anchors_passed": realtime_anchors_passed,
        "repeat_gates": repeat_gates,
        "subject_baseline_deltas": deltas,
        "capability_gates": capability_gates,
        "runs": rows,
        "passed": passed,
    }
    payload["qualification_sha256"] = canonical_sha256(payload)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"runtime qualification -> {arguments.output} passed={passed}",
        flush=True,
    )
    return 0 if passed else 1


def main() -> int:
    return asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
