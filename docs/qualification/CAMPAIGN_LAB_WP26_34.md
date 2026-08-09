# Mission development laboratory WP-26 through WP-34

| Field | Value |
|---|---|
| Status | `IMPLEMENTED_AND_QUALIFIED` |
| Default development case | `SIM / three_drone_multi_conflict` |
| Fleet-size boundary | One to three drones; no larger fleet unless separately required |
| Normal development backend | Fast Sim |
| Physical flight authorized | No |
| Package order | WP-26, WP-27, WP-28, WP-29, WP-30, WP-31, WP-32, WP-33, WP-34 |
| Implementation milestones | WP-26A, WP-27, WP-31A, WP-26B, WP-28, WP-29A, WP-29B, WP-30, WP-31B, WP-32, WP-33, WP-34A, WP-34B |

The implementation and qualification evidence is recorded in
[`CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md`](CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md).

## Product rule

The operator declares goals, hard constraints, allowed strategy families, and
optimization preferences. The planner chooses and explains the trajectory and launch
schedule. A mission case must not encode arbitrary instructions such as “Drone B
hovers for 20 seconds” unless hovering itself is the behavior under test.

Until another case is explicitly selected, development and regression comparisons use
the canonical three-drone multi-conflict mission. All packages remain limited to at
most three drones.

Hard constraints always take precedence over optimization:

1. remain inside the declared flight volume and altitude limits;
2. satisfy dynamics and critical-separation limits with uncertainty margins;
3. preserve required battery reserve;
4. reach every required goal and accepted terminal state; and
5. retain exact plan, trajectory, case, configuration, and evidence identities.

Feasible plans are then compared lexicographically by priority inversion, starvation,
mission completion time, maximum wait, total energy, airborne hover time, path length,
acceleration/jerk, and separation/boundary robustness. The exact order is part of the
immutable case rather than a hidden UI default.

Every acceptance threshold is either numeric in this roadmap or a required, unit-bearing
field in the immutable case or qualification profile. A package may freeze a tighter
threshold after baseline measurement, but it may not close with subjective wording such
as “materially better” or with an unversioned tolerance.

## Pipeline-first execution policy

The catalog may define many missions and variations without flying them. Registration,
schema/hash validation, compilation, boundary/dynamics checks, and deterministic
planning previews do not create telemetry and do not count as mission execution.

At any time, one immutable case is the `ACTIVE_DEVELOPMENT` case for the workspace. The
normal loop is:

1. select or define one case;
2. lock its case hash, seed, backend/profile, configuration hash, planner implementation
   and settings, and comparison-baseline hash;
3. run it accelerated, operator-observed realtime, or both;
4. collect plan, CSV, bundle, evaluator, timing diagnostics, and operator observations;
5. make one bounded implementation change;
6. rerun the same locked case; and
7. promote it or explicitly select a different case.

Changing any locked comparison input creates a new child case or development series; it
does not silently replace the active case. WP-26 through WP-30 qualify against the one
active case and at most one explicitly selected secondary case
(`maximum_development_execution_cases=2`). Unit, property, synthetic-fault, compilation,
and planning-only fixtures are not restricted by that execution budget. No catalog
variation, robustness matrix, recommendation, or dynamic case runs merely because it
was registered or discovered.

Mission lifecycle is mutable metadata stored separately from the immutable case:

| State | Meaning |
|---|---|
| `DEFINED_NOT_RUN` | Case is registered and has no execution history. |
| `READY` | Static validation and planning/admission preview passed; still not run. |
| `ACTIVE_DEVELOPMENT` | Operator selected this exact case for the iterative loop. |
| `BASELINED` | At least one accepted run and review are bound as its comparison baseline. |
| `PROMOTED` | Required hard gates and operator approval passed for its declared claim. |
| `BLOCKED` | A recorded prerequisite, planning, authorization, or implementation reason prevents progress. |

Lifecycle transitions record operator/service identity, UTC time, previous/new state,
case hash, reason, and evidence/review hashes. They never mutate the case itself.

## CSV feasibility trial: 2026-08-09

The two retained `three_drone_multi_conflict` CSVs are sufficient to reconstruct
observed motion, launch and route timing, battery use, 3-D separation, straightness,
altitude use, terminal state, and source-versus-wall-clock behavior. They are not
sufficient by themselves to prove why a strategy was selected, which alternatives
were rejected, or which flight-volume and objective contract applied. The campaign
analyzer must therefore join the CSV with the immutable case, accepted plan, manifest,
and execution bundle.

| Observation | Successful run | Later run |
|---|---:|---:|
| Mission status | `SUCCEEDED` | `ABORTED` |
| CSV telemetry rows | 8,245 | 11,208 |
| All three began takeoff | within 0.32 s | within 0.26 s |
| Airborne wait before route: Alpha | 1.54 s | 1.56 s |
| Airborne wait before route: Beta | 20.99 s | 20.99 s |
| Airborne wait before route: Gamma | 40.44 s | 40.43 s |
| Battery used: Alpha / Beta / Gamma | 5.67% / 10.17% / 14.71% | 5.67% / 10.17% / 14.68% |
| Minimum truth separation | 0.844 m | 0.844 m |
| Gamma source-time / wall-time ratio | 0.829 | 0.810 |
| Gamma terminal state | `READY` | `EMERGENCY` |

The current three-drone planner selected `EXACT_ENUMERATION_STAGING`, which only
permutes full-route precedence. All drones took off first; Beta and Gamma then spent
most of their delay flying at the staging position. This preserved separation but
wasted battery and expanded a nominal 24.7-second mission to approximately 77 seconds.

The successful run's ground-truth cruise paths stayed in one layer at approximately
0.300 m and remained within 5-9 mm of their straight reference lines. The later run
reproduced the same source-clock paths to sub-millimetre RMS agreement. It did not
exercise a lateral curve or vertical layer.

Source-clock cruise speed was approximately 0.124 m/s with a standard deviation of
0.003-0.004 m/s. A 0.5-second source-clock smoothing pass produced cruise 95th-percentile
acceleration below 0.009 m/s2 and jerk below 0.028 m/s3. These values show that CSV
analysis is viable, but they do not by themselves explain a visually bumpy display.

Wall-clock evidence delivery contained route gaps of approximately 0.66-1.15 seconds.
The later run progressed at only about 0.81 source seconds per wall second and exceeded
Gamma's 78.54-second watchdog by approximately 0.10 seconds, producing
`MISSION_TIMEOUT` during landing. The CSV transport latency of 30 ms and packet loss of
0% are explicitly `SIMULATED_MODEL` values, not measurements of the browser, host, or
Internet connection. Host, API/WebSocket delivery, browser rendering, and actual
network delay therefore require separate instrumentation.

The existing evaluator's very large acceleration and jerk peaks must not be used as a
smoothness gate in their current form. It differentiates vehicle speed using
`recorded_at_utc`; clustered or delayed wall-clock events inflate the result. Per-vehicle
kinematics must use the source/simulation clock, while fleet separation continues to
use aligned recorded UTC.

## WP-26 — Evidence-correct mission analyzer and timing integrity

**Objective:** turn a mission case, plan, execution bundle, evaluator report, and CSV
into one reproducible analysis without mixing clock domains, then instrument the live
path deeply enough to locate display and runtime timing faults.

**Depends on:** WP-18 through WP-20, WP-24, and WP-25 retained evidence contracts.

### WP-26A — Offline analyzer correctness

**Deliverables**

- A typed analysis result with mission outcome, source and wall durations, real-time
  factor, launch/route/landing timeline, battery use, 3-D paths, boundary margins,
  pair separation, tracking error, stops, acceleration, and jerk.
- Source/simulation time for per-vehicle kinematics; aligned recorded UTC for fleet
  separation; explicit resampling and smoothing parameters in the result identity.
- A comparison report that distinguishes planner/controller motion from evidence or UI
  delivery jitter.
- Import by persisted mission-execution ID or by operator-supplied manifest/bundle/CSV
  set, so dashboard and historical runs can be analyzed without rerunning them.
- One primary root-cause classification plus optional contributors from `PLANNER`,
  `TRAJECTORY`, `CONTROLLER`, `SIM_TIMING`, `EVIDENCE_DELIVERY`, `UI_RENDERING`,
  `LANDING`, and `UNKNOWN`. Every classification carries confidence in `0.0..1.0`,
  evidence references, counter-evidence, and a human-readable reason.
- Landing comparison among the accepted goal/landing region, planned arrival and
  descent points, estimated and truth touchdown, and—when WP-26B/WP-32 diagnostics are
  present—the displayed goal marker.

**Exit gate**

- Reproduce telemetry row counts exactly, battery use within 0.01 percentage point,
  event times within one source sample, and minimum separation within 0.005 m for the
  two trial runs.
- Classify the later Gamma failure as a wall-watchdog `MISSION_TIMEOUT` without
  misclassifying it as a separation or path-planning failure, with confidence at least
  0.90 and direct watchdog/fault evidence.
- Eliminate clock-induced false acceleration/jerk peaks and add regression tests for
  irregular, delayed, duplicated, and missing telemetry samples.
- Import one existing operator-run bundle and produce a review-ready analysis without
  starting a new mission.
- Never treat the CSV alone as complete qualification evidence.

### WP-26B — Runtime and display timing instrumentation

**Deliverables**

- Separate source-stamped channels for simulator step/real-time factor, controller and
  command completion, recorder commit, API/WebSocket enqueue and delivery, browser
  receipt, render-frame cadence, playback-buffer age, and dropped/coalesced samples.
- Correlation IDs that follow one sample from simulator production to browser render.
  Modeled vehicle transport remains a distinct channel and is never relabeled as host
  or Internet latency.
- A bounded diagnostic trace that can be attached to an operator-started run without
  changing flight authority or qualification evidence.

**Exit gate**

- Inject a simulator slowdown, WebSocket delivery burst, and browser-frame stall in
  separate tests and classify each correct stage with confidence at least 0.90.
- Added instrumentation changes accelerated-run throughput by no more than 5% and
  remains bounded by a versioned retention/sample limit.
- Accepted, actual, and displayed landing coordinates are reported in one world frame
  with the conversion chain identified.

**Out of scope:** planner behavior changes and the WP-32 playback repair itself.

## WP-27 — Campaign case contract and mission catalog

**Objective:** define the immutable input to the iterative mission-development loop.

**Depends on:** WP-23 curriculum identities and WP-25 robustness case identities.

**Deliverables**

- Backend-neutral behavior templates with immutable JSON/YAML cases rather than many
  nearly identical Python missions.
- The operator hierarchy `Simulation|Real -> one|two|three drones -> family -> case`.
- SI units in field names and an explicit coordinate frame on every spatial value.
  Stored mission geometry uses `world`; `home` inputs are converted during compilation
  and the transform becomes part of the case evidence.
- A field classification of `HARD_CONSTRAINT`, `OPTIMIZATION_PREFERENCE`, or
  `EXECUTION_SETTING`; a preference can never override a hard constraint.
- Case fields for room/flight volume, start/landing regions, goal sequences, deadlines,
  separation, dynamics, noise/latency profile, seed, repetitions, clock mode, hover
  permission/limit, vertical-layer permission, fairness, allowed planner strategies,
  objective order, and per-drone battery, minimum reserve, health, priority, roles, and
  required/available capabilities.
- Every base mission definition names its purpose and behavior under test, drone count
  and roles, exact start/intermediate/final/landing regions, hard constraints, permitted
  resolution strategies, objective order, expected planner decision or accepted decision
  set, pass/fail metrics, eligible execution modes (`STATIC_VALIDATE_ONLY`,
  `AUTOMATED_ACCELERATED`, `OPERATOR_OBSERVED_REALTIME`, or `BOTH`), operator observation
  questions, difficulty, prerequisites, and bounded named variations.
- Parent/child case identity, baseline identity, and explicit Sim/Real environment,
  backend, evidence, and authorization profiles.
- A separate lifecycle/run-history record implementing `DEFINED_NOT_RUN`, `READY`,
  `ACTIVE_DEVELOPMENT`, `BASELINED`, `PROMOTED`, and `BLOCKED`. Lifecycle updates and
  active-case selection never change case content or identity.
- A saved operator preset whose default case is the canonical three-drone
  multi-conflict mission.
- Versioned schema migration that retains the original bytes/hash, creates a new
  migrated identity, records the migration implementation/version, and never silently
  rewrites an existing case.
- Catalog discovery restricted to validated case manifests in this repository shape:

  ```text
  missions/
  ├── library/{one_drone,two_drone,three_drone}/<family>/mission.py
  └── campaigns/
      ├── sim/{environments,profiles,cases,baselines}/
      └── real/{qualification_profiles,authorized_cases,evidence}/
  ```

  Discovery does not import arbitrary Python files and rejects duplicate case IDs.
- A case may tighten the selected global safety policy but may never weaken it. A wider
  volume or looser safety limit requires a separately versioned environment/policy
  profile and its normal authorization path.

**Exit gate**

- Changing any material parameter changes the case hash.
- The same behavior template compiles for Sim and an unauthorized Real mirror without
  duplicating mission logic.
- Invalid volumes, unsafe thresholds, more than three drones, and unsupported strategy
  combinations fail before execution.
- Round-trip and migration fixtures preserve units, frames, hard/preference classes,
  source identity, and deterministic hashes across every supported schema version.
- Catalog discovery produces the same ordered case list on repeated runs and rejects
  symlink escapes, unknown files, duplicate IDs, and unvalidated manifests.
- Registering and statically validating cases produces no mission run, telemetry, or
  baseline. A baseline is required only for transition to `BASELINED` or `PROMOTED`, not
  for `DEFINED_NOT_RUN` or `READY`.

**Out of scope:** executing campaigns and granting Real-flight authority.

## WP-28 — Ground-first launch scheduling and energy accounting

**Objective:** remove the assumption that every drone must take off before it is
needed.

**Depends on:** WP-26, WP-27, and the bounded WP-24 three-drone scheduler.

**Deliverables**

- Candidate actions for ground delay, just-in-time arm/takeoff, short declared airborne
  stabilization, airborne staging only when required, and synchronized launch only
  when the mission requires it.
- Separate accounting for ground wait, airborne hover, route energy, landing reserve,
  wall watchdog, and source schedule.
- Required case/profile thresholds `maximum_unrequired_airborne_wait_s` (default
  2.0 s), `maximum_equal_route_battery_spread_percent` (default 1.0 percentage point),
  `minimum_realtime_factor` (default 0.80), and `watchdog_guard_s` (default 2.0 s).
- Launch readiness checks that revalidate battery, health, volume occupancy, and the
  current reservations immediately before delayed takeoff.
- Plan rationale showing why ground wait or airborne staging was selected or rejected.
- Development execution uses the locked `ACTIVE_DEVELOPMENT` case; other launch
  schedules are exercised with planning-only or synthetic fixtures unless the operator
  explicitly selects the one permitted secondary case.

**Exit gate**

- In the canonical three-drone case, Beta and Gamma remain non-flying until their
  planned launch windows unless a case explicitly requires simultaneous takeoff.
- Non-required airborne waiting is no more than
  `maximum_unrequired_airborne_wait_s=2.0`.
- In the equal-route canonical case, the largest battery-use difference among roles is
  no more than `maximum_equal_route_battery_spread_percent=1.0` percentage point.
- Predicted minimum separation is at least warning separation plus configured position
  uncertainty (0.80 m in the canonical case); observed truth separation is at least
  the 0.75 m warning threshold with zero warning/critical samples. The historical
  0.844 m value is a comparison baseline, not a mandatory geometry constraint.
- At a forced `minimum_realtime_factor=0.80`, watchdog duration is derived from the
  admitted source schedule as at least
  `schedule_duration_s / minimum_realtime_factor + watchdog_guard_s`, and all three
  roles reach their required terminal states without timeout.
- No newly registered WP-33 catalog variation is executed as part of this gate.

**Out of scope:** curved detours and vertical layers.

## WP-29 — Constraint-driven three-dimensional conflict planner

**Objective:** compare meaningful joint alternatives for up to three drones instead of
only permuting full-route staging.

**Depends on:** WP-26 through WP-28 and the WP-22/WP-24 prediction contracts.

The planner claims only the best feasible result among the deterministically generated,
bounded candidate set. It does not claim a global optimum over arbitrary continuous
multi-agent trajectories.

### WP-29A — Candidate framework and joint validation

**Deliverables**

- Joint candidate families for direct flight, ground delay, airborne staging, speed
  retiming, horizontal detour, vertical layer, and combined timing/3-D changes, with
  geometry families registered behind one typed candidate interface.
- Hard checks for flight volume, altitude, dynamics, separation with uncertainty,
  battery reserve, goals, and terminal state for every candidate.
- Global three-drone reservations and conflict checking. Pairwise-feasible candidates
  that create a third-drone conflict are rejected.
- Deterministic lexicographic scoring plus selected and rejected candidate explanations.
- Versioned search limits: `prediction_step_s` no greater than 0.02 s,
  `maximum_candidate_count` default 256, and `planning_budget_s` default 5.0 s. The
  retained bounded candidate set and any deterministic truncation to the configured
  maximum are included in the plan identity.
- If the planning budget expires before every retained candidate is completely
  validated and ranked, the result is `BLOCKED` and contains no execution authority.

**Exit gate**

- Joint validation rejects constructed pairwise-safe/third-drone-unsafe cases and every
  injected volume, dynamics, battery, goal, and reservation violation.
- Repeated planning returns byte-identical retained candidates, ranking, rationale, and
  hashes. Budget expiry fails closed; the maximum-candidate fixture deterministically
  truncates before validation and reports that boundary.

### WP-29B — Horizontal, vertical, and combined geometry

**Deliverables**

- Bounded lateral spline, Bezier, arc-around-conflict-tube, and corridor-following
  generators; no hard-coded single parabola.
- Bounded vertical-layer and combined timing/geometry generators with explicit sampled
  offset/radius/factor grids stored in the case/profile identity.
- Rationale that records every generator attempted, its bounded parameters, feasibility,
  cost vector, and exact rejection reason.

**Exit gate**

- Wide, nominal, compact, unequal-priority, bottleneck, and constrained-height cases
  each pass deterministic compilation/planning-only validation and select a feasible
  strategy or give a precise blocking reason; this gate does not fly all six cases.
- A wide-volume case exposes at least one feasible curved or layered alternative to
  full sequential staging.
- A constrained-height case rejects vertical candidates while still considering
  horizontal/timing candidates.
- Allow/forbid controls are authoritative and reflected in plan hashes and evidence.
- Every selected result states “optimal among the bounded generated candidates” and
  reports candidate count, diagnostic-only search duration, truncation status, and
  sampled resolution. Wall-clock search duration is not part of the deterministic plan
  hash.
- Telemetry qualification executes only the locked active case and, when explicitly
  selected, one secondary geometry case; all remaining geometry coverage is static,
  property-based, or synthetic.

**Out of scope:** sensed-object avoidance, mapping, SLAM, and fleets larger than three.

## WP-30 — Smooth trajectory generation and execution

**Objective:** make smoothness an enforced planning and execution property for straight
and curved routes.

**Depends on:** WP-26, WP-29, and the WP-20 trajectory contract.

**Deliverables**

- Continuous position, velocity, and acceleration across route knots and detour entry/
  exit, with configurable jerk limits and no unintended internal stops.
- Time allocation that respects horizontal/vertical speed, acceleration, and jerk
  limits after candidate geometry is chosen.
- A versioned smoothness profile whose canonical Fast Sim defaults are maximum planned
  acceleration 1.0 m/s2, maximum planned jerk 8.0 m/s3, stop-speed threshold 0.02 m/s,
  unintended-stop persistence 0.20 s, maximum source-clock observed acceleration p95
  1.0 m/s2, and maximum source-clock observed jerk p95 8.0 m/s3. Declared holds, the
  initial trajectory endpoint, and accepted goal capture are excluded from unintended-
  stop counting.
- Explicit route-to-arrival and arrival-to-descent transitions. Descent is admitted only
  after goal-region capture, commanded position/velocity are continuous at the cutover,
  and terminal horizontal error, vertical error, and speed are independently checked.
- Source-clock planned-versus-observed speed, acceleration, jerk, curvature, tracking,
  and stop metrics with percentile and peak views.
- Separate planner gates for geometric/temporal continuity and dynamics, and controller
  gates for source-clock tracking RMS/maximum error, observed unintended stops, terminal
  velocity, and touchdown error. A controller failure cannot be reported as a planner
  failure or vice versa.
- Regression comparison against the same immutable case and backend/seed, plus an
  operator note channel that cannot override hard gates.
- Execution evidence is required only for the active case and optional selected
  secondary case. Other trajectory families may close their construction checks through
  compilation, analytical continuity, sampled dynamics, and planner validation without
  generating mission telemetry.

**Exit gate**

- Every accepted trajectory is C2 at all knots/cutovers, has sampled acceleration no
  greater than 1.0 m/s2 and jerk no greater than 8.0 m/s3, and passes those checks
  before execution.
- Curved and layered plans have zero generated unintended stops. Observed speed may not
  remain at or below 0.02 m/s for 0.20 s between the first and last planned movement,
  except during declared holds or accepted goal capture.
- Canonical Fast Sim tracking RMS is no greater than 0.05 m and maximum error no greater
  than 0.10 m. Touchdown remains within the accepted landing goal's 0.10 m horizontal
  and 0.08 m vertical tolerances with terminal speed no greater than 0.05 m/s.
- Between first and last planned trajectory movement and excluding declared holds,
  takeoff, and landing, WP-26's versioned source-clock resampling/filter reports
  observed acceleration p95 no greater than 1.0 m/s2 and observed jerk p95 no greater
  than 8.0 m/s3.
- Accelerated and realtime source-clock target error, path length, tracking RMS, and
  minimum separation differ by no more than their case fields, each of which is numeric,
  unit-bearing, versioned, and included in the case hash.

**Out of scope:** browser rendering performance and in-flight goal replacement. WP-30
owns the accepted route-to-landing behavior; WP-32 owns whether its marker and region
are displayed at the same coordinates.

## WP-31 — Campaign runner and review queue

**Objective:** provide the half-automatic loop `select -> plan -> run -> analyze ->
review -> rerun/branch`.

**Depends on:** WP-26A and WP-27 for WP-31A; WP-26B and WP-28 through WP-30 for
WP-31B.

### WP-31A — Minimal headless runner and evidence intake

**Deliverables**

- One headless API/service that selects or generates an immutable case, invokes the
  current admitted planner/executor, runs accelerated or realtime, and collects the
  manifest, CSV, bundle, evaluation, and WP-26 analysis.
- Explicit actions `SET_ACTIVE_DEVELOPMENT_CASE`, `RUN_ACTIVE_ACCELERATED`,
  `RUN_ACTIVE_OPERATOR_REALTIME`, `RERUN_ACTIVE_SAME_INPUTS`, and
  `CREATE_CHILD_FROM_ACTIVE`. Exactly one workspace case is active; selection is an
  auditable lifecycle transition and does not start it.
- Two equal evidence paths: operator-observed realtime runs selected in the panel with
  review questions/notes, and automated accelerated runs invoked by the service or a
  development chat. Both enter the same analysis and review queue.
- Rerun defaults to the active case's locked case hash, seed, backend/profile,
  configuration, planner/settings, and baseline. Any requested change is previewed and
  creates a child case/development series before execution.
- Automatic intake of dashboard/operator-started terminal missions into the review
  queue, plus idempotent import of an existing manifest/bundle/CSV set without rerun.
- Bounded execution controls: default concurrency 1 and maximum 3, idempotent cancel,
  at most one automatic retry only for a case-declared transient infrastructure class,
  terminal cleanup, startup reconciliation, and resume/review behavior after process
  interruption. Planner/safety/mission failures are never automatically retried as if
  they were infrastructure failures.
- Review approval fields for authenticated operator, UTC timestamp, decision
  `APPROVE|REJECT|NEEDS_RERUN`, report schema/version/hash, reason, and optional note.

**Exit gate**

- Run the current canonical three-drone case and import one historical operator bundle;
  both produce review items without qualification-test internals or duplicate evidence.
- Selecting a different case changes lifecycle metadata but launches nothing. Two
  `RERUN_ACTIVE_SAME_INPUTS` requests bind the same comparison inputs and identify only
  run/evidence identities as new.
- Cancellation before launch grants no command authority; cancellation during execution
  uses the declared safe recovery; restart leaves no orphan worker and preserves every
  terminal/partial artifact.
- Concurrency, retry, cleanup, and interrupted-process tests pass at their declared
  limits.

### WP-31B — Campaign orchestration, comparison, and recommendation

**Deliverables**

- Accelerated coverage followed by optional realtime observation, repetitions, seeds,
  faults, baselines, and case matrices over the WP-31A execution primitive.
- A review item with baseline comparison, planner rationale, rejected alternatives,
  3-D path, separation, boundary, battery, timing, smoothness, fault/recovery timeline,
  and operator observations.
- Actions for rerun same case, create harder child, mark regression, and approve the
  analysis. Hard failures stop promotion automatically.
- The existing WP-25 16-cell robustness matrix as a first-class named campaign, with
  every cell, seed, repetition, hard gate, and retained artifact visible in one result.
  It runs only after explicit operator selection; catalog discovery, recommendation,
  normal startup, and WP-33 registration never trigger it.
- A deterministic recommended-next-case policy, presented for operator approval and
  never auto-executed: first satisfy missing prerequisites; otherwise rerun an unresolved
  failure; otherwise cover an untested hard boundary/allowed strategy; otherwise choose
  the lowest-difficulty unpassed child; otherwise report the campaign complete. The
  decision records inputs, rule, candidates, and recommendation hash.
- Resumable execution with deterministic case/run identities; UI disconnection does
  not cancel an admitted campaign unless requested.

**Exit gate**

- A three-drone campaign can run accelerated plus one realtime observation and produce
  one complete review item through WP-31A.
- The campaign service can materialize the unmodified WP-25 16-cell definition without
  execution and reconcile the existing retained WP-25 evidence. One explicitly
  authorized qualification invocation produces exactly 16 cell outcomes and retains
  all hard-gate reports; it is not part of the normal active-mission loop.
- Dashboard/operator-started runs enter the same review queue automatically, and an
  imported existing bundle is byte-preserved and never executed again.
- Repeating the same case never silently changes its configuration, plan, or baseline.
- Failed/aborted runs remain reviewable evidence and cannot be shown as passed.
- Fixed prerequisite/failure/coverage fixtures produce byte-identical next-case
  recommendations, and no recommendation starts without operator approval.

**Out of scope:** panel presentation and physical execution.

## WP-32 — Campaign panel

**Objective:** expose WP-27 and WP-31 as an operator-friendly mission laboratory.

**Depends on:** WP-27 and WP-31.

**Deliverables**

- Simple preset and bounded advanced modes for hierarchy, room, drones, constraints,
  strategies, objectives, seed/repetitions, and accelerated/realtime selection.
- Mission browser lifecycle badges, history, prerequisites, and a distinct `Set as
  active development mission` action. Selecting or editing a catalog row never launches
  it; Play is available only as a separate authorized action.
- Active-development header showing the locked case, seed, backend/profile,
  configuration, planner/settings, and comparison baseline, with separate buttons for
  automated accelerated run, operator-observed realtime run, same-input rerun, and
  create child case.
- Pre-play plan view with the selected strategy, rejected alternatives, paths/layers,
  predicted margins, duration, energy, and rationale.
- Execution progress and review queue with synchronized 3-D paths and metric plots.
- Clear source-time versus wall-time/UI health indicators so visual stutter is not
  confused with trajectory bumpiness.
- Source-time-buffered display interpolation with `playback_buffer_s` default 0.25 s,
  `maximum_interpolation_gap_s` default 0.20 s, and
  `maximum_extrapolation_s` default 0.10 s. Position and orientation interpolate only
  between valid samples in the same source-clock epoch.
- Delayed, missing, reordered, and coalesced samples remain visible in diagnostics. If
  the interpolation buffer is exhausted or a gap exceeds its limit, the drone freezes
  at the last valid rendered state and the panel shows `DISPLAY_DELAYED`; it does not
  jump forward or extrapolate without bound. Rendering resumes only after the configured
  playback buffer has refilled, using source-time interpolation from the last valid
  state.
- Raw telemetry remains the only evidence input. Interpolated render states are labeled
  presentation-only, are never exported as measured telemetry, and cannot satisfy a
  qualification gate.
- One coordinate pipeline for room geometry, planned trajectory, accepted goal/landing
  region, goal marker, estimate, simulator truth, and rendered drone pose.

**Exit gate**

- The operator can configure and run the canonical three-drone case without editing
  YAML or invoking qualification tests.
- The operator can browse dozens of `DEFINED_NOT_RUN`/`READY` cases without creating a
  run, set one active, execute it through either evidence path, add observations, and
  rerun the exact locked inputs.
- Every advanced input is validated against the case schema and no hidden UI value can
  weaken a hard constraint.
- Under burst delivery of one second with intact source samples, playback either remains
  continuous inside its configured buffer or enters `DISPLAY_DELAYED` without a spatial
  jump. Missing/reordered/coalesced fixtures follow their declared bounded behavior.
- World-space round trips align the accepted goal center, landing-region geometry,
  planned endpoint, and displayed marker within 0.001 m; fixed-camera rendered tests
  align their projected centers within 2 pixels. Estimate and truth remain visibly
  distinct.
- Accessibility, API-adapter, rendering, and end-to-end campaign tests pass.

**Out of scope:** authorizing Real flight.

## WP-33 — Progressive one/two/three-drone campaign library

**Objective:** construct a concrete, progressive catalog of clearly defined one-, two-,
and three-drone missions and variations without automatically executing that catalog.

**Depends on:** WP-27 and WP-31; WP-32 is required for operator-observed promotion.

### Minimum static inventory

Every entry uses the complete WP-27 mission-definition contract. The minimum catalog is
not a promise to execute every entry:

| Drone count | Required reusable base missions |
|---|---|
| One | `takeoff_hover_land`, `move_return`, `continuous_waypoint_sequence`, `curved_route`, `altitude_transition`, `boundary_constrained_route`, `static_multi_goal_sequence`, `failure_recovery` |
| Two | `parallel_routes`, `head_on_conflict`, `perpendicular_crossing`, `merge`, `overtake`, `bottleneck`, `unequal_priority`, `constrained_border_height`, `no_hover_crossing`, `leader_follower`, `formation_spacing`, `role_allocation`, `leader_loss`, `duplicate_assignment_rejection`, `coordination_failure` |
| Three | `single_pair_conflict`, `simultaneous_center_conflict`, `merge`, `bottleneck`, `unequal_priorities`, `constrained_volume`, `alternative_layers_detours`, `role_allocation`, `leader_follower_recovery`, `duplicate_assignment_rejection`, `persistent_coverage_reserve_handover` |

`static_multi_goal_sequence` contains at least three ordered goal regions before its
landing region. Relevant two-/three-drone cases define per-role goal sequences rather
than only one shared endpoint.

### Bounded variation matrix

- Every base mission has one canonical nominal case plus at least two mission-relevant
  named variations selected from compact/nominal/wide volume, constrained height,
  equal/unequal priority, hover allowed/forbidden, vertical separation allowed/forbidden,
  alternate goal order, latency/noise, seed, and declared fault. Variations are explicit;
  the catalog does not generate or execute an uncontrolled Cartesian product.
- `perpendicular_crossing` defines at least
  `compact_equal_priority`, `nominal_equal_priority`, `wide_equal_priority`,
  `wide_alpha_priority`, `compact_no_hover`, `constrained_height`, `vertical_allowed`,
  `vertical_forbidden`, and `latency_and_noise`.
- `simultaneous_center_conflict` defines at least
  `wide_priority_200_150_100` (the canonical case backing the default
  `three_drone_multi_conflict` development mission),
  `compact_equal_priority`, `nominal_equal_priority`, `wide_unequal_priority`,
  `compact_no_hover`, `constrained_height`, `vertical_allowed`, `vertical_forbidden`,
  and `latency_and_noise`.
- Dynamic goal, moving-target, and cascading-replanning definitions are registered in
  lifecycle state `DEFINED_NOT_RUN` with implementation status
  `PLANNED_NOT_EXECUTABLE` and pointers to WP-34. They have no executable authority or
  baseline until an operator explicitly selects one and its corresponding WP-34
  milestone is completed.

### Lifecycle, validation, and promotion

- New static cases start as `DEFINED_NOT_RUN`. Lightweight validation may move them to
  `READY` after schema/hash checks, compilation, exact volume/dynamics checks, role/goal
  completeness, and deterministic planning/admission preview. It does not connect a
  vehicle adapter, advance a simulation clock, create telemetry, or capture a baseline.
- A baseline is required only before `BASELINED` or `PROMOTED`. The catalog may therefore
  contain dozens or hundreds of `DEFINED_NOT_RUN`/`READY` cases.
- Each case declares whether it is eligible for automated accelerated execution,
  operator-observed realtime execution, both, or static validation only. Eligibility is
  not execution authorization.
- Separate Sim profiles and Real mirrors reference the same mission intent. Real cases
  remain visibly `NOT_AUTHORIZED` and cannot transition to active development through
  this software package.
- Persistent coverage defines numeric, unit-bearing
  `handover_trigger_battery_percent`, `minimum_reserve_battery_percent`,
  `maximum_handover_latency_s`, `maximum_coverage_gap_s`,
  `maximum_coverage_gap_percent`, and `minimum_terminal_reserve_percent`. The canonical
  software profile retains the existing 5.0 s maximum handover and 1.0% maximum
  coverage-gap gates. Hard invariants require one owner per task, zero duplicate active
  assignment, deterministic reserve selection, atomic lease generation, incoming
  takeover before outgoing release, safe outgoing return/landing, and accepted terminal
  states for all three drones.

**Exit gate**

- All minimum inventory templates and required named variations exist with immutable
  identities, exact geometry/goals, expected outcomes, hard gates, observation questions,
  prerequisites, difficulty, claim boundaries, and lifecycle state.
- Every static entry passes lightweight validation or records a precise `BLOCKED` reason.
  WP-33 qualification executes zero newly registered missions and creates no new CSV;
  it may reference baselines already produced by the one or two selected development
  cases.
- `DEFINED_NOT_RUN` and `READY` entries require no baseline. Promotion is impossible
  without a passing baseline, required run modes, hard-gate evidence, and operator
  approval.
- Persistent coverage and leader/follower, formation/spacing, role allocation, leader
  loss, and duplicate-assignment families are discoverable with their complete static
  contracts, whether or not the operator has selected them for execution.
- No duplicated Sim/Real mission implementation and no fleet larger than three.

**Out of scope:** physical qualification and new hardware authority.

## WP-34 — Dynamic goals and online replanning

**Objective:** safely replace an active future trajectory when goals or admissible
conditions change.

**Depends on:** WP-26 and WP-29 through WP-31, plus a passing static baseline for the
exact mission family selected for dynamic development. WP-33 registers the dynamic
entries but does not execute them and does not depend on WP-34 results.

### Shared bounded update and cutover contract

- A dynamic catalog entry becomes executable only through an explicit
  `SET_ACTIVE_DEVELOPMENT_CASE` action after the relevant WP-34 implementation is
  available. Catalog discovery, static validation, recommendation, startup, or opening
  the panel cannot activate or run it.
- At most one dynamic case is active for each WP-34 milestone. Qualification telemetry
  is generated only for that selected case; the remaining update, rejection, timeout,
  and fallback coverage uses deterministic component/synthetic fixtures that do not
  connect a mission adapter or create mission CSVs. Selecting a different case is a
  separate audited lifecycle transition.
- Goal updates carry source identity, monotonically increasing sequence, update ID,
  source timestamp, requested effective time, and goal revision. Duplicate IDs are
  idempotent; stale/out-of-order revisions are rejected; accepted updates are rate
  limited by `minimum_goal_update_interval_s` default 0.50 s and the queue retains at
  most the newest pending revision per authority source.
- Replanning uses a case `planning_budget_s` default 2.0 s and hard maximum 10.0 s.
  The triggering observation age must not exceed the mission's configured freshness
  limit and is revalidated before commit.
- While planning, a drone continues its still-valid accepted trajectory only through a
  precomputed safe cutover window. If that future is no longer safe, it executes a
  pre-authorized bounded hold or abort-and-land policy; it never invents an immediate
  stop.
- The replacement defines one exact future source-clock cutover time. Old future
  commands are cancelled and acknowledged before that cutover; the replacement command
  and authority hash are acknowledged before it becomes active.
- Automatic replanning authority is an explicit case policy:
  `OPERATOR_APPROVAL_REQUIRED`, `AUTO_WITHIN_FROZEN_LIMITS`, or
  `ABORT_ONLY`. Automatic approval cannot change hard constraints, strategy permissions,
  or the admitted authority class.

### WP-34A — Single-drone bounded goal replacement

**Deliverables**

- Current measured position/velocity capture, stale-future invalidation, bounded
  candidate generation, approval, and a continuous transition segment into the
  replacement route; the controller must not stop or jump merely because a plan changed.
- Old/new plan, trajectory, reservation, observation, decision, and authority hashes in
  the evidence and review comparison.
- Executable cases for a moving target, one mid-route goal replacement, duplicate/stale
  update rejection, budget expiry, blocked replan, operator-required approval, and
  abort-and-land fallback.

**Exit gate**

- No case executes a stale plan hash. Every accepted cutover is C2, satisfies the WP-30
  dynamics/landing gates, and occurs at its recorded source-clock cutover time within
  one source sample.
- Duplicate and stale updates change no authority; planning-budget/freshness failures
  select the declared safe behavior and retain the cause in evidence.
- The same ordered updates, observations, and seed produce byte-identical replacement
  decisions and plan identities.

### WP-34B — Atomic two-/three-drone replanning

**Deliverables**

- One fleet reservation epoch containing every affected old and replacement route,
  a shared cutover time, validation result, command cancellation/acknowledgement state,
  and commit hash.
- Atomic commit: all affected replacement routes and reservations validate and receive
  authority before any becomes active. If only a subset is feasible or acknowledged,
  none commits; the fleet continues the still-safe old epoch or applies the declared
  all-fleet fallback.
- Deterministic ordering for simultaneous/conflicting goal updates and bounded cascading
  replanning across at most three drones.
- Executable cases for two-drone crossing goal change, simultaneous conflicting updates,
  three-drone cascading replan, partial replacement failure, acknowledgement loss,
  and fleet abort-and-land fallback.

**Exit gate**

- No observer can see mixed old/new reservation epochs as active, and no command from a
  stale epoch executes after the shared cutover.
- Partial feasibility, timeout, cancellation failure, or acknowledgement loss commits
  zero replacement routes and produces the declared safe fleet outcome.
- A three-drone cascading replan is deterministic for the same ordered updates,
  observations, and seed, and satisfies continuity, dynamics, volume, separation,
  battery, landing, and terminal-state gates.
- After WP-34A/B pass, WP-34 publishes a successor catalog version and may capture a new
  baseline only for each explicitly selected and successfully executed dynamic case.
  Every other dynamic entry remains `DEFINED_NOT_RUN` or `READY`, without reopening the
  original WP-33 static qualification.

**Out of scope:** learned/unbounded planners, sensed-object SLAM, and physical flight.

## Ordered implementation rule

WP-26A closes first because current wall-clock smoothness metrics can misdiagnose a
planner change. WP-27 then freezes the input contract, and WP-31A supplies the minimal
headless run/import/review loop used while WP-26B and WP-28 through WP-30 are developed.
WP-28 removes the proven airborne-wait waste; WP-29A freezes bounded joint candidate
validation before WP-29B adds geometry; WP-30 qualifies the resulting trajectories.
WP-31B adds matrices, comparisons, and recommendation, and WP-32 supplies bounded smooth
playback and the operator panel. WP-33 then populates the larger static library as
mostly `DEFINED_NOT_RUN` or `READY`; it runs no newly registered missions and requires
no baseline merely for registration. WP-34A and WP-34B enable bounded dynamic behavior
only for cases explicitly selected as active development missions. Unselected dynamic
catalog entries remain unexecuted and receive no baseline.
