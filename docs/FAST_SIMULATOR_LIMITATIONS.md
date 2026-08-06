# Fast Simulator physical and calibration limitations

Fast Sim release v1 is software-qualified, not hardware-qualified. Every mass,
inertia, rotor, thrust, torque, actuator, drag, battery, controller, sensor, noise,
latency, and environment coefficient is `CONFIGURED_UNQUALIFIED` until controlled
bench/flight evidence proves otherwise. Modeled values must never be described as
measured aircraft data.

## Open physical calibration work

| Area | Current support | Open physical evidence |
| --- | --- | --- |
| Mass, center of mass, inertia | versioned configured rigid body | weigh the exact airframe/payload and measure/identify center of mass and inertia with uncertainty |
| Motors and propellers | configured thrust/torque curves and first-order actuator lag | calibrated thrust stand across command, voltage, motor, propeller, temperature, wear, and unit variation; RPM remains unsupported |
| Aerodynamics | configured linear drag | identify nonlinear/body-axis drag, ground/ceiling/wall effect, prop wash, vortex effects, and inter-vehicle wake interaction |
| Battery and power | configured capacity, load/current, voltage sag, cutoff | characterize actual cells, internal resistance, discharge, recovery, temperature, aging, connector loss, and controller current |
| Flight controller | deterministic high-level tracking controller | compare firmware/controller versions, estimator/controller latency, saturation, gain scheduling, overshoot, and settling |
| IMU | configured rate, noise, bias, clipping | measure per-axis bias/noise, scale, alignment, bandwidth, vibration, temperature drift, and timestamp latency |
| Optical flow | Flow-like body velocity, height, quality model | calibrate deck optics, surface/lighting dependence, motion blur, height limits, drift, dropout, alignment, and latency |
| Multi-ranger | ideal geometry intersection plus configured noise/limits | calibrate beam shape, material/angle response, cross-talk, minimum/maximum range, bias, dropout, mounting transform, and latency |
| Localization | seeded model estimate | validate the actual estimator/deck/mocap source, alignment, covariance, drift, reset behavior, loss/recovery, and source clocks |
| Radio/transport | fixed modeled latency and seeded packet loss | real RF propagation, RSSI/link quality, interference, congestion, jitter, retries, USB latency, and disconnection behavior; no physical radio metric is emitted in SIM |
| Contact/crash | floor/room/obstacle detection with deterministic termination | collision impulse, bounce, friction, deformation, prop strike, tumble, damage, and post-contact sensor behavior are not resolved |
| Environment | configured static room and obstacles | survey geometry/alignment uncertainty, moving objects, airflow, temperature, pressure, lighting, surface properties, and room variability |
| Multi-vehicle | identity-scoped independent dynamics and faults | aerodynamic interaction, wake, ranging/radio contention, perception occlusion, collision response, and synchronized real clocks |

## Unsupported output claims

Fast Sim does not currently support propeller RPM, camera imagery, object
classification, photorealistic reconstruction, physical RSSI, RF propagation,
transport jitter, resolved contact forces, crash survivability, aerodynamic wash,
or externally measured ground truth. Unsupported fields remain absent.

The configured room is evidence about the selected configuration, not proof that a
physical room matches it. Flow is relative and drift-prone. Model ground truth is
truth only inside that simulator run; it is not an external measurement.

## Qualification boundary

Software tests establish determinism, fixed-step convergence, analytic reference
agreement, signal/frame consistency, fault repetition, performance bounds, and
evidence integrity. They do not validate physical predictive accuracy. Physical
qualification requires separately authorized hardware packets, traceable equipment,
controlled procedures, uncertainty bounds, and immutable measured evidence.

Until then, DIGITAL_TWIN remains disabled, physical residuals/calibration stay open,
and Fast Sim is used for mission logic, safety paths, UI, replay, failure injection,
CI, and operator rehearsal within these limitations.
