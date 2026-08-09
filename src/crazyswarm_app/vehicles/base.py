from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from crazyswarm_app.domain.commands import CommandAcknowledgement, CommandEnvelope
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    VehicleBackendProfile,
    VehicleCapabilities,
    VehicleIdentity,
)
from crazyswarm_app.domain.simulation import (
    AdapterContractManifest,
    FleetAuthorityTransition,
    FleetAuthorityTransitionReceipt,
    MissionRunBinding,
)
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
    @abstractmethod
    def backend_profile(self) -> VehicleBackendProfile:
        raise NotImplementedError

    @property
    def parameter_provider(self) -> Any | None:
        return None

    @property
    def simulation_controls(self) -> Any | None:
        return None

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
            "backend_role": self.backend_profile.role.value,
            "authority_class": self.backend_profile.authority.value,
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

    async def bind_run(self, binding: MissionRunBinding) -> None:
        """Bind mission/evidence identity when a backend supports a run-aware session."""

        del binding

    async def transition_fleet_authority(
        self,
        transition: FleetAuthorityTransition,
    ) -> FleetAuthorityTransitionReceipt:
        """Change in-run fleet authority only on adapters that implement the guard."""

        del transition
        raise CrazySwarmError(
            ErrorCode.MODE_NOT_AUTHORIZED,
            "vehicle adapter does not support in-run fleet authority transitions",
        )

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
