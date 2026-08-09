from __future__ import annotations

import hashlib
from collections import defaultdict
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.observability.evaluation import (
    EvaluationStatus,
    MissionExecutionEvaluation,
)
from crazyswarm_app.planning.curriculum import (
    BorderVariant,
    MissionCaseTemplate,
    generate_progressive_curriculum,
)
from crazyswarm_app.safety.policy import SafetyPolicy, SafetyPolicyOverride
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.faults import FaultType, FaultWindow
from crazyswarm_app.simulation.models import SimulationConfig

ROBUSTNESS_CONTRACT = "mission-robustness-matrix-v1"
ROBUSTNESS_VERSION = "1.0.0"
DEFAULT_ROBUSTNESS_SEEDS = (109, 811)
_SAFE_FAILURE_STATUSES = frozenset({"ABORTED", "FAILED", "DEGRADED"})
_HARD_FINDINGS = frozenset(
    {
        "CRITICAL_SAFETY_VIOLATION",
        "EVIDENCE_INCOMPLETE",
        "PLAN_IDENTITY_MISMATCH",
        "UNSAFE_TERMINAL_STATE",
        "BOUNDARY_MARGIN_VIOLATION",
        "EXECUTION_IDENTITY_MISMATCH",
        "GOAL_MARGIN_VIOLATION",
        "SEPARATION_MARGIN_VIOLATION",
        "WARNING_MARGIN_VIOLATION",
    }
)


class RobustnessProfileKind(StrEnum):
    NOMINAL_MULTI_SEED = "NOMINAL_MULTI_SEED"
    SENSOR_NOISE = "SENSOR_NOISE"
    TRANSPORT_LATENCY = "TRANSPORT_LATENCY"
    CLOCK_RATE_VARIATION = "CLOCK_RATE_VARIATION"
    OBSERVATION_LOSS = "OBSERVATION_LOSS"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    BOUNDED_RECOVERY = "BOUNDED_RECOVERY"


class ExpectedDisposition(StrEnum):
    SUCCESS = "SUCCESS"
    SAFE_FAILURE = "SAFE_FAILURE"


class RobustnessSelectedCase(ContractModel):
    case_id: Identifier
    case_sha256: SHA256
    mission_filename: str
    mission_source: str
    mission_source_sha256: SHA256
    role_count: int = Field(ge=1, le=3)
    require_goal_capture: bool
    warning_separation_m: float | None = Field(default=None, gt=0.0)
    critical_separation_m: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def source_identity_matches(self) -> RobustnessSelectedCase:
        if hashlib.sha256(self.mission_source.encode("utf-8")).hexdigest() != (
            self.mission_source_sha256
        ):
            raise ValueError("robustness case source hash does not match source")
        return self


class RobustnessProfile(ContractModel):
    profile_id: Identifier
    kind: RobustnessProfileKind
    target_case_ids: tuple[Identifier, ...]
    seeds: tuple[int, ...]
    clock_modes: tuple[ClockMode, ...]
    repetitions: int = Field(default=1, ge=1, le=5)
    simulation_overrides: dict[Identifier, float] = Field(default_factory=dict)
    safety_overrides: dict[Identifier, float] = Field(default_factory=dict)
    faults: tuple[FaultWindow, ...] = ()
    expected_disposition: ExpectedDisposition
    accepted_reason_codes: tuple[Identifier, ...] = ()
    minimum_pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    maximum_warning_samples: int = Field(default=0, ge=0)
    maximum_critical_samples: int = Field(default=0, ge=0)
    minimum_boundary_margin_m: float = 0.0
    minimum_goal_capture_margin_m: float = 0.0
    minimum_separation_margin_m: float = 0.0
    profile_sha256: SHA256

    @model_validator(mode="after")
    def bounded_and_identified(self) -> RobustnessProfile:
        if not self.target_case_ids or len(set(self.target_case_ids)) != len(self.target_case_ids):
            raise ValueError("robustness profile target cases must be non-empty and unique")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("robustness profile seeds must be non-empty and unique")
        if not self.clock_modes or len(set(self.clock_modes)) != len(self.clock_modes):
            raise ValueError("robustness profile clock modes must be non-empty and unique")
        if (
            self.expected_disposition is ExpectedDisposition.SAFE_FAILURE
            and not self.accepted_reason_codes
        ):
            raise ValueError("safe-failure profile requires an accepted reason")
        simulation_payload = SimulationConfig().model_dump(mode="python")
        simulation_payload.update(self.simulation_overrides)
        SimulationConfig.model_validate(simulation_payload)
        SafetyPolicy().tighten(SafetyPolicyOverride.model_validate(self.safety_overrides))
        if self.profile_sha256 != canonical_sha256(
            self.model_dump(mode="python", exclude={"profile_sha256"})
        ):
            raise ValueError("robustness profile hash does not match its contract")
        return self


class RobustnessMatrixCell(ContractModel):
    cell_id: Identifier
    profile_id: Identifier
    profile_sha256: SHA256
    case_id: Identifier
    case_sha256: SHA256
    seed: int
    clock_mode: ClockMode
    repetition: int = Field(ge=1)
    scenario_id: Identifier
    simulation_configuration_sha256: SHA256
    safety_configuration_sha256: SHA256
    model_id: Identifier
    model_version: str
    cell_sha256: SHA256


class RobustnessMatrixManifest(ContractModel):
    schema_version: Literal[1] = 1
    contract: Literal["mission-robustness-matrix-v1"] = "mission-robustness-matrix-v1"
    version: Literal["1.0.0"] = "1.0.0"
    matrix_id: Identifier
    selected_cases: tuple[RobustnessSelectedCase, ...]
    profiles: tuple[RobustnessProfile, ...]
    cells: tuple[RobustnessMatrixCell, ...]
    limitations: tuple[str, ...]
    manifest_sha256: SHA256

    @model_validator(mode="after")
    def complete_and_identified(self) -> RobustnessMatrixManifest:
        case_ids = {item.case_id for item in self.selected_cases}
        profile_ids = {item.profile_id for item in self.profiles}
        if len(case_ids) != len(self.selected_cases):
            raise ValueError("robustness selected case identities must be unique")
        if len(profile_ids) != len(self.profiles):
            raise ValueError("robustness profile identities must be unique")
        if len({item.cell_id for item in self.cells}) != len(self.cells):
            raise ValueError("robustness matrix cell identities must be unique")
        if any(
            cell.case_id not in case_ids or cell.profile_id not in profile_ids
            for cell in self.cells
        ):
            raise ValueError("robustness cell references an unknown case or profile")
        if self.manifest_sha256 != canonical_sha256(
            self.model_dump(mode="python", exclude={"manifest_sha256"})
        ):
            raise ValueError("robustness manifest hash does not match its contract")
        return self


class ObservedMissionOutcome(ContractModel):
    mission_execution_id: Identifier
    status: Identifier
    reason_code: Identifier
    normalized_outcome_sha256: SHA256
    safe_terminal: bool
    expected_recovery_observed: bool


class RobustnessRunAssessment(ContractModel):
    cell_id: Identifier
    cell_sha256: SHA256
    profile_id: Identifier
    case_id: Identifier
    seed: int
    clock_mode: ClockMode
    repetition: int = Field(ge=1)
    evaluation_report_sha256: SHA256
    mission_execution_id: Identifier
    normalized_outcome_sha256: SHA256
    outcome_status: Identifier
    reason_code: Identifier
    evidence_complete: bool
    plan_identity_preserved: bool
    safe_terminal: bool
    expected_recovery_observed: bool
    warning_samples: int = Field(ge=0)
    critical_samples: int = Field(ge=0)
    minimum_boundary_margin_m: float | None = None
    minimum_goal_capture_margin_m: float | None = None
    minimum_separation_m: float | None = Field(default=None, ge=0.0)
    elapsed_s: float | None = Field(default=None, ge=0.0)
    passed: bool
    findings: tuple[Identifier, ...]
    assessment_sha256: SHA256


class RobustnessProfileSummary(ContractModel):
    profile_id: Identifier
    expected_cell_count: int = Field(ge=1)
    assessed_cell_count: int = Field(ge=0)
    passed_cell_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    minimum_required_pass_rate: float = Field(ge=0.0, le=1.0)
    worst_boundary_margin_m: float | None = None
    worst_goal_capture_margin_m: float | None = None
    worst_separation_margin_m: float | None = None
    safe_failure_count: int = Field(ge=0)
    hard_failure_count: int = Field(ge=0)
    passed: bool
    findings: tuple[Identifier, ...]


class ClockModeReconciliation(ContractModel):
    profile_id: Identifier
    case_id: Identifier
    seed: int
    accelerated_cell_sha256: SHA256
    realtime_cell_sha256: SHA256
    safety_invariants_match: bool
    plan_identity_invariant_match: bool
    terminal_invariant_match: bool
    evidence_invariant_match: bool
    elapsed_delta_s: float | None = None
    model_sensitive_fields: tuple[Identifier, ...]
    passed: bool


class RobustnessQualification(ContractModel):
    schema_version: Literal[1] = 1
    manifest_sha256: SHA256
    assessments: tuple[RobustnessRunAssessment, ...]
    profile_summaries: tuple[RobustnessProfileSummary, ...]
    clock_reconciliations: tuple[ClockModeReconciliation, ...]
    missing_cell_sha256s: tuple[SHA256, ...]
    reproducible: bool
    reproducibility_failures: tuple[Identifier, ...]
    passed: bool
    findings: tuple[Identifier, ...]
    qualification_sha256: SHA256


class HigherFidelityHandoffBundle(ContractModel):
    schema_version: Literal[1] = 1
    bundle_id: Identifier
    source_manifest_sha256: SHA256
    source_qualification_sha256: SHA256
    selected_case_sha256s: tuple[SHA256, ...]
    selected_cell_sha256s: tuple[SHA256, ...]
    fast_sim_evaluation_report_sha256s: tuple[SHA256, ...]
    required_signals: tuple[Identifier, ...]
    acceptance_thresholds: dict[Identifier, float | int | bool]
    model_sensitive_expectations: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    isaac_status: Literal["NOT_RUN"] = "NOT_RUN"
    physical_status: Literal["NOT_RUN"] = "NOT_RUN"
    grants_execution_authority: Literal[False] = False
    bundle_sha256: SHA256


def generate_robustness_matrix() -> RobustnessMatrixManifest:
    selected_cases = _selected_cases()
    profiles = _profiles()
    case_by_id = {item.case_id: item for item in selected_cases}
    cells: list[RobustnessMatrixCell] = []
    for profile in profiles:
        for case_id in profile.target_case_ids:
            selected_case = case_by_id[case_id]
            for seed in profile.seeds:
                for clock_mode in profile.clock_modes:
                    for repetition in range(1, profile.repetitions + 1):
                        cell_payload = {
                            "cell_id": (
                                f"cell-{profile.profile_id}-{case_id}-{seed}-"
                                f"{clock_mode.value}-{repetition}"
                            ),
                            "profile_id": profile.profile_id,
                            "profile_sha256": profile.profile_sha256,
                            "case_id": case_id,
                            "case_sha256": selected_case.case_sha256,
                            "seed": seed,
                            "clock_mode": clock_mode,
                            "repetition": repetition,
                            "scenario_id": "one-drone-room",
                            "simulation_configuration_sha256": canonical_sha256(
                                _simulation_configuration(profile, seed, clock_mode)
                            ),
                            "safety_configuration_sha256": canonical_sha256(
                                _safety_configuration(profile)
                            ),
                            "model_id": "crazyflie-6dof",
                            "model_version": "2.0.0",
                        }
                        cells.append(
                            RobustnessMatrixCell(
                                **cell_payload,
                                cell_sha256=canonical_sha256(cell_payload),
                            )
                        )
    payload = {
        "schema_version": 1,
        "contract": ROBUSTNESS_CONTRACT,
        "version": ROBUSTNESS_VERSION,
        "matrix_id": "fast-sim-mission-robustness-v1",
        "selected_cases": selected_cases,
        "profiles": profiles,
        "cells": tuple(cells),
        "limitations": (
            "bounded configured Fast Sim variations are not a statistical physical model",
            "clock-rate scaling represents bounded source-clock variation, not oscillator physics",
            "object avoidance, live Isaac, digital twin, and physical flight are excluded",
        ),
    }
    return RobustnessMatrixManifest(
        **payload,
        manifest_sha256=canonical_sha256(payload),
    )


def assess_robustness_run(
    manifest: RobustnessMatrixManifest,
    cell: RobustnessMatrixCell,
    evaluation: MissionExecutionEvaluation,
    outcome: ObservedMissionOutcome,
) -> RobustnessRunAssessment:
    profile = next(item for item in manifest.profiles if item.profile_id == cell.profile_id)
    selected_case = next(item for item in manifest.selected_cases if item.case_id == cell.case_id)
    findings: list[str] = []
    if evaluation.mission_execution_id != outcome.mission_execution_id:
        findings.append("EXECUTION_IDENTITY_MISMATCH")
    evidence_complete = (
        evaluation.status is EvaluationStatus.COMPLETE and evaluation.evidence.complete
    )
    if not evidence_complete:
        findings.append("EVIDENCE_INCOMPLETE")
    plan_identity = all(
        item.accepted_plan_identity_match is not False for item in evaluation.vehicles
    )
    if not plan_identity:
        findings.append("PLAN_IDENTITY_MISMATCH")
    if evaluation.fleet.critical_sample_count > profile.maximum_critical_samples:
        findings.append("CRITICAL_SAFETY_VIOLATION")
    if evaluation.fleet.warning_sample_count > profile.maximum_warning_samples:
        findings.append("WARNING_MARGIN_VIOLATION")
    boundary_values = [
        item.minimum_boundary_margin_m
        for item in evaluation.vehicles
        if item.minimum_boundary_margin_m is not None
    ]
    boundary_margin = min(boundary_values, default=None)
    if boundary_margin is not None and boundary_margin < profile.minimum_boundary_margin_m:
        findings.append("BOUNDARY_MARGIN_VIOLATION")
    goal_values = [
        item.terminal_goal_capture_margin_m
        for item in evaluation.vehicles
        if item.terminal_goal_capture_margin_m is not None
    ]
    goal_margin = min(goal_values, default=None)
    if (
        selected_case.require_goal_capture
        and profile.expected_disposition is ExpectedDisposition.SUCCESS
        and (
            len(goal_values) != selected_case.role_count
            or goal_margin is None
            or goal_margin < profile.minimum_goal_capture_margin_m
        )
    ):
        findings.append("GOAL_MARGIN_VIOLATION")
    minimum_separation = (
        evaluation.fleet.minimum_truth_separation_m
        if evaluation.fleet.minimum_truth_separation_m is not None
        else evaluation.fleet.minimum_estimated_separation_m
    )
    if (
        selected_case.role_count > 1
        and selected_case.warning_separation_m is not None
        and (
            minimum_separation is None
            or minimum_separation - selected_case.warning_separation_m
            < profile.minimum_separation_margin_m
        )
    ):
        findings.append("SEPARATION_MARGIN_VIOLATION")
    if not outcome.safe_terminal:
        findings.append("UNSAFE_TERMINAL_STATE")
    if profile.expected_disposition is ExpectedDisposition.SUCCESS:
        if outcome.status != "SUCCEEDED":
            findings.append("EXPECTED_SUCCESS_NOT_OBSERVED")
    else:
        if outcome.status not in _SAFE_FAILURE_STATUSES:
            findings.append("EXPECTED_SAFE_FAILURE_NOT_OBSERVED")
        if outcome.reason_code not in profile.accepted_reason_codes:
            findings.append("UNEXPECTED_FAILURE_REASON")
        if not outcome.expected_recovery_observed:
            findings.append("EXPECTED_RECOVERY_NOT_OBSERVED")
    payload = {
        "cell_id": cell.cell_id,
        "cell_sha256": cell.cell_sha256,
        "profile_id": cell.profile_id,
        "case_id": cell.case_id,
        "seed": cell.seed,
        "clock_mode": cell.clock_mode,
        "repetition": cell.repetition,
        "evaluation_report_sha256": evaluation.report_sha256,
        "mission_execution_id": evaluation.mission_execution_id,
        "normalized_outcome_sha256": outcome.normalized_outcome_sha256,
        "outcome_status": outcome.status,
        "reason_code": outcome.reason_code,
        "evidence_complete": evidence_complete,
        "plan_identity_preserved": plan_identity,
        "safe_terminal": outcome.safe_terminal,
        "expected_recovery_observed": outcome.expected_recovery_observed,
        "warning_samples": evaluation.fleet.warning_sample_count,
        "critical_samples": evaluation.fleet.critical_sample_count,
        "minimum_boundary_margin_m": boundary_margin,
        "minimum_goal_capture_margin_m": goal_margin,
        "minimum_separation_m": minimum_separation,
        "elapsed_s": evaluation.fleet.elapsed_s,
        "passed": not findings,
        "findings": tuple(findings),
    }
    return RobustnessRunAssessment(
        **payload,
        assessment_sha256=canonical_sha256(payload),
    )


def qualify_robustness(
    manifest: RobustnessMatrixManifest,
    observations_by_cell_sha256: dict[
        str, tuple[MissionExecutionEvaluation, ObservedMissionOutcome]
    ],
) -> RobustnessQualification:
    assessments = tuple(
        assess_robustness_run(manifest, cell, *observations_by_cell_sha256[cell.cell_sha256])
        for cell in manifest.cells
        if cell.cell_sha256 in observations_by_cell_sha256
    )
    assessment_by_cell = {item.cell_sha256: item for item in assessments}
    missing = tuple(
        cell.cell_sha256 for cell in manifest.cells if cell.cell_sha256 not in assessment_by_cell
    )
    profile_summaries = tuple(
        _profile_summary(profile, manifest.cells, assessments) for profile in manifest.profiles
    )
    reproducibility_failures = _reproducibility_failures(manifest.cells, assessments)
    reconciliations = _clock_reconciliations(manifest.cells, assessments)
    findings: list[str] = []
    if missing:
        findings.append("MATRIX_EVIDENCE_MISSING")
    if reproducibility_failures:
        findings.append("REPRODUCIBILITY_FAILED")
    if any(not item.passed for item in profile_summaries):
        findings.append("PROFILE_GATE_FAILED")
    if any(not item.passed for item in reconciliations):
        findings.append("CLOCK_MODE_INVARIANT_FAILED")
    payload = {
        "schema_version": 1,
        "manifest_sha256": manifest.manifest_sha256,
        "assessments": assessments,
        "profile_summaries": profile_summaries,
        "clock_reconciliations": reconciliations,
        "missing_cell_sha256s": missing,
        "reproducible": not reproducibility_failures,
        "reproducibility_failures": reproducibility_failures,
        "passed": not findings,
        "findings": tuple(findings),
    }
    return RobustnessQualification(
        **payload,
        qualification_sha256=canonical_sha256(payload),
    )


def build_higher_fidelity_handoff(
    manifest: RobustnessMatrixManifest,
    qualification: RobustnessQualification,
) -> HigherFidelityHandoffBundle:
    if qualification.manifest_sha256 != manifest.manifest_sha256 or not qualification.passed:
        raise ValueError("higher-fidelity handoff requires a passing bound qualification")
    preferred_case_ids = {
        "robust-endpoint-landing",
        "robust-staged-crossing",
        "robust-observation-loss",
    }
    selected = tuple(
        assessment
        for assessment in qualification.assessments
        if assessment.case_id in preferred_case_ids and assessment.repetition == 1
    )
    first_by_case: dict[str, RobustnessRunAssessment] = {}
    for assessment in selected:
        first_by_case.setdefault(assessment.case_id, assessment)
    selected = tuple(first_by_case[item] for item in sorted(first_by_case))
    case_by_id = {item.case_id: item for item in manifest.selected_cases}
    payload = {
        "schema_version": 1,
        "bundle_id": "higher-fidelity-handoff-fast-sim-v1",
        "source_manifest_sha256": manifest.manifest_sha256,
        "source_qualification_sha256": qualification.qualification_sha256,
        "selected_case_sha256s": tuple(case_by_id[item.case_id].case_sha256 for item in selected),
        "selected_cell_sha256s": tuple(item.cell_sha256 for item in selected),
        "fast_sim_evaluation_report_sha256s": tuple(
            item.evaluation_report_sha256 for item in selected
        ),
        "required_signals": (
            "command-envelope",
            "acknowledgement",
            "source-timestamp",
            "received-timestamp",
            "position-estimate",
            "simulator-truth-position",
            "trajectory-setpoint",
            "fault-transition",
            "separation-observation",
            "goal-capture",
            "terminal-state",
        ),
        "acceptance_thresholds": {
            "maximum_critical_samples": 0,
            "maximum_warning_samples": 0,
            "minimum_goal_capture_margin_m": 0.0,
            "minimum_boundary_margin_m": 0.0,
            "evidence_complete": True,
            "plan_identity_preserved": True,
        },
        "model_sensitive_expectations": (
            "wall-clock duration and controller tracking error may differ by backend",
            "safety, plan identity, goal, recovery, and evidence invariants may not differ",
            "Fast Sim truth must remain labeled and is not measured physical truth",
        ),
        "stop_conditions": (
            "any critical separation or boundary violation",
            "lost plan, vehicle, role, source, or configuration identity",
            "unsafe or unexplained terminal state",
            "missing required evidence or unavailable provenance",
            "backend behavior outside its separately approved safety envelope",
        ),
        "isaac_status": "NOT_RUN",
        "physical_status": "NOT_RUN",
        "grants_execution_authority": False,
    }
    return HigherFidelityHandoffBundle(
        **payload,
        bundle_sha256=canonical_sha256(payload),
    )


def _selected_cases() -> tuple[RobustnessSelectedCase, ...]:
    curriculum = generate_progressive_curriculum(
        seeds=(109,),
        border_variants=(BorderVariant.NOMINAL,),
    )
    endpoint = next(
        item for item in curriculum.cases if item.template is MissionCaseTemplate.ENDPOINT_LANDING
    )
    crossing = next(
        item for item in curriculum.cases if item.template is MissionCaseTemplate.STAGED_CROSSING
    )
    observation_source = """async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.observe(timeout_s=0.2, required="position")
    await drone.land(duration_s=2.0)
"""
    observation_sha = hashlib.sha256(observation_source.encode("utf-8")).hexdigest()
    return (
        RobustnessSelectedCase(
            case_id="robust-endpoint-landing",
            case_sha256=endpoint.case_sha256,
            mission_filename=endpoint.mission_filename,
            mission_source=endpoint.mission_source,
            mission_source_sha256=endpoint.mission_source_sha256,
            role_count=endpoint.role_count,
            require_goal_capture=True,
        ),
        RobustnessSelectedCase(
            case_id="robust-staged-crossing",
            case_sha256=crossing.case_sha256,
            mission_filename=crossing.mission_filename,
            mission_source=crossing.mission_source,
            mission_source_sha256=crossing.mission_source_sha256,
            role_count=crossing.role_count,
            require_goal_capture=True,
            warning_separation_m=crossing.warning_separation_m,
            critical_separation_m=crossing.critical_separation_m,
        ),
        RobustnessSelectedCase(
            case_id="robust-observation-loss",
            case_sha256=canonical_sha256(
                {"source_sha256": observation_sha, "case": "observation-loss-v1"}
            ),
            mission_filename="observation_timeout.py",
            mission_source=observation_source,
            mission_source_sha256=observation_sha,
            role_count=1,
            require_goal_capture=False,
        ),
    )


def _simulation_configuration(
    profile: RobustnessProfile,
    seed: int,
    clock_mode: ClockMode,
) -> SimulationConfig:
    payload = SimulationConfig().model_dump(mode="python")
    payload.update(profile.simulation_overrides)
    payload.update({"seed": seed, "clock_mode": clock_mode})
    return SimulationConfig.model_validate(payload)


def _safety_configuration(profile: RobustnessProfile) -> SafetyPolicy:
    payload = SafetyPolicy().model_dump(mode="python")
    payload.update(profile.safety_overrides)
    return SafetyPolicy.model_validate(payload)


def _profiles() -> tuple[RobustnessProfile, ...]:
    endpoint_case = ("robust-endpoint-landing",)
    return (
        _profile(
            "nominal-multi-seed",
            RobustnessProfileKind.NOMINAL_MULTI_SEED,
            endpoint_case,
            seeds=DEFAULT_ROBUSTNESS_SEEDS,
        ),
        _profile(
            "bounded-sensor-noise",
            RobustnessProfileKind.SENSOR_NOISE,
            endpoint_case,
            seeds=DEFAULT_ROBUSTNESS_SEEDS,
            simulation_overrides={
                "position_noise_std_m": 0.006,
                "range_noise_std_m": 0.006,
                "flow_drift_std_m_sqrt_s": 0.004,
            },
        ),
        _profile(
            "bounded-transport-latency",
            RobustnessProfileKind.TRANSPORT_LATENCY,
            endpoint_case,
            seeds=DEFAULT_ROBUSTNESS_SEEDS,
            simulation_overrides={
                "command_latency_s": 0.05,
                "acknowledgement_latency_s": 0.02,
                "estimator_latency_s": 0.01,
            },
        ),
        _profile(
            "bounded-clock-rate",
            RobustnessProfileKind.CLOCK_RATE_VARIATION,
            endpoint_case,
            seeds=(109,),
            clock_modes=(ClockMode.ACCELERATED, ClockMode.REALTIME),
            simulation_overrides={"speed": 1.02},
        ),
        _profile(
            "required-observation-loss",
            RobustnessProfileKind.OBSERVATION_LOSS,
            ("robust-observation-loss",),
            seeds=DEFAULT_ROBUSTNESS_SEEDS,
            repetitions=2,
            faults=(FaultWindow(fault=FaultType.LOCALIZATION_LOSS, start_s=2.0),),
            expected_disposition=ExpectedDisposition.SAFE_FAILURE,
            accepted_reason_codes=("LOCALIZATION_INVALID",),
        ),
        _profile(
            "bounded-execution-timeout",
            RobustnessProfileKind.EXECUTION_TIMEOUT,
            ("robust-endpoint-landing",),
            seeds=(109,),
            repetitions=2,
            safety_overrides={"command_timeout_s": 0.5},
            faults=(
                FaultWindow(
                    fault=FaultType.TRAJECTORY_TIMEOUT,
                    start_s=2.0,
                    vehicle_id="case-primary",
                ),
            ),
            expected_disposition=ExpectedDisposition.SAFE_FAILURE,
            accepted_reason_codes=("COMMAND_TIMEOUT",),
        ),
        _profile(
            "bounded-abort-and-land-recovery",
            RobustnessProfileKind.BOUNDED_RECOVERY,
            ("robust-staged-crossing",),
            seeds=(109,),
            repetitions=2,
            faults=(
                FaultWindow(
                    fault=FaultType.LOCALIZATION_LOSS,
                    start_s=4.0,
                    vehicle_id="crossing-west",
                ),
            ),
            expected_disposition=ExpectedDisposition.SAFE_FAILURE,
            accepted_reason_codes=(
                "LOCALIZATION_INVALID",
                "FLEET_CHILD_FAILURE",
                "FLEET_DEGRADED",
                "FLEET_PARTIAL",
            ),
        ),
    )


def _profile(
    profile_id: str,
    kind: RobustnessProfileKind,
    target_case_ids: tuple[str, ...],
    *,
    seeds: tuple[int, ...],
    clock_modes: tuple[ClockMode, ...] = (ClockMode.ACCELERATED,),
    repetitions: int = 1,
    simulation_overrides: dict[str, float] | None = None,
    safety_overrides: dict[str, float] | None = None,
    faults: tuple[FaultWindow, ...] = (),
    expected_disposition: ExpectedDisposition = ExpectedDisposition.SUCCESS,
    accepted_reason_codes: tuple[str, ...] = (),
) -> RobustnessProfile:
    payload = {
        "profile_id": profile_id,
        "kind": kind,
        "target_case_ids": target_case_ids,
        "seeds": seeds,
        "clock_modes": clock_modes,
        "repetitions": repetitions,
        "simulation_overrides": simulation_overrides or {},
        "safety_overrides": safety_overrides or {},
        "faults": faults,
        "expected_disposition": expected_disposition,
        "accepted_reason_codes": accepted_reason_codes,
        "minimum_pass_rate": 1.0,
        "maximum_warning_samples": 0,
        "maximum_critical_samples": 0,
        "minimum_boundary_margin_m": 0.0,
        "minimum_goal_capture_margin_m": 0.0,
        "minimum_separation_margin_m": 0.0,
    }
    return RobustnessProfile(
        **payload,
        profile_sha256=canonical_sha256(payload),
    )


def _profile_summary(
    profile: RobustnessProfile,
    cells: tuple[RobustnessMatrixCell, ...],
    assessments: tuple[RobustnessRunAssessment, ...],
) -> RobustnessProfileSummary:
    expected = tuple(item for item in cells if item.profile_id == profile.profile_id)
    observed = tuple(item for item in assessments if item.profile_id == profile.profile_id)
    passed_count = sum(item.passed for item in observed)
    pass_rate = passed_count / len(expected)
    boundary = [
        item.minimum_boundary_margin_m
        for item in observed
        if item.minimum_boundary_margin_m is not None
    ]
    goals = [
        item.minimum_goal_capture_margin_m
        for item in observed
        if item.minimum_goal_capture_margin_m is not None
    ]
    separation = []
    for item in observed:
        selected_case = item.case_id
        if item.minimum_separation_m is None:
            continue
        warning = 0.75 if selected_case == "robust-staged-crossing" else None
        if warning is not None:
            separation.append(item.minimum_separation_m - warning)
    hard_count = sum(bool(set(item.findings) & _HARD_FINDINGS) for item in observed)
    findings: list[str] = []
    if len(observed) != len(expected):
        findings.append("PROFILE_EVIDENCE_MISSING")
    if pass_rate < profile.minimum_pass_rate:
        findings.append("PROFILE_PASS_RATE_BELOW_THRESHOLD")
    if hard_count:
        findings.append("PROFILE_HARD_GATE_FAILED")
    return RobustnessProfileSummary(
        profile_id=profile.profile_id,
        expected_cell_count=len(expected),
        assessed_cell_count=len(observed),
        passed_cell_count=passed_count,
        pass_rate=pass_rate,
        minimum_required_pass_rate=profile.minimum_pass_rate,
        worst_boundary_margin_m=min(boundary, default=None),
        worst_goal_capture_margin_m=min(goals, default=None),
        worst_separation_margin_m=min(separation, default=None),
        safe_failure_count=sum(
            item.outcome_status in _SAFE_FAILURE_STATUSES and item.safe_terminal
            for item in observed
        ),
        hard_failure_count=hard_count,
        passed=not findings,
        findings=tuple(findings),
    )


def _reproducibility_failures(
    cells: tuple[RobustnessMatrixCell, ...],
    assessments: tuple[RobustnessRunAssessment, ...],
) -> tuple[str, ...]:
    expected_groups: dict[tuple[str, str, int, ClockMode], list[RobustnessMatrixCell]] = (
        defaultdict(list)
    )
    observed_groups: dict[tuple[str, str, int, ClockMode], list[RobustnessRunAssessment]] = (
        defaultdict(list)
    )
    for cell in cells:
        expected_groups[(cell.profile_id, cell.case_id, cell.seed, cell.clock_mode)].append(cell)
    for assessment in assessments:
        observed_groups[
            (assessment.profile_id, assessment.case_id, assessment.seed, assessment.clock_mode)
        ].append(assessment)
    failures: list[str] = []
    for key, expected in expected_groups.items():
        if len(expected) < 2:
            continue
        observed = observed_groups.get(key, [])
        if (
            len(observed) != len(expected)
            or len({item.normalized_outcome_sha256 for item in observed}) != 1
        ):
            failures.append(f"{key[0]}:{key[1]}:{key[2]}:{key[3].value}")
    return tuple(sorted(failures))


def _clock_reconciliations(
    cells: tuple[RobustnessMatrixCell, ...],
    assessments: tuple[RobustnessRunAssessment, ...],
) -> tuple[ClockModeReconciliation, ...]:
    cell_by_key = {
        (item.profile_id, item.case_id, item.seed, item.clock_mode, item.repetition): item
        for item in cells
    }
    assessment_by_cell = {item.cell_sha256: item for item in assessments}
    comparisons: list[ClockModeReconciliation] = []
    base_keys = sorted(
        {
            (item.profile_id, item.case_id, item.seed, item.repetition)
            for item in cells
            if item.clock_mode is ClockMode.ACCELERATED
            and (
                item.profile_id,
                item.case_id,
                item.seed,
                ClockMode.REALTIME,
                item.repetition,
            )
            in cell_by_key
        }
    )
    for profile_id, case_id, seed, repetition in base_keys:
        accelerated_cell = cell_by_key[
            (profile_id, case_id, seed, ClockMode.ACCELERATED, repetition)
        ]
        realtime_cell = cell_by_key[(profile_id, case_id, seed, ClockMode.REALTIME, repetition)]
        accelerated = assessment_by_cell.get(accelerated_cell.cell_sha256)
        realtime = assessment_by_cell.get(realtime_cell.cell_sha256)
        if accelerated is None or realtime is None:
            continue
        safety_match = (
            accelerated.warning_samples == realtime.warning_samples
            and accelerated.critical_samples == realtime.critical_samples
        )
        identity_match = accelerated.plan_identity_preserved and realtime.plan_identity_preserved
        terminal_match = accelerated.safe_terminal and realtime.safe_terminal
        evidence_match = accelerated.evidence_complete and realtime.evidence_complete
        elapsed_delta = (
            realtime.elapsed_s - accelerated.elapsed_s
            if realtime.elapsed_s is not None and accelerated.elapsed_s is not None
            else None
        )
        comparisons.append(
            ClockModeReconciliation(
                profile_id=profile_id,
                case_id=case_id,
                seed=seed,
                accelerated_cell_sha256=accelerated.cell_sha256,
                realtime_cell_sha256=realtime.cell_sha256,
                safety_invariants_match=safety_match,
                plan_identity_invariant_match=identity_match,
                terminal_invariant_match=terminal_match,
                evidence_invariant_match=evidence_match,
                elapsed_delta_s=elapsed_delta,
                model_sensitive_fields=("elapsed_s", "tracking_error", "wall_clock_duration"),
                passed=safety_match and identity_match and terminal_match and evidence_match,
            )
        )
    return tuple(comparisons)
