from __future__ import annotations

from pathlib import Path

import pytest

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.fleet.artifacts import ExecutionBackend
from crazyswarm_app.fleet.planning import MissionDeploymentPlan, plan_mission_deployment
from crazyswarm_app.missions.planning import MissionPlanReceipt, build_mission_plan
from crazyswarm_app.missions.script import MissionFileRecord, parse_python_mission
from crazyswarm_app.planning.multidrone import (
    MultiDroneConflictPlan,
    MultiDronePlanningStatus,
    MultiDroneResolutionStrategy,
    plan_multi_drone_conflicts,
)
from crazyswarm_app.planning.multidrone_cases import (
    MultiDroneCaseVariant,
    generate_multi_drone_cases,
)
from crazyswarm_app.safety.policy import SafetyPolicy


def _components() -> tuple[MissionFileRecord, MissionDeploymentPlan]:
    path = Path("missions/qualification/three_drone_multi_conflict.py")
    record = parse_python_mission(
        filename=path.name,
        name="Three drone multi conflict",
        source=path.read_text(encoding="utf-8"),
    )
    deployment = plan_mission_deployment(
        record,
        backend=ExecutionBackend.FAST_SIM,
        required_capabilities=frozenset(),
        implicit_vehicle_id="sim01",
        implicit_display_name="Simulation vehicle",
        implicit_home=Vector3(),
        world_minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
        world_maximum_m=Vector3(x=2.0, y=2.0, z=1.0),
    )
    return record, deployment


async def _plan(policy: SafetyPolicy | None = None) -> MissionPlanReceipt:
    record, deployment = _components()
    return await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        policy or SafetyPolicy(),
    )


@pytest.mark.asyncio
async def test_three_drone_joint_schedule_is_exact_priority_fair_and_deterministic() -> None:
    first = await _plan()
    second = await _plan()

    assert first.sha256 == second.sha256
    assert isinstance(first.deconfliction, MultiDroneConflictPlan)
    conflict_plan = first.deconfliction
    assert conflict_plan == second.deconfliction
    assert conflict_plan.status is MultiDronePlanningStatus.RESOLVED
    assert conflict_plan.selected_strategy is MultiDroneResolutionStrategy.EXACT_ENUMERATION_STAGING
    assert len(conflict_plan.conflicts) == 3
    assert len(conflict_plan.candidates) == 6
    assert conflict_plan.deadlock_detected is False
    selected_index = conflict_plan.selected_candidate_index
    assert selected_index is not None
    selected = conflict_plan.candidates[selected_index]
    assert selected.precedence_order == ("route_alpha", "route_beta", "route_gamma")
    assert selected.planned_hold_s_by_role == pytest.approx(
        {"route_alpha": 0.0, "route_beta": 19.45, "route_gamma": 38.90}
    )
    assert selected.priority_inversion_penalty == 0
    assert selected.maximum_wait_s < conflict_plan.starvation_bound_s
    assert selected.starved_role_ids == ()
    assert selected.predicted_minimum_separation_m is not None
    assert selected.predicted_minimum_separation_m >= 0.8
    assert tuple(program.sha256 for program in first.execution_programs) == (
        conflict_plan.selected_program_sha256s
    )


@pytest.mark.asyncio
async def test_joint_scheduler_fails_closed_when_duration_and_starvation_bounds_conflict() -> None:
    plan = await _plan(SafetyPolicy(max_mission_duration_s=60.0))

    assert isinstance(plan.deconfliction, MultiDroneConflictPlan)
    assert plan.deconfliction.status is MultiDronePlanningStatus.BLOCKED
    assert plan.deconfliction.deadlock_detected is True
    assert plan.deconfliction.deadlock_recovery == "LAND_ALL"
    assert plan.deconfliction.selected_program_sha256s == ()
    assert plan.status.value == "BLOCKED"
    assert any(item.code == "PREDICTIVE_DECONFLICTION_BLOCKED" for item in plan.findings)
    assert all(not item.feasible for item in plan.deconfliction.candidates)
    assert all(item.starved_role_ids for item in plan.deconfliction.candidates)


@pytest.mark.asyncio
async def test_above_exact_bound_uses_one_named_deterministic_greedy_candidate() -> None:
    record, deployment = _components()
    raw_deployment = deployment.deployment.model_copy(
        update={
            "tasks": tuple(
                task.model_copy(update={"task_type": "unplanned-route"})
                for task in deployment.deployment.tasks
            )
        }
    )
    base = await build_mission_plan(
        record,
        raw_deployment,
        deployment.assignments,
        SafetyPolicy(),
    )
    assert base.deconfliction is None

    _, result = plan_multi_drone_conflicts(
        mission_id=record.mission_id,
        deployment=deployment.deployment,
        programs=base.execution_programs,
        policy=SafetyPolicy(),
        exact_enumeration_limit=2,
    )

    assert result is not None
    assert len(result.candidates) <= 1
    if result.candidates:
        assert result.candidates[0].strategy is MultiDroneResolutionStrategy.PRIORITY_GREEDY_STAGING
    assert "priority-greedy" in result.optimality_limitation


@pytest.mark.asyncio
async def test_declared_multi_conflict_variants_compile_inside_their_borders() -> None:
    cases = generate_multi_drone_cases()
    assert {case.variant for case in cases} == set(MultiDroneCaseVariant)
    assert len({case.case_sha256 for case in cases}) == len(cases) == 5

    for case in cases:
        record = parse_python_mission(
            filename=case.mission_filename,
            name=case.variant.value,
            source=case.mission_source,
        )
        assert record.source_sha256 == case.mission_source_sha256
        deployment = plan_mission_deployment(
            record,
            backend=ExecutionBackend.FAST_SIM,
            required_capabilities=frozenset(),
            implicit_vehicle_id="sim01",
            implicit_display_name="Simulation vehicle",
            implicit_home=Vector3(),
            world_minimum_m=case.flight_volume.minimum_m,
            world_maximum_m=case.flight_volume.maximum_m,
        )
        plan = await build_mission_plan(
            record,
            deployment.deployment,
            deployment.assignments,
            SafetyPolicy(flight_volume=case.flight_volume),
        )

        assert plan.status.value == "APPROVED"
        assert isinstance(plan.deconfliction, MultiDroneConflictPlan)
        conflict_plan = plan.deconfliction
        assert conflict_plan.status is MultiDronePlanningStatus.RESOLVED
        assert len(conflict_plan.conflicts) == case.expected_pair_conflicts
        selected_index = conflict_plan.selected_candidate_index
        assert selected_index is not None
        selected = conflict_plan.candidates[selected_index]
        assert selected.maximum_wait_s <= case.maximum_planned_wait_s
        assert selected.predicted_minimum_separation_m is not None
        assert selected.predicted_minimum_separation_m >= case.minimum_predicted_separation_m
        assert selected.starved_role_ids == ()
        assert all(
            case.flight_volume.contains(point.position_m)
            for program in plan.execution_programs
            for operation in program.operations
            if operation.kind == "trajectory"
            for point in operation.trajectory.points
        )
