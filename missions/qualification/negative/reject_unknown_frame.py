async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.move_relative(x_m=0.2, duration_s=2.0, frame="map")
    await drone.land(duration_s=2.0)
