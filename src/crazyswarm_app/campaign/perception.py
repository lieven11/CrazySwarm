from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import Region3D
from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class PerceptionChangeKind(StrEnum):
    SOLID_APPEARED = "SOLID_APPEARED"
    SOLID_MOVED = "SOLID_MOVED"
    SOLID_DISAPPEARED = "SOLID_DISAPPEARED"
    PASSAGE_CLOSED = "PASSAGE_CLOSED"
    PASSAGE_OPENED = "PASSAGE_OPENED"


class PerceptionObservation(ContractModel):
    schema_version: Literal[1] = 1
    observation_id: Identifier
    source_event_id: Identifier
    mission_id: Identifier
    run_id: Identifier
    vehicle_id: Identifier
    sensor_id: Identifier
    sensor_configuration_sha256: SHA256
    world_revision: int = Field(ge=1)
    prior_perceived_world_revision: int = Field(ge=0)
    sequence: int = Field(ge=1)
    source_timestamp_s: float = Field(ge=0.0)
    received_timestamp_s: float = Field(ge=0.0)
    effective_source_s: float = Field(ge=0.0)
    expires_source_s: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    change_kind: PerceptionChangeKind
    solid_id: Identifier
    region: Region3D | None = None
    raw_payload_sha256: SHA256
    observation_sha256: SHA256

    @model_validator(mode="after")
    def causal_and_complete(self) -> PerceptionObservation:
        if self.received_timestamp_s < self.source_timestamp_s:
            raise ValueError("perception cannot be received before its source timestamp")
        if self.effective_source_s < self.source_timestamp_s:
            raise ValueError("perceived change cannot predate its source timestamp")
        if self.expires_source_s < self.received_timestamp_s:
            raise ValueError("perception expiry cannot precede receipt")
        needs_region = self.change_kind in {
            PerceptionChangeKind.SOLID_APPEARED,
            PerceptionChangeKind.SOLID_MOVED,
            PerceptionChangeKind.PASSAGE_CLOSED,
            PerceptionChangeKind.PASSAGE_OPENED,
        }
        if needs_region != (self.region is not None):
            raise ValueError("perception region does not match change kind")
        payload = self.model_dump(mode="python", exclude={"observation_sha256"})
        if canonical_sha256(payload) != self.observation_sha256:
            raise ValueError("perception observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> PerceptionObservation:
        payload = {"schema_version": 1, **values}
        return cls(**payload, observation_sha256=canonical_sha256(payload))


class PerceivedWorldState(ContractModel):
    schema_version: Literal[1] = 1
    revision: int = Field(ge=0)
    solids: dict[Identifier, Region3D]
    last_observation_sha256: SHA256 | None = None
    state_sha256: SHA256

    @classmethod
    def empty(cls) -> PerceivedWorldState:
        payload = {"schema_version": 1, "revision": 0, "solids": {}}
        return cls(**payload, state_sha256=canonical_sha256(payload))

    def apply(self, observation: PerceptionObservation) -> PerceivedWorldState:
        if observation.prior_perceived_world_revision != self.revision:
            raise ValueError("perception prior-world revision mismatch")
        solids = dict(self.solids)
        if observation.change_kind in {
            PerceptionChangeKind.SOLID_APPEARED,
            PerceptionChangeKind.SOLID_MOVED,
            PerceptionChangeKind.PASSAGE_CLOSED,
        }:
            assert observation.region is not None
            solids[observation.solid_id] = observation.region
        else:
            solids.pop(observation.solid_id, None)
        payload = {
            "schema_version": 1,
            "revision": self.revision + 1,
            "solids": solids,
            "last_observation_sha256": observation.observation_sha256,
        }
        return PerceivedWorldState(**payload, state_sha256=canonical_sha256(payload))


class PerceptionObservationSource:
    """Bounded causal queue shared by simulator and future physical adapters."""

    def __init__(
        self,
        observations: tuple[PerceptionObservation, ...],
        *,
        maximum_pending: int = 128,
    ) -> None:
        if not 1 <= maximum_pending <= 4096:
            raise ValueError("perception queue bound must be in 1..4096")
        if len(observations) > maximum_pending:
            raise ValueError("perception queue exceeds its configured bound")
        ordered = tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.received_timestamp_s,
                    item.sensor_id,
                    item.sequence,
                    item.observation_id,
                ),
            )
        )
        seen: set[tuple[str, int]] = set()
        for observation in ordered:
            key = (observation.sensor_id, observation.sequence)
            if key in seen:
                raise ValueError("perception source sequence is duplicated")
            seen.add(key)
        self._pending = list(ordered)
        self._persisted: list[SHA256] = []

    @property
    def count(self) -> int:
        return len(self._pending)

    def peek(self) -> PerceptionObservation | None:
        return self._pending[0] if self._pending else None

    def pop_ready(self, source_now_s: float) -> PerceptionObservation | None:
        if not self._pending or self._pending[0].received_timestamp_s > source_now_s:
            return None
        return self._pending.pop(0)

    def acknowledge_persisted(self, observation_sha256: SHA256) -> None:
        if observation_sha256 in self._persisted:
            raise ValueError("perception observation was persisted twice")
        self._persisted.append(observation_sha256)

    @property
    def persisted_sha256s(self) -> tuple[SHA256, ...]:
        return tuple(self._persisted)
