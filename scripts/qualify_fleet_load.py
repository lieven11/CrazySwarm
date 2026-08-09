#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from crazyswarm_app.fleet.load_qualification import run_fleet_load_qualification


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = run_fleet_load_qualification(root)
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if report.decision == "PASS_SOFTWARE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
