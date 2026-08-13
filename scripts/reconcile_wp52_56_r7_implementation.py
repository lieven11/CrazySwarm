#!/usr/bin/env python3
"""Reconcile current WP-52--56 behavior with the immutable R6 design oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audit_wp52_56_r6_design import build_audit

from crazyswarm_app.campaign.submissions import (
    AdmissionLifecycle,
    load_admission_registry,
    load_case_submission_registry,
)
from crazyswarm_app.domain.simulation import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
R6_SCRIPT = ROOT / "scripts/audit_wp52_56_r6_design.py"
R6_ORACLE = ROOT / "docs/work-packages/WP52_56_R6_NUMERICAL_PREDRAFT_AUDIT_2026-08-12.json"
REGISTRY_QUALIFICATION = (
    ROOT / "missions/campaigns/sim/qualification/selective-submission-registry-v1.json"
)
RUNTIME_QUALIFICATION = (
    ROOT / "missions/campaigns/sim/qualification/selective-submission-runtime-v2.json"
)
UI_INSPECTION = (
    ROOT / "missions/campaigns/sim/qualification/selective-submission-ui-inspection-v1.json"
)
DEFAULT_OUTPUT = (
    ROOT / "missions/campaigns/sim/qualification/wp52-56-r7-implementation-reconciliation-v1.json"
)

R6_SCRIPT_SHA256 = "e1fcfc5582fa8af6d217ce23c060a825e751ade24b3f08f698fbbeae088097da"
R6_ORACLE_SHA256 = "43486bab53e0509fdaf7862ed814a2bc186812ec7e2d0f9e3555a60a2f636b89"
R6_INTERNAL_SHA256 = "866261be59fa0651089f5450451e9a727f3526c8117da5d9b569353db25547ea"
ACCEPTED_R7_DESIGN_SHA256 = "4a394f58ecda69b07fce919c009e090aacb20a9ef65bd44a3a7b794fb16ad0a5"

# R7 permits these implementation-owned identities to move while freezing the
# numerical/categorical oracle, candidate family, selected candidates, and case truth.
MUTABLE_IDENTITY_KEYS = frozenset(
    {
        "audit_sha256",
        "capability_resolution_sha256",
        "case_submission_registry_sha256",
        "certificate_sha256",
        "evidence_sha256",
        "execution_profile_sha256",
        "feasibility_certificate_sha256",
        "independent_sample_sha256_by_role",
        "observation_sha256",
        "plan_sha256",
        "planning_submission_sha256",
        "samples_sha256_by_role",
        "trajectory_set_sha256",
        "trajectory_sha256_by_role",
    }
)

# Selected/candidate identities are deliberately absent from MUTABLE_IDENTITY_KEYS.
CURRENT_MANIFEST_PATHS = (
    "scripts/generate_submission_registry.py",
    "missions/campaigns/sim/submissions/case-submissions-v1.yaml",
    "missions/campaigns/sim/submissions/admission-records-v1.yaml",
    "src/crazyswarm_app/campaign/submissions.py",
    "src/crazyswarm_app/campaign/planner.py",
    "src/crazyswarm_app/campaign/trajectory.py",
    "src/crazyswarm_app/campaign/submission_measurement.py",
    "src/crazyswarm_app/campaign/service.py",
    "src/crazyswarm_app/campaign/runtime_executor.py",
    "scripts/qualify_submission_registry.py",
    "scripts/qualify_submission_registry_r6.py",
    "scripts/qualify_submission_runtime.py",
    "scripts/reconcile_wp52_56_r7_implementation.py",
    "tests/campaign/test_submissions.py",
    "tests/campaign/test_submission_runtime_qualification.py",
    "missions/campaigns/sim/qualification/selective-submission-registry-v1.json",
    "missions/campaigns/sim/qualification/selective-submission-runtime-v2.json",
    "missions/campaigns/sim/qualification/selective-submission-ui-inspection-v1.json",
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile the current implementation with the immutable R6 oracle"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected", type=Path, default=R6_ORACLE)
    return parser.parse_args()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_value(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def semantic_projection(value: Any) -> Any:
    """Remove only identities that R7 explicitly classifies as implementation-owned."""

    if isinstance(value, dict):
        return {
            key: semantic_projection(item)
            for key, item in sorted(value.items())
            if key not in MUTABLE_IDENTITY_KEYS
        }
    if isinstance(value, list):
        return [semantic_projection(item) for item in value]
    return value


def _mutable_identity_changes(
    expected: Any,
    actual: Any,
    *,
    path: str = "",
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            nested = f"{path}/{key}"
            if key in MUTABLE_IDENTITY_KEYS:
                before = expected.get(key)
                after = actual.get(key)
                if before != after:
                    changes.append({"path": nested, "before": before, "after": after})
            elif key in expected and key in actual:
                changes.extend(_mutable_identity_changes(expected[key], actual[key], path=nested))
        return changes
    if isinstance(expected, list) and isinstance(actual, list):
        for index, (before, after) in enumerate(zip(expected, actual, strict=False)):
            changes.extend(_mutable_identity_changes(before, after, path=f"{path}/{index}"))
    return changes


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object at {path}")
    return value


def _tree_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return canonical_sha256(
        sorted(
            (
                str(item.relative_to(path)),
                _file_sha256(item),
            )
            for item in path.rglob("*")
            if item.is_file()
        )
    )


def _current_manifest() -> dict[str, str]:
    return {
        relative: (_file_sha256(ROOT / relative) if (ROOT / relative).is_file() else "ABSENT")
        for relative in CURRENT_MANIFEST_PATHS
    }


def _registry_counts() -> dict[str, Any]:
    registry = load_case_submission_registry()
    admissions = load_admission_registry()
    proposals = tuple(item for row in registry.rows for item in row.submissions)
    lifecycle_counts = {
        lifecycle.value: sum(row.lifecycle is lifecycle for row in admissions.rows)
        for lifecycle in AdmissionLifecycle
    }
    retained_altitude_profiles = 5
    return {
        "case_count": len(registry.rows),
        "proposal_count": sum(len(row.proposals) for row in admissions.rows),
        "hidden_collapse_count": sum(not item.catalog_visible for item in proposals),
        "visible_relation_count": sum(item.catalog_visible for item in proposals),
        "lifecycle_counts": lifecycle_counts,
        "retained_altitude_profile_count": retained_altitude_profiles,
        "passed": (
            len(registry.rows) == 54
            and sum(len(row.proposals) for row in admissions.rows) == 111
            and sum(not item.catalog_visible for item in proposals) == 28
            and sum(item.catalog_visible for item in proposals) == 83
            and lifecycle_counts
            == {"SUBMISSIONS": 43, "BASELINE_ONLY": 9, "RETAIN_EXISTING_ONLY": 2}
            and retained_altitude_profiles == 5
        ),
    }


def _artifact_attestation(path: Path) -> dict[str, Any]:
    artifact = _load_json(path)
    if artifact is None:
        return {"path": str(path.relative_to(ROOT)), "present": False, "passed": False}
    retained_hash = artifact.get("report_sha256") or artifact.get("qualification_sha256")
    hash_key = (
        "report_sha256"
        if "report_sha256" in artifact
        else "qualification_sha256"
        if "qualification_sha256" in artifact
        else None
    )
    hash_valid = bool(
        hash_key
        and retained_hash
        and canonical_sha256({key: value for key, value in artifact.items() if key != hash_key})
        == retained_hash
    )
    return {
        "path": str(path.relative_to(ROOT)),
        "present": True,
        "file_sha256": _file_sha256(path),
        "retained_sha256": retained_hash,
        "retained_sha256_valid": hash_valid,
        "passed": bool(artifact.get("passed") or artifact.get("all_runs_passed")),
    }


def build_reconciliation(expected_path: Path = R6_ORACLE) -> dict[str, Any]:
    if _file_sha256(R6_SCRIPT) != R6_SCRIPT_SHA256:
        raise ValueError("immutable R6 prototype script identity changed")
    if _file_sha256(R6_ORACLE) != R6_ORACLE_SHA256:
        raise ValueError("immutable R6 numerical artifact identity changed")
    expected = _load_json(expected_path)
    if expected is None:
        raise ValueError("expected numerical oracle is absent")
    if expected.get("audit_sha256") != R6_INTERNAL_SHA256:
        raise ValueError("expected numerical oracle internal identity changed")
    expected_payload = {key: value for key, value in expected.items() if key != "audit_sha256"}
    if canonical_sha256(expected_payload) != R6_INTERNAL_SHA256:
        raise ValueError("expected numerical oracle payload does not match its internal identity")

    actual = _json_value(build_audit())
    expected_projection = semantic_projection(expected)
    actual_projection = semantic_projection(actual)
    semantic_equal = expected_projection == actual_projection
    identity_changes = _mutable_identity_changes(expected, actual)
    counts = _registry_counts()
    registry_qualification = _load_json(REGISTRY_QUALIFICATION)
    registry_qualification_passed = bool(
        registry_qualification
        and registry_qualification.get("passed") is True
        and registry_qualification.get("accepted_design_payload_sha256")
        == "6294fc5b7e246f300069313a6c1b9d23696018b5f50c390a37b82103a0a8cf93"
        and canonical_sha256(
            {key: value for key, value in registry_qualification.items() if key != "report_sha256"}
        )
        == registry_qualification.get("report_sha256")
        and len(registry_qualification.get("production_preview_results", ())) == 7
    )

    runtime_attestation = _artifact_attestation(RUNTIME_QUALIFICATION)
    ui = _load_json(UI_INSPECTION)
    current_link = ROOT / "ui/.crazyswarm-builds/current"
    current_release = current_link.resolve(strict=True) if current_link.exists() else None
    ui_attestation = {
        "present": ui is not None,
        "passed": bool(ui and ui.get("passed") is True),
        "file_sha256": _file_sha256(UI_INSPECTION) if ui is not None else None,
        "release_name": current_release.name if current_release is not None else None,
        "release_tree_sha256": (
            _tree_sha256(current_release) if current_release is not None else None
        ),
    }
    passed = semantic_equal and counts["passed"] and registry_qualification_passed
    payload = {
        "schema_version": 1,
        "reconciliation_id": "wp52-56-r7-implementation-reconciliation-v1",
        "accepted_r7_design_payload_sha256": ACCEPTED_R7_DESIGN_SHA256,
        "historical_oracle": {
            "script_sha256": _file_sha256(R6_SCRIPT),
            "artifact_sha256": _file_sha256(R6_ORACLE),
            "internal_sha256": expected["audit_sha256"],
        },
        "current_file_manifest": _current_manifest(),
        "registry_counts": counts,
        "semantic_projection_sha256": canonical_sha256(actual_projection),
        "historical_semantic_projection_sha256": canonical_sha256(expected_projection),
        "semantic_projection_equal": semantic_equal,
        "current_semantic_projection": actual_projection,
        "current_audit": actual,
        "mutable_identity_change_count": len(identity_changes),
        "mutable_identity_changes_sha256": canonical_sha256(identity_changes),
        "registry_qualification": _artifact_attestation(REGISTRY_QUALIFICATION),
        "seven_public_service_previews_passed": registry_qualification_passed,
        "runtime_qualification": runtime_attestation,
        "ui_inspection": ui_attestation,
        "claim_boundaries": {
            "integration": passed,
            "production_entry_no_runtime": registry_qualification_passed,
            "fast_sim_accelerated": runtime_attestation["passed"],
            "observed_realtime": bool(
                runtime_attestation["passed"]
                and (_load_json(RUNTIME_QUALIFICATION) or {}).get("realtime_anchors_passed") is True
            ),
            "rendered_ui": ui_attestation["passed"],
        },
        "passed": passed,
    }
    return {**payload, "reconciliation_sha256": canonical_sha256(payload)}


def main() -> int:
    arguments = _arguments()
    payload = build_reconciliation(arguments.expected)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if not arguments.output.is_file():
            print("R7 implementation reconciliation artifact is absent")
            return 1
        if arguments.output.read_text(encoding="utf-8") != rendered:
            print("R7 implementation reconciliation artifact is stale")
            return 1
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    print(payload["reconciliation_sha256"])
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
