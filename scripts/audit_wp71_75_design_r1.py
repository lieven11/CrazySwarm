from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/work-packages/ACTIVE.md"
INITIAL_BEGIN = "<!-- WP71-75-DESIGN-PAYLOAD-BEGIN -->"
INITIAL_END = "<!-- WP71-75-DESIGN-PAYLOAD-END -->"
R1_BEGIN = "<!-- WP71-75-R1-DESIGN-PAYLOAD-BEGIN -->"
R1_END = "<!-- WP71-75-R1-DESIGN-PAYLOAD-END -->"
CLASSIFICATIONS = {
    "IMPLEMENTATION_OWNED",
    "RELIED_UPON_UNCHANGED",
    "GENERATOR",
    "GENERATED",
}

# These paths come from the production traces and the repository routing/system maps,
# not from the artifact. Symbol discovery below independently adds concrete owners.
FIXED_TRANSIT_BOUNDARIES = {
    "config/qualification/reality-physical-plan-v1.json",
    "docs/guides/REALITY_WP04_06_PHYSICAL_PROCEDURE.md",
    "docs/system/README.md",
    "design.md",
    "docs/project/DESIGN.md",
    "src/crazyswarm_app/api/runtime.py",
    "src/crazyswarm_app/api/models.py",
    "src/crazyswarm_app/config.py",
    "src/crazyswarm_app/domain/commands.py",
    "src/crazyswarm_app/domain/telemetry.py",
    "src/crazyswarm_app/fleet/preparation.py",
    "src/crazyswarm_app/fleet/execution.py",
    "src/crazyswarm_app/fleet/coordinator.py",
    "src/crazyswarm_app/missions/models.py",
    "src/crazyswarm_app/missions/catalog.py",
    "src/crazyswarm_app/observability/recorder.py",
    "src/crazyswarm_app/observability/storage.py",
    "src/crazyswarm_app/observability/csv_export.py",
    "src/crazyswarm_app/dashboard.py",
    "src/crazyswarm_app/dashboard_service.py",
    "src/crazyswarm_app/vehicles/providers.py",
    "src/crazyswarm_app/vehicles/crazyflie_link.py",
    "src/crazyswarm_app/twin/models.py",
    "src/crazyswarm_app/twin/storage.py",
    "src/crazyswarm_app/twin/physical_handoff.py",
    "src/crazyswarm_app/twin/curriculum.py",
    "src/crazyswarm_app/twin/pipeline.py",
    "ui/app/page.tsx",
    "ui/app/components/ControlCenter.tsx",
    "ui/app/components/CampaignLab.tsx",
    "ui/app/components/TelemetryDock.tsx",
    "ui/app/lib/api.ts",
    "ui/app/lib/models.ts",
    "ui/package.json",
    "scripts/export_openapi.py",
}

SYMBOL_TRACES = {
    "def create_app(": "src/crazyswarm_app/api",
    "class Mission(ABC": "src/crazyswarm_app/missions",
    "class MissionFleetAuthority": "src/crazyswarm_app/missions",
    "class MissionRunner": "src/crazyswarm_app/missions",
    "class SafetySupervisor": "src/crazyswarm_app/safety",
    "class CrazyflieVehicle": "src/crazyswarm_app/vehicles",
    "class CflibCrazyflieLink": "src/crazyswarm_app/vehicles",
    "class PhysicalFlightEntryRecord": "src/crazyswarm_app/hardware",
    "class PhysicalQualificationPlan": "src/crazyswarm_app/qualification",
    "class TwinCoordinator": "src/crazyswarm_app/twin",
    "class TwinIngestionBoundary": "src/crazyswarm_app/twin",
    "class DurableTwinStore": "src/crazyswarm_app/twin",
    "export function ControlCenter": "ui/app",
    "export function CampaignLab": "ui/app",
}

REQUIREMENT_FILES = {
    "MOT": "docs/project/requirements/MOTION_AND_CONTROL.md",
    "MIS": "docs/project/requirements/MISSION_AND_CURRICULUM.md",
    "REU": "docs/project/requirements/MISSION_AND_CURRICULUM.md",
    "EVI": "docs/project/requirements/EVIDENCE_AND_REVIEW.md",
    "XFR": "docs/project/requirements/FIDELITY_AND_TRANSFER.md",
    "UI": "docs/project/requirements/UI_AND_CATALOG.md",
    "WFL": (
        "docs/project/requirements/workflow/WORK_PACKET_GATES.md",
        "docs/project/requirements/workflow/COST_SCOPE_AND_HANDOFF.md",
        "docs/project/requirements/workflow/PREFREEZE_AND_ORACLES.md",
    ),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def delimited(text: str, begin: str, end: str) -> bytes:
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    return (text[start:finish] + "\n").encode()


def discover_symbol_owners(errors: list[str]) -> set[str]:
    owners: set[str] = set()
    for symbol, root_name in SYMBOL_TRACES.items():
        matches: list[str] = []
        for path in (ROOT / root_name).rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"} or not path.is_file():
                continue
            if symbol in path.read_text(encoding="utf-8"):
                matches.append(str(path.relative_to(ROOT)))
        if len(matches) != 1:
            errors.append(f"production symbol {symbol!r} resolved to {matches}")
        else:
            owners.add(matches[0])
    return owners


def parse_packets(r1: str, errors: list[str]) -> dict[str, list[str]]:
    section = r1.split("### R1-5", 1)[1].split("### R1-6", 1)[0]
    packets: dict[str, list[str]] = {}
    for line in section.splitlines():
        match = re.match(r"\| (WP-7[1-5]) \| (.*?) \|", line)
        if match:
            packets[match.group(1)] = re.findall(r"WP-7[1-5]", match.group(2))
    if tuple(packets) != ("WP-71", "WP-72", "WP-73", "WP-74", "WP-75"):
        errors.append(f"correction packet table mismatch: {packets}")
    return packets


def assert_acyclic(packets: dict[str, list[str]], errors: list[str]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(packet: str) -> None:
        if packet in visiting:
            errors.append(f"dependency cycle at {packet}")
            return
        if packet in visited:
            return
        visiting.add(packet)
        for dependency in packets.get(packet, []):
            if dependency not in packets:
                errors.append(f"{packet} has unknown dependency {dependency}")
            else:
                visit(dependency)
        visiting.remove(packet)
        visited.add(packet)

    for packet in packets:
        visit(packet)


def parse_claims(r1: str) -> list[str]:
    section = r1.split("### R1 corrected production-claim matrix", 1)[1].split(
        "### R1 corrected state", 1
    )[0]
    return re.findall(r"^\| `([a-z0-9_]+)` \|", section, flags=re.MULTILINE)


def parse_generated_outputs(errors: list[str]) -> set[str]:
    package = json.loads((ROOT / "ui/package.json").read_text(encoding="utf-8"))
    command = package.get("scripts", {}).get("generate:api", "")
    outputs: set[str] = set()
    if "--output ui/openapi.json" in command:
        outputs.add("ui/openapi.json")
    if "-o app/lib/api.generated.ts" in command:
        outputs.add("ui/app/lib/api.generated.ts")
    if len(outputs) != 2:
        errors.append(f"could not derive generated pair from generate:api: {command!r}")
    return outputs


def validate_requirements(r1: str, artifact_ids: set[str], errors: list[str]) -> None:
    payload_ids = set(re.findall(r"REQ-(?:MOT|MIS|REU|EVI|XFR|UI|WFL)-\d{3}", r1))
    if payload_ids != artifact_ids:
        errors.append(
            f"requirement set differs between payload/artifact: "
            f"missing={sorted(payload_ids - artifact_ids)}, extra={sorted(artifact_ids - payload_ids)}"
        )
    for requirement in artifact_ids:
        prefix = requirement.split("-")[1]
        sources = REQUIREMENT_FILES[prefix]
        if isinstance(sources, str):
            sources = (sources,)
        if not any(requirement in (ROOT / source).read_text(encoding="utf-8") for source in sources):
            errors.append(f"{requirement} absent from routed requirement sources")


def validate_witness(data: dict, errors: list[str]) -> dict[str, float]:
    safety = data["safety_witness"]
    flight = data["flight_witness"]
    margin = safety["firmware_timeout_s"] - safety["watchdog_nominal_gap_max_s"]
    takeoff_average = flight["takeoff_target_m"][2] / flight["takeoff_duration_s"]
    timeline = (
        flight["takeoff_duration_s"]
        + flight["hover_duration_s"]
        + flight["land_duration_s"]
        + flight["ground_observation_timeout_s"]
    )
    computed = {
        "nominal_firmware_margin_s": round(margin, 6),
        "nominal_takeoff_average_m_s": round(takeoff_average, 6),
        "nominal_stage4_max_timeline_s": round(timeline, 6),
    }
    if safety["computed"]["nominal_firmware_margin_s"] != computed["nominal_firmware_margin_s"]:
        errors.append("watchdog margin is not independently reproducible")
    if flight["computed"]["nominal_takeoff_average_m_s"] != computed[
        "nominal_takeoff_average_m_s"
    ]:
        errors.append("takeoff average is not independently reproducible")
    if flight["computed"]["nominal_stage4_max_timeline_s"] != computed[
        "nominal_stage4_max_timeline_s"
    ]:
        errors.append("stage-4 timeline is not independently reproducible")
    if safety["protocol_acknowledgement"] or safety["automatic_retry_count"] != 0:
        errors.append("protocol incorrectly claims acknowledgement or automatic retry")
    if not (
        safety["watchdog_nominal_gap_max_s"]
        < safety["watchdog_host_failure_gap_s"]
        < safety["firmware_timeout_s"]
        < safety["watchdog_latch_failure_gap_s"]
        < safety["lock_observation_deadline_s"]
    ):
        errors.append("watchdog pass/fail vector ordering is invalid")
    if safety["repeats"] != 100 or flight["required_shakedown_passes"] != 3:
        errors.append("repeat semantics changed")
    failures = flight["isolated_failures"]
    comparisons = (
        (failures["altitude_m"], flight["altitude_cap_m"]),
        (failures["radius_m"], flight["horizontal_radius_cap_m"]),
        (failures["speed_m_s"], flight["translation_speed_cap_m_s"]),
        (failures["acceleration_m_s2"], flight["acceleration_cap_m_s2"]),
        (failures["jerk_m_s3"], flight["jerk_cap_m_s3"]),
    )
    if any(failure <= guard for failure, guard in comparisons):
        errors.append("one or more isolated flight failures do not cross their guard")
    if failures["estimator_axis_range"] != flight["estimator_axis_range_exclusive_max"]:
        errors.append("exclusive estimator equality failure changed")
    if failures["wrong_axis_displacement_m"] == flight["move_displacement_m"]:
        errors.append("axis counterexample is not distinct")
    return computed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "artifact",
        nargs="?",
        type=Path,
        default=ROOT
        / "missions/campaigns/sim/qualification/wp71-75-design-r1-audit-v2.json",
    )
    args = parser.parse_args()
    artifact = args.artifact if args.artifact.is_absolute() else ROOT / args.artifact
    data = json.loads(artifact.read_text(encoding="utf-8"))
    errors: list[str] = []

    ledger_text = LEDGER.read_text(encoding="utf-8")
    initial = delimited(ledger_text, INITIAL_BEGIN, INITIAL_END)
    r1 = delimited(ledger_text, R1_BEGIN, R1_END)
    for label, payload, expected in (
        ("initial", initial, data["initial_payload"]),
        ("r1", r1, data["r1_payload"]),
    ):
        if len(payload) != expected["bytes"] or sha256_bytes(payload) != expected["sha256"]:
            errors.append(f"{label} payload identity mismatch")

    prefix = ledger_text.split(INITIAL_BEGIN, 1)[0]
    if not prefix.endswith("\n\n"):
        errors.append("ledger preimage delimiter shape changed")
    reconstructed = prefix[:-1].encode()
    if sha256_bytes(reconstructed) != data["ledger_preimage_sha256"]:
        errors.append("byte-exact ledger preimage reconstruction mismatch")

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != data["base_commit"]:
        errors.append(f"base commit mismatch: {head}")

    packets = parse_packets(r1.decode(), errors)
    if packets != data["packets"]:
        errors.append(f"payload/artifact packet dependency mismatch: {packets}")
    assert_acyclic(packets, errors)

    claims = parse_claims(r1.decode())
    if claims != data["claims"] or len(claims) != len(set(claims)):
        errors.append(f"payload/artifact claim mismatch: {claims}")

    validate_requirements(r1.decode(), set(data["requirements"]), errors)
    generated = parse_generated_outputs(errors)

    manifest = data["manifest"]
    manifest_paths = set(manifest)
    discovered = FIXED_TRANSIT_BOUNDARIES | discover_symbol_owners(errors) | generated
    missing = discovered - manifest_paths
    if missing:
        errors.append(f"production trace boundaries absent from manifest: {sorted(missing)}")
    if {path for path, row in manifest.items() if row[0] == "GENERATED"} != generated:
        errors.append("generated classifications differ from generate:api outputs")
    for relative, row in manifest.items():
        if len(row) != 2 or row[0] not in CLASSIFICATIONS:
            errors.append(f"{relative}: invalid manifest row {row!r}")
            continue
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"{relative}: missing manifest path")
        elif sha256(path) != row[1]:
            errors.append(f"{relative}: preimage mismatch {sha256(path)}")
    for relative in data["intended_new_paths"]:
        if (ROOT / relative).exists():
            errors.append(f"{relative}: intended new path already exists")

    computed = validate_witness(data, errors)
    artifact_hash = sha256(artifact)
    handoff_match = re.search(
        r"V2 artifact: SHA-256\s+`([a-f0-9]{64})`", ledger_text
    )
    if handoff_match is not None and handoff_match.group(1) != artifact_hash:
        errors.append("V2 artifact handoff hash mismatch")

    result = {
        "artifact": str(artifact.relative_to(ROOT)),
        "artifact_sha256": artifact_hash,
        "base_commit": head,
        "boundary_count": len(manifest),
        "discovered_production_boundary_count": len(discovered),
        "claim_count": len(claims),
        "packet_count": len(packets),
        "requirement_count": len(data["requirements"]),
        "generated_outputs": sorted(generated),
        "computed_witness": computed,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
