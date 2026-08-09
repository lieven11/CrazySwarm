MISSION = {
    "schema_version": 2,
    "roles": {
        "zone_a": {
            "logical_vehicle_id": "coverage-a",
            "display_name": "Coverage A",
            "home_m": [-1.2, 0.0, 0.0],
            "zone": {
                "minimum_m": [-1.5, -0.3, 0.0],
                "maximum_m": [-0.9, 0.3, 0.5],
            },
            "task": {
                "task_type": "persistent-zone-coverage",
                "priority": 200,
                "estimated_energy_percent": 40.0,
                "energy_margin_percent": 15.0,
            },
        },
        "zone_b": {
            "logical_vehicle_id": "coverage-b",
            "display_name": "Coverage B",
            "home_m": [1.2, 0.0, 0.0],
            "zone": {
                "minimum_m": [0.9, -0.3, 0.0],
                "maximum_m": [1.5, 0.3, 0.5],
            },
            "task": {
                "task_type": "persistent-zone-coverage",
                "priority": 190,
                "estimated_energy_percent": 40.0,
                "energy_margin_percent": 15.0,
            },
        },
        "reserve": {
            "logical_vehicle_id": "coverage-reserve",
            "display_name": "Coverage Reserve",
            "home_m": [0.0, -1.5, 0.0],
            "initial_role": "RESERVE",
        },
    },
    "warning_separation_m": 0.75,
    "critical_separation_m": 0.5,
    "observation_freshness_s": 1.0,
    "child_failure_policy": "CONTINUE_HEALTHY",
}


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.observe(timeout_s=0.5)
    await drone.hover(duration_s=20.0)
    await drone.land(duration_s=2.0)
