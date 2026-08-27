from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKETS = ("WP-71", "WP-72", "WP-73", "WP-74", "WP-75")
EXPECTED_CLAIMS = {
    "exact_observation_entry",
    "non_bypassable_physical_authority",
    "props_off_truth",
    "paired_simple_mission_pipeline",
    "contained_first_hover",
    "served_physical_ui",
}
EXPECTED_GENERATED = {"ui/openapi.json", "ui/app/lib/api.generated.ts"}
ALLOWED_CLASSIFICATIONS = {"IMPLEMENTATION_OWNED", "RELIED_UPON_UNCHANGED", "GENERATED"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "artifact",
        nargs="?",
        type=Path,
        default=ROOT / "missions/campaigns/sim/qualification/wp71-75-design-audit-v1.json",
    )
    args = parser.parse_args()
    artifact = args.artifact if args.artifact.is_absolute() else ROOT / args.artifact
    data = json.loads(artifact.read_text(encoding="utf-8"))

    errors: list[str] = []
    packets = data.get("packets", [])
    packet_ids = tuple(item.get("packet_id") for item in packets)
    if packet_ids != EXPECTED_PACKETS:
        errors.append(f"packet order/set mismatch: {packet_ids!r}")
    if len(packet_ids) != len(set(packet_ids)):
        errors.append("duplicate packet IDs")
    packet_set = set(packet_ids)
    for item in packets:
        missing = set(item.get("dependencies", [])) - packet_set
        if missing:
            errors.append(f"{item.get('packet_id')} has unknown dependencies: {sorted(missing)}")
        if not item.get("minimum_value"):
            errors.append(f"{item.get('packet_id')} lacks minimum value")

    claims = data.get("claims", [])
    claim_ids = [item.get("claim_id") for item in claims]
    if set(claim_ids) != EXPECTED_CLAIMS or len(claim_ids) != len(set(claim_ids)):
        errors.append(f"claim set mismatch: {sorted(str(item) for item in claim_ids)}")
    covered_packets = {item.get("packet_id") for item in claims}
    if covered_packets != packet_set:
        errors.append(f"claim packet coverage mismatch: {sorted(str(item) for item in covered_packets)}")
    for item in claims:
        if item.get("boundary") != "PRODUCTION_ENTRY":
            errors.append(f"{item.get('claim_id')} is not a production-entry claim")
        if item.get("environment") != "HARDWARE" or item.get("clock") != "OBSERVED_REALTIME":
            errors.append(f"{item.get('claim_id')} has the wrong physical evidence boundary")

    generated = set(data.get("generated_outputs", []))
    if generated != EXPECTED_GENERATED:
        errors.append(f"generated output mismatch: {sorted(generated)}")

    boundaries = data.get("boundaries", [])
    paths = [item.get("path") for item in boundaries]
    if len(paths) != len(set(paths)):
        errors.append("duplicate boundary paths")
    for item in boundaries:
        relative = item.get("path")
        classification = item.get("classification")
        if classification not in ALLOWED_CLASSIFICATIONS:
            errors.append(f"{relative}: invalid classification {classification!r}")
            continue
        path = ROOT / str(relative)
        if not path.is_file():
            errors.append(f"{relative}: missing boundary")
            continue
        observed = sha256(path)
        if observed != item.get("preimage_sha256"):
            errors.append(f"{relative}: preimage mismatch {observed}")
        if classification == "GENERATED" and relative not in EXPECTED_GENERATED:
            errors.append(f"{relative}: unexpected generated classification")
    for relative in data.get("intended_new_paths", []):
        if (ROOT / relative).exists():
            errors.append(f"{relative}: intended new path already exists")

    required = set(data.get("requirements", []))
    for requirement in ("REQ-XFR-008", "REQ-WFL-034", "REQ-WFL-038", "REQ-WFL-047"):
        if requirement not in required:
            errors.append(f"missing required design coverage: {requirement}")

    result = {
        "artifact": str(artifact.relative_to(ROOT)),
        "artifact_sha256": sha256(artifact),
        "packet_count": len(packets),
        "claim_count": len(claims),
        "boundary_count": len(boundaries),
        "new_path_count": len(data.get("intended_new_paths", [])),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
