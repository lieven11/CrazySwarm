MISSION = {
    "schema_version": 2,
    "roles": {
        "leader": {
            "logical_vehicle_id": "formation-leader",
            "display_name": "Formation Leader",
            "home_m": [-1.0, -0.55, 0.0],
            "task": {
                "task_type": "leader-route",
                "priority": 180,
                "estimated_energy_percent": 15.0,
                "energy_margin_percent": 10.0,
            },
        },
        "follower": {
            "logical_vehicle_id": "formation-follower",
            "display_name": "Formation Follower",
            "home_m": [-1.0, 0.55, 0.0],
            "task": {
                "task_type": "follower-route",
                "priority": 170,
                "estimated_energy_percent": 15.0,
                "energy_margin_percent": 10.0,
            },
        },
    },
    "warning_separation_m": 0.8,
    "critical_separation_m": 0.5,
    "observation_freshness_s": 0.75,
    "child_failure_policy": "LAND_ALL",
}


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=1.0)
    await drone.move_relative(x_m=1.2, duration_s=5.0, frame="home")
    await drone.move_relative(y_m=0.35, duration_s=2.5, frame="home")
    await drone.move_relative(x_m=-0.6, duration_s=3.0, frame="home")
    await drone.hover(duration_s=1.0)
    await drone.land(duration_s=2.0)
