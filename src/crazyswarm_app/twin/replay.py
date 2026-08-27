from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinQuality,
    TwinResidualSample,
    TwinStreamSample,
    TwinStreamSide,
)


def derive_twin_residuals(
    samples: Sequence[TwinStreamSample],
    *,
    alignment_tolerance_s: float,
) -> tuple[TwinResidualSample, ...]:
    """Deterministically align observations to predictions without inventing truth."""

    by_channel: dict[str, list[TwinStreamSample]] = defaultdict(list)
    for sample in samples:
        by_channel[sample.channel_id].append(sample)
    output: list[TwinResidualSample] = []
    for channel_id in sorted(by_channel):
        values = by_channel[channel_id]
        observed = sorted(
            (item for item in values if item.side is TwinStreamSide.OBSERVED),
            key=lambda item: (item.source_timestamp_s, item.sequence, item.sample_id),
        )
        predicted = tuple(item for item in values if item.side is TwinStreamSide.PREDICTED)
        for sample in observed:
            # A paired hardware residual is causal only when both samples came
            # from the same admitted pair and common alignment segment. Never
            # borrow the nearest prediction from an earlier producer epoch.
            nearest = next(
                (
                    item
                    for item in predicted
                    if sample.pair_id is not None
                    and item.pair_id == sample.pair_id
                    and item.pair_sequence == sample.pair_sequence
                    and item.alignment_epoch == sample.alignment_epoch
                    and item.session_id == sample.session_id
                    and item.unit == sample.unit
                    and item.frame == sample.frame
                ),
                None,
            )
            delta = (
                abs(nearest.source_timestamp_s - sample.source_timestamp_s)
                if nearest is not None
                else None
            )
            availability = TwinAvailability.AVAILABLE
            quality = TwinQuality.GOOD
            residual_value: float | Vector3 | None = None
            if sample.availability is not TwinAvailability.AVAILABLE:
                availability = sample.availability
                quality = sample.quality
            elif nearest is None:
                availability = TwinAvailability.MISSING
                quality = TwinQuality.UNQUALIFIED
            elif delta is None or delta > alignment_tolerance_s:
                availability = TwinAvailability.STALE
                quality = TwinQuality.INVALID
            elif nearest.availability is not TwinAvailability.AVAILABLE:
                availability = nearest.availability
                quality = nearest.quality
            else:
                residual_value = _subtract(sample.value, nearest.value)
                if residual_value is None:
                    availability = TwinAvailability.REJECTED
                    quality = TwinQuality.INVALID
            payload = {
                "schema_version": 1,
                "session_id": sample.session_id,
                "channel_id": channel_id,
                "pair_id": sample.pair_id if nearest is not None else None,
                "pair_sequence": sample.pair_sequence if nearest is not None else None,
                "alignment_epoch": sample.alignment_epoch if nearest is not None else None,
                "observed_source_epoch": sample.source_epoch,
                "predicted_source_epoch": (nearest.source_epoch if nearest is not None else None),
                "observed_sample_sha256": sample.sample_sha256,
                "predicted_sample_sha256": (nearest.sample_sha256 if nearest is not None else None),
                "source_timestamp_s": sample.source_timestamp_s,
                "alignment_delta_s": delta,
                "availability": availability,
                "quality": quality,
                "unit": sample.unit,
                "frame": sample.frame,
                "value": residual_value,
            }
            output.append(
                TwinResidualSample(
                    **payload,
                    residual_sha256=canonical_sha256(payload),
                )
            )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.source_timestamp_s,
                item.channel_id,
                item.observed_sample_sha256,
            ),
        )
    )


def _subtract(
    observed: float | bool | str | Vector3 | None,
    predicted: float | bool | str | Vector3 | None,
) -> float | Vector3 | None:
    if isinstance(observed, bool) or isinstance(predicted, bool):
        return None
    if isinstance(observed, (int, float)) and isinstance(predicted, (int, float)):
        return float(observed) - float(predicted)
    if isinstance(observed, Vector3) and isinstance(predicted, Vector3):
        return Vector3(
            x=observed.x - predicted.x,
            y=observed.y - predicted.y,
            z=observed.z - predicted.z,
        )
    return None
