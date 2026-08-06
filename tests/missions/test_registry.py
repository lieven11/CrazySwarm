from __future__ import annotations

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.missions.catalog import HoverParameters
from crazyswarm_app.missions.registry import default_registry


def test_registry_generates_dropdown_metadata_and_json_schemas() -> None:
    registry = default_registry()
    metadata = registry.list_metadata()
    assert [item.mission_id for item in metadata] == ["hover", "move-return", "square"]
    hover = registry.metadata("hover")
    assert hover.parameter_schema["additionalProperties"] is False
    assert hover.parameter_schema["properties"]["height_m"]["maximum"] == 1.0
    assert "gentle-30cm" in hover.presets


def test_defaults_presets_and_overrides_are_validated() -> None:
    registry = default_registry()
    defaults = registry.validate_parameters("hover")
    assert defaults == HoverParameters()
    preset = registry.validate_parameters(
        "hover",
        preset="quick-check",
        overrides={"duration_s": 2.5},
    )
    assert isinstance(preset, HoverParameters)
    assert preset.height_m == 0.2
    assert preset.duration_s == 2.5


def test_unknown_preset_and_extra_parameter_are_rejected() -> None:
    registry = default_registry()
    with pytest.raises(CrazySwarmError) as unknown:
        registry.validate_parameters("hover", preset="unsafe")
    assert unknown.value.code is ErrorCode.INVALID_COMMAND
    with pytest.raises(CrazySwarmError) as extra:
        registry.validate_parameters("hover", {"exec_python": "anything"})
    assert extra.value.code is ErrorCode.INVALID_COMMAND
