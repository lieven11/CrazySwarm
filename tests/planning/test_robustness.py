from __future__ import annotations

from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.observability.evaluation import (
    EvidenceCompleteness,
    FleetExecutionMetrics,
    MissionExecutionEvaluation,
    VehicleExecutionMetrics,
)
from crazyswarm_app.planning.robustness import (
    ExpectedDisposition,
    ObservedMissionOutcome,
    RobustnessMatrixCell,
    RobustnessMatrixManifest,
    RobustnessProfileKind,
    build_higher_fidelity_handoff,
    generate_robustness_matrix,
    qualify_robustness,
)
from crazyswarm_app.simulation.clock import ClockMode


def _observation(
    manifest: RobustnessMatrixManifest,
    cell: RobustnessMatrixCell,
    *,
    critical_samples: int = 0,
    normalized_suffix: str = "stable",
) -> tuple[MissionExecutionEvaluation, ObservedMissionOutcome]:
    profile = next(item for item in manifest.profiles if item.profile_id == cell.profile_id)
    selected_case = next(item for item in manifest.selected_cases if item.case_id == cell.case_id)
    expected_failure = profile.expected_disposition is ExpectedDisposition.SAFE_FAILURE
    vehicles = tuple(
        VehicleExecutionMetrics(
            vehicle_id=f"vehicle-{index}",
            run_ids=(f"run-{cell.cell_id}-{index}",),
            telemetry_sample_count=20,
            command_count=5,
            acknowledgement_count=5,
            elapsed_s=(11.0 if cell.clock_mode is ClockMode.REALTIME else 10.0),
            unintended_stop_count=0,
            declared_hold_count=0,
            declared_hold_duration_s=0.0,
            minimum_boundary_margin_m=0.4,
            terminal_state="READY" if not expected_failure else "DISCONNECTED",
            trajectory_command_count=1,
            accepted_plan_identity_match=True,
            trajectory_generation_unintended_stop_count=0,
            landing_goal_id=(
                f"goal-{index}"
                if selected_case.require_goal_capture and not expected_failure
                else None
            ),
            goal_capture_attempt_count=(
                1 if selected_case.require_goal_capture and not expected_failure else None
            ),
            descent_authorized=(
                True if selected_case.require_goal_capture and not expected_failure else None
            ),
            terminal_goal_capture_margin_m=(
                0.05 if selected_case.require_goal_capture and not expected_failure else None
            ),
            terminal_contact=(
                "SIMULATED_GROUND_CONTACT"
                if selected_case.require_goal_capture and not expected_failure
                else None
            ),
        )
        for index in range(selected_case.role_count)
    )
    fleet = FleetExecutionMetrics(
        vehicle_count=selected_case.role_count,
        elapsed_s=(11.0 if cell.clock_mode is ClockMode.REALTIME else 10.0),
        minimum_truth_separation_m=(
            (selected_case.warning_separation_m or 0.75) + 0.10
            if selected_case.role_count > 1
            else None
        ),
        warning_sample_count=0,
        critical_sample_count=critical_samples,
        warning_separation_m=selected_case.warning_separation_m,
        critical_separation_m=selected_case.critical_separation_m,
        nominal_deconfliction_executed=(
            True if selected_case.role_count > 1 and not expected_failure else None
        ),
    )
    execution_id = f"execution-{cell.cell_id}"
    evaluation_payload = {
        "mission_execution_id": execution_id,
        "status": "COMPLETE",
        "evidence": EvidenceCompleteness(
            complete=True,
            present=("accepted_plan", "commands", "telemetry", "terminal_runs"),
            missing=(),
        ),
        "run_ids": tuple(item.run_ids[0] for item in vehicles),
        "vehicle_ids": tuple(item.vehicle_id for item in vehicles),
        "vehicles": vehicles,
        "fleet": fleet,
        "summary": ("Evidence is complete.",),
    }
    evaluation = MissionExecutionEvaluation(
        **evaluation_payload,
        report_sha256=canonical_sha256(evaluation_payload),
    )
    reason_code = profile.accepted_reason_codes[0] if expected_failure else "FLEET_COMPLETED"
    outcome = ObservedMissionOutcome(
        mission_execution_id=execution_id,
        status="FAILED" if expected_failure else "SUCCEEDED",
        reason_code=reason_code,
        normalized_outcome_sha256=canonical_sha256(
            [
                cell.profile_id,
                cell.case_id,
                cell.seed,
                cell.clock_mode,
                normalized_suffix,
            ]
        ),
        safe_terminal=True,
        expected_recovery_observed=expected_failure,
    )
    return evaluation, outcome


def _passing_observations(
    manifest: RobustnessMatrixManifest,
) -> dict[str, tuple[MissionExecutionEvaluation, ObservedMissionOutcome]]:
    return {cell.cell_sha256: _observation(manifest, cell) for cell in manifest.cells}


def test_default_matrix_is_deterministic_bounded_and_covers_every_wp25_profile() -> None:
    first = generate_robustness_matrix()
    second = generate_robustness_matrix()

    assert first == second
    assert len(first.selected_cases) == 3
    assert len(first.profiles) == 7
    assert len(first.cells) == 16
    assert {item.kind for item in first.profiles} == set(RobustnessProfileKind)
    assert {item.seed for item in first.cells} == {109, 811}
    assert {item.clock_mode for item in first.cells} == {
        ClockMode.ACCELERATED,
        ClockMode.REALTIME,
    }
    assert any(item.simulation_overrides.get("position_noise_std_m") for item in first.profiles)
    assert any(item.simulation_overrides.get("command_latency_s") for item in first.profiles)
    assert any(item.simulation_overrides.get("speed") for item in first.profiles)
    assert any(item.safety_overrides.get("command_timeout_s") for item in first.profiles)
    assert any(item.faults for item in first.profiles)
    assert all("isaac" not in item.profile_id for item in first.profiles)


def test_complete_passing_matrix_reconciles_clocks_and_builds_non_authorizing_handoff() -> None:
    manifest = generate_robustness_matrix()
    qualification = qualify_robustness(manifest, _passing_observations(manifest))

    assert qualification.passed is True
    assert qualification.missing_cell_sha256s == ()
    assert qualification.reproducible is True
    assert all(item.passed for item in qualification.profile_summaries)
    assert all(item.pass_rate == 1.0 for item in qualification.profile_summaries)
    assert len(qualification.clock_reconciliations) == 1
    assert all(item.passed for item in qualification.clock_reconciliations)
    assert all(
        item.model_sensitive_fields == ("elapsed_s", "tracking_error", "wall_clock_duration")
        for item in qualification.clock_reconciliations
    )

    handoff = build_higher_fidelity_handoff(manifest, qualification)
    assert len(handoff.selected_case_sha256s) == 3
    assert len(handoff.fast_sim_evaluation_report_sha256s) == 3
    assert handoff.isaac_status == "NOT_RUN"
    assert handoff.physical_status == "NOT_RUN"
    assert handoff.grants_execution_authority is False
    assert handoff.required_signals
    assert handoff.stop_conditions


def test_one_hard_safety_failure_blocks_matrix_instead_of_being_averaged() -> None:
    manifest = generate_robustness_matrix()
    observations = _passing_observations(manifest)
    target = next(item for item in manifest.cells if item.profile_id == "bounded-sensor-noise")
    observations[target.cell_sha256] = _observation(
        manifest,
        target,
        critical_samples=1,
    )

    qualification = qualify_robustness(manifest, observations)

    assert qualification.passed is False
    summary = next(
        item
        for item in qualification.profile_summaries
        if item.profile_id == "bounded-sensor-noise"
    )
    assert summary.hard_failure_count == 1
    assert "PROFILE_HARD_GATE_FAILED" in summary.findings
    assert "PROFILE_GATE_FAILED" in qualification.findings


def test_repeated_fault_profile_requires_same_normalized_outcome() -> None:
    manifest = generate_robustness_matrix()
    observations = _passing_observations(manifest)
    repeated = [
        item
        for item in manifest.cells
        if item.profile_id == "required-observation-loss" and item.seed == 109
    ]
    assert len(repeated) == 2
    observations[repeated[1].cell_sha256] = _observation(
        manifest,
        repeated[1],
        normalized_suffix="different",
    )

    qualification = qualify_robustness(manifest, observations)

    assert qualification.passed is False
    assert qualification.reproducible is False
    assert qualification.reproducibility_failures == (
        "required-observation-loss:robust-observation-loss:109:accelerated",
    )
    assert "REPRODUCIBILITY_FAILED" in qualification.findings
