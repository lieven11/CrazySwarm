#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crazyswarm_app.observability.evaluation import MissionExecutionEvaluation
from crazyswarm_app.planning.curriculum import (
    CurriculumManifest,
    CurriculumPromotion,
    generate_progressive_curriculum,
    promote_curriculum,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the mission curriculum or promote retained evaluator reports."
    )
    parser.add_argument(
        "--evaluation-map",
        type=Path,
        help=(
            "JSON object mapping immutable case SHA-256 values to persisted "
            "mission-execution evaluation JSON paths"
        ),
    )
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    arguments = parser.parse_args()

    manifest = generate_progressive_curriculum()
    artifact: CurriculumManifest | CurriculumPromotion = manifest
    if arguments.evaluation_map is not None:
        paths = json.loads(arguments.evaluation_map.read_text(encoding="utf-8"))
        if not isinstance(paths, dict):
            raise ValueError("evaluation map must be a JSON object")
        reports = {
            str(case_sha256): MissionExecutionEvaluation.model_validate_json(
                Path(str(path)).read_text(encoding="utf-8")
            )
            for case_sha256, path in paths.items()
        }
        artifact = promote_curriculum(manifest, reports)

    encoded = json.dumps(
        artifact.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    )
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
