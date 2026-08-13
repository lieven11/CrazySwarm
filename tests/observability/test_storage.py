from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crazyswarm_app.domain.models import VehicleIdentity
from crazyswarm_app.missions.models import MissionResult, MissionRunSnapshot, MissionStatus
from crazyswarm_app.missions.registry import default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.observability.bridge import EvidenceBridge
from crazyswarm_app.observability.bus import TelemetryBus
from crazyswarm_app.observability.csv_export import RUN_TELEMETRY_CSV_COLUMNS
from crazyswarm_app.observability.events import EvidenceKind, TelemetryPayload
from crazyswarm_app.observability.recorder import EvidenceRecorder
from crazyswarm_app.observability.storage import (
    EvidenceCorruptionError,
    EvidenceStore,
    IncompleteRunError,
)
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig


async def recorded_mission(path: Path) -> tuple[EvidenceStore, str]:
    bus = TelemetryBus()
    mode_holder: dict[str, SafetySupervisor] = {}
    bridge = EvidenceBridge(bus, mode_provider=lambda: mode_holder["supervisor"].mode)
    supervisor = SafetySupervisor(audit_sinks=(bridge,))
    mode_holder["supervisor"] = supervisor
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Sim 01", adapter="sim"),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=1.0)),
    )
    supervisor.register_vehicle(vehicle)
    runner = MissionRunner(supervisor, default_registry(), audit_sinks=(bridge,))
    store = EvidenceStore(path)
    recorder = EvidenceRecorder(bus, store)
    await recorder.start()
    result = await runner.run("hover", "sim01", parameters={"duration_s": 0.1})
    await recorder.stop()
    assert result.status is MissionStatus.SUCCEEDED
    return store, result.mission_run_id


@pytest.mark.asyncio
async def test_complete_mission_evidence_is_transactional_and_queryable(tmp_path: Path) -> None:
    store, run_id = await recorded_mission(tmp_path / "evidence.sqlite3")
    run = store.get_run(run_id)
    assert run["status"] == "SUCCEEDED"
    assert len(run["configuration_hash"]) == 64
    events = store.query_events(run_id=run_id)
    kinds = {event.kind for event in events}
    assert {
        EvidenceKind.MISSION_STARTED,
        EvidenceKind.COMMAND,
        EvidenceKind.ACKNOWLEDGEMENT,
        EvidenceKind.STATE,
        EvidenceKind.TELEMETRY,
        EvidenceKind.MISSION_RESULT,
    }.issubset(kinds)
    assert [event.sequence for event in events] == sorted(event.sequence for event in events)
    for sample in store.query_events(run_id=run_id, kind=EvidenceKind.TELEMETRY):
        assert sample.vehicle_id == "sim01"
        assert sample.run_id == run_id
        assert sample.source
        assert sample.unit == "SI"
        assert sample.frame is not None
        assert sample.frame.value in {"world", "home"}
    assert store.query_events(run_id=run_id, sensor="imu")
    store.integrity_check()
    store.close()


@pytest.mark.asyncio
async def test_committed_evidence_survives_reopen_and_exports_bundle(tmp_path: Path) -> None:
    database = tmp_path / "evidence.sqlite3"
    store, run_id = await recorded_mission(database)
    expected_count = len(store.query_events(run_id=run_id))
    store.close()

    recovered = EvidenceStore(database)
    recovered.integrity_check()
    assert len(recovered.query_events(run_id=run_id)) == expected_count
    bundle = recovered.export_bundle(run_id, tmp_path / "diagnostic.zip")
    with zipfile.ZipFile(bundle) as archive:
        assert set(archive.namelist()) == {"manifest.json", "run.json", "events.ndjson"}
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["event_count"] == expected_count
    recovered.close()


@pytest.mark.asyncio
async def test_terminal_run_exports_deterministic_rfc4180_telemetry_csv(
    tmp_path: Path,
) -> None:
    store, run_id = await recorded_mission(tmp_path / "telemetry-csv.sqlite3")

    first = store.export_telemetry_csv(run_id)
    second = store.export_telemetry_csv(run_id)

    assert first == second
    assert first.sha256 == hashlib.sha256(first.content).hexdigest()
    assert first.filename.endswith(f"_{run_id[:12]}_telemetry-v1.csv")
    assert first.content.endswith(b"\r\n")
    assert b"\r\n" in first.content
    text = first.content.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    assert tuple(rows[0]) == RUN_TELEMETRY_CSV_COLUMNS
    assert len(rows) == first.row_count
    assert first.row_count > 0
    assert [int(row["event_sequence"]) for row in rows] == sorted(
        int(row["event_sequence"]) for row in rows
    )
    assert {row["run_id"] for row in rows} == {run_id}
    assert {row["csv_schema_version"] for row in rows} == {"1"}
    assert {row["operating_mode"] for row in rows} == {"SIM"}
    assert all(row["recorded_at_utc"].endswith("Z") for row in rows)
    assert {row["replay_timestamp_s"] for row in rows} == {""}
    assert {row["armed"] for row in rows}.issubset({"true", "false"})
    assert {row["flying"] for row in rows}.issubset({"true", "false"})
    assert all(row["faults_json"].startswith("[") for row in rows)
    store.close()


@pytest.mark.asyncio
async def test_legacy_motor_evidence_exports_unrecorded_fields_as_blank(
    tmp_path: Path,
) -> None:
    store, run_id = await recorded_mission(tmp_path / "legacy-motor-evidence.sqlite3")
    event = next(
        item
        for item in store.query_events(run_id=run_id, kind=EvidenceKind.TELEMETRY)
        if isinstance(item.payload, TelemetryPayload)
        and item.payload.telemetry.telemetry.motors is not None
    )
    assert isinstance(event.payload, TelemetryPayload)
    legacy = event.model_dump(mode="json")
    readings = legacy["payload"]["telemetry"]["telemetry"]["motors"]["readings"]
    for reading in readings:
        for field in (
            "requested_thrust_n",
            "applied_pwm_percent",
            "motor_voltage_v",
            "available_thrust_n",
        ):
            reading.pop(field)
    raw = json.dumps(legacy, separators=(",", ":"))
    with store._lock, store._db:
        store._db.execute(
            "UPDATE events SET event_json = ?, sha256 = ? WHERE event_id = ?",
            (raw, hashlib.sha256(raw.encode()).hexdigest(), event.event_id),
        )

    recovered = next(
        item
        for item in store.query_events(run_id=run_id, kind=EvidenceKind.TELEMETRY)
        if item.event_id == event.event_id
    )
    assert isinstance(recovered.payload, TelemetryPayload)
    assert recovered.payload.telemetry.telemetry.motors is not None
    assert recovered.payload.telemetry.telemetry.motors.readings[0].motor_voltage_v is None
    artifact = store.export_telemetry_csv(run_id)
    row = next(
        item
        for item in csv.DictReader(io.StringIO(artifact.content.decode(), newline=""))
        if item["event_id"] == event.event_id
    )
    assert row["motor_m1_requested_thrust_n"] == ""
    assert row["motor_m1_applied_pwm_percent"] == ""
    assert row["motor_m1_voltage_v"] == ""
    assert row["motor_m1_available_thrust_n"] == ""
    store.close()


@pytest.mark.asyncio
async def test_incomplete_run_is_rejected_and_zero_sample_terminal_csv_has_header(
    tmp_path: Path,
) -> None:
    store, source_run_id = await recorded_mission(tmp_path / "zero-telemetry-csv.sqlite3")
    source = store.get_run(source_run_id)
    snapshot = MissionRunSnapshot.model_validate_json(source["snapshot_json"])
    result = MissionResult.model_validate_json(source["result_json"])

    incomplete_id = "run-incomplete-csv"
    store.begin_run(snapshot.model_copy(update={"mission_run_id": incomplete_id}))
    with pytest.raises(IncompleteRunError):
        store.export_telemetry_csv(incomplete_id)

    zero_id = "run-zero-telemetry"
    store.begin_run(snapshot.model_copy(update={"mission_run_id": zero_id}))
    store.complete_run(result.model_copy(update={"mission_run_id": zero_id}))
    artifact = store.export_telemetry_csv(zero_id)
    assert artifact.row_count == 0
    assert artifact.content.decode("utf-8") == ",".join(RUN_TELEMETRY_CSV_COLUMNS) + "\r\n"

    run_rows = {row["run_id"]: row for row in store.list_runs(limit=10)}
    assert run_rows[source_run_id]["telemetry_row_count"] > 0
    assert run_rows[zero_id]["telemetry_row_count"] == 0
    store.close()


@pytest.mark.asyncio
async def test_system_evidence_survives_process_sequence_restart(tmp_path: Path) -> None:
    database = tmp_path / "evidence.sqlite3"
    system_run_ids: list[str] = []

    for cycle in range(2):
        bus = TelemetryBus()
        bridge = EvidenceBridge(bus)
        store = EvidenceStore(database)
        recorder = EvidenceRecorder(bus, store)
        await recorder.start()
        bridge.operator_action(
            vehicle_id="sim01",
            client_id="restart-test",
            request_id=f"restart-{cycle}",
            action="application_start",
        )
        await recorder.stop()
        events = store.query_events(kind=EvidenceKind.OPERATOR_ACTION)
        system_run_ids.append(events[-1].run_id)
        store.close()

    recovered = EvidenceStore(database)
    actions = recovered.query_events(kind=EvidenceKind.OPERATOR_ACTION)
    assert len(actions) == 2
    assert len(set(system_run_ids)) == 2
    recovered.close()


@pytest.mark.asyncio
async def test_recorder_shutdown_is_bounded_after_writer_failure(tmp_path: Path) -> None:
    bus = TelemetryBus()
    bridge = EvidenceBridge(bus)
    store = EvidenceStore(tmp_path / "failed.sqlite3")
    recorder = EvidenceRecorder(bus, store)
    await recorder.start()
    store.close()
    bridge.operator_action(
        vehicle_id="sim01",
        client_id="failure-test",
        request_id="failure-test",
        action="force_closed_store_write",
    )
    assert recorder._task is not None
    with pytest.raises(RuntimeError, match="closed"):
        await recorder._task
    await recorder.stop(flush_timeout_s=0.01)
    assert recorder.last_error is not None
    assert "closed" in recorder.last_error


@pytest.mark.asyncio
async def test_recorder_shutdown_drops_backlog_after_timeout(tmp_path: Path) -> None:
    bus = TelemetryBus()
    store = EvidenceStore(tmp_path / "timeout.sqlite3")
    recorder = EvidenceRecorder(bus, store)
    await recorder.start()
    assert recorder._task is not None
    recorder._task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await recorder._task
    bridge = EvidenceBridge(bus)
    bridge.operator_action(
        vehicle_id="sim01",
        client_id="timeout-test",
        request_id="timeout-test",
        action="queued_after_writer_stop",
    )
    await recorder.stop(flush_timeout_s=0.01)
    assert recorder.shutdown_dropped_events == 1
    store.close()


@pytest.mark.asyncio
async def test_checksum_corruption_is_reported_not_silently_ignored(tmp_path: Path) -> None:
    database = tmp_path / "evidence.sqlite3"
    store, run_id = await recorded_mission(database)
    store.close()
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE events SET event_json = ? WHERE event_id = (SELECT event_id FROM events LIMIT 1)",
        ("{}",),
    )
    connection.commit()
    connection.close()

    corrupted = EvidenceStore(database)
    with pytest.raises(EvidenceCorruptionError, match="checksum"):
        corrupted.query_events(run_id=run_id)
    corrupted.close()


@pytest.mark.asyncio
async def test_retention_prunes_only_completed_unprotected_runs(tmp_path: Path) -> None:
    database = tmp_path / "evidence.sqlite3"
    first_store, first_run = await recorded_mission(database)
    first_store.close()
    second_store, second_run = await recorded_mission(database)
    removed = second_store.prune_completed(
        before_utc=datetime.now(UTC) + timedelta(days=1),
        keep_latest=1,
    )
    assert removed == 1
    assert second_store.get_run(second_run)["run_id"] == second_run
    with pytest.raises(KeyError):
        second_store.get_run(first_run)
    second_store.close()


@pytest.mark.asyncio
async def test_persists_one_atomic_mission_folder_with_one_csv_for_all_vehicles(
    tmp_path: Path,
) -> None:
    source, source_run_id = await recorded_mission(tmp_path / "source.sqlite3")
    source_row = source.get_run(source_run_id)
    snapshot = MissionRunSnapshot.model_validate_json(source_row["snapshot_json"])
    result = MissionResult.model_validate_json(source_row["result_json"])
    source_events = source.query_events(run_id=source_run_id)
    source.close()

    archive = tmp_path / "run-files"
    store = EvidenceStore(
        tmp_path / "grouped.sqlite3",
        run_files_directory=archive,
        keep_latest_missions=100,
    )
    execution_id = "run-crossing-execution"
    members = (("run-south", "cross_south"), ("run-west", "cross_west"))
    for run_id, vehicle_id in members:
        store.begin_run(
            snapshot.model_copy(
                update={
                    "mission_run_id": run_id,
                    "mission_execution_id": execution_id,
                    "mission_id": "crossing-route",
                    "mission_name": "crossing_route_separation",
                    "vehicle_id": vehicle_id,
                }
            )
        )
        for event in source_events:
            store.append_event(
                event.model_copy(
                    update={
                        "event_id": f"copy-{vehicle_id}-{event.event_id}",
                        "run_id": run_id,
                        "vehicle_id": vehicle_id,
                    }
                )
            )

    first_run, first_vehicle = members[0]
    store.complete_run(
        result.model_copy(
            update={
                "mission_run_id": first_run,
                "mission_execution_id": execution_id,
                "mission_id": "crossing-route",
                "mission_name": "crossing_route_separation",
                "vehicle_id": first_vehicle,
            }
        )
    )
    partial = store.materialize_run_files_for_run(first_run)
    assert partial["status"] == "INCOMPLETE"
    assert partial["artifact"]["filename"] is None
    legacy_file = next(path for path in archive.iterdir() if path.is_dir()) / (
        "cross_south_run-south_telemetry-v1.csv"
    )
    legacy_file.write_text("superseded per-drone export", encoding="utf-8")

    second_run, second_vehicle = members[1]
    store.complete_run(
        result.model_copy(
            update={
                "mission_run_id": second_run,
                "mission_execution_id": execution_id,
                "mission_id": "crossing-route",
                "mission_name": "crossing_route_separation",
                "vehicle_id": second_vehicle,
                "status": MissionStatus.ABORTED,
                "reason_code": "OPERATOR_ABORT",
            }
        )
    )
    manifest = store.materialize_run_files_for_run(second_run)

    assert manifest["mission_execution_id"] == execution_id
    assert manifest["schema_version"] == 2
    assert manifest["mission_name"] == "crossing_route_separation"
    assert manifest["status"] == "ABORTED"
    assert manifest["vehicle_ids"] == ["cross_south", "cross_west"]
    assert manifest["artifact"]["vehicle_ids"] == ["cross_south", "cross_west"]
    assert manifest["artifact"]["run_ids"] == ["run-south", "run-west"]
    assert not list(archive.rglob("*.tmp"))
    folders = [path for path in archive.iterdir() if path.is_dir()]
    assert len(folders) == 1
    persisted_manifest = json.loads((folders[0] / "manifest.json").read_text())
    assert persisted_manifest == manifest
    csv_files = list(folders[0].glob("*_telemetry-v1.csv"))
    assert len(csv_files) == 1
    csv_path = csv_files[0]
    item = manifest["artifact"]
    assert csv_path.name == item["filename"]
    assert csv_path.stat().st_size == item["size_bytes"]
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == item["sha256"]
    csv_rows = list(csv.DictReader(io.StringIO(csv_path.read_text(), newline="")))
    assert len(csv_rows) == item["telemetry_row_count"]
    assert {row["vehicle_id"] for row in csv_rows} == {"cross_south", "cross_west"}
    assert {row["run_id"] for row in csv_rows} == {"run-south", "run-west"}
    store.close()


@pytest.mark.asyncio
async def test_deleting_completed_mission_removes_evidence_and_archive_folder(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "run-files"
    store, run_id = await recorded_mission(tmp_path / "delete-mission.sqlite3")
    store.run_files_directory = archive
    store.materialize_run_files_for_run(run_id)
    folder = next(path for path in archive.iterdir() if path.is_dir())

    deleted = store.delete_run_file_mission(run_id)

    assert deleted == {"mission_execution_id": run_id, "deleted_run_ids": [run_id]}
    assert not folder.exists()
    assert store.list_run_file_missions() == []
    with pytest.raises(KeyError):
        store.get_run(run_id)
    store.close()


@pytest.mark.asyncio
async def test_backfill_skips_complete_archives_and_repairs_missing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, run_id = await recorded_mission(tmp_path / "backfill.sqlite3")
    manifest = store.list_run_file_missions()[0]
    folder = Path(str(manifest["_folder"]))
    bundle = manifest["bundle"]
    bundle_path = folder / str(bundle["filename"])
    original_materialize = store._materialize_mission
    materialized: list[str] = []

    def track_materialization(mission_execution_id: str) -> dict[str, object]:
        materialized.append(mission_execution_id)
        return original_materialize(mission_execution_id)

    monkeypatch.setattr(store, "_materialize_mission", track_materialization)

    assert store.backfill_run_files() == 0
    assert materialized == []

    bundle_path.unlink()
    assert store.backfill_run_files() == 1
    assert materialized == [run_id]
    assert bundle_path.stat().st_size == bundle["size_bytes"]
    store.close()


@pytest.mark.asyncio
async def test_mission_retention_keeps_latest_completed_folder_and_active_group(
    tmp_path: Path,
) -> None:
    source, source_run_id = await recorded_mission(tmp_path / "retention-source.sqlite3")
    source_row = source.get_run(source_run_id)
    snapshot = MissionRunSnapshot.model_validate_json(source_row["snapshot_json"])
    result = MissionResult.model_validate_json(source_row["result_json"])
    source.close()

    store = EvidenceStore(
        tmp_path / "retention-groups.sqlite3",
        run_files_directory=tmp_path / "retained-run-files",
        keep_latest_missions=1,
    )
    active_runs = ("run-active-complete-member", "run-active-recording-member")
    for run_id in active_runs:
        store.begin_run(
            snapshot.model_copy(
                update={
                    "mission_run_id": run_id,
                    "mission_execution_id": "mission-active",
                }
            )
        )
    store.complete_run(
        result.model_copy(
            update={
                "mission_run_id": active_runs[0],
                "mission_execution_id": "mission-active",
            }
        )
    )
    store.materialize_run_files_for_run(active_runs[0])

    for execution_id in ("mission-complete-1", "mission-complete-2"):
        run_id = f"run-{execution_id}"
        store.begin_run(
            snapshot.model_copy(
                update={
                    "mission_run_id": run_id,
                    "mission_execution_id": execution_id,
                }
            )
        )
        store.complete_run(
            result.model_copy(
                update={
                    "mission_run_id": run_id,
                    "mission_execution_id": execution_id,
                }
            )
        )
        store.materialize_run_files_for_run(run_id)

    manifests = store.list_run_file_missions()
    assert {item["mission_execution_id"] for item in manifests} == {
        "mission-active",
        "mission-complete-2",
    }
    assert store.get_run(active_runs[1])["status"] is None
    with pytest.raises(KeyError):
        store.get_run("run-mission-complete-1")
    store.close()


def test_run_kind_index_covers_history_counts_and_exports(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "indexed.sqlite3")
    indexes = {str(row[1]) for row in store._db.execute("PRAGMA index_list('events')").fetchall()}
    assert "idx_events_run_kind" in indexes
    plan = store._db.execute(
        "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM events WHERE run_id = ? AND kind = ?",
        ("run-id", EvidenceKind.TELEMETRY.value),
    ).fetchall()
    assert any("idx_events_run_kind" in str(row[3]) for row in plan)
    store.close()
