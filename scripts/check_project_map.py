#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/system/README.md"
AGENTS = ROOT / "AGENTS.md"

MAPPED_PATHS = (
    "src/crazyswarm_app/missions/script.py",
    "src/crazyswarm_app/missions/runner.py",
    "src/crazyswarm_app/campaign/service.py",
    "src/crazyswarm_app/campaign/planner.py",
    "src/crazyswarm_app/campaign/replanning.py",
    "src/crazyswarm_app/campaign/runtime_executor.py",
    "src/crazyswarm_app/fleet/coordinator.py",
    "src/crazyswarm_app/fleet/tasks.py",
    "src/crazyswarm_app/safety/supervisor.py",
    "src/crazyswarm_app/missions/authority.py",
    "src/crazyswarm_app/simulation/vehicle.py",
    "src/crazyswarm_app/simulation/physics.py",
    "src/crazyswarm_app/simulation/parameters.py",
    "src/crazyswarm_app/observability/recorder.py",
    "src/crazyswarm_app/observability/storage.py",
    "src/crazyswarm_app/observability/csv_export.py",
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/api/runtime.py",
    "src/crazyswarm_app/qualification/physical.py",
    "ui/app/components",
    "ui/app/lib",
    "tests/campaign",
    "tests/fleet",
    "tests/safety",
    "tests/observability",
    "tests/api",
    "tests/twin",
)


def main() -> int:
    map_text = MAP.read_text(encoding="utf-8")
    agents_text = AGENTS.read_text(encoding="utf-8")
    errors: list[str] = []
    for relative in MAPPED_PATHS:
        path = ROOT / relative
        if not path.exists():
            errors.append(f"mapped path does not exist: {relative}")
        display = relative.removeprefix("src/crazyswarm_app/")
        if display not in map_text:
            errors.append(f"project map does not mention: {display}")
    if "entry point, responsibility owner, public transit boundary" not in map_text:
        errors.append("project map does not define its structural update trigger")
    if "update `docs/system/README.md`" not in agents_text:
        errors.append("AGENTS.md does not enforce structural map updates")

    result = {"valid": not errors, "mapped_path_count": len(MAPPED_PATHS), "errors": errors}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
