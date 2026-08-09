MISSION = {
    "schema_version": 2,
    "roles": {
        "route_alpha": {
            "logical_vehicle_id": "multi-alpha",
            "display_name": "Multi Route Alpha",
            "home_m": [-1.2, 0.0, 0.0],
            "task": {
                "task_type": "multi-conflict-route",
                "priority": 200,
                "estimated_energy_percent": 18.0,
                "energy_margin_percent": 10.0,
            },
        },
        "route_beta": {
            "logical_vehicle_id": "multi-beta",
            "display_name": "Multi Route Beta",
            "home_m": [0.0, -1.2, 0.0],
            "task": {
                "task_type": "multi-conflict-route",
                "priority": 150,
                "estimated_energy_percent": 18.0,
                "energy_margin_percent": 10.0,
            },
        },
        "route_gamma": {
            "logical_vehicle_id": "multi-gamma",
            "display_name": "Multi Route Gamma",
            "home_m": [-0.848528, -0.848528, 0.0],
            "task": {
                "task_type": "multi-conflict-route",
                "priority": 100,
                "estimated_energy_percent": 18.0,
                "energy_margin_percent": 10.0,
            },
        },
    },
    "warning_separation_m": 0.75,
    "critical_separation_m": 0.4,
    "observation_freshness_s": 1.0,
    "child_failure_policy": "LAND_ALL",
}


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=1.0)
    for _ in range(24):
        if drone.role == "route_alpha":
            await drone.move_relative(x_m=0.1, duration_s=0.8, frame="home")
        elif drone.role == "route_beta":
            await drone.move_relative(y_m=0.1, duration_s=0.8, frame="home")
        else:
            await drone.move_relative(
                x_m=0.0707107,
                y_m=0.0707107,
                duration_s=0.8,
                frame="home",
            )
    await drone.hover(duration_s=0.5)
    await drone.land(duration_s=2.0)
