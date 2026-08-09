from __future__ import annotations

from pathlib import Path

import pytest

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.fleet.artifacts import ExecutionBackend
from crazyswarm_app.fleet.planning import MissionDeploymentPlan, plan_mission_deployment
from crazyswarm_app.missions.planning import MissionPlanReceipt, build_mission_plan
from crazyswarm_app.missions.script import MissionFileRecord, parse_python_mission
from crazyswarm_app.planning.deconfliction import (
    ConflictResolutionStrategy,
    DeconflictionStatus,
    plan_crossing_deconfliction,
)
from crazyswarm_app.safety.policy import SafetyPolicy


def _crossing_source(*, reactive: bool = False) -> str:
    source = Path("missions/qualification/crossing_route_separation.py").read_text(encoding="utf-8")
    return (
        source.replace(
            '"task_type": "crossing-route"',
            '"task_type": "crossing-route-reactive"',
        )
        if reactive
        else source
    )


def _deployment(source: str) -> tuple[MissionFileRecord, MissionDeploymentPlan]:
    record = parse_python_mission(
        filename="crossing_route_separation.py",
        name="Crossing route separation",
        source=source,
    )
    return record, plan_mission_deployment(
        record,
        backend=ExecutionBackend.FAST_SIM,
        required_capabilities=frozenset(),
        implicit_vehicle_id="sim01",
        implicit_display_name="Simulation vehicle",
        implicit_home=Vector3(),
        world_minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
        world_maximum_m=Vector3(x=2.0, y=2.0, z=1.0),
    )


async def _plan(source: str) -> MissionPlanReceipt:
    record, deployment = _deployment(source)
    return await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        SafetyPolicy(),
    )


@pytest.mark.asyncio
async def test_crossing_prediction_and_candidate_selection_are_deterministic() -> None:
    first = await _plan(_crossing_source())
    second = await _plan(_crossing_source())

    assert first.sha256 == second.sha256
    assert first.deconfliction is not None
    assert first.deconfliction == second.deconfliction
    plan = first.deconfliction
    assert plan.status is DeconflictionStatus.RESOLVED
    assert plan.selected_strategy is ConflictResolutionStrategy.STAGING_HOLD
    assert plan.conflict is not None
    assert plan.conflict.predicted_minimum_separation_m < 0.01
    assert plan.conflict.required_separation_m == pytest.approx(0.80)
    assert plan.conflict.ends_at_s - plan.conflict.starts_at_s < 10.0
    assert all(
        tube.starts_at_s == plan.conflict.starts_at_s and tube.ends_at_s == plan.conflict.ends_at_s
        for tube in plan.conflict.tubes
    )

    candidates = {item.strategy: item for item in plan.candidates}
    assert candidates[ConflictResolutionStrategy.STAGING_HOLD].feasible is True
    assert candidates[ConflictResolutionStrategy.STAGING_HOLD].planned_hold_s == pytest.approx(
        19.45
    )
    assert candidates[ConflictResolutionStrategy.SPEED_RETIMING].feasible is True
    assert candidates[ConflictResolutionStrategy.HORIZONTAL_DETOUR].feasible is True
    assert candidates[ConflictResolutionStrategy.VERTICAL_SEPARATION].feasible is False
    assert candidates[ConflictResolutionStrategy.COMBINED_RETIMING_VERTICAL].feasible is True
    assert candidates[
        ConflictResolutionStrategy.STAGING_HOLD
    ].predicted_minimum_separation_m == pytest.approx(1.2, abs=0.001)
    assert tuple(program.sha256 for program in first.execution_programs) == (
        plan.selected_program_sha256s
    )


@pytest.mark.asyncio
async def test_no_hover_candidate_set_compares_retiming_and_horizontal_detour() -> None:
    reactive_source = _crossing_source(reactive=True)
    record, reactive_deployment = _deployment(reactive_source)
    base = await build_mission_plan(
        record,
        reactive_deployment.deployment,
        reactive_deployment.assignments,
        SafetyPolicy(),
    )
    crossing_deployment = reactive_deployment.deployment.model_copy(
        update={
            "tasks": tuple(
                task.model_copy(update={"task_type": "crossing-route"})
                for task in reactive_deployment.deployment.tasks
            )
        }
    )

    programs, deconfliction = plan_crossing_deconfliction(
        mission_id=record.mission_id,
        deployment=crossing_deployment,
        programs=base.execution_programs,
        policy=SafetyPolicy(),
        allowed_strategies=(
            ConflictResolutionStrategy.SPEED_RETIMING,
            ConflictResolutionStrategy.HORIZONTAL_DETOUR,
        ),
    )

    assert deconfliction is not None
    assert deconfliction.status is DeconflictionStatus.RESOLVED
    assert deconfliction.selected_strategy is ConflictResolutionStrategy.SPEED_RETIMING
    assert {item.strategy for item in deconfliction.candidates} == {
        ConflictResolutionStrategy.SPEED_RETIMING,
        ConflictResolutionStrategy.HORIZONTAL_DETOUR,
    }
    assert all(item.feasible for item in deconfliction.candidates)
    assert all(item.planned_hold_s == 0.0 for item in deconfliction.candidates)
    assert tuple(program.sha256 for program in programs) == (deconfliction.selected_program_sha256s)
