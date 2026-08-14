from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.models import (
    TwinSessionConfig,
    TwinSessionRecord,
    TwinStreamSample,
)


class DurableTwinStore:
    """Append-only, restart-safe local twin journal with atomic batch records."""

    def __init__(
        self,
        root: Path,
        *,
        maximum_records: int = 1_000_000,
        maximum_bytes: int = 4 * 1024 * 1024 * 1024,
    ) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.root / "twin-journal-v1.jsonl"
        self.maximum_records = maximum_records
        self.maximum_bytes = maximum_bytes
        self._lock = threading.RLock()
        self._records: dict[str, TwinSessionRecord] = {}
        self._configs: dict[str, TwinSessionConfig] = {}
        self._samples: dict[str, list[TwinStreamSample]] = {}
        self._samples_by_id: dict[tuple[str, str], TwinStreamSample] = {}
        self._calibration_candidates: dict[str, dict[str, Any]] = {}
        self._calibration_reports: dict[str, dict[str, Any]] = {}
        self._active_calibration_id: str | None = None
        self._curriculum_results: list[dict[str, Any]] = []
        self._sample_bytes_by_session: dict[str, int] = {}
        self._record_count = 0
        self._recover()

    def register_session(
        self,
        record: TwinSessionRecord,
        config: TwinSessionConfig,
    ) -> None:
        with self._lock:
            if record.session_id in self._records:
                raise ValueError("twin session already exists")
            self._append(
                "SESSION_CREATED",
                record.session_id,
                {
                    "record": record.model_dump(mode="json"),
                    "config": config.model_dump(mode="json"),
                },
            )
            self._records[record.session_id] = record
            self._configs[record.session_id] = config
            self._samples[record.session_id] = []

    def update_session(self, record: TwinSessionRecord) -> None:
        with self._lock:
            if record.session_id not in self._records:
                raise KeyError("unknown twin session")
            self._append("SESSION_UPDATED", record.session_id, record.model_dump(mode="json"))
            self._records[record.session_id] = record

    def append_samples(
        self,
        session_id: str,
        samples: tuple[TwinStreamSample, ...],
    ) -> tuple[int, int]:
        with self._lock:
            if session_id not in self._records:
                raise KeyError("unknown twin session")
            accepted: list[TwinStreamSample] = []
            accepted_by_id: dict[str, TwinStreamSample] = {}
            idempotent = 0
            for sample in samples:
                if sample.session_id != session_id:
                    raise ValueError("sample belongs to another twin session")
                existing = self._samples_by_id.get((session_id, sample.sample_id))
                pending = accepted_by_id.get(sample.sample_id)
                if pending is not None:
                    if pending.sample_sha256 != sample.sample_sha256:
                        raise ValueError("duplicate twin sample ID has different content")
                    idempotent += 1
                    continue
                if existing is not None:
                    if existing.sample_sha256 != sample.sample_sha256:
                        raise ValueError("duplicate twin sample ID has different content")
                    idempotent += 1
                    continue
                accepted.append(sample)
                accepted_by_id[sample.sample_id] = sample
            if accepted:
                accepted_bytes = sum(_sample_storage_bytes(item) for item in accepted)
                retained_count = len(self._samples[session_id])
                retained_bytes = self._sample_bytes_by_session.get(session_id, 0)
                if retained_count + len(accepted) > self.maximum_records:
                    raise ValueError(
                        "twin retention record limit reached; no record was dropped"
                    )
                if retained_bytes + accepted_bytes > self.maximum_bytes:
                    raise ValueError(
                        "twin retention byte limit reached; no record was dropped"
                    )
                self._append(
                    "SAMPLE_BATCH",
                    session_id,
                    [item.model_dump(mode="json") for item in accepted],
                )
                for sample in accepted:
                    self._samples[session_id].append(sample)
                    self._samples_by_id[(session_id, sample.sample_id)] = sample
                self._sample_bytes_by_session[session_id] = (
                    retained_bytes + accepted_bytes
                )
            return len(accepted), idempotent

    def sessions(self) -> tuple[TwinSessionRecord, ...]:
        with self._lock:
            return tuple(sorted(self._records.values(), key=lambda item: item.session_id))

    def record(self, session_id: str) -> TwinSessionRecord:
        with self._lock:
            return self._records[session_id]

    def config(self, session_id: str) -> TwinSessionConfig:
        with self._lock:
            return self._configs[session_id]

    def samples(self, session_id: str) -> tuple[TwinStreamSample, ...]:
        with self._lock:
            return tuple(self._samples[session_id])

    def append_calibration_candidate(
        self,
        calibration_id: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock:
            if calibration_id in self._calibration_candidates:
                raise ValueError("calibration candidate already exists")
            self._append("CALIBRATION_CANDIDATE", calibration_id, payload)
            self._calibration_candidates[calibration_id] = payload

    def append_calibration_report(
        self,
        calibration_id: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock:
            if calibration_id not in self._calibration_candidates:
                raise KeyError("unknown calibration candidate")
            if calibration_id in self._calibration_reports:
                raise ValueError("calibration candidate already has a promotion report")
            self._append("CALIBRATION_REPORT", calibration_id, payload)
            self._calibration_reports[calibration_id] = payload

    def calibration_candidates(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(
                self._calibration_candidates[key]
                for key in sorted(self._calibration_candidates)
            )

    def calibration_reports(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(
                self._calibration_reports[key]
                for key in sorted(self._calibration_reports)
            )

    def activate_calibration(self, calibration_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            report = self._calibration_reports.get(calibration_id)
            if report is None or report.get("disposition") != "PROMOTED":
                raise ValueError("only a retained promoted calibration can become active")
            if payload.get("predecessor_calibration_id") != self._active_calibration_id:
                raise ValueError("calibration activation predecessor is not current")
            self._append("CALIBRATION_ACTIVATED", calibration_id, payload)
            self._active_calibration_id = calibration_id

    def active_calibration_id(self) -> str | None:
        with self._lock:
            return self._active_calibration_id

    def append_curriculum_result(self, stage_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            if any(str(item.get("stage_id")) == stage_id for item in self._curriculum_results):
                raise ValueError("twin curriculum stage already has a retained result")
            self._append("CURRICULUM_RESULT", stage_id, payload)
            self._curriculum_results.append(payload)

    def curriculum_results(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(self._curriculum_results)

    def _append(self, kind: str, session_id: str, payload: Any) -> None:
        envelope = {
            "kind": kind,
            "session_id": session_id,
            "payload": payload,
        }
        envelope["record_sha256"] = canonical_sha256(envelope)
        encoded = (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(
            self.journal_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._record_count += 1

    def _recover(self) -> None:
        if not self.journal_path.exists():
            return
        with self.journal_path.open("rb") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if not raw_line.endswith(b"\n"):
                    raise ValueError(f"truncated twin journal record at line {line_number}")
                envelope = json.loads(raw_line)
                expected = envelope.pop("record_sha256", None)
                if expected != canonical_sha256(envelope):
                    raise ValueError(f"corrupt twin journal record at line {line_number}")
                self._apply_recovered(envelope)
                self._record_count += 1

    def _apply_recovered(self, envelope: dict[str, Any]) -> None:
        kind = str(envelope["kind"])
        session_id = str(envelope["session_id"])
        payload = envelope["payload"]
        if kind == "SESSION_CREATED":
            self._records[session_id] = TwinSessionRecord.model_validate(payload["record"])
            self._configs[session_id] = TwinSessionConfig.model_validate(payload["config"])
            self._samples.setdefault(session_id, [])
        elif kind == "SESSION_UPDATED":
            self._records[session_id] = TwinSessionRecord.model_validate(payload)
        elif kind == "SAMPLE_BATCH":
            for value in payload:
                sample = TwinStreamSample.model_validate(value)
                key = (session_id, sample.sample_id)
                existing = self._samples_by_id.get(key)
                if existing is not None and existing.sample_sha256 != sample.sample_sha256:
                    raise ValueError("twin journal contains conflicting sample identity")
                if existing is None:
                    self._samples.setdefault(session_id, []).append(sample)
                    self._samples_by_id[key] = sample
                    self._sample_bytes_by_session[session_id] = (
                        self._sample_bytes_by_session.get(session_id, 0)
                        + _sample_storage_bytes(sample)
                    )
        elif kind == "CALIBRATION_CANDIDATE":
            if session_id in self._calibration_candidates:
                raise ValueError("twin journal contains duplicate calibration candidate")
            self._calibration_candidates[session_id] = payload
        elif kind == "CALIBRATION_REPORT":
            if session_id not in self._calibration_candidates:
                raise ValueError("twin journal promotion precedes its calibration candidate")
            if session_id in self._calibration_reports:
                raise ValueError("twin journal contains duplicate calibration report")
            self._calibration_reports[session_id] = payload
        elif kind == "CALIBRATION_ACTIVATED":
            report = self._calibration_reports.get(session_id)
            if report is None or report.get("disposition") != "PROMOTED":
                raise ValueError("twin journal activates a non-promoted calibration")
            if payload.get("predecessor_calibration_id") != self._active_calibration_id:
                raise ValueError("twin journal calibration lineage is inconsistent")
            self._active_calibration_id = session_id
        elif kind == "CURRICULUM_RESULT":
            if any(
                str(item.get("stage_id")) == session_id
                for item in self._curriculum_results
            ):
                raise ValueError("twin journal contains duplicate curriculum result")
            self._curriculum_results.append(payload)
        else:
            raise ValueError(f"unknown twin journal record kind: {kind}")


def _sample_storage_bytes(sample: TwinStreamSample) -> int:
    return len(
        json.dumps(
            sample.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
