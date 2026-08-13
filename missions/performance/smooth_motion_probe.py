"""Long continuous traverses for dashboard motion-cadence profiling."""


async def mission(drone):
    await drone.takeoff(height_m=0.35, duration_s=2.5)
    await drone.move_relative(x_m=0.5, y_m=0.3, duration_s=5.0, frame="home")
    await drone.hover(duration_s=1.0)
    await drone.move_relative(x_m=-0.5, y_m=-0.3, duration_s=5.0, frame="home")
    await drone.land(duration_s=2.5)
