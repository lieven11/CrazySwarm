from __future__ import annotations

import argparse
import json
from pathlib import Path

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.qualification import run_constraint_directed_qualification

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "missions/campaigns/sim/qualification/constraint-directed-planning-v1.json"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Qualify the WP-49 bottleneck/head-on/merge causal matrix"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    report = run_constraint_directed_qualification(catalog)
    payload = report.model_dump(mode="json")
    if args.check:
        retained = json.loads(args.output.read_text(encoding="utf-8"))
        if retained != payload:
            print("constraint-directed qualification artifact is stale")
            return 1
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        f"planner_rows={len(report.rows)} geometry_rows={len(report.geometry_rows)} "
        f"dynamic_rows={len(report.dynamic_rows)} passed={report.passed} "
        f"sha256={report.report_sha256}"
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
