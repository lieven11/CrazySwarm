async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    for step in range(4):
        observation = await drone.observe(timeout_s=0.5, required="front_range")
        if observation.ranges.front_m <= 0.6:
            break
        await drone.move_relative(x_m=0.1, duration_s=1.0, frame="body")
    await drone.hover(duration_s=2.0)
    await drone.move_relative(x_m=-0.2, duration_s=2.0, frame="body")
    await drone.land(duration_s=2.0)
