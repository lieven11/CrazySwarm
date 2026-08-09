MISSION = {
    "schema_version": 2,
    "roles": {
        "cross_west": {
            "logical_vehicle_id": "crossing-west",
            "display_name": "Crossing West",
            "home_m": [-1.2, 0.0, 0.0],
            "task": {
                "task_type": "crossing-route",
                "priority": 150,
                "estimated_energy_percent": 15.0,
                "energy_margin_percent": 10.0,
            },
        },
        "cross_south": {
            "logical_vehicle_id": "crossing-south",
            "display_name": "Crossing South",
            "home_m": [0.0, -1.2, 0.0],
            "task": {
                "task_type": "crossing-route",
                "priority": 150,
                "estimated_energy_percent": 15.0,
                "energy_margin_percent": 10.0,
            },
        },
    },
    "warning_separation_m": 0.75,
    "critical_separation_m": 0.4,
    "observation_freshness_s": 1.0,
    "child_failure_policy": "CONTINUE_HEALTHY",
}


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=1.0)
    for _ in range(24):
        if drone.role == "cross_west":
            await drone.move_relative(x_m=0.1, duration_s=0.8, frame="home")
        else:
            await drone.move_relative(y_m=0.1, duration_s=0.8, frame="home")
    await drone.hover(duration_s=0.5)
    await drone.land(duration_s=2.0)
