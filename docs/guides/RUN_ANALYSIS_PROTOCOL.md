# Run analysis protocol

> Navigation: [documentation index](../README.md)

Use this procedure to interpret one retained mission execution or compare a bounded
tuning change without loading an entire telemetry CSV into the analysis context. The
CSV contract remains [`RUN_TELEMETRY_CSV_V1.md`](../reference/RUN_TELEMETRY_CSV_V1.md);
the grouped evaluator contract remains
[`MISSION_EXECUTION_EVALUATION_V1.md`](../reference/MISSION_EXECUTION_EVALUATION_V1.md).
This guide explains how to use them rather than redefining either contract.

## Efficient read order

1. Run `python scripts/summarize_run.py <mission-folder-or-telemetry.csv>`.
2. Read `manifest.json` to bind the mission execution, case, plan, submission,
   configuration/artifact identities, status, and checksums.
3. Read the compact evaluation for evidence completeness, mission disposition,
   per-vehicle metrics, fleet separation, inherited/new faults, and terminal state.
4. Read the campaign analysis only for its independent oracles, processed/raw gate
   reconciliation, root-cause classification, motion-quality vector, and missing or
   failed guards.
5. Read the execution bundle only when command, acknowledgement, plan, fleet-event,
   state-transition, or accepted-authority detail is needed.
6. Inspect row-level CSV only for the named vehicles, signals, phases, and exact source
   time windows implicated by the preceding evidence.

The CSV is derived telemetry, not the complete evidence source. A successful mission
status does not repair missing evidence, and a complete evaluation does not turn
modeled Fast Sim values into physical measurements.

## Evidence checks before interpretation

- Confirm manifest, evaluation, analysis, and CSV mission-execution identities agree.
- Confirm advertised content hashes and row counts when present.
- Keep `run_id`, `vehicle_id`, backend/mode, configuration hash, plan hash, submission
  hash, seed, and clock mode fixed or explicitly identify every difference.
- Treat estimated position and `ground_truth_*` as separate signals. Blank truth is
  unavailable truth, not zero and not permission to substitute the estimate.
- Use simulation/source time for single-vehicle dynamics. Use the evaluator's declared
  aligned fleet time for multi-vehicle separation.
- Group samples by `source_clock_id` and `source_clock_epoch`. A reset increments the
  epoch; never calculate a derivative or duration across an epoch boundary.
- Treat unavailable optional columns as missing evidence. Do not silently fill them.
- Reconcile raw exact-CSV extrema with filtered/resampled metrics for hard dynamics,
  safety, contact, and terminal claims.

## Mission-focused observations

| Mission question | Primary evidence | Useful CSV signals |
|---|---|---|
| Hover stability | drift, steady speed ripple, attitude/body-rate activity, motor balance, energy | position/truth, velocity, attitude, IMU angular velocity, motor PWM/thrust/saturation, battery |
| Point/target arrival | target and touchdown error, terminal speed/reversals, capture/contact state | position/truth, velocity, state, flying, motor output |
| Level or 3D route | tracking RMS/max, path-tube error, speed compliance, acceleration, jerk, unintended stops | source time, position/truth, velocity, IMU acceleration/angular velocity |
| Altitude transition | vertical tracking/rate, transition ripple, motor headroom, voltage sag, landing separation | Z position/truth, vertical velocity, motor thrust/headroom/saturation, voltage/current |
| Shape/continuous traversal | path adherence, knot-speed preservation, fly-through stops, terminal behavior | position/truth, velocity, motor and attitude signals |
| Multi-drone coordination | aligned minimum separation and pair, warning/critical samples, timing/authority transitions | per-vehicle time/position plus fleet events from the bundle |
| Fault or recovery | inherited versus new faults, detection/response time, missing telemetry/acks, fallback and terminal state | faults, clocks/sequences, state, transport fields; commands/acks from the bundle |
| Replanning | sensed-event time, reaction budget, old/new plan authority, cutover, clearance and fallback | telemetry window plus event/command/ack/certificate records from the bundle/analysis |

## Tuning-to-evidence map

Runtime parameter bounds and mutability are defined by
`src/crazyswarm_app/simulation/parameters.py`. All current Fast Sim coefficients remain
`CONFIGURED_UNQUALIFIED` until physical evidence qualifies them.

| Parameter | Expected primary effect | Inspect first | Important confounders |
|---|---|---|---|
| `sim.max_horizontal_speed_m_s` | route time and horizontal speed cap | horizontal speed, duration, tracking/path error | safety retiming, authored time law |
| `sim.max_vertical_speed_m_s` | climb/descent time and vertical cap | vertical speed, Z tracking, duration | landing/takeoff windows |
| `sim.max_acceleration_m_s2` | responsiveness versus smoothness | acceleration, jerk, overshoot, terminal peaks | trajectory continuity and filtering |
| `sim.position_noise_std_m` | estimate scatter | estimate-versus-truth error and localization quality | truth availability, smoothing |
| `sim.flow_drift_std_m_sqrt_s` | accumulated localization drift | estimate/truth error over time, flow quality/status | resets and mission duration |
| `sim.range_noise_std_m` | clearance-observation stability | directional ranges/status and independent clearance | no-hit semantics, geometry |
| `sim.physics.mass_kg` | required collective thrust and energy | motor thrust/PWM, current, voltage, tracking | payload/CoM and thrust limit |
| `sim.physics.max_motor_thrust_n` | actuator authority/headroom | available thrust, saturation, tracking | mass, battery voltage, motor health |
| `sim.physics.motor_time_constant_s` | actuator lag and transient response | tracking lag, acceleration, jerk, terminal settling | time step and controller/time law |
| `sim.physics.linear_drag_n_s_m` | speed decay and energy loss | speed profile, duration, thrust/current | route geometry and target speed |
| `sim.physics.battery_capacity_ah` | modeled endurance | battery decline and integrated energy | initial state of charge and load |

## Bounded comparison procedure

Follow `REQ-WFL-006` through `REQ-WFL-012` in
[`ITERATION_AND_TUNING.md`](../project/requirements/workflow/ITERATION_AND_TUNING.md):

1. Freeze exact baseline artifact identities and declare one causal hypothesis.
2. Predeclare the primary metric, safety/quality guards, repeat policy, acceptance
   threshold, plateau condition, and revert rule.
3. Change one bounded parameter family. Keep mission/case, submission, backend/model,
   seed policy, clock semantics, and unrelated configuration fixed.
4. Screen the generated artifact and analytic/static gates before executing runs.
5. Use isolated deterministic repeats, then one distinct stress/coupling case.
6. Compare the complete metric vector, not only the desired improvement.
7. Retain failed candidates and rejection reasons; accept only when the primary goal
   and every non-regression gate pass.
8. Stop on success, plateau, exhausted bounds, or an undeclared trade-off. Request the
   minimum meaningful realtime/operator rerun after software acceptance.

## Reporting template

Record a compact result with:

- question and causal hypothesis;
- exact baseline and candidate identities;
- evidence completeness and missing signals;
- affected vehicle/phase/source-time windows;
- primary metric and all guards, with raw/processed reconciliation where relevant;
- supported finding, counter-evidence, and earliest causal owner;
- accepted/rejected/inconclusive disposition and reason;
- retained limitations and the next evidence needed.

Do not infer physical-aircraft performance, controller transfer, contact fidelity, or
digital-twin validity from a Fast Sim CSV.
