import pytest

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinQuality,
    TwinStreamSample,
    TwinStreamSide,
)
from crazyswarm_app.twin.replay import derive_twin_residuals


def _sample(side: TwinStreamSide, value: Vector3 | None, *, time_s: float = 1.0):
    availability = TwinAvailability.AVAILABLE if value is not None else TwinAvailability.MISSING
    return TwinStreamSample.create(
        sample_id=f"{side.value.lower()}-{time_s}",
        session_id="session",
        side=side,
        vehicle_id=side.value.lower(),
        channel_id="pose.position",
        sequence=1,
        source_timestamp_s=time_s,
        received_timestamp_s=time_s + 0.01,
        availability=availability,
        quality=TwinQuality.GOOD if value is not None else TwinQuality.UNQUALIFIED,
        unit="m",
        frame="world",
        value=value,
        raw_payload_sha256=canonical_sha256([side, value, time_s]),
    )


def test_residual_is_independently_recomputed_without_backfill() -> None:
    observed = _sample(TwinStreamSide.OBSERVED, Vector3(x=0.2, z=0.4))
    predicted = _sample(TwinStreamSide.PREDICTED, Vector3(x=0.1, z=0.35))
    residual = derive_twin_residuals(
        (predicted, observed), alignment_tolerance_s=0.15
    )[0]
    assert residual.value is not None
    assert residual.value.x == pytest.approx(0.1)
    assert residual.value.z == pytest.approx(0.05)
    assert residual.observed_sample_sha256 == observed.sample_sha256
    missing = _sample(TwinStreamSide.OBSERVED, None, time_s=2.0)
    unavailable = derive_twin_residuals(
        (predicted, missing), alignment_tolerance_s=0.15
    )[0]
    assert unavailable.availability is TwinAvailability.MISSING
    assert unavailable.value is None
