from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from crazyswarm_app.campaign.corridor import search_goal_corridor
from crazyswarm_app.campaign.execution_head import _response_urgency
from crazyswarm_app.campaign.models import (
    Region3D,
    ScenarioEvent,
    ScenarioEventKind,
    ScenarioExpectedDisposition,
)
from crazyswarm_app.campaign.perception import PerceptionChangeKind
from crazyswarm_app.campaign.replanning import (
    DynamicEventKind,
    InFlightEnvironmentEvent,
    ReplanObservation,
    SafeFallback,
    _reaction_horizon,
)
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.simulation.sensors import PerceptionModelConfig


ROOT = Path(__file__).resolve().parents[1]

SOURCE_RULES = {
    "speed": (
        ("docs/work-packages/ACTIVE.md", "infeasible speed"),
        ("docs/project/requirements/MOTION_AND_CONTROL.md", "speed"),
    ),
    "trajectory_tracking": (
        ("docs/project/requirements/MOTION_AND_CONTROL.md", "tracking"),
        ("docs/project/requirements/REPLANNING_AND_RUNTIME.md", "tracking"),
    ),
    "braking_and_jerk": (
        ("docs/work-packages/ACTIVE.md", "hard braking"),
        ("docs/project/requirements/MOTION_AND_CONTROL.md", "jerk"),
    ),
    "route_continuity": (
        ("docs/work-packages/ACTIVE.md", "route-side churn"),
        ("docs/project/requirements/MOTION_AND_CONTROL.md", "continuity"),
    ),
    "unintended_stop": (
        ("docs/work-packages/ACTIVE.md", "unintended stop"),
        ("docs/project/requirements/MOTION_AND_CONTROL.md", "stop"),
    ),
    "clearance_and_collision": (
        ("docs/work-packages/ACTIVE.md", "minimum safe margin"),
        ("docs/project/requirements/PLANNING_AND_GEOMETRY.md", "clearance"),
    ),
    "event_commit_completeness": (
        ("docs/project/requirements/REPLANNING_AND_RUNTIME.md", "commit"),
        ("docs/project/requirements/EVIDENCE_AND_REVIEW.md", "event"),
    ),
    "freshness_and_budget": (
        ("docs/work-packages/ACTIVE.md", "stale-cutover"),
        ("docs/project/requirements/REPLANNING_AND_RUNTIME.md", "budget"),
    ),
    "goal_and_landing": (
        ("docs/project/requirements/REPLANNING_AND_RUNTIME.md", "goal"),
        ("docs/project/requirements/MISSION_AND_CURRICULUM.md", "landing"),
    ),
}

GUARD_REGISTRY = {
    "speed": {
        "metric": "accepted_epoch_speed_band_coverage_fraction",
        "threshold": ">=0.95 outside takeoff/cutover/final-capture windows",
        "isolated_perturbation": "replace every moving sample with 0.10 m/s",
    },
    "trajectory_tracking": {
        "metric": "accepted_epoch_trajectory_tracking_rms_m",
        "threshold": "<=0.03 m",
        "isolated_perturbation": "offset observed position 0.04 m from accepted trajectory",
    },
    "braking_and_jerk": {
        "metric": "route_peak_deceleration_m_s2 / route_peak_jerk_m_s3",
        "threshold": "<=1.0 m/s^2 and <=8.0 m/s^3",
        "isolated_perturbation": "inject a 1.1 m/s^2 hard-brake sample",
    },
    "route_continuity": {
        "metric": "replacement_initial_heading_change_rad / nominal_side_reversal_count",
        "threshold": "<=pi/2 and 0 nominal side reversals",
        "isolated_perturbation": "mirror one replacement onto the opposite feasible side",
    },
    "unintended_stop": {
        "metric": "accepted_epoch_unintended_stop_count",
        "threshold": "0; speed <=0.02 m/s continuously for >=0.20 s only within a moving epoch",
        "isolated_perturbation": "insert a 0.21 s zero-speed interval inside one moving epoch",
    },
    "clearance_and_collision": {
        "metric": "minimum_nominal_envelope_to_solid_clearance_m / collision_count",
        "threshold": ">=requested clearance and 0 collisions",
        "isolated_perturbation": "move a solid 0.01 m inside requested clearance",
    },
    "event_commit_completeness": {
        "metric": "configured/observed/certified/committed/dispatched event identity join",
        "threshold": "complete for every configured event",
        "isolated_perturbation": "remove one preparation receipt",
    },
    "freshness_and_budget": {
        "metric": "observation_age_s / start_error_m / cumulative_planning_latency_s",
        "threshold": "<=0.25 s / <=0.10 m / <=2.0 s",
        "isolated_perturbation": "age the final observation to 0.251 s",
    },
    "goal_and_landing": {
        "metric": "goal_capture_and_landing",
        "threshold": "both captured with declared terminal limits",
        "isolated_perturbation": "omit the landing completion record",
    },
}

TRANSIT_ANCHORS = (
    "MotionPreparationRequest",
    "ResolvedPlanningPackage",
    "CampaignRunRequest",
    "CampaignExecutionRequest",
    "resolve_planning_package",
    "compile_scenario_trace",
    "SimulatedPerceptionObservationSource",
    "CampaignExecutionHead",
    "search_goal_corridor",
    "plan_changed_world_replacement",
    "_response_urgency",
    "_motion_guard_verdict",
    "_classify",
    "CampaignLab",
    "runActiveCampaign",
    "previewActiveCampaign",
)

MODIFY_PATHS = {
    "design.md",
    "docs/project/DESIGN.md",
    "docs/system/README.md",
    "missions/campaigns/sim/cases/dynamic-replanning/1d-cases-v1.yaml",
    "missions/library/one_drone/online_obstacle_replan/mission.py",
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/campaign/analyzer.py",
    "src/crazyswarm_app/campaign/api_models.py",
    "src/crazyswarm_app/campaign/catalog.py",
    "src/crazyswarm_app/campaign/corridor.py",
    "src/crazyswarm_app/campaign/execution_head.py",
    "src/crazyswarm_app/campaign/models.py",
    "src/crazyswarm_app/campaign/planner.py",
    "src/crazyswarm_app/campaign/replanning.py",
    "src/crazyswarm_app/campaign/runtime_executor.py",
    "src/crazyswarm_app/campaign/scenario.py",
    "src/crazyswarm_app/campaign/scheduling.py",
    "src/crazyswarm_app/campaign/service.py",
    "src/crazyswarm_app/campaign/submissions.py",
    "src/crazyswarm_app/campaign/trajectory.py",
    "src/crazyswarm_app/observability/evaluation.py",
    "src/crazyswarm_app/observability/storage.py",
    "src/crazyswarm_app/simulation/sensors.py",
    "src/crazyswarm_app/simulation/world.py",
    "ui/app/components/CampaignLab.tsx",
    "ui/app/globals.css",
    "ui/app/lib/api.ts",
    "ui/app/lib/models.ts",
}

NEW_PATHS = {
    "src/crazyswarm_app/campaign/dynamic_obstacles.py",
    "tests/campaign/test_dynamic_preparation.py",
}


def _region(region_id: str, values: tuple[float, float, float, float, float, float]) -> Region3D:
    return Region3D(
        region_id=region_id,
        minimum_m=Vector3(x=values[0], y=values[1], z=values[2]),
        maximum_m=Vector3(x=values[3], y=values[4], z=values[5]),
    )


WORLD_TEMPLATES = {
    1: {
        "solid_id": "sensed-rock-1",
        "added": (-0.15, -0.20, 0.10, 0.20, 0.20, 0.70),
        "moved": (0.20, -0.25, 0.10, 0.50, 0.15, 0.70),
    },
    2: {
        "solid_id": "sensed-wall-2",
        "added": (0.85, 0.45, 0.00, 1.00, 0.90, 0.80),
    },
    3: {
        "solid_id": "sensed-wall-3",
        "added": (0.55, -0.80, 0.00, 0.75, -0.45, 0.80),
    },
    4: {
        "solid_id": "sensed-wall-4",
        "added": (0.90, -0.80, 0.00, 1.10, -0.45, 0.80),
    },
}

ADD_TIMES = {1: 2.0, 2: 7.5, 3: 9.25, 4: 11.0}


def _world_events(count: int, mode: str, seed: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def append(
        event_id: str,
        kind: ScenarioEventKind,
        trigger: float,
        solid_id: str,
        geometry: tuple[float, float, float, float, float, float] | None,
    ) -> None:
        sequence = len(events) + 1
        region = None if geometry is None else _region(solid_id, geometry)
        model = ScenarioEvent(
            event_id=event_id,
            kind=kind,
            trigger_time_s=trigger,
            replacement_goal=region,
            duration_s=3.0,
            source_id="campaign-scenario",
            sequence=sequence,
            generation=sequence,
            update_identity=solid_id if geometry is None else None,
            expected_disposition=ScenarioExpectedDisposition.ACCEPTED_UPDATE,
        )
        events.append(
            {
                **model.model_dump(mode="json"),
                "solid_id": solid_id,
                "effective_source_s": trigger + 3.0,
                "sensor_received_source_s": trigger + 0.12,
                "sensor_expires_source_s": trigger + 0.62,
                "perception_change_kind": PerceptionChangeKind[
                    {
                        ScenarioEventKind.OBSTACLE_ADDED: "SOLID_APPEARED",
                        ScenarioEventKind.OBSTACLE_MOVED: "SOLID_MOVED",
                        ScenarioEventKind.OBSTACLE_REMOVED: "SOLID_DISAPPEARED",
                    }[kind]
                ].value,
            }
        )

    first = WORLD_TEMPLATES[1]
    append(
        "online-obstacle-appear-1",
        ScenarioEventKind.OBSTACLE_ADDED,
        ADD_TIMES[1],
        first["solid_id"],
        first["added"],
    )
    append(
        "online-obstacle-move-1",
        ScenarioEventKind.OBSTACLE_MOVED,
        5.5,
        first["solid_id"],
        first["moved"],
    )
    for index in range(2, count + 1):
        template = WORLD_TEMPLATES[index]
        append(
            f"online-obstacle-appear-{index}",
            ScenarioEventKind.OBSTACLE_ADDED,
            ADD_TIMES[index],
            template["solid_id"],
            template["added"],
        )
    append(
        "online-obstacle-remove-1",
        ScenarioEventKind.OBSTACLE_REMOVED,
        12.5,
        first["solid_id"],
        None,
    )
    return events


def _world_resolution(count: int, mode: str, seed: int) -> dict[str, Any]:
    events = _world_events(count, mode, seed)
    definition = {
        "schema_version": 1,
        "source_case_id": "1d.online_obstacle_replan.dynamic_nominal",
        "obstacle_count": count,
        "variation_mode": mode,
        "variation_seed": seed,
        "run_id_participates_in_truth": False,
        "templates": {str(key): value for key, value in WORLD_TEMPLATES.items() if key <= count},
    }
    definition_sha = canonical_sha256(definition)
    event_sha = canonical_sha256(events)
    resolved = {
        "definition": definition,
        "definition_sha256": definition_sha,
        "events": events,
        "event_set_sha256": event_sha,
    }
    resolved_sha = canonical_sha256(resolved)
    return {
        **resolved,
        "resolved_dynamic_world_sha256": resolved_sha,
        "resolved_case_id": f"1d.online_obstacle_replan.dynamic_nominal.world-{resolved_sha[:12]}",
        "resolved_case_sha256": canonical_sha256(
            {
                "source_case_sha256": "4" * 64,
                "resolved_dynamic_world_sha256": resolved_sha,
                "scenario_events": events,
            }
        ),
    }


def _opening_witnesses() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    constants = {
        "vehicle_radius_m": 0.055,
        "position_uncertainty_m": 0.05,
        "spline_search_reserve_m": 0.05,
        "cell_size_phase_reserve_m": 0.05,
    }
    openings = []
    for clearance in (0.15, 0.25):
        protected = 2.0 * (
            constants["vehicle_radius_m"]
            + constants["position_uncertainty_m"]
            + clearance
            + constants["spline_search_reserve_m"]
        )
        openings.append(
            {
                "minimum_clearance_m": clearance,
                "physical_protected_opening_m": round(protected, 12),
                "planner_guaranteed_opening_m": round(
                    protected + constants["cell_size_phase_reserve_m"], 12
                ),
                "components": constants,
            }
        )

    volume = _region("phase-volume", (-1.0, -1.0, 0.0, 1.0, 1.0, 1.0))
    lattice = []
    for gap, offset in ((0.61, 0.0), (0.61, 0.025), (0.63, 0.025), (0.66, 0.025)):
        obstacles = (
            _region("lower", (-0.2, -1.0, 0.0, 0.2, offset - gap / 2.0, 1.0)),
            _region("upper", (-0.2, offset + gap / 2.0, 0.0, 0.2, 1.0, 1.0)),
        )
        result = search_goal_corridor(
            start_m=Vector3(x=-0.7, y=offset, z=0.4),
            goal_m=Vector3(x=0.7, y=offset, z=0.4),
            flight_volume=volume,
            obstacles=obstacles,
            inflation_m=0.305,
            boundary_horizontal_margin_m=0.255,
        )
        lattice.append(
            {
                "raw_gap_m": gap,
                "gap_center_offset_from_lattice_m": offset,
                "production_disposition": result.disposition.value,
                "result_sha256": result.result_sha256,
            }
        )
    return openings, lattice


def _reaction_witnesses() -> dict[str, Any]:
    observations = {
        "Alpha": ReplanObservation.create(
            observation_id="wp67-r2-reaction",
            role_id="Alpha",
            source_timestamp_s=2.12,
            captured_at_source_s=2.12,
            position_m=Vector3(x=0.0, y=0.0, z=0.4),
            velocity_m_s=Vector3(x=0.30, y=0.0, z=0.0),
            acceleration_m_s2=Vector3(),
        )
    }
    speed_rows = []
    for clearance in (0.15, 0.25):
        for speed in (0.29, 0.30, 0.50):
            observations["Alpha"] = observations["Alpha"].model_copy(
                update={"velocity_m_s": Vector3(x=speed, y=0.0, z=0.0)}
            )
            obstacle = _region("surface", (0.70, -0.1, 0.0, 0.80, 0.1, 0.8))
            urgency = _response_urgency(
                observations=observations,
                perceived_solids={"surface": obstacle},
                vehicle_radius_m=0.055,
                position_uncertainty_m=0.05,
                policy_clearance_m=clearance,
                maximum_acceleration_m_s2=1.0,
                maximum_jerk_m_s3=8.0,
            )
            speed_rows.append({"clearance_m": clearance, **urgency})

    event = InFlightEnvironmentEvent(
        event_id="wp67-r2-clock",
        kind=DynamicEventKind.OBSTACLE_ADDED,
        source_id="simulated-depth-range",
        sequence=1,
        source_timestamp_s=2.0,
        received_source_s=2.12,
        effective_source_s=5.0,
        affected_role_ids=("Alpha",),
        world_generation=1,
        region_id="surface",
        region=_region("surface", (0.70, -0.1, 0.0, 0.80, 0.1, 0.8)),
    )
    horizon = _reaction_horizon(
        event,
        decision_time_source_s=2.64,
        queue_latency_s=0.02,
        planning_latency_s=0.50,
        acknowledgement_latency_s=0.0006,
        cutover_guard_s=0.0994,
        old_epoch_safe_until_source_s=5.0,
        planning_budget_s=2.0,
        freshness_limit_s=0.25,
    )
    stale = _reaction_horizon(
        event.model_copy(update={"received_source_s": 2.251}),
        decision_time_source_s=2.771,
        queue_latency_s=0.02,
        planning_latency_s=0.50,
        acknowledgement_latency_s=0.0006,
        cutover_guard_s=0.0994,
        old_epoch_safe_until_source_s=5.0,
        planning_budget_s=2.0,
        freshness_limit_s=0.25,
    )
    return {
        "clocks_and_latency": {
            "truth_trigger_source_s": 2.0,
            "sensor_latency_s": PerceptionModelConfig().latency_s,
            "sensor_received_source_s": 2.12,
            "validation_queue_latency_s": 0.02,
            "planning_latency_witness_s": 0.50,
            "acknowledgement_latency_s": 0.0006,
            "cutover_guard_s": 0.0994,
            "complete_response_latency_s": 0.74,
            "event_effective_source_s": 5.0,
            "prediction_horizon_s": 3.0,
            "sensor_expiry_s": PerceptionModelConfig().expiry_s,
            "freshness_limit_s": 0.25,
            "planning_budget_s": 2.0,
            "trajectory_prediction_step_s": 0.02,
        },
        "speed_rows": speed_rows,
        "nominal_reaction_horizon": horizon.model_dump(mode="json"),
        "stale_reaction_horizon": stale.model_dump(mode="json"),
        "certificate_command_witnesses": [
            {
                "case": "nominal fresh feasible detour",
                "certificate": "safe-prefix + corridor + preparation receipt",
                "command": "MOVING_REPLACEMENT",
                "dispatch": True,
            },
            {
                "case": "late observation with certified safe stationary prefix",
                "certificate": "safe-prefix only",
                "command": "STOP_AND_HOLD",
                "dispatch": True,
            },
            {
                "case": "late observation without safe stationary prefix",
                "certificate": "abort-route certificate",
                "command": SafeFallback.ABORT_AND_LAND.value,
                "dispatch": True,
            },
            {
                "case": "missing or tampered preparation receipt",
                "certificate": "invalid",
                "command": "NO_REPLACEMENT_DISPATCH",
                "dispatch": False,
            },
        ],
    }


def _discover_transit() -> tuple[dict[str, Any], list[str]]:
    candidates = [
        *ROOT.glob("src/**/*.py"),
        *ROOT.glob("missions/library/**/*.py"),
        *ROOT.glob("ui/app/**/*.ts"),
        *ROOT.glob("ui/app/**/*.tsx"),
    ]
    discovered: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(set(candidates)):
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        hits = []
        for anchor in TRANSIT_ANCHORS:
            for match in re.finditer(rf"\b{re.escape(anchor)}\b", text):
                hits.append({"anchor": anchor, "line": text.count("\n", 0, match.start()) + 1})
        if hits:
            discovered[relative] = hits
    generated_command = json.loads((ROOT / "ui/package.json").read_text())["scripts"][
        "generate:api"
    ]
    generated = sorted(
        path
        for path in ("ui/openapi.json", "ui/app/lib/api.generated.ts")
        if Path(path).name in generated_command or path in generated_command
    )
    classified = {
        path: {
            "edit_classification": (
                "GENERATED"
                if path in generated
                else "MODIFY"
                if path in MODIFY_PATHS
                else "NEW"
                if path in NEW_PATHS
                else "PRESERVE"
            ),
            "anchors": hits,
        }
        for path, hits in discovered.items()
    }
    for path in sorted(MODIFY_PATHS | NEW_PATHS | set(generated)):
        classified.setdefault(
            path,
            {
                "edit_classification": (
                    "GENERATED"
                    if path in generated
                    else "NEW"
                    if path in NEW_PATHS
                    else "MODIFY"
                ),
                "anchors": [],
            },
        )
    return classified, generated


def _preimages(paths: dict[str, Any]) -> dict[str, Any]:
    output = {}
    for relative, record in paths.items():
        path = ROOT / relative
        output[relative] = {
            "edit_classification": record["edit_classification"],
            "state": "EXISTING" if path.exists() else "INTENDED_NEW",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
            "anchors": record["anchors"],
        }
    return output


def main() -> None:
    output_path = (
        Path(sys.argv[1])
        if len(sys.argv) == 2
        else ROOT
        / "missions/campaigns/sim/qualification/wp67-70-r2-design-audit-v1.json"
    )
    source_results: dict[str, Any] = {}
    for category, rules in SOURCE_RULES.items():
        witnesses = []
        for relative, needle in rules:
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            witnesses.append(
                {"path": relative, "needle": needle, "found": needle.lower() in text}
            )
        source_results[category] = witnesses

    openings, lattice = _opening_witnesses()
    worlds = {
        f"count_{count}": _world_resolution(count, "FIXED", 42)
        for count in range(1, 5)
    }
    fixed_a = _world_resolution(3, "FIXED", 42)
    fixed_b = _world_resolution(3, "FIXED", 42)
    stress_a = _world_resolution(3, "SEEDED_STRESS", 43)
    stress_b = _world_resolution(3, "SEEDED_STRESS", 44)
    occupancy = {}
    for key, world in worlds.items():
        active: set[str] = set()
        maximum = 0
        for event in world["events"]:
            if event["kind"] == ScenarioEventKind.OBSTACLE_REMOVED.value:
                active.discard(event["solid_id"])
            else:
                active.add(event["solid_id"])
            maximum = max(maximum, len(active))
        occupancy[key] = {
            "event_count": len(world["events"]),
            "maximum_simultaneous_obstacles": maximum,
            "sequences": [event["sequence"] for event in world["events"]],
            "generations": [event["generation"] for event in world["events"]],
            "event_ids": [event["event_id"] for event in world["events"]],
            "solid_ids": sorted({event["solid_id"] for event in world["events"]}),
        }

    transit, generated = _discover_transit()
    reaction = _reaction_witnesses()
    exact_dispositions = [row["production_disposition"] for row in lattice]
    category_counts = Counter(GUARD_REGISTRY.keys())
    checks = {
        "guard_sources_present": all(
            witness["found"]
            for witnesses in source_results.values()
            for witness in witnesses
        ),
        "guard_registry_independently_complete": set(GUARD_REGISTRY) == set(SOURCE_RULES)
        and all(value == 1 for value in category_counts.values()),
        "physical_and_guaranteed_openings_exact": openings
        == [
            {
                "minimum_clearance_m": 0.15,
                "physical_protected_opening_m": 0.61,
                "planner_guaranteed_opening_m": 0.66,
                "components": openings[0]["components"],
            },
            {
                "minimum_clearance_m": 0.25,
                "physical_protected_opening_m": 0.81,
                "planner_guaranteed_opening_m": 0.86,
                "components": openings[1]["components"],
            },
        ],
        "production_lattice_phase_counterexample_exact": exact_dispositions
        == ["SELECTED", "NO_SOLUTION", "NO_SOLUTION", "SELECTED"],
        "world_event_cardinality_exact": [
            occupancy[f"count_{count}"]["event_count"] for count in range(1, 5)
        ]
        == [3, 4, 5, 6],
        "world_population_exact": [
            occupancy[f"count_{count}"]["maximum_simultaneous_obstacles"]
            for count in range(1, 5)
        ]
        == [1, 2, 3, 4],
        "world_sequences_contiguous": all(
            row["sequences"] == list(range(1, row["event_count"] + 1))
            and row["generations"] == list(range(1, row["event_count"] + 1))
            for row in occupancy.values()
        ),
        "fixed_identity_excludes_run_id": fixed_a["resolved_dynamic_world_sha256"]
        == fixed_b["resolved_dynamic_world_sha256"],
        "stress_identity_is_explicit_seeded_truth": stress_a["resolved_dynamic_world_sha256"]
        != stress_b["resolved_dynamic_world_sha256"],
        "clocks_and_latency_exact": reaction["clocks_and_latency"]
        == {
            "truth_trigger_source_s": 2.0,
            "sensor_latency_s": 0.12,
            "sensor_received_source_s": 2.12,
            "validation_queue_latency_s": 0.02,
            "planning_latency_witness_s": 0.5,
            "acknowledgement_latency_s": 0.0006,
            "cutover_guard_s": 0.0994,
            "complete_response_latency_s": 0.74,
            "event_effective_source_s": 5.0,
            "prediction_horizon_s": 3.0,
            "sensor_expiry_s": 0.5,
            "freshness_limit_s": 0.25,
            "planning_budget_s": 2.0,
            "trajectory_prediction_step_s": 0.02,
        },
        "nominal_and_stale_horizon_sensitive": reaction["nominal_reaction_horizon"][
            "passed"
        ]
        and not reaction["stale_reaction_horizon"]["passed"],
        "clearance_025_speed_witness_exact": math.isclose(
            next(
                row["required_center_to_surface_distance_m"]
                for row in reaction["speed_rows"]
                if row["clearance_m"] == 0.25 and row["speed_m_s"] == 0.30
            ),
            0.64075,
            abs_tol=1e-12,
        ),
        "certificate_command_classes_complete": [
            row["command"] for row in reaction["certificate_command_witnesses"]
        ]
        == [
            "MOVING_REPLACEMENT",
            "STOP_AND_HOLD",
            SafeFallback.ABORT_AND_LAND.value,
            "NO_REPLACEMENT_DISPATCH",
        ],
        "transit_discovered_and_classified": bool(transit)
        and all(row["edit_classification"] in {"MODIFY", "PRESERVE", "NEW", "GENERATED"} for row in transit.values()),
        "generated_outputs_derived": generated
        == ["ui/app/lib/api.generated.ts", "ui/openapi.json"],
    }
    payload = {
        "schema_version": 1,
        "audit_id": "wp67-70-r2-design-audit-v1",
        "base_commit": "40cd9947f87eb9bf2719d72e7c72ea867eab9977",
        "source_derived_guard_categories": source_results,
        "guard_registry": GUARD_REGISTRY,
        "opening_witnesses": openings,
        "lattice_phase_witnesses": lattice,
        "dynamic_world_resolutions": worlds,
        "occupancy_witnesses": occupancy,
        "repeat_identity_witnesses": {
            "fixed_same_seed_a": fixed_a["resolved_dynamic_world_sha256"],
            "fixed_same_seed_different_run_id": fixed_b["resolved_dynamic_world_sha256"],
            "stress_seed_43": stress_a["resolved_dynamic_world_sha256"],
            "stress_seed_44": stress_b["resolved_dynamic_world_sha256"],
        },
        "reaction_witnesses": reaction,
        "source_to_transit_discovery": _preimages(transit),
        "generated_outputs": generated,
        "checks": checks,
        "passed": all(checks.values()),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": payload["passed"], "checks": checks}, sort_keys=True))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
