import os


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.land(duration_s=2.0)
