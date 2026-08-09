#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from crazyswarm_app.observability.evaluation import MissionExecutionEvaluation
from crazyswarm_app.planning.robustness import (
    HigherFidelityHandoffBundle,
    ObservedMissionOutcome,
    RobustnessMatrixManifest,
    RobustnessQualification,
    build_higher_fidelity_handoff,
    generate_robustness_matrix,
    qualify_robustness,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the bounded mission-robustness matrix or qualify persisted "
            "evaluation/outcome evidence."
        )
    )
    parser.add_argument(
        "--evidence-map",
        type=Path,
        help=(
            "JSON object mapping matrix cell SHA-256 values to objects containing "
            "evaluation and outcome JSON paths"
        ),
    )
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    parser.add_argument(
        "--handoff-output",
        type=Path,
        help="write a backend-neutral handoff bundle when qualification passes",
    )
    arguments = parser.parse_args()

    manifest = generate_robustness_matrix()
    artifact: RobustnessMatrixManifest | RobustnessQualification = manifest
    handoff: HigherFidelityHandoffBundle | None = None
    if arguments.evidence_map is not None:
        raw = json.loads(arguments.evidence_map.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("robustness evidence map must be a JSON object")
        evidence_map: dict[str, tuple[MissionExecutionEvaluation, ObservedMissionOutcome]] = {}
        for cell_sha256, value in raw.items():
            paths = cast(dict[str, Any], value)
            evaluation_path = Path(str(paths["evaluation"]))
            outcome_path = Path(str(paths["outcome"]))
            evidence_map[str(cell_sha256)] = (
                MissionExecutionEvaluation.model_validate_json(
                    evaluation_path.read_text(encoding="utf-8")
                ),
                ObservedMissionOutcome.model_validate_json(
                    outcome_path.read_text(encoding="utf-8")
                ),
            )
        artifact = qualify_robustness(manifest, evidence_map)
        if artifact.passed:
            handoff = build_higher_fidelity_handoff(manifest, artifact)

    _emit(artifact, arguments.output)
    if arguments.handoff_output is not None:
        if handoff is None:
            raise ValueError("handoff output requires a complete passing qualification")
        _emit(handoff, arguments.handoff_output)
    return 0


def _emit(
    artifact: RobustnessMatrixManifest | RobustnessQualification | HigherFidelityHandoffBundle,
    output: Path | None,
) -> None:
    encoded = json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True)
    if output is None:
        print(encoded)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
