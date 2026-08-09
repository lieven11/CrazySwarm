from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import VehicleCapability, VehicleState
from crazyswarm_app.vehicles.base import Vehicle

ParameterValue = bool | int | float | str


class ParameterAccess(StrEnum):
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"


class ParameterPersistence(StrEnum):
    SESSION = "SESSION"
    STORED = "STORED"


class ParameterRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: ParameterValue
    default: ParameterValue
    value_type: str
    access: ParameterAccess
    persistence: ParameterPersistence
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    source_class: str = "CONFIGURED"


class ParameterSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    vehicle_id: str
    created_at_monotonic_s: float
    values: dict[str, ParameterValue]


class ParameterProvider(Protocol):
    def list_parameters(self) -> tuple[ParameterRecord, ...]: ...

    def write_parameter(
        self,
        name: str,
        value: ParameterValue,
        *,
        state: VehicleState,
        armed: bool,
    ) -> ParameterRecord: ...


@dataclass(slots=True)
class ParameterService:
    """Capability-routed parameter facade with no concrete adapter dependency."""

    vehicles: dict[str, Vehicle]
    snapshots: dict[str, ParameterSnapshot] = field(default_factory=dict)

    def list(self, vehicle_id: str) -> tuple[ParameterRecord, ...]:
        return self._provider(vehicle_id).list_parameters()

    def write(
        self,
        vehicle_id: str,
        name: str,
        value: ParameterValue,
        *,
        state: VehicleState,
        armed: bool = False,
    ) -> ParameterRecord:
        return self._provider(vehicle_id).write_parameter(
            name,
            value,
            state=state,
            armed=armed,
        )

    def snapshot(self, vehicle_id: str) -> ParameterSnapshot:
        values = {record.name: record.value for record in self.list(vehicle_id)}
        snapshot = ParameterSnapshot(
            snapshot_id=f"params-{uuid.uuid4().hex}",
            vehicle_id=vehicle_id,
            created_at_monotonic_s=time.monotonic(),
            values=values,
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def diff(self, vehicle_id: str, snapshot_id: str) -> dict[str, dict[str, ParameterValue]]:
        snapshot = self._require_snapshot(vehicle_id, snapshot_id)
        current = {record.name: record.value for record in self.list(vehicle_id)}
        return {
            name: {"before": value, "current": current[name]}
            for name, value in snapshot.values.items()
            if current.get(name) != value
        }

    def restore(
        self,
        vehicle_id: str,
        snapshot_id: str,
        *,
        state: VehicleState,
        armed: bool = False,
    ) -> tuple[ParameterRecord, ...]:
        snapshot = self._require_snapshot(vehicle_id, snapshot_id)
        current = {record.name: record for record in self.list(vehicle_id)}
        for name, value in snapshot.values.items():
            if current[name].access is ParameterAccess.READ_ONLY:
                continue
            self.write(vehicle_id, name, value, state=state, armed=armed)
        return self.list(vehicle_id)

    def _provider(self, vehicle_id: str) -> ParameterProvider:
        try:
            vehicle = self.vehicles[vehicle_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH, f"unknown vehicle: {vehicle_id}"
            ) from error
        if VehicleCapability.PARAMETER_ACCESS not in vehicle.capabilities.features:
            raise CrazySwarmError(ErrorCode.CAPABILITY_MISSING, "parameter access is unavailable")
        provider = vehicle.parameter_provider
        if provider is None:
            raise CrazySwarmError(ErrorCode.CAPABILITY_MISSING, "parameter provider is unavailable")
        return cast(ParameterProvider, provider)

    def _require_snapshot(self, vehicle_id: str, snapshot_id: str) -> ParameterSnapshot:
        try:
            snapshot = self.snapshots[snapshot_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, f"unknown parameter snapshot: {snapshot_id}"
            ) from error
        if snapshot.vehicle_id != vehicle_id:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH, "parameter snapshot vehicle mismatch"
            )
        return snapshot
