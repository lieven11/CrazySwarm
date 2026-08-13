from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.missions.models import MissionResult, MissionRunSnapshot
from crazyswarm_app.observability.evaluation import (
    EvaluationStatus,
    evaluate_mission_execution,
)
from crazyswarm_app.observability.events import EvidenceEvent, TelemetryPayload
from crazyswarm_app.observability.storage import EvidenceStore
from tests.observability.test_storage import recorded_mission


def execution_context(vehicle_ids: tuple[str, ...]) -> dict[str, Any]:
    roles = [
        {
            "role_id": f"role-{index}",
            "vehicle_id": vehicle_id,
            "planned_duration_s": 2.0,
            "waypoints": [
                {
                    "sequence": 1,
                    "action": "land",
                    "starts_at_s": 1.0,
                    "ends_at_s": 2.0,
                    "start_m": {"x": float(index), "y": 0.0, "z": 0.5},
                    "end_m": {"x": float(index), "y": 0.0, "z": 0.0},
                    "start_yaw_rad": 0.0,
                    "end_yaw_rad": 0.0,
                }
            ],
        }
        for index, vehicle_id in enumerate(vehicle_ids)
    ]
    return {
        "deployment": {"deployment_id": "evaluation-deployment"},
        "binding": {"backend": "FAST_SIM"},
        "assignments": {
            f"role-{index}": vehicle_id for index, vehicle_id in enumerate(vehicle_ids)
        },
        "mission_plan": {
            "roles": roles,
            "safety": {
                "flight_volume_minimum_m": {"x": -2.0, "y": -2.0, "z": 0.0},
                "flight_volume_maximum_m": {"x": 2.0, "y": 2.0, "z": 2.0},
                "warning_separation_m": 0.75,
                "critical_separation_m": 0.4,
            },
            "planning": {
                "route_plans": [{"expected_minimum_separation_m": 0.8} for _ in vehicle_ids]
            },
        },
        "fleet_events": ([{"event_type": "MISSION_STARTED"}] if len(vehicle_ids) > 1 else []),
        "execution_result": {"status": "SUCCEEDED"},
    }


@pytest.mark.parametrize(
    "relative_path",
    (
        "20260811T155020Z_Campaign_1d.altitude_transition.canonical_nominal_"
        "campaign-run-ea696b52d37c22c5a1f2/Campaign_1d.altitude_transition."
        "canonical_nominal_campaign-run-ea696b52d37c22c5a1f2_execution-bundle-v1.json",
        "20260811T161111Z_Campaign_1d.altitude_transition.wide_"
        "campaign-run-c56e371bd418c389ef11/Campaign_1d.altitude_transition.wide_"
        "campaign-run-c56e371bd418c389ef11_execution-bundle-v1.json",
    ),
)
def test_retained_campaign_bundle_reconciles_accepted_authority(
    relative_path: str,
) -> None:
    path = Path("run-files") / relative_path
    bundle = json.loads(path.read_text(encoding="utf-8"))
    runs = [
        {
            **run,
            "snapshot_json": json.dumps(run["snapshot"]),
            "result_json": json.dumps(run["result"]),
        }
        for run in bundle["runs"]
    ]
    evaluation = evaluate_mission_execution(
        mission_execution_id=bundle["mission_execution_id"],
        runs=runs,
        events=[EvidenceEvent.model_validate(item) for item in bundle["events"]],
        context=bundle["context"],
    )

    assert evaluation.status is EvaluationStatus.COMPLETE
    assert evaluation.evidence.missing == ()
    assert evaluation.vehicles[0].accepted_plan_identity_match is True
    assert evaluation.vehicles[0].unintended_stop_count == 0


def test_mismatched_accepted_authority_fails_evidence_completeness() -> None:
    path = Path(
        "run-files/20260811T155020Z_Campaign_1d.altitude_transition.canonical_nominal_"
        "campaign-run-ea696b52d37c22c5a1f2/Campaign_1d.altitude_transition."
        "canonical_nominal_campaign-run-ea696b52d37c22c5a1f2_execution-bundle-v1.json"
    )
    bundle = json.loads(path.read_text(encoding="utf-8"))
    for event in bundle["events"]:
        command = event.get("payload", {}).get("command", {})
        payload = command.get("payload", {})
        if payload.get("kind") == "execute_trajectory":
            payload["accepted_plan_sha256"] = "0" * 64
    runs = [
        {
            **run,
            "snapshot_json": json.dumps(run["snapshot"]),
            "result_json": json.dumps(run["result"]),
        }
        for run in bundle["runs"]
    ]

    evaluation = evaluate_mission_execution(
        mission_execution_id=bundle["mission_execution_id"],
        runs=runs,
        events=[EvidenceEvent.model_validate(item) for item in bundle["events"]],
        context=bundle["context"],
    )

    assert evaluation.vehicles[0].accepted_plan_identity_match is False
    assert evaluation.status is EvaluationStatus.INCOMPLETE
    assert "accepted_authority_identity" in evaluation.evidence.missing


@pytest.mark.asyncio
async def test_single_run_evaluation_is_deterministic_and_faults_are_run_scoped(
    tmp_path: Path,
) -> None:
    store, run_id = await recorded_mission(tmp_path / "evaluation.sqlite3")
    store.upsert_execution_context(run_id, execution_context(("sim01",)))

    first = store.evaluate_mission_execution(run_id)
    second = store.evaluate_mission_execution(run_id)
    assert first == second
    assert first.status is EvaluationStatus.COMPLETE
    assert first.evidence.complete
    assert first.report_sha256 == canonical_sha256(first.canonical_payload())
    assert first.shared_time_basis == "recorded_at_utc"
    assert first.vehicles[0].telemetry_sample_count > 0
    assert first.summary

    events = store.query_events(run_id=run_id, limit=None)
    telemetry_indexes = [
        index for index, event in enumerate(events) if isinstance(event.payload, TelemetryPayload)
    ]
    assert len(telemetry_indexes) >= 2
    scoped_events = list(events)
    for offset, faults in enumerate((("inherited-link",), ("inherited-link", "new-motor"))):
        index = telemetry_indexes[offset]
        event = scoped_events[index]
        assert isinstance(event.payload, TelemetryPayload)
        telemetry = event.payload.telemetry
        sample = telemetry.telemetry.model_copy(update={"faults": faults})
        payload = event.payload.model_copy(
            update={"telemetry": telemetry.model_copy(update={"telemetry": sample})}
        )
        scoped_events[index] = event.model_copy(update={"payload": payload})
    scoped = evaluate_mission_execution(
        mission_execution_id=run_id,
        runs=[store.get_run(run_id)],
        events=scoped_events,
        context=execution_context(("sim01",)),
    )
    assert scoped.vehicles[0].inherited_faults == ("inherited-link",)
    assert scoped.vehicles[0].new_faults == ("new-motor",)

    manifest = store.materialize_mission_execution(run_id)
    evaluation_artifact = store.get_persisted_execution_evaluation(run_id)
    bundle_artifact = store.get_persisted_execution_bundle(run_id)
    evaluation_bytes = Path(evaluation_artifact["path"]).read_bytes()
    bundle_bytes = Path(bundle_artifact["path"]).read_bytes()
    assert hashlib.sha256(evaluation_bytes).hexdigest() == manifest["evaluation"]["sha256"]
    assert hashlib.sha256(bundle_bytes).hexdigest() == manifest["bundle"]["sha256"]
    bundle = json.loads(bundle_bytes)
    assert bundle["mission_execution_id"] == run_id
    assert {item["kind"] for item in bundle["events"]} >= {
        "telemetry",
        "command",
        "acknowledgement",
        "mission_result",
    }

    store.add_execution_annotation(
        run_id,
        annotation_id="annotation-operator-1",
        author_id="operator-1",
        note="landing looked early",
        created_at_utc=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
    )
    annotated = store.evaluate_mission_execution(run_id)
    assert annotated.annotations[0].note == "landing looked early"
    assert annotated.report_sha256 != first.report_sha256
    assert store.evaluate_mission_execution(run_id) == annotated
    store.close()


@pytest.mark.asyncio
async def test_grouped_crossing_bundle_contains_both_children_and_fleet_metrics(
    tmp_path: Path,
) -> None:
    source, source_run_id = await recorded_mission(tmp_path / "source.sqlite3")
    source_row = source.get_run(source_run_id)
    snapshot = MissionRunSnapshot.model_validate_json(source_row["snapshot_json"])
    result = MissionResult.model_validate_json(source_row["result_json"])
    source_events = source.query_events(run_id=source_run_id, limit=None)
    source.close()

    store = EvidenceStore(
        tmp_path / "grouped.sqlite3",
        run_files_directory=tmp_path / "run-files",
    )
    execution_id = "crossing-evaluation"
    members = (("run-south", "cross_south"), ("run-west", "cross_west"))
    store.upsert_execution_context(
        execution_id,
        execution_context(tuple(vehicle_id for _, vehicle_id in members)),
    )
    for run_id, vehicle_id in members:
        store.begin_run(
            snapshot.model_copy(
                update={
                    "mission_run_id": run_id,
                    "mission_execution_id": execution_id,
                    "vehicle_id": vehicle_id,
                }
            )
        )
        for event in source_events:
            store.append_event(
                event.model_copy(
                    update={
                        "event_id": f"{vehicle_id}-{event.event_id}",
                        "run_id": run_id,
                        "vehicle_id": vehicle_id,
                    }
                )
            )
        store.complete_run(
            result.model_copy(
                update={
                    "mission_run_id": run_id,
                    "mission_execution_id": execution_id,
                    "vehicle_id": vehicle_id,
                }
            )
        )

    first_manifest = store.materialize_mission_execution(execution_id)
    first_report = store.evaluate_mission_execution(execution_id)
    second_manifest = store.materialize_mission_execution(execution_id)
    second_report = store.evaluate_mission_execution(execution_id)

    assert first_report == second_report
    assert first_report.status is EvaluationStatus.COMPLETE
    assert first_report.run_ids == ("run-south", "run-west")
    assert first_report.vehicle_ids == ("cross_south", "cross_west")
    assert first_report.fleet.vehicle_count == 2
    assert first_report.fleet.minimum_truth_separation_m == pytest.approx(0.0)
    assert first_report.fleet.critical_sample_count > 0
    assert first_manifest["evaluation"]["sha256"] == second_manifest["evaluation"]["sha256"]
    assert first_manifest["bundle"]["sha256"] == second_manifest["bundle"]["sha256"]
    bundle_path = Path(store.get_persisted_execution_bundle(execution_id)["path"])
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert {item["vehicle_id"] for item in bundle["runs"]} == {
        "cross_south",
        "cross_west",
    }
    assert bundle["evaluation"]["evidence"]["complete"] is True
    store.close()
