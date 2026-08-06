"""Minimal source-backed mission for the first simulator workflow."""


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=3.0)
    await drone.land(duration_s=2.0)
