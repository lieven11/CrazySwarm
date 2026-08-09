from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from crazyswarm_app.isaac.protocol import GATEWAY_PROTOCOL_VERSION


class LaunchReadiness(StrEnum):
    READY_FOR_EXPLICIT_LIVE_LAUNCH = "READY_FOR_EXPLICIT_LIVE_LAUNCH"
    WAITING_FOR_COMPATIBLE_LOCAL_OR_CLOUD_HOST = "WAITING_FOR_COMPATIBLE_LOCAL_OR_CLOUD_HOST"


@dataclass(frozen=True, slots=True)
class HeadlessLaunchPlan:
    status: LaunchReadiness
    issues: tuple[str, ...]
    argv: tuple[str, ...] | None
    runtime_version: str | None
    host_profile: Path | None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "issues": list(self.issues),
            "argv": list(self.argv) if self.argv is not None else None,
            "runtime_version": self.runtime_version,
            "host_profile": str(self.host_profile) if self.host_profile is not None else None,
            "gateway_protocol_version": GATEWAY_PROTOCOL_VERSION,
            "live_isaac_started": False,
            "paid_cloud_resources_created": False,
        }


def inspect_headless_launch(
    scene_path: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> HeadlessLaunchPlan:
    """Build a no-shell launch plan only after an external host gate is accepted."""

    values = os.environ if environment is None else environment
    issues: list[str] = []
    executable = _absolute_file(
        values.get("CRAZYSWARM_ISAAC_SIM_EXECUTABLE"),
        "CRAZYSWARM_ISAAC_SIM_EXECUTABLE",
        "executable",
        issues,
    )
    entrypoint = _absolute_file(
        values.get("CRAZYSWARM_ISAAC_GATEWAY_ENTRYPOINT"),
        "CRAZYSWARM_ISAAC_GATEWAY_ENTRYPOINT",
        "entrypoint",
        issues,
    )
    host_profile = _absolute_file(
        values.get("CRAZYSWARM_ISAAC_HOST_PROFILE"),
        "CRAZYSWARM_ISAAC_HOST_PROFILE",
        "host profile",
        issues,
    )
    runtime_version = values.get("CRAZYSWARM_ISAAC_RUNTIME_VERSION")
    if not runtime_version or runtime_version.lower() == "latest":
        issues.append("CRAZYSWARM_ISAAC_RUNTIME_VERSION must be an exact non-latest pin")
    token = values.get("CRAZYSWARM_ISAAC_GATEWAY_TOKEN")
    if token is None or len(token) < 32:
        issues.append("CRAZYSWARM_ISAAC_GATEWAY_TOKEN must contain at least 32 characters")
    if not scene_path.is_absolute() or not scene_path.is_file():
        issues.append("scene path must be an existing absolute file")
    if host_profile is not None:
        try:
            raw = json.loads(host_profile.read_text(encoding="utf-8"))
            if raw.get("decision") != "GO_MINIMAL_EXPERIMENT":
                issues.append("host profile decision is not GO_MINIMAL_EXPERIMENT")
            if raw.get("compatible") is not True:
                issues.append("host profile does not record compatible=true")
            if raw.get("headless_gateway_authorized") is not True:
                issues.append("host profile does not authorize a headless gateway launch")
            if raw.get("classification") != "MEASURED_HOST_EVIDENCE":
                issues.append("host profile is not measured host evidence")
            if raw.get("checker_status") != "PASSED":
                issues.append("host profile does not contain a passing official checker")
            profile_runtime = raw.get("isaac_runtime_version")
            if (
                not isinstance(profile_runtime, str)
                or profile_runtime.lower() == "latest"
                or profile_runtime.startswith("NOT_")
            ):
                issues.append("host profile does not contain an exact Isaac runtime pin")
            elif profile_runtime != runtime_version:
                issues.append("host profile runtime pin does not match the launch environment")
            for field in ("driver_version", "ros_distribution", "middleware"):
                value = raw.get(field)
                if not isinstance(value, str) or not value or value.startswith("NOT_"):
                    issues.append(f"host profile does not pin {field}")
        except (OSError, json.JSONDecodeError, AttributeError):
            issues.append("host profile is unreadable or malformed")
    argv = None
    if not issues and executable is not None and entrypoint is not None:
        argv = (
            str(executable),
            str(entrypoint),
            "--headless",
            "--scene",
            str(scene_path),
            "--gateway-protocol",
            GATEWAY_PROTOCOL_VERSION,
        )
    return HeadlessLaunchPlan(
        status=(
            LaunchReadiness.READY_FOR_EXPLICIT_LIVE_LAUNCH
            if argv is not None
            else LaunchReadiness.WAITING_FOR_COMPATIBLE_LOCAL_OR_CLOUD_HOST
        ),
        issues=tuple(issues),
        argv=argv,
        runtime_version=runtime_version,
        host_profile=host_profile,
    )


def _absolute_file(
    value: str | None,
    environment_name: str,
    label: str,
    issues: list[str],
) -> Path | None:
    if not value:
        issues.append(f"{environment_name} is not configured")
        return None
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        issues.append(f"Isaac {label} must be an existing absolute file")
        return None
    return path
