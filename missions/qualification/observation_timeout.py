async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    observation = await drone.observe(timeout_s=0.2, required="position")
    await drone.land(duration_s=2.0)
