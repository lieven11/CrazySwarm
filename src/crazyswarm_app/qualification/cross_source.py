from __future__ import annotations

import statistics
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256
from crazyswarm_app.qualification.physical import DatasetSplit, TrialClassification


class EvidenceSource(StrEnum):
    FAST_SIM = "FAST_SIM"
    MOCK_ISAAC = "MOCK_ISAAC"
    REAL_CRAZYFLIE = "REAL_CRAZYFLIE"
    ISAAC_SIM = "ISAAC_SIM"


class ParameterQualification(StrEnum):
    MEASURED_QUALIFIED = "MEASURED_QUALIFIED"
    CONFIGURED_UNQUALIFIED = "CONFIGURED_UNQUALIFIED"


class NvidiaEntryDecision(StrEnum):
    GO_ARCHITECTURE_AND_MOCK = "GO_ARCHITECTURE_AND_MOCK"
    GO_LIVE_ISAAC_MINIMAL = "GO_LIVE_ISAAC_MINIMAL"
    GO_ISAAC_PHYSICAL_MODEL = "GO_ISAAC_PHYSICAL_MODEL"
    DEFER_HARDWARE_DATA = "DEFER_HARDWARE_DATA"
    DEFER_RESOURCE_LIMIT = "DEFER_RESOURCE_LIMIT"


class ComparableRun(ContractModel):
    run_id: Identifier
    qf_id: Identifier
    source: EvidenceSource
    mission_source_sha256: SHA256
    normalized_intent_sha256: SHA256
    evidence_bundle_sha256: SHA256
    evidence_complete: bool
    classification: TrialClassification
    reason_code: Identifier
    dataset_split: DatasetSplit
    external_reference_alignment_sha256: SHA256 | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)


class ParameterEvidence(ContractModel):
    parameter: Identifier
    value: float | str | bool
    unit: str
    qualification: ParameterQualification
    evidence_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def measured_values_are_traceable(self) -> ParameterEvidence:
        if (
            self.qualification is ParameterQualification.MEASURED_QUALIFIED
            and not self.evidence_ids
        ):
            raise ValueError("measured parameters require traceable evidence IDs")
        return self


class ModelConfigurationVersion(ContractModel):
    model_configuration_id: Identifier
    schema_version: Literal[1] = 1
    parent_configuration_sha256: SHA256 | None = None
    configuration_sha256: SHA256
    parameter_evidence: tuple[ParameterEvidence, ...]
    calibration_run_ids: tuple[Identifier, ...]
    validation_run_ids: tuple[Identifier, ...]
    acceptance_tolerances: dict[Identifier, float] = Field(default_factory=dict)
    tolerance_evidence_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def calibration_and_validation_are_disjoint(self) -> ModelConfigurationVersion:
        overlap = set(self.calibration_run_ids) & set(self.validation_run_ids)
        if overlap:
            raise ValueError(f"calibration and validation runs overlap: {sorted(overlap)}")
        if not self.model_configuration_id.endswith(self.configuration_sha256[:12]):
            raise ValueError("immutable model ID must include the configuration hash prefix")
        return self


class CrossSourceFinding(ContractModel):
    code: Identifier
    passed: bool
    message: str


class CrossSourceReport(ContractModel):
    schema_version: Literal[1] = 1
    report_id: Identifier
    decision: NvidiaEntryDecision
    physical_model_authorized: bool
    digital_twin_enabled: bool = False
    isaac_profile: str
    findings: tuple[CrossSourceFinding, ...]
    unsupported_claims: tuple[str, ...]

    @model_validator(mode="after")
    def twin_cannot_be_enabled_by_this_gate(self) -> CrossSourceReport:
        if self.digital_twin_enabled:
            raise ValueError("WP-06 may define a twin gate but cannot enable DIGITAL_TWIN")
        if (
            self.physical_model_authorized
            and self.decision is not NvidiaEntryDecision.GO_ISAAC_PHYSICAL_MODEL
        ):
            raise ValueError("physical model authority requires GO_ISAAC_PHYSICAL_MODEL")
        return self


def derive_acceptance_tolerance(
    calibration_residuals: tuple[float, ...],
    *,
    engineering_margin: float,
    minimum_samples: int = 5,
) -> float:
    if len(calibration_residuals) < minimum_samples:
        raise ValueError("insufficient calibration residuals for a measured tolerance")
    if engineering_margin < 0.0:
        raise ValueError("engineering margin cannot be negative")
    center = statistics.fmean(calibration_residuals)
    measured_peak = max(abs(value - center) for value in calibration_residuals)
    return measured_peak + engineering_margin


def build_cross_source_report(
    *,
    report_id: str,
    runs: tuple[ComparableRun, ...],
    software_gate_passed: bool,
    bench_gate_passed: bool,
    physical_gate_passed: bool,
    nvidia_host_compatible: bool,
    model_configuration: ModelConfigurationVersion | None = None,
    resource_limit: bool = False,
) -> CrossSourceReport:
    qf_groups: dict[str, list[ComparableRun]] = {}
    for run in runs:
        qf_groups.setdefault(run.qf_id, []).append(run)
    source_and_intent_match = bool(qf_groups) and all(
        len({run.mission_source_sha256 for run in group}) == 1
        and len({run.normalized_intent_sha256 for run in group}) == 1
        for group in qf_groups.values()
    )
    required_sources = {
        EvidenceSource.FAST_SIM,
        EvidenceSource.MOCK_ISAAC,
        EvidenceSource.REAL_CRAZYFLIE,
    }
    cross_source_coverage = bool(qf_groups) and all(
        required_sources.issubset({run.source for run in group}) for group in qf_groups.values()
    )
    evidence_complete = bool(runs) and all(run.evidence_complete for run in runs)
    calibration_ids = {run.run_id for run in runs if run.dataset_split is DatasetSplit.CALIBRATION}
    validation_ids = {run.run_id for run in runs if run.dataset_split is DatasetSplit.VALIDATION}
    split_is_disjoint = not (calibration_ids & validation_ids)
    held_out_real_validation = any(
        run.source is EvidenceSource.REAL_CRAZYFLIE
        and run.dataset_split is DatasetSplit.VALIDATION
        and run.classification is TrialClassification.PASSED
        and run.external_reference_alignment_sha256 is not None
        for run in runs
    )
    all_run_ids = {run.run_id for run in runs}
    model_configuration_traceable = bool(
        model_configuration is not None
        and model_configuration.calibration_run_ids
        and model_configuration.validation_run_ids
        and set(model_configuration.calibration_run_ids).issubset(all_run_ids)
        and set(model_configuration.validation_run_ids).issubset(all_run_ids)
        and any(
            parameter.qualification is ParameterQualification.MEASURED_QUALIFIED
            for parameter in model_configuration.parameter_evidence
        )
        and model_configuration.acceptance_tolerances
        and all(value > 0.0 for value in model_configuration.acceptance_tolerances.values())
        and model_configuration.tolerance_evidence_ids
    )
    physical_model_authorized = all(
        (
            software_gate_passed,
            bench_gate_passed,
            physical_gate_passed,
            source_and_intent_match,
            cross_source_coverage,
            evidence_complete,
            split_is_disjoint,
            held_out_real_validation,
            model_configuration_traceable,
        )
    )
    if resource_limit:
        decision = NvidiaEntryDecision.DEFER_RESOURCE_LIMIT
    elif physical_model_authorized:
        decision = NvidiaEntryDecision.GO_ISAAC_PHYSICAL_MODEL
    elif software_gate_passed and nvidia_host_compatible:
        decision = NvidiaEntryDecision.GO_LIVE_ISAAC_MINIMAL
    elif software_gate_passed:
        decision = NvidiaEntryDecision.GO_ARCHITECTURE_AND_MOCK
    else:
        decision = NvidiaEntryDecision.DEFER_HARDWARE_DATA
    findings = (
        CrossSourceFinding(
            code="SOFTWARE_GATE",
            passed=software_gate_passed,
            message="Reality WP-00 through WP-03 software gate",
        ),
        CrossSourceFinding(
            code="BENCH_GATE",
            passed=bench_gate_passed,
            message="Reality WP-04 accepted physical bench evidence",
        ),
        CrossSourceFinding(
            code="PHYSICAL_GATE",
            passed=physical_gate_passed,
            message="Reality WP-05 accepted contained-flight evidence",
        ),
        CrossSourceFinding(
            code="SOURCE_AND_INTENT",
            passed=source_and_intent_match,
            message="QF source and normalized intent match across every available side",
        ),
        CrossSourceFinding(
            code="CROSS_SOURCE_COVERAGE",
            passed=cross_source_coverage,
            message="every QF group covers Fast Sim, mock Isaac, and the real Crazyflie",
        ),
        CrossSourceFinding(
            code="EVIDENCE_COMPLETE",
            passed=evidence_complete,
            message="all input runs contain immutable complete evidence",
        ),
        CrossSourceFinding(
            code="CALIBRATION_VALIDATION_SPLIT",
            passed=split_is_disjoint and bool(calibration_ids) and bool(validation_ids),
            message="calibration and held-out validation IDs are disjoint and non-empty",
        ),
        CrossSourceFinding(
            code="HELD_OUT_EXTERNAL_REFERENCE",
            passed=held_out_real_validation,
            message="a held-out real validation run has qualified external alignment",
        ),
        CrossSourceFinding(
            code="MODEL_CONFIGURATION_TRACEABLE",
            passed=model_configuration_traceable,
            message=(
                "immutable model parameters and variability-derived tolerances trace to "
                "calibration and held-out validation evidence"
            ),
        ),
    )
    return CrossSourceReport(
        report_id=report_id,
        decision=decision,
        physical_model_authorized=physical_model_authorized,
        digital_twin_enabled=False,
        isaac_profile=(
            "one Crazyflie; onboard high-level relative planner; Flow2 estimator; "
            "Multi-ranger validity/no-hit; measured command/telemetry clocks; "
            "no simulator authority"
        ),
        findings=findings,
        unsupported_claims=(
            "precise global return",
            "tight formation",
            "docking",
            "map quality",
            "object recognition",
            "real RF propagation",
            "true digital twin",
        ),
    )
