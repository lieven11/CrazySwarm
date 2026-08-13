from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.service import CampaignRunMode, CampaignRunStatus, CampaignService
from crazyswarm_app.campaign.submissions import BASELINE_SUBMISSION_ID
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "missions/campaigns/sim/qualification/altitude-profile-runtime-qualification-v1.json"
)
ACCELERATED_MATRIX = (
    (
        "1d.altitude_transition.canonical_nominal",
        (
            BASELINE_SUBMISSION_ID,
            "constant_path_speed.slow",
            "constant_path_speed.stress",
            "ramped_segment_speed.altitude_kinks",
        ),
    ),
    (
        "1d.altitude_transition.wide",
        (
            BASELINE_SUBMISSION_ID,
            "constant_path_speed.stress",
            "bounded_vertical_rate.wide",
        ),
    ),
)
REALTIME_MATRIX = (
    (
        "1d.altitude_transition.canonical_nominal",
        (
            BASELINE_SUBMISSION_ID,
            "constant_path_speed.slow",
            "constant_path_speed.stress",
        ),
    ),
    (
        "1d.altitude_transition.wide",
        (BASELINE_SUBMISSION_ID, "constant_path_speed.stress"),
    ),
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Qualify the bounded WP-43 altitude-transition profile matrix"
    )
    parser.add_argument(
        "--mode",
        choices=("accelerated", "realtime", "both"),
        default="accelerated",
    )
    parser.add_argument("--repetitions", type=int, choices=(1, 2), default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _matrix(mode: str) -> tuple[tuple[CampaignRunMode, str, tuple[str, ...]], ...]:
    rows: list[tuple[CampaignRunMode, str, tuple[str, ...]]] = []
    if mode in {"accelerated", "both"}:
        rows.extend(
            (CampaignRunMode.AUTOMATED_ACCELERATED, case_id, submissions)
            for case_id, submissions in ACCELERATED_MATRIX
        )
    if mode in {"realtime", "both"}:
        rows.extend(
            (CampaignRunMode.OPERATOR_OBSERVED_REALTIME, case_id, submissions)
            for case_id, submissions in REALTIME_MATRIX
        )
    return tuple(rows)


def _evaluation(service: CampaignService, mission_execution_id: str) -> dict[str, Any]:
    path = service.state_directory / "evidence" / mission_execution_id / "evaluation.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("campaign evaluation artifact is not an object")
    return value


def _qualification_gates(rows: list[dict[str, Any]]) -> dict[str, bool]:
    non_baselines = [row for row in rows if row["submission_id"] != BASELINE_SUBMISSION_ID]
    exact_baselines = all(
        row["baseline_comparison"].get("baseline_available") is True
        for row in non_baselines
    )
    wide_stress = [
        row
        for row in rows
        if row["case_id"] == "1d.altitude_transition.wide"
        and row["submission_id"] == "constant_path_speed.stress"
    ]
    cross_geometry = bool(wide_stress) and all(
        row["cross_case_profile_comparison"].get("comparison_available") is True
        for row in wide_stress
    )
    grouped: dict[tuple[str, str, CampaignRunMode], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["case_id"], row["submission_id"], row["mode"])].append(row)
    repeat_identity = all(
        len({row["plan_sha256"] for row in repeats}) == 1
        and len({row["trajectory_set_sha256"] for row in repeats}) == 1
        and len(
            {
                (
                    row["vehicle_metrics"][0].get("battery_used_percent"),
                    row["vehicle_metrics"][0].get("terminal_state"),
                    row["vehicle_metrics"][0].get("touchdown_target_center_error_m"),
                    row["vehicle_metrics"][0].get("planned_profile_conformance_passed"),
                )
                for row in repeats
            }
        )
        == 1
        for repeats in grouped.values()
    )
    accelerated_canonical = {
        row["submission_id"]: row
        for row in rows
        if row["case_id"] == "1d.altitude_transition.canonical_nominal"
        and row["mode"] is CampaignRunMode.AUTOMATED_ACCELERATED
        and row["repetition"] == 1
    }
    slow = accelerated_canonical.get("constant_path_speed.slow")
    stress = accelerated_canonical.get("constant_path_speed.stress")
    operating_region_distinct = False
    if slow is not None and stress is not None:
        slow_vehicle = slow["vehicle_metrics"][0]
        stress_vehicle = stress["vehicle_metrics"][0]
        operating_region_distinct = any(
            abs(float(stress_vehicle[metric]) - float(slow_vehicle[metric])) > threshold
            for metric, threshold in (
                ("elapsed_s", 0.25),
                ("minimum_motor_thrust_headroom_n", 0.001),
                ("tracking_rms_error_m", 0.002),
                ("battery_used_percent", 0.1),
            )
            if stress_vehicle.get(metric) is not None and slow_vehicle.get(metric) is not None
        )
    realtime_rows = [
        row
        for row in rows
        if row["mode"] is CampaignRunMode.OPERATOR_OBSERVED_REALTIME
    ]
    realtime_comparisons = all(
        row["mode_comparison"] is not None
        and row["mode_comparison"]["all_gates_passed"]
        for row in realtime_rows
    )
    return {
        "exact_baseline_comparisons_complete": exact_baselines,
        "cross_geometry_stress_comparisons_complete": cross_geometry,
        "repeat_identity_complete": repeat_identity,
        "slow_stress_operating_regions_distinct": operating_region_distinct,
        "realtime_mode_comparisons_complete": realtime_comparisons,
    }


async def _run(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="crazyswarm-altitude-profile-qualification-") as raw:
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
        rows: list[dict[str, Any]] = []
        await runtime.start()
        try:
            for run_mode, case_id, submission_ids in _matrix(args.mode):
                service.set_active(
                    case_id,
                    actor_id="altitude-profile-runtime-qualifier",
                    reason="isolated WP-43 profile qualification",
                )
                for submission_id in submission_ids:
                    for repetition in range(1, args.repetitions + 1):
                        review = await service.run_active(
                            run_mode,
                            idempotency_key=(
                                f"wp43-v1:{run_mode.value}:{case_id}:{submission_id}:"
                                f"repeat-{repetition}"
                            ),
                            submission_id=submission_id,
                        )
                        run = next(
                            item for item in service.state.runs if item.run_id == review.run_id
                        )
                        if run.mission_execution_id is None:
                            raise RuntimeError("qualification run has no mission execution ID")
                        evaluation = _evaluation(service, run.mission_execution_id)
                        vehicles = evaluation.get("vehicles", [])
                        profile_passed = all(
                            vehicle.get("planned_profile_conformance_passed") is not False
                            for vehicle in vehicles
                            if isinstance(vehicle, dict)
                        )
                        row = {
                            "case_id": case_id,
                            "case_sha256": run.locked_inputs.case_sha256,
                            "submission_id": submission_id,
                            "submission_sha256": run.locked_inputs.submission_sha256,
                            "mode": run_mode,
                            "repetition": repetition,
                            "status": review.status,
                            "run_id": run.run_id,
                            "mission_execution_id": run.mission_execution_id,
                            "plan_sha256": run.plan_sha256,
                            "trajectory_set_sha256": run.trajectory_set_sha256,
                            "artifact_set_sha256": review.artifact_set_sha256,
                            "analysis_sha256": review.analysis.analysis_sha256,
                            "evaluation_status": evaluation.get("status"),
                            "evaluation_evidence_complete": evaluation.get(
                                "evidence", {}
                            ).get("complete"),
                            "planned_profile_conformance_passed": profile_passed,
                            "all_required_behavior_oracles_passed": (
                                review.analysis.all_required_behavior_oracles_passed
                            ),
                            "baseline_comparison": review.baseline_comparison,
                            "cross_case_profile_comparison": (
                                review.cross_case_profile_comparison
                            ),
                            "mode_comparison": (
                                review.mode_comparison.model_dump(mode="json")
                                if review.mode_comparison is not None
                                else None
                            ),
                            "vehicle_metrics": vehicles,
                        }
                        rows.append(row)
                        print(
                            case_id,
                            submission_id,
                            run_mode.value,
                            f"repeat={repetition}",
                            review.status.value,
                            flush=True,
                        )
        finally:
            await runtime.stop()

    gates = _qualification_gates(rows)
    passed = all(gates.values()) and all(
        row["status"] == CampaignRunStatus.SUCCEEDED
        and row["evaluation_status"] == "COMPLETE"
        and row["evaluation_evidence_complete"] is True
        and row["planned_profile_conformance_passed"]
        and row["all_required_behavior_oracles_passed"]
        and (
            row["mode"] is not CampaignRunMode.OPERATOR_OBSERVED_REALTIME
            or (
                row["mode_comparison"] is not None
                and row["mode_comparison"]["all_gates_passed"]
            )
        )
        for row in rows
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "qualification_kind": "WP43_ALTITUDE_PROFILE_FAST_SIM_RUNTIME",
        "claim_boundary": (
            "Deterministic software behavior in isolated Fast Sim only; no physical-flight, "
            "live-Isaac, digital-twin, calibrated contact, or constant-rotor claim."
        ),
        "requested_mode": args.mode,
        "repetitions": args.repetitions,
        "run_count": len(rows),
        "qualification_gates": gates,
        "all_runs_and_gates_passed": passed,
        "runs": rows,
    }
    payload["qualification_sha256"] = canonical_sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"altitude profile qualification -> {args.output}", flush=True)
    return 0 if passed else 1


def main() -> int:
    return asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
