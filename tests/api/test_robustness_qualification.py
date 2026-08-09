from __future__ import annotations

import time
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.models import VehicleState
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.observability.evaluation import MissionExecutionEvaluation
from crazyswarm_app.planning.robustness import (
    ObservedMissionOutcome,
    RobustnessMatrixCell,
    RobustnessMatrixManifest,
    assess_robustness_run,
    build_higher_fidelity_handoff,
    generate_robustness_matrix,
    qualify_robustness,
)
from crazyswarm_app.simulation.world import load_scenario
from tests.api.conftest import TOKEN, approve_mission_plan, auth_headers


def _execute_cell(
    tmp_path: Path,
    manifest: RobustnessMatrixManifest,
    cell: RobustnessMatrixCell,
) -> tuple[MissionExecutionEvaluation, ObservedMissionOutcome, dict[str, object]]:
    profile = next(item for item in manifest.profiles if item.profile_id == cell.profile_id)
    selected_case = next(item for item in manifest.selected_cases if item.case_id == cell.case_id)
    base_config = load_config(Path("config/app.yaml"))
    config = base_config.model_copy(
        update={
            "cache_directory": tmp_path / "cache",
            "safety_envelope": base_config.safety_envelope.model_copy(
                update=profile.safety_overrides
            ),
        }
    )
    assert canonical_sha256(config.safety_envelope) == cell.safety_configuration_sha256
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    simulation = scenario.simulation.model_copy(
        update={
            "seed": cell.seed,
            "clock_mode": cell.clock_mode,
            **profile.simulation_overrides,
        }
    )
    assert canonical_sha256(simulation) == cell.simulation_configuration_sha256
    scenario = scenario.model_copy(update={"simulation": simulation, "faults": profile.faults})
    runtime = create_runtime(
        config,
        scenario,
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    with TestClient(create_app(runtime, local_token=TOKEN)) as client:
        uploaded = client.post(
            "/api/v1/mission-files",
            headers=auth_headers(f"upload-{cell.cell_id}"),
            json={
                "name": selected_case.case_id,
                "filename": selected_case.mission_filename,
                "source": selected_case.mission_source,
            },
        )
        uploaded.raise_for_status()
        mission_id = cast(str, uploaded.json()["mission_id"])
        approval = approve_mission_plan(client, mission_id, f"approve-{cell.cell_id}")
        started = client.post(
            f"/api/v1/mission-files/{mission_id}/start",
            headers=auth_headers(f"play-{cell.cell_id}"),
            json={"execution_mode": "SIMULATION", **approval},
        )
        assert started.status_code == 200, started.json()
        run_id = cast(str, started.json()["mission_run_id"])
        for _ in range(60_000):
            status = client.get(
                f"/api/v1/mission-runs/{run_id}",
                headers=auth_headers(),
            ).json()
            if status.get("result") is not None:
                result = cast(dict[str, object], status["result"])
                break
            time.sleep(0.002)
        else:
            raise AssertionError(f"robustness mission did not terminate: {status}")
        evaluation = MissionExecutionEvaluation.model_validate(
            client.get(
                f"/api/v1/run-files/{run_id}/evaluation",
                headers=auth_headers(),
            ).json()
        )
        persisted_evaluation = MissionExecutionEvaluation.model_validate(
            client.get(
                f"/api/v1/run-files/{run_id}/evaluation.json",
                headers=auth_headers(),
            ).json()
        )
        assert persisted_evaluation == evaluation
        safe_terminal = all(
            runtime.supervisor.session(vehicle_id).state
            in {VehicleState.READY, VehicleState.DISCONNECTED}
            for vehicle_id in evaluation.vehicle_ids
        )
    normalized = result.get("normalized_outcome_sha256")
    if not isinstance(normalized, str):
        normalized = canonical_sha256(
            {
                "status": result["status"],
                "reason_code": result["reason_code"],
                "normalized_intent_trace": result.get("normalized_intent_trace", []),
                "goal_captures": result.get("goal_captures", []),
            }
        )
    outcome = ObservedMissionOutcome(
        mission_execution_id=evaluation.mission_execution_id,
        status=cast(str, result["status"]),
        reason_code=cast(str, result["reason_code"]),
        normalized_outcome_sha256=normalized,
        safe_terminal=safe_terminal,
        expected_recovery_observed=(safe_terminal and cast(str, result["status"]) != "SUCCEEDED"),
    )
    return evaluation, outcome, result


def test_complete_declared_matrix_qualifies_and_builds_backend_neutral_handoff(
    tmp_path: Path,
) -> None:
    manifest = generate_robustness_matrix()
    evidence = {}
    for cell in manifest.cells:
        evaluation, outcome, _ = _execute_cell(
            tmp_path / cell.cell_id,
            manifest,
            cell,
        )
        assessment = assess_robustness_run(manifest, cell, evaluation, outcome)
        assert assessment.passed is True, (cell.cell_id, assessment.findings)
        assert assessment.evidence_complete is True
        assert assessment.plan_identity_preserved is True
        assert assessment.safe_terminal is True
        assert assessment.warning_samples == 0
        assert assessment.critical_samples == 0
        evidence[cell.cell_sha256] = (evaluation, outcome)

    qualification = qualify_robustness(manifest, evidence)
    assert qualification.passed is True
    assert qualification.reproducible is True
    assert qualification.missing_cell_sha256s == ()
    assert all(item.pass_rate == 1.0 for item in qualification.profile_summaries)
    assert all(item.hard_failure_count == 0 for item in qualification.profile_summaries)
    assert all(item.passed for item in qualification.clock_reconciliations)
    handoff = build_higher_fidelity_handoff(manifest, qualification)
    assert handoff.isaac_status == "NOT_RUN"
    assert handoff.physical_status == "NOT_RUN"
    assert handoff.grants_execution_authority is False
    assert len(handoff.selected_case_sha256s) == 3
