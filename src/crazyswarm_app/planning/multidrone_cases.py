from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.safety.policy import FlightVolume


class MultiDroneCaseVariant(StrEnum):
    MULTI_CONFLICT = "MULTI_CONFLICT"
    MERGE = "MERGE"
    BOTTLENECK = "BOTTLENECK"
    UNEQUAL_PRIORITY = "UNEQUAL_PRIORITY"
    CONSTRAINED_BORDER = "CONSTRAINED_BORDER"


class MultiDroneCaseDefinition(ContractModel):
    schema_version: Literal[1] = 1
    case_id: Identifier
    variant: MultiDroneCaseVariant
    mission_filename: str
    mission_source: str
    mission_source_sha256: SHA256
    flight_volume: FlightVolume
    role_priorities: dict[Identifier, int]
    expected_pair_conflicts: int = Field(ge=1)
    maximum_planned_wait_s: float = Field(gt=0.0)
    minimum_predicted_separation_m: float = Field(gt=0.0)
    objective_order: tuple[Identifier, ...] = (
        "hard_feasibility",
        "priority_inversion",
        "maximum_wait",
        "total_wait",
        "fairness_spread",
    )
    case_sha256: SHA256

    @model_validator(mode="after")
    def identities_match(self) -> MultiDroneCaseDefinition:
        source_sha256 = hashlib.sha256(self.mission_source.encode("utf-8")).hexdigest()
        if self.mission_source_sha256 != source_sha256:
            raise ValueError("multi-drone case source hash does not match source")
        payload = self.model_dump(mode="python", exclude={"case_sha256"})
        if self.case_sha256 != canonical_sha256(payload):
            raise ValueError("multi-drone case hash does not match its contract")
        return self


def generate_multi_drone_cases() -> tuple[MultiDroneCaseDefinition, ...]:
    specifications = (
        (
            MultiDroneCaseVariant.MULTI_CONFLICT,
            ((-1.2, 0.0), (0.0, -1.2), (-0.848528, -0.848528)),
            (200, 150, 100),
            FlightVolume(),
            0.75,
            0.40,
        ),
        (
            MultiDroneCaseVariant.MERGE,
            ((-1.2, 0.0), (-0.6, -1.03923), (-0.6, 1.03923)),
            (180, 160, 140),
            FlightVolume(),
            0.75,
            0.40,
        ),
        (
            MultiDroneCaseVariant.BOTTLENECK,
            ((-1.2, 0.0), (0.0, -1.2), (-0.848528, -0.848528)),
            (150, 150, 150),
            FlightVolume(
                minimum_m=Vector3(x=-1.35, y=-1.35, z=0.0),
                maximum_m=Vector3(x=1.35, y=1.35, z=0.8),
            ),
            0.75,
            0.40,
        ),
        (
            MultiDroneCaseVariant.UNEQUAL_PRIORITY,
            ((-1.2, 0.0), (0.0, -1.2), (-0.848528, -0.848528)),
            (300, 120, 20),
            FlightVolume(),
            0.75,
            0.40,
        ),
        (
            MultiDroneCaseVariant.CONSTRAINED_BORDER,
            ((-1.1, 0.0), (0.0, -1.1), (-0.777817, -0.777817)),
            (200, 150, 100),
            FlightVolume(
                minimum_m=Vector3(x=-1.2, y=-1.2, z=0.0),
                maximum_m=Vector3(x=1.2, y=1.2, z=0.65),
            ),
            0.65,
            0.35,
        ),
    )
    return tuple(
        _case(variant, homes, priorities, volume, warning, critical)
        for variant, homes, priorities, volume, warning, critical in specifications
    )


def _case(
    variant: MultiDroneCaseVariant,
    homes: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    priorities: tuple[int, int, int],
    volume: FlightVolume,
    warning_separation_m: float,
    critical_separation_m: float,
) -> MultiDroneCaseDefinition:
    source = _mission_source(
        variant=variant,
        homes=homes,
        priorities=priorities,
        volume=volume,
        warning_separation_m=warning_separation_m,
        critical_separation_m=critical_separation_m,
    )
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    payload = {
        "schema_version": 1,
        "case_id": f"multi-{variant.value.lower().replace('_', '-')}-v1",
        "variant": variant,
        "mission_filename": f"multi_{variant.value.lower()}_v1.py",
        "mission_source": source,
        "mission_source_sha256": source_sha256,
        "flight_volume": volume,
        "role_priorities": {
            "route_alpha": priorities[0],
            "route_beta": priorities[1],
            "route_gamma": priorities[2],
        },
        "expected_pair_conflicts": 3,
        "maximum_planned_wait_s": 45.0,
        "minimum_predicted_separation_m": warning_separation_m + 0.05,
        "objective_order": (
            "hard_feasibility",
            "priority_inversion",
            "maximum_wait",
            "total_wait",
            "fairness_spread",
        ),
    }
    return MultiDroneCaseDefinition(
        **payload,
        case_sha256=canonical_sha256(payload),
    )


def _mission_source(
    *,
    variant: MultiDroneCaseVariant,
    homes: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    priorities: tuple[int, int, int],
    volume: FlightVolume,
    warning_separation_m: float,
    critical_separation_m: float,
) -> str:
    role_data = tuple(
        (
            role_id,
            vehicle_id,
            home,
            priority,
            -2.0 * home[0] / 12.0,
            -2.0 * home[1] / 12.0,
        )
        for role_id, vehicle_id, home, priority in zip(
            ("route_alpha", "route_beta", "route_gamma"),
            ("multi-alpha", "multi-beta", "multi-gamma"),
            homes,
            priorities,
            strict=True,
        )
    )
    roles = "\n".join(
        f'''        "{role_id}": {{
            "logical_vehicle_id": "{vehicle_id}",
            "display_name": "{variant.value.title()} {role_id}",
            "home_m": [{home[0]:.7f}, {home[1]:.7f}, 0.0],
            "zone": {{
                "minimum_m": [
                    {volume.minimum_m.x:.2f}, {volume.minimum_m.y:.2f},
                    {volume.minimum_m.z:.2f}
                ],
                "maximum_m": [
                    {volume.maximum_m.x:.2f}, {volume.maximum_m.y:.2f},
                    {volume.maximum_m.z:.2f}
                ],
            }},
            "task": {{
                "task_type": "multi-conflict-route",
                "priority": {priority},
                "estimated_energy_percent": 18.0,
                "energy_margin_percent": 10.0,
            }},
        }},'''
        for role_id, vehicle_id, home, priority, _, _ in role_data
    )
    branches = "\n".join(
        (
            f'        {"if" if index == 0 else "elif"} drone.role == "{role_id}":\n'
            f"            await drone.move_relative(\n"
            f"                x_m={dx:.7f}, y_m={dy:.7f}, "
            'duration_s=1.2, frame="home"\n'
            f"            )"
        )
        for index, (role_id, _, _, _, dx, dy) in enumerate(role_data)
    )
    return f"""MISSION = {{
    "schema_version": 2,
    "roles": {{
{roles}
    }},
    "warning_separation_m": {warning_separation_m:.2f},
    "critical_separation_m": {critical_separation_m:.2f},
    "observation_freshness_s": 1.0,
    "child_failure_policy": "LAND_ALL",
}}


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=1.0)
    for _ in range(12):
{branches}
    await drone.hover(duration_s=0.5)
    await drone.land(duration_s=2.0)
"""
