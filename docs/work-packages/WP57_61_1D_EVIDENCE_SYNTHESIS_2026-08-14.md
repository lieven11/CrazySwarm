# WP-57 through WP-61 — 1D evidence synthesis

| Field | Value |
|---|---|
| Source workspace | `.cache/crazyswarm/campaign/workspace-state.json` |
| Workspace SHA-256 | `f26b155cbb8458650e4c2c9d70ff81a701da32a263b6f0112663b696e7c795d1` |
| Reproducible audit | `scripts/audit_wp57_61_design.py` |
| Retained audit | `missions/campaigns/sim/qualification/wp57-61-predraft-1d-evidence-v1.json` |
| Audit payload SHA-256 | `65f7243a5c7bf944570e6758a84dccc060882af8459c310fedb9356136bbea40` |
| Audit file SHA-256 | `5ee24c1382553e3168caa86825208c5c1cf116c3e6e412bcf3f2f4e7d95c0ada` |
| Review boundary | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` for retained realtime runs; `ACCELERATED` for the three retained accelerated repeats; no physical or digital-twin qualification |

## Scope and completeness

The audit read every retained review for a `1d.*` case, every corresponding CSV,
analysis, evaluation, execution bundle, and manifest, every literal operator
observation, and both retained 1D screenshots. It found:

- 28 reviewed runs with complete evidence across 11 executed 1D cases;
- 8 reviews containing operator observations;
- 2 screenshots, both from figure-eight run
  `campaign-run-7e55b398244d31cb6a75`;
- 4 failed, unreviewed altitude-transition run records without review evidence; and
- 20 defined 1D cases in the workspace: 7 promoted, 3 baselined, 1 ready, and 9 not
  run.

The revised audit also verifies nine cross-artifact identity/hash links per reviewed
run and fails a comparison if any declared metric is absent. All 28 link chains and
all five exact same-case/same-clock comparator sets pass structurally. “Pass” here
means usable design evidence, not that a current submission meets a future packet
gate; every literal value and disposition is retained.

The four failed unreviewed records are retained in the JSON audit. They do not become
motion evidence because no completed review/CSV bundle exists. The short operator-
aborted static-multi-goal run remains in the reviewed inventory, but its route metrics
are unavailable and are not interpreted as zeros.

## Operator observations

The exact operator text is retained in the machine artifact. The distinct observations
were:

1. constant-speed conformance needs a percentile/band measure and a separate shakiness
   measure; hard turning may preserve speed/path at the cost of sudden IMU changes;
2. route, speed-profile, acceleration/jerk/shakiness, and path-deviation authority are
   an explicit mission-dependent trade-off that may change in flight;
3. baseline circle, rounded-square, and figure-eight motion visibly slows at fly-through
   nodes; checkpoint motion and continuous motion must remain distinct capabilities;
4. the figure-eight also slows at the geometrically repeated center crossover even
   though the authored route continues through it;
5. the curved-route run accelerates shortly before landing entry;
6. equal-looking motor behavior during forward motion appears physically suspicious;
   and
7. the takeoff/hover/land case should not remain last in the 1D catalog order.

## Neutral evidence assessment

### Constant speed and shakiness are different axes

The circle comparison is the clearest witness. Relative to its baseline, the constant-
path-speed run reduced independently measured route speed p95–p05 ripple from
`0.306 m/s` to `0.052 m/s` (83% lower). At the same time:

- IMU angular-rate p95 increased from `0.131` to `0.329 rad/s` (`2.52×`);
- applied-motor spread p95 increased from `0.139` to `0.470` percentage points
  (`3.38×`);
- tracking RMS changed only from `0.024` to `0.025 m`; and
- no motor saturation or retained unintended stop was reported.

This supports the operator's trade-off observation. A speed-only pass is insufficient,
and a global “smoothness score” would hide which physical quantity changed.

The waypoint smoothness run shows why more than one shakiness proxy is needed. Against
its same-clock realtime baseline it reduced speed ripple from `0.308` to `0.020 m/s`,
acceleration p95 from `0.399` to `0.076 m/s²`, and jerk p95 from about `0.894` to
`0.478 m/s³`. However, angular-rate p95 rose from about `0.126` to `0.154 rad/s`, motor
spread p95 roughly doubled from about `0.126` to `0.252` percentage points, and tracking
RMS rose from `0.019` to `0.029 m`. The separate accelerated baseline produced the same
rounded values but is corroboration, not part of the frozen same-clock comparator.
Translational smoothness improved while attitude/
actuation activity and path tracking did not improve together.

### Baseline knot slowdowns and the figure-eight crossover are measured

For ordinary fly-through knots, median speed within `±0.12 s` of a knot was compared
with median speed `0.35..0.75 s` to either side. Baseline ratios were typically
`0.59..0.85`, quantitatively supporting the reported repeated slowdown/reacceleration.

At the figure-eight's repeated center point, baseline runs produced knot/adjacent speed
ratios of `0.725` and `0.773`. The curvature-continuity run produced `1.00` at that
center. It therefore removed the crossover-specific dip, but did so with a globally
slow `0.08 m/s` profile and a much longer route. That is evidence of a useful mechanism,
not evidence that the current fixed profile is the generally correct policy.

The rounded-square corner-transition run reduced route speed ripple from `0.346` to
`0.014 m/s`, acceleration p95 from `0.277` to `0.042 m/s²`, and jerk p95 from `1.047`
to `0.298 m/s³`; tracking RMS increased from `0.025` to `0.031 m`. Again, smoothness,
time/speed, and path fidelity must be selected together under the mission's bounds.

### Screenshot assessment

Both image hashes match their workspace records and both images were visually
inspected. They show the flown cyan trace and planned dashed figure-eight geometry near
the repeated center. They are useful spatial context but are not independent proof of
speed. Their exact-time CSV samples are:

| Snapshot | Source time | Truth XY (m) | Speed (m/s) | Angular rate (rad/s) | Motor spread (percentage points) |
|---|---:|---:|---:|---:|---:|
| `snapshot-4f49de76ed2cd44f3f92` | 12.88 | `(-0.108,-0.115)` | 0.236 | 0.0036 | 0.0190 |
| `snapshot-cf82bb567011908821a9` | 14.60 | `(0.190,0.225)` | 0.344 | 0.0615 | 0.0159 |

The crossover slowdown occurs near the intervening repeated-center knot. The images
bracket it but do not land exactly on its minimum-speed sample, so the knot-window CSV
measurement—not visual impression—is the retained oracle.

### Motor behavior is differential, but the current presentation obscures it

Twenty-six of the 28 reviewed runs contain moving route evidence in which more than
95% of samples have unequal applied PWM across M1–M4. The two exceptions are the
operator-aborted run and takeoff/hover/land, which have no ordinary route window. The
control mixer in `simulation/physics.py` computes roll and pitch torques and distributes
them across the X-layout motors; the CSV confirms that production Fast Sim consumes
that differential output.

The concern remains valid at the operator boundary: four traces close to roughly 63%
collective can look identical when overlaid or rounded, while the meaningful difference
is often tenths or hundredths of a percentage point. Review must expose per-motor
spread, pitch/roll response, saturation/headroom, and provenance rather than imply
that the current configured model is physically qualified.

### Terminal acceleration is confirmed and remains an open product gate

The curved-route `curve.jerk_first` run reduced whole-route acceleration and jerk
relative to baseline, but whole-route percentiles do not answer the reported short
pre-landing acceleration. The revised raw-CSV audit now defines the terminal approach
as the final authored route segment, reduces duplicate samples to fixed `0.10 s`
source-clock medians, and counts a secondary speed peak when its prominence is strictly
greater than `0.02 m/s`. Baseline and jerk-first runs each contain one such peak, with
prominence `0.151` and `0.107 m/s`, respectively. The observation is therefore
supported, but neither retained run passes the proposed zero-peak product gate.

The audit retains exact pass/fail sensitivity witnesses at `0.019` and `0.021 m/s`,
plus complete numerical prototypes for the WP-58 motion gates, the X-layout WP-60
force/torque and source-alignment oracle, and WP-61 ingestion/calibration bounds. These
synthetic witnesses prove that the thresholds are computable and sensitive; they do
not qualify the missing implementations.

## Per-run metric index

`Speed ripple` is independent velocity-norm p95–p05 over the retained route window.
`Angular` is body angular-rate p95. Acceleration, jerk, tracking, and stop counts come
from the retained analyzer and are shown here for traceability. The abbreviated run ID
is only a display aid; the JSON retains every full identity and file hash.

| Case | Run suffix | Submission | Speed ripple (m/s) | Angular p95 (rad/s) | Accel p95 (m/s²) | Jerk p95 (m/s³) | Motor spread p95 (pp) | Tracking RMS (m) | Stops |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `1d.altitude_transition.canonical_nominal` | `47d54c51` | baseline | 0.292 | 0.198 | 0.399 | 1.420 | 0.149 | 0.017 | 0 |
| `1d.altitude_transition.canonical_nominal` | `5df8dd99` | constant slow | 0.125 | 0.057 | 0.180 | 0.487 | 0.062 | 0.019 | 0 |
| `1d.altitude_transition.canonical_nominal` | `fbe586a3` | constant stress | 0.215 | 0.094 | 0.253 | 0.806 | 0.090 | 0.018 | 0 |
| `1d.altitude_transition.canonical_nominal` | `9a84bcf4` | ramped kinks | 0.247 | 0.140 | 0.293 | 1.161 | 0.185 | 0.021 | 0 |
| `1d.altitude_transition.wide` | `f147b843` | baseline | 0.252 | 0.151 | 0.351 | 1.181 | 0.118 | 0.021 | 0 |
| `1d.altitude_transition.wide` | `9d80a677` | baseline | 0.265 | 0.145 | 0.351 | 1.181 | 0.113 | 0.021 | 0 |
| `1d.altitude_transition.wide` | `6966aebd` | baseline | 0.265 | 0.145 | 0.351 | 1.181 | 0.113 | 0.021 | 0 |
| `1d.altitude_transition.wide` | `9ae113af` | baseline | 0.265 | 0.145 | 0.351 | 1.181 | 0.113 | 0.021 | 0 |
| `1d.continuous_waypoint_sequence.canonical_nominal` | `9f80c0cf` | baseline | 0.308 | 0.127 | 0.399 | 0.893 | 0.127 | 0.019 | 0 |
| `1d.continuous_waypoint_sequence.canonical_nominal` | `904ac0cb` | baseline | 0.308 | 0.125 | 0.399 | 0.895 | 0.124 | 0.019 | 0 |
| `1d.continuous_waypoint_sequence.canonical_nominal` | `51f16d88` | smoothness | 0.020 | 0.154 | 0.076 | 0.478 | 0.252 | 0.029 | 0 |
| `1d.curved_route.canonical_nominal` | `a546c79a` | baseline | 0.285 | 0.094 | 0.343 | 0.731 | 0.091 | 0.020 | 0 |
| `1d.curved_route.canonical_nominal` | `538c18d7` | jerk first | 0.218 | 0.042 | 0.200 | 0.344 | 0.037 | 0.024 | 0 |
| `1d.move_return.canonical_nominal` | `e975bd82` | baseline | 0.433 | 0.017 | 0.147 | 0.147 | 0.027 | 0.021 | 0 |
| `1d.move_return.canonical_nominal` | `bb326abd` | baseline | 0.353 | 0.013 | 0.096 | 0.081 | 0.026 | 0.024 | 0 |
| `1d.planar_shape_loop.circle` | `c6f32a86` | baseline | 0.306 | 0.131 | 0.293 | 0.883 | 0.139 | 0.024 | 0 |
| `1d.planar_shape_loop.circle` | `e4229d25` | constant speed | 0.052 | 0.329 | 0.148 | 0.623 | 0.470 | 0.025 | 0 |
| `1d.planar_shape_loop.figure_eight` | `999c6908` | baseline | 0.288 | 0.144 | 0.314 | 0.753 | 0.175 | 0.025 | 0 |
| `1d.planar_shape_loop.figure_eight` | `31cb6a75` | baseline | 0.290 | 0.145 | 0.314 | 0.760 | 0.176 | 0.025 | 0 |
| `1d.planar_shape_loop.rounded_square` | `30e02072` | baseline | 0.346 | 0.200 | 0.277 | 1.047 | 0.238 | 0.025 | 0 |
| `1d.planar_shape_loop.rounded_square` | `62c5453c` | corner transition | 0.014 | 0.182 | 0.042 | 0.298 | 0.225 | 0.031 | 0 |
| `1d.planar_shape_loop.figure_eight` | `c20dde1d` | curvature continuity | 0.017 | 0.163 | 0.073 | 0.463 | 0.260 | 0.031 | 0 |
| `1d.point_to_point_relocation.canonical_nominal` | `3db0d59b` | baseline | 0.430 | 0.015 | 0.130 | 0.139 | 0.025 | 0.018 | 0 |
| `1d.static_multi_goal_sequence.canonical_nominal` | `bc96a9f5` | baseline | 0.437 | 0.058 | 0.298 | 0.565 | 0.061 | 0.026 | 0 |
| `1d.static_multi_goal_sequence.canonical_nominal` | `23cae3db` | baseline | 0.343 | 0.026 | 0.173 | 0.256 | 0.032 | 0.027 | 0 |
| `1d.static_multi_goal_sequence.canonical_nominal` | `399e94e1` | aborted baseline | unavailable | unavailable | unavailable | unavailable | unavailable | 0.002 | 0 |
| `1d.static_multi_goal_sequence.canonical_nominal` | `80b0477e` | baseline | 0.343 | 0.026 | 0.173 | 0.269 | 0.031 | 0.027 | 0 |
| `1d.takeoff_hover_land.canonical_nominal` | `2fbdb4c1` | baseline | unavailable | unavailable | 0.026 | 0.124 | unavailable | 0.014 | 0 |

## Supported reusable findings

1. **Separate motion intent from trajectory mechanism.** The reusable contract needs
   explicit `CHECKPOINT`, `CONTINUOUS_FLY_THROUGH`, and bounded adaptive behavior. A
   case/submission selects the trade-off; no one profile is the global default.
2. **Evaluate a vector, not one score.** At minimum retain speed-band coverage/ripple,
   knot/crossover continuity, path deviation/tracking, acceleration, jerk, angular
   activity, per-motor spread/headroom/saturation, energy, and terminal behavior.
3. **Plan over the meaningful future geometry.** Repeated points and authored sampling
   density are not semantic corners. Whole-route/horizon curvature and stop intent must
   determine the velocity envelope, with density/rename/reordering perturbations.
4. **Bind changes in flight.** A live change of objective/profile/path authority is a
   source-time, hash-bound replan/cutover with preserved hard constraints and safe
   fallback—not an unrecorded controller toggle.
5. **Keep model truth narrow.** The Fast-Sim mixer is differential, but every coefficient
   remains `CONFIGURED_UNQUALIFIED` until bench/contained-flight evidence closes the
   physical gate.
6. **Add a terminal-specific oracle.** Pre-landing monotonic deceleration, secondary
   peaks, component reversals, landing descent, and contact must be separated.

## Open questions and retained limits

- The two screenshots have no snapshot-level operator comment or neutral assessment in
  workspace state. Their purpose is recoverable only through the run-level note.
- No real-aircraft or live-Isaac data is present in this evidence set. It cannot tune
  physical coefficients or prove real-world smoothness.
- Existing constant/curvature profiles are fixed low-speed examples. They demonstrate
  capability pieces but not the requested mission-aware combined policy.
- The four failed unreviewed altitude records retain failure metadata only and require
  separate evidence if their causes matter to a later claim.
- Hardware learning must use bounded candidate calibration with holdout/cross-mission
  checks and operator promotion. Automatically rewriting the flight controller or
  safety limits from one run is explicitly excluded.
