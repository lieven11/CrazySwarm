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
BEGIN = "<!-- WP86-DESIGN-PAYLOAD-BEGIN -->"
END = "<!-- WP86-DESIGN-PAYLOAD-END -->"

PYTHON_SEEDS = {
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/api/runtime.py",
    "src/crazyswarm_app/dashboard.py",
    "src/crazyswarm_app/dashboard_service.py",
    "src/crazyswarm_app/hardware/observation_twin.py",
    "src/crazyswarm_app/twin/coordinator.py",
    "src/crazyswarm_app/twin/ingestion.py",
    "src/crazyswarm_app/twin/models.py",
    "src/crazyswarm_app/twin/storage.py",
    "src/crazyswarm_app/vehicles/_cflib_link.py",
    "src/crazyswarm_app/vehicles/crazyflie.py",
}

UI_SEEDS = {
    "ui/app/components/ControlCenter.tsx",
    "ui/app/components/RoomScene.tsx",
    "ui/app/components/TelemetryDock.tsx",
    "ui/app/globals.css",
    "ui/app/layout.tsx",
    "ui/app/lib/api.ts",
    "ui/app/lib/models.ts",
    "ui/app/page.tsx",
    "ui/worker/index.ts",
}

FIXED_BOUNDARIES = {
    "design.md",
    "docs/project/DESIGN.md",
    "docs/project/requirements/FIDELITY_AND_TRANSFER.md",
    "docs/project/requirements/UI_AND_CATALOG.md",
    "docs/project/requirements/workflow/COST_SCOPE_AND_HANDOFF.md",
    "docs/project/requirements/workflow/PREFREEZE_AND_ORACLES.md",
    "docs/project/requirements/workflow/WORK_PACKET_GATES.md",
    "scripts/audit_wp86_design.py",
    "scripts/export_openapi.py",
    "tests/api/test_physical_twin.py",
    "tests/hardware/test_observation_twin_service.py",
    "tests/hardware/test_crazyflie_adapter.py",
    "tests/twin/test_ingestion.py",
    "tests/twin/test_persistence.py",
    "tests/twin/test_storage.py",
    "ui/package.json",
    "ui/tests/api-adapter.test.ts",
    "ui/tests/components.test.tsx",
    "ui/tests/twin-session.test.tsx",
}

IMPLEMENTATION_OWNED = PYTHON_SEEDS | UI_SEEDS | {
    "design.md",
    "docs/project/DESIGN.md",
    "tests/api/test_physical_twin.py",
    "tests/hardware/test_observation_twin_service.py",
    "tests/hardware/test_crazyflie_adapter.py",
    "tests/twin/test_ingestion.py",
    "tests/twin/test_persistence.py",
    "tests/twin/test_storage.py",
    "ui/tests/api-adapter.test.ts",
    "ui/tests/components.test.tsx",
    "ui/tests/twin-session.test.tsx",
}

INTENDED_NEW_PATHS = {
    "ui/app/components/TwinObservationReadout.tsx",
    "ui/tests/twin-observation-readout.test.tsx",
}

CLAIM_KEYS = (
    "background_observer_isolation",
    "single_subject_projection",
    "authoritative_transition_reconciliation",
    "literal_props_off_diagnostics",
    "paired_session_clock",
)


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


def delimited_payload(text: str) -> bytes:
    start = text.index(BEGIN)
    finish = text.index(END, start) + len(END)
    return (text[start:finish] + "\n").encode()


def clock_oracle(case: dict[str, object]) -> dict[str, object]:
    admitted = [float(value) for value in case["admitted_monotonic_s"]]
    observed = [float(value) for value in case["observed_raw_source_s"]]
    predicted = [float(value) for value in case["predicted_raw_source_s"]]
    if not admitted or len(admitted) != len(observed) or len(admitted) != len(predicted):
        raise ValueError("clock witness vectors must be non-empty and equal length")
    origin = admitted[0]
    mapped = [round(value - origin, 9) for value in admitted]
    return {
        "observed_mapped_s": mapped,
        "predicted_mapped_s": mapped,
        "observed_raw_source_s": observed,
        "predicted_raw_source_s": predicted,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "artifact",
        nargs="?",
        type=Path,
        default=ROOT / "missions/campaigns/sim/qualification/wp86-design-audit-v1.json",
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
    payload = delimited_payload(ledger_text)
    identity = data["payload"]
    if len(payload) != identity["bytes"] or sha256_bytes(payload) != identity["sha256"]:
        errors.append("WP-86 payload identity mismatch")
    prefix = ledger_text.split(BEGIN, 1)[0]
    if sha256_bytes(prefix.encode()) != data["ledger_preimage_sha256"]:
        errors.append("WP-86 ledger preimage mismatch")
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
            errors.append(f"{path}: classification/preimage mismatch")
    if set(data["intended_new_paths"]) != INTENDED_NEW_PATHS:
        errors.append("intended new path set mismatch")
    for path in INTENDED_NEW_PATHS:
        if (ROOT / path).exists():
            errors.append(f"{path}: intended new path already exists")

    text = payload.decode()
    matrix = text.split("### Claim and exit matrix", 1)[1].split("### Exact implementation boundary", 1)[0]
    payload_claims = re.findall(r"^\| `([a-z0-9_]+)` \|", matrix, re.MULTILINE)
    if tuple(payload_claims) != CLAIM_KEYS or set(data["claims"]) != set(payload_claims):
        errors.append(f"claim key mismatch: {payload_claims}")
    allowed_paths = set(data["manifest"]) | INTENDED_NEW_PATHS
    for key, row in data["claims"].items():
        missing = set(row["owners"] + row["entries"]) - allowed_paths
        if missing:
            errors.append(f"{key}: paths absent from manifest/new set: {sorted(missing)}")

    required_intent = {"minimum_useful_outcome", "requested", "prerequisites", "optional", "non_goals"}
    if set(data["intent_value_card"]) != required_intent:
        errors.append("intent/value card keys mismatch")

    witnesses = data["clock_witnesses"]
    for name in ("nominal", "raw_clock_perturbation", "admission_time_perturbation"):
        actual = clock_oracle(witnesses[name])
        if actual != witnesses[name]["expected"]:
            errors.append(f"clock witness mismatch: {name}")
    if witnesses["nominal"]["expected"] == witnesses["admission_time_perturbation"]["expected"]:
        errors.append("clock oracle is insensitive to admission-time perturbation")
    if witnesses["nominal"]["expected"]["observed_mapped_s"] != witnesses["raw_clock_perturbation"]["expected"]["observed_mapped_s"]:
        errors.append("raw producer perturbation changed paired session alignment")
    placeholder = witnesses["placeholder_rejection"]
    if placeholder != {
        "all_measured_channels_missing": True,
        "emit_pair": False,
        "establish_clock_origin": False,
    }:
        errors.append("placeholder rejection witness mismatch")

    observation = data["hardware_observation"]
    if observation["session_id"] != "twin-f33a1e55c4f2431480f1f41cd6f45a19":
        errors.append("hardware observation session mismatch")
    if observation["channel_sample_count"] != observation["paired_cycles"] * 56:
        errors.append("hardware channel/cycle count mismatch")
    if observation["observed_battery"]["unique_values"] <= 1:
        errors.append("battery evidence does not prove repeated measurement")
    if observation["clock"]["observed_final_mapped_s"] <= observation["clock"]["predicted_final_mapped_s"] * 10:
        errors.append("hardware clock counterexample is not discriminating")

    result = {
        "artifact": str(artifact.relative_to(ROOT)),
        "artifact_sha256": sha256(artifact),
        "payload_sha256": sha256_bytes(payload),
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
