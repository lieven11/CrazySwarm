from __future__ import annotations

import itertools
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import AcceptedExecutionProgram
from crazyswarm_app.planning.deconfliction import (
    DEFAULT_POSITION_UNCERTAINTY_M,
    STAGING_RELEASE_BUFFER_S,
    delay_program_before_trajectory,
    predict_program_minimum_separation,
    trajectory_schedule_window,
)
from crazyswarm_app.safety.policy import SafetyPolicy

if TYPE_CHECKING:
    from crazyswarm_app.fleet.artifacts import DeploymentManifest


class MultiDronePlanningStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"


class MultiDroneResolutionStrategy(StrEnum):
    EXACT_ENUMERATION_STAGING = "EXACT_ENUMERATION_STAGING"
    PRIORITY_GREEDY_STAGING = "PRIORITY_GREEDY_STAGING"


class MultiDronePairConflict(ContractModel):
    conflict_id: Identifier
    role_ids: tuple[Identifier, Identifier]
    predicted_minimum_separation_m: float = Field(ge=0.0)
    closest_approach_s: float = Field(ge=0.0)
    required_separation_m: float = Field(gt=0.0)


class MultiDroneScheduleCandidate(ContractModel):
    candidate_id: Identifier
    strategy: MultiDroneResolutionStrategy
    precedence_order: tuple[Identifier, ...]
    planned_hold_s_by_role: dict[Identifier, float]
    feasible: bool
    predicted_minimum_separation_m: float | None = Field(default=None, ge=0.0)
    maximum_wait_s: float = Field(ge=0.0)
    total_wait_s: float = Field(ge=0.0)
    fairness_wait_spread_s: float = Field(ge=0.0)
    priority_inversion_penalty: int = Field(ge=0)
    starved_role_ids: tuple[Identifier, ...]
    execution_program_sha256s: tuple[SHA256, ...]
    reason: str


class MultiDroneConflictPlan(ContractModel):
    schema_version: Literal[1] = 1
    deconfliction_id: Identifier
    status: MultiDronePlanningStatus
    role_ids: tuple[Identifier, ...]
    conflicts: tuple[MultiDronePairConflict, ...]
    candidates: tuple[MultiDroneScheduleCandidate, ...]
    selected_strategy: MultiDroneResolutionStrategy | None = None
    selected_candidate_index: int | None = Field(default=None, ge=0)
    selected_program_sha256s: tuple[SHA256, ...]
    exact_enumeration_limit: int = Field(default=4, ge=2)
    starvation_bound_s: float = Field(gt=0.0)
    deadlock_detected: bool
    deadlock_recovery: Literal["LAND_ALL"] = "LAND_ALL"
    optimality_limitation: str
    plan_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"plan_sha256"})


def plan_multi_drone_conflicts(
    *,
    mission_id: str,
    deployment: DeploymentManifest,
    programs: tuple[AcceptedExecutionProgram, ...],
    policy: SafetyPolicy,
    exact_enumeration_limit: int = 4,
) -> tuple[tuple[AcceptedExecutionProgram, ...], MultiDroneConflictPlan | None]:
    task_by_role = {
        task.task_id: task for task in deployment.tasks if task.task_type == "multi-conflict-route"
    }
    if len(task_by_role) < 3:
        return programs, None
    role_ids = tuple(sorted(task_by_role))
    by_role = {program.role_id: program for program in programs}
    starvation_bound_s = min(90.0, policy.max_mission_duration_s / 2.0)
    if set(role_ids) != set(by_role):
        return programs, _blocked_plan(
            mission_id,
            role_ids,
            conflicts=(),
            candidates=(),
            starvation_bound_s=starvation_bound_s,
            exact_enumeration_limit=exact_enumeration_limit,
            reason="multi-conflict roles do not have static accepted programs",
        )
    required = deployment.constraints.warning_separation_m + DEFAULT_POSITION_UNCERTAINTY_M
    conflicts = tuple(
        conflict
        for first_index, first_role in enumerate(role_ids)
        for second_role in role_ids[first_index + 1 :]
        if (
            conflict := _pair_conflict(
                mission_id,
                by_role[first_role],
                by_role[second_role],
                required,
            )
        )
        is not None
    )
    if not conflicts:
        payload: dict[str, object] = {
            "deconfliction_id": f"multi-plan-{canonical_sha256([mission_id, role_ids])[:20]}",
            "status": MultiDronePlanningStatus.NOT_REQUIRED,
            "role_ids": role_ids,
            "conflicts": (),
            "candidates": (),
            "selected_program_sha256s": tuple(program.sha256 for program in programs),
            "exact_enumeration_limit": exact_enumeration_limit,
            "starvation_bound_s": starvation_bound_s,
            "deadlock_detected": False,
            "optimality_limitation": "no conflict resolution was required",
        }
        return programs, MultiDroneConflictPlan(
            **payload,
            plan_sha256=canonical_sha256(payload),
        )

    priorities = {role_id: task_by_role[role_id].priority for role_id in role_ids}
    if len(role_ids) <= exact_enumeration_limit:
        strategy = MultiDroneResolutionStrategy.EXACT_ENUMERATION_STAGING
        orders = tuple(itertools.permutations(role_ids))
        limitation = (
            "globally minimum candidate under the bounded full-route staging model; "
            "not a global optimum over arbitrary continuous trajectories"
        )
    else:
        strategy = MultiDroneResolutionStrategy.PRIORITY_GREEDY_STAGING
        orders = (tuple(sorted(role_ids, key=lambda item: (-priorities[item], item))),)
        limitation = (
            "deterministic O(n^2) priority-greedy full-route staging; no general "
            "optimality guarantee"
        )
    candidates: list[MultiDroneScheduleCandidate] = []
    scheduled_by_index: dict[int, tuple[AcceptedExecutionProgram, ...]] = {}
    for candidate_index, order in enumerate(orders):
        scheduled, candidate = _schedule_candidate(
            candidate_index=candidate_index,
            order=order,
            strategy=strategy,
            base_programs=by_role,
            priorities=priorities,
            required_separation_m=required,
            starvation_bound_s=starvation_bound_s,
            policy=policy,
        )
        candidates.append(candidate)
        scheduled_by_index[candidate_index] = scheduled

    feasible_indexes = [index for index, item in enumerate(candidates) if item.feasible]
    if not feasible_indexes:
        return programs, _blocked_plan(
            mission_id,
            role_ids,
            conflicts=conflicts,
            candidates=tuple(candidates),
            starvation_bound_s=starvation_bound_s,
            exact_enumeration_limit=exact_enumeration_limit,
            reason="joint schedule has deadlock or exceeds the starvation/duration bound",
        )
    selected_index = min(
        feasible_indexes,
        key=lambda index: (
            candidates[index].priority_inversion_penalty,
            candidates[index].maximum_wait_s,
            candidates[index].total_wait_s,
            candidates[index].fairness_wait_spread_s,
            candidates[index].precedence_order,
        ),
    )
    selected_programs = scheduled_by_index[selected_index]
    selected = candidates[selected_index]
    payload = {
        "deconfliction_id": f"multi-plan-{canonical_sha256([mission_id, conflicts])[:20]}",
        "status": MultiDronePlanningStatus.RESOLVED,
        "role_ids": role_ids,
        "conflicts": conflicts,
        "candidates": tuple(candidates),
        "selected_strategy": selected.strategy,
        "selected_candidate_index": selected_index,
        "selected_program_sha256s": tuple(program.sha256 for program in selected_programs),
        "exact_enumeration_limit": exact_enumeration_limit,
        "starvation_bound_s": starvation_bound_s,
        "deadlock_detected": False,
        "optimality_limitation": limitation,
    }
    return selected_programs, MultiDroneConflictPlan(
        **payload,
        plan_sha256=canonical_sha256(payload),
    )


def _pair_conflict(
    mission_id: str,
    first: AcceptedExecutionProgram,
    second: AcceptedExecutionProgram,
    required_separation_m: float,
) -> MultiDronePairConflict | None:
    minimum, closest_s = predict_program_minimum_separation(first, second)
    if minimum >= required_separation_m:
        return None
    role_ids = tuple(sorted((first.role_id, second.role_id)))
    return MultiDronePairConflict(
        conflict_id=(f"multi-conflict-{canonical_sha256([mission_id, role_ids, closest_s])[:20]}"),
        role_ids=(role_ids[0], role_ids[1]),
        predicted_minimum_separation_m=minimum,
        closest_approach_s=closest_s,
        required_separation_m=required_separation_m,
    )


def _schedule_candidate(
    *,
    candidate_index: int,
    order: tuple[str, ...],
    strategy: MultiDroneResolutionStrategy,
    base_programs: dict[str, AcceptedExecutionProgram],
    priorities: dict[str, int],
    required_separation_m: float,
    starvation_bound_s: float,
    policy: SafetyPolicy,
) -> tuple[tuple[AcceptedExecutionProgram, ...], MultiDroneScheduleCandidate]:
    scheduled: dict[str, AcceptedExecutionProgram] = {}
    waits: dict[str, float] = {}
    latest_clear_s = 0.0
    for role_index, role_id in enumerate(order):
        program = base_programs[role_id]
        starts_at_s, _ = trajectory_schedule_window(program)
        wait_s = (
            0.0
            if role_index == 0
            else max(0.0, latest_clear_s - starts_at_s + STAGING_RELEASE_BUFFER_S)
        )
        selected = delay_program_before_trajectory(program, wait_s) if wait_s else program
        scheduled[role_id] = selected
        waits[role_id] = wait_s
        _, selected_end_s = trajectory_schedule_window(selected)
        latest_clear_s = max(latest_clear_s, selected_end_s)

    minimum = float("inf")
    for first_index, first_role in enumerate(order):
        for second_role in order[first_index + 1 :]:
            pair_minimum, _ = predict_program_minimum_separation(
                scheduled[first_role], scheduled[second_role]
            )
            minimum = min(minimum, pair_minimum)
    max_wait = max(waits.values(), default=0.0)
    min_wait = min(waits.values(), default=0.0)
    starved = tuple(
        sorted(role_id for role_id, wait_s in waits.items() if wait_s > starvation_bound_s)
    )
    duration_exceeded = any(
        program.schedule_duration_s > policy.max_mission_duration_s
        for program in scheduled.values()
    )
    inversion_penalty = sum(
        max(0, priorities[later] - priorities[earlier])
        for earlier_index, earlier in enumerate(order)
        for later in order[earlier_index + 1 :]
    )
    feasible = minimum >= required_separation_m and not starved and not duration_exceeded
    ordered_programs = tuple(scheduled[role_id] for role_id in sorted(scheduled))
    return ordered_programs, MultiDroneScheduleCandidate(
        candidate_id=f"multi-candidate-{candidate_index + 1}",
        strategy=strategy,
        precedence_order=order,
        planned_hold_s_by_role=waits,
        feasible=feasible,
        predicted_minimum_separation_m=minimum,
        maximum_wait_s=max_wait,
        total_wait_s=sum(waits.values()),
        fairness_wait_spread_s=max_wait - min_wait,
        priority_inversion_penalty=inversion_penalty,
        starved_role_ids=starved,
        execution_program_sha256s=tuple(program.sha256 for program in ordered_programs),
        reason=(
            "joint conflict graph schedule satisfies separation, duration, and starvation bounds"
            if feasible
            else "joint schedule violates separation, duration, or starvation bounds"
        ),
    )


def _blocked_plan(
    mission_id: str,
    role_ids: tuple[str, ...],
    *,
    conflicts: tuple[MultiDronePairConflict, ...],
    candidates: tuple[MultiDroneScheduleCandidate, ...],
    starvation_bound_s: float,
    exact_enumeration_limit: int,
    reason: str,
) -> MultiDroneConflictPlan:
    payload = {
        "deconfliction_id": f"multi-plan-{canonical_sha256([mission_id, reason])[:20]}",
        "status": MultiDronePlanningStatus.BLOCKED,
        "role_ids": role_ids,
        "conflicts": conflicts,
        "candidates": candidates,
        "selected_program_sha256s": (),
        "exact_enumeration_limit": exact_enumeration_limit,
        "starvation_bound_s": starvation_bound_s,
        "deadlock_detected": True,
        "optimality_limitation": reason,
    }
    return MultiDroneConflictPlan(
        **payload,
        plan_sha256=canonical_sha256(payload),
    )
