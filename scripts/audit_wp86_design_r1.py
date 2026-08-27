from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import audit_wp86_design as initial


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/work-packages/ACTIVE.md"
INITIAL_ARTIFACT = (
    ROOT / "missions/campaigns/sim/qualification/wp86-design-audit-v1.json"
)
HARDWARE_ARTIFACT = (
    ROOT / "missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json"
)
DEFAULT_ARTIFACT = (
    ROOT / "missions/campaigns/sim/qualification/wp86-r1-design-audit-v2.json"
)
BEGIN = "<!-- WP86-R1-DESIGN-PAYLOAD-BEGIN -->"
END = "<!-- WP86-R1-DESIGN-PAYLOAD-END -->"

CLAIM_KEYS = (
    "background_observer_isolation",
    "single_subject_projection",
    "authoritative_transition_reconciliation",
    "literal_props_off_diagnostics",
    "paired_session_clock",
    "retained_hardware_observation",
)
BOUNDARIES = {"MODEL_ONLY", "COMPONENT", "INTEGRATION", "PRODUCTION_ENTRY"}
ENVIRONMENTS = {"NO_RUNTIME", "FAST_SIM", "LIVE_ISAAC", "HARDWARE"}
CLOCKS = {"NOT_APPLICABLE", "ACCELERATED", "OBSERVED_REALTIME"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def delimited_payload(text: str, begin: str, end: str) -> bytes:
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    return (text[start:finish] + "\n").encode()


def corrected_manifest() -> dict[str, list[str]]:
    manifest = initial.inferred_manifest()
    additions = {
        "tests/twin/test_replay.py": "IMPLEMENTATION_OWNED",
        "scripts/extract_wp86_hardware_observation.py": "RELIED_UPON_UNCHANGED",
        "missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json": (
            "RELIED_UPON_UNCHANGED"
        ),
        "scripts/audit_wp86_design_r1.py": "RELIED_UPON_UNCHANGED",
    }
    additions["src/crazyswarm_app/twin/replay.py"] = "IMPLEMENTATION_OWNED"
    for path, classification in additions.items():
        manifest[path] = [classification, sha256(ROOT / path)]
    return dict(sorted(manifest.items()))


def pair_residual(
    observed: dict[str, Any], predicted: list[dict[str, Any]]
) -> dict[str, Any]:
    if observed["availability"] != "AVAILABLE":
        return {"availability": observed["availability"], "quality": "UNQUALIFIED", "pair_id": None}
    candidate = next(
        (
            item
            for item in predicted
            if item["session_id"] == observed["session_id"]
            and item["channel_id"] == observed["channel_id"]
            and item["unit"] == observed["unit"]
            and item["frame"] == observed["frame"]
            and item.get("pair_id") == observed.get("pair_id")
            and item.get("pair_sequence") == observed.get("pair_sequence")
            and item.get("alignment_epoch") == observed.get("alignment_epoch")
        ),
        None,
    )
    if candidate is None or observed.get("pair_id") is None:
        return {"availability": "MISSING", "quality": "UNQUALIFIED", "pair_id": None}
    if candidate["availability"] != "AVAILABLE":
        return {"availability": candidate["availability"], "quality": "UNQUALIFIED", "pair_id": candidate["pair_id"]}
    return {
        "availability": "AVAILABLE",
        "quality": "GOOD",
        "pair_id": candidate["pair_id"],
        "alignment_epoch": candidate["alignment_epoch"],
        "observed_source_epoch": observed["source_epoch"],
        "predicted_source_epoch": candidate["source_epoch"],
        "value": float(observed["value"]) - float(candidate["value"]),
    }


def sample(
    *,
    side: str,
    channel: str,
    pair_sequence: int | None,
    alignment_epoch: int | None,
    source_epoch: int,
    value: float | None,
) -> dict[str, Any]:
    return {
        "session_id": "session",
        "side": side,
        "channel_id": channel,
        "unit": "V" if channel == "battery.voltage" else "m/s^2",
        "frame": "vehicle" if channel == "battery.voltage" else "body",
        "pair_id": (
            f"pair-{pair_sequence}" if pair_sequence is not None else None
        ),
        "pair_sequence": pair_sequence,
        "alignment_epoch": alignment_epoch,
        "source_epoch": source_epoch,
        "availability": "AVAILABLE" if value is not None else "MISSING",
        "value": value,
    }


def execute_pair_witnesses() -> dict[str, Any]:
    old_prediction = sample(
        side="PREDICTED",
        channel="battery.voltage",
        pair_sequence=1,
        alignment_epoch=1,
        source_epoch=1,
        value=4.10,
    )
    rolled_observation = sample(
        side="OBSERVED",
        channel="battery.voltage",
        pair_sequence=2,
        alignment_epoch=2,
        source_epoch=2,
        value=3.90,
    )
    current_prediction = sample(
        side="PREDICTED",
        channel="battery.voltage",
        pair_sequence=2,
        alignment_epoch=2,
        source_epoch=1,
        value=4.00,
    )
    missing_battery = sample(
        side="OBSERVED",
        channel="battery.voltage",
        pair_sequence=3,
        alignment_epoch=2,
        source_epoch=2,
        value=None,
    )
    imu_observed = sample(
        side="OBSERVED",
        channel="imu.acceleration",
        pair_sequence=3,
        alignment_epoch=2,
        source_epoch=2,
        value=9.81,
    )
    imu_predicted = sample(
        side="PREDICTED",
        channel="imu.acceleration",
        pair_sequence=3,
        alignment_epoch=2,
        source_epoch=1,
        value=9.80,
    )
    legacy_observed = sample(
        side="OBSERVED",
        channel="battery.voltage",
        pair_sequence=None,
        alignment_epoch=None,
        source_epoch=1,
        value=3.9,
    )
    return {
        "rollback_exact_pair": pair_residual(
            rolled_observation, [old_prediction, current_prediction]
        ),
        "rollback_current_prediction_removed": pair_residual(
            rolled_observation, [old_prediction]
        ),
        "partial_sensor_battery": pair_residual(missing_battery, [current_prediction]),
        "partial_sensor_imu": pair_residual(imu_observed, [imu_predicted]),
        "legacy_no_pair": pair_residual(legacy_observed, [old_prediction]),
        "all_measured_missing": {
            "emit_pair": False,
            "consume_pair_sequence": False,
            "establish_clock_origin": False,
        },
    }


def artifact_template() -> dict[str, Any]:
    ledger_text = LEDGER.read_text(encoding="utf-8")
    initial_data = json.loads(INITIAL_ARTIFACT.read_text(encoding="utf-8"))
    initial_payload = delimited_payload(
        ledger_text, initial.BEGIN, initial.END
    )
    r1_payload = delimited_payload(ledger_text, BEGIN, END)
    hardware = json.loads(HARDWARE_ARTIFACT.read_text(encoding="utf-8"))
    return {
        "schema_version": 2,
        "review_unit": "WP-86",
        "correction": "R1",
        "base_commit": initial_data["base_commit"],
        "initial_payload": {
            "bytes": len(initial_payload),
            "sha256": sha256_bytes(initial_payload),
            "verified_artifact_sha256": sha256(INITIAL_ARTIFACT),
        },
        "r1_payload": {
            "bytes": len(r1_payload),
            "sha256": sha256_bytes(r1_payload),
            "ledger_preimage_sha256": sha256_bytes(
                ledger_text.split(BEGIN, 1)[0].encode()
            ),
        },
        "manifest": corrected_manifest(),
        "claims": {
            "background_observer_isolation": {
                "owners": [
                    "src/crazyswarm_app/hardware/observation_twin.py",
                    "ui/app/components/ControlCenter.tsx",
                ],
                "entries": ["src/crazyswarm_app/api/app.py", "ui/worker/index.ts"],
            },
            "single_subject_projection": {
                "owners": [
                    "ui/app/components/ControlCenter.tsx",
                    "ui/app/components/RoomScene.tsx",
                    "ui/app/components/TwinObservationReadout.tsx",
                ],
                "entries": ["ui/app/page.tsx", "ui/app/components/TelemetryDock.tsx"],
            },
            "authoritative_transition_reconciliation": initial_data["claims"][
                "authoritative_transition_reconciliation"
            ],
            "literal_props_off_diagnostics": initial_data["claims"][
                "literal_props_off_diagnostics"
            ],
            "paired_session_clock": {
                "owners": [
                    "src/crazyswarm_app/hardware/observation_twin.py",
                    "src/crazyswarm_app/twin/ingestion.py",
                    "src/crazyswarm_app/twin/models.py",
                    "src/crazyswarm_app/twin/replay.py",
                ],
                "entries": [
                    "tests/hardware/test_observation_twin_service.py",
                    "tests/twin/test_replay.py",
                ],
            },
            "retained_hardware_observation": {
                "owners": ["scripts/extract_wp86_hardware_observation.py"],
                "entries": [
                    "missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json"
                ],
            },
        },
        "canonical_boundaries": {
            "background_observer_isolation": "PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME",
            "single_subject_projection": "PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME",
            "authoritative_transition_reconciliation": "PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME",
            "literal_props_off_diagnostics": "PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME",
            "paired_session_clock": "INTEGRATION / FAST_SIM / OBSERVED_REALTIME",
            "retained_hardware_observation": "PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME",
        },
        "clock_witnesses": initial_data["clock_witnesses"],
        "pair_witnesses": execute_pair_witnesses(),
        "hardware_observation": {
            "artifact": str(HARDWARE_ARTIFACT.relative_to(ROOT)),
            "artifact_sha256": sha256(HARDWARE_ARTIFACT),
            "session_id": hardware["session_id"],
            "status": hardware["status"],
            "session_envelope_count": hardware["session_envelope_count"],
            "normalized_sample_count": hardware["normalized_sample_count"],
            "normalized_samples_sha256": hardware["normalized_samples_sha256"],
            "paired_cycles": hardware["paired_cycles"],
        },
        "implementation_hardware_claim": "NOT_RUN",
    }


def audit(data: dict[str, Any], artifact: Path) -> list[str]:
    errors: list[str] = []
    expected = artifact_template()
    if data != expected:
        errors.append("R1 artifact differs from executable template")

    ledger_text = LEDGER.read_text(encoding="utf-8")
    payload = delimited_payload(ledger_text, BEGIN, END).decode()
    matrix = payload.split("### Canonical claim/evidence boundaries", 1)[1].split(
        "### Reconstructable clean hardware observation", 1
    )[0]
    payload_claims = tuple(
        re.findall(r"^\| `([a-z0-9_]+)` \|", matrix, re.MULTILINE)
    )
    if payload_claims != CLAIM_KEYS or set(data["claims"]) != set(CLAIM_KEYS):
        errors.append(f"R1 claim mismatch: {payload_claims}")
    allowed_paths = set(data["manifest"]) | initial.INTENDED_NEW_PATHS
    for key, row in data["claims"].items():
        missing = set(row["owners"] + row["entries"]) - allowed_paths
        if missing:
            errors.append(f"{key}: owner/entry absent from manifest: {sorted(missing)}")
    for key, value in data["canonical_boundaries"].items():
        parts = value.split(" / ")
        if (
            len(parts) != 3
            or parts[0] not in BOUNDARIES
            or parts[1] not in ENVIRONMENTS
            or parts[2] not in CLOCKS
        ):
            errors.append(f"{key}: noncanonical boundary {value}")
    forbidden = ("SERVED_UI", "HARDWARE-LIKE", "FAST_SIM+HARDWARE")
    if any(token in payload for token in forbidden):
        errors.append("R1 payload retains a forbidden boundary label")

    witnesses = data["clock_witnesses"]
    for name in ("nominal", "raw_clock_perturbation", "admission_time_perturbation"):
        if initial.clock_oracle(witnesses[name]) != witnesses[name]["expected"]:
            errors.append(f"clock witness mismatch: {name}")
    executed = execute_pair_witnesses()
    if executed != data["pair_witnesses"]:
        errors.append("pair witness execution mismatch")
    if executed["rollback_exact_pair"] != {
        "availability": "AVAILABLE",
        "quality": "GOOD",
        "pair_id": "pair-2",
        "alignment_epoch": 2,
        "observed_source_epoch": 2,
        "predicted_source_epoch": 1,
        "value": -0.10000000000000009,
    }:
        errors.append("rollback exact-pair witness did not preserve independent epochs")
    for name in (
        "rollback_current_prediction_removed",
        "partial_sensor_battery",
        "legacy_no_pair",
    ):
        if executed[name]["availability"] != "MISSING" or executed[name]["quality"] != "UNQUALIFIED":
            errors.append(f"{name}: did not fail closed")
    if executed["partial_sensor_imu"]["availability"] != "AVAILABLE":
        errors.append("partial sensor pair incorrectly rejected available IMU")

    hardware_check = subprocess.run(
        [
            "python",
            "scripts/extract_wp86_hardware_observation.py",
            "--check",
            "missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if hardware_check.returncode:
        errors.append(f"hardware reconstruction failed: {hardware_check.stdout}{hardware_check.stderr}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", nargs="?", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--print-manifest", action="store_true")
    args = parser.parse_args()
    artifact = args.artifact if args.artifact.is_absolute() else ROOT / args.artifact
    if args.print_manifest:
        print(json.dumps(corrected_manifest(), indent=2, sort_keys=True))
        return 0
    if args.freeze:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(artifact_template(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    data = json.loads(artifact.read_text(encoding="utf-8"))
    errors = audit(data, artifact)
    result = {
        "artifact": str(artifact.relative_to(ROOT)),
        "artifact_sha256": sha256(artifact),
        "initial_payload_sha256": data["initial_payload"]["sha256"],
        "r1_payload_sha256": data["r1_payload"]["sha256"],
        "boundary_count": len(data["manifest"]),
        "pair_witness_count": len(data["pair_witnesses"]),
        "hardware_normalized_sample_count": data["hardware_observation"][
            "normalized_sample_count"
        ],
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
