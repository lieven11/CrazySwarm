# Reality WP-04 through WP-06 physical qualification procedure

> Navigation: [documentation index](../README.md)

Status: software and procedure prepared; no radio access, motor command, or physical
flight has been performed by the 2026-08-06 unattended implementation run.

## What is implemented

`CrazyflieVehicle` implements the same `Vehicle` boundary used by the Fast Simulator
and mock Isaac gateway. The same reviewed Python mission bytes are parsed by the same
restricted runtime, pass through `MissionContext`, `SafetySupervisor`, canonical command
envelopes, and the evidence-bearing `MissionRunner`, then reach a backend-specific command
mapping. The current real mapping is:

| Canonical command | Provisional Crazyflie mapping | Completion evidence |
|---|---|---|
| arm/disarm | firmware supervisor arming request | supervisor bitfield |
| takeoff | high-level commander absolute-height takeoff | elapsed command duration plus telemetry/supervisor state |
| hover | retain the last high-level planner setpoint | continuous fresh telemetry for the requested duration |
| HOME move | high-level relative `go_to` | elapsed duration plus telemetry |
| BODY move | rotate displacement with latest measured yaw, then relative `go_to` | measured-yaw input and telemetry |
| land/controlled abort | high-level land to zero | elapsed duration plus supervisor/telemetry state |
| emergency stop | firmware supervisor emergency stop | supervisor disarmed state; props-off evidence by default |

The mapping ID is `cf21-flow-hlc-relative-v1-provisional`. It must remain provisional
until the exact firmware/controller/estimator combination passes WP-04 bench review.
It must not be described as trajectory-equivalent to Fast Sim.

Construction is inert. The adapter never scans, connects, arms, or sends a motor-affecting
command automatically. Connection requires a complete Crazyradio URI, verifies the URI
returned by cflib, requires CRTP protocol 12 or later, and measures both
`deck.bcFlow2` and `deck.bcMultiranger` as nonzero. Commands require a matching,
unexpired permit. A props-off permit permits only arm, disarm, and emergency-stop tests;
takeoff/move/land require an accepted contained-flight entry record.

## Reality statement

The software can now preserve the same Python source and normalized mission intent on the
real-adapter path. That is not evidence that hovering or trajectories are physically the
same. Fast Sim uses a configured estimator/controller/physics approximation. The real
Crazyflie uses its onboard firmware, Flow2, Multi-ranger, IMU, actual airframe, batteries,
surface, light, and radio. External physical trajectory accuracy remains unavailable until
a synchronized independent reference is qualified and held-out runs pass.

## WP-04 onsite bench sequence

Do this only with a named operator present. For all initial steps remove every propeller,
physically restrain the airframe, isolate the work area, and keep a direct power-removal
path available.

1. Inspect and record aircraft identity, radio URI/address, visible condition, deck
   mounting/revisions, motors, propeller set, battery IDs, takeoff mass, and center of mass.
2. Record the exact host OS/Python/cflib, Crazyradio, STM32 firmware, nRF firmware,
   controller, estimator, and relevant parameter set. Replace every
   `CONFIGURED_UNQUALIFIED` field in the bench template with measured evidence; do not
   infer a firmware version from cflib.
3. If the URI is unknown, run only the explicit discovery command while onsite:

   ```bash
   .venv/bin/python scripts/discover_crazyflies.py --scan
   ```

   Discovery does not connect or arm. Select one exact URI and record it before continuing.
4. Run one observation-only cycle, inspect the record, then scale to the required 100 cycles:

   ```bash
   .venv/bin/python scripts/observe_crazyflie_bench.py \
     --vehicle-id cf01 \
     --uri radio://0/80/2M/E7E7E7E701 \
     --expected-firmware REPLACE_WITH_MEASURED_VERSION \
     --cycles 1 \
     --sample-duration-s 2 \
     --confirm "PROPS REMOVED OPERATOR PRESENT AIRFRAME RESTRAINED" \
     --output evidence/wp04-connect-cycle-001.json
   ```

   This tool never installs a command permit and therefore cannot arm. Wrong URI, identity,
   firmware, protocol, or deck presence must fail closed.
5. Measure receive-side state/attitude/range/battery/link rates, latency, jitter, loss,
   maximum gaps, TOC availability, queue bounds, reconnect behavior, CPU/memory, radio
   removal, reboot, stale/malformed values, and source-clock reset behavior. One configured
   log rate is not evidence of an achieved rate.
6. Execute the static sensor matrix with at least 30 samples per point/condition:

   - Flow surfaces: patterned matte baseline, low texture, dark, reflective, and one
     deliberately rejected surface.
   - Lighting: measured baseline plus defined low/high safe conditions.
   - Heights: geometry check, then 0.10, 0.20, 0.30, 0.50, and 0.80 m where safely fixtured.
   - Ranges: 0.20, 0.50, 1.00, 2.00 m and no target; light/dark/reflective/angled/edge targets.
   - Attitude fixtures: level and surveyed plus/minus 10 degrees roll/pitch.

   Derive uncertainty, clipping, no-hit, dropout, rate, latency, and surface/light limits.
   Invalid/no-hit remains `None` with an explicit status and never becomes zero or clear.
7. Under a separately reviewed props-off command procedure, create a short-lived
   `PROPS_OFF_BENCH` permit and test arm, disarm, and emergency-stop translation. Confirm
   supervisor state physically and in telemetry. A timeout is `UNKNOWN_OUTCOME`; never retry
   it automatically and never infer motor-off from silence.
8. Measure and review both ground and onboard watchdog behavior. In particular, establish
   what the exact firmware does when the Python worker dies, the application dies, the radio
   is removed, or acknowledgements disappear while the high-level controller is active.
   Ground recovery cannot be credited for a total link loss. WP-05 stays blocked until a
   safe onboard outcome or an explicitly accepted residual risk is documented.
9. Freeze the completed `BenchQualificationRecord`, evidence bundle hash, review identity,
   and every open anomaly. Acceptance requires 100 cycles, both decks, all pinned versions,
   static/timing/reconnect tests, props-off commands, inspection, and zero open anomalies.

## WP-05 contained-flight sequence

The immutable trial plan is
`config/qualification/reality-physical-plan-v1.json`. Before every session, create an
unexpired `PhysicalFlightEntryRecord` containing a named operator and observer, site risk
assessment, exclusion zone, containment, emergency plan, stop criteria, airframe/deck/
battery inspection, accepted WP-04 evidence, exact QF hashes, Fast Sim/mock dry-run receipt
hashes, and external-reference qualification where required.

Run the three conservative takeoff/hover/land shakedowns first. Stop after any anomaly.
Only then execute the required QF repetitions and batteries in the plan. QF-05 is limited
to 0.10 m/s against a large surveyed flat obstacle. QF-06 uses surveyed single-obstacle
placements. QF-09 tests controlled cancellation and abort-and-land. QF-10 remains props-off;
airborne motor cutoff is not required. Physical QF-11 is optional and needs its own procedure.

The live launcher validates the bench record, entry record, current frozen source hashes,
and an exact onsite confirmation phrase before constructing the cflib link:

```bash
.venv/bin/python scripts/run_physical_qualification.py QF-01 \
  --bench-record evidence/wp04-bench-accepted.json \
  --flight-entry-record evidence/wp05-session-001.json \
  --run-id wp05-qf01-bat01-trial01 \
  --confirm "OPERATOR AND OBSERVER PRESENT IN APPROVED CONTAINMENT" \
  --output evidence/wp05-qf01-bat01-trial01.json
```

Never batch unattended flights. A human reviews the aircraft, battery, containment, video,
telemetry, and anomalies after every run. Freeze failures and aborts as well as successes;
do not overwrite evidence or retry before root-cause review.

Without a qualified external reference, accepted WP-05 results can only be classified
`FUNCTIONAL_HARDWARE_BASELINE_ONLY`. Onboard estimate cannot validate itself.

## WP-06 cross-source gate

The evaluator requires exact mission-source and normalized-intent identity per QF, complete
immutable evidence, disjoint calibration and held-out validation run IDs, and a held-out
real run with qualified external alignment before it can issue
`GO_ISAAC_PHYSICAL_MODEL`. Measured model parameters require evidence IDs; all others stay
`CONFIGURED_UNQUALIFIED`. Every accepted calibration creates a new immutable configuration
hash and model ID; Fast Sim v1 history and safety limits are never mutated automatically.

The current decision is `GO_ARCHITECTURE_AND_MOCK`: WP-00 through WP-03 pass, but WP-04
and WP-05 physical evidence does not exist. This permits contract/mock NVIDIA work only.
It does not authorize live Isaac, an Isaac physical model, real flight, or DIGITAL_TWIN.

Run the current no-radio readiness evaluator with:

```bash
.venv/bin/python scripts/evaluate_reality_wp04_06.py
```

`DIGITAL_TWIN` remains disabled even after WP-06. A later gate must accept synchronized
real/external/simulator comparison, uncertainty, held-out residual tolerances, and prove the
simulator is observation-only and cannot command, correct, or stop the aircraft.
