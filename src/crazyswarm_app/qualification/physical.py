from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256
from crazyswarm_app.hardware.models import (
    BenchQualificationRecord,
    PhysicalFlightEntryRecord,
)


class DatasetSplit(StrEnum):
    CALIBRATION = "CALIBRATION"
    VALIDATION = "VALIDATION"
    FUNCTIONAL_ONLY = "FUNCTIONAL_ONLY"


class TrialClassification(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    NOT_RUN = "NOT_RUN"


class MissionTrialRequirement(ContractModel):
    qf_id: Identifier
    source_path: str
    source_sha256: SHA256
    minimum_trials: int = Field(ge=0)
    minimum_batteries: int = Field(default=1, ge=1)
    maximum_speed_m_s: float | None = Field(default=None, gt=0.0)
    external_reference_required: bool = False
    physical_execution_required: bool = True
    notes: tuple[str, ...] = ()


class PhysicalQualificationPlan(ContractModel):
    schema_version: Literal[1] = 1
    plan_id: Identifier
    command_mapping_id: Identifier
    required_cflib_version: str
    minimum_protocol_version: int = Field(ge=1)
    required_deck_parameters: dict[str, int]
    connect_cycle_count: int = Field(ge=100)
    static_samples_per_point: int = Field(ge=30)
    required_battery_count: int = Field(ge=2)
    shakedown_trials: int = Field(ge=3)
    missions: tuple[MissionTrialRequirement, ...]
    unsupported_claims: tuple[str, ...]

    @model_validator(mode="after")
    def qf_ids_are_unique(self) -> PhysicalQualificationPlan:
        ids = [mission.qf_id for mission in self.missions]
        if len(ids) != len(set(ids)):
            raise ValueError("qualification mission IDs must be unique")
        return self


class TrialEvidenceRecord(ContractModel):
    schema_version: Literal[1] = 1
    trial_id: Identifier
    session_record_id: Identifier
    qf_id: Identifier
    mission_source_sha256: SHA256
    mission_parameters_sha256: SHA256
    battery_id: Identifier
    dataset_split: DatasetSplit
    classification: TrialClassification
    reason_code: Identifier
    normalized_intent_sha256: SHA256
    evidence_bundle_sha256: SHA256
    started_at_utc: datetime
    finished_at_utc: datetime
    anomaly_ids: tuple[Identifier, ...] = ()
    external_reference_id: Identifier | None = None
    external_reference_alignment_sha256: SHA256 | None = None
    external_metrics: dict[str, float | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def evidence_is_ordered_and_attributed(self) -> TrialEvidenceRecord:
        if self.finished_at_utc < self.started_at_utc:
            raise ValueError("trial finish cannot precede start")
        external_fields = (
            self.external_reference_id,
            self.external_reference_alignment_sha256,
        )
        if any(value is None for value in external_fields) and any(
            value is not None for value in self.external_metrics.values()
        ):
            raise ValueError("external trajectory metrics require qualified reference alignment")
        return self


class GateFinding(ContractModel):
    code: Identifier
    passed: bool
    message: str


class PhysicalGateAssessment(ContractModel):
    accepted: bool
    classification: Literal[
        "READY_FOR_CONTAINED_FLIGHT",
        "BENCH_EVIDENCE_INCOMPLETE",
        "FLIGHT_ENTRY_INCOMPLETE",
        "FUNCTIONAL_HARDWARE_BASELINE_ONLY",
        "PHYSICAL_QUALIFICATION_WITH_EXTERNAL_REFERENCE",
    ]
    findings: tuple[GateFinding, ...]


def load_physical_plan(path: Path) -> PhysicalQualificationPlan:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return PhysicalQualificationPlan.model_validate(raw)


def verify_plan_source_hashes(
    plan: PhysicalQualificationPlan,
    root: Path,
) -> tuple[GateFinding, ...]:
    findings: list[GateFinding] = []
    for mission in plan.missions:
        path = root / mission.source_path
        observed = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        findings.append(
            GateFinding(
                code=f"SOURCE_{mission.qf_id.replace('-', '_')}",
                passed=observed == mission.source_sha256,
                message=(
                    f"source hash verified: {observed}"
                    if observed == mission.source_sha256
                    else (
                        f"source hash mismatch: expected {mission.source_sha256}, "
                        f"observed {observed}"
                    )
                ),
            )
        )
    return tuple(findings)


def assess_flight_entry(
    bench: BenchQualificationRecord,
    entry: PhysicalFlightEntryRecord,
    plan: PhysicalQualificationPlan,
    *,
    now: datetime | None = None,
) -> PhysicalGateAssessment:
    current = now or datetime.now(UTC)
    findings = (
        GateFinding(
            code="BENCH_ACCEPTED",
            passed=bench.accepted,
            message=(
                "WP-04 bench record is accepted" if bench.accepted else "WP-04 bench record is open"
            ),
        ),
        GateFinding(
            code="IDENTITY_MATCH",
            passed=bench.vehicle_id == entry.vehicle_id,
            message="bench and flight-entry vehicle identities match",
        ),
        GateFinding(
            code="BENCH_EVIDENCE_MATCH",
            passed=(
                bench.evidence_sha256 is not None
                and bench.evidence_sha256 == entry.bench_evidence_sha256
            ),
            message="flight entry names the immutable accepted bench evidence",
        ),
        GateFinding(
            code="SOURCE_SET_MATCH",
            passed=all(
                entry.exact_source_hashes.get(requirement.qf_id) == requirement.source_sha256
                for requirement in plan.missions
                if requirement.physical_execution_required
            ),
            message="flight entry freezes every required physical QF source hash",
        ),
        GateFinding(
            code="SESSION_AUTHORIZATION",
            passed=entry.accepted(now=current),
            message="operator, observer, containment, and time-bounded authorization are current",
        ),
    )
    accepted = all(finding.passed for finding in findings)
    classification = (
        "READY_FOR_CONTAINED_FLIGHT"
        if accepted
        else "BENCH_EVIDENCE_INCOMPLETE"
        if not bench.accepted
        else "FLIGHT_ENTRY_INCOMPLETE"
    )
    return PhysicalGateAssessment(
        accepted=accepted,
        classification=classification,
        findings=findings,
    )


def assess_completed_trials(
    plan: PhysicalQualificationPlan,
    records: tuple[TrialEvidenceRecord, ...],
) -> PhysicalGateAssessment:
    findings: list[GateFinding] = []
    for requirement in plan.missions:
        if not requirement.physical_execution_required:
            continue
        matching = tuple(record for record in records if record.qf_id == requirement.qf_id)
        passed = tuple(
            record for record in matching if record.classification is TrialClassification.PASSED
        )
        battery_count = len({record.battery_id for record in passed})
        source_match = all(
            record.mission_source_sha256 == requirement.source_sha256 for record in matching
        )
        external_ok = not requirement.external_reference_required or all(
            record.external_reference_id is not None
            and record.external_reference_alignment_sha256 is not None
            for record in passed
        )
        requirement_passed = all(
            (
                len(passed) >= requirement.minimum_trials,
                battery_count >= requirement.minimum_batteries,
                source_match,
                external_ok,
            )
        )
        findings.append(
            GateFinding(
                code=f"TRIALS_{requirement.qf_id.replace('-', '_')}",
                passed=requirement_passed,
                message=(
                    f"{len(passed)}/{requirement.minimum_trials} passing trials, "
                    f"{battery_count}/{requirement.minimum_batteries} batteries, "
                    f"source_match={source_match}, external_reference={external_ok}"
                ),
            )
        )
    accepted = bool(findings) and all(finding.passed for finding in findings)
    has_external_reference = any(
        record.external_reference_id is not None
        and record.external_reference_alignment_sha256 is not None
        for record in records
    )
    return PhysicalGateAssessment(
        accepted=accepted,
        classification=(
            "PHYSICAL_QUALIFICATION_WITH_EXTERNAL_REFERENCE"
            if accepted and has_external_reference
            else "FUNCTIONAL_HARDWARE_BASELINE_ONLY"
        ),
        findings=tuple(findings),
    )


def canonical_record_sha256(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()
