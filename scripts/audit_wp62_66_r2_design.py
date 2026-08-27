#!/usr/bin/env python3
"""Reproduce the narrow WP-62 through WP-66 R2 design correction audit."""

from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path
import time
from typing import Any

import audit_wp62_66_design as base


WALL_BUDGET_S = 0.5
MAXIMUM_EXPANSIONS = 8192
TRACKING_RMS_GUARD = {
    "category": "tracking",
    "metric": "tracking_rms_m",
    "comparator": "<=",
    "threshold": 0.05,
    "pass_value": 0.049,
    "isolated_fail_value": 0.051,
}

# Filled from the pre-freeze command after the timed algorithm and witnesses exist.
FROZEN_TIMING_SAMPLES_S: dict[str, list[float]] = {
    "obstructed": [
        0.22960458399938943,
        0.22534387499945296,
        0.22835112500069954,
        0.22378625000055763,
        0.2245147920002637,
    ],
    "no_solution": [
        0.13022362499941664,
        0.13043441599984362,
        0.1305727079998178,
        0.12966625000080967,
        0.12972999999874446,
    ],
}


def _astar_with_wall_budget(
    start_m: tuple[float, float],
    goal_m: tuple[float, float],
    obstacles: list[dict[str, Any]],
    *,
    maximum_expansions: int = MAXIMUM_EXPANSIONS,
    wall_budget_s: float = WALL_BUDGET_S,
    reverse_neighbors: bool = False,
    certificate_delay_s: float = 0.0,
) -> dict[str, Any]:
    started = time.monotonic()
    start_xy = (base._grid_index(start_m[0]), base._grid_index(start_m[1]))
    goal_xy = (base._grid_index(goal_m[0]), base._grid_index(goal_m[1]))
    start = (start_xy[0], start_xy[1], 0)
    queue: list[tuple[float, float, float, float, int, int, int]] = []
    heapq.heappush(queue, (math.dist(start_m, goal_m), 0.0, 0.0, 0.0, *start))
    best: dict[tuple[int, int, int], tuple[float, float, float]] = {start: (0.0, 0.0, 0.0)}
    previous: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    expanded = 0
    final: tuple[int, int, int] | None = None
    timed_out = False
    heading_order = list(range(len(base.HEADINGS)))
    if reverse_neighbors:
        heading_order.reverse()
    while queue:
        if time.monotonic() - started >= wall_budget_s:
            timed_out = True
            break
        _, distance, turn, negative_clearance, ix, iy, heading = heapq.heappop(queue)
        state = (ix, iy, heading)
        if best.get(state) != (distance, turn, negative_clearance):
            continue
        if (ix, iy) == goal_xy:
            final = state
            break
        if expanded >= maximum_expansions:
            break
        expanded += 1
        for next_heading in heading_order:
            dx, dy = base.HEADINGS[next_heading]
            next_xy = (ix + dx, iy + dy)
            point = base._grid_point(next_xy)
            if base._blocked(point, obstacles):
                continue
            current_point = base._grid_point((ix, iy))
            if dx and dy and (
                base._blocked(base._grid_point((ix + dx, iy)), obstacles)
                or base._blocked(base._grid_point((ix, iy + dy)), obstacles)
            ):
                continue
            clear, minimum = base._segment_clear(current_point, point, obstacles)
            if not clear:
                continue
            edge = base.GRID_STEP_M * (math.sqrt(2.0) if dx and dy else 1.0)
            heading_delta = min((next_heading - heading) % 8, (heading - next_heading) % 8)
            next_cost = (
                round(distance + edge, 12),
                round(turn + heading_delta * (math.pi / 4.0), 12),
                min(negative_clearance, -(minimum or 99.0)),
            )
            next_state = (next_xy[0], next_xy[1], next_heading)
            if next_state in best and best[next_state] <= next_cost:
                continue
            best[next_state] = next_cost
            previous[next_state] = state
            heuristic = math.dist(point, goal_m)
            heapq.heappush(queue, (next_cost[0] + heuristic, *next_cost, *next_state))
    elapsed_s = time.monotonic() - started
    if final is None:
        disposition = (
            "BUDGET_EXHAUSTED"
            if timed_out or expanded >= maximum_expansions
            else "NO_SOLUTION"
        )
        core = {
            "disposition": disposition,
            "expanded_nodes": expanded,
            "maximum_expansions": maximum_expansions,
            "wall_budget_s": wall_budget_s,
            "path": [],
            "path_length_m": None,
            "integrated_turn_rad": None,
            "minimum_center_clearance_m": None,
        }
        return {
            **core,
            "result_sha256": base._canonical_sha256(core),
            "observed_elapsed_s": elapsed_s,
        }
    states = [final]
    while states[-1] != start:
        states.append(previous[states[-1]])
    states.reverse()
    path = [list(base._grid_point((state[0], state[1]))) for state in states]
    cost = best[final]
    if certificate_delay_s > 0.0:
        time.sleep(certificate_delay_s)
    certificate = base._path_certificate(path, obstacles)
    elapsed_s = time.monotonic() - started
    if elapsed_s >= wall_budget_s:
        core = {
            "disposition": "BUDGET_EXHAUSTED",
            "expanded_nodes": expanded,
            "maximum_expansions": maximum_expansions,
            "wall_budget_s": wall_budget_s,
            "path": [],
            "path_length_m": None,
            "integrated_turn_rad": None,
            "minimum_center_clearance_m": None,
        }
        return {
            **core,
            "result_sha256": base._canonical_sha256(core),
            "observed_elapsed_s": elapsed_s,
        }
    core = {
        "disposition": "FOUND_CERTIFIED" if certificate["passed"] else "REJECTED_UNCERTIFIED",
        "expanded_nodes": expanded,
        "maximum_expansions": maximum_expansions,
        "wall_budget_s": wall_budget_s,
        "path": path,
        "path_length_m": cost[0],
        "integrated_turn_rad": cost[1],
        "minimum_center_clearance_m": certificate["minimum_center_to_obstacle_surface_m"],
        "certificate": certificate,
    }
    return {
        **core,
        "result_sha256": base._canonical_sha256(core),
        "observed_elapsed_s": elapsed_s,
    }


def _deterministic_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "observed_elapsed_s"}


def _search_witnesses() -> dict[str, Any]:
    obstacle = {"id": "rock", "min_m": [-0.2, -0.2], "max_m": [0.2, 0.2]}
    wall = {"id": "wall", "min_m": [-0.95, -1.8], "max_m": [-0.9, 1.8]}
    obstructed = _astar_with_wall_budget((-1.3, 0.0), (1.3, 0.0), [obstacle])
    no_solution = _astar_with_wall_budget((-1.3, 0.0), (1.3, 0.0), [wall])
    forced_timeout = _astar_with_wall_budget(
        (-1.3, 0.0),
        (1.3, 0.0),
        [obstacle],
        wall_budget_s=0.0,
    )
    delayed_certificate = _astar_with_wall_budget(
        (-1.3, 0.0),
        (1.3, 0.0),
        [],
        certificate_delay_s=0.51,
    )
    return {
        "obstructed": _deterministic_result(obstructed),
        "no_solution": _deterministic_result(no_solution),
        "forced_timeout": _deterministic_result(forced_timeout),
        "delayed_certificate": _deterministic_result(delayed_certificate),
    }


def _reaction_budget() -> dict[str, Any]:
    latency_s = 0.12 + 0.02 + WALL_BUDGET_S + 0.0006 + 0.0994
    results: dict[str, Any] = {}
    for witness_id, speed_m_s, distance_m in (
        ("nominal", 0.4, 0.95),
        ("progressive", 0.4, 0.75),
        ("lower-speed", 0.2, 0.75),
        ("insufficient", 0.4, 0.50),
    ):
        stop_time_s, stop_distance_m = base._jerk_limited_stop(speed_m_s)
        response_distance_m = speed_m_s * latency_s + stop_distance_m
        required_distance_m = base.PROTECTED_PADDING_M + response_distance_m
        margin_m = distance_m - required_distance_m
        urgency = max(0.0, min(1.0, 1.0 - margin_m / 0.25))
        results[witness_id] = {
            "speed_m_s": speed_m_s,
            "surface_distance_m": distance_m,
            "total_latency_s": latency_s,
            "jerk_limited_stop_time_s": stop_time_s,
            "jerk_limited_stop_distance_m": stop_distance_m,
            "response_distance_m": response_distance_m,
            "required_distance_m": required_distance_m,
            "margin_m": margin_m,
            "urgency": urgency,
        }
    return results


def _reaction_witness(
    witness_id: str,
    *,
    speed_m_s: float,
    surface_distance_m: float,
    observation_variant: str = "TRUSTED",
    block_goal: bool = False,
    maximum_hover_s: float = 60.0,
) -> dict[str, Any]:
    latency_s = 0.12 + 0.02 + WALL_BUDGET_S + 0.0006 + 0.0994
    stop_time_s, stop_distance_m = base._jerk_limited_stop(speed_m_s)
    response_distance_m = speed_m_s * latency_s + stop_distance_m
    required_distance_m = base.PROTECTED_PADDING_M + response_distance_m
    margin_m = surface_distance_m - required_distance_m
    urgency = max(0.0, min(1.0, 1.0 - margin_m / 0.25))
    current_x_m = -surface_distance_m
    obstacle = {"id": "sensed-rock", "min_m": [0.0, -0.2], "max_m": [0.35, 0.2]}
    planning_obstacles = [obstacle]
    if block_goal:
        planning_obstacles = [
            {"id": "blocking-wall", "min_m": [-0.1, -1.8], "max_m": [0.1, 1.8]}
        ]
    payload = {"solid_id": obstacle["id"], "region": obstacle}
    observation = {
        "source_s": 5.0,
        "received_s": 5.12,
        "current_source_s": 5.20,
        "generation": 2,
        "current_generation": 1,
        "payload": payload,
        "authenticated_payload_sha256": base._canonical_sha256(payload),
    }
    if observation_variant == "TAMPERED":
        observation["authenticated_payload_sha256"] = "0" * 64
    elif observation_variant == "STALE":
        observation["generation"] = 1
    elif observation_variant == "LATE_SOURCE":
        observation["current_source_s"] = 5.26
    elif observation_variant == "LATE_RECEIVE":
        observation["received_s"] = 5.121
    status = base._observation_status(observation)
    search = _deterministic_result(
        _astar_with_wall_budget((current_x_m, 0.0), (1.35, 0.0), planning_obstacles)
    )
    braking_path = [[current_x_m, 0.0], [current_x_m + response_distance_m, 0.0]]
    braking_certificate = base._path_certificate(braking_path, [obstacle])
    hold_clearance_m = surface_distance_m - base.PROTECTED_PADDING_M
    hold_core = {
        "oracle": "independent-invariant-hold-v1",
        "speed_m_s": speed_m_s,
        "maximum_hold_speed_m_s": 0.02,
        "clearance_margin_m": hold_clearance_m,
        "prediction_horizon_s": 3.0,
        "maximum_hover_s": maximum_hover_s,
        "passed": speed_m_s <= 0.02 and hold_clearance_m >= 0.0 and maximum_hover_s >= 3.0,
    }
    hold_certificate = {
        **hold_core,
        "certificate_sha256": base._canonical_sha256(hold_core),
    }
    abort_certificate = base._vertical_abort_certificate(current_x_m, speed_m_s, obstacle)
    trusted = status == "TRUSTED_FRESH"
    if not trusted:
        command = (
            "REJECT_UPDATE_AND_CERTIFIED_HOLD"
            if hold_certificate["passed"]
            else "REJECT_UPDATE_NO_CERTIFIED_CONTINGENCY"
        )
    elif search["disposition"] == "FOUND_CERTIFIED" and braking_certificate["passed"]:
        command = (
            "CONTINUE_WITH_MOVING_REPLAN"
            if urgency == 0.0
            else "JERK_LIMITED_DECELERATE_AND_TURN"
        )
    elif hold_certificate["passed"]:
        command = "CERTIFIED_HOLD"
    elif abort_certificate["passed"]:
        command = "CERTIFIED_ABORT_AND_LAND"
    else:
        command = "NO_CERTIFIED_RESPONSE_FAIL_CLOSED"
    core = {
        "witness_id": witness_id,
        "vehicle": {
            "position_m": [current_x_m, 0.0, 0.4],
            "velocity_m_s": [speed_m_s, 0.0, 0.0],
            "acceleration_m_s2": [0.0, 0.0, 0.0],
            "nominal_radius_m": 0.055,
            "maximum_acceleration_m_s2": 1.0,
            "maximum_jerk_m_s3": 8.0,
        },
        "world": {
            "flight_volume_min_m": [-1.8, -1.8, 0.0],
            "flight_volume_max_m": [1.8, 1.8, 1.0],
            "goal_m": [1.35, 0.0, 0.4],
            "obstacles": planning_obstacles,
            "center_to_obstacle_surface_distance_m": surface_distance_m,
        },
        "clocks": {
            "source_clock_id": "fast-sim-Alpha",
            "source_clock_epoch": 1,
            "observation": observation,
            "effective_cutover_s": 5.74,
            "budgets_s": {
                "sense_process": 0.12,
                "validate": 0.02,
                "plan_and_certificate": WALL_BUDGET_S,
                "acknowledge": 0.0006,
                "commit_guard": 0.0994,
                "total": latency_s,
                "prediction_horizon": 3.0,
            },
        },
        "observation_status": status,
        "protection": {
            "position_uncertainty_m": 0.05,
            "policy_clearance_m": 0.15,
            "jerk_limited_stop_time_s": stop_time_s,
            "jerk_limited_stop_distance_m": stop_distance_m,
            "response_distance_m": response_distance_m,
            "required_center_surface_distance_m": required_distance_m,
            "margin_m": margin_m,
            "urgency_0_to_1": urgency,
        },
        "search": search,
        "braking_certificate": braking_certificate,
        "hold_certificate": hold_certificate,
        "abort_certificate": abort_certificate,
        "resulting_command": command,
    }
    return {**core, "decision_certificate_sha256": base._canonical_sha256(core)}


def _reaction_witnesses() -> list[dict[str, Any]]:
    return [
        _reaction_witness("nominal-moving-detour", speed_m_s=0.4, surface_distance_m=0.95),
        _reaction_witness("progressive-turn", speed_m_s=0.4, surface_distance_m=0.75),
        _reaction_witness("lower-speed-same-distance", speed_m_s=0.2, surface_distance_m=0.75),
        _reaction_witness("insufficient-clearance", speed_m_s=0.4, surface_distance_m=0.50),
        _reaction_witness(
            "stale-generation",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            observation_variant="STALE",
            block_goal=True,
        ),
        _reaction_witness(
            "late-source",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            observation_variant="LATE_SOURCE",
            block_goal=True,
        ),
        _reaction_witness(
            "late-receive",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            observation_variant="LATE_RECEIVE",
            block_goal=True,
        ),
        _reaction_witness(
            "tampered-observation",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            observation_variant="TAMPERED",
            block_goal=True,
        ),
        _reaction_witness(
            "certified-hold",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            block_goal=True,
        ),
        _reaction_witness(
            "certified-abort-land",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            block_goal=True,
            maximum_hover_s=0.0,
        ),
        _reaction_witness(
            "no-certified-response",
            speed_m_s=0.0,
            surface_distance_m=0.20,
            block_goal=True,
        ),
    ]


def _tracking_repeat_policy() -> dict[str, Any]:
    expected_repeat_ids = [
        "accelerated-1",
        "accelerated-2",
        "accelerated-3",
        "realtime-1",
    ]

    def qualify(repeats: list[dict[str, Any]]) -> dict[str, Any]:
        by_id = {row["repeat_id"]: row for row in repeats}
        failures: list[str] = []
        for repeat_id in expected_repeat_ids:
            row = by_id.get(repeat_id)
            if row is None:
                failures.append(f"{repeat_id}:MISSING")
                continue
            if row.get("applicable") is not True:
                failures.append(f"{repeat_id}:INVALID_NOT_APPLICABLE")
                continue
            value = row.get("tracking_rms_m")
            if value is None:
                failures.append(f"{repeat_id}:MISSING_VALUE")
            elif value > TRACKING_RMS_GUARD["threshold"]:
                failures.append(f"{repeat_id}:ABOVE_THRESHOLD")
        unexpected = sorted(set(by_id) - set(expected_repeat_ids))
        failures.extend(f"{repeat_id}:UNEXPECTED" for repeat_id in unexpected)
        return {
            "passed": not failures,
            "failures": failures,
            "evaluated_repeat_ids": expected_repeat_ids,
        }

    passing = [
        {"repeat_id": "accelerated-1", "applicable": True, "tracking_rms_m": 0.047},
        {"repeat_id": "accelerated-2", "applicable": True, "tracking_rms_m": 0.048},
        {"repeat_id": "accelerated-3", "applicable": True, "tracking_rms_m": 0.049},
        {"repeat_id": "realtime-1", "applicable": True, "tracking_rms_m": 0.049},
    ]
    missing = [row for row in passing if row["repeat_id"] != "accelerated-2"]
    invalid_not_applicable = [dict(row) for row in passing]
    invalid_not_applicable[1] = {
        "repeat_id": "accelerated-2",
        "applicable": False,
        "tracking_rms_m": None,
    }
    single_failure = [dict(row) for row in passing]
    single_failure[2]["tracking_rms_m"] = 0.051
    aggregate_cheat = [dict(row) for row in passing]
    for row, value in zip(aggregate_cheat, (0.049, 0.049, 0.049, 0.053), strict=True):
        row["tracking_rms_m"] = value
    return {
        "metric": "tracking_rms_m",
        "threshold_m": TRACKING_RMS_GUARD["threshold"],
        "applicability": (
            "required for every accelerated and realtime MotionQualityContract repeat; "
            "there is no N/A branch"
        ),
        "aggregation_rule": "all expected repeats pass individually; no mean or median substitute",
        "expected_repeat_ids": expected_repeat_ids,
        "cases": {
            "passing": {"repeats": passing, "outcome": qualify(passing)},
            "missing": {"repeats": missing, "outcome": qualify(missing)},
            "invalid_not_applicable": {
                "repeats": invalid_not_applicable,
                "outcome": qualify(invalid_not_applicable),
            },
            "single_failure": {
                "repeats": single_failure,
                "outcome": qualify(single_failure),
            },
            "aggregate_cheat": {
                "arithmetic_mean_m": sum(
                    row["tracking_rms_m"] for row in aggregate_cheat
                )
                / len(aggregate_cheat),
                "repeats": aggregate_cheat,
                "outcome": qualify(aggregate_cheat),
            },
        },
    }


def build_payload() -> dict[str, Any]:
    registry = base._guard_registry()
    rows = [*registry["guards"], TRACKING_RMS_GUARD]
    rows.sort(key=lambda row: row["metric"])
    pass_vector = {row["metric"]: row["pass_value"] for row in rows}
    isolated = {
        row["metric"]: {row["metric"]: row["isolated_fail_value"]} for row in rows
    }
    return {
        "schema_version": 1,
        "batch": "WP-62-through-WP-66-R2",
        "base_design_sha256": "52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6",
        "search_contract": {
            "maximum_expansions": MAXIMUM_EXPANSIONS,
            "wall_budget_s": WALL_BUDGET_S,
            "timeout_check": (
                "time.monotonic before every expansion and after independent certification"
            ),
            "timeout_disposition": "BUDGET_EXHAUSTED / NO COMMAND",
            "frozen_timing_samples_s": FROZEN_TIMING_SAMPLES_S,
        },
        "search_witnesses": _search_witnesses(),
        "reaction_budget": _reaction_budget(),
        "reaction_witnesses": _reaction_witnesses(),
        "tracking_rms_guard": TRACKING_RMS_GUARD,
        "tracking_repeat_policy": _tracking_repeat_policy(),
        "guard_count": len(rows),
        "passing_whole_vector": pass_vector,
        "isolated_failure_overrides": isolated,
    }


def _passes(row: dict[str, Any], value: Any) -> bool:
    if row["comparator"] == "<=":
        return value <= row["threshold"]
    if row["comparator"] == ">=":
        return value >= row["threshold"]
    if row["comparator"] == "==":
        return value == row["threshold"]
    raise AssertionError(row["comparator"])


def check(payload: dict[str, Any]) -> None:
    assert payload["search_contract"]["wall_budget_s"] == WALL_BUDGET_S
    samples = payload["search_contract"]["frozen_timing_samples_s"]
    assert len(samples["obstructed"]) == 5
    assert len(samples["no_solution"]) == 5
    assert max(samples["obstructed"] + samples["no_solution"]) < WALL_BUDGET_S
    witnesses = payload["search_witnesses"]
    assert witnesses["obstructed"]["disposition"] == "FOUND_CERTIFIED"
    assert witnesses["no_solution"]["disposition"] == "NO_SOLUTION"
    assert witnesses["forced_timeout"]["disposition"] == "BUDGET_EXHAUSTED"
    assert witnesses["delayed_certificate"]["disposition"] == "BUDGET_EXHAUSTED"
    assert witnesses["delayed_certificate"]["path"] == []
    for _ in range(3):
        current = _search_witnesses()
        assert current == witnesses
    reaction = payload["reaction_budget"]
    assert reaction["nominal"]["urgency"] == 0.0
    assert 0.0 < reaction["progressive"]["urgency"] < 1.0
    assert reaction["lower-speed"]["urgency"] < reaction["progressive"]["urgency"]
    assert reaction["insufficient"]["urgency"] == 1.0
    reaction_witnesses = {
        row["witness_id"]: row for row in payload["reaction_witnesses"]
    }
    assert set(reaction_witnesses) == {
        "nominal-moving-detour",
        "progressive-turn",
        "lower-speed-same-distance",
        "insufficient-clearance",
        "stale-generation",
        "late-source",
        "late-receive",
        "tampered-observation",
        "certified-hold",
        "certified-abort-land",
        "no-certified-response",
    }
    expected_commands = {
        "nominal-moving-detour": "CONTINUE_WITH_MOVING_REPLAN",
        "progressive-turn": "JERK_LIMITED_DECELERATE_AND_TURN",
        "lower-speed-same-distance": "CONTINUE_WITH_MOVING_REPLAN",
        "insufficient-clearance": "NO_CERTIFIED_RESPONSE_FAIL_CLOSED",
        "stale-generation": "REJECT_UPDATE_AND_CERTIFIED_HOLD",
        "late-source": "REJECT_UPDATE_AND_CERTIFIED_HOLD",
        "late-receive": "REJECT_UPDATE_AND_CERTIFIED_HOLD",
        "tampered-observation": "REJECT_UPDATE_AND_CERTIFIED_HOLD",
        "certified-hold": "CERTIFIED_HOLD",
        "certified-abort-land": "CERTIFIED_ABORT_AND_LAND",
        "no-certified-response": "NO_CERTIFIED_RESPONSE_FAIL_CLOSED",
    }
    for witness_id, witness in reaction_witnesses.items():
        assert math.isclose(witness["clocks"]["budgets_s"]["total"], 0.74)
        assert witness["resulting_command"] == expected_commands[witness_id]
        assert witness["decision_certificate_sha256"] == base._canonical_sha256(
            {
                key: value
                for key, value in witness.items()
                if key != "decision_certificate_sha256"
            }
        )
        for certificate_key in (
            "braking_certificate",
            "hold_certificate",
            "abort_certificate",
        ):
            certificate = witness[certificate_key]
            hash_key = "certificate_sha256"
            assert certificate[hash_key] == base._canonical_sha256(
                {key: value for key, value in certificate.items() if key != hash_key}
            )
    repeat_policy = payload["tracking_repeat_policy"]
    assert repeat_policy["expected_repeat_ids"] == [
        "accelerated-1",
        "accelerated-2",
        "accelerated-3",
        "realtime-1",
    ]
    assert repeat_policy["cases"]["passing"]["outcome"]["passed"]
    for case_id in (
        "missing",
        "invalid_not_applicable",
        "single_failure",
        "aggregate_cheat",
    ):
        assert not repeat_policy["cases"][case_id]["outcome"]["passed"]
    assert repeat_policy["cases"]["aggregate_cheat"]["arithmetic_mean_m"] == 0.05
    assert payload["guard_count"] == 29
    assert "tracking_rms_m" in payload["passing_whole_vector"]
    registry_rows = [*base._guard_registry()["guards"], TRACKING_RMS_GUARD]
    for row in registry_rows:
        assert _passes(row, row["pass_value"])
        assert not _passes(row, row["isolated_fail_value"])
        vector = dict(payload["passing_whole_vector"])
        vector.update(payload["isolated_failure_overrides"][row["metric"]])
        failed = [item["metric"] for item in registry_rows if not _passes(item, vector[item["metric"]])]
        assert failed == [row["metric"]]


def _measure() -> dict[str, list[float]]:
    obstacle = {"id": "rock", "min_m": [-0.2, -0.2], "max_m": [0.2, 0.2]}
    wall = {"id": "wall", "min_m": [-0.95, -1.8], "max_m": [-0.9, 1.8]}
    result = {"obstructed": [], "no_solution": []}
    for _ in range(5):
        result["obstructed"].append(
            _astar_with_wall_budget((-1.3, 0.0), (1.3, 0.0), [obstacle])["observed_elapsed_s"]
        )
        result["no_solution"].append(
            _astar_with_wall_budget((-1.3, 0.0), (1.3, 0.0), [wall])["observed_elapsed_s"]
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", nargs="?", type=Path)
    parser.add_argument("--measure", action="store_true")
    args = parser.parse_args()
    if args.measure:
        print(json.dumps(_measure(), sort_keys=True, indent=2))
        return
    payload = build_payload()
    check(payload)
    if args.artifact is not None:
        assert json.loads(args.artifact.read_text()) == payload
    print(json.dumps(payload, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
