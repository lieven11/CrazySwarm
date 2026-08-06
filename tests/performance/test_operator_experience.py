from __future__ import annotations

import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from crazyswarm_app.domain.models import CoordinateFrame, OperatingMode
from crazyswarm_app.observability.events import (
    EvidenceEvent,
    EvidenceKind,
    OperatorActionPayload,
)
from crazyswarm_app.observability.storage import EvidenceStore


def load_budgets() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(Path("config/qualification/operator-experience-v1.json").read_text()),
    )


def budget_values() -> dict[str, float | int]:
    return cast(dict[str, float | int], load_budgets()["budgets"])


def percentile_95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20, method="inclusive")[-1]


def operator_event(sequence: int) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=f"perf-event-{sequence}",
        sequence=sequence,
        kind=EvidenceKind.OPERATOR_ACTION,
        vehicle_id="sim01",
        run_id="perf-run",
        mode=OperatingMode.SIM,
        source="performance-test",
        source_timestamp_s=float(sequence),
        received_timestamp_s=float(sequence),
        recorded_at_utc=datetime.now(UTC),
        unit="event",
        frame=CoordinateFrame.WORLD,
        payload=OperatorActionPayload(
            client_id="performance-test",
            action="inspect",
            request_id=f"request-{sequence}",
        ),
    )


def test_evidence_commit_and_history_budgets(tmp_path: Path) -> None:
    budget = budget_values()
    store = EvidenceStore(tmp_path / "performance.sqlite3")
    elapsed_ms: list[float] = []
    for sequence in range(250):
        started = time.perf_counter()
        store.append_event(operator_event(sequence))
        elapsed_ms.append((time.perf_counter() - started) * 1000.0)

    assert percentile_95(elapsed_ms) < float(budget["evidence_commit_p95_ms"])
    assert len(store.query_events(limit=int(budget["evidence_query_max_events"]))) == 250
    store.integrity_check()
    store.close()


def test_operator_buffers_and_history_are_explicitly_bounded() -> None:
    budget = budget_values()
    control_source = Path("ui/app/components/ControlCenter.tsx").read_text()
    api_source = Path("src/crazyswarm_app/api/app.py").read_text()
    bus_source = Path("src/crazyswarm_app/observability/bus.py").read_text()

    assert f"slice(-{budget['operator_trace_max_points']})" in control_source
    assert f"buffer_size={budget['websocket_client_buffer_events']}" in api_source
    query_default = budget["default_run_history_rows"]
    query_maximum = budget["maximum_run_history_rows"]
    assert f"Query({query_default}, ge=1, le={query_maximum})" in api_source
    assert "if subscription.queue.full()" in bus_source


def test_performance_document_is_explicitly_software_only() -> None:
    report = load_budgets()
    assert report["hardware_qualified"] is False
    assert report["scope"] == "software-only local operator path"
    assert "not measured aircraft" in str(report["interpretation"])
