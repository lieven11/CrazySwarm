async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    initial = await drone.observe(timeout_s=0.5, required="position")
    await drone.move_relative(x_m=0.3, duration_s=2.0, frame="home")
    await drone.move_relative(x_m=-0.3, duration_s=2.0, frame="home")
    final = await drone.observe(timeout_s=0.5, required="position")
    await drone.checkpoint()
    await drone.land(duration_s=2.0)
