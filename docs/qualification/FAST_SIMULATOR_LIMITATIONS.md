# Fast Simulator physical and calibration limitations

> Navigation: [documentation index](../README.md)

Fast Sim physical model v2 is software-qualified, not hardware-qualified. Every mass,
inertia, rotor, thrust, torque, actuator, drag, battery, controller, sensor, noise,
latency, and environment coefficient is `CONFIGURED_UNQUALIFIED` until controlled
bench/flight evidence proves otherwise. Modeled values must never be described as
measured aircraft data.

The v2 equations, provenance, command semantics and compatibility boundary are described
in [`FAST_SIM_PHYSICS_V2.md`](../reference/FAST_SIM_PHYSICS_V2.md). Canonical schema-v1 scenarios and
the architecture-only Isaac mock remain pinned to the preserved v1 plant.

## Reality WP-03 software boundary

The normal operator profile is now `ESTIMATOR_IN_LOOP_REFERENCE`. Its controller
receives an explicit estimated control state; physics ground truth is structurally
separate and is used only for simulator evidence/comparison. The old ideal-truth
controller path remains `IDEAL_TRUTH_TEST_ONLY` for analytic tests and cannot be the
normal operator or twin profile.

The reference estimator consumes independently sampled and held IMU, Flow, and range
observations. It integrates IMU attitude, Flow-derived horizontal velocity, and
Flow/range-derived ground distance before applying configured drift, bias, noise,
latency, clipping, and reset behavior. Current physics position is comparator evidence,
not the normal v2 controller position source. Flow quality responds to height, tilt,
motion blur, declared surface/lighting class, mounting, latency, noise, and dropout.
These are deterministic engineering models, not emulation of Bitcraze firmware,
PMW3901 image processing, or Kalman estimator internals. Snapshot polling reuses the
latest source sample and does not draw new noise or alter later dynamics.

Canonical range observations are front/back/left/right/up plus Flow down, with
explicit `VALID`, `NO_HIT`, `CLIPPED`, `STALE`, and `UNAVAILABLE` states. A stale,
clipped, or unavailable required range fails closed. Surface and lighting labels
only select declared quality scales; they do not claim optical or material fidelity.
Barometric altitude is explicitly unsupported and remains absent.

The out-of-process `MockIsaacSimVehicle` qualifies the gateway contract and failure
semantics without Isaac, ROS, RTX hardware, or a network service. It is not evidence
that Isaac Sim itself is installed, functional, or physically accurate.

## Open physical calibration work

| Area | Current support | Open physical evidence |
| --- | --- | --- |
| Mass, center of mass, inertia | versioned configured rigid body | weigh the exact airframe/payload and measure/identify center of mass and inertia with uncertainty |
| Motors and propellers | firmware-sourced cubic motor-voltage/thrust curve, X geometry, PWM saturation, averaged current and first-order actuator lag | calibrated thrust stand across command, voltage, motor, propeller, temperature, wear, and unit variation; RPM remains unsupported |
| Aerodynamics | body-axis linear/quadratic drag; bounded ground effect implemented but disabled by default | identify drag valid ranges and qualify ground/ceiling/wall effect, prop wash, vortex effects, and inter-vehicle wake interaction |
| Battery and power | OCV table, Coulomb counting, resistive load-line solve, current limit, filtered compensation, persistent/depleted cutoff | characterize actual cells, internal resistance, discharge, recovery, temperature, aging, connector loss, and controller current |
| Flight controller | deterministic estimator-in-loop reference controller; ideal truth is test-only | compare firmware/controller versions, estimator/controller latency, saturation, gain scheduling, overshoot, and settling |
| IMU | configured rate, noise, bias, clipping | measure per-axis bias/noise, scale, alignment, bandwidth, vibration, temperature drift, and timestamp latency |
| Optical flow | Flow-like body velocity, height, quality model | calibrate deck optics, surface/lighting dependence, motion blur, height limits, drift, dropout, alignment, and latency |
| Multi-ranger | ideal geometry intersection plus configured noise/limits | calibrate beam shape, material/angle response, cross-talk, minimum/maximum range, bias, dropout, mounting transform, and latency |
| Localization | stateful seeded estimate with drift, bias, latency and clipping | validate the actual estimator/deck/mocap source, alignment, covariance, drift, reset behavior, loss/recovery, and source clocks |
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
