from __future__ import annotations

import pytest

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.fleet.artifacts import ExecutionBackend
from crazyswarm_app.fleet.planning import MissionDeploymentPlan, plan_mission_deployment
from crazyswarm_app.missions.planning import (
    MissionPlanReceipt,
    MissionPlanStatus,
    build_mission_plan,
)
from crazyswarm_app.missions.script import MissionFileRecord, parse_python_mission
from crazyswarm_app.observability.evaluation import (
    EvidenceCompleteness,
    FleetExecutionMetrics,
    MissionExecutionEvaluation,
    VehicleExecutionMetrics,
)
from crazyswarm_app.planning.curriculum import (
    BorderVariant,
    MissionCaseDefinition,
    MissionCaseTemplate,
    generate_progressive_curriculum,
    promote_curriculum,
)
from crazyswarm_app.planning.deconfliction import ConflictResolutionStrategy


async def _compile_case(
    case: MissionCaseDefinition,
) -> tuple[MissionFileRecord, MissionDeploymentPlan, MissionPlanReceipt]:
    record = parse_python_mission(
        filename=case.mission_filename,
        name=case.case_id,
        source=case.mission_source,
    )
    deployment = plan_mission_deployment(
        record,
        backend=ExecutionBackend.FAST_SIM,
        required_capabilities=frozenset(),
        implicit_vehicle_id="case-primary",
        implicit_display_name="Curriculum case vehicle",
        implicit_home=Vector3(),
        world_minimum_m=case.flight_volume.minimum_m,
        world_maximum_m=case.flight_volume.maximum_m,
    )
    plan = await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        case.safety_policy(),
    )
    return record, deployment, plan


def _passing_evaluation(case: MissionCaseDefinition) -> MissionExecutionEvaluation:
    strategy = case.thresholds.required_deconfliction_strategy
    vehicles = tuple(
        VehicleExecutionMetrics(
            vehicle_id=f"case-vehicle-{index}",
            run_ids=(f"case-run-{index}",),
            telemetry_sample_count=10,
            command_count=4,
            acknowledgement_count=4,
            unintended_stop_count=0,
            declared_hold_count=(1 if strategy is ConflictResolutionStrategy.STAGING_HOLD else 0),
            declared_hold_duration_s=(
                1.0 if strategy is ConflictResolutionStrategy.STAGING_HOLD else 0.0
            ),
            trajectory_command_count=1,
            accepted_plan_identity_match=True,
            trajectory_generation_unintended_stop_count=0,
            landing_goal_id=f"landing-goal-{index}",
            goal_capture_attempt_count=1,
            descent_authorized=True,
            terminal_goal_capture_margin_m=0.05,
            terminal_contact="SIMULATED_GROUND_CONTACT",
        )
        for index in range(case.role_count)
    )
    fleet = FleetExecutionMetrics(
        vehicle_count=case.role_count,
        warning_sample_count=0,
        critical_sample_count=0,
        minimum_truth_separation_m=(1.0 if case.role_count > 1 else None),
        selected_deconfliction_strategy=strategy.value if strategy is not None else None,
        nominal_deconfliction_executed=True if strategy is not None else None,
    )
    payload = {
        "mission_execution_id": f"execution-{case.case_id}",
        "status": "COMPLETE",
        "evidence": EvidenceCompleteness(
            complete=True,
            present=("accepted_plan", "commands", "telemetry", "terminal_runs"),
            missing=(),
        ),
        "run_ids": tuple(item.run_ids[0] for item in vehicles),
        "vehicle_ids": tuple(item.vehicle_id for item in vehicles),
        "vehicles": vehicles,
        "fleet": fleet,
        "summary": ("Evidence is complete.",),
    }
    return MissionExecutionEvaluation(
        **payload,
        report_sha256=canonical_sha256(payload),
    )


@pytest.mark.asyncio
async def test_levels_one_through_five_generate_and_compile_every_declared_variant() -> None:
    first = generate_progressive_curriculum()
    second = generate_progressive_curriculum()

    assert first == second
    assert len(first.cases) == 30
    assert {item.level for item in first.cases} == {1, 2, 3, 4, 5}
    assert {item.border_variant for item in first.cases} == set(BorderVariant)
    assert {item.seed for item in first.cases} == {109, 811}
    assert len({item.case_sha256 for item in first.cases}) == 30

    for case in first.cases:
        record, deployment, plan = await _compile_case(case)
        assert record.source_sha256 == case.mission_source_sha256
        assert deployment.deployment.constraints.warning_separation_m == 0.75
        assert plan.status is MissionPlanStatus.APPROVED
        assert len(plan.execution_programs) == case.role_count
        assert plan.safety.flight_volume_minimum_m == case.flight_volume.minimum_m
        assert plan.safety.flight_volume_maximum_m == case.flight_volume.maximum_m
        if case.template in {
            MissionCaseTemplate.STAGED_CROSSING,
            MissionCaseTemplate.NO_HOVER_CROSSING,
        }:
            assert plan.deconfliction is not None
            assert (
                plan.deconfliction.selected_strategy
                is case.thresholds.required_deconfliction_strategy
            )
        else:
            assert plan.deconfliction is None


@pytest.mark.asyncio
async def test_no_hover_template_excludes_hold_and_admits_continuous_resolution() -> None:
    case = next(
        item
        for item in generate_progressive_curriculum(seeds=(109,)).cases
        if item.template is MissionCaseTemplate.NO_HOVER_CROSSING
        and item.border_variant is BorderVariant.NOMINAL
    )
    record, _, plan = await _compile_case(case)

    assert record.package is not None
    assert record.package.planned_hold_permitted is False
    assert record.package.deconfliction_strategies == (
        "SPEED_RETIMING",
        "HORIZONTAL_DETOUR",
    )
    assert plan.deconfliction is not None
    assert plan.deconfliction.selected_strategy is ConflictResolutionStrategy.SPEED_RETIMING
    assert all(
        item.strategy is not ConflictResolutionStrategy.STAGING_HOLD
        for item in plan.deconfliction.candidates
    )
    assert all(item.planned_hold_s == 0.0 for item in plan.deconfliction.candidates)


def test_promotion_retains_evaluator_baselines_and_blocks_higher_levels_on_regression() -> None:
    manifest = generate_progressive_curriculum()
    reports = {item.case_sha256: _passing_evaluation(item) for item in manifest.cases}

    promoted = promote_curriculum(manifest, reports)

    assert promoted.passed is True
    assert promoted.promoted_levels == (1, 2, 3, 4, 5)
    assert promoted.blocked_level is None
    assert len(promoted.baselines) == len(manifest.cases)
    assert all(item.hard_gates_passed for item in promoted.baselines)
    assert len({item.baseline_sha256 for item in promoted.baselines}) == len(manifest.cases)

    regressed_case = next(item for item in manifest.cases if item.level == 2)
    report = reports[regressed_case.case_sha256]
    regressed_fleet = report.fleet.model_copy(update={"critical_sample_count": 1})
    report_payload = report.model_dump(mode="python", exclude={"report_sha256"})
    report_payload["fleet"] = regressed_fleet
    reports[regressed_case.case_sha256] = MissionExecutionEvaluation(
        **report_payload,
        report_sha256=canonical_sha256(report_payload),
    )

    blocked = promote_curriculum(manifest, reports)

    assert blocked.passed is False
    assert blocked.promoted_levels == (1,)
    assert blocked.blocked_level == 2
    assert blocked.failed_case_sha256s == (regressed_case.case_sha256,)
