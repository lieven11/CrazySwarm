from __future__ import annotations

from typing import Any, cast

from pydantic import ValidationError

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.missions.base import Mission, MissionParameters
from crazyswarm_app.missions.models import MissionMetadata


class MissionRegistry:
    def __init__(self) -> None:
        self._missions: dict[str, Mission[Any]] = {}

    def register(self, mission: Mission[Any], *, replace: bool = False) -> None:
        if mission.mission_id in self._missions and not replace:
            raise ValueError(f"mission already registered: {mission.mission_id}")
        self._missions[mission.mission_id] = mission

    def get(self, mission_id: str) -> Mission[Any]:
        try:
            return self._missions[mission_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                f"unknown mission: {mission_id}",
                details={"mission_id": mission_id},
            ) from error

    def unregister(self, mission_id: str) -> Mission[Any]:
        mission = self.get(mission_id)
        del self._missions[mission_id]
        return mission

    def list_metadata(self) -> tuple[MissionMetadata, ...]:
        return tuple(self.metadata(item) for item in sorted(self._missions))

    def metadata(self, mission_id: str) -> MissionMetadata:
        mission = self.get(mission_id)
        return MissionMetadata(
            mission_id=mission.mission_id,
            mission_version=mission.mission_version,
            name=mission.name,
            description=mission.description,
            required_capabilities=mission.required_capabilities,
            parameter_schema=mission.parameters_type.model_json_schema(),
            presets=mission.presets,
            source_kind=mission.source_kind,
            source_filename=mission.source_filename,
            source_sha256=mission.source_sha256,
            planned_commands=mission.planned_commands,
        )

    def validate_parameters(
        self,
        mission_id: str,
        values: dict[str, Any] | None = None,
        *,
        preset: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> MissionParameters:
        mission = self.get(mission_id)
        merged: dict[str, Any] = {}
        if preset is not None:
            try:
                merged.update(mission.presets[preset])
            except KeyError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    f"unknown preset {preset!r} for mission {mission_id}",
                    details={"available_presets": sorted(mission.presets)},
                ) from error
        if values:
            merged.update(values)
        if overrides:
            merged.update(overrides)
        try:
            return cast(MissionParameters, mission.parameters_type.model_validate(merged))
        except ValidationError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "mission parameters are invalid",
                details={"errors": error.errors(include_url=False)},
            ) from error


def default_registry() -> MissionRegistry:
    from crazyswarm_app.missions.catalog import HoverMission, RelativeMoveMission, SquareMission

    registry = MissionRegistry()
    registry.register(HoverMission())
    registry.register(RelativeMoveMission())
    registry.register(SquareMission())
    return registry
