#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from contextlib import suppress
from itertools import pairwise
from pathlib import Path

from crazyswarm_app.vehicles._cflib_link import CflibCrazyflieLink
from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle

CONFIRMATION = "PROPS REMOVED OPERATOR PRESENT AIRFRAME RESTRAINED"


async def _observe(arguments: argparse.Namespace) -> dict[str, object]:
    adapter = CrazyflieVehicle(
        vehicle_id=arguments.vehicle_id,
        selected_uri=arguments.uri,
        link=CflibCrazyflieLink(),
        expected_firmware_version=arguments.expected_firmware,
    )
    cycle_records: list[dict[str, object]] = []
    for cycle in range(arguments.cycles):
        started = time.monotonic()
        samples = []
        failure: str | None = None
        try:
            await adapter.connect()
            deadline = time.monotonic() + arguments.sample_duration_s
            while time.monotonic() < deadline:
                samples.append(await adapter.snapshot())
                await asyncio.sleep(0.02)
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
        finally:
            with suppress(Exception):
                await adapter.disconnect()
        receive_times = [sample.received_timestamp_s for sample in samples]
        intervals = [later - earlier for earlier, later in pairwise(receive_times)]
        cycle_records.append(
            {
                "cycle": cycle + 1,
                "status": "PASSED" if failure is None else "FAILED",
                "failure": failure,
                "elapsed_s": time.monotonic() - started,
                "samples": len(samples),
                "mean_receive_interval_s": statistics.fmean(intervals) if intervals else None,
                "maximum_receive_gap_s": max(intervals) if intervals else None,
                "last_capabilities": (
                    samples[-1].telemetry.capabilities.model_dump(mode="json")
                    if samples and samples[-1].telemetry.capabilities is not None
                    else None
                ),
                "last_faults": list(samples[-1].telemetry.faults) if samples else [],
            }
        )
        if failure is not None:
            break
    cycles_completed = sum(record["status"] == "PASSED" for record in cycle_records)
    return {
        "schema_version": 1,
        "operation": "PROPS_OFF_OBSERVATION_ONLY_NO_ARM_NO_MOTOR_COMMAND",
        "vehicle_id": arguments.vehicle_id,
        "selected_uri": arguments.uri,
        "cycles_requested": arguments.cycles,
        "cycles_completed": cycles_completed,
        "cycles": cycle_records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Props-off Crazyflie connect/telemetry/disconnect bench observer"
    )
    parser.add_argument("--vehicle-id", required=True)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--expected-firmware")
    parser.add_argument("--cycles", type=int, default=1, choices=range(1, 101))
    parser.add_argument("--sample-duration-s", type=float, default=1.0)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.confirm != CONFIRMATION:
        parser.error("exact props-off onsite confirmation missing; no radio action taken")
    if arguments.sample_duration_s <= 0.0:
        parser.error("sample duration must be positive")
    output = asyncio.run(_observe(arguments))
    arguments.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "RECORDED", "output": str(arguments.output)}, indent=2))
    return 0 if output["cycles_completed"] == arguments.cycles else 1


if __name__ == "__main__":
    raise SystemExit(main())
