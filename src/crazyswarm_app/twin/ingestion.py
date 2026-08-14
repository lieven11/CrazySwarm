from __future__ import annotations

from collections import defaultdict

from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.models import (
    TwinChannelDefinition,
    TwinIngestionBatch,
    TwinIngestionReceipt,
    TwinTimeline,
)
from crazyswarm_app.twin.replay import derive_twin_residuals
from crazyswarm_app.twin.storage import DurableTwinStore


class TwinIngestionBoundary:
    """One bounded contract for simulator and real-adapter-shaped samples."""

    def __init__(self, store: DurableTwinStore) -> None:
        self.store = store
        self._channels: dict[str, dict[str, TwinChannelDefinition]] = {}

    def register_channels(
        self,
        session_id: str,
        channels: tuple[TwinChannelDefinition, ...],
    ) -> None:
        if not 1 <= len(channels) <= 32:
            raise ValueError("a twin session must declare 1..32 channels")
        if len({item.channel_id for item in channels}) != len(channels):
            raise ValueError("twin channel IDs must be unique")
        self.store.record(session_id)
        self._channels[session_id] = {item.channel_id: item for item in channels}

    def ingest(self, batch: TwinIngestionBatch) -> TwinIngestionReceipt:
        encoded_size = len(batch.model_dump_json().encode())
        if encoded_size > 1024 * 1024:
            raise ValueError("twin ingestion batch exceeds 1 MiB")
        channels = self._channels.get(batch.session_id)
        if channels is None:
            raise ValueError("twin channels are not registered for this session")
        existing = self.store.samples(batch.session_id)
        existing_by_id = {item.sample_id: item for item in existing}
        last_by_stream = {
            (item.side, item.vehicle_id, item.channel_id): item
            for item in sorted(
                existing,
                key=lambda item: (item.source_timestamp_s, item.sequence),
            )
        }
        batch_seen: dict[str, str] = {}
        for sample in batch.samples:
            if sample.session_id != batch.session_id:
                raise ValueError("twin batch contains a cross-session sample")
            definition = channels.get(sample.channel_id)
            if definition is None:
                raise ValueError("twin sample uses an undeclared channel")
            if sample.unit != definition.unit or sample.frame != definition.frame:
                raise ValueError("twin sample unit/frame differs from channel contract")
            prior_hash = batch_seen.get(sample.sample_id)
            if prior_hash is not None and prior_hash != sample.sample_sha256:
                raise ValueError("batch contains conflicting duplicate sample IDs")
            if prior_hash == sample.sample_sha256:
                continue
            batch_seen[sample.sample_id] = sample.sample_sha256
            persisted = existing_by_id.get(sample.sample_id)
            if persisted is not None:
                if persisted.sample_sha256 != sample.sample_sha256:
                    raise ValueError("persisted sample ID has different content")
                continue
            stream = (sample.side, sample.vehicle_id, sample.channel_id)
            previous = last_by_stream.get(stream)
            if previous is not None:
                if sample.sequence <= previous.sequence:
                    raise ValueError("twin stream sequence is stale or out of order")
                if sample.source_timestamp_s <= previous.source_timestamp_s:
                    raise ValueError("twin stream source time is stale or out of order")
                if sample.source_timestamp_s - previous.source_timestamp_s < 1.0 / 500.0:
                    raise ValueError("twin stream exceeds the 500 Hz ingestion bound")
            last_by_stream[stream] = sample
        accepted, idempotent = self.store.append_samples(
            batch.session_id,
            batch.samples,
        )
        payload = {
            "session_id": batch.session_id,
            "accepted_count": accepted,
            "idempotent_count": idempotent,
            "first_sequence": min(item.sequence for item in batch.samples),
            "last_sequence": max(item.sequence for item in batch.samples),
            "batch_sha256": canonical_sha256(batch),
        }
        return TwinIngestionReceipt(**payload)

    def timeline(
        self,
        session_id: str,
        *,
        channel_ids: tuple[str, ...] = (),
        after_source_s: float | None = None,
        limit: int = 4096,
    ) -> TwinTimeline:
        if not 1 <= limit <= 4096:
            raise ValueError("twin timeline limit must be in 1..4096")
        selected_channels = set(channel_ids)
        if len(selected_channels) > 32:
            raise ValueError("twin timeline may select at most 32 channels")
        values = [
            item
            for item in self.store.samples(session_id)
            if (not selected_channels or item.channel_id in selected_channels)
            and (after_source_s is None or item.source_timestamp_s > after_source_s)
        ]
        values.sort(
            key=lambda item: (
                item.source_timestamp_s,
                item.side,
                item.channel_id,
                item.sequence,
            )
        )
        page = tuple(values[:limit])
        next_after = page[-1].source_timestamp_s if len(values) > limit else None
        page_hashes = {item.sample_sha256 for item in page}
        residuals = tuple(
            item
            for item in derive_twin_residuals(
                values,
                alignment_tolerance_s=self.store.config(
                    session_id
                ).alignment_tolerance_s,
            )
            if item.observed_sample_sha256 in page_hashes
        )
        payload = {
            "session_id": session_id,
            "samples": page,
            "residuals": residuals,
            "next_after_source_s": next_after,
        }
        return TwinTimeline(**payload, timeline_sha256=canonical_sha256(payload))


def default_twin_channels() -> tuple[TwinChannelDefinition, ...]:
    """Complete common schema; producers emit MISSING instead of inventing values."""

    definitions = {
        "pose.position": ("m", "world", "VECTOR3"),
        "velocity.linear": ("m/s", "world", "VECTOR3"),
        "attitude.euler": ("rad", "body", "VECTOR3"),
        "imu.acceleration": ("m/s^2", "body", "VECTOR3"),
        "imu.angular_velocity": ("rad/s", "body", "VECTOR3"),
        "battery.voltage": ("V", "vehicle", "SCALAR"),
        "battery.current": ("A", "vehicle", "SCALAR"),
        "battery.state": ("json", "vehicle", "IDENTIFIER"),
        "estimator.health": ("state", "vehicle", "IDENTIFIER"),
        "flow.state": ("json", "body", "IDENTIFIER"),
        "range.state": ("json", "body", "IDENTIFIER"),
        "perception.world_revision": ("revision", "world", "SCALAR"),
        "command.identity": ("sha256", "authority", "IDENTIFIER"),
        "plan.identity": ("sha256", "authority", "IDENTIFIER"),
        "replan.identity": ("sha256", "authority", "IDENTIFIER"),
        "safety.state": ("state", "authority", "IDENTIFIER"),
        **{
            f"motor.m{index}.thrust": ("N", "body", "SCALAR")
            for index in range(1, 5)
        },
        **{
            f"motor.m{index}.pwm": ("percent", "body", "SCALAR")
            for index in range(1, 5)
        },
        **{
            f"motor.m{index}.state": ("json", "body", "IDENTIFIER")
            for index in range(1, 5)
        },
    }
    by_kind: dict[str, list[TwinChannelDefinition]] = defaultdict(list)
    for channel_id, (unit, frame, kind) in definitions.items():
        by_kind[kind].append(
            TwinChannelDefinition(
                channel_id=channel_id,
                unit=unit,
                frame=frame,
                value_kind=kind,
            )
        )
    return tuple(
        item
        for kind in sorted(by_kind)
        for item in sorted(by_kind[kind], key=lambda value: value.channel_id)
    )
