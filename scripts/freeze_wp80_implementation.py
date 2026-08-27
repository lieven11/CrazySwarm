#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DESIGN_AUDIT = ROOT / "missions/campaigns/sim/qualification/wp80-r1-design-audit-v2.json"
DEFAULT_OUTPUT = ROOT / "missions/campaigns/sim/qualification/wp80-implementation-manifest-v1.json"
LEDGER = ROOT / "docs/work-packages/ACTIVE.md"
IMPLEMENTATION_BEGIN = "<!-- WP80-IMPLEMENTATION-PAYLOAD-BEGIN -->"
IMPLEMENTATION_END = "<!-- WP80-IMPLEMENTATION-PAYLOAD-END -->"

PACKET_PATHS = {
    "design.md",
    "docs/project/DESIGN.md",
    "docs/system/README.md",
    "scripts/freeze_wp80_implementation.py",
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/hardware/observation_twin.py",
    "src/crazyswarm_app/twin/coordinator.py",
    "src/crazyswarm_app/twin/models.py",
    "src/crazyswarm_app/twin/replay.py",
    "src/crazyswarm_app/vehicles/crazyflie.py",
    "tests/api/test_physical_twin.py",
    "tests/hardware/test_crazyflie_adapter.py",
    "tests/hardware/test_observation_twin_service.py",
    "ui/app/components/ControlCenter.tsx",
    "ui/app/globals.css",
    "ui/app/lib/api.generated.ts",
    "ui/app/lib/api.ts",
    "ui/app/lib/models.ts",
    "ui/openapi.json",
    "ui/tests/components.test.tsx",
    "ui/tests/physical-twin.test.tsx",
}

GENERATED_PATHS = {"ui/openapi.json", "ui/app/lib/api.generated.ts"}

EVIDENCE = [
    {
        "check": "packet_python_and_boundary_suite",
        "result": "PASS",
        "summary": "58 passed; packet-specific final subset 10 passed",
    },
    {
        "check": "ui_unit_suite",
        "result": "PASS",
        "summary": "140 passed",
    },
    {"check": "ui_production_build", "result": "PASS"},
    {"check": "typescript_typecheck", "result": "PASS"},
    {"check": "packet_eslint_ruff_mypy", "result": "PASS"},
    {"check": "openapi_regeneration", "result": "PASS"},
    {
        "check": "live_visual_browser",
        "result": "NOT_RUN",
        "summary": "dashboard served HTTP 200; in-app browser could not reach local host",
    },
    {
        "check": "hardware",
        "result": "NOT_RUN",
        "summary": "no scan, connection, permit, motor command, or flight",
    },
    {
        "check": "broader_api_suite",
        "result": "OUT_OF_SCOPE_FAILURE",
        "summary": "concurrent campaign catalog expected 55 cases but production reports 54",
    },
]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(relative: str) -> str | None:
    path = ROOT / relative
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def delimited_payload(text: str, begin: str, end: str) -> bytes:
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    return (text[start:finish] + "\n").encode()


def build_manifest() -> dict[str, Any]:
    design = json.loads(DESIGN_AUDIT.read_text(encoding="utf-8"))
    ledger_text = LEDGER.read_text(encoding="utf-8")
    frozen = design["manifest"]
    closure: dict[str, dict[str, str | None]] = {}
    for relative, (design_classification, preimage) in sorted(frozen.items()):
        postimage = sha256_path(relative)
        if relative in PACKET_PATHS:
            disposition = "WP80_IMPLEMENTATION"
        elif postimage == preimage:
            disposition = "RELIED_UPON_UNCHANGED"
        else:
            disposition = "CONCURRENT_OUT_OF_SCOPE_DRIFT"
        closure[relative] = {
            "design_classification": design_classification,
            "preimage_sha256": preimage,
            "postimage_sha256": postimage,
            "disposition": disposition,
        }

    implementation: dict[str, dict[str, str | None]] = {}
    for relative in sorted(PACKET_PATHS):
        preimage = frozen.get(relative, (None, None))[1]
        implementation[relative] = {
            "classification": (
                "GENERATED"
                if relative in GENERATED_PATHS
                else "NEW"
                if preimage is None
                else "CHANGED"
            ),
            "preimage_sha256": preimage,
            "postimage_sha256": sha256_path(relative),
        }

    return {
        "schema_version": 1,
        "review_unit": "WP-80",
        "base_commit": design["base_commit"],
        "accepted_design": {
            "initial_sha256": design["initial_payload"]["sha256"],
            "r1_sha256": design["r1_payload"]["sha256"],
            "design_audit_sha256": sha256_path(
                "missions/campaigns/sim/qualification/wp80-r1-design-audit-v2.json"
            ),
        },
        "dirty_tree_identity": (
            "exact frozen closure pre/post hashes plus explicit packet-owned paths; "
            "not an undifferentiated git diff"
        ),
        "implementation_payload": {
            "sha256": sha256_bytes(
                delimited_payload(ledger_text, IMPLEMENTATION_BEGIN, IMPLEMENTATION_END)
            ),
            "status": "IMPLEMENTED",
            "independent_verification": "BLOCKED_WITH_FINDINGS",
        },
        "implementation_paths": implementation,
        "frozen_design_closure": closure,
        "evidence": EVIDENCE,
        "hardware_evidence": "NOT_RUN",
        "authority_claim": "OBSERVATION_ONLY_ZERO_COMMAND",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = build_manifest()
    encoded = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if args.check:
        if not output.is_file():
            raise SystemExit(f"missing implementation manifest: {output}")
        actual = json.loads(output.read_text(encoding="utf-8"))
        if actual != expected:
            raise SystemExit("WP-80 implementation manifest does not match current postimages")
        boundary_count = len(expected["frozen_design_closure"])
        print(f"WP-80 implementation manifest PASS ({boundary_count} boundaries)")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    print(output.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
