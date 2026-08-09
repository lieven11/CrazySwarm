#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crazyswarm_app.fleet.qualification import run_persistent_fleet_qualification


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qualify WP-05 through WP-08 software-only fleet behavior"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = run_persistent_fleet_qualification(root)
    payload = report.model_dump(mode="json")
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.decision == "PASS_SOFTWARE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
