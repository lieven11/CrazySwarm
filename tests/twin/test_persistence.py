from pathlib import Path

import pytest

from crazyswarm_app.domain.models import CoordinateFrame, Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.coordinator import TwinCoordinator
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinIngestionBatch,
    TwinInitialState,
    TwinQuality,
    TwinSessionConfig,
    TwinSourceClass,
    TwinStreamSample,
    TwinStreamSide,
)


def _config() -> TwinSessionConfig:
    return TwinSessionConfig(
        observed_vehicle_id="observed",
        simulated_vehicle_id="predicted",
        mission_id="straight-1d",
        mission_version="1.0.0",
        observed_initial_state=TwinInitialState(
            source_class=TwinSourceClass.CONFIGURED,
            source_id="fast-sim-truth",
            frame=CoordinateFrame.WORLD,
        ),
        simulated_initial_state=TwinInitialState(
            source_class=TwinSourceClass.SIMULATED_MODEL,
            source_id="model",
            frame=CoordinateFrame.WORLD,
        ),
        ground_truth_available=True,
    )


def _sample(
    session_id: str,
    *,
    sample_id: str = "sample-1",
    sequence: int = 1,
    time_s: float = 1.0,
):
    raw = {"position_m": [0.1, 0.0, 0.4], "sequence": sequence}
    return TwinStreamSample.create(
        sample_id=sample_id,
        session_id=session_id,
        side=TwinStreamSide.OBSERVED,
        vehicle_id="observed",
        channel_id="pose.position",
        sequence=sequence,
        source_timestamp_s=time_s,
        received_timestamp_s=time_s + 0.02,
        availability=TwinAvailability.AVAILABLE,
        quality=TwinQuality.GOOD,
        unit="m",
        frame="world",
        value=Vector3(x=0.1, z=0.4),
        raw_payload_sha256=canonical_sha256(raw),
    )


def test_twin_samples_survive_restart_and_duplicate_is_idempotent(tmp_path: Path) -> None:
    coordinator = TwinCoordinator(tmp_path / "twin")
    session = coordinator.create_session(_config())
    sample = _sample(session.session_id)
    first = coordinator.ingest(
        TwinIngestionBatch(session_id=session.session_id, samples=(sample,))
    )
    assert first.accepted_count == 1

    restarted = TwinCoordinator(tmp_path / "twin")
    assert restarted.session(session.session_id).session_id == session.session_id
    timeline = restarted.timeline(session.session_id)
    assert timeline.samples == (sample,)
    duplicate = restarted.ingest(
        TwinIngestionBatch(session_id=session.session_id, samples=(sample,))
    )
    assert duplicate.accepted_count == 0
    assert duplicate.idempotent_count == 1


def test_out_of_order_and_conflicting_duplicate_fail_atomically(tmp_path: Path) -> None:
    coordinator = TwinCoordinator(tmp_path / "twin")
    session = coordinator.create_session(_config())
    first = _sample(session.session_id)
    coordinator.ingest(TwinIngestionBatch(session_id=session.session_id, samples=(first,)))
    stale = _sample(session.session_id, sample_id="sample-2", sequence=2, time_s=0.9)
    with pytest.raises(ValueError, match="out of order"):
        coordinator.ingest(TwinIngestionBatch(session_id=session.session_id, samples=(stale,)))
    conflicting = first.model_dump(mode="python", exclude={"sample_sha256"})
    conflicting["value"] = Vector3(x=0.2, z=0.4)
    changed = TwinStreamSample(
        **conflicting,
        sample_sha256=canonical_sha256(conflicting),
    )
    with pytest.raises(ValueError, match="different content"):
        coordinator.ingest(TwinIngestionBatch(session_id=session.session_id, samples=(changed,)))
    assert len(coordinator.timeline(session.session_id).samples) == 1


def test_per_session_retention_overflow_rejects_without_dropping_prefix(
    tmp_path: Path,
) -> None:
    coordinator = TwinCoordinator(tmp_path / "twin")
    session = coordinator.create_session(_config())
    assert coordinator._store is not None
    coordinator._store.maximum_records = 1
    first = _sample(session.session_id)
    coordinator.ingest(
        TwinIngestionBatch(session_id=session.session_id, samples=(first,))
    )
    second = _sample(
        session.session_id,
        sample_id="sample-2",
        sequence=2,
        time_s=1.1,
    )
    with pytest.raises(ValueError, match="retention record limit"):
        coordinator.ingest(
            TwinIngestionBatch(session_id=session.session_id, samples=(second,))
        )
    assert coordinator.timeline(session.session_id).samples == (first,)
