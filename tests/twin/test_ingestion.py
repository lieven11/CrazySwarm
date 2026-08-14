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


def _coordinator(tmp_path: Path) -> tuple[TwinCoordinator, str]:
    coordinator = TwinCoordinator(tmp_path / "twin")
    record = coordinator.create_session(
        TwinSessionConfig(
            observed_vehicle_id="observed",
            simulated_vehicle_id="predicted",
            mission_id="straight",
            mission_version="1",
            observed_initial_state=TwinInitialState(
                source_class=TwinSourceClass.CONFIGURED,
                source_id="sim",
                frame=CoordinateFrame.WORLD,
            ),
            simulated_initial_state=TwinInitialState(
                source_class=TwinSourceClass.SIMULATED_MODEL,
                source_id="model",
                frame=CoordinateFrame.WORLD,
            ),
        )
    )
    return coordinator, record.session_id


def _sample(session_id: str, *, sequence: int, time_s: float) -> TwinStreamSample:
    return TwinStreamSample.create(
        sample_id=f"sample-{sequence}",
        session_id=session_id,
        side=TwinStreamSide.OBSERVED,
        vehicle_id="observed",
        channel_id="pose.position",
        sequence=sequence,
        source_timestamp_s=time_s,
        received_timestamp_s=time_s + 0.01,
        availability=TwinAvailability.AVAILABLE,
        quality=TwinQuality.GOOD,
        unit="m",
        frame="world",
        value=Vector3(x=time_s),
        raw_payload_sha256=canonical_sha256([sequence, time_s]),
    )


def test_batch_is_atomic_for_out_of_order_and_bad_frame(tmp_path: Path) -> None:
    coordinator, session_id = _coordinator(tmp_path)
    good = _sample(session_id, sequence=1, time_s=1.0)
    bad = _sample(session_id, sequence=2, time_s=0.9)
    with pytest.raises(ValueError, match="out of order"):
        coordinator.ingest(TwinIngestionBatch(session_id=session_id, samples=(good, bad)))
    assert coordinator.timeline(session_id).samples == ()
    wrong = _sample(session_id, sequence=1, time_s=1.0)
    payload = wrong.model_dump(mode="python", exclude={"sample_sha256"})
    payload["frame"] = "body"
    wrong_frame = TwinStreamSample(**payload, sample_sha256=canonical_sha256(payload))
    with pytest.raises(ValueError, match="unit/frame"):
        coordinator.ingest(
            TwinIngestionBatch(session_id=session_id, samples=(wrong_frame,))
        )
    assert coordinator.timeline(session_id).samples == ()


def test_500_hz_and_512_sample_limits_are_enforced(tmp_path: Path) -> None:
    coordinator, session_id = _coordinator(tmp_path)
    first = _sample(session_id, sequence=1, time_s=1.0)
    coordinator.ingest(TwinIngestionBatch(session_id=session_id, samples=(first,)))
    too_fast = _sample(session_id, sequence=2, time_s=1.001)
    with pytest.raises(ValueError, match="500 Hz"):
        coordinator.ingest(
            TwinIngestionBatch(session_id=session_id, samples=(too_fast,))
        )
