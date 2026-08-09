#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crazyswarm_app.simulation.physical_qualification import (
    run_fast_sim_physical_v2_qualification,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/qualification/fast-sim-physical-v2.json"),
    )
    arguments = parser.parse_args()
    report = run_fast_sim_physical_v2_qualification()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "decision": report["decision"],
        "normalized_report_sha256": report["normalized_report_sha256"],
        "output": str(arguments.output),
    }, sort_keys=True))
    if report["decision"] != "SOFTWARE_QUALIFIED_CONFIGURED_UNQUALIFIED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
