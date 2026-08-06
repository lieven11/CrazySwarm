from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crazyswarm_app.missions.models import MissionResult, MissionRunSnapshot
from crazyswarm_app.observability.events import EvidenceEvent, EvidenceKind, TelemetryPayload


class EvidenceCorruptionError(RuntimeError):
    pass


class EvidenceStore:
    """SQLite WAL-backed append-only event store.

    Durability boundary: a return from ``append_event`` means SQLite committed the
    event with synchronous=FULL. A process crash can lose only events still queued
    upstream; committed rows are checksum-verified when read.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._connection: sqlite3.Connection | None = self._connect()
        self._lock = threading.Lock()
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def open(self) -> None:
        """Reopen the store after an application lifespan has stopped."""
        if self._connection is None:
            self._connection = self._connect()
            self._create_schema()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("evidence store is closed")
        return self._connection

    def _create_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                mission_version TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                configuration_hash TEXT NOT NULL,
                started_at_monotonic_s REAL NOT NULL,
                started_at_utc TEXT NOT NULL,
                status TEXT,
                snapshot_json TEXT NOT NULL,
                result_json TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                vehicle_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                source_timestamp_s REAL NOT NULL,
                received_timestamp_s REAL NOT NULL,
                recorded_at_utc TEXT NOT NULL,
                event_json TEXT NOT NULL,
                sha256 TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_run_sequence
                ON events(run_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_events_vehicle_time
                ON events(vehicle_id, source_timestamp_s);
            CREATE INDEX IF NOT EXISTS idx_events_kind_time
                ON events(kind, source_timestamp_s);
            """
        )
        self._db.commit()

    def begin_run(self, run: MissionRunSnapshot) -> None:
        snapshot_json = run.model_dump_json()
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT OR IGNORE INTO runs (
                    run_id, mission_id, mission_version, vehicle_id, mode,
                    configuration_hash, started_at_monotonic_s, started_at_utc, snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.mission_run_id,
                    run.mission_id,
                    run.mission_version,
                    run.vehicle_id,
                    run.mode.value,
                    run.configuration_hash,
                    run.started_at_monotonic_s,
                    datetime.now(UTC).isoformat(),
                    snapshot_json,
                ),
            )

    def complete_run(self, result: MissionResult) -> None:
        with self._lock, self._db:
            cursor = self._db.execute(
                "UPDATE runs SET status = ?, result_json = ? WHERE run_id = ?",
                (result.status.value, result.model_dump_json(), result.mission_run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"run has not been started: {result.mission_run_id}")

    def append_event(self, event: EvidenceEvent) -> None:
        event_json = event.model_dump_json()
        checksum = hashlib.sha256(event_json.encode()).hexdigest()
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT INTO events (
                    event_id, run_id, sequence, vehicle_id, kind,
                    source_timestamp_s, received_timestamp_s, recorded_at_utc,
                    event_json, sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.sequence,
                    event.vehicle_id,
                    event.kind.value,
                    event.source_timestamp_s,
                    event.received_timestamp_s,
                    event.recorded_at_utc.isoformat(),
                    event_json,
                    checksum,
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def list_runs(self, *, vehicle_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if vehicle_id is None:
            rows = self._db.execute(
                "SELECT * FROM runs ORDER BY started_at_utc DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM runs WHERE vehicle_id = ? ORDER BY started_at_utc DESC LIMIT ?",
                (vehicle_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def query_events(
        self,
        *,
        run_id: str | None = None,
        vehicle_id: str | None = None,
        kind: EvidenceKind | None = None,
        sensor: str | None = None,
        start_s: float | None = None,
        end_s: float | None = None,
        limit: int = 10_000,
    ) -> list[EvidenceEvent]:
        clauses: list[str] = []
        parameters: list[object] = []
        for column, value in (("run_id", run_id), ("vehicle_id", vehicle_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(kind.value)
        if start_s is not None:
            clauses.append("source_timestamp_s >= ?")
            parameters.append(start_s)
        if end_s is not None:
            clauses.append("source_timestamp_s <= ?")
            parameters.append(end_s)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        rows = self._db.execute(
            f"SELECT event_json, sha256 FROM events{where} ORDER BY sequence LIMIT ?",
            parameters,
        ).fetchall()
        events = [self._decode_event(row) for row in rows]
        if sensor is not None:
            events = [event for event in events if self._contains_sensor(event, sensor)]
        return events

    def integrity_check(self) -> None:
        result = self._db.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise EvidenceCorruptionError(f"SQLite integrity check failed: {result}")
        for row in self._db.execute("SELECT event_json, sha256 FROM events"):
            self._decode_event(row)

    def export_bundle(self, run_id: str, destination: Path) -> Path:
        run = self.get_run(run_id)
        events = self.query_events(run_id=run_id)
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "event_count": len(events),
            "exported_at_utc": datetime.now(UTC).isoformat(),
            "files": ["run.json", "events.ndjson"],
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
            bundle.writestr("run.json", json.dumps(run, indent=2, default=str))
            bundle.writestr(
                "events.ndjson",
                "\n".join(event.model_dump_json() for event in events) + "\n",
            )
        return destination

    def prune_completed(self, *, before_utc: datetime, keep_latest: int = 10) -> int:
        protected = {
            row[0]
            for row in self._db.execute(
                "SELECT run_id FROM runs ORDER BY started_at_utc DESC LIMIT ?", (keep_latest,)
            )
        }
        candidates = self._db.execute(
            "SELECT run_id FROM runs WHERE status IS NOT NULL AND started_at_utc < ?",
            (before_utc.isoformat(),),
        ).fetchall()
        selected = [row[0] for row in candidates if row[0] not in protected]
        with self._lock, self._db:
            for run_id in selected:
                self._db.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
                self._db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        return len(selected)

    @staticmethod
    def _decode_event(row: sqlite3.Row) -> EvidenceEvent:
        raw = str(row["event_json"])
        expected = str(row["sha256"])
        actual = hashlib.sha256(raw.encode()).hexdigest()
        if actual != expected:
            raise EvidenceCorruptionError("event checksum mismatch")
        return EvidenceEvent.model_validate_json(raw)

    @staticmethod
    def _contains_sensor(event: EvidenceEvent, sensor: str) -> bool:
        if not isinstance(event.payload, TelemetryPayload):
            return False
        telemetry = event.payload.telemetry.telemetry
        available = {
            "vehicle": True,
            "position": True,
            "battery": True,
            "link": True,
            "imu": telemetry.imu is not None,
            "flow": telemetry.flow is not None,
            "ranges": telemetry.ranges is not None,
        }
        return available.get(sensor, False)
