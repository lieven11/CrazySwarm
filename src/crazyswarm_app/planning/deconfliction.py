from __future__ import annotations

import math
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import (
    AcceptedExecutionProgram,
    ExecutionOperation,
    GroundWaitExecutionOperation,
    HoldExecutionOperation,
    TrajectoryExecutionOperation,
    TrajectoryPoint,
    sample_trajectory,
)
from crazyswarm_app.safety.policy import SafetyPolicy

if TYPE_CHECKING:
    from crazyswarm_app.fleet.artifacts import DeploymentManifest

PREDICTION_STEP_S = 0.02
DEFAULT_POSITION_UNCERTAINTY_M = 0.05
STAGING_RELEASE_BUFFER_S = 0.25


class ConflictResolutionStrategy(StrEnum):
    STAGING_HOLD = "STAGING_HOLD"
    SPEED_RETIMING = "SPEED_RETIMING"
    HORIZONTAL_DETOUR = "HORIZONTAL_DETOUR"
    VERTICAL_SEPARATION = "VERTICAL_SEPARATION"
    COMBINED_RETIMING_VERTICAL = "COMBINED_RETIMING_VERTICAL"


class DeconflictionStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"


class TrajectoryTubeReservation(ContractModel):
    reservation_id: Identifier
    role_id: Identifier
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(gt=0.0)
    minimum_m: Vector3
    maximum_m: Vector3
    uncertainty_radius_m: float = Field(ge=0.0)

    @model_validator(mode="after")
    def ordered(self) -> TrajectoryTubeReservation:
        if self.ends_at_s <= self.starts_at_s:
            raise ValueError("trajectory tube reservation requires positive duration")
        if not (
            self.minimum_m.x <= self.maximum_m.x
            and self.minimum_m.y <= self.maximum_m.y
            and self.minimum_m.z <= self.maximum_m.z
        ):
            raise ValueError("trajectory tube reservation bounds are reversed")
        return self


class PredictedConflict(ContractModel):
    conflict_id: Identifier
    role_ids: tuple[Identifier, Identifier]
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(gt=0.0)
    closest_approach_s: float = Field(ge=0.0)
    predicted_minimum_separation_m: float = Field(ge=0.0)
    required_separation_m: float = Field(gt=0.0)
    warning_separation_m: float = Field(gt=0.0)
    uncertainty_margin_m: float = Field(ge=0.0)
    tubes: tuple[TrajectoryTubeReservation, TrajectoryTubeReservation]


class ResolutionCandidate(ContractModel):
    strategy: ConflictResolutionStrategy
    feasible: bool
    precedence_role_id: Identifier | None = None
    held_role_id: Identifier | None = None
    staging_point_m: Vector3 | None = None
    planned_hold_s: float = Field(default=0.0, ge=0.0)
    retiming_factor: float | None = Field(default=None, ge=1.0)
    horizontal_detour_m: float | None = None
    vertical_offset_m: float | None = None
    predicted_minimum_separation_m: float | None = Field(default=None, ge=0.0)
    added_duration_s: float = Field(default=0.0, ge=0.0)
    added_path_length_m: float = Field(default=0.0, ge=0.0)
    execution_program_sha256: SHA256 | None = None
    reason: str


class FleetDeconflictionPlan(ContractModel):
    schema_version: Literal[1] = 1
    deconfliction_id: Identifier
    status: DeconflictionStatus
    conflict: PredictedConflict | None = None
    candidates: tuple[ResolutionCandidate, ...]
    selected_strategy: ConflictResolutionStrategy | None = None
    selected_candidate_index: int | None = Field(default=None, ge=0)
    selected_program_sha256s: tuple[SHA256, ...] = ()
    deterministic_tie_break: Literal["FEASIBLE_THEN_DECLARED_ORDER_THEN_COST_THEN_ROLE_ID"] = (
        "FEASIBLE_THEN_DECLARED_ORDER_THEN_COST_THEN_ROLE_ID"
    )
    plan_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"plan_sha256"})


def plan_crossing_deconfliction(
    *,
    mission_id: str,
    deployment: DeploymentManifest,
    programs: tuple[AcceptedExecutionProgram, ...],
    policy: SafetyPolicy,
    allowed_strategies: tuple[ConflictResolutionStrategy, ...] = tuple(ConflictResolutionStrategy),
) -> tuple[tuple[AcceptedExecutionProgram, ...], FleetDeconflictionPlan | None]:
    crossing_tasks = {
        task.task_id: task for task in deployment.tasks if task.task_type == "crossing-route"
    }
    if len(crossing_tasks) != 2:
        return programs, None
    by_role = {program.role_id: program for program in programs}
    ordered_role_ids = sorted(crossing_tasks)
    role_ids = (ordered_role_ids[0], ordered_role_ids[1])
    if set(role_ids) != set(by_role):
        return programs, _blocked_plan(
            mission_id,
            candidates=(),
            reason="crossing roles do not have static accepted execution programs",
        )
    if any(len(_trajectory_operations(by_role[role_id])) != 1 for role_id in role_ids):
        return programs, _blocked_plan(
            mission_id,
            candidates=(),
            reason="crossing deconfliction requires one continuous trajectory per role",
        )

    first = by_role[role_ids[0]]
    second = by_role[role_ids[1]]
    warning = deployment.constraints.warning_separation_m
    uncertainty = DEFAULT_POSITION_UNCERTAINTY_M
    required = warning + uncertainty
    predicted = _prediction(first, second, required)
    if predicted.minimum_separation_m >= required:
        payload: dict[str, object] = {
            "deconfliction_id": f"deconfliction-{canonical_sha256([mission_id, role_ids])[:20]}",
            "status": DeconflictionStatus.NOT_REQUIRED,
            "candidates": (),
            "selected_program_sha256s": tuple(program.sha256 for program in programs),
        }
        return programs, FleetDeconflictionPlan(
            **payload,
            plan_sha256=canonical_sha256(payload),
        )

    conflict = _conflict_contract(
        mission_id=mission_id,
        role_ids=role_ids,
        first=first,
        second=second,
        prediction=predicted,
        warning_separation_m=warning,
        required_separation_m=required,
        uncertainty_m=uncertainty,
    )
    precedence = min(
        role_ids,
        key=lambda role_id: (-crossing_tasks[role_id].priority, role_id),
    )
    held = next(role_id for role_id in role_ids if role_id != precedence)
    candidates: list[ResolutionCandidate] = []
    candidate_programs: dict[ConflictResolutionStrategy, tuple[AcceptedExecutionProgram, ...]] = {}

    if ConflictResolutionStrategy.STAGING_HOLD in allowed_strategies:
        transformed, candidate = _staging_candidate(
            programs,
            precedence_role_id=precedence,
            held_role_id=held,
            required_separation_m=required,
            policy=policy,
        )
        candidates.append(candidate)
        if candidate.feasible:
            candidate_programs[candidate.strategy] = transformed

    if ConflictResolutionStrategy.SPEED_RETIMING in allowed_strategies:
        transformed, candidate = _retiming_candidate(
            programs,
            precedence_role_id=precedence,
            retimed_role_id=held,
            required_separation_m=required,
            policy=policy,
        )
        candidates.append(candidate)
        if candidate.feasible:
            candidate_programs[candidate.strategy] = transformed

    if ConflictResolutionStrategy.HORIZONTAL_DETOUR in allowed_strategies:
        transformed, candidate = _horizontal_candidate(
            programs,
            precedence_role_id=precedence,
            detour_role_id=held,
            required_separation_m=required,
            policy=policy,
        )
        candidates.append(candidate)
        if candidate.feasible:
            candidate_programs[candidate.strategy] = transformed

    if ConflictResolutionStrategy.VERTICAL_SEPARATION in allowed_strategies:
        transformed, candidate = _vertical_candidate(
            programs,
            precedence_role_id=precedence,
            shifted_role_id=held,
            required_separation_m=required,
            policy=policy,
        )
        candidates.append(candidate)
        if candidate.feasible:
            candidate_programs[candidate.strategy] = transformed

    if ConflictResolutionStrategy.COMBINED_RETIMING_VERTICAL in allowed_strategies:
        transformed, candidate = _combined_candidate(
            programs,
            precedence_role_id=precedence,
            shifted_role_id=held,
            required_separation_m=required,
            policy=policy,
        )
        candidates.append(candidate)
        if candidate.feasible:
            candidate_programs[candidate.strategy] = transformed

    selected_index = next(
        (index for index, item in enumerate(candidates) if item.feasible),
        None,
    )
    if selected_index is None:
        return programs, _blocked_plan(
            mission_id,
            candidates=tuple(candidates),
            reason="no deterministic two-drone resolution candidate is feasible",
            conflict=conflict,
        )
    selected = candidates[selected_index]
    selected_programs = candidate_programs[selected.strategy]
    payload = {
        "deconfliction_id": f"deconfliction-{canonical_sha256([mission_id, conflict])[:20]}",
        "status": DeconflictionStatus.RESOLVED,
        "conflict": conflict,
        "candidates": tuple(candidates),
        "selected_strategy": selected.strategy,
        "selected_candidate_index": selected_index,
        "selected_program_sha256s": tuple(program.sha256 for program in selected_programs),
    }
    return selected_programs, FleetDeconflictionPlan(
        **payload,
        plan_sha256=canonical_sha256(payload),
    )


def predict_program_minimum_separation(
    first: AcceptedExecutionProgram,
    second: AcceptedExecutionProgram,
) -> tuple[float, float]:
    prediction = _prediction(first, second, 0.001)
    return prediction.minimum_separation_m, prediction.closest_approach_s


def delay_program_before_trajectory(
    program: AcceptedExecutionProgram,
    delay_s: float,
) -> AcceptedExecutionProgram:
    return _delay_before_launch(program, delay_s)


def trajectory_schedule_window(
    program: AcceptedExecutionProgram,
) -> tuple[float, float]:
    operation = _trajectory_operations(program)[0]
    return operation.starts_at_s, operation.ends_at_s


class _Prediction:
    def __init__(
        self,
        minimum_separation_m: float,
        closest_approach_s: float,
        conflict_start_s: float | None,
        conflict_end_s: float | None,
    ) -> None:
        self.minimum_separation_m = minimum_separation_m
        self.closest_approach_s = closest_approach_s
        self.conflict_start_s = conflict_start_s
        self.conflict_end_s = conflict_end_s


def _prediction(
    first: AcceptedExecutionProgram,
    second: AcceptedExecutionProgram,
    required_separation_m: float,
) -> _Prediction:
    duration_s = max(first.schedule_duration_s, second.schedule_duration_s)
    sample_count = max(1, math.ceil(duration_s / PREDICTION_STEP_S))
    minimum = float("inf")
    closest_s = 0.0
    conflict_times: list[float] = []
    for index in range(sample_count + 1):
        time_s = min(duration_s, index * duration_s / sample_count)
        distance = _distance(
            _program_position(first, time_s),
            _program_position(second, time_s),
        )
        if distance < minimum:
            minimum = distance
            closest_s = time_s
        if distance < required_separation_m:
            conflict_times.append(time_s)
    return _Prediction(
        minimum,
        closest_s,
        min(conflict_times) if conflict_times else None,
        max(conflict_times) if conflict_times else None,
    )


def _program_position(program: AcceptedExecutionProgram, time_s: float) -> Vector3:
    trajectory_operation = _trajectory_operations(program)[0]
    if time_s <= trajectory_operation.starts_at_s:
        return trajectory_operation.trajectory.points[0].position_m
    if time_s >= trajectory_operation.ends_at_s:
        return trajectory_operation.trajectory.points[-1].position_m
    return sample_trajectory(
        trajectory_operation.trajectory,
        time_s - trajectory_operation.starts_at_s,
    ).position_m


def _conflict_contract(
    *,
    mission_id: str,
    role_ids: tuple[str, str],
    first: AcceptedExecutionProgram,
    second: AcceptedExecutionProgram,
    prediction: _Prediction,
    warning_separation_m: float,
    required_separation_m: float,
    uncertainty_m: float,
) -> PredictedConflict:
    start_s = prediction.conflict_start_s or prediction.closest_approach_s
    end_s = prediction.conflict_end_s or (start_s + PREDICTION_STEP_S)
    if end_s <= start_s:
        end_s = start_s + PREDICTION_STEP_S
    conflict_id = f"conflict-{canonical_sha256([mission_id, role_ids, start_s, end_s])[:20]}"
    return PredictedConflict(
        conflict_id=conflict_id,
        role_ids=role_ids,
        starts_at_s=start_s,
        ends_at_s=end_s,
        closest_approach_s=prediction.closest_approach_s,
        predicted_minimum_separation_m=prediction.minimum_separation_m,
        required_separation_m=required_separation_m,
        warning_separation_m=warning_separation_m,
        uncertainty_margin_m=uncertainty_m,
        tubes=(
            _tube(conflict_id, first, start_s, end_s, uncertainty_m),
            _tube(conflict_id, second, start_s, end_s, uncertainty_m),
        ),
    )


def _tube(
    conflict_id: str,
    program: AcceptedExecutionProgram,
    starts_at_s: float,
    ends_at_s: float,
    uncertainty_m: float,
) -> TrajectoryTubeReservation:
    middle_s = (starts_at_s + ends_at_s) / 2.0
    positions = tuple(
        _program_position(program, sample_s) for sample_s in (starts_at_s, middle_s, ends_at_s)
    )
    return TrajectoryTubeReservation(
        reservation_id=f"tube-{conflict_id}-{program.role_id}",
        role_id=program.role_id,
        starts_at_s=starts_at_s,
        ends_at_s=ends_at_s,
        minimum_m=Vector3(
            x=min(item.x for item in positions) - uncertainty_m,
            y=min(item.y for item in positions) - uncertainty_m,
            z=min(item.z for item in positions) - uncertainty_m,
        ),
        maximum_m=Vector3(
            x=max(item.x for item in positions) + uncertainty_m,
            y=max(item.y for item in positions) + uncertainty_m,
            z=max(item.z for item in positions) + uncertainty_m,
        ),
        uncertainty_radius_m=uncertainty_m,
    )


def _staging_candidate(
    programs: tuple[AcceptedExecutionProgram, ...],
    *,
    precedence_role_id: str,
    held_role_id: str,
    required_separation_m: float,
    policy: SafetyPolicy,
) -> tuple[tuple[AcceptedExecutionProgram, ...], ResolutionCandidate]:
    by_role = {program.role_id: program for program in programs}
    precedence_trajectory = _trajectory_operations(by_role[precedence_role_id])[0]
    held_trajectory = _trajectory_operations(by_role[held_role_id])[0]
    delay_s = max(
        0.0,
        precedence_trajectory.ends_at_s - held_trajectory.starts_at_s + STAGING_RELEASE_BUFFER_S,
    )
    delayed = _delay_before_trajectory(by_role[held_role_id], delay_s)
    transformed = tuple(
        delayed if program.role_id == held_role_id else program for program in programs
    )
    prediction = _prediction(transformed[0], transformed[1], required_separation_m)
    feasible = (
        prediction.minimum_separation_m >= required_separation_m
        and delayed.schedule_duration_s <= policy.max_mission_duration_s
    )
    return transformed, ResolutionCandidate(
        strategy=ConflictResolutionStrategy.STAGING_HOLD,
        feasible=feasible,
        precedence_role_id=precedence_role_id,
        held_role_id=held_role_id,
        staging_point_m=held_trajectory.trajectory.points[0].position_m,
        planned_hold_s=delay_s,
        predicted_minimum_separation_m=prediction.minimum_separation_m,
        added_duration_s=delay_s,
        execution_program_sha256=delayed.sha256 if feasible else None,
        reason=(
            "precedence role clears the conflict while the held role remains at an admitted "
            "staging point outside the required separation tube"
            if feasible
            else "staging delay does not satisfy separation or mission duration"
        ),
    )


def _retiming_candidate(
    programs: tuple[AcceptedExecutionProgram, ...],
    *,
    precedence_role_id: str,
    retimed_role_id: str,
    required_separation_m: float,
    policy: SafetyPolicy,
) -> tuple[tuple[AcceptedExecutionProgram, ...], ResolutionCandidate]:
    best = programs
    selected_factor: float | None = None
    selected_prediction: _Prediction | None = None
    for factor in (1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0):
        candidate_program = _retime_program(
            next(item for item in programs if item.role_id == retimed_role_id),
            factor,
        )
        transformed = tuple(
            candidate_program if item.role_id == retimed_role_id else item for item in programs
        )
        prediction = _prediction(transformed[0], transformed[1], required_separation_m)
        if (
            prediction.minimum_separation_m >= required_separation_m
            and candidate_program.schedule_duration_s <= policy.max_mission_duration_s
        ):
            best = transformed
            selected_factor = factor
            selected_prediction = prediction
            break
    feasible = selected_factor is not None and selected_prediction is not None
    return best, ResolutionCandidate(
        strategy=ConflictResolutionStrategy.SPEED_RETIMING,
        feasible=feasible,
        precedence_role_id=precedence_role_id,
        held_role_id=retimed_role_id,
        retiming_factor=selected_factor,
        predicted_minimum_separation_m=(
            selected_prediction.minimum_separation_m if selected_prediction else None
        ),
        added_duration_s=(
            next(item for item in best if item.role_id == retimed_role_id).schedule_duration_s
            - next(item for item in programs if item.role_id == retimed_role_id).schedule_duration_s
            if feasible
            else 0.0
        ),
        execution_program_sha256=(
            next(item for item in best if item.role_id == retimed_role_id).sha256
            if feasible
            else None
        ),
        reason=(
            "continuous trajectory timing separates the closest-approach instants"
            if feasible
            else "bounded continuous retiming cannot retain the required separation"
        ),
    )


def _horizontal_candidate(
    programs: tuple[AcceptedExecutionProgram, ...],
    *,
    precedence_role_id: str,
    detour_role_id: str,
    required_separation_m: float,
    policy: SafetyPolicy,
) -> tuple[tuple[AcceptedExecutionProgram, ...], ResolutionCandidate]:
    original = next(item for item in programs if item.role_id == detour_role_id)
    best = programs
    selected_offset: float | None = None
    selected_prediction: _Prediction | None = None
    for offset_m in (
        required_separation_m,
        -required_separation_m,
        1.2,
        -1.2,
        1.5,
        -1.5,
    ):
        candidate_program = _offset_program(original, horizontal_offset_m=offset_m)
        if not _program_admissible(candidate_program, policy):
            continue
        transformed = tuple(
            candidate_program if item.role_id == detour_role_id else item for item in programs
        )
        prediction = _prediction(transformed[0], transformed[1], required_separation_m)
        if prediction.minimum_separation_m >= required_separation_m:
            best = transformed
            selected_offset = offset_m
            selected_prediction = prediction
            break
    feasible = selected_offset is not None and selected_prediction is not None
    return best, ResolutionCandidate(
        strategy=ConflictResolutionStrategy.HORIZONTAL_DETOUR,
        feasible=feasible,
        precedence_role_id=precedence_role_id,
        held_role_id=detour_role_id,
        horizontal_detour_m=selected_offset,
        predicted_minimum_separation_m=(
            selected_prediction.minimum_separation_m if selected_prediction else None
        ),
        added_path_length_m=(abs(selected_offset) * 2.0 if selected_offset else 0.0),
        execution_program_sha256=(
            next(item for item in best if item.role_id == detour_role_id).sha256
            if feasible
            else None
        ),
        reason=(
            "smooth in-volume lateral bump separates the crossing trajectories"
            if feasible
            else "bounded horizontal detour does not satisfy separation inside the volume"
        ),
    )


def _vertical_candidate(
    programs: tuple[AcceptedExecutionProgram, ...],
    *,
    precedence_role_id: str,
    shifted_role_id: str,
    required_separation_m: float,
    policy: SafetyPolicy,
) -> tuple[tuple[AcceptedExecutionProgram, ...], ResolutionCandidate]:
    original = next(item for item in programs if item.role_id == shifted_role_id)
    shifted = _offset_program(original, vertical_offset_m=required_separation_m)
    inside = _program_admissible(shifted, policy)
    transformed = tuple(shifted if item.role_id == shifted_role_id else item for item in programs)
    prediction = (
        _prediction(transformed[0], transformed[1], required_separation_m) if inside else None
    )
    feasible = (
        inside
        and prediction is not None
        and prediction.minimum_separation_m >= required_separation_m
    )
    return (transformed if feasible else programs), ResolutionCandidate(
        strategy=ConflictResolutionStrategy.VERTICAL_SEPARATION,
        feasible=feasible,
        precedence_role_id=precedence_role_id,
        held_role_id=shifted_role_id,
        vertical_offset_m=required_separation_m,
        predicted_minimum_separation_m=prediction.minimum_separation_m if prediction else None,
        execution_program_sha256=shifted.sha256 if feasible else None,
        reason=(
            "vertical layer fits the flight volume and retains the required margin"
            if feasible
            else "required vertical layer exceeds altitude, flight-volume, or uncertainty bounds"
        ),
    )


def _combined_candidate(
    programs: tuple[AcceptedExecutionProgram, ...],
    *,
    precedence_role_id: str,
    shifted_role_id: str,
    required_separation_m: float,
    policy: SafetyPolicy,
) -> tuple[tuple[AcceptedExecutionProgram, ...], ResolutionCandidate]:
    original = next(item for item in programs if item.role_id == shifted_role_id)
    best = programs
    selected_factor: float | None = None
    selected_offset: float | None = None
    selected_prediction: _Prediction | None = None
    for factor in (1.5, 2.0, 2.5, 3.0, 3.25):
        for offset_m in (0.2, 0.4, 0.6):
            candidate_program = _offset_program(
                _retime_program(original, factor),
                vertical_offset_m=offset_m,
            )
            if not _program_admissible(candidate_program, policy):
                continue
            transformed = tuple(
                candidate_program if item.role_id == shifted_role_id else item for item in programs
            )
            prediction = _prediction(transformed[0], transformed[1], required_separation_m)
            if prediction.minimum_separation_m >= required_separation_m:
                best = transformed
                selected_factor = factor
                selected_offset = offset_m
                selected_prediction = prediction
                break
        if selected_prediction is not None:
            break
    feasible = selected_prediction is not None
    selected_program = next(
        (item for item in best if item.role_id == shifted_role_id),
        original,
    )
    return best, ResolutionCandidate(
        strategy=ConflictResolutionStrategy.COMBINED_RETIMING_VERTICAL,
        feasible=feasible,
        precedence_role_id=precedence_role_id,
        held_role_id=shifted_role_id,
        retiming_factor=selected_factor,
        vertical_offset_m=selected_offset,
        predicted_minimum_separation_m=(
            selected_prediction.minimum_separation_m if selected_prediction else None
        ),
        added_duration_s=(
            selected_program.schedule_duration_s - original.schedule_duration_s if feasible else 0.0
        ),
        execution_program_sha256=selected_program.sha256 if feasible else None,
        reason=(
            "bounded retiming and vertical offset jointly retain the required margin"
            if feasible
            else "bounded retiming and vertical combinations do not fit all hard constraints"
        ),
    )


def _delay_before_trajectory(
    program: AcceptedExecutionProgram,
    delay_s: float,
) -> AcceptedExecutionProgram:
    trajectory_index = next(
        index
        for index, operation in enumerate(program.operations)
        if isinstance(operation, TrajectoryExecutionOperation)
    )
    operations: list[ExecutionOperation] = list(program.operations)
    if trajectory_index > 0 and isinstance(
        operations[trajectory_index - 1], HoldExecutionOperation
    ):
        hold = operations[trajectory_index - 1]
        operations[trajectory_index - 1] = hold.model_copy(
            update={"ends_at_s": hold.ends_at_s + delay_s}
        )
        shift_from = trajectory_index
    else:
        trajectory = operations[trajectory_index]
        operations.insert(
            trajectory_index,
            HoldExecutionOperation(
                sequence=trajectory.sequence,
                starts_at_s=trajectory.starts_at_s,
                ends_at_s=trajectory.starts_at_s + delay_s,
            ),
        )
        shift_from = trajectory_index + 1
    for index in range(shift_from, len(operations)):
        operation = operations[index]
        operations[index] = operation.model_copy(
            update={
                "sequence": index + 1,
                "starts_at_s": operation.starts_at_s + delay_s,
                "ends_at_s": operation.ends_at_s + delay_s,
            }
        )
    for index in range(shift_from):
        operation = operations[index]
        if operation.sequence != index + 1:
            operations[index] = operation.model_copy(update={"sequence": index + 1})
    return _rebuild_program(program, tuple(operations))


def _delay_before_launch(
    program: AcceptedExecutionProgram,
    delay_s: float,
) -> AcceptedExecutionProgram:
    if delay_s <= 0.0:
        return program
    operations: list[ExecutionOperation] = list(program.operations)
    if isinstance(operations[0], GroundWaitExecutionOperation):
        wait = operations[0]
        operations[0] = wait.model_copy(update={"ends_at_s": wait.ends_at_s + delay_s})
        shift_from = 1
    else:
        operations.insert(
            0,
            GroundWaitExecutionOperation(
                sequence=1,
                starts_at_s=0.0,
                ends_at_s=delay_s,
            ),
        )
        shift_from = 1
    for index in range(shift_from, len(operations)):
        operation = operations[index]
        operations[index] = operation.model_copy(
            update={
                "sequence": index + 1,
                "starts_at_s": operation.starts_at_s + delay_s,
                "ends_at_s": operation.ends_at_s + delay_s,
            }
        )
    return _rebuild_program(program, tuple(operations))


def _retime_program(
    program: AcceptedExecutionProgram,
    factor: float,
) -> AcceptedExecutionProgram:
    operations: list[ExecutionOperation] = []
    added_s = 0.0
    for operation in program.operations:
        if isinstance(operation, TrajectoryExecutionOperation):
            trajectory = operation.trajectory
            points = tuple(
                point.model_copy(
                    update={
                        "time_from_start_s": point.time_from_start_s * factor,
                        "velocity_m_s": _scale(point.velocity_m_s, 1.0 / factor),
                        "acceleration_m_s2": _scale(point.acceleration_m_s2, 1.0 / factor**2),
                        "yaw_rate_rad_s": point.yaw_rate_rad_s / factor,
                    }
                )
                for point in trajectory.points
            )
            updated = trajectory.model_copy(
                update={
                    "trajectory_id": f"{trajectory.trajectory_id}-retimed",
                    "points": points,
                }
            )
            duration_s = updated.duration_s
            old_duration_s = operation.ends_at_s - operation.starts_at_s
            operations.append(
                operation.model_copy(
                    update={
                        "starts_at_s": operation.starts_at_s + added_s,
                        "ends_at_s": operation.starts_at_s + added_s + duration_s,
                        "trajectory": updated,
                        "trajectory_sha256": updated.sha256,
                    }
                )
            )
            added_s += duration_s - old_duration_s
        else:
            operations.append(
                operation.model_copy(
                    update={
                        "starts_at_s": operation.starts_at_s + added_s,
                        "ends_at_s": operation.ends_at_s + added_s,
                    }
                )
            )
    return _rebuild_program(program, tuple(operations))


def _offset_program(
    program: AcceptedExecutionProgram,
    *,
    horizontal_offset_m: float = 0.0,
    vertical_offset_m: float = 0.0,
) -> AcceptedExecutionProgram:
    operations: list[ExecutionOperation] = []
    for operation in program.operations:
        if not isinstance(operation, TrajectoryExecutionOperation):
            operations.append(operation)
            continue
        trajectory = operation.trajectory
        duration_s = trajectory.duration_s
        points: list[TrajectoryPoint] = []
        for point in trajectory.points:
            phase = point.time_from_start_s / duration_s
            if horizontal_offset_m:
                bump, bump_velocity, bump_acceleration = _plateau_bump(
                    phase,
                    duration_s,
                )
            else:
                bump = math.sin(math.pi * phase) ** 2
                bump_velocity = math.pi * math.sin(2.0 * math.pi * phase) / duration_s
                bump_acceleration = (
                    2.0 * math.pi**2 * math.cos(2.0 * math.pi * phase) / duration_s**2
                )
            points.append(
                point.model_copy(
                    update={
                        "position_m": point.position_m.model_copy(
                            update={
                                "y": point.position_m.y + horizontal_offset_m * bump,
                                "z": point.position_m.z + vertical_offset_m * bump,
                            }
                        ),
                        "velocity_m_s": point.velocity_m_s.model_copy(
                            update={
                                "y": point.velocity_m_s.y + horizontal_offset_m * bump_velocity,
                                "z": point.velocity_m_s.z + vertical_offset_m * bump_velocity,
                            }
                        ),
                        "acceleration_m_s2": point.acceleration_m_s2.model_copy(
                            update={
                                "y": point.acceleration_m_s2.y
                                + horizontal_offset_m * bump_acceleration,
                                "z": point.acceleration_m_s2.z
                                + vertical_offset_m * bump_acceleration,
                            }
                        ),
                    }
                )
            )
        updated = trajectory.model_copy(
            update={
                "trajectory_id": f"{trajectory.trajectory_id}-offset",
                "route_sha256": canonical_sha256(
                    [trajectory.route_sha256, horizontal_offset_m, vertical_offset_m]
                ),
                "points": tuple(points),
            }
        )
        operations.append(
            operation.model_copy(
                update={"trajectory": updated, "trajectory_sha256": updated.sha256}
            )
        )
    return _rebuild_program(program, tuple(operations))


def _rebuild_program(
    original: AcceptedExecutionProgram,
    operations: tuple[ExecutionOperation, ...],
) -> AcceptedExecutionProgram:
    duration_s = operations[-1].ends_at_s
    payload = original.model_dump(mode="python")
    payload.update(
        {
            "program_id": f"{original.program_id}-resolved",
            "operations": operations,
            "route_sha256s": tuple(
                item.trajectory.route_sha256
                for item in operations
                if isinstance(item, TrajectoryExecutionOperation)
            ),
            "schedule_duration_s": duration_s,
            "execution_timeout_s": (
                duration_s + original.contingency_reserve_s + original.recovery_reserve_s
            ),
        }
    )
    return AcceptedExecutionProgram.model_validate(payload)


def _program_admissible(
    program: AcceptedExecutionProgram,
    policy: SafetyPolicy,
) -> bool:
    for operation in _trajectory_operations(program):
        trajectory = operation.trajectory
        sample_count = max(1, math.ceil(trajectory.duration_s / PREDICTION_STEP_S))
        for index in range(sample_count + 1):
            setpoint = sample_trajectory(
                trajectory,
                min(
                    trajectory.duration_s,
                    index * trajectory.duration_s / sample_count,
                ),
            )
            if (
                not policy.flight_volume.contains(setpoint.position_m)
                or setpoint.position_m.z > policy.max_altitude_m
                or math.hypot(setpoint.velocity_m_s.x, setpoint.velocity_m_s.y)
                > policy.max_horizontal_speed_m_s
                or abs(setpoint.velocity_m_s.z) > policy.max_vertical_speed_m_s
                or math.sqrt(
                    setpoint.acceleration_m_s2.x**2
                    + setpoint.acceleration_m_s2.y**2
                    + setpoint.acceleration_m_s2.z**2
                )
                > policy.max_acceleration_m_s2
            ):
                return False
    return True


def _trajectory_operations(
    program: AcceptedExecutionProgram,
) -> tuple[TrajectoryExecutionOperation, ...]:
    return tuple(
        operation
        for operation in program.operations
        if isinstance(operation, TrajectoryExecutionOperation)
    )


def _blocked_plan(
    mission_id: str,
    *,
    candidates: tuple[ResolutionCandidate, ...],
    reason: str,
    conflict: PredictedConflict | None = None,
) -> FleetDeconflictionPlan:
    if not candidates:
        candidates = (
            ResolutionCandidate(
                strategy=ConflictResolutionStrategy.STAGING_HOLD,
                feasible=False,
                reason=reason,
            ),
        )
    payload: dict[str, object] = {
        "deconfliction_id": f"deconfliction-{canonical_sha256([mission_id, reason])[:20]}",
        "status": DeconflictionStatus.BLOCKED,
        "conflict": conflict,
        "candidates": candidates,
    }
    return FleetDeconflictionPlan(
        **payload,
        plan_sha256=canonical_sha256(payload),
    )


def _scale(value: Vector3, factor: float) -> Vector3:
    return Vector3(x=value.x * factor, y=value.y * factor, z=value.z * factor)


def _plateau_bump(phase: float, duration_s: float) -> tuple[float, float, float]:
    ramp = 0.25
    if ramp <= phase <= 1.0 - ramp:
        return 1.0, 0.0, 0.0
    descending = phase > 1.0 - ramp
    u = (1.0 - phase) / ramp if descending else phase / ramp
    u = max(0.0, min(1.0, u))
    value = 10.0 * u**3 - 15.0 * u**4 + 6.0 * u**5
    first_u = 30.0 * u**2 - 60.0 * u**3 + 30.0 * u**4
    second_u = 60.0 * u - 180.0 * u**2 + 120.0 * u**3
    direction = -1.0 if descending else 1.0
    velocity = direction * first_u / ramp / duration_s
    acceleration = second_u / ramp**2 / duration_s**2
    return value, velocity, acceleration


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )
