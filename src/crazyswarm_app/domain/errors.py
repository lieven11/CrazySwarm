from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_COMMAND = "INVALID_COMMAND"
    INVALID_STATE = "INVALID_STATE"
    MODE_NOT_AUTHORIZED = "MODE_NOT_AUTHORIZED"
    CAPABILITY_MISSING = "CAPABILITY_MISSING"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    COMMAND_DROPPED = "COMMAND_DROPPED"
    LINK_LOST = "LINK_LOST"
    TELEMETRY_STALE = "TELEMETRY_STALE"
    LOCALIZATION_INVALID = "LOCALIZATION_INVALID"
    CRITICAL_BATTERY = "CRITICAL_BATTERY"
    GEOFENCE_BREACH = "GEOFENCE_BREACH"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class CrazySwarmError(RuntimeError):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }
