from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from itertools import pairwise
from typing import Any, Literal, TypeVar

from pydantic import Field

from crazyswarm_app.domain.commands import CommandKind, ExecuteTrajectoryCommand
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import sample_trajectory
from crazyswarm_app.observability.events import (
    AcknowledgementPayload,
    CommandPayload,
    EvidenceEvent,
    FaultPayload,
    MissionResultPayload,
    TelemetryPayload,
)

MISSION_EXECUTION_BUNDLE_CONTRACT = "mission-execution-bundle-v1"
MISSION_EXECUTION_EVALUATION_CONTRACT = "mission-execution-evaluation-v1"
EVALUATOR_ID = "deterministic-mission-execution-evaluator"
EVALUATOR_VERSION = "1.0.0"
_STOP_SPEED_M_S = 0.02
_PAIRING_TOLERANCE_S = 0.25
T = TypeVar("T")


class EvaluationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class EvidenceCompleteness(ContractModel):
    complete: bool
    present: tuple[Identifier, ...]
    missing: tuple[Identifier, ...]


class VehicleExecutionMetrics(ContractModel):
    vehicle_id: Identifier
    run_ids: tuple[Identifier, ...]
    telemetry_sample_count: int = Field(ge=0)
    command_count: int = Field(ge=0)
    acknowledgement_count: int = Field(ge=0)
    elapsed_s: float | None = Field(default=None, ge=0.0)
    estimate_path_length_m: float | None = Field(default=None, ge=0.0)
    truth_path_length_m: float | None = Field(default=None, ge=0.0)
    estimate_target_error_m: float | None = Field(default=None, ge=0.0)
    truth_target_error_m: float | None = Field(default=None, ge=0.0)
    tracking_rms_error_m: float | None = Field(default=None, ge=0.0)
    tracking_max_error_m: float | None = Field(default=None, ge=0.0)
    final_speed_m_s: float | None = Field(default=None, ge=0.0)
    peak_speed_m_s: float | None = Field(default=None, ge=0.0)
    peak_acceleration_m_s2: float | None = Field(default=None, ge=0.0)
    peak_jerk_m_s3: float | None = Field(default=None, ge=0.0)
    unintended_stop_count: int = Field(ge=0)
    declared_hold_count: int = Field(ge=0)
    declared_hold_duration_s: float = Field(ge=0.0)
    battery_used_percent: float | None = Field(default=None, ge=0.0)
    minimum_boundary_margin_m: float | None = None
    planned_duration_s: float | None = Field(default=None, ge=0.0)
    execution_duration_delta_s: float | None = None
    terminal_state: str | None = None
    inherited_faults: tuple[str, ...] = ()
    new_faults: tuple[str, ...] = ()
    trajectory_command_count: int = Field(ge=0)
    accepted_plan_identity_match: bool | None = None
    accepted_trajectory_sha256s: tuple[SHA256, ...] = ()
    trajectory_generation_unintended_stop_count: int = Field(ge=0)
    trajectory_tracking_rms_error_m: float | None = Field(default=None, ge=0.0)
    trajectory_tracking_max_error_m: float | None = Field(default=None, ge=0.0)
    landing_goal_id: Identifier | None = None
    goal_capture_attempt_count: int | None = Field(default=None, ge=1)
    descent_authorized: bool | None = None
    terminal_goal_capture_margin_m: float | None = None
    terminal_contact: str | None = None


class FleetExecutionMetrics(ContractModel):
    vehicle_count: int = Field(ge=1)
    elapsed_s: float | None = Field(default=None, ge=0.0)
    minimum_estimated_separation_m: float | None = Field(default=None, ge=0.0)
    minimum_truth_separation_m: float | None = Field(default=None, ge=0.0)
    minimum_separation_pair: tuple[Identifier, Identifier] | None = None
    warning_sample_count: int = Field(ge=0)
    critical_sample_count: int = Field(ge=0)
    warning_separation_m: float | None = Field(default=None, gt=0.0)
    critical_separation_m: float | None = Field(default=None, gt=0.0)
    predicted_minimum_separation_m: float | None = Field(default=None, ge=0.0)
    plan_execution_duration_delta_s: float | None = None
    deconfliction_plan_sha256: SHA256 | None = None
    selected_deconfliction_strategy: Identifier | None = None
    nominal_deconfliction_executed: bool | None = None


class OperatorAnnotation(ContractModel):
    annotation_id: Identifier
    author_id: Identifier
    note: str = Field(min_length=1, max_length=2_000)
    created_at_utc: str


class MissionExecutionEvaluation(ContractModel):
    schema_version: Literal[1] = 1
    contract: Literal["mission-execution-evaluation-v1"] = "mission-execution-evaluation-v1"
    evaluator_id: Literal["deterministic-mission-execution-evaluator"] = (
        "deterministic-mission-execution-evaluator"
    )
    evaluator_version: Literal["1.0.0"] = "1.0.0"
    mission_execution_id: Identifier
    shared_time_basis: Literal["recorded_at_utc"] = "recorded_at_utc"
    status: EvaluationStatus
    evidence: EvidenceCompleteness
    run_ids: tuple[Identifier, ...]
    vehicle_ids: tuple[Identifier, ...]
    vehicles: tuple[VehicleExecutionMetrics, ...]
    fleet: FleetExecutionMetrics
    summary: tuple[str, ...]
    annotations: tuple[OperatorAnnotation, ...] = ()
    report_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"report_sha256"})


def evaluate_mission_execution(
    *,
    mission_execution_id: str,
    runs: Sequence[Mapping[str, Any]],
    events: Iterable[EvidenceEvent],
    context: Mapping[str, Any] | None = None,
    annotations: Sequence[Mapping[str, Any]] = (),
) -> MissionExecutionEvaluation:
    if not runs:
        raise ValueError("mission execution evaluation requires at least one run")
    materialized_events = sorted(
        events,
        key=lambda item: (
            item.recorded_at_utc,
            item.vehicle_id,
            item.run_id,
            item.sequence,
            item.event_id,
        ),
    )
    selected_context = dict(context or {})
    plan = _mapping(selected_context.get("mission_plan"))
    assignments = {
        str(role_id): str(vehicle_id)
        for role_id, vehicle_id in _mapping(selected_context.get("assignments")).items()
    }
    execution_result = _mapping(selected_context.get("execution_result"))
    accepted_plan_sha256 = str(
        selected_context.get("mission_plan_sha256")
        or execution_result.get("mission_plan_sha256")
        or ""
    )
    events_by_vehicle: dict[str, list[EvidenceEvent]] = defaultdict(list)
    for event in materialized_events:
        events_by_vehicle[event.vehicle_id].append(event)

    run_ids_by_vehicle: dict[str, list[str]] = defaultdict(list)
    for run in runs:
        run_ids_by_vehicle[str(run["vehicle_id"])].append(str(run["run_id"]))
    vehicle_ids = tuple(sorted(run_ids_by_vehicle))
    vehicle_metrics = tuple(
        _vehicle_metrics(
            vehicle_id=vehicle_id,
            run_ids=tuple(sorted(run_ids_by_vehicle[vehicle_id])),
            events=events_by_vehicle.get(vehicle_id, []),
            plan=plan,
            assignments=assignments,
            accepted_plan_sha256=accepted_plan_sha256,
        )
        for vehicle_id in vehicle_ids
    )
    completeness = _evidence_completeness(
        runs=runs,
        events_by_vehicle=events_by_vehicle,
        context=selected_context,
        vehicle_count=len(vehicle_ids),
    )
    parsed_annotations = tuple(
        OperatorAnnotation.model_validate(item)
        for item in sorted(
            annotations,
            key=lambda item: (str(item.get("created_at_utc", "")), str(item["annotation_id"])),
        )
    )
    fleet_metrics = _fleet_metrics(events_by_vehicle, plan, vehicle_metrics)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": MISSION_EXECUTION_EVALUATION_CONTRACT,
        "evaluator_id": EVALUATOR_ID,
        "evaluator_version": EVALUATOR_VERSION,
        "mission_execution_id": mission_execution_id,
        "shared_time_basis": "recorded_at_utc",
        "status": (
            EvaluationStatus.COMPLETE if completeness.complete else EvaluationStatus.INCOMPLETE
        ),
        "evidence": completeness,
        "run_ids": tuple(sorted(str(run["run_id"]) for run in runs)),
        "vehicle_ids": vehicle_ids,
        "vehicles": vehicle_metrics,
        "fleet": fleet_metrics,
        "summary": _operator_summary(completeness, vehicle_metrics, fleet_metrics),
        "annotations": parsed_annotations,
    }
    return MissionExecutionEvaluation(
        **payload,
        report_sha256=canonical_sha256(payload),
    )


def build_execution_bundle(
    *,
    mission_execution_id: str,
    runs: Sequence[Mapping[str, Any]],
    events: Iterable[EvidenceEvent],
    context: Mapping[str, Any] | None,
    annotations: Sequence[Mapping[str, Any]],
    evaluation: MissionExecutionEvaluation,
) -> dict[str, Any]:
    ordered_runs = sorted(runs, key=lambda item: (str(item["vehicle_id"]), str(item["run_id"])))
    ordered_events = sorted(
        events,
        key=lambda item: (
            item.recorded_at_utc,
            item.vehicle_id,
            item.run_id,
            item.sequence,
            item.event_id,
        ),
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": MISSION_EXECUTION_BUNDLE_CONTRACT,
        "mission_execution_id": mission_execution_id,
        "shared_time_basis": "recorded_at_utc",
        "context": dict(context or {}),
        "runs": [_run_bundle_view(run) for run in ordered_runs],
        "events": [event.model_dump(mode="json") for event in ordered_events],
        "annotations": [dict(item) for item in annotations],
        "evaluation": evaluation.model_dump(mode="json"),
    }
    return {**payload, "bundle_sha256": canonical_sha256(payload)}


def _vehicle_metrics(
    *,
    vehicle_id: str,
    run_ids: tuple[str, ...],
    events: Sequence[EvidenceEvent],
    plan: Mapping[str, Any],
    assignments: Mapping[str, str],
    accepted_plan_sha256: str,
) -> VehicleExecutionMetrics:
    telemetry_events = _telemetry_events(events)
    commands = [item.payload.command for item in events if isinstance(item.payload, CommandPayload)]
    acknowledgements = [
        item.payload.acknowledgement
        for item in events
        if isinstance(item.payload, AcknowledgementPayload)
    ]
    samples = [payload.telemetry.telemetry for _, payload in telemetry_events]
    times = [item.recorded_at_utc.timestamp() for item, _ in telemetry_events]
    estimates = [sample.position_m for sample in samples]
    truths = [sample.ground_truth_position_m for sample in samples]
    velocities = [sample.velocity_m_s for sample in samples]
    speeds = [_norm(value) if value is not None else None for value in velocities]
    target, planned_duration = _vehicle_plan(vehicle_id, plan, assignments)
    boundaries = _plan_boundaries(plan)
    tracking_errors = [
        _distance(estimate, truth)
        for estimate, truth in zip(estimates, truths, strict=True)
        if estimate is not None and truth is not None
    ]
    observed_faults = [set(sample.faults) for sample in samples]
    explicit_faults = {
        item.payload.code for item in events if isinstance(item.payload, FaultPayload)
    }
    inherited_faults = observed_faults[0] if observed_faults else set()
    later_faults = set().union(*observed_faults[1:]) if len(observed_faults) > 1 else set()
    new_faults = (later_faults | explicit_faults) - inherited_faults
    elapsed = times[-1] - times[0] if len(times) >= 2 else None
    accelerations = _derivatives(speeds, times)
    jerks = _derivatives(accelerations, times[1:]) if len(times) >= 3 else []
    final_estimate = _last_present(estimates)
    final_truth = _last_present(truths)
    battery_values = [
        sample.battery_percent for sample in samples if sample.battery_percent is not None
    ]
    selected_positions = [
        truth or estimate for truth, estimate in zip(truths, estimates, strict=True)
    ]
    margins = [
        _boundary_margin(position, boundaries)
        for position in selected_positions
        if position is not None and boundaries is not None
    ]
    hold_commands = [
        command.payload
        for command in commands
        if command.payload.kind in {CommandKind.HOVER, CommandKind.STOP_AND_HOLD}
    ]
    (
        trajectory_count,
        plan_identity_match,
        trajectory_sha256s,
        generated_stops,
        trajectory_tracking_errors,
    ) = _trajectory_metrics(events, plan, accepted_plan_sha256)
    (
        landing_goal_id,
        goal_attempt_count,
        descent_authorized,
        terminal_goal_margin,
        terminal_contact,
    ) = _goal_capture_metrics(events)
    return VehicleExecutionMetrics(
        vehicle_id=vehicle_id,
        run_ids=run_ids,
        telemetry_sample_count=len(samples),
        command_count=len(commands),
        acknowledgement_count=len(acknowledgements),
        elapsed_s=_nonnegative(elapsed),
        estimate_path_length_m=_path_length(estimates),
        truth_path_length_m=_path_length(truths),
        estimate_target_error_m=(
            _distance(final_estimate, target)
            if final_estimate is not None and target is not None
            else None
        ),
        truth_target_error_m=(
            _distance(final_truth, target)
            if final_truth is not None and target is not None
            else None
        ),
        tracking_rms_error_m=_rms(tracking_errors),
        tracking_max_error_m=max(tracking_errors, default=None),
        final_speed_m_s=_last_present(speeds),
        peak_speed_m_s=max((item for item in speeds if item is not None), default=None),
        peak_acceleration_m_s2=max(accelerations, default=None),
        peak_jerk_m_s3=max(jerks, default=None),
        unintended_stop_count=_unintended_stops(speeds),
        declared_hold_count=len(hold_commands),
        declared_hold_duration_s=sum(
            float(getattr(command, "duration_s", 0.0)) for command in hold_commands
        ),
        battery_used_percent=(
            max(0.0, battery_values[0] - battery_values[-1]) if battery_values else None
        ),
        minimum_boundary_margin_m=min(margins, default=None),
        planned_duration_s=planned_duration,
        execution_duration_delta_s=(
            elapsed - planned_duration
            if elapsed is not None and planned_duration is not None
            else None
        ),
        terminal_state=samples[-1].state.value if samples else None,
        inherited_faults=tuple(sorted(inherited_faults)),
        new_faults=tuple(sorted(new_faults)),
        trajectory_command_count=trajectory_count,
        accepted_plan_identity_match=plan_identity_match,
        accepted_trajectory_sha256s=trajectory_sha256s,
        trajectory_generation_unintended_stop_count=generated_stops,
        trajectory_tracking_rms_error_m=_rms(trajectory_tracking_errors),
        trajectory_tracking_max_error_m=max(trajectory_tracking_errors, default=None),
        landing_goal_id=landing_goal_id,
        goal_capture_attempt_count=goal_attempt_count,
        descent_authorized=descent_authorized,
        terminal_goal_capture_margin_m=terminal_goal_margin,
        terminal_contact=terminal_contact,
    )


def _goal_capture_metrics(
    events: Sequence[EvidenceEvent],
) -> tuple[str | None, int | None, bool | None, float | None, str | None]:
    results = [
        event.payload.result for event in events if isinstance(event.payload, MissionResultPayload)
    ]
    if not results or not results[-1].goal_captures:
        return None, None, None, None, None
    capture = _mapping(results[-1].goal_captures[-1])
    goal = _mapping(capture.get("goal"))
    target = _vector(goal.get("landing_target_m"))
    terminal = _vector(
        capture.get("terminal_truth_position_m") or capture.get("terminal_estimated_position_m")
    )
    horizontal_tolerance = goal.get("horizontal_tolerance_m")
    vertical_tolerance = goal.get("vertical_tolerance_m")
    margin = None
    if (
        target is not None
        and terminal is not None
        and isinstance(horizontal_tolerance, (int, float))
        and isinstance(vertical_tolerance, (int, float))
    ):
        margin = min(
            float(horizontal_tolerance) - math.hypot(terminal.x - target.x, terminal.y - target.y),
            float(vertical_tolerance) - abs(terminal.z - target.z),
        )
    attempt_count = capture.get("attempt_count")
    descent = capture.get("descent_authorized")
    return (
        str(goal["goal_id"]) if goal.get("goal_id") else None,
        int(attempt_count) if isinstance(attempt_count, int) else None,
        bool(descent) if isinstance(descent, bool) else None,
        margin,
        str(capture["terminal_contact"]) if capture.get("terminal_contact") else None,
    )


def _trajectory_metrics(
    events: Sequence[EvidenceEvent],
    plan: Mapping[str, Any],
    accepted_plan_sha256: str,
) -> tuple[int, bool | None, tuple[str, ...], int, list[float]]:
    selected: list[tuple[int, ExecuteTrajectoryCommand]] = []
    for index, event in enumerate(events):
        if isinstance(event.payload, CommandPayload) and isinstance(
            event.payload.command.payload,
            ExecuteTrajectoryCommand,
        ):
            selected.append((index, event.payload.command.payload))
    if not selected:
        return 0, None, (), 0, []

    expected_plan_id = str(plan.get("plan_id", ""))
    expected_programs = {
        str(_mapping(program).get("program_id", "")): _mapping(program)
        for program in plan.get("execution_programs", [])
        if isinstance(program, Mapping)
    }
    identity_match = True
    trajectory_hashes: list[str] = []
    generated_stops = 0
    tracking_errors: list[float] = []
    for command_index, command in selected:
        trajectory_hashes.append(command.trajectory_sha256)
        program_matches = any(
            canonical_sha256(program) == command.execution_program_sha256
            and command.trajectory_sha256
            in {
                str(_mapping(operation).get("trajectory_sha256", ""))
                for operation in program.get("operations", [])
                if isinstance(operation, Mapping)
            }
            for program in expected_programs.values()
        )
        identity_match = identity_match and (
            command.accepted_plan_id == expected_plan_id
            and command.accepted_plan_sha256 == accepted_plan_sha256
            and program_matches
        )
        declared_stops = set(command.trajectory.declared_stop_sequences)
        generated_stops += sum(
            1
            for point in command.trajectory.points[1:-1]
            if point.sequence not in declared_stops and _norm(point.velocity_m_s) <= _STOP_SPEED_M_S
        )

        acknowledgement_index = len(events)
        command_id = None
        command_event = events[command_index]
        if isinstance(command_event.payload, CommandPayload):
            command_id = command_event.payload.command.command_id
        for index in range(command_index + 1, len(events)):
            payload = events[index].payload
            if (
                isinstance(payload, AcknowledgementPayload)
                and payload.acknowledgement.command_id == command_id
            ):
                acknowledgement_index = index
                break
        samples = [
            payload.telemetry
            for event in events[command_index + 1 : acknowledgement_index]
            if isinstance((payload := event.payload), TelemetryPayload)
        ]
        if not samples:
            continue
        source_start_s = samples[0].source_timestamp_s
        for envelope in samples:
            actual = envelope.telemetry.ground_truth_position_m or envelope.telemetry.position_m
            if actual is None:
                continue
            desired = sample_trajectory(
                command.trajectory,
                envelope.source_timestamp_s - source_start_s,
            )
            tracking_errors.append(_distance(actual, desired.position_m))
    return (
        len(selected),
        identity_match,
        tuple(sorted(set(trajectory_hashes))),
        generated_stops,
        tracking_errors,
    )


def _fleet_metrics(
    events_by_vehicle: Mapping[str, Sequence[EvidenceEvent]],
    plan: Mapping[str, Any],
    vehicles: Sequence[VehicleExecutionMetrics],
) -> FleetExecutionMetrics:
    telemetry = {
        vehicle_id: _telemetry_events(events) for vehicle_id, events in events_by_vehicle.items()
    }
    warning, critical = _separation_thresholds(plan)
    minimum_estimate: float | None = None
    minimum_truth: float | None = None
    minimum_pair: tuple[str, str] | None = None
    warning_count = 0
    critical_count = 0
    ids = sorted(telemetry)
    for first_index, first_id in enumerate(ids):
        for second_id in ids[first_index + 1 :]:
            for first, second in _paired_telemetry(telemetry[first_id], telemetry[second_id]):
                first_sample = first[1].telemetry.telemetry
                second_sample = second[1].telemetry.telemetry
                estimate_distance = _optional_distance(
                    first_sample.position_m,
                    second_sample.position_m,
                )
                truth_distance = _optional_distance(
                    first_sample.ground_truth_position_m,
                    second_sample.ground_truth_position_m,
                )
                observed = truth_distance if truth_distance is not None else estimate_distance
                if estimate_distance is not None and (
                    minimum_estimate is None or estimate_distance < minimum_estimate
                ):
                    minimum_estimate = estimate_distance
                    if minimum_truth is None:
                        minimum_pair = (first_id, second_id)
                if truth_distance is not None and (
                    minimum_truth is None or truth_distance < minimum_truth
                ):
                    minimum_truth = truth_distance
                    minimum_pair = (first_id, second_id)
                elif minimum_pair is None and observed is not None:
                    minimum_pair = (first_id, second_id)
                if observed is not None and critical is not None and observed < critical:
                    critical_count += 1
                elif observed is not None and warning is not None and observed < warning:
                    warning_count += 1
    elapsed_values = [item.elapsed_s for item in vehicles if item.elapsed_s is not None]
    planned_values = [
        item.planned_duration_s for item in vehicles if item.planned_duration_s is not None
    ]
    fleet_elapsed = max(elapsed_values, default=None)
    planned_duration = max(planned_values, default=None)
    deconfliction = _mapping(plan.get("deconfliction"))
    selected_strategy = deconfliction.get("selected_strategy")
    deconfliction_status = deconfliction.get("status")
    identity_results = [
        item.accepted_plan_identity_match
        for item in vehicles
        if item.accepted_plan_identity_match is not None
    ]
    nominal_deconfliction_executed = (
        bool(identity_results) and len(identity_results) == len(vehicles) and all(identity_results)
        if deconfliction_status == "RESOLVED"
        else None
    )
    return FleetExecutionMetrics(
        vehicle_count=len(vehicles),
        elapsed_s=fleet_elapsed,
        minimum_estimated_separation_m=minimum_estimate,
        minimum_truth_separation_m=minimum_truth,
        minimum_separation_pair=minimum_pair,
        warning_sample_count=warning_count,
        critical_sample_count=critical_count,
        warning_separation_m=warning,
        critical_separation_m=critical,
        predicted_minimum_separation_m=_predicted_minimum_separation(plan),
        plan_execution_duration_delta_s=(
            fleet_elapsed - planned_duration
            if fleet_elapsed is not None and planned_duration is not None
            else None
        ),
        deconfliction_plan_sha256=(
            str(deconfliction["plan_sha256"]) if deconfliction.get("plan_sha256") else None
        ),
        selected_deconfliction_strategy=(str(selected_strategy) if selected_strategy else None),
        nominal_deconfliction_executed=nominal_deconfliction_executed,
    )


def _evidence_completeness(
    *,
    runs: Sequence[Mapping[str, Any]],
    events_by_vehicle: Mapping[str, Sequence[EvidenceEvent]],
    context: Mapping[str, Any],
    vehicle_count: int,
) -> EvidenceCompleteness:
    checks = {
        "accepted_plan": bool(_mapping(context.get("mission_plan"))),
        "acknowledgements": all(
            any(isinstance(item.payload, AcknowledgementPayload) for item in events)
            for events in events_by_vehicle.values()
        ),
        "binding": bool(_mapping(context.get("binding"))),
        "child_results": all(run.get("result_json") for run in runs),
        "commands": all(
            any(isinstance(item.payload, CommandPayload) for item in events)
            for events in events_by_vehicle.values()
        ),
        "deployment": bool(_mapping(context.get("deployment"))),
        "execution_result": bool(_mapping(context.get("execution_result"))),
        "fleet_events": vehicle_count == 1 or bool(context.get("fleet_events")),
        "provenance": all(_run_has_provenance(run) for run in runs),
        "telemetry": all(
            any(isinstance(item.payload, TelemetryPayload) for item in events)
            for events in events_by_vehicle.values()
        ),
        "terminal_runs": all(run.get("status") is not None for run in runs),
    }
    present = tuple(sorted(name for name, value in checks.items() if value))
    missing = tuple(sorted(name for name, value in checks.items() if not value))
    return EvidenceCompleteness(complete=not missing, present=present, missing=missing)


def _operator_summary(
    evidence: EvidenceCompleteness,
    vehicles: Sequence[VehicleExecutionMetrics],
    fleet: FleetExecutionMetrics,
) -> tuple[str, ...]:
    lines = [
        (
            "Evidence is complete."
            if evidence.complete
            else f"Evidence is incomplete: {', '.join(evidence.missing)}."
        )
    ]
    for vehicle in vehicles:
        target_error = (
            vehicle.truth_target_error_m
            if vehicle.truth_target_error_m is not None
            else vehicle.estimate_target_error_m
        )
        error_text = "target error unavailable"
        if target_error is not None:
            error_text = f"target error {target_error:.3f} m"
        lines.append(
            f"{vehicle.vehicle_id}: {error_text}; "
            f"{vehicle.unintended_stop_count} unintended stops; "
            f"terminal {vehicle.terminal_state or 'unknown'}."
        )
    separation = (
        fleet.minimum_truth_separation_m
        if fleet.minimum_truth_separation_m is not None
        else fleet.minimum_estimated_separation_m
    )
    if fleet.vehicle_count > 1:
        separation_text = (
            f"minimum separation {separation:.3f} m"
            if separation is not None
            else "minimum separation unavailable"
        )
        lines.append(
            f"Fleet: {separation_text}; {fleet.warning_sample_count} warning samples; "
            f"{fleet.critical_sample_count} critical samples."
        )
    return tuple(lines)


def _run_has_provenance(run: Mapping[str, Any]) -> bool:
    raw = run.get("result_json") or run.get("snapshot_json")
    if not raw:
        return False
    try:
        import json

        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return False
    return bool(
        value.get("configuration_hash")
        and value.get("mission_runtime_id")
        and value.get("vehicle_adapter")
    )


def _run_bundle_view(run: Mapping[str, Any]) -> dict[str, Any]:
    import json

    return {
        key: value for key, value in run.items() if key not in {"snapshot_json", "result_json"}
    } | {
        "snapshot": json.loads(str(run["snapshot_json"])),
        "result": json.loads(str(run["result_json"])) if run.get("result_json") else None,
    }


def _vehicle_plan(
    vehicle_id: str,
    plan: Mapping[str, Any],
    assignments: Mapping[str, str],
) -> tuple[Vector3 | None, float | None]:
    roles = plan.get("roles")
    if isinstance(roles, list):
        for role in roles:
            item = _mapping(role)
            role_id = str(item.get("role_id", ""))
            if str(item.get("vehicle_id", assignments.get(role_id, ""))) != vehicle_id:
                continue
            waypoints = item.get("waypoints")
            target = None
            if isinstance(waypoints, list) and waypoints:
                target = _vector(_mapping(waypoints[-1]).get("end_m"))
            duration = item.get("planned_duration_s")
            return target, float(duration) if isinstance(duration, (int, float)) else None
    return None, None


def _plan_boundaries(plan: Mapping[str, Any]) -> tuple[Vector3, Vector3] | None:
    safety = _mapping(plan.get("safety"))
    minimum = _vector(safety.get("flight_volume_minimum_m"))
    maximum = _vector(safety.get("flight_volume_maximum_m"))
    return (minimum, maximum) if minimum is not None and maximum is not None else None


def _separation_thresholds(plan: Mapping[str, Any]) -> tuple[float | None, float | None]:
    safety = _mapping(plan.get("safety"))
    warning = safety.get("warning_separation_m")
    critical = safety.get("critical_separation_m")
    return (
        float(warning) if isinstance(warning, (int, float)) else None,
        float(critical) if isinstance(critical, (int, float)) else None,
    )


def _predicted_minimum_separation(plan: Mapping[str, Any]) -> float | None:
    deconfliction = _mapping(plan.get("deconfliction"))
    candidates = deconfliction.get("candidates")
    selected_index = deconfliction.get("selected_candidate_index")
    if (
        isinstance(candidates, list)
        and isinstance(selected_index, int)
        and 0 <= selected_index < len(candidates)
    ):
        value = _mapping(candidates[selected_index]).get("predicted_minimum_separation_m")
        if isinstance(value, (int, float)):
            return float(value)
    planning = _mapping(plan.get("planning"))
    routes = planning.get("route_plans")
    values: list[float] = []
    if isinstance(routes, list):
        for route in routes:
            value = _mapping(route).get("expected_minimum_separation_m")
            if isinstance(value, (int, float)):
                values.append(float(value))
    return min(values, default=None)


def _paired_telemetry(
    first: Sequence[tuple[EvidenceEvent, TelemetryPayload]],
    second: Sequence[tuple[EvidenceEvent, TelemetryPayload]],
) -> Iterable[
    tuple[tuple[EvidenceEvent, TelemetryPayload], tuple[EvidenceEvent, TelemetryPayload]]
]:
    second_index = 0
    for first_event in first:
        first_time = first_event[0].recorded_at_utc.timestamp()
        while second_index + 1 < len(second) and abs(
            second[second_index + 1][0].recorded_at_utc.timestamp() - first_time
        ) <= abs(second[second_index][0].recorded_at_utc.timestamp() - first_time):
            second_index += 1
        if second and abs(second[second_index][0].recorded_at_utc.timestamp() - first_time) <= (
            _PAIRING_TOLERANCE_S
        ):
            yield first_event, second[second_index]


def _telemetry_events(
    events: Sequence[EvidenceEvent],
) -> list[tuple[EvidenceEvent, TelemetryPayload]]:
    selected: list[tuple[EvidenceEvent, TelemetryPayload]] = []
    for event in events:
        if isinstance(event.payload, TelemetryPayload):
            selected.append((event, event.payload))
    return selected


def _derivatives(values: Sequence[float | None], times: Sequence[float]) -> list[float]:
    result: list[float] = []
    for previous, current, previous_time, current_time in zip(
        values[:-1],
        values[1:],
        times[:-1],
        times[1:],
        strict=True,
    ):
        delta = current_time - previous_time
        if previous is not None and current is not None and delta > 0.0:
            result.append(abs(current - previous) / delta)
        else:
            result.append(0.0)
    return result


def _unintended_stops(speeds: Sequence[float | None]) -> int:
    moving = [
        index for index, speed in enumerate(speeds) if speed is not None and speed > _STOP_SPEED_M_S
    ]
    if len(moving) < 2:
        return 0
    first_moving, last_moving = moving[0], moving[-1]
    stopped = False
    count = 0
    for speed in speeds[first_moving + 1 : last_moving]:
        current_stopped = speed is not None and speed <= _STOP_SPEED_M_S
        if current_stopped and not stopped:
            count += 1
        stopped = current_stopped
    return count


def _path_length(values: Sequence[Vector3 | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(_distance(first, second) for first, second in pairwise(present))


def _boundary_margin(position: Vector3, bounds: tuple[Vector3, Vector3]) -> float:
    minimum, maximum = bounds
    return min(
        position.x - minimum.x,
        maximum.x - position.x,
        position.y - minimum.y,
        maximum.y - position.y,
        position.z - minimum.z,
        maximum.z - position.z,
    )


def _vector(value: object) -> Vector3 | None:
    if isinstance(value, Vector3):
        return value
    if isinstance(value, Mapping):
        try:
            return Vector3.model_validate(value)
        except ValueError:
            return None
    return None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )


def _optional_distance(first: Vector3 | None, second: Vector3 | None) -> float | None:
    return _distance(first, second) if first is not None and second is not None else None


def _norm(value: Vector3) -> float:
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


def _rms(values: Sequence[float]) -> float | None:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else None


def _last_present(values: Sequence[T | None]) -> T | None:
    return next((value for value in reversed(values) if value is not None), None)


def _nonnegative(value: float | None) -> float | None:
    return max(0.0, value) if value is not None else None
