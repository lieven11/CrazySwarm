from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import (
    BehaviorOracleKind,
    CampaignCase,
    MotionQualityContract,
    ScenarioEventKind,
    ScenarioExpectedDisposition,
    TraversalMode,
)
from crazyswarm_app.campaign.physical_truth import (
    DifferentialActuationAnalysis,
    analyze_differential_actuation_csv,
)
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class RootCauseStage(StrEnum):
    PLANNER = "PLANNER"
    TRAJECTORY = "TRAJECTORY"
    CONTROLLER = "CONTROLLER"
    SIM_TIMING = "SIM_TIMING"
    EVIDENCE_DELIVERY = "EVIDENCE_DELIVERY"
    UI_RENDERING = "UI_RENDERING"
    LANDING = "LANDING"
    UNKNOWN = "UNKNOWN"


class AnalysisParameters(ContractModel):
    schema_version: Literal[1] = 1
    source_resample_step_s: float = Field(default=0.02, gt=0.0, le=1.0)
    smoothing_window_s: float = Field(default=0.50, ge=0.0, le=10.0)
    fleet_alignment_tolerance_s: float = Field(default=0.25, gt=0.0, le=2.0)
    stop_speed_threshold_m_s: float = Field(default=0.02, ge=0.0)
    stop_persistence_s: float = Field(default=0.20, gt=0.0)


class MetricDistribution(ContractModel):
    sample_count: int = Field(ge=0)
    p50: float | None = None
    p95: float | None = None
    peak: float | None = None


class MotionQualityVector(ContractModel):
    """Literal source-clock motion vector; fields remain separate by design."""

    speed_compliance_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    speed_ripple_m_s: float | None = Field(default=None, ge=0.0)
    acceleration_p95_m_s2: float | None = Field(default=None, ge=0.0)
    jerk_p95_m_s3: float | None = Field(default=None, ge=0.0)
    angular_rate_p95_rad_s: float | None = Field(default=None, ge=0.0)
    minimum_motor_thrust_headroom_n: float | None = None
    motor_spread_p95_percent: float | None = Field(default=None, ge=0.0)
    motor_saturation_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    motor_differential_sign_agreement_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    motor_differential_normalized_error_p95: float | None = Field(default=None, ge=0.0)
    electrical_energy_used_j: float | None = Field(default=None, ge=0.0)
    tracking_rms_m: float | None = Field(default=None, ge=0.0)
    path_tube_max_error_m: float | None = Field(default=None, ge=0.0)
    minimum_clearance_m: float | None = None
    collision_count: int | None = Field(default=None, ge=0)
    checkpoint_hold_conformance_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_continuous_knot_speed_ratio: float | None = Field(default=None, ge=0.0)
    unintended_fly_through_stop_count: int | None = Field(default=None, ge=0)
    terminal_secondary_peak_m_s: float | None = Field(default=None, ge=0.0)
    terminal_reversal_count: int | None = Field(default=None, ge=0)
    duration_s: float = Field(ge=0.0)
    supervisor_safety_gate_passed: bool | None = None


class MotionQualityAnalysis(ContractModel):
    schema_version: Literal[1] = 1
    vehicle_id: Identifier
    contract_sha256: SHA256
    csv_sha256: SHA256
    sample_count: int = Field(ge=0)
    vector: MotionQualityVector
    failed_guards: tuple[Identifier, ...]
    missing_guards: tuple[Identifier, ...]
    analysis_sha256: SHA256


def analyze_motion_quality_csv(
    csv_bytes: bytes,
    contract: MotionQualityContract,
    *,
    vehicle_id: str | None = None,
    planned_route_m: Sequence[Vector3] = (),
    minimum_clearance_m: float | None = None,
    collision_count: int | None = None,
    checkpoint_hold_conformance_fraction: float | None = None,
    minimum_continuous_knot_speed_ratio: float | None = None,
    unintended_fly_through_stop_count: int | None = None,
    motor_differential_sign_agreement_fraction: float | None = None,
    motor_differential_normalized_error_p95: float | None = None,
    supervisor_safety_gate_passed: bool | None = None,
    motion_window_source_s: tuple[float, float] | None = None,
) -> MotionQualityAnalysis:
    """Recompute the WP-57/61 guard vector from raw run-telemetry-v1 rows.

    Geometry-, mixer-, and Supervisor-owned values are explicit inputs. They are
    reported missing when their independent oracle did not supply them; this function
    never fabricates them from a summary or a visually rounded motor value.
    """

    text = csv_bytes.decode("utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise ValueError("telemetry CSV contains no rows")
    selected_id = vehicle_id or str(rows[0].get("vehicle_id") or "")
    selected = [row for row in rows if row.get("vehicle_id") == selected_id]
    if not selected_id or not selected:
        raise ValueError("motion analysis vehicle is absent from telemetry CSV")
    ordered = sorted(
        selected,
        key=lambda row: (
            _first_float(row, "simulation_timestamp_s", "source_timestamp_s"),
            int(_float(row.get("telemetry_sequence")) or 0),
        ),
    )
    unique: list[Mapping[str, str]] = []
    seen: set[tuple[float, int]] = set()
    for row in ordered:
        key = (
            _first_float(row, "simulation_timestamp_s", "source_timestamp_s"),
            int(_float(row.get("telemetry_sequence")) or 0),
        )
        if key not in seen:
            seen.add(key)
            unique.append(row)
    if motion_window_source_s is not None:
        start_s, end_s = motion_window_source_s
        if end_s <= start_s:
            raise ValueError("motion source window must have positive duration")
        unique = [
            row
            for row in unique
            if start_s <= _first_float(row, "simulation_timestamp_s", "source_timestamp_s") <= end_s
        ]
        if len(unique) < 3:
            raise ValueError("motion source window contains fewer than three samples")
    times = [_first_float(row, "simulation_timestamp_s", "source_timestamp_s") for row in unique]
    velocities = [
        (timestamp, value)
        for timestamp, row in zip(times, unique, strict=True)
        if (value := _row_vector(row, "velocity", "_m_s")) is not None
    ]
    if not velocities:
        positions = [
            (timestamp, value)
            for timestamp, row in zip(times, unique, strict=True)
            if (value := _row_vector(row, "ground_truth")) is not None
        ]
        velocities = _derivative_vectors(positions)
    speeds = [(timestamp, _norm(value)) for timestamp, value in velocities]
    moving_speeds = [value for _timestamp, value in speeds if value > 0.02]
    accelerations = _derivative_values(speeds)
    imu_accelerations = [
        (timestamp, value)
        for timestamp, row in zip(times, unique, strict=True)
        if (value := _row_vector(row, "imu_acceleration", "_m_s2")) is not None
    ]
    imu_jerks = _derivative_vectors(imu_accelerations)
    jerks = (
        [(timestamp, _norm(value)) for timestamp, value in imu_jerks]
        if imu_jerks
        else _derivative_values(accelerations)
    )
    angular_rates = [
        _norm(value)
        for row in unique
        if (value := _row_vector(row, "imu_angular_velocity", "_rad_s")) is not None
    ]
    motor_spreads: list[float] = []
    motor_headrooms: list[float] = []
    saturated_count = 0
    motor_count = 0
    for row in unique:
        pwm = [_float(row.get(f"motor_m{index}_applied_pwm_percent")) for index in range(1, 5)]
        present_pwm = [value for value in pwm if value is not None]
        if len(present_pwm) == 4:
            motor_spreads.append(max(present_pwm) - min(present_pwm))
        for index in range(1, 5):
            thrust = _float(row.get(f"motor_m{index}_thrust_n"))
            available = _float(row.get(f"motor_m{index}_available_thrust_n"))
            saturated = _boolean(row.get(f"motor_m{index}_saturated"))
            if thrust is not None and available is not None:
                motor_headrooms.append(available - thrust)
            if saturated is not None:
                motor_count += 1
                saturated_count += int(saturated)
    power = [
        (timestamp, voltage * current)
        for timestamp, row in zip(times, unique, strict=True)
        if (voltage := _float(row.get("battery_voltage_v"))) is not None
        and (current := _float(row.get("battery_current_a"))) is not None
    ]
    energy = sum(
        (before[1] + after[1]) * 0.5 * (after[0] - before[0])
        for before, after in pairwise(power)
        if after[0] > before[0]
    )
    observed_positions = [
        value for row in unique if (value := _row_vector(row, "ground_truth")) is not None
    ]
    path_errors = (
        [_distance_to_polyline(point, planned_route_m) for point in observed_positions]
        if len(planned_route_m) >= 2
        else []
    )
    terminal_window_size = max(3, len(speeds) // 10)
    terminal_speeds = [value for _timestamp, value in speeds[-terminal_window_size:]]
    terminal_peak = _secondary_peak_prominence(terminal_speeds)
    terminal_reversals = _terminal_reversal_count(
        [value for _timestamp, value in velocities[-terminal_window_size:]],
        direction=(
            Vector3(
                x=planned_route_m[-1].x - planned_route_m[-2].x,
                y=planned_route_m[-1].y - planned_route_m[-2].y,
                z=planned_route_m[-1].z - planned_route_m[-2].z,
            )
            if len(planned_route_m) >= 2
            else None
        ),
    )
    speed_compliance = None
    if contract.target_speed_m_s is not None and moving_speeds:
        speed_compliance = sum(
            abs(value - contract.target_speed_m_s) <= contract.speed_band_m_s
            for value in moving_speeds
        ) / len(moving_speeds)
    payload_vector = MotionQualityVector(
        speed_compliance_fraction=speed_compliance,
        speed_ripple_m_s=(
            _percentile(sorted(moving_speeds), 0.95) - _percentile(sorted(moving_speeds), 0.05)
            if moving_speeds
            else None
        ),
        acceleration_p95_m_s2=(
            _percentile(sorted(value for _time, value in accelerations), 0.95)
            if accelerations
            else None
        ),
        jerk_p95_m_s3=(
            _percentile(sorted(value for _time, value in jerks), 0.95) if jerks else None
        ),
        angular_rate_p95_rad_s=(
            _percentile(sorted(angular_rates), 0.95) if angular_rates else None
        ),
        minimum_motor_thrust_headroom_n=min(motor_headrooms, default=None),
        motor_spread_p95_percent=(
            _percentile(sorted(motor_spreads), 0.95) if motor_spreads else None
        ),
        motor_saturation_fraction=(saturated_count / motor_count if motor_count else None),
        motor_differential_sign_agreement_fraction=(motor_differential_sign_agreement_fraction),
        motor_differential_normalized_error_p95=motor_differential_normalized_error_p95,
        electrical_energy_used_j=(energy if len(power) >= 2 else None),
        tracking_rms_m=(
            math.sqrt(sum(value * value for value in path_errors) / len(path_errors))
            if path_errors
            else None
        ),
        path_tube_max_error_m=max(path_errors, default=None),
        minimum_clearance_m=minimum_clearance_m,
        collision_count=collision_count,
        checkpoint_hold_conformance_fraction=checkpoint_hold_conformance_fraction,
        minimum_continuous_knot_speed_ratio=minimum_continuous_knot_speed_ratio,
        unintended_fly_through_stop_count=unintended_fly_through_stop_count,
        terminal_secondary_peak_m_s=terminal_peak,
        terminal_reversal_count=terminal_reversals,
        duration_s=max(0.0, times[-1] - times[0]),
        supervisor_safety_gate_passed=supervisor_safety_gate_passed,
    )
    failed, missing = _motion_guard_verdict(payload_vector, contract)
    payload: dict[str, Any] = {
        "vehicle_id": selected_id,
        "contract_sha256": contract.contract_sha256,
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "sample_count": len(unique),
        "vector": payload_vector,
        "failed_guards": failed,
        "missing_guards": missing,
    }
    return MotionQualityAnalysis(**payload, analysis_sha256=canonical_sha256(payload))


class KinematicsGateReconciliation(ContractModel):
    raw_scope: Literal["ALL_RECORDED_AIRBORNE_SAMPLES"] = "ALL_RECORDED_AIRBORNE_SAMPLES"
    processed_scope: Literal["SMOOTHED_ROUTE_WINDOW"] = "SMOOTHED_ROUTE_WINDOW"
    raw_horizontal_speed_peak_m_s: float | None = Field(default=None, ge=0.0)
    raw_vertical_speed_peak_m_s: float | None = Field(default=None, ge=0.0)
    processed_horizontal_speed_peak_m_s: float | None = Field(default=None, ge=0.0)
    processed_vertical_speed_peak_m_s: float | None = Field(default=None, ge=0.0)
    maximum_horizontal_speed_m_s: float = Field(gt=0.0)
    maximum_vertical_speed_m_s: float = Field(gt=0.0)
    raw_gate_passed: bool | None = None
    processed_gate_passed: bool | None = None
    gate_disagreement: bool


class VehicleTimeline(ContractModel):
    first_source_s: float
    last_source_s: float
    takeoff_source_s: float | None = None
    takeoff_complete_source_s: float | None = None
    route_start_source_s: float | None = None
    landing_start_source_s: float | None = None
    touchdown_source_s: float | None = None
    airborne_wait_before_route_s: float | None = Field(default=None, ge=0.0)


class VehicleAnalysis(ContractModel):
    vehicle_id: Identifier
    telemetry_row_count: int = Field(ge=0)
    source_clock_id: str
    source_clock_epoch: int = Field(ge=0)
    source_duration_s: float = Field(ge=0.0)
    wall_duration_s: float = Field(ge=0.0)
    realtime_factor: float | None = Field(default=None, ge=0.0)
    timeline: VehicleTimeline
    battery_used_percent: float | None = Field(default=None, ge=0.0)
    truth_path_length_m: float | None = Field(default=None, ge=0.0)
    estimate_path_length_m: float | None = Field(default=None, ge=0.0)
    tracking_rms_error_m: float | None = Field(default=None, ge=0.0)
    tracking_max_error_m: float | None = Field(default=None, ge=0.0)
    source_clock_target_error_s: float | None = Field(default=None, ge=0.0)
    minimum_boundary_margin_m: float | None = None
    speed_m_s: MetricDistribution
    acceleration_m_s2: MetricDistribution
    jerk_m_s3: MetricDistribution
    kinematics_gate_reconciliation: KinematicsGateReconciliation
    unintended_stop_count: int = Field(ge=0)
    duplicate_sample_count: int = Field(ge=0)
    missing_sequence_count: int = Field(ge=0)
    out_of_order_sample_count: int = Field(ge=0)
    terminal_state: str | None = None
    estimated_touchdown_m: Vector3 | None = None
    truth_touchdown_m: Vector3 | None = None


class PairSeparation(ContractModel):
    vehicle_ids: tuple[Identifier, Identifier]
    aligned_sample_count: int = Field(ge=0)
    minimum_estimated_separation_m: float | None = Field(default=None, ge=0.0)
    minimum_truth_separation_m: float | None = Field(default=None, ge=0.0)
    closest_recorded_at_utc: datetime | None = None


class LandingComparison(ContractModel):
    vehicle_id: Identifier
    frame: Literal["world"] = "world"
    accepted_landing_center_m: Vector3
    planned_arrival_m: Vector3 | None = None
    planned_descent_m: Vector3 | None = None
    estimated_touchdown_m: Vector3 | None = None
    truth_touchdown_m: Vector3 | None = None
    displayed_goal_marker_m: Vector3 | None = None
    landing_goal_id: Identifier | None = None
    terminal_contact: str | None = None
    pre_contact_vertical_speed_m_s: float | None = Field(default=None, ge=0.0)
    contact_source_timestamp_s: float | None = Field(default=None, ge=0.0)
    post_contact_settling_s: float | None = Field(default=None, ge=0.0)
    disarmed_source_timestamp_s: float | None = Field(default=None, ge=0.0)
    motors_cut_after_contact: bool | None = None
    coordinate_conversion_chain: tuple[str, ...] = ("world -> world",)


class CauseClassification(ContractModel):
    stage: RootCauseStage
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_references: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()


class BehaviorOracleResult(ContractModel):
    oracle_id: Identifier
    kind: BehaviorOracleKind
    passed: bool
    observed_value: float | str | bool | None = None
    threshold: float | None = None
    unit: str | None = None
    reason: str = Field(min_length=1, max_length=1000)
    evidence_references: tuple[str, ...]


class MissionAnalysis(ContractModel):
    schema_version: Literal[1, 2] = 2
    analyzer_id: Literal["campaign-offline-analyzer"] = "campaign-offline-analyzer"
    analyzer_version: Literal["1.0.0"] = "1.0.0"
    mission_execution_id: Identifier
    mission_outcome: str
    telemetry_row_count: int = Field(ge=0)
    evidence_complete: bool
    source_kinematics_time_basis: Literal["SOURCE_OR_SIMULATION_CLOCK"] = (
        "SOURCE_OR_SIMULATION_CLOCK"
    )
    fleet_separation_time_basis: Literal["ALIGNED_RECORDED_UTC"] = "ALIGNED_RECORDED_UTC"
    parameters: AnalysisParameters
    case_sha256: SHA256
    plan_sha256: SHA256 | None = None
    planning_submission_id: Identifier | None = None
    planning_submission_sha256: SHA256 | None = None
    resolved_planning_package_sha256: SHA256 | None = None
    manifest_sha256: SHA256
    bundle_sha256: SHA256
    csv_sha256: SHA256
    vehicles: tuple[VehicleAnalysis, ...]
    motion_quality: tuple[MotionQualityAnalysis, ...] = ()
    physical_truth: tuple[DifferentialActuationAnalysis, ...] = ()
    replan_timeline: tuple[dict[str, Any], ...] = ()
    pair_separation: tuple[PairSeparation, ...]
    minimum_truth_separation_m: float | None = Field(default=None, ge=0.0)
    landing: tuple[LandingComparison, ...]
    primary_cause: CauseClassification
    contributors: tuple[CauseClassification, ...] = ()
    behavior_oracles: tuple[BehaviorOracleResult, ...] = ()
    all_required_behavior_oracles_passed: bool = True
    analysis_sha256: SHA256

    @model_validator(mode="after")
    def planning_evidence_identity_is_complete(self) -> MissionAnalysis:
        if (self.planning_submission_id is None) != (self.planning_submission_sha256 is None):
            raise ValueError("analysis planning submission identity must be complete")
        if (
            self.resolved_planning_package_sha256 is not None
            and self.planning_submission_sha256 is None
        ):
            raise ValueError("analysis package identity requires planning submission identity")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"analysis_sha256"})


class ModeComparison(ContractModel):
    schema_version: Literal[1] = 1
    accelerated_analysis_sha256: SHA256
    realtime_analysis_sha256: SHA256
    maximum_source_clock_target_error_difference_s: float | None = Field(default=None, ge=0.0)
    maximum_truth_path_length_difference_m: float | None = Field(default=None, ge=0.0)
    maximum_tracking_rms_difference_m: float | None = Field(default=None, ge=0.0)
    minimum_separation_difference_m: float | None = Field(default=None, ge=0.0)
    source_clock_target_error_gate_applicable: bool = True
    truth_path_length_gate_applicable: bool = True
    tracking_rms_gate_applicable: bool = True
    minimum_separation_gate_applicable: bool = True
    source_clock_target_error_gate_passed: bool
    truth_path_length_gate_passed: bool
    tracking_rms_gate_passed: bool
    minimum_separation_gate_passed: bool
    all_gates_passed: bool
    comparison_sha256: SHA256


def compare_execution_modes(
    case: CampaignCase,
    accelerated: MissionAnalysis,
    realtime: MissionAnalysis,
) -> ModeComparison:
    """Compare source-clock evidence from the same immutable case across clock modes."""

    if accelerated.case_sha256 != case.case_sha256 or realtime.case_sha256 != case.case_sha256:
        raise ValueError("mode comparison analyses must match the immutable case")
    accelerated_by_vehicle = {item.vehicle_id: item for item in accelerated.vehicles}
    realtime_by_vehicle = {item.vehicle_id: item for item in realtime.vehicles}
    if set(accelerated_by_vehicle) != set(realtime_by_vehicle):
        raise ValueError("mode comparison vehicle sets differ")

    def maximum_difference(attribute: str) -> tuple[float | None, bool, bool]:
        differences: list[float] = []
        applicable = False
        asymmetric_absence = False
        for vehicle_id in sorted(accelerated_by_vehicle):
            first = getattr(accelerated_by_vehicle[vehicle_id], attribute)
            second = getattr(realtime_by_vehicle[vehicle_id], attribute)
            if first is None and second is None:
                continue
            applicable = True
            if first is None or second is None:
                asymmetric_absence = True
                continue
            differences.append(abs(float(first) - float(second)))
        return max(differences, default=None), applicable, asymmetric_absence

    target, target_applicable, target_asymmetric = maximum_difference("source_clock_target_error_s")
    path, path_applicable, path_asymmetric = maximum_difference("truth_path_length_m")
    tracking, tracking_applicable, tracking_asymmetric = maximum_difference("tracking_rms_error_m")
    accelerated_separation = accelerated.minimum_truth_separation_m
    realtime_separation = realtime.minimum_truth_separation_m
    separation_applicable = accelerated_separation is not None or realtime_separation is not None
    separation_asymmetric = (accelerated_separation is None) != (realtime_separation is None)
    separation = None
    if accelerated_separation is not None and realtime_separation is not None:
        separation = abs(accelerated_separation - realtime_separation)
    limits = case.hard_constraints.mode_comparison

    def gate(
        difference: float | None,
        *,
        applicable: bool,
        asymmetric_absence: bool,
        limit: float,
    ) -> bool:
        if not applicable:
            return True
        return not asymmetric_absence and difference is not None and difference <= limit

    gates = (
        gate(
            target,
            applicable=target_applicable,
            asymmetric_absence=target_asymmetric,
            limit=limits.maximum_source_clock_target_error_difference_s,
        ),
        gate(
            path,
            applicable=path_applicable,
            asymmetric_absence=path_asymmetric,
            limit=limits.maximum_truth_path_length_difference_m,
        ),
        gate(
            tracking,
            applicable=tracking_applicable,
            asymmetric_absence=tracking_asymmetric,
            limit=limits.maximum_tracking_rms_difference_m,
        ),
        gate(
            separation,
            applicable=separation_applicable,
            asymmetric_absence=separation_asymmetric,
            limit=limits.maximum_minimum_separation_difference_m,
        ),
    )
    payload: dict[str, Any] = {
        "accelerated_analysis_sha256": accelerated.analysis_sha256,
        "realtime_analysis_sha256": realtime.analysis_sha256,
        "maximum_source_clock_target_error_difference_s": target,
        "maximum_truth_path_length_difference_m": path,
        "maximum_tracking_rms_difference_m": tracking,
        "minimum_separation_difference_m": separation,
        "source_clock_target_error_gate_applicable": target_applicable,
        "truth_path_length_gate_applicable": path_applicable,
        "tracking_rms_gate_applicable": tracking_applicable,
        "minimum_separation_gate_applicable": separation_applicable,
        "source_clock_target_error_gate_passed": gates[0],
        "truth_path_length_gate_passed": gates[1],
        "tracking_rms_gate_passed": gates[2],
        "minimum_separation_gate_passed": gates[3],
        "all_gates_passed": all(gates),
    }
    return ModeComparison(**payload, comparison_sha256=canonical_sha256(payload))


class PersistedExecutionResolver(Protocol):
    def analysis_inputs(
        self, mission_execution_id: str
    ) -> tuple[CampaignCase, Mapping[str, Any], Mapping[str, Any], bytes]: ...


def analyze_persisted_execution(
    mission_execution_id: str,
    resolver: PersistedExecutionResolver,
    *,
    parameters: AnalysisParameters | None = None,
) -> MissionAnalysis:
    case, manifest, bundle, csv_bytes = resolver.analysis_inputs(mission_execution_id)
    return analyze_execution(
        case=case,
        manifest=manifest,
        bundle=bundle,
        csv_bytes=csv_bytes,
        parameters=parameters,
    )


def analyze_artifact_set(
    *,
    case_path: Path,
    manifest_path: Path,
    bundle_path: Path,
    csv_path: Path,
    parameters: AnalysisParameters | None = None,
) -> MissionAnalysis:
    case = CampaignCase.model_validate(_load_data(case_path))
    manifest = _mapping(_load_data(manifest_path), "manifest")
    bundle = _mapping(_load_data(bundle_path), "bundle")
    return analyze_execution(
        case=case,
        manifest=manifest,
        bundle=bundle,
        csv_bytes=csv_path.read_bytes(),
        parameters=parameters,
    )


def analyze_execution(
    *,
    case: CampaignCase,
    manifest: Mapping[str, Any],
    bundle: Mapping[str, Any],
    csv_bytes: bytes,
    parameters: AnalysisParameters | None = None,
) -> MissionAnalysis:
    """Join all qualification inputs; a CSV alone is intentionally insufficient."""

    selected = parameters or AnalysisParameters()
    execution_id = str(
        manifest.get("mission_execution_id") or bundle.get("mission_execution_id") or ""
    )
    if not execution_id:
        raise ValueError("manifest/bundle must identify the mission execution")
    manifest_case_hash = manifest.get("case_sha256") or bundle.get("case_sha256")
    if manifest_case_hash is not None and str(manifest_case_hash) != case.case_sha256:
        raise ValueError("case identity does not match manifest/bundle")
    rows = _parse_csv(csv_bytes)
    if not rows:
        raise ValueError("telemetry CSV contains no rows")
    by_vehicle: dict[str, list[_Sample]] = defaultdict(list)
    for row in rows:
        by_vehicle[row.vehicle_id].append(row)
    drones_by_role = {drone.role_id: drone for drone in case.drones}
    context = _mapping(bundle.get("context", {}), "context")
    campaign_trajectories = _mapping(
        context.get("campaign_trajectories", {}), "campaign_trajectories"
    )
    trajectory_values = campaign_trajectories.get("trajectories", ())
    trajectories_by_role = {
        str(value.get("role_id")): value
        for value in trajectory_values
        if isinstance(value, Mapping)
    }
    assignments = _mapping(
        bundle.get("assignments") or context.get("assignments", {}), "assignments"
    )
    retained_motion_contract = _retained_motion_contract(context)
    analyses: list[VehicleAnalysis] = []
    motion_analyses: list[MotionQualityAnalysis] = []
    physical_truth_analyses: list[DifferentialActuationAnalysis] = []
    landing: list[LandingComparison] = []
    for vehicle_id in sorted(by_vehicle):
        samples = by_vehicle[vehicle_id]
        artifact_role_id = next(
            (str(role) for role, assigned in assignments.items() if str(assigned) == vehicle_id),
            vehicle_id,
        )
        role_id = _case_role_id(artifact_role_id, tuple(drones_by_role))
        route_window = _campaign_route_window(context, artifact_role_id)
        analysis = _analyze_vehicle(
            samples,
            case,
            selected,
            planned_route_window_s=route_window,
            planned_declared_stop_offsets_s=_declared_stop_offsets(
                trajectories_by_role.get(artifact_role_id)
            ),
        )
        analyses.append(analysis)
        contract = retained_motion_contract or case.motion_contract_for(role_id)
        physical_truth = analyze_differential_actuation_csv(
            csv_bytes,
            vehicle_id=vehicle_id,
        )
        physical_truth_analyses.append(physical_truth)
        planned_route = _planned_route_for_role(context, artifact_role_id)
        knot_ratio, checkpoint_conformance = _route_semantics_observations(
            case=case,
            role_id=role_id,
            samples=samples,
            trajectory=trajectories_by_role.get(artifact_role_id),
            route_points=planned_route,
            route_start_source_s=analysis.timeline.route_start_source_s,
            contract=contract,
        )
        trace = _mapping(
            context.get("campaign_execution_head_trace", {}),
            "execution_head_trace",
        )
        clearance = _minimum_certified_clearance(trace)
        if clearance is None:
            clearance = _minimum_route_clearance(
                case,
                samples,
                analysis.timeline.route_start_source_s,
                analysis.timeline.landing_start_source_s,
            )
        fleet_result = _mapping(context.get("fleet_result", {}), "fleet_result")
        supervisor_passed = (
            str(fleet_result.get("status", "")) == "SUCCEEDED" if fleet_result else None
        )
        collision_count = sum("COLLISION" in sample.faults.upper() for sample in samples)
        motion_analyses.append(
            analyze_motion_quality_csv(
                csv_bytes,
                contract,
                vehicle_id=vehicle_id,
                planned_route_m=planned_route,
                minimum_clearance_m=clearance,
                collision_count=collision_count,
                checkpoint_hold_conformance_fraction=checkpoint_conformance,
                minimum_continuous_knot_speed_ratio=knot_ratio,
                unintended_fly_through_stop_count=analysis.unintended_stop_count,
                motor_differential_sign_agreement_fraction=(physical_truth.sign_agreement_fraction),
                motor_differential_normalized_error_p95=(physical_truth.normalized_error_p95),
                supervisor_safety_gate_passed=supervisor_passed,
                motion_window_source_s=(
                    (
                        analysis.timeline.route_start_source_s,
                        analysis.timeline.landing_start_source_s,
                    )
                    if analysis.timeline.route_start_source_s is not None
                    and analysis.timeline.landing_start_source_s is not None
                    else None
                ),
            )
        )
        drone = drones_by_role.get(role_id)
        if drone is not None:
            capture = _goal_capture_for_vehicle(context, vehicle_id)
            plan = _mapping(bundle.get("accepted_plan", {}), "accepted_plan")
            role_plan = _mapping(
                _mapping(plan.get("roles", {}), "roles").get(artifact_role_id, {}),
                "role",
            )
            campaign_plan = _mapping(
                bundle.get("campaign_plan") or context.get("campaign_plan", {}),
                "campaign_plan",
            )
            campaign_arrival = _campaign_arrival(campaign_plan, artifact_role_id)
            landing.append(
                LandingComparison(
                    vehicle_id=vehicle_id,
                    accepted_landing_center_m=drone.landing_region.center_m,
                    planned_arrival_m=(
                        _optional_vector(role_plan.get("planned_arrival_m")) or campaign_arrival
                    ),
                    planned_descent_m=(
                        _optional_vector(role_plan.get("planned_descent_m")) or campaign_arrival
                    ),
                    estimated_touchdown_m=analysis.estimated_touchdown_m,
                    truth_touchdown_m=analysis.truth_touchdown_m,
                    displayed_goal_marker_m=_displayed_marker(bundle, artifact_role_id),
                    landing_goal_id=_optional_string(
                        _mapping(capture.get("goal", {}), "goal").get("goal_id")
                    ),
                    terminal_contact=_optional_string(capture.get("terminal_contact")),
                    pre_contact_vertical_speed_m_s=_optional_nonnegative_float(
                        capture.get("pre_contact_vertical_speed_m_s")
                    ),
                    contact_source_timestamp_s=_optional_nonnegative_float(
                        capture.get("contact_source_timestamp_s")
                    ),
                    post_contact_settling_s=_optional_nonnegative_float(
                        capture.get("post_contact_settling_s")
                    ),
                    disarmed_source_timestamp_s=_optional_nonnegative_float(
                        capture.get("disarmed_source_timestamp_s")
                    ),
                    motors_cut_after_contact=(
                        capture.get("motors_cut_after_contact")
                        if isinstance(capture.get("motors_cut_after_contact"), bool)
                        else None
                    ),
                    coordinate_conversion_chain=tuple(
                        str(item)
                        for item in bundle.get("coordinate_conversion_chain", ("world -> world",))
                    ),
                )
            )
    pairs = tuple(
        _pair_separation(by_vehicle[first], by_vehicle[second], selected)
        for first, second in combinations(sorted(by_vehicle), 2)
    )
    truth_minima = [
        item.minimum_truth_separation_m
        for item in pairs
        if item.minimum_truth_separation_m is not None
    ]
    outcome = str(
        manifest.get("status") or bundle.get("status") or bundle.get("mission_outcome") or "UNKNOWN"
    )
    primary, contributors = _classify(outcome, analyses, manifest, bundle)
    oracle_results = _evaluate_behavior_oracles(
        case,
        by_vehicle=by_vehicle,
        assignments=assignments,
        vehicle_analyses=tuple(analyses),
        minimum_truth_separation_m=min(truth_minima) if truth_minima else None,
        context=context,
    )
    payload: dict[str, Any] = {
        "mission_execution_id": execution_id,
        "mission_outcome": outcome,
        "telemetry_row_count": len(rows),
        "evidence_complete": True,
        "parameters": selected,
        "case_sha256": case.case_sha256,
        "plan_sha256": _optional_sha(manifest.get("plan_sha256") or bundle.get("plan_sha256")),
        "manifest_sha256": canonical_sha256(manifest),
        "bundle_sha256": canonical_sha256(bundle),
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "vehicles": tuple(analyses),
        "motion_quality": tuple(motion_analyses),
        "physical_truth": tuple(physical_truth_analyses),
        "replan_timeline": tuple(
            dict(record)
            for record in _mapping(
                context.get("campaign_execution_head_trace", {}),
                "execution_head_trace",
            ).get("records", ())
            if isinstance(record, Mapping)
        ),
        "pair_separation": pairs,
        "minimum_truth_separation_m": min(truth_minima) if truth_minima else None,
        "landing": tuple(landing),
        "primary_cause": primary,
        "contributors": contributors,
        "behavior_oracles": oracle_results,
        "all_required_behavior_oracles_passed": all(
            result.passed
            for oracle, result in zip(
                case.semantics.behavior_oracles if case.semantics is not None else (),
                oracle_results,
                strict=True,
            )
            if oracle.required
        ),
    }
    planning_submission_id = _optional_string(
        manifest.get("planning_submission_id")
        or bundle.get("planning_submission_id")
        or _mapping(context.get("campaign_locked_inputs", {}), "locked_inputs").get(
            "planning_submission_id"
        )
    )
    planning_submission_sha256 = _optional_sha(
        manifest.get("planning_submission_sha256")
        or bundle.get("planning_submission_sha256")
        or _mapping(context.get("campaign_locked_inputs", {}), "locked_inputs").get(
            "planning_submission_sha256"
        )
    )
    resolved_package_sha256 = _optional_sha(
        manifest.get("resolved_planning_package_sha256")
        or bundle.get("resolved_planning_package_sha256")
        or _mapping(context.get("campaign_locked_inputs", {}), "locked_inputs").get(
            "resolved_planning_package_sha256"
        )
    )
    if (planning_submission_id is None) != (planning_submission_sha256 is None):
        raise ValueError("planning submission evidence identity is incomplete")
    payload.update(
        {
            "planning_submission_id": planning_submission_id,
            "planning_submission_sha256": planning_submission_sha256,
            "resolved_planning_package_sha256": resolved_package_sha256,
        }
    )
    return MissionAnalysis(**payload, analysis_sha256=canonical_sha256(payload))


def _case_role_id(artifact_role_id: str, case_role_ids: tuple[str, ...]) -> str:
    if artifact_role_id in case_role_ids:
        return artifact_role_id
    normalized = artifact_role_id.lower().removeprefix("route_").replace("-", "_")
    matches = [
        role_id
        for role_id in case_role_ids
        if role_id.lower().replace("-", "_") == normalized
        or normalized.endswith(role_id.lower().replace("-", "_"))
    ]
    if len(matches) != 1:
        raise ValueError(
            f"artifact role {artifact_role_id!r} cannot be mapped to immutable case roles"
        )
    return matches[0]


def _planned_route_for_role(context: Mapping[str, Any], role_id: str) -> tuple[Vector3, ...]:
    plan = _mapping(context.get("campaign_plan", {}), "campaign_plan")
    candidates = plan.get("retained_candidates", ())
    selected_index = plan.get("selected_candidate_index")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return ()
    if not isinstance(selected_index, int) or not 0 <= selected_index < len(candidates):
        return ()
    candidate = candidates[selected_index]
    if not isinstance(candidate, Mapping):
        return ()
    for route in candidate.get("routes", ()):
        if not isinstance(route, Mapping) or str(route.get("role_id")) != role_id:
            continue
        return tuple(
            point
            for value in route.get("points_m", ())
            if (point := _optional_vector(value)) is not None
        )
    return ()


def _retained_motion_contract(
    context: Mapping[str, Any],
) -> MotionQualityContract | None:
    """Recover and cross-check the contract that was actually planned and flown."""

    contracts: list[MotionQualityContract] = []
    for key in ("campaign_plan", "campaign_trajectories"):
        retained = _mapping(context.get(key, {}), key)
        raw_contract = retained.get("motion_quality_contract")
        if raw_contract is None:
            continue
        if not isinstance(raw_contract, Mapping):
            raise ValueError(f"{key} motion quality contract must be a mapping")
        contract = MotionQualityContract.model_validate(raw_contract)
        retained_sha256 = retained.get("motion_quality_contract_sha256")
        if retained_sha256 is not None and str(retained_sha256) != canonical_sha256(contract):
            raise ValueError(f"{key} motion quality contract hash mismatch")
        contracts.append(contract)
    if contracts and any(contract != contracts[0] for contract in contracts[1:]):
        raise ValueError("planned and flown motion quality contracts differ")
    return contracts[0] if contracts else None


def _route_semantics_observations(
    *,
    case: CampaignCase,
    role_id: str,
    samples: Sequence[_Sample],
    trajectory: Mapping[str, Any] | None,
    route_points: Sequence[Vector3],
    route_start_source_s: float | None,
    contract: MotionQualityContract,
) -> tuple[float | None, float | None]:
    """Observe semantic knot motion on the raw source clock.

    Authored route states are matched in sequence against the accepted trajectory, so
    a repeated figure-eight crossover remains two distinct observations rather than
    one coordinate lookup.
    """

    if (
        case.semantics is None
        or trajectory is None
        or route_start_source_s is None
        or len(route_points) < 2
    ):
        return None, None
    intents = case.semantics.route_intent_by_role.get(role_id, ())
    if len(intents) != len(route_points) - 1:
        return None, None
    trajectory_points = tuple(
        value for value in trajectory.get("points", ()) if isinstance(value, Mapping)
    )
    matched: list[tuple[Any, Mapping[str, Any]]] = []
    cursor = 0
    for route_point, intent in zip(route_points[1:], intents, strict=True):
        match_index = next(
            (
                index
                for index in range(cursor, len(trajectory_points))
                if (
                    (position := _optional_vector(trajectory_points[index].get("position_m")))
                    is not None
                    and _distance(position, route_point) <= 1e-6
                )
            ),
            None,
        )
        if match_index is None:
            return None, None
        matched.append((intent, trajectory_points[match_index]))
        cursor = match_index + 1

    ordered_samples = sorted(samples, key=lambda item: (item.source_s, item.sequence))
    fly_through_ratios: list[float] = []
    checkpoint_passes: list[bool] = []
    for intent, point in matched[:-1]:
        offset = point.get("time_from_start_s")
        planned_velocity = _optional_vector(point.get("velocity_m_s"))
        if not isinstance(offset, (int, float)) or planned_velocity is None:
            continue
        target_source_s = route_start_source_s + float(offset)
        observed = min(
            ordered_samples,
            key=lambda item: abs(item.source_s - target_source_s),
            default=None,
        )
        if observed is None or observed.velocity is None:
            continue
        observed_speed = _norm(observed.velocity)
        planned_speed = _norm(planned_velocity)
        if intent.mode.value == "FLY_THROUGH" and planned_speed > 1e-6:
            fly_through_ratios.append(observed_speed / planned_speed)
        elif intent.mode.value in {"CAPTURE_AND_HOLD", "REVERSAL"}:
            checkpoint_passes.append(
                observed_speed <= case.hard_constraints.dynamics.stop_speed_threshold_m_s + 1e-9
            )
    knot_ratio = (
        min(fly_through_ratios)
        if contract.traversal_mode is TraversalMode.CONTINUOUS_FLY_THROUGH and fly_through_ratios
        else None
    )
    checkpoint_conformance = (
        sum(checkpoint_passes) / len(checkpoint_passes)
        if contract.traversal_mode is TraversalMode.CHECKPOINT and checkpoint_passes
        else None
    )
    return knot_ratio, checkpoint_conformance


def _minimum_certified_clearance(trace: Mapping[str, Any]) -> float | None:
    clearances = [
        float(certificate["certified_clearance_m"])
        for record in trace.get("records", ())
        if isinstance(record, Mapping)
        and isinstance(certificate := record.get("safe_prefix_certificate"), Mapping)
        and isinstance(certificate.get("certified_clearance_m"), (int, float))
    ]
    return min(clearances, default=None)


def _evaluate_behavior_oracles(
    case: CampaignCase,
    *,
    by_vehicle: Mapping[str, list[_Sample]],
    assignments: Mapping[str, Any],
    vehicle_analyses: tuple[VehicleAnalysis, ...],
    minimum_truth_separation_m: float | None,
    context: Mapping[str, Any],
) -> tuple[BehaviorOracleResult, ...]:
    if case.semantics is None:
        return ()
    role_to_vehicle = {
        drone.role_id: str(assignments.get(drone.role_id, drone.role_id)) for drone in case.drones
    }
    analyses = {item.vehicle_id: item for item in vehicle_analyses}
    trajectory_set = _mapping(context.get("campaign_trajectories", {}), "trajectories")
    audit_values = trajectory_set.get("audits", ())
    scenario_trace = _mapping(context.get("campaign_scenario_trace", {}), "scenario_trace")
    execution_head_trace = _mapping(
        context.get("campaign_execution_head_trace", {}),
        "execution_head_trace",
    )
    campaign_plan = _mapping(context.get("campaign_plan", {}), "campaign_plan")
    candidates = campaign_plan.get("retained_candidates", ())
    selected_index = campaign_plan.get("selected_candidate_index")
    selected_candidate: Mapping[str, Any] = {}
    if (
        isinstance(candidates, Sequence)
        and isinstance(selected_index, int)
        and 0 <= selected_index < len(candidates)
        and isinstance(candidates[selected_index], Mapping)
    ):
        selected_candidate = candidates[selected_index]
    planned_routes = {
        str(value.get("role_id")): value
        for value in selected_candidate.get("routes", ())
        if isinstance(value, Mapping)
    }
    campaign_schedule = _mapping(context.get("campaign_schedule", {}), "campaign_schedule")
    scheduled_roles = {
        str(value.get("role_id")): value
        for value in campaign_schedule.get("roles", ())
        if isinstance(value, Mapping)
    }
    output = []
    for oracle in case.semantics.behavior_oracles:
        passed = False
        observed: float | str | bool | None = None
        reason = "No implemented evidence reducer accepted this oracle."
        references: tuple[str, ...] = ()
        roles = oracle.role_ids or tuple(drone.role_id for drone in case.drones)
        if oracle.kind is BehaviorOracleKind.ROUTE_NODES_CAPTURED:
            captured = 0
            required = 0
            drone_by_role = {drone.role_id: drone for drone in case.drones}
            for role_id in roles:
                samples = by_vehicle.get(role_to_vehicle[role_id], [])
                nodes = case.semantics.route_intent_by_role[role_id]
                for region, node in zip(drone_by_role[role_id].goal_sequence, nodes, strict=True):
                    required += 1
                    if any(
                        point is not None
                        and _distance(point, region.center_m) <= node.capture_tolerance_m
                        for sample in samples
                        for point in (sample.truth or sample.estimate,)
                    ):
                        captured += 1
            observed = float(captured)
            passed = captured == required
            reason = f"Captured {captured} of {required} ordered authored route regions."
            references = ("telemetry.csv:ground_truth_position", "campaign_case:route_intent")
        elif oracle.kind is BehaviorOracleKind.HOLD_DURATION:
            hold_errors = []
            drone_by_role = {drone.role_id: drone for drone in case.drones}
            trajectory_values = trajectory_set.get("trajectories", ())
            trajectory_by_role = {
                str(value.get("role_id")): value
                for value in trajectory_values
                if isinstance(value, Mapping)
            }
            for role_id in roles:
                samples = by_vehicle.get(role_to_vehicle[role_id], [])
                for region, node in zip(
                    drone_by_role[role_id].goal_sequence,
                    case.semantics.route_intent_by_role[role_id],
                    strict=True,
                ):
                    if node.dwell_s <= 0.0:
                        continue
                    duration = _planned_region_dwell_s(
                        trajectory_by_role.get(role_id),
                        region.center_m,
                        node.capture_tolerance_m,
                    )
                    if duration is None:
                        duration = _longest_region_dwell_s(
                            samples, region.center_m, node.capture_tolerance_m
                        )
                    hold_errors.append(abs(duration - node.dwell_s))
            observed = max(hold_errors, default=0.0)
            passed = bool(hold_errors) and observed <= float(oracle.threshold or 0.0)
            reason = f"Maximum declared-hold duration error was {observed:.3f} s."
            references = ("telemetry.csv:source_timestamp_s", "campaign_case:dwell_s")
        elif oracle.kind is BehaviorOracleKind.NO_UNDECLARED_STOP:
            generated_counts = [
                int(item.get("generated_unintended_stop_count", 0))
                for item in audit_values
                if isinstance(item, Mapping)
            ]
            executed_count = sum(
                analyses[role_to_vehicle[role]].unintended_stop_count for role in roles
            )
            generated_count = sum(generated_counts)
            observed = float(executed_count)
            threshold = float(oracle.threshold or 0.0)
            passed = (
                executed_count <= threshold
                and generated_count <= threshold
                and (not generated_counts or generated_count == executed_count)
            )
            reason = (
                "Route-phase telemetry found "
                f"{executed_count} undeclared stops; the generated-trajectory audit found "
                f"{generated_count}. Diagnostic takeoff, stabilization, landing-entry, and "
                "terminal low-speed phases are outside this route window."
            )
            references = (
                "telemetry.csv:planned_route_source_window",
                "campaign_trajectories:audits",
            )
        elif oracle.kind is BehaviorOracleKind.ALTITUDE_TRANSITION:
            authored_levels = {
                round(goal.center_m.z, 2)
                for drone in case.drones
                if drone.role_id in roles
                for goal in drone.goal_sequence
            }
            observed_levels = {
                level
                for role in roles
                for sample in by_vehicle.get(role_to_vehicle[role], [])
                for point in (sample.truth or sample.estimate,)
                if point is not None
                for level in authored_levels
                if abs(point.z - level) <= 0.08
            }
            observed = float(len(observed_levels))
            passed = observed >= float(oracle.threshold or 0.0)
            reason = (
                f"Execution crossed {int(observed)} of {len(authored_levels)} "
                "authored altitude levels."
            )
            references = ("telemetry.csv:ground_truth_z", "campaign_case:goal_sequence")
        elif oracle.kind is BehaviorOracleKind.CURVED_PATH:
            turn = max(
                (
                    _integrated_horizontal_turn(
                        tuple(goal.center_m for goal in drone.goal_sequence)
                    )
                    for drone in case.drones
                    if drone.role_id in roles
                ),
                default=0.0,
            )
            observed = turn
            passed = turn >= float(oracle.threshold or 0.0)
            reason = (
                f"The executed hash-bound route carries {turn:.3f} rad integrated horizontal turn."
            )
            references = ("campaign_plan:selected_candidate.routes", "telemetry.csv:tracking_error")
        elif oracle.kind is BehaviorOracleKind.CLOSED_SHAPE:
            closure = min(
                (
                    _minimum_nonadjacent_distance(
                        tuple(goal.center_m for goal in drone.goal_sequence)
                    )
                    for drone in case.drones
                    if drone.role_id in roles
                ),
                default=float("inf"),
            )
            observed = closure
            passed = closure <= float(oracle.threshold or 0.0)
            reason = f"Minimum non-adjacent loop closure error was {closure:.3f} m."
            references = ("campaign_case:goal_sequence", "telemetry.csv:ordered_capture")
        elif oracle.kind is BehaviorOracleKind.DISTINCT_START_AND_LANDING:
            displacement = min(
                (
                    _distance(drone.start_region.center_m, drone.landing_region.center_m)
                    for drone in case.drones
                    if drone.role_id in roles
                ),
                default=0.0,
            )
            observed = displacement
            passed = displacement >= float(oracle.threshold or 0.0)
            reason = f"Minimum authored start-to-landing displacement was {displacement:.3f} m."
            references = ("campaign_case:start_region", "campaign_case:landing_region")
        elif oracle.kind is BehaviorOracleKind.SYNCHRONIZED_ROUTE_START:
            starts: list[float] = []
            for role in roles:
                start = analyses[role_to_vehicle[role]].timeline.route_start_source_s
                if start is not None:
                    starts.append(start)
            observed = max(starts, default=0.0) - min(starts, default=0.0)
            passed = len(starts) == len(roles) and observed <= float(oracle.threshold or 0.0)
            reason = f"Observed fleet route-start skew was {observed:.3f} s."
            references = ("telemetry.csv:route_start_source_s",)
        elif oracle.kind is BehaviorOracleKind.MINIMUM_FLIGHT_OVERLAP:
            starts = []
            ends: list[float] = []
            for role in roles:
                timeline = analyses[role_to_vehicle[role]].timeline
                start = timeline.route_start_source_s
                end = timeline.landing_start_source_s
                if start is not None and end is not None:
                    starts.append(start)
                    ends.append(end)
            overlap = max(0.0, min(ends, default=0.0) - max(starts, default=0.0))
            observed = overlap
            passed = len(starts) == len(roles) and overlap >= float(oracle.threshold or 0.0)
            reason = f"Observed simultaneous route-flight overlap was {overlap:.3f} s."
            references = ("telemetry.csv:source_timeline",)
        elif oracle.kind is BehaviorOracleKind.FORMATION_ERROR:
            coordination = case.semantics.coordination_constraints
            # Planner admission computes this continuously; the retained selected route
            # and telemetry tracking bounds are both required evidence here.
            tracking = max(
                (
                    analyses[role_to_vehicle[role]].tracking_max_error_m or float("inf")
                    for role in roles
                ),
                default=float("inf"),
            )
            observed = tracking
            passed = tracking <= float(
                oracle.threshold or coordination.maximum_formation_error_m or 0.0
            )
            reason = (
                f"Maximum role tracking error within the admitted formation was {tracking:.3f} m."
            )
            references = ("campaign_plan:formation_admission", "telemetry.csv:tracking_error")
        elif oracle.kind is BehaviorOracleKind.CONFLICT_RESOLVED:
            observed = minimum_truth_separation_m
            passed = observed is not None and observed >= float(oracle.threshold or 0.0)
            reason = (
                f"Minimum time-aligned truth separation was {observed:.3f} m."
                if observed is not None
                else "No aligned pairwise truth separation evidence was available."
            )
            references = ("telemetry.csv:aligned_ground_truth",)
        elif oracle.kind is BehaviorOracleKind.BOUNDARY_MARGIN:
            margins: list[float] = []
            volume = case.hard_constraints.flight_volume
            for role in roles:
                for sample in by_vehicle.get(role_to_vehicle[role], []):
                    point = sample.truth or sample.estimate
                    # The floor is intentionally reached during takeoff/landing.  This
                    # oracle concerns the lateral faces and ceiling exercised by the
                    # authored boundary route while airborne.
                    if point is None or point.z <= 0.10:
                        continue
                    margins.append(
                        min(
                            point.x - volume.minimum_m.x,
                            volume.maximum_m.x - point.x,
                            point.y - volume.minimum_m.y,
                            volume.maximum_m.y - point.y,
                            volume.maximum_m.z - point.z,
                        )
                    )
            observed = min(margins, default=-1.0)
            passed = bool(margins) and observed >= float(oracle.threshold or 0.0)
            reason = f"Minimum sampled airborne lateral/ceiling margin was {observed:.3f} m."
            references = ("telemetry.csv:ground_truth_position", "campaign_case:flight_volume")
        elif oracle.kind is BehaviorOracleKind.KEEP_OUT_AVOIDED:
            violations = sum(
                1
                for role in roles
                for sample in by_vehicle.get(role_to_vehicle[role], [])
                for point in (sample.truth or sample.estimate,)
                if point is not None
                and any(
                    region.contains(point)
                    for region in case.semantics.environment_constraints.keep_out_regions
                )
            )
            observed = float(violations)
            passed = violations <= int(oracle.threshold or 0.0)
            reason = f"Observed {violations} telemetry samples inside configured keep-out regions."
            references = (
                "telemetry.csv:ground_truth_position",
                "campaign_case:environment_constraints.keep_out_regions",
            )
        elif oracle.kind is BehaviorOracleKind.NO_AIRBORNE_HOLD:
            airborne_hold_s = 0.0
            evidence_complete = True
            for role in roles:
                scheduled = scheduled_roles.get(role)
                energy = scheduled.get("energy") if scheduled is not None else None
                if not isinstance(energy, Mapping) or not isinstance(
                    energy.get("airborne_hover_s"), (int, float)
                ):
                    evidence_complete = False
                    continue
                airborne_hold_s += float(energy["airborne_hover_s"])
            observed = airborne_hold_s
            passed = evidence_complete and airborne_hold_s <= float(oracle.threshold or 0.0)
            reason = f"The retained schedule assigned {airborne_hold_s:.3f} s airborne hold."
            references = ("campaign_schedule:roles.energy.airborne_hover_s",)
        elif oracle.kind is BehaviorOracleKind.PRIORITY_PRECEDENCE:
            prioritized = sorted(
                (drone for drone in case.drones if drone.role_id in roles),
                key=lambda drone: (-drone.priority, drone.role_id),
            )
            start_times = []
            for drone in prioritized:
                route = planned_routes.get(drone.role_id)
                start = route.get("route_start_s") if route is not None else None
                if isinstance(start, (int, float)):
                    start_times.append(float(start))
            gaps = [later - earlier for earlier, later in pairwise(start_times)]
            observed = min(gaps, default=-1.0)
            passed = len(start_times) == len(prioritized) and observed >= float(
                oracle.threshold or 0.0
            )
            reason = (
                f"Minimum source-time precedence gap from higher to lower priority was "
                f"{observed:.3f} s."
            )
            references = (
                "campaign_case:drones.priority",
                "campaign_plan:selected_candidate.routes.route_start_s",
            )
        elif oracle.kind is BehaviorOracleKind.CONSTRAINT_ENFORCED:
            strategy = str(selected_candidate.get("strategy", ""))
            observed = bool(
                not case.hard_constraints.vertical_layers_allowed
                and strategy not in {"VERTICAL_LAYER", "COMBINED_TIMING_GEOMETRY"}
            )
            passed = observed
            reason = (
                "Vertical layers were forbidden and the selected strategy remained non-vertical."
                if passed
                else "The selected plan did not prove enforcement of the forbidden-layer input."
            )
            references = (
                "campaign_case:hard_constraints.vertical_layers_allowed",
                "campaign_plan:selected_candidate.strategy",
            )
        elif oracle.kind is BehaviorOracleKind.UNAFFECTED_ROLE_NONINTERFERENCE:
            delays = []
            for role in roles:
                route = planned_routes.get(role)
                delay = route.get("ground_wait_s") if route is not None else None
                if isinstance(delay, (int, float)):
                    delays.append(float(delay))
            observed = max(delays, default=float("inf"))
            passed = len(delays) == len(roles) and observed <= float(oracle.threshold or 0.0)
            reason = (
                f"Maximum planner-imposed ground delay for unaffected roles was {observed:.3f} s."
            )
            references = (
                "campaign_plan:selected_candidate.routes.ground_wait_s",
                "campaign_case:selective_conflict_roles",
            )
        elif oracle.kind is BehaviorOracleKind.EVENT_HANDLED:
            accepted_environment_events = {
                event.event_id
                for event in case.semantics.scenario_events
                if event.kind
                in {
                    ScenarioEventKind.OBSTACLE_ADDED,
                    ScenarioEventKind.OBSTACLE_MOVED,
                    ScenarioEventKind.OBSTACLE_REMOVED,
                    ScenarioEventKind.PASSAGE_CLOSED,
                    ScenarioEventKind.PASSAGE_OPENED,
                }
                and event.expected_disposition is ScenarioExpectedDisposition.ACCEPTED_UPDATE
            }
            runtime_handled_events = {
                str(record.get("event_id", ""))
                for record in execution_head_trace.get("records", ())
                if isinstance(record, Mapping)
                and str(record.get("disposition", "")) == "ACCEPTED"
                and str(record.get("execution_disposition", "")) == "DISPATCHED"
                and isinstance(record.get("replacement_trajectory_sha256_by_role"), Mapping)
                and set(record["replacement_trajectory_sha256_by_role"]) == set(role_to_vehicle)
                and isinstance(record.get("replacement_authority_sha256_by_role"), Mapping)
                and set(record["replacement_authority_sha256_by_role"]) == set(role_to_vehicle)
                and isinstance(record.get("replacement_prepared_role_ids"), Sequence)
                and not isinstance(record.get("replacement_prepared_role_ids"), (str, bytes))
                and set(record.get("replacement_prepared_role_ids", ())) == set(role_to_vehicle)
                and isinstance(record.get("replacement_dispatch_started_role_ids"), Sequence)
                and not isinstance(
                    record.get("replacement_dispatch_started_role_ids"), (str, bytes)
                )
                and set(record.get("replacement_dispatch_started_role_ids", ()))
                == set(role_to_vehicle)
                and all(
                    len(str(record.get(key, ""))) == 64
                    for key in (
                        "proposal_sha256",
                        "decision_sha256",
                        "plan_sha256",
                        "replacement_world_sha256",
                    )
                )
            }
            static_handled = bool(scenario_trace.get("all_expected_dispositions_observed", False))
            runtime_handled = accepted_environment_events.issubset(runtime_handled_events)
            observed = static_handled and runtime_handled
            passed = observed
            reason = (
                "Every injected event produced its declared admission disposition and "
                "every accepted changed-world event committed a runtime replacement."
                if passed
                else "Admission or runtime replacement evidence is missing for an event."
            )
            references = (
                "execution-bundle:campaign_scenario_trace",
                "execution-bundle:campaign_execution_head_trace",
            )
        elif oracle.kind is BehaviorOracleKind.ACCEPTED_EVENT_GOALS_CAPTURED:
            accepted_goals = [
                (event.role_id, event.replacement_goal)
                for event in case.semantics.scenario_events
                if event.expected_disposition.value == "ACCEPTED_UPDATE"
                and event.replacement_goal is not None
                and event.role_id is not None
            ]
            captured = sum(
                1
                for role_id, replacement_goal in accepted_goals
                if any(
                    point is not None and _distance(point, replacement_goal.center_m) <= 0.10
                    for sample in by_vehicle.get(role_to_vehicle[role_id], [])
                    for point in (sample.truth or sample.estimate,)
                )
            )
            ratio = captured / len(accepted_goals) if accepted_goals else 0.0
            observed = ratio
            passed = bool(accepted_goals) and ratio >= float(oracle.threshold or 1.0)
            reason = (
                f"Execution captured {captured} of {len(accepted_goals)} "
                "accepted replacement goals."
            )
            references = (
                "campaign_scenario_trace:accepted_updates",
                "telemetry.csv:ground_truth_position",
            )
        output.append(
            BehaviorOracleResult(
                oracle_id=oracle.oracle_id,
                kind=oracle.kind,
                passed=passed,
                observed_value=observed,
                threshold=oracle.threshold,
                unit=oracle.unit,
                reason=reason,
                evidence_references=references,
            )
        )
    return tuple(output)


def _longest_region_dwell_s(
    samples: Sequence[_Sample], center: Vector3, tolerance_m: float
) -> float:
    longest = 0.0
    start: float | None = None
    previous: float | None = None
    for sample in sorted(samples, key=lambda item: item.source_s):
        point = sample.truth or sample.estimate
        inside = point is not None and _distance(point, center) <= tolerance_m
        if inside:
            if start is None or (previous is not None and sample.source_s - previous > 0.20):
                start = sample.source_s
            previous = sample.source_s
            longest = max(longest, sample.source_s - start)
        else:
            start = None
            previous = None
    return longest


def _planned_region_dwell_s(
    trajectory: Mapping[str, Any] | None,
    center: Vector3,
    tolerance_m: float,
) -> float | None:
    if trajectory is None:
        return None
    timestamps = []
    for raw in trajectory.get("points", ()):
        if not isinstance(raw, Mapping):
            continue
        position = _optional_vector(raw.get("position_m"))
        raw_timestamp = raw.get("time_from_start_s")
        timestamp = float(raw_timestamp) if isinstance(raw_timestamp, (int, float)) else None
        if (
            position is not None
            and timestamp is not None
            and _distance(position, center) <= tolerance_m
        ):
            timestamps.append(timestamp)
    return max(timestamps) - min(timestamps) if len(timestamps) >= 2 else None


def _integrated_horizontal_turn(points: tuple[Vector3, ...]) -> float:
    total = 0.0
    for first, middle, last in zip(points, points[1:], points[2:], strict=False):
        first_angle = math.atan2(middle.y - first.y, middle.x - first.x)
        second_angle = math.atan2(last.y - middle.y, last.x - middle.x)
        total += abs((second_angle - first_angle + math.pi) % (2 * math.pi) - math.pi)
    return total


def _minimum_nonadjacent_distance(points: tuple[Vector3, ...]) -> float:
    return min(
        (
            _distance(first, second)
            for index, first in enumerate(points)
            for second in points[index + 2 :]
        ),
        default=float("inf"),
    )


class _Sample:
    __slots__ = (
        "battery",
        "clock_id",
        "epoch",
        "estimate",
        "faults",
        "flying",
        "recorded_s",
        "sequence",
        "source_s",
        "state",
        "truth",
        "vehicle_id",
        "velocity",
    )

    def __init__(self, row: Mapping[str, str]) -> None:
        self.vehicle_id = row.get("vehicle_id", "")
        self.source_s = _first_float(row, "simulation_timestamp_s", "source_timestamp_s")
        self.recorded_s = _utc_seconds(row.get("recorded_at_utc", ""))
        self.sequence = int(
            _float(row.get("telemetry_sequence")) or _float(row.get("event_sequence")) or 0
        )
        self.clock_id = row.get("source_clock_id") or "unknown-source-clock"
        self.epoch = int(_float(row.get("source_clock_epoch")) or 0)
        self.estimate = _row_vector(row, "position")
        self.truth = _row_vector(row, "ground_truth")
        self.velocity = _row_vector(row, "velocity", "_m_s")
        self.battery = _float(row.get("battery_percent"))
        self.state = row.get("state") or None
        self.flying = _boolean(row.get("flying"))
        self.faults = row.get("faults_json") or ""


def _analyze_vehicle(
    raw: Sequence[_Sample],
    case: CampaignCase,
    parameters: AnalysisParameters,
    *,
    planned_route_window_s: tuple[float, float] | None = None,
    planned_declared_stop_offsets_s: tuple[float, ...] = (),
) -> VehicleAnalysis:
    original_order = list(raw)
    out_of_order = sum(
        1 for before, after in pairwise(original_order) if after.source_s < before.source_s
    )
    ordered = sorted(raw, key=lambda sample: (sample.epoch, sample.source_s, sample.sequence))
    unique: list[_Sample] = []
    seen: set[tuple[int, float, int]] = set()
    duplicates = 0
    for sample in ordered:
        key = (sample.epoch, sample.source_s, sample.sequence)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(sample)
    sequences = sorted({item.sequence for item in unique if item.sequence > 0})
    missing = sum(max(0, current - previous - 1) for previous, current in pairwise(sequences))
    first, last = unique[0], unique[-1]
    source_duration = max(0.0, last.source_s - first.source_s)
    wall_duration = max(0.0, last.recorded_s - first.recorded_s)
    realtime = source_duration / wall_duration if wall_duration > 0.0 else None
    truth = [(item.source_s, item.truth) for item in unique if item.truth is not None]
    estimate = [(item.source_s, item.estimate) for item in unique if item.estimate is not None]
    motion = truth or estimate
    resampled = _resample(motion, parameters.source_resample_step_s)
    smoothed = _smooth(resampled, parameters.smoothing_window_s)
    processed_velocity = _derivative_vectors(smoothed)
    speeds = [(timestamp, _norm(value)) for timestamp, value in processed_velocity]
    tracking = [
        _distance(item.estimate, item.truth)
        for item in unique
        if item.estimate is not None and item.truth is not None
    ]
    batteries = [item.battery for item in unique if item.battery is not None]
    boundary_points = [point for _, point in motion]
    margins = [_boundary_margin(point, case) for point in boundary_points]
    timeline = _timeline(unique, motion, parameters.stop_speed_threshold_m_s)
    absolute_route_window = (
        (
            first.source_s + planned_route_window_s[0],
            first.source_s + planned_route_window_s[1],
        )
        if planned_route_window_s is not None
        else None
    )
    route_speeds = _movement_window(speeds, timeline, absolute_route_window)
    route_processed_velocity = _movement_vector_window(
        processed_velocity,
        timeline,
        absolute_route_window,
    )
    route_acceleration = _derivative_values(route_speeds)
    route_jerk = _derivative_values(route_acceleration)
    declared_stop_base_s = (
        absolute_route_window[0]
        if absolute_route_window is not None
        else timeline.route_start_source_s
    )
    declared_stop_source_s = (
        tuple(declared_stop_base_s + offset for offset in planned_declared_stop_offsets_s)
        if declared_stop_base_s is not None
        else ()
    )
    stop_count = _count_stops(
        route_speeds,
        parameters,
        declared_stop_source_s=declared_stop_source_s,
    )
    source_clock_target_error = (
        abs((timeline.route_start_source_s - first.source_s) - planned_route_window_s[0])
        if timeline.route_start_source_s is not None and planned_route_window_s is not None
        else None
    )
    estimated_touchdown = next((item.estimate for item in reversed(unique) if item.estimate), None)
    truth_touchdown = next((item.truth for item in reversed(unique) if item.truth), None)
    raw_airborne_velocity = tuple(
        item.velocity for item in unique if item.velocity is not None and item.flying is True
    )
    raw_horizontal_peak = max(
        (math.hypot(value.x, value.y) for value in raw_airborne_velocity),
        default=None,
    )
    raw_vertical_peak = max(
        (abs(value.z) for value in raw_airborne_velocity),
        default=None,
    )
    processed_horizontal_peak = max(
        (math.hypot(value.x, value.y) for _, value in route_processed_velocity),
        default=None,
    )
    processed_vertical_peak = max(
        (abs(value.z) for _, value in route_processed_velocity),
        default=None,
    )
    limits = case.hard_constraints.dynamics
    raw_gate_passed = (
        raw_horizontal_peak <= limits.maximum_horizontal_speed_m_s + 1e-9
        and raw_vertical_peak <= limits.maximum_vertical_speed_m_s + 1e-9
        if raw_horizontal_peak is not None and raw_vertical_peak is not None
        else None
    )
    processed_gate_passed = (
        processed_horizontal_peak <= limits.maximum_horizontal_speed_m_s + 1e-9
        and processed_vertical_peak <= limits.maximum_vertical_speed_m_s + 1e-9
        if processed_horizontal_peak is not None and processed_vertical_peak is not None
        else None
    )
    return VehicleAnalysis(
        vehicle_id=first.vehicle_id,
        telemetry_row_count=len(raw),
        source_clock_id=first.clock_id,
        source_clock_epoch=first.epoch,
        source_duration_s=source_duration,
        wall_duration_s=wall_duration,
        realtime_factor=realtime,
        timeline=timeline,
        battery_used_percent=(max(batteries) - batteries[-1] if batteries else None),
        truth_path_length_m=_path_length(truth),
        estimate_path_length_m=_path_length(estimate),
        tracking_rms_error_m=(
            math.sqrt(sum(value * value for value in tracking) / len(tracking))
            if tracking
            else None
        ),
        tracking_max_error_m=max(tracking) if tracking else None,
        source_clock_target_error_s=source_clock_target_error,
        minimum_boundary_margin_m=min(margins) if margins else None,
        speed_m_s=_distribution([value for _, value in route_speeds]),
        acceleration_m_s2=_distribution([value for _, value in route_acceleration]),
        jerk_m_s3=_distribution([value for _, value in route_jerk]),
        kinematics_gate_reconciliation=KinematicsGateReconciliation(
            raw_horizontal_speed_peak_m_s=raw_horizontal_peak,
            raw_vertical_speed_peak_m_s=raw_vertical_peak,
            processed_horizontal_speed_peak_m_s=processed_horizontal_peak,
            processed_vertical_speed_peak_m_s=processed_vertical_peak,
            maximum_horizontal_speed_m_s=limits.maximum_horizontal_speed_m_s,
            maximum_vertical_speed_m_s=limits.maximum_vertical_speed_m_s,
            raw_gate_passed=raw_gate_passed,
            processed_gate_passed=processed_gate_passed,
            gate_disagreement=(
                raw_gate_passed is not None
                and processed_gate_passed is not None
                and raw_gate_passed is not processed_gate_passed
            ),
        ),
        unintended_stop_count=stop_count,
        duplicate_sample_count=duplicates,
        missing_sequence_count=missing,
        out_of_order_sample_count=out_of_order,
        terminal_state=last.state,
        estimated_touchdown_m=estimated_touchdown,
        truth_touchdown_m=truth_touchdown,
    )


def _pair_separation(
    first: Sequence[_Sample], second: Sequence[_Sample], parameters: AnalysisParameters
) -> PairSeparation:
    left = sorted(first, key=lambda item: item.recorded_s)
    right = sorted(second, key=lambda item: item.recorded_s)
    right_index = 0
    estimated: list[tuple[float, float]] = []
    truth: list[tuple[float, float]] = []
    for left_sample in left:
        while right_index + 1 < len(right) and abs(
            right[right_index + 1].recorded_s - left_sample.recorded_s
        ) <= abs(right[right_index].recorded_s - left_sample.recorded_s):
            right_index += 1
        candidate = right[right_index]
        if (
            abs(candidate.recorded_s - left_sample.recorded_s)
            > parameters.fleet_alignment_tolerance_s
        ):
            continue
        if left_sample.estimate is not None and candidate.estimate is not None:
            estimated.append(
                (left_sample.recorded_s, _distance(left_sample.estimate, candidate.estimate))
            )
        if left_sample.truth is not None and candidate.truth is not None:
            truth.append((left_sample.recorded_s, _distance(left_sample.truth, candidate.truth)))
    closest = min(truth, key=lambda item: item[1]) if truth else None
    ids = tuple(sorted((left[0].vehicle_id, right[0].vehicle_id)))
    return PairSeparation(
        vehicle_ids=(ids[0], ids[1]),
        aligned_sample_count=max(len(estimated), len(truth)),
        minimum_estimated_separation_m=min((item[1] for item in estimated), default=None),
        minimum_truth_separation_m=closest[1] if closest else None,
        closest_recorded_at_utc=(datetime.fromtimestamp(closest[0], UTC) if closest else None),
    )


def _classify(
    outcome: str,
    vehicles: Sequence[VehicleAnalysis],
    manifest: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> tuple[CauseClassification, tuple[CauseClassification, ...]]:
    if outcome.upper() in {"SUCCEEDED", "PASSED"}:
        return CauseClassification(
            stage=RootCauseStage.UNKNOWN,
            confidence=1.0,
            reason="the mission completed and no failure root cause is applicable",
            evidence_references=("manifest:status",),
        ), ()
    searchable = json.dumps([manifest, bundle], sort_keys=True, default=str).upper()
    if "MISSION_TIMEOUT" in searchable or "WATCHDOG" in searchable:
        primary = CauseClassification(
            stage=RootCauseStage.SIM_TIMING,
            confidence=0.98,
            reason=(
                "the wall-clock watchdog expired while the source-clock schedule "
                "was still progressing"
            ),
            evidence_references=(
                "bundle:faults",
                "manifest:reason_code",
                "analysis:realtime_factor",
            ),
            counter_evidence=("no separation or route-boundary failure identified",),
        )
        contributors: tuple[CauseClassification, ...] = ()
        if any((item.realtime_factor or 1.0) < 0.95 for item in vehicles):
            contributors = (
                CauseClassification(
                    stage=RootCauseStage.EVIDENCE_DELIVERY,
                    confidence=0.55,
                    reason=(
                        "wall delivery lag is visible but does not by itself prove "
                        "a UI or network fault"
                    ),
                    evidence_references=("analysis:source_vs_wall_duration",),
                    counter_evidence=("vehicle transport telemetry is modeled",),
                ),
            )
        return primary, contributors
    if any(
        item.minimum_boundary_margin_m is not None and item.minimum_boundary_margin_m < 0
        for item in vehicles
    ):
        return CauseClassification(
            stage=RootCauseStage.PLANNER,
            confidence=0.95,
            reason="observed path left the immutable case flight volume",
            evidence_references=("analysis:minimum_boundary_margin_m",),
        ), ()
    return CauseClassification(
        stage=RootCauseStage.UNKNOWN,
        confidence=0.25,
        reason="the retained evidence does not identify a single supported failure stage",
        evidence_references=("manifest", "bundle", "telemetry"),
    ), ()


def _parse_csv(content: bytes) -> list[_Sample]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    required = {"vehicle_id", "recorded_at_utc", "source_timestamp_s"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("telemetry CSV does not satisfy run-telemetry-v1 identity columns")
    return [_Sample(row) for row in reader if row.get("vehicle_id")]


def _motion_guard_verdict(
    vector: MotionQualityVector,
    contract: MotionQualityContract,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    checks: tuple[tuple[str, float | int | bool | None, bool], ...] = (
        (
            "speed_compliance_fraction",
            vector.speed_compliance_fraction,
            vector.speed_compliance_fraction is not None
            and vector.speed_compliance_fraction >= contract.minimum_speed_band_coverage_fraction,
        ),
        (
            "speed_ripple_m_s",
            vector.speed_ripple_m_s,
            vector.speed_ripple_m_s is not None
            and vector.speed_ripple_m_s <= contract.maximum_speed_ripple_m_s,
        ),
        (
            "acceleration_p95_m_s2",
            vector.acceleration_p95_m_s2,
            vector.acceleration_p95_m_s2 is not None
            and vector.acceleration_p95_m_s2 <= contract.maximum_acceleration_m_s2,
        ),
        (
            "jerk_p95_m_s3",
            vector.jerk_p95_m_s3,
            vector.jerk_p95_m_s3 is not None and vector.jerk_p95_m_s3 <= contract.maximum_jerk_m_s3,
        ),
        (
            "angular_rate_p95_rad_s",
            vector.angular_rate_p95_rad_s,
            vector.angular_rate_p95_rad_s is not None
            and vector.angular_rate_p95_rad_s <= contract.maximum_angular_rate_p95_rad_s,
        ),
        (
            "minimum_motor_thrust_headroom_n",
            vector.minimum_motor_thrust_headroom_n,
            vector.minimum_motor_thrust_headroom_n is not None
            and vector.minimum_motor_thrust_headroom_n >= contract.minimum_motor_thrust_headroom_n,
        ),
        (
            "motor_spread_p95_percent",
            vector.motor_spread_p95_percent,
            vector.motor_spread_p95_percent is not None
            and vector.motor_spread_p95_percent <= contract.maximum_motor_spread_p95_percent,
        ),
        (
            "motor_saturation_fraction",
            vector.motor_saturation_fraction,
            vector.motor_saturation_fraction is not None
            and vector.motor_saturation_fraction <= contract.maximum_motor_saturation_fraction,
        ),
        (
            "motor_differential_sign_agreement_fraction",
            vector.motor_differential_sign_agreement_fraction,
            vector.motor_differential_sign_agreement_fraction is not None
            and vector.motor_differential_sign_agreement_fraction
            >= contract.minimum_motor_differential_sign_agreement_fraction,
        ),
        (
            "motor_differential_normalized_error_p95",
            vector.motor_differential_normalized_error_p95,
            vector.motor_differential_normalized_error_p95 is not None
            and vector.motor_differential_normalized_error_p95
            <= contract.maximum_motor_differential_normalized_error_p95,
        ),
        (
            "electrical_energy_used_j",
            vector.electrical_energy_used_j,
            vector.electrical_energy_used_j is not None
            and vector.electrical_energy_used_j <= contract.maximum_electrical_energy_used_j,
        ),
        (
            "tracking_rms_m",
            vector.tracking_rms_m,
            vector.tracking_rms_m is not None
            and vector.tracking_rms_m <= contract.maximum_path_tube_error_m,
        ),
        (
            "path_tube_max_error_m",
            vector.path_tube_max_error_m,
            vector.path_tube_max_error_m is not None
            and vector.path_tube_max_error_m <= contract.maximum_path_tube_error_m,
        ),
        (
            "minimum_clearance_m",
            vector.minimum_clearance_m,
            vector.minimum_clearance_m is not None
            and vector.minimum_clearance_m >= contract.minimum_clearance_m,
        ),
        (
            "collision_count",
            vector.collision_count,
            vector.collision_count is not None
            and vector.collision_count <= contract.maximum_collision_count,
        ),
        (
            "checkpoint_hold_conformance_fraction",
            vector.checkpoint_hold_conformance_fraction,
            vector.checkpoint_hold_conformance_fraction is not None
            and vector.checkpoint_hold_conformance_fraction
            >= contract.minimum_checkpoint_hold_conformance_fraction,
        ),
        (
            "minimum_continuous_knot_speed_ratio",
            vector.minimum_continuous_knot_speed_ratio,
            vector.minimum_continuous_knot_speed_ratio is not None
            and vector.minimum_continuous_knot_speed_ratio
            >= contract.minimum_continuous_knot_speed_ratio,
        ),
        (
            "unintended_fly_through_stop_count",
            vector.unintended_fly_through_stop_count,
            vector.unintended_fly_through_stop_count is not None
            and vector.unintended_fly_through_stop_count
            <= contract.maximum_unintended_fly_through_stop_count,
        ),
        (
            "terminal_secondary_peak_m_s",
            vector.terminal_secondary_peak_m_s,
            vector.terminal_secondary_peak_m_s is not None
            and vector.terminal_secondary_peak_m_s <= contract.maximum_terminal_secondary_peak_m_s,
        ),
        (
            "terminal_reversal_count",
            vector.terminal_reversal_count,
            vector.terminal_reversal_count is not None
            and vector.terminal_reversal_count <= contract.maximum_terminal_reversal_count,
        ),
        (
            "duration_s",
            vector.duration_s,
            contract.maximum_duration_s is None or vector.duration_s <= contract.maximum_duration_s,
        ),
        (
            "supervisor_safety_gate_passed",
            vector.supervisor_safety_gate_passed,
            not contract.supervisor_safety_gate_required
            or vector.supervisor_safety_gate_passed is True,
        ),
    )
    not_applicable: set[str] = set()
    if contract.target_speed_m_s is None:
        not_applicable.add("speed_compliance_fraction")
    if contract.traversal_mode is TraversalMode.CONTINUOUS_FLY_THROUGH:
        not_applicable.add("checkpoint_hold_conformance_fraction")
    else:
        not_applicable.update(
            {
                "minimum_continuous_knot_speed_ratio",
                "unintended_fly_through_stop_count",
            }
        )
    missing = tuple(
        guard_id
        for guard_id, observed, _passed in checks
        if observed is None and guard_id not in not_applicable
    )
    failed = tuple(
        guard_id
        for guard_id, observed, passed in checks
        if observed is not None and not passed and guard_id not in not_applicable
    )
    return failed, missing


def _secondary_peak_prominence(values: Sequence[float]) -> float:
    if len(values) < 3:
        return 0.0
    peaks = [
        value - max(values[index - 1], values[index + 1])
        for index, value in enumerate(values[1:-1], start=1)
        if value > values[index - 1] and value > values[index + 1]
    ]
    return max(peaks, default=0.0)


def _terminal_reversal_count(
    values: Sequence[Vector3],
    threshold_m_s: float = 0.01,
    *,
    direction: Vector3 | None = None,
) -> int:
    if direction is None or _norm(direction) <= 1e-12:
        direction = next((value for value in values if _norm(value) > threshold_m_s), None)
    if direction is None:
        return 0
    unit = Vector3(
        x=direction.x / _norm(direction),
        y=direction.y / _norm(direction),
        z=direction.z / _norm(direction),
    )
    progress = [value.x * unit.x + value.y * unit.y + value.z * unit.z for value in values]
    signs = [1 if value > 0.0 else -1 for value in progress if abs(value) > threshold_m_s]
    return sum(before != after for before, after in pairwise(signs))


def _distance_to_polyline(point: Vector3, route: Sequence[Vector3]) -> float:
    return min(_distance_to_segment(point, before, after) for before, after in pairwise(route))


def _distance_to_segment(point: Vector3, before: Vector3, after: Vector3) -> float:
    segment = Vector3(
        x=after.x - before.x,
        y=after.y - before.y,
        z=after.z - before.z,
    )
    offset = Vector3(
        x=point.x - before.x,
        y=point.y - before.y,
        z=point.z - before.z,
    )
    denominator = segment.x**2 + segment.y**2 + segment.z**2
    if denominator <= 1e-15:
        return _distance(point, before)
    factor = max(
        0.0,
        min(
            1.0,
            (offset.x * segment.x + offset.y * segment.y + offset.z * segment.z) / denominator,
        ),
    )
    projection = Vector3(
        x=before.x + factor * segment.x,
        y=before.y + factor * segment.y,
        z=before.z + factor * segment.z,
    )
    return _distance(point, projection)


def _resample(
    values: Sequence[tuple[float, Vector3]], step_s: float
) -> list[tuple[float, Vector3]]:
    if len(values) < 2:
        return list(values)
    deduplicated: list[tuple[float, Vector3]] = []
    for timestamp, point in sorted(values, key=lambda item: item[0]):
        if deduplicated and math.isclose(timestamp, deduplicated[-1][0], abs_tol=1e-9):
            deduplicated[-1] = (timestamp, point)
        else:
            deduplicated.append((timestamp, point))
    if len(deduplicated) < 2:
        return deduplicated
    output: list[tuple[float, Vector3]] = []
    index = 0
    timestamp = deduplicated[0][0]
    end = deduplicated[-1][0]
    while timestamp <= end + step_s * 0.25:
        while index + 1 < len(deduplicated) - 1 and deduplicated[index + 1][0] < timestamp:
            index += 1
        before, after = deduplicated[index], deduplicated[index + 1]
        span = after[0] - before[0]
        factor = 0.0 if span <= 0.0 else max(0.0, min(1.0, (timestamp - before[0]) / span))
        output.append((timestamp, _lerp(before[1], after[1], factor)))
        timestamp += step_s
    return output


def _smooth(
    values: Sequence[tuple[float, Vector3]], window_s: float
) -> list[tuple[float, Vector3]]:
    if window_s <= 0.0 or len(values) < 3:
        return list(values)
    half = window_s / 2.0
    output: list[tuple[float, Vector3]] = []
    for timestamp, _ in values:
        selected = [
            (sample_time, point)
            for sample_time, point in values
            if abs(sample_time - timestamp) <= half
        ]
        output.append(
            (
                timestamp,
                Vector3(
                    x=_local_linear_value(selected, timestamp, "x"),
                    y=_local_linear_value(selected, timestamp, "y"),
                    z=_local_linear_value(selected, timestamp, "z"),
                ),
            )
        )
    return output


def _local_linear_value(
    samples: Sequence[tuple[float, Vector3]], timestamp: float, axis: str
) -> float:
    """Smooth one axis while preserving constant-velocity motion at window edges."""

    if len(samples) == 1:
        return float(getattr(samples[0][1], axis))
    mean_time = sum(item[0] for item in samples) / len(samples)
    mean_value = sum(float(getattr(item[1], axis)) for item in samples) / len(samples)
    denominator = sum((item[0] - mean_time) ** 2 for item in samples)
    if denominator <= 1e-15:
        return mean_value
    slope = (
        sum(
            (item[0] - mean_time) * (float(getattr(item[1], axis)) - mean_value) for item in samples
        )
        / denominator
    )
    return mean_value + slope * (timestamp - mean_time)


def _derivative_norms(values: Sequence[tuple[float, Vector3]]) -> list[tuple[float, float]]:
    return [
        (after[0], _distance(after[1], before[1]) / (after[0] - before[0]))
        for before, after in pairwise(values)
        if after[0] > before[0]
    ]


def _derivative_vectors(
    values: Sequence[tuple[float, Vector3]],
) -> list[tuple[float, Vector3]]:
    return [
        (
            after[0],
            Vector3(
                x=(after[1].x - before[1].x) / (after[0] - before[0]),
                y=(after[1].y - before[1].y) / (after[0] - before[0]),
                z=(after[1].z - before[1].z) / (after[0] - before[0]),
            ),
        )
        for before, after in pairwise(values)
        if after[0] > before[0]
    ]


def _derivative_values(values: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    return [
        (after[0], abs(after[1] - before[1]) / (after[0] - before[0]))
        for before, after in pairwise(values)
        if after[0] > before[0]
    ]


def _timeline(
    samples: Sequence[_Sample], motion: Sequence[tuple[float, Vector3]], speed_threshold: float
) -> VehicleTimeline:
    takeoff = next((item.source_s for item in samples if item.flying), None)
    takeoff_complete = next(
        (
            item.source_s
            for item in samples
            if item.state is not None and item.state.upper() == "FLYING"
        ),
        takeoff,
    )
    speeds = _horizontal_derivative_norms(motion)
    route = next((time_s for time_s, speed in speeds if speed > speed_threshold), None)
    landing = next(
        (item.source_s for item in samples if item.state and "LAND" in item.state.upper()),
        None,
    )
    touchdown = next((item.source_s for item in reversed(samples) if item.flying is False), None)
    wait = (
        max(0.0, route - takeoff_complete)
        if takeoff_complete is not None and route is not None
        else None
    )
    return VehicleTimeline(
        first_source_s=samples[0].source_s,
        last_source_s=samples[-1].source_s,
        takeoff_source_s=takeoff,
        takeoff_complete_source_s=takeoff_complete,
        route_start_source_s=route,
        landing_start_source_s=landing,
        touchdown_source_s=touchdown,
        airborne_wait_before_route_s=wait,
    )


def _horizontal_derivative_norms(
    values: Sequence[tuple[float, Vector3]],
) -> list[tuple[float, float]]:
    return [
        (
            after[0],
            math.hypot(after[1].x - before[1].x, after[1].y - before[1].y) / (after[0] - before[0]),
        )
        for before, after in pairwise(values)
        if after[0] > before[0]
    ]


def _count_stops(
    values: Sequence[tuple[float, float]],
    parameters: AnalysisParameters,
    *,
    declared_stop_source_s: Sequence[float] = (),
) -> int:
    count = 0
    start: float | None = None
    for timestamp, speed in values:
        if speed <= parameters.stop_speed_threshold_m_s:
            start = timestamp if start is None else start
        elif start is not None:
            is_terminal_capture_band = (
                values and values[-1][0] - timestamp <= parameters.stop_persistence_s
            )
            is_declared = any(
                start - parameters.stop_persistence_s
                <= declared
                <= timestamp + parameters.stop_persistence_s
                for declared in declared_stop_source_s
            )
            if (
                timestamp - start >= parameters.stop_persistence_s
                and not is_terminal_capture_band
                and not is_declared
            ):
                count += 1
            start = None
    # A trailing low-speed interval is the accepted route/goal endpoint. Only a
    # low-speed interval followed by renewed motion is an unintended internal stop.
    return count


def _movement_window(
    values: Sequence[tuple[float, float]],
    timeline: VehicleTimeline,
    planned_window_s: tuple[float, float] | None,
) -> list[tuple[float, float]]:
    if timeline.route_start_source_s is None and planned_window_s is None:
        return list(values)
    start = timeline.route_start_source_s
    if start is None:
        assert planned_window_s is not None
        start = planned_window_s[0]
    end_candidates = [
        value
        for value in (
            planned_window_s[1] if planned_window_s is not None else None,
            timeline.landing_start_source_s,
        )
        if value is not None
    ]
    end = min(end_candidates) if end_candidates else None
    return [item for item in values if item[0] >= start and (end is None or item[0] < end)]


def _movement_vector_window(
    values: Sequence[tuple[float, Vector3]],
    timeline: VehicleTimeline,
    planned_window_s: tuple[float, float] | None,
) -> list[tuple[float, Vector3]]:
    if timeline.route_start_source_s is None and planned_window_s is None:
        return list(values)
    start = timeline.route_start_source_s
    if start is None:
        assert planned_window_s is not None
        start = planned_window_s[0]
    end_candidates = [
        value
        for value in (
            planned_window_s[1] if planned_window_s is not None else None,
            timeline.landing_start_source_s,
        )
        if value is not None
    ]
    end = min(end_candidates) if end_candidates else None
    return [item for item in values if item[0] >= start and (end is None or item[0] < end)]


def _distribution(values: Sequence[float]) -> MetricDistribution:
    if not values:
        return MetricDistribution(sample_count=0)
    ordered = sorted(values)
    return MetricDistribution(
        sample_count=len(ordered),
        p50=_percentile(ordered, 0.50),
        p95=_percentile(ordered, 0.95),
        peak=max(ordered),
    )


def _percentile(values: Sequence[float], quantile: float) -> float:
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _path_length(values: Sequence[tuple[float, Vector3]]) -> float | None:
    if not values:
        return None
    return sum(_distance(before[1], after[1]) for before, after in pairwise(values))


def _boundary_margin(point: Vector3, case: CampaignCase) -> float:
    volume = case.hard_constraints.flight_volume
    return min(
        point.x - volume.minimum_m.x,
        volume.maximum_m.x - point.x,
        point.y - volume.minimum_m.y,
        volume.maximum_m.y - point.y,
        point.z - volume.minimum_m.z,
        volume.maximum_m.z - point.z,
    )


def _minimum_route_clearance(
    case: CampaignCase,
    samples: Sequence[_Sample],
    start_source_s: float | None,
    end_source_s: float | None,
) -> float | None:
    if start_source_s is None or end_source_s is None:
        return None
    points = [
        sample.truth or sample.estimate
        for sample in samples
        if start_source_s <= sample.source_s <= end_source_s
        and (sample.truth is not None or sample.estimate is not None)
    ]
    if not points:
        return None
    nominal_vehicle_radius_m = 0.055
    margins = [_boundary_margin(point, case) - nominal_vehicle_radius_m for point in points]
    keep_out = (
        case.semantics.environment_constraints.keep_out_regions
        if case.semantics is not None
        else ()
    )
    for point in points:
        for region in keep_out:
            dx = max(region.minimum_m.x - point.x, 0.0, point.x - region.maximum_m.x)
            dy = max(region.minimum_m.y - point.y, 0.0, point.y - region.maximum_m.y)
            dz = max(region.minimum_m.z - point.z, 0.0, point.z - region.maximum_m.z)
            margins.append(math.sqrt(dx * dx + dy * dy + dz * dz) - nominal_vehicle_radius_m)
    return min(margins)


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )


def _norm(value: Vector3) -> float:
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


def _lerp(first: Vector3, second: Vector3, factor: float) -> Vector3:
    return Vector3(
        x=first.x + (second.x - first.x) * factor,
        y=first.y + (second.y - first.y) * factor,
        z=first.z + (second.z - first.z) * factor,
    )


def _row_vector(row: Mapping[str, str], prefix: str, suffix: str = "_m") -> Vector3 | None:
    values = tuple(_float(row.get(f"{prefix}_{axis}{suffix}")) for axis in ("x", "y", "z"))
    if any(value is None for value in values):
        return None
    return Vector3(x=values[0], y=values[1], z=values[2])


def _first_float(row: Mapping[str, str], *keys: str) -> float:
    for key in keys:
        value = _float(row.get(key))
        if value is not None:
            return value
    raise ValueError(f"telemetry row has no source timestamp in {keys}")


def _float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _boolean(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.strip().lower() in {"1", "true", "yes"}


def _utc_seconds(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _load_data(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _optional_vector(value: Any) -> Vector3 | None:
    return Vector3.model_validate(value) if isinstance(value, Mapping) else None


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None and str(value) else None


def _optional_nonnegative_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value >= 0.0 else None


def _goal_capture_for_vehicle(context: Mapping[str, Any], vehicle_id: str) -> Mapping[str, Any]:
    fleet_result = context.get("fleet_result")
    if not isinstance(fleet_result, Mapping):
        return {}
    children = fleet_result.get("child_results")
    if not isinstance(children, list):
        return {}
    for child in children:
        if not isinstance(child, Mapping) or str(child.get("vehicle_id")) != vehicle_id:
            continue
        mission_result = child.get("mission_result")
        if not isinstance(mission_result, Mapping):
            return {}
        captures = mission_result.get("goal_captures")
        if not isinstance(captures, list):
            return {}
        return next(
            (capture for capture in reversed(captures) if isinstance(capture, Mapping)),
            {},
        )
    return {}


def _displayed_marker(bundle: Mapping[str, Any], role_id: str) -> Vector3 | None:
    diagnostics = bundle.get("display_diagnostics")
    if not isinstance(diagnostics, Mapping):
        return None
    markers = diagnostics.get("goal_markers_m")
    if not isinstance(markers, Mapping):
        return None
    return _optional_vector(markers.get(role_id))


def _optional_sha(value: Any) -> str | None:
    text = str(value) if value is not None else ""
    return (
        text
        if len(text) == 64 and all(character in "0123456789abcdef" for character in text)
        else None
    )


def _campaign_arrival(plan: Mapping[str, Any], role_id: str) -> Vector3 | None:
    candidates = plan.get("retained_candidates")
    selected_index = plan.get("selected_candidate_index")
    if not isinstance(candidates, list) or not isinstance(selected_index, int):
        return None
    if selected_index < 0 or selected_index >= len(candidates):
        return None
    selected = candidates[selected_index]
    if not isinstance(selected, Mapping):
        return None
    routes = selected.get("routes")
    if not isinstance(routes, list):
        return None
    for route in routes:
        if not isinstance(route, Mapping) or str(route.get("role_id")) != role_id:
            continue
        points = route.get("points_m")
        if isinstance(points, list) and points:
            return _optional_vector(points[-1])
    return None


def _campaign_route_window(context: Mapping[str, Any], role_id: str) -> tuple[float, float] | None:
    schedule = context.get("campaign_schedule")
    if not isinstance(schedule, Mapping):
        return None
    roles = schedule.get("roles")
    if not isinstance(roles, list):
        return None
    for role in roles:
        if not isinstance(role, Mapping) or str(role.get("role_id")) != role_id:
            continue
        actions = role.get("actions")
        if not isinstance(actions, list):
            return None
        for action in actions:
            if not isinstance(action, Mapping) or action.get("kind") != "START_ROUTE":
                continue
            start = action.get("starts_at_source_s")
            end = action.get("ends_at_source_s")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                return float(start), float(end)
    return None


def _declared_stop_offsets(trajectory: Any) -> tuple[float, ...]:
    """Return internal, hash-bound trajectory stops in route-relative source time."""

    if not isinstance(trajectory, Mapping):
        return ()
    points = trajectory.get("points")
    sequences = trajectory.get("declared_stop_sequences")
    if not isinstance(points, list) or not isinstance(sequences, list):
        return ()
    output = []
    for sequence in sequences:
        if not isinstance(sequence, int) or sequence <= 1 or sequence >= len(points):
            continue
        point = points[sequence - 1]
        if not isinstance(point, Mapping):
            continue
        timestamp = point.get("time_from_start_s")
        if isinstance(timestamp, (int, float)):
            output.append(float(timestamp))
    return tuple(sorted(set(output)))
