#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from crazyswarm_app.domain.models import OperatingMode
from crazyswarm_app.hardware.models import (
    BenchQualificationRecord,
    CommandPermit,
    PermitScope,
    PhysicalFlightEntryRecord,
)
from crazyswarm_app.missions.registry import MissionRegistry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.missions.script import ScriptMission, parse_python_mission
from crazyswarm_app.qualification.physical import (
    assess_flight_entry,
    canonical_record_sha256,
    load_physical_plan,
    verify_plan_source_hashes,
)
from crazyswarm_app.safety.models import LiveModeAuthorization
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.vehicles._cflib_link import CflibCrazyflieLink
from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle

CONFIRMATION = "OPERATOR AND OBSERVER PRESENT IN APPROVED CONTAINMENT"


def _load_bench_record(path: Path) -> BenchQualificationRecord:
    return BenchQualificationRecord.model_validate_json(path.read_text(encoding="utf-8"))


def _load_flight_entry_record(path: Path) -> PhysicalFlightEntryRecord:
    return PhysicalFlightEntryRecord.model_validate_json(path.read_text(encoding="utf-8"))


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    root = arguments.root.resolve()
    plan = load_physical_plan(arguments.plan)
    source_findings = verify_plan_source_hashes(plan, root)
    if not all(item.passed for item in source_findings):
        raise RuntimeError("qualification source hashes changed; no radio action taken")
    bench = _load_bench_record(arguments.bench_record)
    entry = _load_flight_entry_record(arguments.flight_entry_record)
    gate = assess_flight_entry(bench, entry, plan)
    if not gate.accepted:
        raise RuntimeError(
            "physical flight entry gate is open: "
            + ", ".join(item.code for item in gate.findings if not item.passed)
        )
    if arguments.confirm != CONFIRMATION:
        raise RuntimeError("exact onsite confirmation phrase missing; no radio action taken")
    requirement = next(
        (item for item in plan.missions if item.qf_id == arguments.qf_id),
        None,
    )
    if requirement is None or not requirement.physical_execution_required:
        raise RuntimeError("selected QF is not authorized by the contained-flight plan")
    source_path = root / requirement.source_path
    record = parse_python_mission(
        filename=source_path.name,
        name=requirement.qf_id,
        source=source_path.read_text(encoding="utf-8"),
    )
    if record.source_sha256 != requirement.source_sha256:
        raise RuntimeError("parsed mission hash differs from the frozen physical plan")
    firmware = next(
        (
            item.observed_version
            for item in bench.versions
            if item.component == "crazyflie-stm32-firmware"
        ),
        None,
    )
    controller = next(
        (
            item.observed_version
            for item in bench.versions
            if item.component == "stabilizer-controller"
        ),
        None,
    )
    estimator = next(
        (
            item.observed_version
            for item in bench.versions
            if item.component == "stabilizer-estimator"
        ),
        None,
    )
    adapter = CrazyflieVehicle(
        vehicle_id=entry.vehicle_id,
        selected_uri=bench.selected_uri,
        link=CflibCrazyflieLink(),
        expected_firmware_version=firmware,
        expected_controller=controller,
        expected_estimator=estimator,
        minimum_protocol_version=plan.minimum_protocol_version,
    )
    adapter.install_command_permit(
        CommandPermit(
            permit_id=f"permit-{entry.record_id}-{arguments.qf_id.lower()}",
            vehicle_id=entry.vehicle_id,
            selected_uri=bench.selected_uri,
            operator_id=entry.operator_id,
            scope=PermitScope.CONTAINED_FLIGHT,
            issued_at_utc=datetime.now(UTC),
            expires_at_utc=entry.expires_at_utc,
            operator_present=True,
            props_removed=False,
            physically_restrained=False,
            flight_entry_record_id=entry.record_id,
            flight_entry_evidence_sha256=canonical_record_sha256(entry),
        )
    )
    registry = MissionRegistry()
    mission = ScriptMission(record)
    registry.register(mission)
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(adapter)
    supervisor.set_mode(
        OperatingMode.LIVE,
        authorization=LiveModeAuthorization(
            vehicle_id=entry.vehicle_id,
            operator_id=entry.operator_id,
            mode=OperatingMode.LIVE,
            confirmed=True,
            authorized_at_monotonic_s=asyncio.get_running_loop().time(),
        ),
    )
    result = await MissionRunner(supervisor, registry).run(
        mission.mission_id,
        entry.vehicle_id,
        mission_run_id=arguments.run_id,
    )
    return {
        "schema_version": 1,
        "operation": "CONTAINED_PHYSICAL_QUALIFICATION",
        "qf_id": arguments.qf_id,
        "plan_id": plan.plan_id,
        "bench_record_id": bench.record_id,
        "flight_entry_record_id": entry.record_id,
        "result": result.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one frozen QF source on a real Crazyflie after all physical gates"
    )
    parser.add_argument("qf_id")
    parser.add_argument("--bench-record", type=Path, required=True)
    parser.add_argument("--flight-entry-record", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--confirm", required=True, help="must match the documented onsite phrase")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path("config/qualification/reality-physical-plan-v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    output = asyncio.run(_run(arguments))
    arguments.output.write_text(
        json.dumps(output, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "RECORDED", "output": str(arguments.output)}, indent=2))
    result = output["result"]
    return 0 if isinstance(result, dict) and result.get("status") == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
