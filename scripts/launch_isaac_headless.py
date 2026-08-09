#!/usr/bin/env python3
"""Inspect or explicitly exec a qualified headless Isaac gateway launch plan."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from crazyswarm_app.isaac.launcher import LaunchReadiness, inspect_headless_launch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument(
        "--launch",
        action="store_true",
        help="exec the qualified plan; omitted by default so inspection cannot start Isaac",
    )
    args = parser.parse_args()
    scene = args.scene.resolve()
    plan = inspect_headless_launch(scene)
    print(json.dumps(plan.as_dict(), indent=2, sort_keys=True))
    if not args.launch:
        return 0 if plan.status is LaunchReadiness.READY_FOR_EXPLICIT_LIVE_LAUNCH else 2
    if plan.argv is None:
        return 2
    os.execve(plan.argv[0], plan.argv, dict(os.environ))
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
