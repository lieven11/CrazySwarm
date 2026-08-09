async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    before = await drone.observe(timeout_s=0.5, required="position")
    await drone.move_relative(x_m=0.1, duration_s=1.0, frame="home")
    after = await drone.observe(timeout_s=0.5, required="position")
    await drone.hover(duration_s=1.0)
    await drone.land(duration_s=2.0)
