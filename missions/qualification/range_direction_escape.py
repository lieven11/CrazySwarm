async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    observation = await drone.observe(timeout_s=0.5, required="front_range")
    if observation.ranges.front_m < 0.6 and observation.ranges.front_m < observation.ranges.back_m and observation.ranges.front_m < observation.ranges.left_m and observation.ranges.front_m < observation.ranges.right_m:
        await drone.move_relative(x_m=-0.2, duration_s=2.0, frame="body")
    elif observation.ranges.back_m < 0.6 and observation.ranges.back_m < observation.ranges.left_m and observation.ranges.back_m < observation.ranges.right_m:
        await drone.move_relative(x_m=0.2, duration_s=2.0, frame="body")
    elif observation.ranges.left_m < 0.6 and observation.ranges.left_m < observation.ranges.right_m:
        await drone.move_relative(y_m=-0.2, duration_s=2.0, frame="body")
    elif observation.ranges.right_m < 0.6:
        await drone.move_relative(y_m=0.2, duration_s=2.0, frame="body")
    await drone.hover(duration_s=1.0)
    await drone.land(duration_s=2.0)
