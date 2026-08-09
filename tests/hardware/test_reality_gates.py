from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.hardware.models import (
    AirframeInspection,
    BenchQualificationRecord,
    CommandPermit,
    DeckObservation,
    PermitScope,
    QualificationStatus,
    VersionPin,
)
from crazyswarm_app.qualification.cross_source import (
    ComparableRun,
    EvidenceSource,
    ModelConfigurationVersion,
    NvidiaEntryDecision,
    ParameterEvidence,
    ParameterQualification,
    build_cross_source_report,
    derive_acceptance_tolerance,
)
from crazyswarm_app.qualification.physical import (
    DatasetSplit,
    TrialClassification,
    load_physical_plan,
    verify_plan_source_hashes,
)

ROOT = Path(__file__).resolve().parents[2]
SHA_A = "a" * 64
SHA_B = "b" * 64
URI = "radio://0/80/2M/E7E7E7E701"


def test_flight_permit_requires_entry_evidence_and_installed_props() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        CommandPermit(
            permit_id="bad-flight",
            vehicle_id="cf01",
            selected_uri=URI,
            operator_id="operator",
            scope=PermitScope.CONTAINED_FLIGHT,
            issued_at_utc=now,
            expires_at_utc=now + timedelta(minutes=1),
            operator_present=True,
            props_removed=True,
            physically_restrained=True,
        )


def test_physical_plan_freezes_every_current_source_hash() -> None:
    plan = load_physical_plan(ROOT / "config/qualification/reality-physical-plan-v1.json")
    findings = verify_plan_source_hashes(plan, ROOT)
    assert len(findings) == 9
    assert all(finding.passed for finding in findings)


def test_incomplete_bench_record_cannot_self_certify() -> None:
    record = BenchQualificationRecord(
        record_id="bench-open",
        vehicle_id="cf01",
        selected_uri=URI,
        repository_dirty=True,
        versions=(VersionPin(component="cflib", expected_version="0.1.32"),),
        decks=(
            DeckObservation(parameter="deck.bcFlow2"),
            DeckObservation(parameter="deck.bcMultiranger"),
        ),
        airframe=AirframeInspection(),
    )
    assert not record.accepted


def test_complete_bench_record_requires_all_100_cycles_and_review() -> None:
    now = datetime.now(UTC)
    passed = QualificationStatus.PASSED
    record = BenchQualificationRecord(
        record_id="bench-passed",
        vehicle_id="cf01",
        selected_uri=URI,
        repository_commit="a" * 40,
        repository_dirty=False,
        versions=tuple(
            VersionPin(
                component=component,
                expected_version=version,
                observed_version=version,
                status=passed,
            )
            for component, version in (
                ("cflib", "0.1.32"),
                ("crazyflie-stm32-firmware", "2026.06"),
                ("crazyflie-nrf-firmware", "2026.06"),
                ("stabilizer-controller", "1"),
                ("stabilizer-estimator", "2"),
                ("crazyradio-firmware", "2026.06"),
            )
        ),
        decks=(
            DeckObservation(parameter="deck.bcFlow2", observed_value=1, status=passed),
            DeckObservation(parameter="deck.bcMultiranger", observed_value=1, status=passed),
        ),
        airframe=AirframeInspection(
            takeoff_mass_kg=0.035,
            center_of_mass_body_m=Vector3(),
            deck_mounting_passed=True,
            propeller_configuration="stock-verified",
            motor_configuration="stock-verified",
            battery_ids=("bat01", "bat02"),
            no_visible_damage=True,
            no_contamination=True,
            inspected_by="operator",
            inspected_at_utc=now,
        ),
        connect_cycles_completed=100,
        telemetry_matrix_status=passed,
        static_sensor_matrix_status=passed,
        props_off_command_status=passed,
        reconnect_status=passed,
        timing_and_resource_status=passed,
        evidence_sha256=SHA_A,
        reviewed_by="reviewer",
        reviewed_at_utc=now,
    )
    assert record.accepted


def run(source: EvidenceSource, split: DatasetSplit, run_id: str) -> ComparableRun:
    return ComparableRun(
        run_id=run_id,
        qf_id="QF-01",
        source=source,
        mission_source_sha256=SHA_A,
        normalized_intent_sha256=SHA_B,
        evidence_bundle_sha256=SHA_A,
        evidence_complete=True,
        classification=TrialClassification.PASSED,
        reason_code="MISSION_COMPLETED",
        dataset_split=split,
        external_reference_alignment_sha256=(
            SHA_B if source is EvidenceSource.REAL_CRAZYFLIE else None
        ),
    )


def test_current_evidence_only_authorizes_architecture_and_mock() -> None:
    report = build_cross_source_report(
        report_id="current-gate",
        runs=(),
        software_gate_passed=True,
        bench_gate_passed=False,
        physical_gate_passed=False,
        nvidia_host_compatible=False,
    )
    assert report.decision is NvidiaEntryDecision.GO_ARCHITECTURE_AND_MOCK
    assert not report.physical_model_authorized
    assert not report.digital_twin_enabled


def test_physical_model_requires_held_out_real_external_validation() -> None:
    runs = (
        run(EvidenceSource.FAST_SIM, DatasetSplit.CALIBRATION, "sim-cal"),
        run(EvidenceSource.MOCK_ISAAC, DatasetSplit.CALIBRATION, "mock-cal"),
        run(EvidenceSource.REAL_CRAZYFLIE, DatasetSplit.VALIDATION, "real-val"),
    )
    model = ModelConfigurationVersion(
        model_configuration_id=f"cf-model-{SHA_A[:12]}",
        configuration_sha256=SHA_A,
        parameter_evidence=(
            ParameterEvidence(
                parameter="mass",
                value=0.035,
                unit="kg",
                qualification=ParameterQualification.MEASURED_QUALIFIED,
                evidence_ids=("bench01",),
            ),
        ),
        calibration_run_ids=("sim-cal", "mock-cal"),
        validation_run_ids=("real-val",),
        acceptance_tolerances={"horizontal-residual-m": 0.2},
        tolerance_evidence_ids=("variability-report-01",),
    )
    report = build_cross_source_report(
        report_id="physical-gate",
        runs=runs,
        software_gate_passed=True,
        bench_gate_passed=True,
        physical_gate_passed=True,
        nvidia_host_compatible=True,
        model_configuration=model,
    )
    assert report.decision is NvidiaEntryDecision.GO_ISAAC_PHYSICAL_MODEL
    assert report.physical_model_authorized
    assert not report.digital_twin_enabled


def test_model_version_prevents_fit_and_accept_on_same_run() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        ModelConfigurationVersion(
            model_configuration_id=f"cf-model-{SHA_A[:12]}",
            configuration_sha256=SHA_A,
            parameter_evidence=(
                ParameterEvidence(
                    parameter="mass",
                    value=0.035,
                    unit="kg",
                    qualification=ParameterQualification.MEASURED_QUALIFIED,
                    evidence_ids=("bench01",),
                ),
            ),
            calibration_run_ids=("run01",),
            validation_run_ids=("run01",),
        )


def test_tolerance_comes_from_variability_plus_explicit_margin() -> None:
    tolerance = derive_acceptance_tolerance(
        (-0.03, -0.01, 0.0, 0.02, 0.04),
        engineering_margin=0.02,
    )
    assert tolerance == pytest.approx(0.056)
    with pytest.raises(ValueError, match="insufficient"):
        derive_acceptance_tolerance((0.1, 0.2), engineering_margin=0.01)
