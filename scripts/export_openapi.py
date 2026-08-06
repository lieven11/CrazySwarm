from __future__ import annotations

import argparse
import json
from pathlib import Path

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runtime = create_runtime(
        load_config(Path("config/app.yaml")),
        Path("config/worlds/one_drone.yaml"),
        evidence_path=Path("/tmp/crazyswarm-openapi.sqlite3"),
    )
    try:
        schema = create_app(
            runtime,
            local_token="schema-generation-token-00000000",
            manage_runtime=False,
        ).openapi()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    finally:
        runtime.store.close()


if __name__ == "__main__":
    main()
