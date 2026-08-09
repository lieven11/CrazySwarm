from __future__ import annotations

from collections.abc import Iterable
from typing import Generic, TypeVar

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.planning.contracts import (
    FleetPolicy,
    PluginKind,
    PluginManifest,
    QualificationState,
    RecoveryStrategy,
    RoutePlanner,
)

PluginT = TypeVar("PluginT", RoutePlanner, FleetPolicy, RecoveryStrategy)


class PluginRegistry(Generic[PluginT]):
    """Explicit process-local allow list. It never imports or installs plugin code."""

    def __init__(self, kind: PluginKind, plugins: Iterable[PluginT] = ()) -> None:
        self.kind = kind
        self._plugins: dict[tuple[str, str], PluginT] = {}
        for plugin in plugins:
            self.register(plugin)

    def register(self, plugin: PluginT) -> None:
        manifest = plugin.manifest
        if manifest.kind is not self.kind:
            raise ValueError(f"{manifest.plugin_id} has the wrong plugin kind")
        key = (manifest.plugin_id, manifest.implementation_version)
        if key in self._plugins:
            raise ValueError(f"duplicate plugin registration: {key[0]}@{key[1]}")
        self._plugins[key] = plugin

    def resolve(
        self,
        plugin_id: str,
        version: str,
        *,
        required_capabilities: frozenset[str] = frozenset(),
        require_qualified: bool = True,
    ) -> PluginT:
        plugin = self._plugins.get((plugin_id, version))
        if plugin is None:
            raise CrazySwarmError(
                ErrorCode.CAPABILITY_MISSING,
                f"plugin is not registered: {plugin_id}@{version}",
            )
        manifest = plugin.manifest
        if not required_capabilities.issubset(manifest.capabilities):
            raise CrazySwarmError(
                ErrorCode.CAPABILITY_MISSING,
                f"plugin does not provide required capabilities: {plugin_id}@{version}",
                details={
                    "required": sorted(required_capabilities),
                    "available": sorted(manifest.capabilities),
                },
            )
        if require_qualified and manifest.qualification is not QualificationState.QUALIFIED:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                f"plugin is not qualified: {plugin_id}@{version}",
            )
        return plugin

    def manifests(self) -> tuple[PluginManifest, ...]:
        return tuple(self._plugins[key].manifest for key in sorted(self._plugins))
