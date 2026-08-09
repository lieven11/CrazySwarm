async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    while True:
        await drone.hover(duration_s=1.0)
    await drone.land(duration_s=2.0)
