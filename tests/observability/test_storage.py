from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crazyswarm_app.domain.models import VehicleIdentity
from crazyswarm_app.missions.models import MissionStatus
from crazyswarm_app.missions.registry import default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.observability.bridge import EvidenceBridge
from crazyswarm_app.observability.bus import TelemetryBus
from crazyswarm_app.observability.events import EvidenceKind
from crazyswarm_app.observability.recorder import EvidenceRecorder
from crazyswarm_app.observability.storage import EvidenceCorruptionError, EvidenceStore
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
