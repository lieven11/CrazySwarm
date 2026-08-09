# Fast Sim physical model v2

> Navigation: [documentation index](../README.md)

## Status and claim boundary

`crazyflie-6dof@2.0.0` is the default Fast Sim plant. It is a deterministic,
reduced-order engineering model with `CONFIGURED_UNQUALIFIED` parameters. It is not a
digital twin and it does not authorize physical flight, endurance claims, controller
gain transfer, or exact-aircraft performance claims.

The implementation is in Fast Sim. No live Isaac implementation is implied. A future
Isaac backend should consume the same versioned vehicle parameters and apply the same
rotor forces; detailed contact, friction, bounce, tumble, and rendered sensors remain
Isaac-side work.

## Command and powertrain semantics

The actuator input has one meaning: a value from 0 to 1 is normalized desired motor
thrust. It is not raw PWM. Fast Sim records applied PWM separately.

For model v2, each step performs the following bounded calculation:

1. Interpolate battery open-circuit voltage from the configured state-of-charge table.
2. Convert desired thrust to required motor voltage by numerically inverting the pinned
   cubic Crazyflie 2.1+ firmware curve.
3. Divide required motor voltage by filtered terminal voltage to obtain PWM and clamp it.
4. Solve `V_terminal = V_OCV - I_total * R_effective` with a bracketed deterministic
   load-line solve.
5. Enforce per-motor current and total battery-current limits.
6. Re-evaluate motor voltage, target thrust, available thrust, current, and saturation.
7. Apply first-order actuator response and Coulomb-count the consumed charge.
8. Apply persistent undervoltage cutoff or immediate depleted-energy cutoff.

This allows compensation to preserve hover thrust while PWM and current headroom exist.
At low charge, PWM and current rise. Once voltage/current/PWM limits bind, maximum thrust
falls. At zero state of charge, an authoritative `DEPLETED` cutoff prevents sustained
positive thrust. If cutoff occurs while airborne, Fast Sim continues the zero-thrust rigid
body through ground impact and publishes the settled fault sample before command failure.

High-frequency PWM ripple, commutation ripple, and electrical measurement noise are not
resolved at the 100 Hz reference physics step. Reported current is an averaged model.

## Rotor and mass properties

The default rotor layout is the firmware-compatible X configuration. Per-rotor forces
use explicit body-frame position and thrust-axis vectors. Moments are computed as
`(rotor_position - combined_center_of_mass) × rotor_force`, with explicit reaction-torque
signs.

Base and payload center of mass are combined by mass weighting. Diagonal payload inertia
and point-mass offsets are combined using the parallel-axis theorem. Per-motor thrust,
current, and time-constant scales provide deterministic degradation and unit variation.

## Sensors and aerodynamics

The IMU has an independent sample clock and held-sample semantics. Optional latency,
per-axis bias, bias random walk, white noise, scale error, small-angle misalignment,
filtering, and clipping are modeled. All default error coefficients are zero, so the
default IMU remains exact. Snapshot polling returns the held sample and cannot create
new noise. Configured gyro error reaches the estimator/controller angular-rate state.

Flow and six-direction range observations have their own configurable sample clocks,
latency buffers, source timestamps, and held-sample semantics. Flow velocity quality is
a reduced-order function of height, tilt, horizontal motion/blur, declared surface and
lighting classes, mounting yaw, dropout, and configured noise. Range preserves explicit
`VALID`, `NO_HIT`, `CLIPPED`, `STALE`, and `UNAVAILABLE` states with configured bias and
beam scope. Barometric altitude is explicitly unsupported for the selected profile.

The normal `ESTIMATOR_IN_LOOP_REFERENCE` profile integrates sampled IMU attitude,
Flow-derived horizontal velocity, and Flow/range-derived ground distance. Its controller
position and velocity are therefore sensor-derived; current physics position is retained
only as simulator comparator evidence. This is a deterministic reduced-order estimator,
not the Crazyflie firmware Kalman estimator. `IDEAL_TRUTH_TEST_ONLY` remains available
only for analytic tests.

The plant uses body-axis linear and quadratic drag. Quadratic coefficients default to
zero. A bounded reduced-order ground-effect term exists but defaults to disabled because
no exact-aircraft qualification evidence is available. Wind, inter-vehicle wake, CFD,
blade-resolved vibration, RPM, and crash/contact dynamics are outside this model.

## Parameter provenance

The executable default config carries provenance groups. Firmware-derived X geometry,
motor curve, thrust bounds, and reaction torque are pinned to Bitcraze firmware release
`2026.04`. The battery voltage table is the firmware's generic single-cell LiPo curve.
Existing mass, inertia, actuator, resistance, current, and drag values remain project
configuration baselines. None has been promoted to measured or hardware-qualified.

Later bench measurements are imported with
`scripts/import_fast_sim_calibration.py`. Import creates an immutable
`2.0.0-cal.<hash>` model version and new configuration identity; it never overwrites the
configured-unqualified default. Imported values remain unqualified until the separate
Reality review promotes their evidence.

## Compatibility

Old behavior is available only through `PhysicsModelConfig.legacy_v1()`, which produces
`crazyflie-6dof@1.0.0`, the plus layout, and the uncoupled thrust/battery model. Model v1
and v2 configurations have different version and configuration identities. A v1 version
cannot be paired with v2 powertrain/layout semantics without validation failure.

Schema-v1 scenario files that omit a physics block are migrated explicitly to the legacy
v1 plant when loaded. This preserves their canonical identity and outcome evidence. New
v2 scenario files must carry an explicit v2 physics block; they cannot silently reinterpret
an old scenario.

The simulator adapter contract remains `1.0.0`; command frames and units did not change.
The richer modeled motor and battery fields are additions to telemetry.

## Evidence

The machine-readable software report is
[`config/qualification/fast-sim-physical-v2.json`](../../config/qualification/fast-sim-physical-v2.json).
It contains 168 powertrain cases, 6 mechanical/actuator cases, 15 seeded sensor cases,
the model-v1/model-v2 comparison, finite-duration/performance evidence, and a normalized
report SHA-256 of
`b8a8ad321ef3314e5ba96c2b8f747f134260275098dfa0dafb082f5f0dbdec37`. Measured
wall time and throughput remain recorded but are excluded from normalized identity so
equivalent qualification content hashes identically across repeated runs.
Focused analytic and invariant tests are in
[`tests/simulation/test_physical_fidelity_v2.py`](../../tests/simulation/test_physical_fidelity_v2.py).
The v1 report remains in place and is not relabeled as v2 evidence.
