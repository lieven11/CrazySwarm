#!/usr/bin/env python3
"""Mark a completed campaign evidence generation as old without deleting it.

Restart the campaign API immediately afterward so its in-memory state reloads the
persisted boundary before another campaign mutation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.service import CampaignService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIRECTORY = ROOT / ".cache/crazyswarm/campaign"
DEFAULT_CASE_ROOT = ROOT / "missions/campaigns/sim/cases"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retain selected campaign runs as old, non-current evidence"
    )
    parser.add_argument("--state-directory", type=Path, default=DEFAULT_STATE_DIRECTORY)
    parser.add_argument("--case-root", type=Path, default=DEFAULT_CASE_ROOT)
    parser.add_argument("--fleet-size", type=int, choices=(1, 2, 3))
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--actor", default="operator")
    parser.add_argument("--reason", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    service = CampaignService(
        catalog=CampaignCatalog(arguments.case_root),
        state_directory=arguments.state_directory,
    )
    case_ids = set(arguments.case_id)
    if arguments.fleet_size is not None:
        case_ids.update(
            case.case_id
            for case in service.catalog.cases()
            if case.drone_count == arguments.fleet_size
        )
    if not case_ids:
        raise SystemExit("provide --fleet-size or at least one --case-id")

    changed = service.mark_runs_old(
        case_ids=sorted(case_ids),
        revision_id=arguments.revision,
        actor_id=arguments.actor,
        reason=arguments.reason,
    )
    print(
        json.dumps(
            {
                "marked_old_count": len(changed),
                "revision": arguments.revision,
                "run_ids": [run.run_id for run in changed],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
