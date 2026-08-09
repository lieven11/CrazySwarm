async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    eval("1 + 1")
    await drone.land(duration_s=2.0)
