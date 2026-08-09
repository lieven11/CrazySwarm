#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crazyswarm_app.isaac.host_qualification import (
    evaluate_isaac_host,
    load_host_inventory,
    load_official_requirements,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a measured Isaac host inventory with the pinned WP01 baseline."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = evaluate_isaac_host(
        load_host_inventory(arguments.inventory),
        load_official_requirements(arguments.requirements),
    )
    rendered = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.compatible else 2


if __name__ == "__main__":
    raise SystemExit(main())
