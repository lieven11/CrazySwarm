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

from pydantic import Field

from crazyswarm_app.campaign.models import CampaignCase
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
    coordinate_conversion_chain: tuple[str, ...] = ("world -> world",)


class CauseClassification(ContractModel):
    stage: RootCauseStage
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_references: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()


class MissionAnalysis(ContractModel):
    schema_version: Literal[1] = 1
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
    manifest_sha256: SHA256
    bundle_sha256: SHA256
    csv_sha256: SHA256
    vehicles: tuple[VehicleAnalysis, ...]
    pair_separation: tuple[PairSeparation, ...]
    minimum_truth_separation_m: float | None = Field(default=None, ge=0.0)
    landing: tuple[LandingComparison, ...]
    primary_cause: CauseClassification
    contributors: tuple[CauseClassification, ...] = ()
    analysis_sha256: SHA256

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"analysis_sha256"})


class ModeComparison(ContractModel):
    schema_version: Literal[1] = 1
    accelerated_analysis_sha256: SHA256
    realtime_analysis_sha256: SHA256
    maximum_source_clock_target_error_difference_s: float | None = Field(
        default=None, ge=0.0
    )
    maximum_truth_path_length_difference_m: float | None = Field(default=None, ge=0.0)
    maximum_tracking_rms_difference_m: float | None = Field(default=None, ge=0.0)
    minimum_separation_difference_m: float | None = Field(default=None, ge=0.0)
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

    def maximum_difference(attribute: str) -> float | None:
        differences = []
        for vehicle_id in sorted(accelerated_by_vehicle):
            first = getattr(accelerated_by_vehicle[vehicle_id], attribute)
            second = getattr(realtime_by_vehicle[vehicle_id], attribute)
            if first is not None and second is not None:
                differences.append(abs(float(first) - float(second)))
        return max(differences, default=None)

    target = maximum_difference("source_clock_target_error_s")
    path = maximum_difference("truth_path_length_m")
    tracking = maximum_difference("tracking_rms_error_m")
    separation = (
        abs(accelerated.minimum_truth_separation_m - realtime.minimum_truth_separation_m)
        if accelerated.minimum_truth_separation_m is not None
        and realtime.minimum_truth_separation_m is not None
        else None
    )
    limits = case.hard_constraints.mode_comparison
    gates = (
        target is not None
        and target <= limits.maximum_source_clock_target_error_difference_s,
        path is not None and path <= limits.maximum_truth_path_length_difference_m,
        tracking is not None and tracking <= limits.maximum_tracking_rms_difference_m,
        separation is not None
        and separation <= limits.maximum_minimum_separation_difference_m,
    )
    payload: dict[str, Any] = {
        "accelerated_analysis_sha256": accelerated.analysis_sha256,
        "realtime_analysis_sha256": realtime.analysis_sha256,
        "maximum_source_clock_target_error_difference_s": target,
        "maximum_truth_path_length_difference_m": path,
        "maximum_tracking_rms_difference_m": tracking,
        "minimum_separation_difference_m": separation,
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
    assignments = _mapping(
        bundle.get("assignments") or context.get("assignments", {}), "assignments"
    )
    analyses: list[VehicleAnalysis] = []
    landing: list[LandingComparison] = []
    for vehicle_id in sorted(by_vehicle):
        samples = by_vehicle[vehicle_id]
        role_id = next(
            (str(role) for role, assigned in assignments.items() if str(assigned) == vehicle_id),
            vehicle_id,
        )
        route_window = _campaign_route_window(context, role_id)
        analysis = _analyze_vehicle(
            samples,
            case,
            selected,
            planned_route_window_s=route_window,
        )
        analyses.append(analysis)
        drone = drones_by_role.get(role_id)
        if drone is not None:
            plan = _mapping(bundle.get("accepted_plan", {}), "accepted_plan")
            role_plan = _mapping(_mapping(plan.get("roles", {}), "roles").get(role_id, {}), "role")
            campaign_plan = _mapping(
                bundle.get("campaign_plan") or context.get("campaign_plan", {}),
                "campaign_plan",
            )
            campaign_arrival = _campaign_arrival(campaign_plan, role_id)
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
                    displayed_goal_marker_m=_displayed_marker(bundle, role_id),
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
        "pair_separation": pairs,
        "minimum_truth_separation_m": min(truth_minima) if truth_minima else None,
        "landing": tuple(landing),
        "primary_cause": primary,
        "contributors": contributors,
    }
    return MissionAnalysis(**payload, analysis_sha256=canonical_sha256(payload))


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
    speeds = _derivative_norms(smoothed)
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
    route_acceleration = _derivative_values(route_speeds)
    route_jerk = _derivative_values(route_acceleration)
    stop_count = _count_stops(route_speeds, parameters)
    source_clock_target_error = (
        abs((timeline.route_start_source_s - first.source_s) - planned_route_window_s[0])
        if timeline.route_start_source_s is not None and planned_route_window_s is not None
        else None
    )
    estimated_touchdown = next((item.estimate for item in reversed(unique) if item.estimate), None)
    truth_touchdown = next((item.truth for item in reversed(unique) if item.truth), None)
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
            (item[0] - mean_time) * (float(getattr(item[1], axis)) - mean_value)
            for item in samples
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


def _count_stops(values: Sequence[tuple[float, float]], parameters: AnalysisParameters) -> int:
    count = 0
    start: float | None = None
    for timestamp, speed in values:
        if speed <= parameters.stop_speed_threshold_m_s:
            start = timestamp if start is None else start
        elif start is not None:
            is_terminal_capture_band = (
                values and values[-1][0] - timestamp <= parameters.stop_persistence_s
            )
            if (
                timestamp - start >= parameters.stop_persistence_s
                and not is_terminal_capture_band
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
    return [
        item
        for item in values
        if item[0] >= start
        and (end is None or item[0] < end)
    ]


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


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )


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


def _campaign_route_window(
    context: Mapping[str, Any], role_id: str
) -> tuple[float, float] | None:
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
