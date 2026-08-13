from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import ImplementationStatus
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.service import (
    CampaignRunMode,
    CampaignRunStatus,
    CampaignService,
)
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "missions/campaigns/sim/qualification/catalog-runtime-qualification-v2.json"
REALTIME_ANCHORS = (
    "1d.takeoff_hover_land.canonical_nominal",
    "1d.point_to_point_relocation.canonical_nominal",
    "1d.altitude_transition.canonical_nominal",
    "1d.planar_shape_loop.figure_eight",
    "2d.parallel_routes.canonical_nominal",
    "2d.perpendicular_crossing.nominal_equal_priority",
    "2d.no_hover_crossing.canonical_nominal",
    "2d.leader_follower.canonical_nominal",
    "3d.single_pair_conflict.canonical_nominal",
    "3d.simultaneous_center_conflict.joint_schedule_v2",
    "3d.formation_shape_transform.canonical_nominal",
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute isolated Fast Sim qualification runs for the campaign catalog"
    )
    parser.add_argument(
        "--mode",
        choices=("accelerated", "realtime", "both"),
        default="accelerated",
    )
    parser.add_argument("--case", action="append", dest="case_ids", default=[])
    parser.add_argument("--all-realtime", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _selected_cases(
    catalog: CampaignCatalog,
    *,
    mode: str,
    requested: list[str],
    all_realtime: bool,
) -> tuple[str, ...]:
    executable = tuple(
        case.case_id
        for case in catalog.cases()
        if case.environment.value == "SIMULATION"
        and case.implementation_status is ImplementationStatus.EXECUTABLE
    )
    if requested:
        unknown = sorted(set(requested).difference(executable))
        if unknown:
            raise ValueError(
                "runtime qualification requires executable Simulation cases: " + ", ".join(unknown)
            )
        return tuple(dict.fromkeys(requested))
    if mode in {"realtime", "both"} and not all_realtime:
        return REALTIME_ANCHORS
    return executable


async def _run_case(case_id: str, modes: tuple[CampaignRunMode, ...]) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="crazyswarm-campaign-qualification-") as raw:
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
        rows: list[dict[str, Any]] = []
        try:
            locked = service.set_active(
                case_id,
                actor_id="catalog-runtime-qualifier",
                reason="isolated catalog runtime qualification",
            )
            for mode in modes:
                review = await service.run_active(
                    mode,
                    idempotency_key=f"catalog-runtime-v2:{mode.value}:{case_id}",
                )
                run = next(item for item in service.state.runs if item.run_id == review.run_id)
                row = {
                    "case_id": case_id,
                    "case_sha256": locked.case_sha256,
                    "mode": mode,
                    "status": review.status,
                    "run_id": review.run_id,
                    "mission_execution_id": run.mission_execution_id,
                    "failure_reason": run.failure_reason,
                    "plan_sha256": run.plan_sha256,
                    "schedule_sha256": run.schedule_sha256,
                    "trajectory_set_sha256": run.trajectory_set_sha256,
                    "artifact_set_sha256": review.artifact_set_sha256,
                    "analysis_sha256": review.analysis.analysis_sha256,
                    "review_sha256": review.review_sha256,
                    "all_required_behavior_oracles_passed": (
                        review.analysis.all_required_behavior_oracles_passed
                    ),
                    "behavior_oracles": [
                        result.model_dump(mode="json")
                        for result in review.analysis.behavior_oracles
                    ],
                    "mode_comparison": (
                        review.mode_comparison.model_dump(mode="json")
                        if review.mode_comparison is not None
                        else None
                    ),
                }
                rows.append(row)
                print(
                    case_id,
                    mode.value,
                    review.status.value,
                    "oracles=PASS"
                    if review.analysis.all_required_behavior_oracles_passed
                    else "oracles=FAIL",
                    flush=True,
                )
        finally:
            await runtime.stop()
        return rows


async def _run(args: argparse.Namespace) -> int:
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    case_ids = _selected_cases(
        catalog,
        mode=args.mode,
        requested=args.case_ids,
        all_realtime=args.all_realtime,
    )
    modes = {
        "accelerated": (CampaignRunMode.AUTOMATED_ACCELERATED,),
        "realtime": (CampaignRunMode.OPERATOR_OBSERVED_REALTIME,),
        "both": (
            CampaignRunMode.AUTOMATED_ACCELERATED,
            CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
        ),
    }[args.mode]
    rows: list[dict[str, Any]] = []
    for case_id in case_ids:
        rows.extend(await _run_case(case_id, modes))
    passed = all(
        row["status"] == CampaignRunStatus.SUCCEEDED
        and row["all_required_behavior_oracles_passed"]
        and (
            row["mode_comparison"] is None
            or row["mode_comparison"]["all_gates_passed"]
        )
        for row in rows
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "qualification_kind": "ISOLATED_FAST_SIM_RUNTIME",
        "claim_boundary": (
            "Deterministic software behavior in isolated Fast Sim. This does not claim "
            "physical-flight, live-Isaac, perception, SLAM, or digital-twin qualification."
        ),
        "requested_mode": args.mode,
        "case_count": len(case_ids),
        "run_count": len(rows),
        "all_runs_and_oracles_passed": passed,
        "runs": rows,
    }
    payload["qualification_sha256"] = canonical_sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"runtime qualification -> {args.output}", flush=True)
    return 0 if passed else 1


def main() -> int:
    return asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
