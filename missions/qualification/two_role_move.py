MISSION = {
    "schema_version": 2,
    "roles": {
        "left": {
            "logical_vehicle_id": "drone-left",
            "home_m": [-0.8, 0.0, 0.0],
        },
        "right": {
            "logical_vehicle_id": "drone-right",
            "home_m": [0.8, 0.0, 0.0],
        },
    },
}


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    if drone.role == "left":
        await drone.move_relative(x_m=-0.1, duration_s=1.0, frame="home")
    else:
        await drone.move_relative(y_m=0.1, duration_s=1.0, frame="home")
    await drone.land(duration_s=2.0)
