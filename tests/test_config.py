from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from crazyswarm_app.config import AppConfig, load_config
from crazyswarm_app.domain.models import OperatingMode


def test_default_mode_is_sim() -> None:
    assert AppConfig().default_mode is OperatingMode.SIM


def test_example_config_loads() -> None:
    config = load_config(Path("config/app.yaml"))
    assert config.default_mode is OperatingMode.SIM
    assert config.safety_envelope.max_altitude_m == 1.0


def test_unknown_config_key_fails(tmp_path: Path) -> None:
    config_path = tmp_path / "bad.yaml"
    config_path.write_text("schema_version: 1\nunknown: true\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="Extra inputs"):
        load_config(config_path)
