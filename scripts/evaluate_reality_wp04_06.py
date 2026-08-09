#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crazyswarm_app.qualification.cross_source import build_cross_source_report
from crazyswarm_app.qualification.physical import load_physical_plan, verify_plan_source_hashes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Reality WP-04 through WP-06 readiness evaluator"
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path("config/qualification/reality-physical-plan-v1.json"),
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    plan = load_physical_plan(arguments.plan)
    source_findings = verify_plan_source_hashes(plan, arguments.root)
    report = build_cross_source_report(
        report_id="reality-wp06-provisional",
        runs=(),
        software_gate_passed=True,
        bench_gate_passed=False,
        physical_gate_passed=False,
        nvidia_host_compatible=False,
    )
    output = {
        "schema_version": 1,
        "operation": "READ_ONLY_NO_RADIO_NO_FLIGHT",
        "plan": plan.model_dump(mode="json"),
        "source_findings": [item.model_dump(mode="json") for item in source_findings],
        "cross_source_report": report.model_dump(mode="json"),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if all(item.passed for item in source_findings) else 1


if __name__ == "__main__":
    raise SystemExit(main())
