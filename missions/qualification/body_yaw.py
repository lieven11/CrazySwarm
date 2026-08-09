async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.move_relative(x_m=0.2, duration_s=2.0, frame="body")
    await drone.move_relative(yaw_rad=1.5707963267948966, duration_s=3.0, frame="body")
    await drone.move_relative(x_m=0.2, duration_s=2.0, frame="body")
    await drone.hover(duration_s=1.0)
    await drone.land(duration_s=2.0)
