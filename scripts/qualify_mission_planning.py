from __future__ import annotations

import json

from crazyswarm_app.planning.release import run_planning_release_qualification


def main() -> int:
    report = run_planning_release_qualification()
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
