from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import statistics
import zlib
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOURNAL = ROOT / ".cache/crazyswarm/digital-twin/twin-journal-v1.jsonl"
DEFAULT_OUTPUT = (
    ROOT
    / "missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json"
)
SESSION_ID = "twin-f33a1e55c4f2431480f1f41cd6f45a19"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def vector(value: object) -> tuple[float, float, float]:
    if not isinstance(value, dict):
        raise ValueError("expected vector object")
    return float(value["x"]), float(value["y"]), float(value["z"])


def load_session(journal: Path) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    samples: list[dict[str, Any]] = []
    final_record: dict[str, Any] | None = None
    envelope_hashes: list[str] = []
    with journal.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.endswith(b"\n"):
                raise ValueError(f"truncated journal record at line {line_number}")
            envelope = json.loads(raw_line)
            if envelope.get("session_id") != SESSION_ID:
                continue
            expected_record_hash = envelope.pop("record_sha256", None)
            actual_record_hash = canonical_sha256(envelope)
            if expected_record_hash != actual_record_hash:
                raise ValueError(f"record hash mismatch at line {line_number}")
            envelope_hashes.append(actual_record_hash)
            kind = envelope["kind"]
            payload = envelope["payload"]
            if kind == "SESSION_CREATED":
                final_record = payload["record"]
            elif kind == "SESSION_UPDATED":
                final_record = payload
            elif kind == "SAMPLE_BATCH_ZLIB_V1":
                if payload.get("codec") != "zlib-json-v1":
                    raise ValueError("unsupported sample codec")
                values = json.loads(zlib.decompress(base64.b64decode(payload["data_base64"])))
                if len(values) != payload["sample_count"]:
                    raise ValueError("compressed sample count mismatch")
                if canonical_sha256(values) != payload["samples_sha256"]:
                    raise ValueError("compressed sample hash mismatch")
                samples.extend(values)
            elif kind == "SAMPLE_BATCH":
                samples.extend(payload)
    if final_record is None:
        raise ValueError(f"session {SESSION_ID} not found")
    return samples, final_record, envelope_hashes


def normalized_sample(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        key: sample.get(key)
        for key in (
            "session_id",
            "side",
            "channel_id",
            "sequence",
            "source_clock_id",
            "source_epoch",
            "raw_source_timestamp_s",
            "source_timestamp_s",
            "availability",
            "quality",
            "unit",
            "frame",
            "source_frame",
            "value",
        )
    }


def available_observed(samples: list[dict[str, Any]], channel: str) -> list[dict[str, Any]]:
    return [
        sample
        for sample in samples
        if sample["side"] == "OBSERVED"
        and sample["channel_id"] == channel
        and sample["availability"] == "AVAILABLE"
    ]


def build_artifact(journal: Path) -> dict[str, Any]:
    samples, record, envelope_hashes = load_session(journal)
    normalized = sorted(
        (normalized_sample(sample) for sample in samples),
        key=lambda sample: (
            sample["sequence"],
            sample["side"],
            sample["channel_id"],
        ),
    )
    by_side = Counter(sample["side"] for sample in samples)
    by_side_channel = Counter(
        (sample["side"], sample["channel_id"]) for sample in samples
    )
    per_side_counts = {
        side: dict(
            sorted(
                (channel, count)
                for (candidate_side, channel), count in by_side_channel.items()
                if candidate_side == side
            )
        )
        for side in ("OBSERVED", "PREDICTED")
    }
    sequences = sorted({int(sample["sequence"]) for sample in samples})

    batteries = available_observed(samples, "battery.voltage")
    battery_values = [float(sample["value"]) for sample in batteries]
    unique_battery = sorted(set(battery_values))
    battery_steps = [
        right - left for left, right in zip(unique_battery, unique_battery[1:])
    ]

    flow_values = [json.loads(sample["value"]) for sample in available_observed(samples, "flow.state")]
    flow_quality = [float(value["quality_percent"]) for value in flow_values]
    flow_speed = [
        math.hypot(
            float(value["velocity_body_m_s"]["x"]),
            float(value["velocity_body_m_s"]["y"]),
        )
        for value in flow_values
    ]
    ground_distance = [float(value["ground_distance_m"]) for value in flow_values]

    estimator_values = [
        json.loads(sample["value"])
        for sample in available_observed(samples, "estimator.health")
    ]
    converged = Counter(bool(value["converged"]) for value in estimator_values)

    acceleration = [
        vector(sample["value"])
        for sample in available_observed(samples, "imu.acceleration")
    ]
    angular_velocity = [
        vector(sample["value"])
        for sample in available_observed(samples, "imu.angular_velocity")
    ]
    attitude = [
        vector(sample["value"])
        for sample in available_observed(samples, "attitude.euler")
    ]
    acceleration_norm = [math.sqrt(sum(axis * axis for axis in value)) for value in acceleration]
    angular_velocity_norm = [
        math.sqrt(sum(axis * axis for axis in value)) for value in angular_velocity
    ]
    attitude_span = {
        axis: max(value[index] for value in attitude) - min(value[index] for value in attitude)
        for index, axis in enumerate(("x", "y", "z"))
    }

    observed_battery_all = [
        sample
        for sample in samples
        if sample["side"] == "OBSERVED" and sample["channel_id"] == "battery.voltage"
    ]
    predicted_battery_all = [
        sample
        for sample in samples
        if sample["side"] == "PREDICTED" and sample["channel_id"] == "battery.voltage"
    ]

    return {
        "schema_version": 1,
        "session_id": SESSION_ID,
        "status": record["status"],
        "evidence_boundary": "PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME",
        "ground_truth_available": False,
        "reconstruction": {
            "script": "scripts/extract_wp86_hardware_observation.py",
            "command": (
                "python scripts/extract_wp86_hardware_observation.py --check "
                "missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json"
            ),
            "source": ".cache/crazyswarm/digital-twin/twin-journal-v1.jsonl",
        },
        "session_envelope_count": len(envelope_hashes),
        "session_envelope_hashes_sha256": canonical_sha256(envelope_hashes),
        "normalized_sample_count": len(normalized),
        "normalized_samples_sha256": canonical_sha256(normalized),
        "paired_cycles": len(sequences),
        "sequence_first": sequences[0],
        "sequence_last": sequences[-1],
        "samples_by_side": dict(sorted(by_side.items())),
        "samples_by_side_and_channel": per_side_counts,
        "observed_battery": {
            "total_samples": len(observed_battery_all),
            "available_samples": len(batteries),
            "first_cycle_availability": observed_battery_all[0]["availability"],
            "first_v": battery_values[0],
            "last_v": battery_values[-1],
            "unique_values": unique_battery,
            "minimum_quantized_step_v": min(battery_steps),
        },
        "flow": {
            "available_samples": len(flow_values),
            "reported_statuses": dict(Counter(value["status"] for value in flow_values)),
            "quality_percent": {
                "minimum": min(flow_quality),
                "median": statistics.median(flow_quality),
                "maximum": max(flow_quality),
            },
            "horizontal_speed_m_s": {
                "median": statistics.median(flow_speed),
                "p95": percentile(flow_speed, 0.95),
                "maximum": max(flow_speed),
            },
            "ground_distance_m": {
                "minimum": min(ground_distance),
                "median": statistics.median(ground_distance),
                "maximum": max(ground_distance),
            },
            "usability": "UNQUALIFIED",
        },
        "estimator": {
            "available_samples": len(estimator_values),
            "converged_false": converged[False],
            "converged_true": converged[True],
            "first_position_variance_m2": estimator_values[0]["position_variance_m2"],
            "last_position_variance_m2": estimator_values[-1]["position_variance_m2"],
        },
        "stationary_checks": {
            "acceleration_norm_m_s2": {
                "median": statistics.median(acceleration_norm),
                "p95": percentile(acceleration_norm, 0.95),
            },
            "angular_rate_norm_rad_s": {
                "median": statistics.median(angular_velocity_norm),
                "p95": percentile(angular_velocity_norm, 0.95),
            },
            "attitude_span_rad": attitude_span,
        },
        "clock_counterexample": {
            "observed_first_cycle_availability": observed_battery_all[0]["availability"],
            "observed_first_available_raw_s": batteries[0]["raw_source_timestamp_s"],
            "observed_final_mapped_s": observed_battery_all[-1]["source_timestamp_s"],
            "predicted_final_mapped_s": predicted_battery_all[-1]["source_timestamp_s"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    journal = args.journal if args.journal.is_absolute() else ROOT / args.journal
    actual = build_artifact(journal)
    if args.check:
        check_path = args.check if args.check.is_absolute() else ROOT / args.check
        expected = json.loads(check_path.read_text(encoding="utf-8"))
        if actual != expected:
            print(json.dumps({"status": "MISMATCH", "actual": actual}, indent=2, sort_keys=True))
            return 1
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "artifact": str(check_path.relative_to(ROOT)),
                    "artifact_sha256": hashlib.sha256(check_path.read_bytes()).hexdigest(),
                    "normalized_samples_sha256": actual["normalized_samples_sha256"],
                    "normalized_sample_count": actual["normalized_sample_count"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
