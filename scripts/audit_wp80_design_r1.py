from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/work-packages/ACTIVE.md"
BEGIN = "<!-- WP80-DESIGN-PAYLOAD-BEGIN -->"
END = "<!-- WP80-DESIGN-PAYLOAD-END -->"
R1_BEGIN = "<!-- WP80-R1-DESIGN-PAYLOAD-BEGIN -->"
R1_END = "<!-- WP80-R1-DESIGN-PAYLOAD-END -->"

PYTHON_SEEDS = {
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/api/runtime.py",
    "src/crazyswarm_app/config.py",
    "src/crazyswarm_app/vehicles/crazyflie.py",
    "src/crazyswarm_app/vehicles/_cflib_link.py",
    "src/crazyswarm_app/vehicles/crazyflie_link.py",
    "src/crazyswarm_app/vehicles/providers.py",
    "src/crazyswarm_app/twin/coordinator.py",
    "src/crazyswarm_app/twin/ingestion.py",
    "src/crazyswarm_app/twin/models.py",
    "src/crazyswarm_app/twin/storage.py",
    "src/crazyswarm_app/dashboard.py",
    "src/crazyswarm_app/dashboard_service.py",
}

UI_SEEDS = {
    "ui/app/page.tsx",
    "ui/app/components/ControlCenter.tsx",
    "ui/app/lib/api.ts",
    "ui/app/lib/models.ts",
    "ui/app/layout.tsx",
    "ui/app/globals.css",
    "ui/worker/index.ts",
}

FIXED_BOUNDARIES = {
    "config/qualification/reality-physical-plan-v1.json",
    "design.md",
    "docs/project/DESIGN.md",
    "docs/system/README.md",
    "docs/project/requirements/FIDELITY_AND_TRANSFER.md",
    "docs/project/requirements/UI_AND_CATALOG.md",
    "docs/project/requirements/workflow/WORK_PACKET_GATES.md",
    "docs/project/requirements/workflow/COST_SCOPE_AND_HANDOFF.md",
    "scripts/export_openapi.py",
    "ui/package.json",
    "tests/hardware/test_crazyflie_adapter.py",
    "tests/twin/test_coordinator.py",
    "tests/twin/test_ingestion.py",
    "tests/twin/test_storage.py",
    "tests/twin/test_twin_pipeline_e2e.py",
    "tests/api/test_twin.py",
    "tests/test_dashboard.py",
    "ui/tests/components.test.tsx",
    "ui/tests/twin-session.test.tsx",
}

IMPLEMENTATION_OWNED = PYTHON_SEEDS | UI_SEEDS | {
    "design.md",
    "docs/project/DESIGN.md",
    "docs/system/README.md",
    "ui/package.json",
    "scripts/export_openapi.py",
    "tests/hardware/test_crazyflie_adapter.py",
    "tests/twin/test_coordinator.py",
    "tests/twin/test_ingestion.py",
    "tests/twin/test_storage.py",
    "tests/twin/test_twin_pipeline_e2e.py",
    "tests/api/test_twin.py",
    "tests/test_dashboard.py",
    "ui/tests/components.test.tsx",
    "ui/tests/twin-session.test.tsx",
}

INTENDED_NEW_PATHS = {
    "src/crazyswarm_app/hardware/observation_twin.py",
    "tests/hardware/test_observation_twin_service.py",
    "tests/api/test_physical_twin.py",
    "ui/tests/physical-twin.test.tsx",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def python_module_path(module: str) -> str | None:
    if not module.startswith("crazyswarm_app"):
        return None
    relative = Path("src") / Path(*module.split("."))
    module_file = relative.with_suffix(".py")
    package_file = relative / "__init__.py"
    if (ROOT / module_file).is_file():
        return str(module_file)
    if (ROOT / package_file).is_file():
        return str(package_file)
    return None


def module_name(path: str) -> str:
    relative = Path(path).relative_to("src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def python_imports(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    current = module_name(path)
    current_package = current if path.endswith("/__init__.py") else current.rsplit(".", 1)[0]
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = python_module_path(alias.name)
                if resolved:
                    imports.add(resolved)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = current_package.split(".")
                prefix = ".".join(parts[: len(parts) - node.level + 1])
                target = ".".join(item for item in (prefix, node.module or "") if item)
            else:
                target = node.module or ""
            resolved = python_module_path(target)
            if resolved:
                imports.add(resolved)
            for alias in node.names:
                child = python_module_path(f"{target}.{alias.name}")
                if child:
                    imports.add(child)
    return imports


def recursive_python_closure() -> set[str]:
    closure = set(PYTHON_SEEDS)
    pending = list(PYTHON_SEEDS)
    while pending:
        path = pending.pop()
        for imported in python_imports(path):
            if imported not in closure:
                closure.add(imported)
                pending.append(imported)
    return closure


def resolve_ui_import(source: str, specifier: str) -> str | None:
    if specifier.startswith("@/"):
        base = Path("ui/app") / specifier[2:]
    elif specifier.startswith("."):
        base = Path(source).parent / specifier
    else:
        return None
    candidates = (
        base,
        base.with_suffix(".ts"),
        base.with_suffix(".tsx"),
        base.with_suffix(".css"),
        base / "index.ts",
        base / "index.tsx",
    )
    for candidate in candidates:
        if (ROOT / candidate).is_file():
            return os.path.normpath(str(candidate))
    return None


def ui_imports(path: str) -> set[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    specifiers = re.findall(
        r"(?:from\s+|import\s*\(|import\s+)[\s]*[\"']([^\"']+)[\"']",
        text,
    )
    return {
        resolved
        for specifier in specifiers
        if (resolved := resolve_ui_import(path, specifier)) is not None
    }


def recursive_ui_closure() -> set[str]:
    closure = set(UI_SEEDS)
    pending = list(UI_SEEDS)
    while pending:
        path = pending.pop()
        for imported in ui_imports(path):
            if imported not in closure:
                closure.add(imported)
                pending.append(imported)
    return closure


def generated_outputs() -> set[str]:
    package = json.loads((ROOT / "ui/package.json").read_text(encoding="utf-8"))
    command = package["scripts"]["generate:api"]
    outputs: set[str] = set()
    if "--output ui/openapi.json" in command:
        outputs.add("ui/openapi.json")
    if "-o app/lib/api.generated.ts" in command:
        outputs.add("ui/app/lib/api.generated.ts")
    return outputs


def discovered_boundaries() -> set[str]:
    return recursive_python_closure() | recursive_ui_closure() | FIXED_BOUNDARIES | generated_outputs()


def inferred_manifest() -> dict[str, list[str]]:
    generated = generated_outputs()
    return {
        path: [
            "GENERATED"
            if path in generated
            else "IMPLEMENTATION_OWNED"
            if path in IMPLEMENTATION_OWNED
            else "RELIED_UPON_UNCHANGED",
            sha256(ROOT / path),
        ]
        for path in sorted(discovered_boundaries())
    }


def delimited_payload(text: str, begin: str, end: str) -> bytes:
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    return (text[start:finish] + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "artifact",
        nargs="?",
        type=Path,
        default=ROOT / "missions/campaigns/sim/qualification/wp80-r1-design-audit-v2.json",
    )
    parser.add_argument("--print-manifest", action="store_true")
    args = parser.parse_args()
    if args.print_manifest:
        print(json.dumps(inferred_manifest(), indent=2, sort_keys=True))
        return 0

    artifact = args.artifact if args.artifact.is_absolute() else ROOT / args.artifact
    data = json.loads(artifact.read_text(encoding="utf-8"))
    errors: list[str] = []
    ledger_text = LEDGER.read_text(encoding="utf-8")
    payload = delimited_payload(ledger_text, BEGIN, END)
    r1_payload = delimited_payload(ledger_text, R1_BEGIN, R1_END)
    for label, value, identity in (
        ("WP-80", payload, data["initial_payload"]),
        ("WP-80 R1", r1_payload, data["r1_payload"]),
    ):
        if len(value) != identity["bytes"] or sha256_bytes(value) != identity["sha256"]:
            errors.append(f"{label} payload identity mismatch")
    prefix = ledger_text.split(BEGIN, 1)[0]
    if not prefix.endswith("\n\n"):
        errors.append("WP-80 ledger delimiter shape changed")
    elif sha256_bytes(prefix[:-1].encode()) != data["ledger_preimage_sha256"]:
        errors.append("WP-80 ledger preimage mismatch")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != data["base_commit"]:
        errors.append(f"base commit mismatch: {head}")

    derived = inferred_manifest()
    if set(derived) != set(data["manifest"]):
        errors.append(
            "recursive transit manifest mismatch: "
            f"missing={sorted(set(derived) - set(data['manifest']))}, "
            f"extra={sorted(set(data['manifest']) - set(derived))}"
        )
    for path in sorted(set(derived) & set(data["manifest"])):
        if derived[path] != data["manifest"][path]:
            errors.append(f"{path}: classification/preimage mismatch {derived[path]}")
    if generated_outputs() != {"ui/openapi.json", "ui/app/lib/api.generated.ts"}:
        errors.append("generated API pair could not be derived exactly")
    if set(data["intended_new_paths"]) != INTENDED_NEW_PATHS:
        errors.append("intended new path set mismatch")
    for path in INTENDED_NEW_PATHS:
        if (ROOT / path).exists():
            errors.append(f"{path}: intended new path already exists")

    r1_text = r1_payload.decode()
    claim_section = r1_text.split("### R1 corrected claim matrix", 1)[1].split(
        "The corrected audit artifacts", 1
    )[0]
    payload_claims = re.findall(r"^\| `([a-z0-9_]+)` \|", claim_section, re.MULTILINE)
    artifact_claims = data["claims"]
    if payload_claims != list(artifact_claims) or len(payload_claims) != len(set(payload_claims)):
        errors.append(f"claim key mismatch: {payload_claims}")
    allowed_claim_paths = set(data["manifest"]) | INTENDED_NEW_PATHS
    for claim, row in artifact_claims.items():
        missing_claim_paths = set(row["owners"] + row["entries"]) - allowed_claim_paths
        if missing_claim_paths:
            errors.append(
                f"{claim}: claim paths absent from manifest/new set: {sorted(missing_claim_paths)}"
            )

    result = {
        "artifact": str(artifact.relative_to(ROOT)),
        "artifact_sha256": sha256(artifact),
        "initial_payload_sha256": sha256_bytes(payload),
        "r1_payload_sha256": sha256_bytes(r1_payload),
        "boundary_count": len(derived),
        "python_closure_count": len(recursive_python_closure()),
        "ui_closure_count": len(recursive_ui_closure()),
        "generated_outputs": sorted(generated_outputs()),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
