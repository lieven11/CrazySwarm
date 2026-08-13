from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.execution import compile_campaign_execution_programs
from crazyswarm_app.campaign.models import ImplementationStatus
from crazyswarm_app.campaign.planner import BoundedJointPlanner, PlanningStatus
from crazyswarm_app.campaign.scenario import compile_scenario_trace
from crazyswarm_app.campaign.scheduling import build_ground_first_schedule
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.simulation import canonical_sha256


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed static qualification of every active campaign case"
    )
    parser.add_argument("--catalog", type=Path, default=Path("missions/campaigns/sim/cases"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("missions/campaigns/sim/qualification/catalog-static-qualification-v2.json"),
    )
    args = parser.parse_args()
    catalog = CampaignCatalog(args.catalog)
    catalog.discover()
    audit_by_case = {item.case_id: item for item in catalog.semantic_audits()}
    planner = BoundedJointPlanner()
    case_rows: list[dict[str, Any]] = []
    for case in catalog.cases():
        plan = planner.plan(case)
        if plan.status is not PlanningStatus.READY or plan.selected is None:
            if case.implementation_status is ImplementationStatus.EXECUTABLE:
                raise RuntimeError(f"static qualification blocked for {case.case_id}")
            scenario = compile_scenario_trace(case)
            case_rows.append(
                {
                    "case_id": case.case_id,
                    "case_sha256": case.case_sha256,
                    "execution_semantics_sha256": case.execution_semantics_sha256,
                    "implementation_status": case.implementation_status,
                    "execution_eligibility": case.execution_eligibility,
                    "semantic_classification": audit_by_case[case.case_id].classification,
                    "planning_status": plan.status,
                    "blocking_reason": plan.blocking_reason,
                    "plan_sha256": plan.plan_sha256,
                    "selected_candidate_sha256": None,
                    "selected_strategy": None,
                    "schedule_sha256": None,
                    "trajectory_set_sha256": None,
                    "execution_program_sha256s": [],
                    "scenario_trace_sha256": scenario.trace_sha256,
                    "behavior_oracle_ids": [
                        oracle.oracle_id
                        for oracle in (
                            case.semantics.behavior_oracles if case.semantics is not None else ()
                        )
                    ],
                    "accelerated_execution": "NOT_AUTHORIZED_FOR_QUARANTINED_DEFINITION",
                    "realtime_execution": "NOT_AUTHORIZED_FOR_QUARANTINED_DEFINITION",
                }
            )
            continue
        schedule = build_ground_first_schedule(case, plan.selected)
        trajectories = generate_smooth_trajectories(case, plan.selected)
        programs = compile_campaign_execution_programs(
            case=case,
            plan=plan,
            schedule=schedule,
            trajectories=trajectories,
            mission_source_sha256=case.case_sha256,
        )
        scenario = compile_scenario_trace(case)
        if not scenario.all_expected_dispositions_observed:
            raise RuntimeError(f"scenario qualification failed for {case.case_id}")
        case_rows.append(
            {
                "case_id": case.case_id,
                "case_sha256": case.case_sha256,
                "execution_semantics_sha256": case.execution_semantics_sha256,
                "implementation_status": case.implementation_status,
                "execution_eligibility": case.execution_eligibility,
                "semantic_classification": audit_by_case[case.case_id].classification,
                "planning_status": plan.status,
                "blocking_reason": None,
                "plan_sha256": plan.plan_sha256,
                "selected_candidate_sha256": plan.selected.candidate_sha256,
                "selected_strategy": plan.selected.strategy,
                "schedule_sha256": schedule.schedule_sha256,
                "trajectory_set_sha256": trajectories.set_sha256,
                "execution_program_sha256s": [program.sha256 for program in programs],
                "scenario_trace_sha256": scenario.trace_sha256,
                "behavior_oracle_ids": [
                    oracle.oracle_id
                    for oracle in (
                        case.semantics.behavior_oracles if case.semantics is not None else ()
                    )
                ],
                "accelerated_execution": "NOT_RUN_BY_STATIC_QUALIFIER",
                "realtime_execution": "NOT_RUN_BY_STATIC_QUALIFIER",
            }
        )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "qualification_kind": "FAIL_CLOSED_STATIC_COMPILATION",
        "claim_boundary": (
            "All catalog definitions parse, receive a semantic classification, admit a "
            "bounded-plan result, and reduce their scenario contract. Every executable case "
            "also admits a plan, schedule, smooth trajectory set, and accepted execution "
            "program. Quarantined definitions may retain an explicit blocked plan and receive "
            "no runtime authority. Scenario reduction is not live source-time event injection. "
            "This artifact does not claim a Fast Sim run."
        ),
        "case_count": len(case_rows),
        "executable_case_count": sum(
            row["implementation_status"] == "EXECUTABLE" for row in case_rows
        ),
        "quarantined_case_count": sum(
            row["implementation_status"] == "PLANNED_NOT_EXECUTABLE" for row in case_rows
        ),
        "planned_blocked_case_count": sum(row["planning_status"] == "BLOCKED" for row in case_rows),
        "cases": case_rows,
    }
    payload["qualification_sha256"] = canonical_sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"qualified {len(case_rows)} cases -> {args.output} ({payload['qualification_sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
