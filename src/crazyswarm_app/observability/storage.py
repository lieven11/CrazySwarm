from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crazyswarm_app.missions.models import MissionResult, MissionRunSnapshot
from crazyswarm_app.observability.csv_export import (
    RunTelemetryCsvArtifact,
    serialize_mission_telemetry_csv,
    serialize_run_telemetry_csv,
)
from crazyswarm_app.observability.evaluation import (
    MISSION_EXECUTION_BUNDLE_CONTRACT,
    MISSION_EXECUTION_EVALUATION_CONTRACT,
    MissionExecutionEvaluation,
    build_execution_bundle,
    evaluate_mission_execution,
)
from crazyswarm_app.observability.events import EvidenceEvent, EvidenceKind, TelemetryPayload


class EvidenceCorruptionError(RuntimeError):
    pass


class IncompleteRunError(RuntimeError):
    pass


class EvidenceStore:
    """SQLite WAL-backed append-only event store.

    Durability boundary: a return from ``append_event`` means SQLite committed the
    event with synchronous=FULL. A process crash can lose only events still queued
    upstream; committed rows are checksum-verified when read.
    """

    def __init__(
        self,
        path: Path,
        *,
        run_files_directory: Path | None = None,
        keep_latest_missions: int = 100,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if keep_latest_missions < 1:
            raise ValueError("keep_latest_missions must be at least 1")
        self.path = path
        self.run_files_directory = run_files_directory or path.parent / "run-files"
        self.keep_latest_missions = keep_latest_missions
        self._connection: sqlite3.Connection | None = self._connect()
        self._lock = threading.Lock()
        self._artifact_lock = threading.Lock()
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def open(self) -> None:
        """Reopen the store after an application lifespan has stopped."""
        with self._lock:
            if self._connection is None:
                self._connection = self._connect()
                self._create_schema()

    def close(self) -> None:
        with self._lock:
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
                mission_execution_id TEXT,
                mission_id TEXT NOT NULL,
                mission_name TEXT,
                mission_version TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                configuration_hash TEXT NOT NULL,
                started_at_monotonic_s REAL NOT NULL,
                started_at_utc TEXT NOT NULL,
                completed_at_utc TEXT,
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
            CREATE INDEX IF NOT EXISTS idx_events_run_kind
                ON events(run_id, kind);
            CREATE TABLE IF NOT EXISTS execution_contexts (
                mission_execution_id TEXT PRIMARY KEY,
                context_json TEXT NOT NULL,
                sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS execution_annotations (
                annotation_id TEXT PRIMARY KEY,
                mission_execution_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_execution_annotations_execution
                ON execution_annotations(mission_execution_id, created_at_utc, annotation_id);
            """
        )
        run_columns = {
            str(row[1]) for row in self._db.execute("PRAGMA table_info(runs)").fetchall()
        }
        for column, declaration in (
            ("mission_execution_id", "TEXT"),
            ("mission_name", "TEXT"),
            ("completed_at_utc", "TEXT"),
        ):
            if column not in run_columns:
                self._db.execute(f"ALTER TABLE runs ADD COLUMN {column} {declaration}")
        self._db.execute(
            "UPDATE runs SET mission_execution_id = run_id WHERE mission_execution_id IS NULL"
        )
        self._db.execute("UPDATE runs SET mission_name = mission_id WHERE mission_name IS NULL")
        self._recover_legacy_execution_ids()
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_mission_execution "
            "ON runs(mission_execution_id, started_at_utc)"
        )
        self._db.commit()

    def _recover_legacy_execution_ids(self) -> None:
        candidates = self._db.execute(
            """
            SELECT run_id FROM runs
            WHERE mission_execution_id = run_id
              AND snapshot_json NOT LIKE '%"mission_execution_id"%'
            """
        ).fetchall()
        for candidate in candidates:
            run_id = str(candidate["run_id"])
            events = self._db.execute(
                """
                SELECT event_json FROM events
                WHERE run_id = ? AND kind = ?
                ORDER BY sequence
                """,
                (run_id, EvidenceKind.COMMAND.value),
            ).fetchall()
            for event in events:
                try:
                    raw = json.loads(str(event["event_json"]))
                    execution_id = raw["payload"]["command"]["fleet"]["fleet_run_id"]
                except (KeyError, TypeError, json.JSONDecodeError):
                    continue
                if isinstance(execution_id, str) and execution_id:
                    self._db.execute(
                        "UPDATE runs SET mission_execution_id = ? WHERE run_id = ?",
                        (execution_id, run_id),
                    )
                    break

    def begin_run(self, run: MissionRunSnapshot) -> None:
        snapshot_json = run.model_dump_json()
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT OR IGNORE INTO runs (
                    run_id, mission_execution_id, mission_id, mission_name,
                    mission_version, vehicle_id, mode,
                    configuration_hash, started_at_monotonic_s, started_at_utc, snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.mission_run_id,
                    run.mission_execution_id or run.mission_run_id,
                    run.mission_id,
                    run.mission_name or run.mission_id,
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
                """
                UPDATE runs
                SET status = ?, result_json = ?, completed_at_utc = ?,
                    mission_execution_id = COALESCE(?, mission_execution_id),
                    mission_name = COALESCE(?, mission_name)
                WHERE run_id = ?
                """,
                (
                    result.status.value,
                    result.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                    result.mission_execution_id,
                    result.mission_name,
                    result.mission_run_id,
                ),
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
        with self._lock:
            row = self._db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def list_runs(self, *, vehicle_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            if vehicle_id is None:
                rows = self._db.execute(
                    """
                    SELECT runs.*, (
                        SELECT COUNT(*) FROM events
                        WHERE events.run_id = runs.run_id AND events.kind = ?
                    ) AS telemetry_row_count
                    FROM runs ORDER BY started_at_utc DESC LIMIT ?
                    """,
                    (EvidenceKind.TELEMETRY.value, limit),
                ).fetchall()
            else:
                rows = self._db.execute(
                    """
                    SELECT runs.*, (
                        SELECT COUNT(*) FROM events
                        WHERE events.run_id = runs.run_id AND events.kind = ?
                    ) AS telemetry_row_count
                    FROM runs WHERE vehicle_id = ? ORDER BY started_at_utc DESC LIMIT ?
                    """,
                    (EvidenceKind.TELEMETRY.value, vehicle_id, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def update_mission_names(self, names: dict[str, str]) -> None:
        with self._lock, self._db:
            for mission_id, mission_name in names.items():
                self._db.execute(
                    """
                    UPDATE runs SET mission_name = ?
                    WHERE mission_id = ? AND (mission_name IS NULL OR mission_name = mission_id)
                    """,
                    (mission_name, mission_id),
                )

    def query_events(
        self,
        *,
        run_id: str | None = None,
        vehicle_id: str | None = None,
        kind: EvidenceKind | None = None,
        sensor: str | None = None,
        start_s: float | None = None,
        end_s: float | None = None,
        limit: int | None = 10_000,
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
        statement = f"SELECT event_json, sha256 FROM events{where} ORDER BY sequence"
        if limit is not None:
            parameters.append(limit)
            statement += " LIMIT ?"
        with self._lock:
            rows = self._db.execute(statement, parameters).fetchall()
        events = [self._decode_event(row) for row in rows]
        if sensor is not None:
            events = [event for event in events if self._contains_sensor(event, sensor)]
        return events

    def integrity_check(self) -> None:
        with self._lock:
            result = self._db.execute("PRAGMA integrity_check").fetchone()
            rows = self._db.execute("SELECT event_json, sha256 FROM events").fetchall()
        if result is None or result[0] != "ok":
            raise EvidenceCorruptionError(f"SQLite integrity check failed: {result}")
        for row in rows:
            self._decode_event(row)

    def export_bundle(self, run_id: str, destination: Path) -> Path:
        run = self.get_run(run_id)
        events = self.query_events(run_id=run_id, limit=None)
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

    def export_telemetry_csv(self, run_id: str) -> RunTelemetryCsvArtifact:
        run = self.get_run(run_id)
        if run["status"] is None:
            raise IncompleteRunError(run_id)
        events = self.query_events(run_id=run_id, kind=EvidenceKind.TELEMETRY, limit=None)
        return serialize_run_telemetry_csv(run, events)

    def export_mission_telemetry_csv(self, mission_execution_id: str) -> RunTelemetryCsvArtifact:
        runs = self._mission_rows(mission_execution_id)
        if not runs:
            raise KeyError(mission_execution_id)
        if any(run["status"] is None for run in runs):
            raise IncompleteRunError(mission_execution_id)
        events: list[EvidenceEvent] = []
        for run in runs:
            events.extend(
                self.query_events(
                    run_id=str(run["run_id"]),
                    kind=EvidenceKind.TELEMETRY,
                    limit=None,
                )
            )
        return serialize_mission_telemetry_csv(runs, events)

    def upsert_execution_context(
        self,
        mission_execution_id: str,
        context: dict[str, Any],
    ) -> str:
        """Persist the accepted and terminal execution context without wall-clock noise."""
        normalized = {**context, "mission_execution_id": mission_execution_id}
        content = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        checksum = hashlib.sha256(content.encode()).hexdigest()
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT INTO execution_contexts (mission_execution_id, context_json, sha256)
                VALUES (?, ?, ?)
                ON CONFLICT(mission_execution_id) DO UPDATE SET
                    context_json = excluded.context_json,
                    sha256 = excluded.sha256
                """,
                (mission_execution_id, content, checksum),
            )
        return checksum

    def add_execution_annotation(
        self,
        mission_execution_id: str,
        *,
        annotation_id: str,
        author_id: str,
        note: str,
        created_at_utc: datetime | None = None,
    ) -> dict[str, str]:
        if not note.strip():
            raise ValueError("execution annotation cannot be blank")
        if len(note) > 2_000:
            raise ValueError("execution annotation exceeds 2000 characters")
        if not self._mission_rows(mission_execution_id):
            raise KeyError(mission_execution_id)
        item = {
            "annotation_id": annotation_id,
            "author_id": author_id,
            "note": note.strip(),
            "created_at_utc": (created_at_utc or datetime.now(UTC)).isoformat(),
        }
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT INTO execution_annotations (
                    annotation_id, mission_execution_id, author_id, note, created_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    item["annotation_id"],
                    mission_execution_id,
                    item["author_id"],
                    item["note"],
                    item["created_at_utc"],
                ),
            )
        self._materialize_mission(mission_execution_id)
        return item

    def evaluate_mission_execution(
        self,
        mission_execution_id: str,
    ) -> MissionExecutionEvaluation:
        runs = self._mission_rows(mission_execution_id)
        if not runs:
            raise KeyError(mission_execution_id)
        events = self._mission_events(runs)
        return evaluate_mission_execution(
            mission_execution_id=mission_execution_id,
            runs=runs,
            events=events,
            context=self._execution_context(mission_execution_id),
            annotations=self._execution_annotations(mission_execution_id),
        )

    def get_persisted_execution_evaluation(
        self,
        mission_execution_id: str,
    ) -> dict[str, Any]:
        return self._get_persisted_execution_json(mission_execution_id, "evaluation")

    def get_persisted_execution_bundle(
        self,
        mission_execution_id: str,
    ) -> dict[str, Any]:
        return self._get_persisted_execution_json(mission_execution_id, "bundle")

    def materialize_run_files_for_run(self, run_id: str) -> dict[str, Any]:
        """Atomically persist every terminal member of the run's mission execution."""
        run = self.get_run(run_id)
        if run["status"] is None:
            raise IncompleteRunError(run_id)
        execution_id = str(run.get("mission_execution_id") or run_id)
        return self._materialize_mission(execution_id)

    def materialize_mission_execution(self, mission_execution_id: str) -> dict[str, Any]:
        """Refresh the complete grouped evidence, evaluator report, and manifest."""
        return self._materialize_mission(mission_execution_id)

    def backfill_run_files(self) -> int:
        """Persist retained completed missions that predate the run-file archive."""
        with self._artifact_lock:
            archived = {
                str(manifest["mission_execution_id"]): str(manifest.get("completed_at_utc") or "")
                for manifest in self._read_run_file_manifests_locked()
                if self._run_file_manifest_is_complete(manifest)
            }
        with self._lock:
            groups = self._db.execute(
                """
                SELECT mission_execution_id,
                       MIN(started_at_utc) AS mission_started_at_utc,
                       MAX(completed_at_utc) AS mission_completed_at_utc
                FROM runs
                GROUP BY mission_execution_id
                HAVING SUM(CASE WHEN status IS NULL THEN 1 ELSE 0 END) = 0
                ORDER BY mission_started_at_utc DESC
                LIMIT ?
                """,
                (self.keep_latest_missions,),
            ).fetchall()
        missing = [
            row
            for row in reversed(groups)
            if archived.get(str(row["mission_execution_id"]))
            != str(row["mission_completed_at_utc"] or "")
        ]
        for row in missing:
            self._materialize_mission(str(row["mission_execution_id"]))
        return len(missing)

    def list_run_file_missions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._artifact_lock:
            manifests = self._read_run_file_manifests_locked()
        return manifests[:limit]

    def delete_run_file_mission(self, mission_execution_id: str) -> dict[str, Any]:
        """Permanently remove a completed mission's evidence and archive folder."""
        with self._artifact_lock:
            archive_folder: Path | None = None
            root = self.run_files_directory.resolve()
            for manifest in self._read_run_file_manifests_locked():
                if manifest.get("mission_execution_id") != mission_execution_id:
                    continue
                folder = Path(str(manifest["_folder"])).resolve()
                if folder.parent != root:
                    raise RuntimeError(
                        f"refusing to delete run-file path outside archive: {folder}"
                    )
                archive_folder = folder
                break

            with self._lock:
                rows = self._db.execute(
                    """
                    SELECT run_id, status
                    FROM runs
                    WHERE mission_execution_id = ?
                    ORDER BY run_id
                    """,
                    (mission_execution_id,),
                ).fetchall()
                if not rows:
                    raise KeyError(mission_execution_id)
                active_run_ids = [str(row["run_id"]) for row in rows if row["status"] is None]
                if active_run_ids:
                    raise IncompleteRunError(mission_execution_id)

                run_ids = [str(row["run_id"]) for row in rows]
                with self._db:
                    for run_id in run_ids:
                        self._db.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
                    self._db.execute(
                        "DELETE FROM execution_contexts WHERE mission_execution_id = ?",
                        (mission_execution_id,),
                    )
                    self._db.execute(
                        "DELETE FROM execution_annotations WHERE mission_execution_id = ?",
                        (mission_execution_id,),
                    )
                    self._db.execute(
                        "DELETE FROM runs WHERE mission_execution_id = ?",
                        (mission_execution_id,),
                    )

            if archive_folder is not None:
                shutil.rmtree(archive_folder)

        return {"mission_execution_id": mission_execution_id, "deleted_run_ids": run_ids}

    def get_persisted_run_file(
        self,
        mission_execution_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        run = self.get_run(run_id)
        execution_id = str(run.get("mission_execution_id") or run_id)
        if execution_id != mission_execution_id:
            raise KeyError((mission_execution_id, run_id))
        if run["status"] is None:
            raise IncompleteRunError(run_id)
        return self.get_persisted_mission_file(mission_execution_id)

    def get_persisted_mission_file(
        self,
        mission_execution_id: str,
    ) -> dict[str, Any]:
        with self._artifact_lock:
            for manifest in self._read_run_file_manifests_locked():
                if manifest.get("mission_execution_id") != mission_execution_id:
                    continue
                folder = Path(str(manifest["_folder"]))
                item = manifest.get("artifact")
                if not isinstance(item, dict):
                    raise KeyError(mission_execution_id)
                filename = str(item.get("filename") or "")
                if not filename or Path(filename).name != filename:
                    raise KeyError(mission_execution_id)
                path = (folder / filename).resolve()
                if path.parent != folder.resolve() or not path.is_file():
                    raise KeyError(mission_execution_id)
                return {
                    **item,
                    "mission_execution_id": mission_execution_id,
                    "path": path,
                }
        raise KeyError(mission_execution_id)

    def get_persisted_run_file_for_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] is None:
            raise IncompleteRunError(run_id)
        execution_id = str(run.get("mission_execution_id") or run_id)
        try:
            return self.get_persisted_mission_file(execution_id)
        except KeyError:
            self.materialize_run_files_for_run(run_id)
            return self.get_persisted_mission_file(execution_id)

    def prune_completed_missions(self, *, keep_latest: int | None = None) -> int:
        keep = self.keep_latest_missions if keep_latest is None else keep_latest
        if keep < 1:
            raise ValueError("keep_latest must be at least 1")
        with self._lock, self._db:
            groups = self._db.execute(
                """
                SELECT mission_execution_id, MIN(started_at_utc) AS mission_started_at_utc
                FROM runs
                GROUP BY mission_execution_id
                HAVING SUM(CASE WHEN status IS NULL THEN 1 ELSE 0 END) = 0
                ORDER BY mission_started_at_utc DESC
                """
            ).fetchall()
            selected = [str(row["mission_execution_id"]) for row in groups[keep:]]
            for execution_id in selected:
                run_ids = self._db.execute(
                    "SELECT run_id FROM runs WHERE mission_execution_id = ?",
                    (execution_id,),
                ).fetchall()
                for row in run_ids:
                    self._db.execute("DELETE FROM events WHERE run_id = ?", (row["run_id"],))
                self._db.execute(
                    "DELETE FROM runs WHERE mission_execution_id = ?",
                    (execution_id,),
                )
                self._db.execute(
                    "DELETE FROM execution_contexts WHERE mission_execution_id = ?",
                    (execution_id,),
                )
                self._db.execute(
                    "DELETE FROM execution_annotations WHERE mission_execution_id = ?",
                    (execution_id,),
                )
        return len(selected)

    def _materialize_mission(self, mission_execution_id: str) -> dict[str, Any]:
        with self._artifact_lock:
            rows = self._mission_rows(mission_execution_id)
            if not rows:
                raise KeyError(mission_execution_id)
            folder = self._mission_folder_locked(mission_execution_id, rows)
            folder.mkdir(parents=True, exist_ok=True)
            previous = self._read_manifest(folder)
            statuses = {str(row["status"] or "INCOMPLETE") for row in rows}
            telemetry_row_count = sum(int(row.get("telemetry_row_count", 0)) for row in rows)
            artifact_entry: dict[str, Any] = {
                "run_ids": [str(row["run_id"]) for row in rows],
                "vehicle_ids": sorted({str(row["vehicle_id"]) for row in rows}),
                "filename": None,
                "media_type": "text/csv",
                "schema_version": "run-telemetry-v1",
                "size_bytes": None,
                "telemetry_row_count": telemetry_row_count,
                "sha256": None,
            }
            destination: Path | None = None
            if "INCOMPLETE" not in statuses:
                generated = self.export_mission_telemetry_csv(mission_execution_id)
                destination = folder / generated.filename
                old = previous.get("artifact")
                reusable = (
                    isinstance(old, dict)
                    and old.get("filename") == generated.filename
                    and old.get("telemetry_row_count") == generated.row_count
                    and destination.is_file()
                    and destination.stat().st_size == old.get("size_bytes")
                    and old.get("sha256") == generated.sha256
                )
                if reusable:
                    assert isinstance(old, dict)
                    artifact_entry.update(
                        filename=generated.filename,
                        size_bytes=int(old["size_bytes"]),
                        sha256=str(old["sha256"]),
                        telemetry_row_count=generated.row_count,
                    )
                else:
                    self._atomic_write(destination, generated.content)
                    artifact_entry.update(
                        filename=generated.filename,
                        size_bytes=len(generated.content),
                        sha256=generated.sha256,
                        telemetry_row_count=generated.row_count,
                    )
            events = self._mission_events(rows)
            context = self._execution_context(mission_execution_id)
            annotations = self._execution_annotations(mission_execution_id)
            evaluation = evaluate_mission_execution(
                mission_execution_id=mission_execution_id,
                runs=rows,
                events=events,
                context=context,
                annotations=annotations,
            )
            bundle = build_execution_bundle(
                mission_execution_id=mission_execution_id,
                runs=rows,
                events=events,
                context=context,
                annotations=annotations,
                evaluation=evaluation,
            )
            mission_segment = self._safe_component(
                str(rows[0].get("mission_name") or rows[0]["mission_id"]),
                maximum=64,
            )
            execution_segment = self._safe_component(mission_execution_id, maximum=96)
            prefix = f"{mission_segment}_{execution_segment}"
            evaluation_bytes = (
                json.dumps(
                    evaluation.model_dump(mode="json"),
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode()
            bundle_bytes = (json.dumps(bundle, indent=2, sort_keys=True) + "\n").encode()
            evaluation_filename = f"{prefix}_evaluation-v1.json"
            bundle_filename = f"{prefix}_execution-bundle-v1.json"
            self._atomic_write(folder / evaluation_filename, evaluation_bytes)
            self._atomic_write(folder / bundle_filename, bundle_bytes)
            evaluation_entry = {
                "filename": evaluation_filename,
                "media_type": "application/json",
                "schema_version": MISSION_EXECUTION_EVALUATION_CONTRACT,
                "size_bytes": len(evaluation_bytes),
                "sha256": hashlib.sha256(evaluation_bytes).hexdigest(),
                "report_sha256": evaluation.report_sha256,
                "status": evaluation.status.value,
                "evidence_complete": evaluation.evidence.complete,
            }
            bundle_entry = {
                "filename": bundle_filename,
                "media_type": "application/json",
                "schema_version": MISSION_EXECUTION_BUNDLE_CONTRACT,
                "size_bytes": len(bundle_bytes),
                "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
                "bundle_sha256": bundle["bundle_sha256"],
                "event_count": len(events),
            }
            manifest = {
                "schema_version": 2,
                "mission_execution_id": mission_execution_id,
                "mission_id": str(rows[0]["mission_id"]),
                "mission_name": str(rows[0].get("mission_name") or rows[0]["mission_id"]),
                "started_at_utc": min(str(row["started_at_utc"]) for row in rows),
                "completed_at_utc": (
                    max(str(row["completed_at_utc"]) for row in rows)
                    if all(row.get("completed_at_utc") for row in rows)
                    else None
                ),
                "status": self._mission_status(statuses),
                "vehicle_ids": sorted({str(row["vehicle_id"]) for row in rows}),
                "telemetry_row_count": telemetry_row_count,
                "artifact": artifact_entry,
                "evaluation": evaluation_entry,
                "bundle": bundle_entry,
            }
            self._atomic_write(
                folder / "manifest.json",
                (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
            )
            self._remove_superseded_csvs_locked(folder, keep=destination)
            if manifest["status"] != "INCOMPLETE":
                self._prune_run_file_folders_locked()
                self.prune_completed_missions()
            return manifest

    def _mission_rows(self, mission_execution_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT runs.*, (
                    SELECT COUNT(*) FROM events
                    WHERE events.run_id = runs.run_id AND events.kind = ?
                ) AS telemetry_row_count
                FROM runs
                WHERE mission_execution_id = ?
                ORDER BY started_at_utc, vehicle_id, run_id
                """,
                (EvidenceKind.TELEMETRY.value, mission_execution_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _mission_events(self, rows: list[dict[str, Any]]) -> list[EvidenceEvent]:
        events: list[EvidenceEvent] = []
        for row in rows:
            events.extend(self.query_events(run_id=str(row["run_id"]), limit=None))
        return events

    def _execution_context(self, mission_execution_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT context_json FROM execution_contexts WHERE mission_execution_id = ?",
                (mission_execution_id,),
            ).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(str(row["context_json"]))
        except json.JSONDecodeError as error:
            raise EvidenceCorruptionError("execution context is not valid JSON") from error
        if not isinstance(value, dict):
            raise EvidenceCorruptionError("execution context must be a JSON object")
        return value

    def _execution_annotations(self, mission_execution_id: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT annotation_id, author_id, note, created_at_utc
                FROM execution_annotations
                WHERE mission_execution_id = ?
                ORDER BY created_at_utc, annotation_id
                """,
                (mission_execution_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_persisted_execution_json(
        self,
        mission_execution_id: str,
        kind: str,
    ) -> dict[str, Any]:
        with self._artifact_lock:
            for manifest in self._read_run_file_manifests_locked():
                if manifest.get("mission_execution_id") != mission_execution_id:
                    continue
                item = manifest.get(kind)
                if not isinstance(item, dict):
                    raise KeyError(mission_execution_id)
                filename = str(item.get("filename") or "")
                folder = Path(str(manifest["_folder"])).resolve()
                path = (folder / filename).resolve()
                if not filename or Path(filename).name != filename or path.parent != folder:
                    raise KeyError(mission_execution_id)
                if not path.is_file():
                    raise KeyError(mission_execution_id)
                return {
                    **item,
                    "mission_execution_id": mission_execution_id,
                    "path": path,
                }
        raise KeyError(mission_execution_id)

    def _mission_folder_locked(
        self,
        mission_execution_id: str,
        rows: list[dict[str, Any]],
    ) -> Path:
        started = self._utc_token(str(rows[0]["started_at_utc"]))
        mission = self._safe_component(
            str(rows[0].get("mission_name") or rows[0]["mission_id"]), maximum=64
        )
        execution = self._safe_component(mission_execution_id, maximum=96)
        expected = self.run_files_directory / f"{started}_{mission}_{execution}"
        for manifest in self._read_run_file_manifests_locked():
            if manifest.get("mission_execution_id") == mission_execution_id:
                current = Path(str(manifest["_folder"]))
                if current != expected and not expected.exists():
                    os.replace(current, expected)
                    return expected
                return current
        return expected

    def _read_run_file_manifests_locked(self) -> list[dict[str, Any]]:
        if not self.run_files_directory.is_dir():
            return []
        manifests: list[dict[str, Any]] = []
        for folder in self.run_files_directory.iterdir():
            if not folder.is_dir():
                continue
            manifest = self._read_manifest(folder)
            if not manifest or not isinstance(manifest.get("mission_execution_id"), str):
                continue
            manifest["_folder"] = str(folder.resolve())
            manifests.append(manifest)
        return sorted(
            manifests,
            key=lambda item: (
                str(item.get("started_at_utc", "")),
                str(item["mission_execution_id"]),
            ),
            reverse=True,
        )

    @staticmethod
    def _run_file_manifest_is_complete(manifest: dict[str, Any]) -> bool:
        """Check archive completeness without decoding or hashing its large payloads."""
        if manifest.get("schema_version") != 2 or manifest.get("status") == "INCOMPLETE":
            return False
        folder_value = manifest.get("_folder")
        if not isinstance(folder_value, str):
            return False
        folder = Path(folder_value).resolve()
        for kind in ("artifact", "evaluation", "bundle"):
            item = manifest.get(kind)
            if not isinstance(item, dict):
                return False
            filename = item.get("filename")
            size_bytes = item.get("size_bytes")
            if (
                not isinstance(filename, str)
                or not filename
                or Path(filename).name != filename
                or not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or size_bytes < 0
            ):
                return False
            path = (folder / filename).resolve()
            try:
                if path.parent != folder or path.stat().st_size != size_bytes:
                    return False
            except OSError:
                return False
        return True

    @staticmethod
    def _read_manifest(folder: Path) -> dict[str, Any]:
        try:
            value = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return value if isinstance(value, dict) else {}

    def _prune_run_file_folders_locked(self) -> int:
        manifests = self._read_run_file_manifests_locked()
        with self._lock:
            retained_execution_ids = {
                str(row["mission_execution_id"])
                for row in self._db.execute(
                    "SELECT DISTINCT mission_execution_id FROM runs"
                ).fetchall()
            }
        orphaned = [
            item
            for item in manifests
            if str(item["mission_execution_id"]) not in retained_execution_ids
        ]
        completed = [
            item for item in manifests if item not in orphaned if item.get("status") != "INCOMPLETE"
        ]
        selected = orphaned + completed[self.keep_latest_missions :]
        root = self.run_files_directory.resolve()
        for manifest in selected:
            folder = Path(str(manifest["_folder"])).resolve()
            if folder.parent != root:
                raise RuntimeError(f"refusing to prune run-file path outside archive: {folder}")
            shutil.rmtree(folder)
        return len(selected)

    @staticmethod
    def _remove_superseded_csvs_locked(folder: Path, *, keep: Path | None) -> None:
        resolved_folder = folder.resolve()
        resolved_keep = keep.resolve() if keep is not None else None
        for candidate in folder.iterdir():
            resolved = candidate.resolve()
            if (
                resolved.parent == resolved_folder
                and resolved != resolved_keep
                and candidate.is_file()
                and candidate.name.endswith("_telemetry-v1.csv")
            ):
                candidate.unlink()

    @staticmethod
    def _atomic_write(destination: Path, content: bytes) -> None:
        temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _mission_status(statuses: set[str]) -> str:
        if "INCOMPLETE" in statuses:
            return "INCOMPLETE"
        if "FAILED" in statuses:
            return "FAILED"
        if "ABORTED" in statuses:
            return "ABORTED"
        return "SUCCEEDED"

    @staticmethod
    def _safe_component(value: str, *, maximum: int) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
        return (cleaned or "unnamed")[:maximum]

    @staticmethod
    def _utc_token(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            parsed = datetime.now(UTC)
        return parsed.strftime("%Y%m%dT%H%M%SZ")

    def prune_completed(self, *, before_utc: datetime, keep_latest: int = 10) -> int:
        with self._lock, self._db:
            protected = {
                row[0]
                for row in self._db.execute(
                    "SELECT run_id FROM runs ORDER BY started_at_utc DESC LIMIT ?",
                    (keep_latest,),
                )
            }
            candidates = self._db.execute(
                "SELECT run_id FROM runs WHERE status IS NOT NULL AND started_at_utc < ?",
                (before_utc.isoformat(),),
            ).fetchall()
            selected = [row[0] for row in candidates if row[0] not in protected]
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
