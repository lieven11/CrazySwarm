from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from crazyswarm_app.domain.commands import CommandAcknowledgement, CommandEnvelope
from crazyswarm_app.domain.models import VehicleCapabilities, VehicleIdentity
from crazyswarm_app.domain.simulation import AdapterContractManifest
from crazyswarm_app.domain.telemetry import TelemetryEnvelope


class Vehicle(ABC):
    """Backend-neutral asynchronous vehicle contract."""

    @property
    @abstractmethod
    def identity(self) -> VehicleIdentity:
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> VehicleCapabilities:
        raise NotImplementedError

    @property
    def contract_manifest(self) -> AdapterContractManifest:
        return AdapterContractManifest(
            adapter_id=self.identity.adapter,
            supported_capabilities=self.capabilities.features,
            supported_signals=frozenset(),
            supported_model_ids=frozenset(),
        )

    @property
    def execution_metadata(self) -> dict[str, Any]:
        """Stable adapter/model identity copied into every mission receipt."""
        return {
            "vehicle_adapter": self.identity.adapter,
            "physics_model_id": None,
            "physics_model_version": None,
            "physics_configuration_sha256": None,
            "scenario_id": None,
            "scenario_schema_version": None,
            "scenario_configuration_sha256": None,
            "simulation_seed": None,
            "simulation_fixed_step_s": None,
            "initial_state_sha256": None,
            "run_identity_sha256": None,
        }

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, command: CommandEnvelope) -> CommandAcknowledgement:
        raise NotImplementedError

    @abstractmethod
    async def snapshot(self) -> TelemetryEnvelope:
        raise NotImplementedError

    @abstractmethod
    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        raise NotImplementedError
