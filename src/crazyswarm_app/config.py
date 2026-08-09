from __future__ import annotations

import ipaddress
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import OperatingMode
from crazyswarm_app.safety.policy import SafetyPolicy
from crazyswarm_app.simulation.models import SimulationConfig


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    application_name: str = "CrazySwarm Control Center"
    default_mode: OperatingMode = OperatingMode.SIM
    telemetry_period_s: float = Field(default=0.05, gt=0.0, le=10.0)
    cache_directory: Path = Path(".cache/crazyswarm")
    safety_envelope: SafetyPolicy = Field(default_factory=SafetyPolicy)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    api: ApiConfig = Field(default_factory=lambda: ApiConfig())
    evidence: EvidenceConfig = Field(default_factory=lambda: EvidenceConfig())
    run_files: RunFilesConfig = Field(default_factory=lambda: RunFilesConfig())


class ApiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bind_host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )

    @classmethod
    def _is_loopback(cls, host: str) -> bool:
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    @model_validator(mode="after")
    def local_bind_only(self) -> ApiConfig:
        if not self._is_loopback(self.bind_host):
            raise ValueError("API bind_host must be a loopback address")
        return self


class EvidenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    database_path: Path = Path(".cache/crazyswarm/evidence.sqlite3")
    recorder_buffer_size: int = Field(default=8192, ge=256)
    retention_days: int = Field(default=30, ge=1)


class RunFilesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory: Path = Path("run-files")
    keep_latest_missions: int = Field(default=100, ge=1)


def load_config(path: Path) -> AppConfig:
    with path.open(encoding="utf-8") as config_file:
        raw = yaml.safe_load(config_file) or {}
    if not isinstance(raw, dict):
        raise ValueError("application configuration must be a mapping")
    return AppConfig.model_validate(raw)
