#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from crazyswarm_app.simulation.calibration import (
    PhysicalCalibrationArtifact,
    import_physical_calibration,
)
from crazyswarm_app.simulation.physics import PhysicsModelConfig


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(
            f"refusing to overwrite immutable calibration import: {arguments.output}"
        )
    artifact = PhysicalCalibrationArtifact.model_validate(_load_json(arguments.artifact))
    base = (
        PhysicsModelConfig()
        if arguments.base is None
        else PhysicsModelConfig.model_validate(_load_json(arguments.base))
    )
    imported = import_physical_calibration(artifact, base=base)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(imported.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "calibration_id": imported.calibration_id,
                "configuration_sha256": imported.imported_configuration_sha256,
                "model_version": imported.model_version,
                "output": str(arguments.output),
                "qualification": imported.parameter_source,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
