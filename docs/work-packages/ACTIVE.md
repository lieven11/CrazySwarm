# Active and next work

| Field | Value |
|---|---|
| Document role | The only authoritative ledger for active, next, and blocked work |
| Status | `IMPLEMENTED_WITH_OPEN_GATES_AND_DEFINED_SUCCESSOR_QUEUE` |
| Last reconciled | 2026-08-11 |
| Completed counterpart | [`COMPLETED.md`](COMPLETED.md) |
| Default operator backend | `FAST_SIM` |
| Physical flight authorized | No |
| Digital twin enabled | No |
| Active package | `WP-35 through WP-39 — executable mission curriculum truth repair`; `WP-44 through WP-50` have implemented cores but retain the qualification gaps recorded in the [2026-08-11 audit](WP44_50_IMPLEMENTATION_AUDIT_2026-08-11.md) |
| Ordered next milestones | Close WP-48 peer/uncertainty/realtime gates, author the missing WP-49 successor rows, and rerun the complete WP-50 matrix without weakening the WP-35 through WP-39 queue |
| Immediate next action | Use the retained 19-row matrix as a regression subset, not as proof that the larger required WP-49/WP-50 matrix is complete |
| Operator loop | `SEMI_AUTOMATIC_REALTIME_REVIEW` |
| Catalog policy | `EXECUTION_SEMANTICS_BEFORE_CASE_COUNT` |
| Current development case | `SIM / three_drone_multi_conflict` until the WP-39 catalog cutover |
| Development execution budget | One active case plus at most one explicitly selected secondary case |

## 2026-08-27 — Healthy-radio telemetry-stall recovery fast loop

**Status:** `IMPLEMENTED`

**Independent verification:** `IMPLEMENTED_UNVERIFIED` (fast-loop work; no formal
independent gate requested)

**Frozen baseline:** the live observer closed and reopened its link at
`2026-08-27T19:33:50Z` and `2026-08-27T19:35:28Z`. Both failures were classified as
`TELEMETRY_STALE`; contemporaneous transport reported healthy ACKs, an empty outbound
queue, and zero USB errors. The reconnects restored firmware log delivery without a
firmware-clock reset. Application command volume and RF loss are therefore not the
measured failure boundary.

**Bounded implementation:** after the existing stale grace, and only when transport
classification remains `TELEMETRY_STALE`, stop/delete and recreate the existing cflib
log blocks on the retained radio link. Clear cached log values, require a fresh callback
within a bounded timeout, and journal the repair attempt/result. Permit one repair per
stale episode; if it fails or stalls again within `30 s`, retain the existing full
disconnect/reconnect fallback.
Never apply this recovery to RF loss, queue saturation, USB failure, command execution,
or a suspended observer.

**Exit gate:** injected observer coverage proves successful log repair preserves the
same radio connection, failed repair falls back to exactly one reconnect, and an RF
fade never invokes log repair. Link-level coverage proves old blocks are removed,
fresh telemetry is required, and no connection epoch changes. No live deployment or
physical operation is part of this coding task.

**Author checks:** the combined adapter, observer, commissioning, and physical-twin API
selection passed `110` tests; after the final repeated-stall escalation bound, the
adapter/observer selection passed `72` tests. Ruff, strict mypy on the four changed
production modules, and `git diff --check` passed.

## 2026-08-27 — Physical hover drop / radio-causality fast loop

**Status:** `IMPLEMENTED`

**Independent verification:** `IMPLEMENTED_UNVERIFIED` (fast-loop work; no formal
independent gate requested)

**Operator intent:** keep the improved room-wide Crazyradio connection, determine
whether intermittent physical drops are caused by excessive packet traffic, and stop
the aircraft from waiting in an unstable near-floor/controller-recovery condition.

**Frozen baseline:** the two completed `hover-12s` runs at `2026-08-27T18:18:51Z`
and `2026-08-27T18:19:48Z`, the aborted operation
`twin-basic-real-806004e76c7d4553b9287ae1a3571157`, and their retained telemetry/radio
transport evidence. The completed hover windows remained within `0.276..0.346 m` and
`0.302..0.344 m`; their minimum loaded voltages / displayed battery levels were
`3.859 V / 30%` and `3.806 V / 20%`. At the near-floor anomaly the measured transport
was `HEALTHY` with `0%` window packet loss, queue depth `0`, and sub-millisecond ACK
age, while the down range was `0.003 m`, motor PWM reached `98.73%`, attitude reached
approximately `14.5 deg` roll / `6.9 deg` pitch, and loaded battery voltage / displayed
level fell to `3.669 V / 10%`. The later RF loss burst occurred after motor output was
already zero. This supports loss of power/actuator margin as the guarded condition but
does not qualify battery, motor, propeller, floor contact, or estimator hardware as the
single component cause.

**Causal hypothesis:** isolated radio misses are not the initiating cause because the
high-level Crazyflie commander holds its setpoint onboard and the anomaly precedes the
observed RF burst. The immediate software gap is that duration-based high-level
commands collect telemetry but do not turn sustained measured floor proximity,
estimator loss, excessive tilt, or combined actuator saturation/voltage sag into a
fail-closed command result.

**Bounded implementation:** add a physical-adapter airborne-stability guard for
takeoff, hover, stop/hold, and relative movement. Use sustained time windows so one
packet miss, one asynchronous log value, or one sensor sample cannot trigger it. Route
a violation through the existing recorded failure and abort/land path; do not retune
the onboard controller, replay uncertain commands, change the radio URI, or claim the
physical cause is qualified. The bounded thresholds are floor proximity at or below
`0.06 m` for `0.30 s`; an unavailable/unconverged estimator or roll/pitch at or above
`20 deg` for `0.25 s`; and motor output at or above `95%` together with loaded battery
voltage at or below `3.75 V` for `0.25 s`.

**Exit gate:** focused adapter and physical-flight tests prove that stable flight and
isolated packet loss remain admitted, while sustained near-floor flight, estimator
loss, excessive tilt, and saturation with loaded-voltage sag fail with exact measured
details and permit the existing recovery path to land. Physical validation remains an
operator rerun after deployment and is not part of this coding task.

## Current state and reason for reopening curriculum work

WP-01 through WP-34 remain closed as the implemented software and Fast Sim foundation
recorded in [`COMPLETED.md`](COMPLETED.md). This package does not discard the Campaign
Lab, planner, smooth-trajectory, runtime, safety, evidence, replay, or review shell.
It opens successor work because the WP-33 catalog inventory does not truthfully
implement most of the behaviors represented by its names.

The current audit found 47 named Simulation mission families but only six distinct
physical start/goal/landing coordinate patterns:

- 14 of 15 one-drone families share one route; only
  `static_multi_goal_sequence` differs.
- 15 of 18 two-drone families share the default perpendicular-crossing route; the
  only other coordinate patterns are `parallel_routes` and the shared
  `head_on_conflict`/`overtake` pattern.
- All 14 three-drone families share one coordinate route pattern.

For example, `1d.continuous_waypoint_sequence.canonical_nominal` and
`1d.altitude_transition.canonical_nominal` both compile to the same two-point route
from `(-1.50, 0.00, 0.30)` to `(1.50, 0.00, 0.30)`, use the same selected strategy,
and have the same route and schedule durations. The former contains no internal
waypoint sequence and the latter contains no en-route altitude transition. Their
different IDs, descriptions, and case hashes do not make their execution different.

The Python files under `missions/library/` are generated data-only labels; catalog
discovery does not import them. The executable behavior comes from the YAML case
geometry, constraints, schedules, events, and runtime compiler. The present generator
special-cases only three route shapes and otherwise changes mostly descriptive fields.
The existing catalog test proves inventory count and whole-case hash uniqueness, but
does not prove execution-semantic uniqueness or that the named behavior occurred.

### Implementation status on 2026-08-10

The count-driven geometry generator has now been replaced by exact family builders and
the successor catalog contains 54 definitions as an outcome of the learning design:

- 31 cases are `EXECUTABLE`. They cover one-drone motion, altitude, fly-through,
  curves and closed shapes; two-drone conflict geometry and synchronized formation;
  and three-drone joint scheduling, layers, and formation transformation.
- 23 definitions are `PLANNED_NOT_EXECUTABLE` and `STATIC_VALIDATE_ONLY`: 20 dynamic
  update/failure/handover cases, the two role-allocation cases, and `overtake`. The
  present overtake geometry has safe trailing/leading lanes but no compiler-consumed
  role-specific pace contract, so it cannot yet prove a real catch-up. Their typed events,
  expected dispositions, geometry, and static programs are retained, but the current
  Campaign executor reduces those events before provisioning rather than injecting
  them at source time. Calling that a live recovery or cutover would be false, so the
  service refuses to activate them.
- Every definition has an execution-semantics fingerprint and semantic audit result.
  All 54 pass fail-closed parsing and receive a bounded-plan result. All 31 executable
  cases pass planning, scheduling, trajectory audit, and accepted-program compilation;
  two quarantined dynamic definitions retain an explicit blocked plan. This is static
  qualification, not proof that all 54 executed.
- All 31 executable cases pass isolated accelerated Fast Sim execution and every
  required behavior oracle. Eleven progression anchors (four one-drone, four
  two-drone, and three three-drone cases) also pass in both accelerated and observed
  realtime modes: 22 successful runs and 11/11 applicable mode comparisons. Metrics
  that have no mathematical meaning for a case, such as pairwise separation for one
  drone, are recorded explicitly as not applicable; a value missing in only one mode
  fails the comparison.

The machine-readable static boundary is retained at
`missions/campaigns/sim/qualification/catalog-static-qualification-v2.json`. It
explicitly records `NOT_RUN_BY_STATIC_QUALIFIER` for both execution modes.
Runtime results and content hashes are retained in
`catalog-runtime-accelerated-v2.json` and
`catalog-runtime-realtime-anchors-v2.json` in the same directory. The isolated
qualifier removes its temporary evidence stores after hashing and analysis, so these
manifests do not by themselves close WP-39's retained-bundle or repeatability gates.

This is a qualification defect, not evidence that the Campaign Lab shell must be
rewritten. The repair will use the current bounded Fast Sim, joint planner, C2
trajectory generator, Safety Supervisor, execution evidence, analyzer, review queue,
and Control Center. New contract fields are permitted only where the current catalog
cannot express a real behavior, such as a deliberate hold, fly-through waypoint,
fault trigger, task transfer, or expected causal outcome.

## Non-negotiable truth rules

1. **Behavior before label.** A family name, purpose string, template ID, or unique
   hash is not executable behavior. Every distinguishing claim must alter a compiler-
   consumed, hash-bound input and must have an evidence-backed oracle.
2. **No quota-driven cases.** There is no required equal count for one, two, and three
   drones and no requirement to preserve 127 Simulation cases. A case exists only
   when it teaches or tests a materially different subproblem.
3. **Easy-to-hard progression.** `1d`, `2d`, and `3d` mean one, two, and three drones;
   they do not mean spatial dimensions. Each fleet-size curriculum has explicit
   prerequisites and progresses from basic motion to geometry, coordination, dynamic
   changes, and failure handling.
4. **A variation must vary execution.** `compact`, `wide`, different seeds, or renamed
   text are retained only when they create a different feasible set, path, event,
   decision, or evidence question. Otherwise they are removed.
5. **Negative cases are legitimate only when causal.** A blocked or rejected case can
   teach an important safety property, but it must inject the declared invalid input,
   prove that no prohibited command executed, and verify the specified safe outcome.
6. **No silent equivalence.** Cases may share a route only when another behavior-driving
   dimension is intentionally different, such as no-hover authority, priority,
   capability assignment, a fault, or a goal update. That difference must be exercised
   and observed.
7. **Every executable case runs.** Static validation alone cannot qualify the word
   `EXECUTABLE`. Every executable case must complete an accelerated Fast Sim run or its
   declared preflight rejection; selected progression anchors must also run in observed
   realtime mode.
8. **Truthful claim boundary.** These packages qualify deterministic software behavior
   in Fast Sim. They do not claim physical accuracy, live Isaac parity, learned
   autonomy, obstacle perception, SLAM, or real-aircraft safety.
   NVIDIA/Isaac installation is not authorized by WP-35 through WP-39.

## Definition of an executable learning case

A case may carry `implementation_status: EXECUTABLE` only when all of the following
are true:

- Every role has an exact start region, ordered route intent, landing region, and
  terminal state.
- Each route node declares whether it is `FLY_THROUGH`, `CAPTURE`,
  `CAPTURE_AND_HOLD`, or an intentional reversal. Declared holds and reversals are not
  misclassified as unintended stops.
- Any behavior involving changing goals, failures, priorities, capabilities,
  ownership, acknowledgements, or battery has a typed bounded scenario event or
  initial condition consumed by the executor.
- The case has machine-evaluable behavior oracles beyond generic tracking and landing,
  including the exact fact that distinguishes the family.
- The compiled execution-semantics fingerprint covers route geometry and node modes,
  environmental constraints, role/task policy, events, permitted decisions, search
  settings, and behavior oracles. Descriptive text is retained in the whole-case hash
  but excluded from this semantic fingerprint.
- The planner preview and execution evidence can explain what was attempted, what was
  selected or rejected, why, and whether the learning objective passed.
- The case is materially distinguishable from every other executable case. Intentional
  shared baselines are declared explicitly and compared by a named delta.

Anything that fails this definition is `PLANNED_NOT_EXECUTABLE` and
`STATIC_VALIDATE_ONLY`, even if a generic route could technically be launched.

## Required bounded contract additions

WP-35 may publish a successor campaign-case schema, but it must reuse the existing
runtime authority and preserve old evidence identities. The minimum additions are:

- `route_intent` per role: ordered world-space regions, node mode, capture tolerance,
  optional bounded dwell, intentional reversal flag, and landing handoff.
- `environment_constraints`: optional known keep-out regions and admitted corridors
  for bottleneck/boundary cases. This is configured geometry, not perceived-object
  avoidance.
- `scenario_events`: a bounded ordered list of source-clock or authenticated telemetry
  triggers for goal updates, observation/link loss, battery thresholds, assignment
  proposals, acknowledgement loss, and abort/fallback requests.
- `coordination_constraints`: optional synchronized launch/node/phase groups,
  overlapping-flight requirements, relative formation geometry, and unaffected-role
  maximum delay. A planner may not serialize a formation or independent-role case and
  report that it executed the named coordination behavior.
- `behavior_oracles`: typed metric/event/state assertions with comparator, threshold,
  evidence source, and the family claim they prove.
- `learning_objective`, `difficulty_rationale`, and explicit prerequisites for operator
  understanding. These remain descriptive, while the corresponding oracle remains
  executable.
- `execution_semantics_sha256`: a canonical fingerprint of behavior-driving inputs,
  separate from the full immutable case hash.

The compiler must reject an event or oracle it does not implement. It may never ignore
an unknown behavior field and proceed with a generic route.

### Pre-implementation geometry feasibility audit

On 2026-08-10, in-memory successor cases were compiled through the current bounded
planner and C2 trajectory generator without changing the repository catalog. The
proposed point-to-point, move-return, altitude-transition, slalom, S-curve,
multi-goal, and boundary routes all passed current volume and dynamics gates. The
altitude route reached 0.892 m/s2 peak planned acceleration and 5.976 m/s3 peak planned
jerk, below the current 1.0 m/s2 and 8.0 m/s3 limits. Proposed two-drone parallel,
head-on, merge, and curved leader/follower geometry and three-drone selective-conflict
and merge geometry also admitted.

This was a geometry-only feasibility check, not execution qualification. It also found
a useful counterexample: the proposed rotating triangular formation can be made
collision-safe by ground-delaying whole roles. That result does not execute a
formation. The coordination constraints and behavior oracles above are therefore
required to demand synchronized overlapping flight and bounded phase/shape error for
formation cases.

## Dependency and delivery order

```text
WP-35 semantic truth gate and successor case contract
  -> WP-36A one-drone motion curriculum
  -> WP-36B one-drone dynamic and recovery curriculum
  -> WP-37A two-drone geometry and coordination curriculum
  -> WP-37B two-drone dynamic and failure curriculum
  -> WP-38A three-drone joint-motion curriculum
  -> WP-38B three-drone allocation, handover, and recovery curriculum
  -> WP-39 catalog cutover, UI learning surface, and full qualification
```

Higher fleet-size work must not compensate for a failed lower-level prerequisite.
WP-37 may reuse the qualified WP-36 route primitives; WP-38 may reuse qualified WP-37
conflict, coordination, and event primitives. No package is complete because a more
complex showcase happens to run.

## WP-35 — Semantic truth gate and executable-case contract

**Status:** `IMPLEMENTED`

**Objective:** prevent a named mission from being treated as executable when its
distinguishing behavior is only text, and establish the smallest contract needed to
express real learning cases through the existing Campaign Lab.

### Tasks

- [x] Add a catalog audit that groups cases by execution-semantics fingerprint and
      reports identical route, constraint, role, event, and oracle inputs.
- [x] Add family-invariant checks. At minimum: a continuous sequence has multiple
      ordered fly-through nodes; an altitude transition has multiple en-route altitude
      levels; a move-return returns; a curved route has non-zero integrated curvature;
      a leader/follower case carries relative-role behavior; and a failure/replan case
      carries the triggering event and causal oracle.
- [x] Add the bounded route-node, environment-constraint, scenario-event,
      coordination-constraint, behavior-oracle, and semantic-fingerprint contracts
      described above.
- [x] Make catalog parsing and execution fail closed on unsupported scenario events,
      route-node modes, and oracles.
- [x] Change all current entries that cannot pass their family invariant to
      `PLANNED_NOT_EXECUTABLE` and `STATIC_VALIDATE_ONLY`. Do not fabricate uniqueness by
      perturbing a coordinate or description.
- [x] Preserve old case source, full hashes, and retained run/review evidence. A changed
      case with retained evidence receives a successor ID; an unrun definition may use
      the existing safe identity-refresh path.
- [x] Replace count/hash-only catalog tests with semantic-invariant, compiler-consumption,
      duplicate-fingerprint, and unsupported-field rejection tests.
- [x] Keep the existing default development case until an explicitly qualified WP-39
      cutover; quarantine must not silently change the active selection.

### Exit gate

- Every catalog case has an audit classification of `SEMANTICALLY_EXECUTABLE`,
  `INTENTIONAL_SHARED_BASELINE`, or `PLACEHOLDER_QUARANTINED` with a precise reason.
- Zero `EXECUTABLE` cases rely only on names/descriptions to distinguish their behavior.
- Mutating a route node, event, role policy, environment constraint, or oracle changes
  the semantic fingerprint; mutating prose alone does not.
- An unsupported event or oracle fails before provisioning and produces no arm/takeoff
  command.
- Existing immutable evidence remains readable and traceable to its original case hash.

## WP-36 — One-drone executable learning curriculum

**Status:** `WP_36A_FAST_SIM_QUALIFIED__WP_36B_QUARANTINED`

**Objective:** establish trustworthy motion, geometry, goal, landing, dynamic-update,
and recovery primitives with one drone before using them in fleet cases.

All coordinates below are world-space meters inside the current bounded Fast Sim room.
`S` is the start/takeoff location, `G1..Gn` are ordered in-flight route nodes, and `L`
is the touchdown location. A route description is normative enough to generate exact
regions; generated YAML must retain the exact expanded coordinates and hashes.

### WP-36A — Static motion and geometry

| Level | Family / canonical case | Concrete route intent | Learning outcome and required oracle |
|---:|---|---|---|
| 1 | `takeoff_hover_land` | `S=(0,0,0.04)`, vertical takeoff to `G1=(0,0,0.35)`, declared 3 s hold, `L=S` | Separates takeoff, stable hold, and descent. Prove XY drift, hold-duration error, altitude error, capture, and landed/disarmed terminal state. |
| 2 | `point_to_point_relocation` | `S=(-1.20,-0.80,0.04)`, fly to `G1=(1.00,0.70,0.35)`, `L=(1.00,0.70,0.04)` | Proves straight relocation and landing at a different place. Prove cross-track error, positive displacement, destination capture, and touchdown error. |
| 2 | `move_return` | `S=(-1.20,-0.80,0.04)`, capture `G1=(1.10,-0.80,0.35)`, intentional reversal to `G2=(-1.20,-0.80,0.35)`, `L=S` | Proves outbound capture, deliberate reversal, return-to-home, and home landing; it must not be accepted as a one-way relocation. |
| 3 | `altitude_transition` | `S=(-1.20,-0.60,0.04)`, fly through `(-0.80,-0.60,0.25)`, `(-0.20,-0.60,0.65)`, `(0.45,-0.60,0.35)`, `(1.05,-0.60,0.55)`, then land at `(1.05,-0.60,0.04)` | Proves coupled horizontal/vertical motion through at least three altitude layers. Prove ordered altitude crossings, vertical speed/acceleration/jerk limits, no internal stop, and offset landing. |
| 3 | `continuous_waypoint_sequence` | `S=(-1.35,0,0.04)`, five `FLY_THROUGH` nodes forming a slalom: `(-0.90,0.45,0.35)`, `(-0.30,-0.45,0.35)`, `(0.30,0.45,0.35)`, `(0.90,-0.45,0.35)`, `(1.35,0,0.35)`, land at `(1.35,0,0.04)` | Proves ordered fly-through, C2 continuity, and zero unintended internal stops. Every node must be crossed in order without being converted into a hover. |
| 4 | `curved_route` | Canonical S-curve from `(-1.25,-0.75,0.35)` through `(-0.75,-0.25,0.35)`, `(-0.20,0.45,0.45)`, `(0.35,-0.35,0.55)`, `(0.90,0.30,0.40)` to `(1.25,0.75,0.35)` with start/landing directly below the endpoints | Proves actual non-collinear curved motion, curvature sign change, bounded cross-track error, C2 continuity, and dynamics compliance. A straight chord fails the shape oracle. |
| 4 | `planar_shape_loop.circle` | At `z=0.40`, follow `(-0.65,0)`, `(-0.46,0.46)`, `(0,0.65)`, `(0.46,0.46)`, `(0.65,0)`, `(0.46,-0.46)`, `(0,-0.65)`, `(-0.46,-0.46)`, and `(-0.65,0)`; exit to `(1.20,0.70,0.35)` and land there | Proves constant-sign curvature, loop closure, continued motion after closure, and landing away from the loop origin. |
| 4 | `planar_shape_loop.rounded_square` | At `z=0.40`, follow `(-0.60,-0.35)`, `(-0.35,-0.60)`, `(0.35,-0.60)`, `(0.60,-0.35)`, `(0.60,0.35)`, `(0.35,0.60)`, `(-0.35,0.60)`, `(-0.60,0.35)`, and close at `(-0.60,-0.35)` before an offset landing | Proves straight/curved segment transitions and corner dynamics without stopping at vertices. |
| 4 | `planar_shape_loop.figure_eight` | At `z=0.45`, follow `(0,0)`, `(-0.45,0.45)`, `(-0.90,0)`, `(-0.45,-0.45)`, `(0,0)`, `(0.45,0.45)`, `(0.90,0)`, `(0.45,-0.45)`, and `(0,0)`; then exit to a separate landing | Proves signed-curvature reversal, intentional self-crossing at different source times, loop ordering, and no false goal completion at the first center crossing. |
| 4 | `static_multi_goal_sequence` | Capture and hold 1 s at `(-0.60,0.50,0.30)`, `(0,-0.50,0.45)`, and `(0.60,0.50,0.30)`, then land at `(0.95,-0.70,0.04)` | Proves ordered region capture and declared dwell semantics. It is intentionally different from the fly-through sequence and must show three holds, not three unintended stops. |
| 4 | `boundary_constrained_route` | Follow three fly-through nodes 0.20 m inside the west, north, and east flight-volume faces, then land at a fourth interior point | Proves minimum boundary margin along the full sampled trajectory, not only at endpoints, and demonstrates that a smoothing spline cannot cut outside the volume. |

The three shape-loop entries are retained because they test different curvature
properties. They are not cosmetic `compact`/`wide` copies. If the implementation
cannot produce separate causal oracles for them, they collapse to one case.

### WP-36A tasks and exit gate

- [x] Implement the route-node modes using existing takeoff, hold, smooth trajectory,
      goal-capture, and landing operations.
- [x] Generate exact case definitions from explicit per-family builders; remove the
      one generic `_drones()` geometry path for these families.
- [x] Add shape, ordered-capture, altitude-extrema, declared-hold, reversal, boundary,
      start/landing displacement, and unintended-stop metrics to retained analysis.
- [x] Enforce the prerequisite order above in lifecycle promotion.
- [x] Execute every WP-36A case in accelerated Fast Sim and execute one anchor from
      each level in observed realtime mode.

WP-36A passes only when all cases produce complete evidence and their family-specific
oracle passes. Generic success plus landing is insufficient.

### WP-36B — Dynamic goals and recovery

| Family | Real injected behavior | Distinct learning outcome |
|---|---|---|
| `moving_target` | Three bounded target revisions arrive at declared source times while the drone follows a safe old route | Proves rate limiting, ordered accepted generations, continuous future replacement, and capture of the final target rather than the initial target. |
| `mid_route_goal_replacement` | One authenticated replacement changes the remaining route and offset landing after the first goal capture | Proves a single clean cutover and that no stale-plan command executes after it. |
| `duplicate_stale_goal_update` | A duplicate generation and then an older generation are submitted after one accepted update | Proves deterministic rejection, unchanged active route identity, and zero duplicate cutover. |
| `planning_budget_expiry` | A deliberately bounded search expires before validating a replacement | Proves that no partial candidate becomes authority and the declared still-safe old route or hold remains active. |
| `blocked_replan` | The replacement target is outside the frozen flight volume or cannot meet the deadline | Proves precise infeasibility, no weakened constraint, no cutover, and the declared safe continuation/landing outcome. |
| `operator_approval_goal_replacement` | A feasible replacement is proposed before and after an exact hash-bound operator approval | Proves that feasibility is not authority; only the approved identity may cut over. |
| `failure_recovery` | Fresh-position observations are lost after a declared route node | Proves detection latency, supervisor preemption, no continued nominal trajectory, and the declared bounded landing or abort terminal state. |
| `abort_and_land_goal_fallback` | The old route becomes unsafe while the replacement is blocked | Proves the explicit abort-and-land goal, accepted fallback landing region, and evidence that neither unsafe route executed. |

WP-36B reuses the completed WP-34 replanning primitives but must connect each event to
the Campaign Lab executor. Unit-testing the replanner without injecting the event into
a run does not close the case.

WP-36 is complete when all static and dynamic one-drone cases meet their distinct
oracles in accelerated Fast Sim, the declared realtime anchors reconcile, and no
one-drone executable family shares a semantic fingerprint without an explicit delta.

## WP-37 — Two-drone executable learning curriculum

**Status:** `WP_37A_FAST_SIM_QUALIFIED__WP_37B_QUARANTINED`

**Objective:** build from qualified one-drone routes to real pairwise independence,
conflicts, priorities, constrained choices, relative motion, allocation, atomic
updates, and failure handling.

### WP-37A — Geometry, scheduling, and coordination

| Level | Family | Concrete pairwise problem | Learning outcome and required oracle |
|---:|---|---|---|
| 1 | `parallel_routes` | Alpha and Beta fly from `x=-1.40` to `x=1.40` at `y=-0.65/+0.65`, `z=0.35`, with synchronized launch and separate landings | Non-conflicting baseline: both start without unnecessary delay and preserve at least 1.10 m nominal spacing. |
| 2 | `head_on_conflict` | Separate pads at `(-1.40,-0.90)` and `(1.40,0.90)` feed opposite directions through the same `y=0, z=0.35` corridor between `x=-1.20/+1.20`, then exit to separate pads | Predicts the shared conflict interval and admits a real temporal/geometry resolution; the unmodified simultaneous direct pair is infeasible. |
| 2 | `perpendicular_crossing` | Alpha crosses west-east and Beta south-north through `(0,0,0.35)` | Resolves one compact crossing window and proves time-aligned separation, not endpoint distance. |
| 3 | `merge` | Routes from `(-1.40,-0.80)` and `(-1.40,0.80)` converge through `(-0.50,-0.25/+0.25)` to a shared `(0.20,0,0.35)` merge, then split to separate east landings | Proves ordered shared-corridor occupancy, merge precedence, and independent post-merge completion. |
| 3 | `overtake` | A trailing faster role starts 1.0 m behind a slower role on a shared corridor and both split to separate landing lanes after the pass zone | Proves that role-specific pace/arrival intent creates a real catch-up conflict and that retiming or a lateral pass prevents unsafe overlap. |
| 3 | `bottleneck` | Configured keep-out regions leave one sub-warning-width central gate used in opposite directions | Proves corridor-aware queueing and that endpoint-only or unconstrained detours are rejected. |
| 3 | `unequal_priority` | A perpendicular crossing gives Alpha priority 200 and Beta priority 100 | Proves priority causally changes precedence: Alpha receives no Beta-caused delay while Beta absorbs the admissible resolution. |
| 4 | `constrained_border_height` | A crossing lies near a flight-volume edge with `z_max=0.42`; lateral and vertical candidates violate declared margins | Proves exact candidate rejection and selection of a feasible timing solution without weakening volume/height constraints. |
| 4 | `no_hover_crossing` | A perpendicular crossing sets `hover_allowed=false` and `maximum_hover_s=0` | Proves ground delay or continuous speed retiming with zero airborne hold, while maintaining separation and smoothness. |
| 4 | `leader_follower` | Leader follows the WP-36 S-curve with altitude changes; follower tracks an explicit 0.85 m relative offset | Proves asymmetric role authority, relative-offset RMS/maximum error, isolated routing, and separate landing. Independent coincident endpoints do not pass. |
| 4 | `formation_spacing` | A symmetric two-role formation translates through a bend and `z=0.30 -> 0.60 -> 0.40` while retaining a 1.00 m lateral baseline | Proves synchronized overlapping flight, bounded phase error, and continuous pairwise spacing through turning and altitude change; unlike leader/follower, neither route is derived by authority from the other. Ground-delaying an entire role fails the oracle. |
| 4 | `role_allocation` | Two spatial tasks have different capability and energy requirements; only one assignment is feasible for the precision task | Proves deterministic unique assignment, capability matching, role-bound command routing, and completion of the assigned—not merely indexed—route. |

Known keep-out regions and corridors are immutable case inputs validated before launch;
they do not add online perception. The current obstacle-aware and bounded candidate
components should be reused rather than creating an unbounded path planner.

### WP-37B — Pairwise protocol and failure cases

| Family | Real injected behavior | Distinct learning outcome |
|---|---|---|
| `leader_loss` | Authenticated leader observations are lost during the curved formation route | Follower detects the declared source, stops accepting leader-relative updates, and enters its bounded landing outcome. |
| `duplicate_assignment_rejection` | Two assignment proposals claim the same exclusive task generation | The conflict is rejected before launch or task transfer; exactly one owner remains and no cross-routed command executes. |
| `coordination_failure` | One required preparation/cutover acknowledgement is withheld | No half-coordinated schedule or route generation commits; both roles retain the declared safe state. |
| `crossing_goal_change` | One role receives a new post-crossing goal while both routes are active | Both future reservations are recomputed atomically and separation remains valid before, at, and after cutover. |
| `simultaneous_conflicting_updates` | Both roles receive incompatible updates at the same source timestamp | Deterministic ordering selects or rejects the whole bounded update set; no mixed generation becomes active. |
| `partial_replacement_failure` | Only one proposed replacement is feasible | Zero fleet replacement routes commit; the still-safe old epoch or declared pairwise fallback remains authoritative. |

### WP-37 exit gate

- Every pairwise case executes the named interaction rather than the generic
  perpendicular route.
- The direct-unmodified conflict baseline is retained for conflict cases and is proven
  infeasible or less preferred for the exact causal reason claimed.
- Minimum separation, conflict-window occupancy, airborne wait, role-relative error,
  ownership uniqueness, update generation, and terminal outcomes are evaluated from
  retained evidence.
- Every case runs accelerated; `parallel_routes`, `perpendicular_crossing`,
  `no_hover_crossing`, `leader_follower`, and one atomic-update case also pass observed
  realtime reconciliation.
- Pairwise failures commit no partial authority and issue no command to the wrong role.

## WP-38 — Three-drone executable learning curriculum

**Status:** `WP_38A_FAST_SIM_QUALIFIED__WP_38B_QUARANTINED`

**Objective:** test genuinely joint reasoning that cannot be reduced to three copied
routes or independent pair decisions: selective intervention, global scheduling,
fairness, priority, three-dimensional alternatives, formation transformation,
allocation, reserve handover, cascading updates, and fleet fallback.

### WP-38A — Joint geometry and motion

| Level | Family | Concrete three-role problem | Learning outcome and required oracle |
|---:|---|---|---|
| 1 | `single_pair_conflict` | Alpha crosses `(-1.40,0,0.35) -> (1.40,0,0.35)`, Beta crosses `(0,-1.40,0.35) -> (0,1.40,0.35)`, and Gamma follows an independent northwest-corner route `(-1.45,1.35,0.35) -> (-0.95,1.35,0.35) -> (-0.95,0.95,0.35)` | Proves conflict localization: resolve Alpha/Beta without unnecessary Gamma delay or detour. |
| 2 | `simultaneous_center_conflict` | Alpha crosses west-east, Beta south-north, and Gamma southwest-northeast through the same center and altitude | Proves one joint conflict graph and schedule; composing independently safe-looking pair decisions is not accepted authority. |
| 3 | `merge` | Roles start at `(-1.45,-1.20/0/1.20,0.35)`, approach through `(-0.40,-0.35/0/0.35,0.35)`, share `(0,0,0.35)` at distinct times, then fan out to `(1.40,-1.20/0/1.20,0.35)` and separate landings | Proves global merge order, one occupant at a time, and completion without starvation. |
| 3 | `bottleneck` | Alpha/Beta approach a configured central gate from `(-1.45,-1.20/1.20,0.35)` while Gamma approaches from `(1.70,0,0.35)`; every path must traverse the same narrow `x=-0.40 -> 0.40, y=0` corridor before fanning out to unoccupied landing pads | Proves bounded queueing, direction change, fair release, ground-pad occupancy safety, and maximum-wait compliance for all roles. |
| 3 | `unequal_priorities` | Three center-conflict roles carry priorities 300/200/100 | Proves lexicographic priority order without starvation and records exactly which delay each lower-priority role absorbs. |
| 4 | `constrained_volume` | Center-conflict geometry forbids vertical layers and leaves no valid horizontal detour | Proves a complete ground/timing sequence or a precise blocked result under a tightened deadline; no infeasible candidate is launched. |
| 4 | `alternative_layers_detours` | Three same-altitude center-conflict routes begin at `z=0.35`; the bounded candidate set admits explicit `z=0.25/0.55/0.85` conflict layers and lateral arcs, followed by return transitions to distinct landing approaches | Proves real en-route altitude transitions, vertical separation, candidate comparison, and return to distinct landing approaches. |
| 4 | `formation_shape_transform` | A side-0.90 m triangle follows centroid knots `(-1.00,-0.60,0.30)`, `(-0.45,0,0.50)`, `(0,0.55,0.70)`, `(0.55,0,0.55)`, `(1.00,0.60,0.40)` while its stored role offsets rotate from 0 to 90 degrees, then all roles land separately | Proves synchronized joint formation translation, rotation, altitude change, pairwise-distance/phase bounds, overlapping flight, and per-role trajectory identity. Full-role serialization is a failure. This is the high-visibility shape-following fleet case. |

### WP-38B — Allocation, handover, and fleet recovery

| Family | Real injected behavior | Distinct learning outcome |
|---|---|---|
| `role_allocation` | Two active tasks and one reserve role have asymmetric capabilities, energy, and priorities | Proves deterministic assignment, one idle-ready reserve, unique ownership, and no command to the reserve before assignment. |
| `duplicate_assignment_rejection` | Conflicting generations attempt to assign one task to two roles | Proves atomic rejection and exactly one authoritative owner across planner, runtime, evidence, and replay. |
| `persistent_coverage_reserve_handover` | Alpha/Beta fly distinct closed coverage loops; Alpha crosses the declared battery threshold and Gamma takes over Alpha's exact task | Proves telemetry-triggered reserve launch, geometry-confirmed takeover, atomic lease generation, uninterrupted ownership, outgoing return/landing, and continued Beta coverage. |
| `leader_follower_recovery` | A leader in the triangular/curved formation is lost after the first altitude transition | Proves the declared bounded choice—deterministic successor leadership with revalidated geometry, or all-role landing—and rejects undeclared improvisation. |
| `cascading_replan` | An accepted Gamma update invalidates Beta's reservation, whose safe replacement then affects Alpha | Proves deterministic bounded cascade order, one shared cutover epoch, and no stale command after the epoch. |
| `acknowledgement_loss` | One role misses the shared cutover acknowledgement | Proves zero partial commit and continuation of the safe old epoch or the declared all-fleet fallback. |
| `fleet_abort_fallback` | The old epoch is unsafe and the atomic replacement cannot commit | Proves coordinated abort/landing for all roles, individualized landing regions, terminal evidence, and cleanup. |

### WP-38 exit gate

- Each case demonstrates a property that cannot be established by running only one
  drone or one independent pair.
- The joint planner and runtime share one hash-bound schedule/update epoch; no set of
  independently selected pair plans is composed after the fact.
- Selective cases prove unaffected-role non-interference; global cases prove fairness,
  priority, and maximum-wait bounds.
- Formation and layer cases contain actual altitude-changing trajectories and shape/
  spacing/phase oracles, overlapping flight, and synchronized coordination—not only
  three differently named straight lines or three serial solo flights.
- Allocation and handover cases prove task/lease ownership from retained events and
  commands, not only final positions.
- Every case runs accelerated. `single_pair_conflict`,
  `simultaneous_center_conflict`, `formation_shape_transform`,
  `persistent_coverage_reserve_handover`, and one fleet-fallback case also pass observed
  realtime reconciliation.

## WP-39 — Catalog cutover, learning surface, and full qualification

**Status:** `PARTIALLY_IMPLEMENTED__DYNAMIC_AND_RETAINED_EVIDENCE_GATES_OPEN`

**Objective:** replace the misleading count-driven catalog with the qualified
curriculum, expose what each case teaches, and prove that every executable entry can
actually be run through the current operator setup.

### Tasks

- [x] Generate the successor Simulation catalog only from qualified per-family builders
      and exact immutable inputs. Do not preserve an old entry merely to keep a count.
- [x] Preserve old WP-33 definitions and retained run identities as historical evidence;
      do not silently rewrite a case that has a run, review, baseline, or promotion.
- [x] Retain unauthorized Real mirrors only for cases whose Simulation intent is
      qualified. Real mirrors remain `NOT_AUTHORIZED` and `STATIC_VALIDATE_ONLY`.
- [x] Add curriculum level, prerequisite, learning objective, concrete route summary,
      distinguishing oracle, and execution status to the Campaign Lab case view.
- [x] Preview the exact per-role route, altitude profile, planned holds, conflict
      windows, event triggers, start locations, and landing regions. A generic family
      icon or description is not an adequate preview.
- [x] Make recommendations progression-aware: choose the lowest unmet prerequisite or
      a regression, not simply the highest difficulty or newest case.
- [x] Add a machine-readable qualification manifest binding every executable case to
      semantic fingerprint, accelerated result/evaluation/analysis hashes, required
      realtime anchor evidence, and pass/fail oracle results.
- [x] Add a regression that fails if executable families collapse to the same semantic
      fingerprint without an explicit shared-baseline delta.
- [ ] Update guides and completed records only after all gates below pass.

### Full exit gate

1. Every successor case is classified and has an explicit learning objective,
   prerequisite, behavior-driving input, and causal oracle.
2. Every `EXECUTABLE` Simulation case completes its accelerated run or its declared
   safe rejection/failure path with complete manifest, telemetry where flight occurs,
   execution bundle, evaluation, and analysis.
3. Every specified realtime anchor passes the existing accelerated/realtime comparison
   tolerances. No average may hide a hard failure.
4. Each fly-through, hold, reversal, altitude, curve/shape, boundary, separation,
   formation, priority, allocation, update, recovery, and landing claim is checked from
   retained evidence.
5. Two repeated executions with identical case/configuration/seed reproduce plan,
   schedule, trajectory, event disposition, terminal outcome, and normalized evidence
   identities where the existing deterministic contract requires them.
6. Unsupported behavior fails before provisioning. Fault/rejection cases prove zero
   prohibited commands and the exact safe outcome.
7. The Control Center can select, preview, activate, run, review, replay, and download
   evidence for the new one-, two-, and three-drone progression using the existing Fast
   Sim operator workflow.
8. The final number of cases is reported as an outcome, never used as a pass criterion.
   Semantically redundant cases are removed or explicitly documented baselines.
9. Physical flight, live Isaac, and digital-twin status remain unchanged and visibly
   unqualified.

WP-35 through WP-39 move to [`COMPLETED.md`](COMPLETED.md) only after this full gate
passes. Implementing a schema, drawing distinct paths, or demonstrating one showcase
does not close the package by itself.

## Operator-review successor queue — altitude transition and submissions

**Status:** `IMPLEMENTED`

**Implementation boundary:** these packets are implemented in successor contracts,
runtime behavior, evidence, tests, and the catalog surface. The immutable
`canonical_nominal` and `wide` definitions, retained runs, baselines, promotions, and
existing review/flag state were not changed. New dynamic qualification evidence is
still governed by each packet's exit gate.

The bounded WP-43 runtime matrix is retained in
`missions/campaigns/sim/qualification/altitude-profile-runtime-qualification-v1.json`.
It contains 24 isolated Fast Sim runs (two repeats per admitted accelerated profile
and two repeats per minimal realtime anchor); every run, evaluator-completeness gate,
behavior/profile oracle, exact-baseline comparison, cross-geometry stress comparison,
and accelerated/realtime comparison passed. Its qualification hash is
`e1236e89b24d9e8345e476bcceac6b5437cdba84c19ca7a8f6ab7cd228e11f84`.

The durable design rules are in
[`docs/project/WORKFLOW_AND_REQUIREMENTS.md`](../project/WORKFLOW_AND_REQUIREMENTS.md). The packets below are
successors to the current WP-35 through WP-39 implementation, but they must be
completed before new altitude-transition profile evidence can close the relevant
WP-39 evidence gates.

### Reviewed evidence and neutral interpretation

The reviewed set contains four current
`1d.altitude_transition.canonical_nominal` runs and two current
`1d.altitude_transition.wide` runs. All six completed successfully and repeated runs
within each case were deterministic within the reviewed precision.

| Metric | Canonical reviewed set | Wide reviewed set | Interpretation |
|---|---:|---:|---|
| Authored altitude envelope | about `0.25..0.65 m` | about `0.20..0.82 m` | Wide changes the vertical geometry, not the control objective. |
| Source duration | about `16.88 s` | about `19.78 s` | The wider vertical route is longer and is retimed. |
| Truth path length | about `3.258 m` | about `3.802 m` | Confirms a material geometric stress delta. |
| Tracking RMS | about `0.0152 m` | `0.0197 m` | Wide is modestly harder to track but remains below the current `0.05 m` gate. |
| Maximum tracking error | about `0.0222 m` | `0.0316..0.0321 m` | The larger envelope adds quantitative stress, not a new qualitative behavior. |
| Peak route speed | about `0.436 m/s` | about `0.395 m/s` | The current planner slows/retimes the longer path; this is not a constant-speed comparison. |
| Peak acceleration / jerk | about `0.780 m/s^2` / `3.14 m/s^3` | about `0.62 m/s^2` / `1.71..1.80 m/s^3` | Both remain inside current limits; wide is not automatically the harsher time law. |
| Battery used | about `3.836%` | about `4.499%` | Wide adds duration/energy cost. |
| Truth touchdown horizontal error | about `0.0525 m` | about `0.0470 m` | Both pass the `0.10 m` gate, but reveal a shared landing-target fidelity issue. |

The operator observation that wide looked “not really different” is valid at the
behavior-policy level. Its useful difference is the greater altitude, duration,
energy, and tracking envelope. It should remain a stress geometry, not be treated as
proof that a different speed/controller policy was exercised.

The earlier canonical visual observations are also directionally valid, with two
important distinctions:

- The visible truth/estimate separation can be dominated by the configured `0.25 s`
  estimate playback buffer while truth is shown at current source time. It must be
  decomposed into display age and same-time physical error before judging tracking.
- The brisk speed changes at the altitude knots remain within the current dynamics
  limits. The improvement is to make the requested speed law explicit and compare
  commanded versus achieved speed, not to assume every change is a fault.

### Dependency order

1. WP-40 makes pictures, comments, CSV, evaluation, and replay time-consistent.
2. WP-41 repairs the shared landing-target/contact behavior once for both geometries.
3. WP-42 introduces the execution-profile submission contract and catalog layer.
4. WP-43 qualifies the minimal altitude-transition submission matrix.

WP-40 and WP-41 may be implemented independently after explicit authorization. WP-43
is blocked on all three preceding packets because a profile comparison is not useful
until its evidence clock, evaluator, terminal behavior, and identity are trustworthy.

## WP-40 — Review evidence clock and semantic evaluation

**Status:** `IMPLEMENTED`

**Objective:** make operator images/comments and quantitative evidence refer to the
same source-time behavior, and make the evaluator distinguish mission semantics from
generic takeoff/landing phase diagnostics.

### Tasks

- [x] Define one review-frame contract containing run, case, accepted-plan,
      trajectory, source timestamp, wall timestamp, playback age, layer timestamps,
      interpolation state, and snapshot identity.
- [x] Render truth, estimate, desired trajectory, and event markers at the same
      effective source time by default. If an intentionally current truth layer is
      compared with a delayed estimate, label both times and the expected displacement
      from the delay.
- [x] Bind a snapshot and its operator comment to exact source rows so the same frame
      can be recovered from CSV/evidence without relying on wall-clock approximation.
- [x] Preserve the operator comment verbatim and store a separate neutral assessment,
      evidence references, confidence, and disposition (`VALID`, `PARTLY_VALID`,
      `DISPLAY_EFFECT`, `NOT_SUPPORTED`, or `NEEDS_MORE_EVIDENCE`).
- [x] Repair execution-bundle/evaluator reconciliation so a retained accepted plan and
      execution result with matching identities produce a complete report rather than
      the current `INCOMPLETE` state.
- [x] Separate route-phase unintended-stop oracles from diagnostic low-speed phases at
      takeoff, stabilization, landing entry, and terminal flare. Retain the diagnostics
      without letting them contradict the mission-specific no-stop oracle.
- [x] Add exact-time regression fixtures for the reviewed canonical/wide snapshots and
      evaluator bundle, without mutating the retained runs.

### Exit gate

1. A review frame round-trips to the same telemetry samples and makes any inter-layer
   time offset explicit.
2. Same-time truth/estimate error and buffer-induced visual displacement are reported
   separately.
3. Operator text and neutral assessment remain separately attributable.
4. The canonical and wide retained bundles evaluate `COMPLETE` when all required
   matching components exist; an actually missing or mismatched component still fails
   closed.
5. Mission-semantic stop counts agree across campaign analysis and execution
   evaluation while phase diagnostics remain available.

## WP-41 — Landing target alignment and contact-aware terminal behavior

**Status:** `IMPLEMENTED`

**Objective:** make both altitude-transition cases land at their admitted target
rather than descending from the current horizontal position, and remove motor cutoff
before the declared simulated-contact/terminal gate.

### Tasks

- [x] Carry the immutable landing-goal identity, target center, approach point,
      horizontal/vertical capture tolerances, speed tolerance, correction budget, and
      failure action from accepted plan to backend command and terminal evidence.
- [x] Perform a bounded horizontal alignment/settling maneuver at the admitted
      approach altitude before descent. Never derive nominal landing XY solely from
      the current controller state.
- [x] Keep the controller and simulated actuators authoritative through descent until
      simulated ground contact plus the terminal speed/state gate. Do not cut thrust
      merely because the descent command reached nominal zero altitude.
- [x] Record pre-contact vertical speed, touchdown horizontal/vertical error, contact
      classification, post-contact settling, disarm time, and any correction attempts.
- [x] Evaluate landing-region capture as the hard gate and target-center error as a
      quality metric so a safe in-region landing is not falsely failed while alignment
      quality remains visible.
- [x] Reuse one landing implementation and qualification fixture for canonical and
      wide; do not create a geometry-specific landing workaround.

### Exit gate

1. Both cases descend only after admitted approach capture and terminate inside their
   landing regions at or below the declared terminal speed.
2. Target-center error improves relative to the reviewed baseline and is deterministic
   under identical case/profile/configuration/seed.
3. No nominal run contains a motor-cutoff/free-fall velocity step before simulated
   contact.
4. The result, goal-capture record, telemetry, evaluation, analysis, and replay agree
   on approach, contact, touchdown, disarm, and terminal state.
5. The claim remains simulated ground contact only; no physical docking/contact claim
   is added.

## WP-42 — Execution-profile submission contract and catalog surface

**Status:** `IMPLEMENTED`

**Objective:** allow one immutable mission case to accept a small set of justified
execution-policy submissions without turning every profile parameter into a duplicate
mission case.

The existing frozen `progressive-mission-curriculum-v1` and
`time-parameterized-trajectory-v1` contracts are not edited in place. This packet must
define versioned successor contracts and an explicit compatibility/migration path.

### Submission contract

Each submission must bind at least:

- `profile_id`, semantic version, canonical profile hash, status, and human rationale;
- immutable case ID/hash and baseline submission ID/hash;
- one causal question and one principal variable;
- owner layer: planner, time parameterizer, trajectory tracker, or low-level actuator;
- exact path-speed/vertical-rate/segment law, parameters, entry/exit ramps, and
  tolerances;
- applicable mission families/cases and an explicit reason for each inclusion;
- required lower-level evidence and the integration property still being tested;
- supported backend capabilities, semantic adapter mapping, and no-fallback behavior;
- hard safety/dynamics/energy/actuator/terminal bounds;
- expected accepted-plan/trajectory difference and semantic fingerprint inputs; and
- profile-specific metrics, oracles, preview fields, evidence, evaluator, analysis,
  replay, and comparison behavior.

### Tasks

- [x] Define versioned mission-submission and accepted-profile contracts without
      weakening existing case immutability or accepted execution authority.
- [x] Include the selected profile and parameters in plan/program/trajectory hashes
      and every retained/replayed identity boundary.
- [x] Implement the ten-question variation-admission gate from
      `docs/project/WORKFLOW_AND_REQUIREMENTS.md` as an authoring audit with actionable failures.
- [x] Keep mission sub-problems separate: a wait-only, layer-only, or detour-only
      crossing changes allowed solutions and remains a distinct case, while a speed
      law on unchanged geometry is a profile submission.
- [x] Replace ambiguous use of `named_variations` with an explicit case-variation
      relationship plus eligible submissions. Preserve read compatibility for current
      catalog/evidence; do not reinterpret historical values silently.
- [x] Add a nested catalog flow: family -> case/sub-problem -> eligible submission ->
      backend/configuration -> run. Show rationale, delta, prerequisites, support,
      expected trade-offs, and required evidence before Play.
- [x] Show comparisons grouped by exact case and submission, with a deliberate option
      to compare the same profile across canonical/wide when admitted.
- [x] Quarantine unsupported profiles before provisioning and expose the precise
      missing capability or qualification gate.

### Exit gate

1. No label-only submission can pass authoring validation or share a semantic
   fingerprint with its baseline without an explicit, accepted reason.
2. Selecting a submission materially changes the accepted time/control contract and
   all downstream identities; selecting nothing preserves current compatible behavior.
3. The UI never offers every profile for every case by default and explains why each
   offered profile is useful.
4. Historical case hashes, runs, comments, review flags, baselines, and promotions are
   unchanged and still readable.
5. An unsupported backend/profile combination fails before connect, arm, or takeoff;
   there is no semantic fallback.

## WP-43 — Altitude-transition submission set and qualification

**Status:** `IMPLEMENTED`

**Objective:** use canonical and wide altitude transitions to learn how path-speed and
vertical-control objectives affect coupled motion, while adding only profiles whose
causal value justifies their cost.

### Admission matrix

| Proposed submission | Canonical | Wide | Admission reasoning |
|---|---|---|---|
| `planner_retained_baseline` | Retain four reviewed runs | Retain two reviewed runs | Existing geometry comparison; no new run is required merely to rename it. |
| `constant_path_speed.slow` | Implement and qualify | Initially omit | Establishes the primitive with control margin; wide would initially duplicate the same question. |
| `constant_path_speed.stress` | Qualify after slow anchor | Qualify only after canonical passes | Tests a second, deliberately higher operating region; wide adds vertical-envelope/headroom coupling. |
| `ramped_segment_speed.altitude_kinks` | Implement one schedule | Conditional | Tests whether requested slow/fast transitions remain C2 and track without oscillation. Repeat on wide only if a declared vertical-headroom question remains. |
| `bounded_vertical_rate.wide` | Prerequisite/reference only | Implement after constant-speed primitive | Specifically tests larger ascent/descent authority while horizontal pace adapts. |
| `constant_rotor_speed` | `PLANNED_NOT_EXECUTABLE` | `PLANNED_NOT_EXECUTABLE` | Fixed rotor command/RPM cannot also guarantee arbitrary path tracking and lacks a qualified low-level physical semantic mapping. |

### Tasks

- [x] Define route-phase arc length, tangent, curvature, climb/descent windows, and
      entry/terminal ramp exclusions for both immutable geometries.
- [x] Compute the feasible constant-path-speed interval from horizontal/vertical
      velocity, acceleration, jerk, curvature, energy, controller, actuator-headroom,
      approach, and terminal limits. Fail closed if no nontrivial constant interval
      exists.
- [x] Select no more than two initial constant-speed targets: one margin-rich anchor
      and one higher-stress anchor that probes a materially different control region.
      Record why each was chosen; do not generate a dense arbitrary sweep.
- [x] Time-parameterize the unchanged path so scalar route speed is constant only in
      the declared route phase. Takeoff, entry, exit, and landing use explicit smooth
      ramps and are not misreported as constant-speed violations.
- [x] Define one ramped segment schedule whose causal question is speed-transition
      response at altitude changes. The schedule must not contain instantaneous
      velocity jumps at authored knots.
- [x] Define the wide bounded-vertical-rate profile only after canonical constant-path
      speed is qualified. It should hold a declared climb/descent rate while horizontal
      progress adjusts, subject to the unchanged dynamics and terminal gates.
- [x] Keep the controller free to adjust per-motor thrust, attitude, and collective
      command for path/velocity tracking. Record requested/applied/available thrust,
      PWM where modeled, saturation, voltage/current, and energy as evidence, not as a
      falsely constant actuator objective.
- [x] Add profile oracles for path-speed RMS/maximum error, steady-window coverage,
      transition overshoot/settling, vertical-rate error where applicable, route and
      altitude-node capture, no unintended route stop, tracking, dynamics, actuator
      margin/saturation, energy, landing, and terminal state.
- [x] Compare each profile with its exact baseline and compare canonical versus wide
      only for the stress profile that both geometries admit. Report every run; do not
      hide failures in an average.
- [x] Run accelerated qualification first. Add the minimum realtime anchors needed to
      verify source-clock equivalence after deterministic gates pass.

### Exit gate

1. Every admitted profile produces a different accepted time/control trajectory while
   preserving the exact case geometry, route-node order, safety constraints, and
   landing goal.
2. Achieved versus requested path speed or vertical rate is evaluated only in the
   declared windows and meets versioned tolerances; all existing dynamics and terminal
   hard gates also pass.
3. The slow and stress anchors demonstrate distinct operating regions in at least one
   declared metric such as duration, thrust headroom, tracking, or energy; otherwise
   the redundant anchor is removed.
4. Wide adds evidence about vertical-envelope coupling. Profiles that do not add such
   evidence are not copied from canonical.
5. Identical case/profile/configuration/seed repeats reproduce the accepted plan,
   trajectory, profile metrics, terminal outcome, and normalized evidence identities
   where the deterministic contract requires them.
6. All retained review evidence remains immutable, and neither already reviewed case
   is flagged or transitioned again as a side effect.
7. Fast Sim results remain software-simulation claims. Constant-rotor-speed, live
   Isaac, digital-twin, and physical-flight execution remain outside this packet.

## Operator-review successor queue — constraint-directed multi-drone planning

**Status:** `DEFINED_NOT_STARTED`

This queue translates the operator's general intent into bounded implementation work.
The CSV, retained plans, telemetry, evaluations, analyses, and comments establish the
current baseline and expose gaps; they do not require future behavior to copy the
current review workflow or the planner's present ground-delay preference.

### Reconciled evidence baseline

All five reviewed campaign runs finished `SUCCEEDED`. Their current campaign analyses
report `evidence_complete: true` and all required behavior oracles passed. However, the
retained deterministic mission evaluation for every run is `INCOMPLETE` because
`fleet_events` is missing. The analysis metrics are therefore useful diagnostic
baselines, but these exact retained evaluator reports are not qualification closure.
The planner-required pairwise separation was `0.80 m`. The reviewed results are:

| Case | Immutable reviewed runs | Selected plan | Retained/CSV result | What it proves, and what it does not prove |
|---|---|---|---|---|
| `2d.bottleneck.canonical_nominal` | `campaign-run-c89c7b645810ffc542a2`, `campaign-run-ea60ddd772a5aca9780c` | Ground-delay Alpha by `12 s`; predicted minimum separation `1.0642 m` | Truth minimum separation `1.019485 m` and `1.019667 m`; CSV-derived flight-start lag about `12.08 s` and `11.99 s`, with about `8.97 s` and `9.20 s` simultaneous flight | Reproducible safe serialization through the configured corridor. It does not prove a minimum safe release calculation, a geometry-backed edge/contact limit, or an altitude/lateral solution. |
| `2d.head_on_conflict.canonical_nominal` | `campaign-run-6a067834a8d9072e089f` | Ground-delay Alpha by `24 s`; predicted minimum separation `0.867874 m` | Truth minimum separation `0.918629 m`; CSV-derived flight-start lag about `24.44 s` and only about `1.07 s` simultaneous flight | Safe near-complete serialization. It does not force a same-time head-on encounter or prove that the pair found a way around one another. |
| `2d.merge.canonical_nominal` | `campaign-run-2f37348ae19f07b0e94c`, `campaign-run-64fc4cb6bfb8cbfe9ef1` | Ground-delay Alpha by `4 s`; predicted minimum separation `0.934102 m` | Truth minimum separation `0.899823 m` and `0.899826 m`; CSV-derived simultaneous flight about `17.38 s` and `16.46 s` | Repeatable timed merge. Combined timing/geometry candidates were feasible, but the objective selected pure delay; this does not prove parallel-capacity, altitude-stack, or obstacle-conditioned merge behavior. |

The five telemetry CSVs contain 20,963 rows respectively split as `4,104`, `4,158`,
`5,132`, `3,798`, and `3,771`. CSV timing comparisons above use the shared
`recorded_at_utc` basis and each vehicle's `flying` state rather than comparing
unreconciled simulation clocks.

The bottleneck snapshot comment that the stopped grey and orange vehicles differ in
landing position is visually correct but is not, by itself, a landing defect. Alpha
and Beta have intentionally different accepted landing centers about `3.041 m` apart.
Their truth touchdown horizontal errors relative to their own centers were about
`0.063 m` and `0.045 m`, respectively, and were identical in the deterministic repeat.
Those values fit the authored `0.10 m` case gate, but the retained evaluator still
reports target error unavailable and is `INCOMPLETE`. Successor review must therefore
show role-relative landing error and region capture before showing raw fleet spacing;
these retained runs remain diagnostic rather than landing qualification.

Seven exact-time snapshot records remain across the five reviews, but all seven image
payloads were purged during the review transitions and none has a retained neutral
assessment. Their run, case, plan, trajectory, source-time, and operator-comment
metadata remain available, so the comments can be reconciled with CSV/analysis data,
but the historical pixels cannot now be independently re-inspected. WP-50 must create
the neutral assessment and machine evidence references before any future payload purge
or state the same limitation explicitly.

The bottleneck repeats differed by about `0.000182 m` in truth minimum separation; the
merge repeats differed by about `0.000003 m`. That is useful repeatability evidence for
the existing solution, not evidence that the desired alternatives were exercised.
The analysis/evaluator completeness disagreement is itself retained and must not be
hidden by the successful campaign lifecycle state.

Across the ten vehicle traces, analyzer-derived tracking RMS was about
`0.00794..0.02489 m`, tracking maximum was `0.01491..0.03945 m`, processed speed peak
was `0.3788..0.3958 m/s`, and every trace reported zero unintended stops. Exact-CSV
applied-PWM averages during `flying` were about `62.82..62.96%`, maxima were at most
`68.76%`, and no motor saturation flag was set. Those observations support the
operator's “generally good” motion assessment for these runs. The analysis landing
fields put role-relative truth touchdown horizontal error across all three families at
about `0.0268..0.0630 m`, inside the authored `0.10 m` gates, but this remains
diagnostic because the retained evaluator target-error inputs are unavailable.

The raw CSV also contains the same Beta first-takeoff sample in all five runs at source
time about `0.08 s`: state `TAKING_OFF`, `flying=true`, and vertical velocity about
`-0.740979 m/s`. That is above the authored `0.30 m/s` vertical-speed bound if this raw
signal and phase are gate-applicable, while the analyzer summaries report much lower
processed peaks. Its exact cross-family repetition points to a deterministic
takeoff/contact-boundary or phase-classification issue rather than a planner-strategy
difference, but it must be reconciled explicitly; smoothing cannot make a potential
hard excursion disappear from qualification.

The current candidate set searched 89 fixed choices per case. It used a coarse delay
grid (`2, 4, 8, 12, 24, 40 s`), small fixed lateral/vertical offsets, and selected by a
cost ordering that can prefer serialization. Pure lateral, vertical, and speed-only
solutions were infeasible in the reviewed bottleneck and head-on plans; merge admitted
combined timing/geometry alternatives but did not select them.

The present `ExecutionProfileSubmission` changes a time/control law only. The case
schema can admit broad strategy labels, but it cannot express per-submission maneuver
authority, route adherence, deviation budget, same-time encounter obligation, or an
objective such as earliest safe release. Known obstacles are axis-aligned keep-out
boxes and required corridors; they do not yet provide a general solid/free-space model.
Fast Sim evaluates policy separation but does not retain qualified multi-vehicle shape
clearance or contact truth. The available Isaac configuration includes a
`0.092 x 0.092 x 0.029 m` body box with `CONFIGURED_UNQUALIFIED` provenance and
visual-only rotor geometry; it is not promoted into collision evidence for these Fast
Sim runs. Typed replanning primitives exist, but source-time dynamic obstacle/peer
events and atomic in-flight fleet plan replacement remain open.

The reviewed cases, run identities, comments, CSVs, plans, evaluations, and analyses
remain immutable baselines. Successor work adds new contracts, submissions, cases,
and evidence without rewriting those records.

### Operator observations translated into scope

| Review source | General intent retained from the comments | Work-packet consequence |
|---|---|---|
| Bottleneck reviews | Keep the good current runs, but add submissions that can use altitude and simultaneous flight; vary the admitted solution to find the minimum safe launch/release time; use vehicle geometry and collision/intersection edge tests. The landing-spacing snapshot is expected from distinct role targets and must be assessed target-relatively. | WP-44 submission authority, WP-45 shape/contact truth, WP-47 continuous earliest release, WP-49 bottleneck rows, and WP-50 role-relative landing evidence. |
| Head-on review | Force a direct same-time conflict that must be resolved around or above/below, not avoided by a long initial delay; bound how far the reference path may be left; then add reality-oriented artificial changing conditions that require in-flight replanning. | WP-44 adherence/overlap authority, WP-47 forced resolution, WP-48 source-time changes, and WP-49 head-on/dynamic rows. |
| Merge reviews | Permit altitude stacking or parallel merging when free space allows it; let bridges, tunnels, width, ceiling, and side openings determine whether geometry or timing is feasible. | WP-46 structured solids/free passages, WP-47 auditable strategy choice, and WP-49 capacity/precedence rows. |

The common product goal is a flexible, bounded, obstacle- and constraint-directed
planner whose allowed solution space is selected deliberately and evidenced exactly.
It is not a workflow that merely reproduces whichever motion appeared in the CSV.

### Dependency and delivery order

```text
Existing live source-time event/cutover qualification
  -> WP-44 planning-submission contract
       -> WP-45 geometry-backed clearance and contact
       -> WP-46 structured environment and free space
            -> WP-47 bounded constraint-directed joint planner
                 -> WP-48 in-flight environment/peer replanning
                 -> WP-49 reviewed-family case/submission matrix
                      -> WP-50 operator surface and full qualification
```

WP-45 nominal-geometry and protection-layer contracts must land before WP-46 freezes
inflation semantics. WP-46 authoring/schema work may otherwise proceed in parallel
after WP-44, but its integration gate still depends on WP-45. Static WP-49 fixtures may
be authored after WP-46, but no fixture becomes `EXECUTABLE` until the planner,
independent verifier, runtime, and oracle that distinguish it pass their lower-level
gates. The dynamic WP-49 subset also depends on WP-48.

## WP-44 — Planning-submission contract and compatibility

**Status:** `IMPLEMENTED_NOT_FULLY_QUALIFIED`

**Current evidence and open gate:** `campaign/submissions.py` defines hash-bound
planning authority and resolved packages; package self-hash/cross-component validation,
template-bound child submissions, and the runtime request authority chain now fail
closed. The broad round-trip/mutation matrix and every downstream replay/comparison
identity path still require one retained end-to-end qualification run.

**Objective:** add one immutable, case-bound planning request that explicitly states
what the planner may change and what outcome it should optimize, while preserving the
implemented execution-profile submission as a narrower component and preserving all
historical identities.

**Dependencies:** current case identity/evidence contracts and WP-42 profile identity.

### Tasks

- Publish the normative planning-submission/resolved-package reference and machine
  schema, including canonicalization, compatibility, and migration rules.
- Define a versioned `PlanningSubmission` with case hash, stable ID/hash, allowed
  release/precedence, airborne wait, speed, lateral, vertical, and combined authority;
  path-adherence mode and segment/region deviation limits; coordination/overlap rules;
  objective and deterministic tie-break; clearance policy; supported backends;
  optional eligible execution-profile reference; and submission-specific oracles.
- Define one resolved, versioned submission-package artifact that an operator can
  author/download as a single file. It must include or resolve the immutable case/world
  snapshot, vehicle/model references, `PlanningSubmission`, and optional execution
  profile while retaining separate component hashes and one resolved-package hash.
- Give every objective typed terms, units, normalization or lexicographic order,
  equality tolerance, deterministic tie-break, planning horizon, resource budget, and
  declared bounded-search completeness/resolution claim. Strategy labels alone are
  not executable objectives.
- Enforce that a submission may tighten but never weaken case/world, vehicle, safety,
  authorization, landing, energy, dynamics, or evidence bounds.
- Keep `ExecutionProfileSubmission` readable and executable under its current identity.
  Add an explicit compatibility adapter; do not reinterpret an old profile as geometric
  or replanning authority.
- Bind the planning-submission ID/hash through preview, accepted plan, schedule,
  trajectory, runtime authority, telemetry/evidence manifest, evaluation, analysis,
  replay, comparison, and download.
- Add fail-closed parser, canonicalization, hash mutation, unknown-field, unsupported-
  backend, ineligible-profile, contradictory resolved-package, resource-budget, and
  case/submission mismatch tests.
- Expose only submissions admitted by the selected immutable case; do not construct a
  global Cartesian product of cases, maneuver policies, profiles, and seeds.

**Non-goals:** no new search algorithm, obstacle primitive, collision physics, dynamic
perception, or case-matrix qualification in this packet.

### Exit gate

1. Every granted degree of freedom changes the hash and accepted authority; every
   ungranted degree is rejected before provisioning.
2. Exact-route, hard-tube, required-region, and soft-reference submissions compile to
   observably different admissible sets without changing the case hash.
3. Historical profile-only runs remain readable with identical identities and meaning.
4. No submission can weaken a case safety or world constraint, and unsupported
   combinations produce no arm/takeoff command.
5. The single-file resolved package round-trips without losing the separate case,
   world, vehicle/model, planning-submission, and profile identities; mutating any
   component changes the resolved hash and cannot masquerade as the same request.

## WP-45 — Geometry-backed clearance and contact truth

**Status:** `PARTIALLY_IMPLEMENTED__RUNTIME_GEOMETRY_GATES_OPEN`

**Current evidence and open gate:** `campaign/geometry.py` separates center policy,
protected occupancy, and nominal contact for a level-flight cylindrical proxy and
performs continuous piecewise-linear pair/AABB checks with an independently hashed
certificate. Composite body/propeller swept geometry, pose/tilt, first-contact
kinematics, and one shared planner/runtime/replay/evaluator geometry path are not yet
implemented; no physical-contact qualification is claimed.

**Objective:** distinguish center-separation policy, uncertainty-protected occupancy,
and actual vehicle/obstacle geometry intersection and make all three usable by
planning, runtime intervention, and evidence without claiming impact fidelity.

**Dependencies:** WP-44; versioned backend/model provenance.

### Tasks

- Publish the nominal-geometry/protection/contact reference and machine schema,
  including supported primitive/pose types, tolerances, and backend claim status.
- Define a versioned nominal composite collision geometry for body, propeller swept
  volume, payload, pose/orientation convention, and supported conservative
  approximation; bind its source and qualification status.
- Define uncertainty occupancy and operational policy clearance as separate layers on
  top of nominal geometry. Prevent double inflation and retain each layer's identity
  and contribution.
- Implement conservative continuous/swept, pose-aware vehicle-vehicle,
  vehicle-obstacle, and vehicle-boundary clearance checks so tilt or sample spacing
  cannot hide an intersection.
- Retain minimum center-policy separation, minimum signed protected clearance, and
  minimum signed nominal-shape clearance as separate metrics with identities for the
  closest pair/object and source time.
- Only nominal truth-shape intersection is configured contact. On contact, retain
  first-contact time/location, relative velocity, signed penetration, model/config
  identity, numerical tolerance, and deterministic configured response.
- Use the same nominal geometry and explicitly identified protection layers in
  candidate validation, independent accepted-plan audit, runtime monitoring, replay,
  evaluator, and comparison.
- Add negative simulation fixtures at just-clear, center-policy breach/no protected
  breach, protected-envelope breach/no nominal contact, first nominal contact, and
  between-sample tunneling boundaries.

**Non-goals:** resolved crash dynamics, damage, prop-strike physics, survivability,
contact-rich control, or physical collision qualification.

### Exit gate

1. A center-policy breach, protected-envelope breach, and nominal geometry contact are
   independently detectable and cannot be mislabeled as one another.
2. Analytic just-clear/contact fixtures agree with planner, runtime, replay, and
   evaluator results under the same model hash.
3. A known-contact trajectory is never eligible for nominal or physical execution;
   negative cases terminate or take their declared safe response.
4. Uncertainty changes conservative protected clearance without changing nominal
   truth-shape contact, and no inflation component is counted twice.

## WP-46 — Structured obstacles, passages, and route-adherence space

**Status:** `PARTIALLY_IMPLEMENTED__TOPOLOGY_AND_SURFACE_GATES_OPEN`

**Current evidence and open gate:** AABB solids, traversable AABB passages,
solid/free contradiction checks, scalar passage capacity, flight-volume extents, and
path-adherence gates are implemented. Free-space connectivity/topology, per-primitive
lifetime/provenance, role/segment-specific passages, and matching runtime/replay/UI
geometry layers remain open; the six geometry rows are analytic fixtures, not the
required concrete bridge/tunnel successor cases.

**Objective:** make configured world geometry determine whether under, over, side, or
timing solutions are feasible, and make route accuracy versus bounded path freedom an
explicit planning input.

**Dependencies:** WP-44 and WP-45 envelope/inflation contract.

### Tasks

- Publish the structured-world/reference-space schema and static compiler contract,
  including primitive precedence, frame transforms, topology identity, and validation
  diagnostics.
- Add immutable configured solid primitives/composites and explicit free/traversable
  volumes, with frame, lifetime, semantic ID, geometry hash, and provenance.
- Represent walls, low bridges, tunnels, side openings, ceilings, floors, corridor
  closures, and role/segment-specific required regions without relying on prose.
- Define deterministic precedence and reject contradictory solids, traversable
  volumes, workspace boundaries, and required regions. An overlapping free-volume
  annotation may not carve space from an authoritative solid implicitly.
- Inflate obstacles by vehicle envelope, model/localization/prediction uncertainty,
  and submission clearance policy; retain every inflation component.
- Compile `EXACT_ROUTE`, `HARD_TUBE`, `REQUIRED_REGIONS`, and `SOFT_REFERENCE` into
  concrete planner/runtime/evaluator constraints.
- Derive topology/connectivity of remaining free space so left/right/above/below/
  under/through choices are searched when open and rejected with a binding obstacle
  or adherence reason when closed. Derive protected passage capacity/occupancy from
  geometry rather than a family-name special case so a tunnel can admit one vehicle,
  parallel vehicles, or no vehicle under different model/clearance hashes.
- Add authoring/static-validation and preview layers for solids, traversable volumes,
  inflated boundaries, reference route, required regions, and deviation budget.

**Non-goals:** live perception, learned semantic mapping, SLAM, camera reasoning, or
unbounded arbitrary mesh planning.

### Exit gate

1. Closing the ceiling removes overflight; blocking the side removes lateral detour;
   a low bridge with an admitted underpass allows only a geometrically clear route.
2. The same world with different case-bound submissions changes admitted route freedom
   without changing obstacle truth; moving or adding an obstacle changes case/event
   identity, not merely the submission.
3. Preview, accepted plan, runtime clearance, replay, and evaluator use identical
   geometry and inflation hashes.
4. Contradictory geometry fails static compilation, and analytic passage-capacity
   fixtures agree with the independent trajectory-set verifier.

## WP-47 — Bounded constraint-directed joint planner

**Status:** `IMPLEMENTED_WITH_OPEN_PROPERTY_AND_RUNTIME_GATES`

**Current evidence and open gate:** the bounded planner declares selected,
proven-infeasible, budget-exhausted, and verifier-rejected dispositions; applies
lexicographic objectives, derives continuous release candidates, searches admitted
lateral/vertical/timing combinations, and requires an independent certificate. The
in-flight path now lazily returns the first certified feasible candidate within the
frozen budget with an explicit no-optimality claim. Complete property/repeat coverage,
fully topology-derived generators, and runtime reproduction of every retained
alternative remain open.

**Objective:** replace fixed-offset/coarse-delay strategy sampling with a bounded,
deterministic search over exactly the timing and geometric authority granted by the
submission.

**Dependencies:** WP-44 through WP-46.

### Tasks

- Publish the bounded planner-result and independent feasibility-certificate contract,
  including search disposition, objective evaluation, representative alternatives,
  binding constraints, and numerical/completeness claims.
- Compute continuous conflict intervals and earliest safe release within declared
  tolerance instead of limiting minimum-wait experiments to the current delay grid.
- Search the admitted timing, speed, lateral, vertical, and combined space against
  route-adherence, free-space, geometry, dynamics, energy, deadline, terminal, and
  uncertainty constraints.
- State the bounded search domain, discretization/refinement rule, numerical
  tolerances, planning horizon, completeness claim, and timeout disposition. Distinguish
  proven infeasible, unsupported, and budget exhausted; none may provision flight.
- Add synchronized-encounter constraints for source-time launch/route-start skew and
  minimum simultaneous-flight overlap; forbid whole-role serialization when the
  submission requires active resolution.
- Make the declared objective—such as earliest completion/release, path fidelity,
  maximum clearance/robustness, energy, fairness, or simultaneous progress—drive
  selection under a deterministic tie-break, not candidate generator order.
- Retain bounded Pareto/strategy-class representatives and exact rejection/binding
  reasons rather than an unbounded candidate dump. Explain changed segments,
  maneuver, release/wait, predicted closest approach/clearance, and why the winner beat
  each relevant alternative under the typed objective.
- Independently verify the exact accepted continuous trajectory set after search and
  retain a feasibility certificate for submission authority, adherence, dynamics,
  energy, terminal conditions, center policy, protected clearance, nominal geometry,
  and every uncertainty/model hash. Search output alone has no execution authority.
- Add deterministic regression/property tests for open/blocked maneuver dimensions,
  continuous release-time tolerance, infeasibility, and repeated plan identity.

**Non-goals:** globally optimal unbounded planning, learned policy selection, or
relaxation of hard safety/authority limits.

### Exit gate

1. The planner never uses an ungranted dimension and finds each analytically feasible
   timing/lateral/vertical alternative in the bounded fixtures.
2. Earliest-safe-release results meet the declared continuous tolerance and are not
   quantized to the legacy delay grid.
3. A forced simultaneous head-on case cannot pass by full serialization, and every
   accepted choice is reproducible and explainable from retained inputs.
4. Search timeout/budget exhaustion is never reported as proven infeasibility, and no
   candidate reaches provisioning without an independently reproducible feasibility
   certificate.

## WP-48 — Source-time environment and peer replanning

**Status:** `PARTIALLY_IMPLEMENTED__OBJECT_PASSAGE_FAST_SIM_ONLY`

**Current evidence and open gate:** accepted obstacle and passage events can now alter
an executing two/three-drone Fast-Sim route: the execution head establishes a fleet
hold, reads fresh observations, constructs a changed world, rebinds the submission,
plans/certifies inside the frozen budget, prepares every role, commits one software
epoch, and dispatches the replacement routes. The evaluator requires the exact runtime
proposal/decision/world/route authority chain. Peer-trajectory and uncertainty inputs
remain coordinator-contract fixtures rather than planner/runtime integrations;
single-drone goal updates, observed-realtime anchors, and a backend-level distributed
prepare/commit acknowledgement remain open.

**Objective:** exercise reality-oriented but artificially configured changing
conditions during flight and replace the affected fleet plan atomically within the
same bounded submission authority.

**Dependencies:** existing runtime event/cutover qualification plus WP-44 through
WP-47.

### Tasks

- Publish the dynamic world/peer event, replan transaction, contingency, and cutover
  evidence contract with source-time/generation semantics.
- Extend typed scenario events to obstacle appearance/movement/removal, corridor
  closure/opening, uncertainty change, and authenticated peer trajectory/reservation
  updates with source time, sequence, validity, provenance, and canonical identity.
- Give each fixture an observation lead time, prediction horizon, and end-to-end
  sense/validate/plan/commit latency budget. Classify changes inside the unavoidable
  stopping/escape horizon as declared negative intervention cases rather than nominal
  replan successes.
- Inject events during execution rather than reducing them only before provisioning;
  reject duplicate, stale, late, contradictory, or unauthenticated updates.
- Reconstruct fresh fleet state, identify invalidated route segments/reservations, and
  replan only within the original case/submission safety, maneuver, adherence,
  deadline, energy, and terminal authority.
- Keep an independent safety monitor and a prevalidated contingency trajectory or
  controlled-invariant hold/abort set authoritative throughout replanning. Continue an
  old prefix/reservation only for the portion still proven safe under the new event,
  then replace it at one acknowledged atomic fleet cutover epoch. Prevent split-role or
  partially committed program authority.
- Implement declared bounded fallbacks: continue a proven-safe prefix, bounded hold
  where allowed, or coordinated abort/landing when freshness/planning budget expires.
- Retain trigger, observed world/peer generation, invalidation, candidate search,
  selected replacement, acknowledgements, cutover, post-cutover tracking, and
  unaffected-role delay/trajectory impact.

**Non-goals:** real sensor ingestion, obstacle recognition, mapping, prediction from
unqualified perception, or autonomous physical-flight authorization.

### Exit gate

1. A source-time event changes an already executing accepted plan; preflight-only
   reduction cannot satisfy the oracle.
2. No command gap, stale post-cutover command, mixed generation, or unauthorized
   maneuver appears in accelerated or observed-realtime evidence.
3. Planned replacement, safe fallback, stale-event rejection, and no-feasible-replan
   fixtures all produce their declared causal outcomes.
4. Retained timing proves the complete reaction chain met its declared horizon; an
   impossible late event produces the expected bounded intervention and is never
   counted as successful avoidance planning.

## WP-49 — Reviewed-family case and planning-submission matrix

**Status:** `PARTIALLY_IMPLEMENTED__REQUIRED_MATRIX_ROWS_OPEN`

**Current evidence and open gate:** the retained regression subset
`missions/campaigns/sim/qualification/constraint-directed-planning-v1.json` contains
9 bottleneck/head-on/merge planning rows, 6 structured-geometry rows, and 4 dynamic
replanning rows; all 19 currently pass. The accepted object-in-line row now contains a
real changed-world proposal/world/certificates, while peer and negative rows are
explicitly labeled `COORDINATOR_TRANSACTION_ONLY`. This is not the complete required
matrix: concrete under/side/open-ceiling, path-fidelity, lateral/vertical-capacity,
dynamic-peer runtime, repeat, and realtime rows remain open.

**Objective:** turn the bottleneck, head-on, and merge feedback into a small causal
curriculum that varies world truth separately from admitted planning strategy.

**Dependencies:** WP-44 through WP-47 for static rows; WP-48 for dynamic rows.

### Required matrix

| Family/level | Immutable case truth | Planning submissions | Required distinguishing oracle |
|---|---|---|---|
| Baseline | Preserve the three reviewed canonical cases exactly | Historical planner-retimed baseline | Reproduce existing selected plan/evidence identities; no rewritten review state. |
| Geometry/contact boundary fixture | Analytic vehicle-pair and vehicle-solid trajectories with nominal gap fixed at just-clear, policy-only breach, protected-envelope breach, nominal first contact, and between-sample contact | Negative simulation validation only; never normal or physical eligibility | Planner certificate, runtime monitor, replay, and evaluator agree separately on center policy, protected clearance, and nominal contact under the same model/tolerance hashes. |
| Bottleneck: earliest release | Reviewed corridor geometry and safety truth | `earliest_safe_release`; optional fixed-delay regression | Derive minimum feasible release within tolerance, retain occupancy/uncertainty basis, and pass all separation/clearance gates. |
| Bottleneck: simultaneous altitude | Reviewed flight volume and routes, with no obstacle added | Vertical-only synchronized submission with whole-role serialization forbidden | Find a continuously verified altitude-layer solution if one exists in the admitted bounds, or return a certified binding constraint/bounded-search disposition without silently falling back to delay. |
| Passage base: under only | Successor low bridge with sides and overflight closed and one geometrically valid underpass | Under/through authority; lateral-only and vertical-overflight negative submissions | Use the underpass when protected capacity admits it and reject side/over choices with the exact solid or adherence constraint. |
| Passage delta: side opening | Change only one side boundary from the under-only parent so a protected lateral passage opens | Lateral-only plus the same adherence/objective contract | The feasible-set/topology hash adds the side route and the planner uses or rejects it only according to the declared objective. |
| Passage delta: open ceiling | Change only the ceiling/bridge extent from the under-only parent so protected overflight opens | Vertical-only plus the same adherence/objective contract | The feasible-set/topology hash adds the over route; restoring the ceiling removes it with the ceiling as binding reason. |
| Head-on: forced active resolution | Successor direct opposing routes with source-time start/route synchronization and enough shared occupancy to create a conflict | Vertical-only, lateral-only with declared left/right deviation tube, and bounded combined submissions; ground-delay/whole-role hold forbidden | Meet start skew and minimum overlap, execute an admitted around/above/below solution, preserve clearance, and never pass through full serialization. |
| Head-on: path-fidelity boundary | Same open-room head-on truth | Exact/too-tight negative submission versus increasing hard-tube budgets | Identify the smallest admitted deviation budget that becomes feasible and retain the binding route/clearance constraint. |
| Merge: lateral capacity | Successor merge whose only principal delta is sufficient protected lateral width for two simultaneous lanes | Lateral/parallel simultaneous-progress submission | Use parallel capacity, meet overlap/progress gates, and retain lane assignment and clearance; no hidden release serialization. |
| Merge: vertical capacity | Successor of the single-capacity merge whose only principal delta is sufficient protected vertical clearance | Vertical-stack simultaneous-progress submission | Use distinct altitude layers and retain protected/nominal clearance and layer-transition constraints. |
| Merge: single capacity/precedence | Successor merge whose protected passage admits one vehicle at a time | Earliest precedence/release with bounded fairness and wait | Select and explain safe precedence, prove continuous occupancy release, and meet maximum wait/starvation gates. |
| Dynamic obstacle | An initially valid in-flight route followed by a configured obstacle/corridor event | Bounded replan authority with declared fallback | Prove source-time invalidation and atomic replacement around/above/below, or prove the exact safe fallback when all admitted passages close. |
| Dynamic peer conflict | Two executing routes followed by a peer trajectory/reservation update that creates a future conflict | Bounded fleet replan authority | Replan before predicted conflict, maintain one atomic generation and signed clearance, and bound unaffected-role impact. |

Each row must cite the lower-level primitive evidence it reuses. Repeating a seed,
clock mode, or execution profile is a run/qualification observation unless it changes
the causal question. Obstacles and hard corridors belong to immutable case/event
truth; the planning submission says which safe freedoms and trade-offs are permitted
inside that truth.

### Tasks

- Author each concrete successor case with its parent hash, one principal causal
  delta, resolved world/model identities, submission eligibility, oracle, expected
  disposition, prerequisite evidence, and claim boundary.
- Compile every planning submission through the WP-44 contract and admit only the
  authority/objective combinations needed to answer that row's causal question.
- Keep rows `PLANNED_NOT_EXECUTABLE` until their WP-45 through WP-48 primitive,
  independent-verifier, runtime, and evaluator dependencies pass; metadata or a
  family label cannot promote them.
- Implement the geometry/contact and blocked/infeasible cases as explicit negative
  simulation fixtures with no normal or physical execution eligibility.
- Generate a machine-readable matrix manifest and static audit that rejects duplicate
  semantics, bundled principal deltas, missing parents, missing oracles, and unsupported
  backend fallbacks.

**Non-goals:** no exhaustive Cartesian product of geometry, authority, objective,
profile, seed, and backend; no rewrite of reviewed cases/runs; no physical/high-
fidelity qualification; and no execution before lower-level capability gates pass.

### Exit gate

1. Every matrix row has a unique compiler-consumed causal delta and machine oracle;
   no row exists only because the operator mentioned a strategy name.
2. The head-on active-resolution row cannot be satisfied by ground delay, while the
   bottleneck/merge timing rows can intentionally measure minimum safe release.
3. Bridge/tunnel/open-side/open-ceiling and merge-capacity outcomes follow configured
   free space, not hard-coded family names.
4. Static and dynamic negative cases reject/intervene causally and issue no prohibited
   command; all historical reviewed evidence remains unchanged.
5. Every successor case declares its parent and one principal causal delta; bridge,
   side-opening, ceiling-opening, lateral-capacity, and vertical-capacity changes are
   not bundled into one case/hash.
6. Geometry boundary fixtures distinguish policy, protected occupancy, and nominal
   contact and remain simulation-only negative evidence.

## WP-50 — Operator surface, evidence, and qualification

**Status:** `PARTIALLY_IMPLEMENTED__DYNAMIC_REPLAY_AND_FULL_MATRIX_GATES_OPEN`

**Current evidence and open gate:** Campaign Lab already separates planning contracts
from execution profiles and provides resolved-package, static planning, exact-CSV,
landing, snapshot, and review surfaces. Runtime bundles now retain the changed-world
execution-head trace, and the deterministic evaluator rejects missing dynamic or
replacement-authority evidence. The UI does not yet provide the required dynamic
generation/invalidation/cutover replay layers, and the incomplete WP-49 matrix has not
received all accelerated repeats plus observed-realtime anchors. WP-50 therefore
cannot be called fully Fast-Sim qualified from the current regression subset.

**Objective:** make planning freedom, world constraints, selected strategy, geometry
clearance, replanning, and comparison inspectable before and after execution, then
qualify the successor matrix without hiding failures in averages.

**Dependencies:** WP-44 through WP-49.

### Tasks

- Show immutable case/world truth separately from submission authority and optional
  execution profile while allowing one resolved package to be authored/downloaded.
  Preview reference route, adherence regions, solids/free passages, nominal geometry,
  protected/inflated boundaries, candidate alternatives, accepted changes,
  waits/releases, predicted policy separation, protected clearance, and nominal signed
  geometry clearance.
- Keep the case-bound planning-submission/profile selector subordinate to the selected
  mission case in the left navigation hierarchy; keep rationale, feasibility,
  objective, evidence gate, and learning value in the case detail pane.
- Explain infeasibility and selection using binding constraints and the declared
  objective. Do not present a selected delay as though no geometric alternative was
  searched when feasible alternatives exist.
- Add replay/timeline layers for obstacle/peer generations, invalidated plan portions,
  candidate replacement, atomic cutover acknowledgements, fallback, and contact or
  minimum-clearance events.
- Compare each successor against its exact baseline and compare submissions on the
  same case. Report every hard gate/run; do not average away a collision, stale event,
  missed synchronization, unauthorized maneuver, or terminal failure.
- For fleet landing review, show every vehicle's accepted landing region, truth and
  estimated touchdown, region capture, and target-relative horizontal/vertical error
  before any raw stopped-vehicle spacing. Preserve the bottleneck landing comment with
  its neutral assessment that distinct role targets are intentionally far apart.
- Show compact, exact-CSV, time-aligned per-drone graphs for velocity magnitude,
  world-Z altitude, and recorded motor output percentage with explicit signal
  provenance, consistent fleet scales, visible unavailable states, and the row-level
  CSV still downloadable.
- Reconcile raw exact-CSV hard-gate extrema with filtered/resampled evaluator and
  analyzer metrics, including signal identity, phase/window, filter, and any justified
  exclusion. Carry the repeated Beta first-takeoff vertical-velocity transient as an
  explicit diagnostic until its gate semantics and cause are resolved.
- Generate the exact-time neutral assessment and machine evidence references for every
  snapshot used by a finding before its image-retention purge; show an explicit
  unavailable-pixels limitation for legacy records that cannot be re-inspected.
- Require deterministic evaluator `COMPLETE` status and all required fleet evidence
  for successor qualification. An analyzer-level completeness flag or `SUCCEEDED`
  lifecycle state may not override a missing evaluator input such as `fleet_events`.
- Run deterministic/unit/property tests, static compilation, accelerated Fast Sim
  qualification, exact repeats for plan/evidence stability, and the minimum observed-
  realtime anchors needed for source-clock/cutover equivalence.
- Retain a machine-readable matrix of case/submission/profile/backend/config/seed,
  expected disposition, actual result, hashes, oracle results, and claim boundary.
- Retain requirement-to-packet-to-contract-to-test-to-evidence traceability for every
  `REQ-PLN`, `REQ-GEO`, `REQ-RPL`, and applicable `REQ-EVI`/`REQ-UI` item so no packet
  can be marked complete from a UI demonstration alone.
- Group Run history by retained case/submission/profile/planner/configuration semantic
  identities after implementation changes. Show current-iteration runs first and keep
  prior-implementation runs below a labeled divider without deleting or mixing them.

**Non-goals:** no new search, collision, world, or replan semantics in the UI packet;
no lifecycle change to historical reviewed cases; no averages-only qualification; no
physical contact/perception claims; and no requirement to retain every image payload
indefinitely when its assessment/evidence record has been safely retained.

### Exit gate

1. Every executable WP-49 row passes retained accelerated evidence and its declared
   repeats with complete evaluator inputs; selected synchronization and dynamic-
   cutover anchors also pass realtime.
2. Preview, accepted plan, runtime, evaluator, analysis, replay, and download reconcile
   case, planning-submission, profile, geometry, event-generation, and model identities.
3. Operator comments can be traced to neutral evidence assessments and successor
   requirements without changing historical review/lifecycle state.
4. Results are claimed only as deterministic configured Fast Sim behavior. Geometry
   intersection is not reported as physical crash severity, and configured events are
   not reported as real perception.
5. The operator can inspect and download one resolved submission package while still
   seeing which immutable world conditions, planning freedoms, profile, objective,
   geometry layers, and bounded-search/verification claims produced the result.

### WP-44 through WP-50 traceability

| Requirement scope | Packet | Current implemented contract/surface | Primary regression evidence and open boundary |
|---|---|---|---|
| `REQ-PLN-001` through `REQ-PLN-003`, `REQ-PLN-010`, `REQ-MIS-006` through `REQ-MIS-009` | WP-44 | `PlanningSubmission`, `ResolvedPlanningPackage`, component/package hashing, case/profile/backend compatibility, plan/schedule/trajectory/runtime/analysis identity propagation | `test_submissions.py`, planning-contract API test, resolved-package download test |
| `REQ-GEO-001` through `REQ-GEO-005`, `REQ-GEO-009`, `REQ-GEO-010` | WP-45 | level-flight cylinder proxy, protected/policy layers, continuous piecewise-linear pair/AABB clearance, contact classification, independent `FeasibilityCertificate` | `test_geometry.py`; composite swept pose geometry and shared runtime/replay/evaluator use remain open |
| `REQ-GEO-006` through `REQ-GEO-008`, `REQ-GEO-011`, `REQ-PLN-002`, `REQ-PLN-004`, `REQ-PLN-008` | WP-46 | AABB solids/passages, contradiction checks, scalar capacity, flight-volume and path-adherence gates | 6 retained analytic rows plus `test_geometry.py`; topology and concrete successor cases remain open |
| `REQ-PLN-004` through `REQ-PLN-007`, `REQ-PLN-009`, `REQ-PLN-011` through `REQ-PLN-013` | WP-47 | bounded dispositions, continuous release bisection, admitted lateral/vertical/joint generators, lexicographic selection, representative candidates, independent certification | `test_constraint_directed_planner.py`; 9 retained family rows |
| `REQ-RPL-001` through `REQ-RPL-008` | WP-48 | real object/passage changed-world proposal and Fast-Sim execution head; reaction-horizon and all-or-zero coordinator contracts | `test_dynamic_replanning.py`; object-in-line runtime integration in `test_campaign_execution.py`; peer/negative retained rows explicitly transaction-only |
| `REQ-WFL-001` through `REQ-WFL-007`, reviewed bottleneck/head-on/merge causal questions | WP-49 | retained 19-row regression subset with explicit dynamic qualification scope; required successor matrix remains incomplete | `test_constraint_qualification.py`; report SHA-256 `4f386eb18e5906cab5ad9ae74a1a823a54d300b581283386d0230723ead41d94` |
| `REQ-EVI-001` through `REQ-EVI-013`, `REQ-UI-001` | WP-50 | case-bound selectors, resolved preview/download, exact-CSV plots, raw/processed reconciliation, role-relative landing, neutral snapshot guard, semantic iteration groups, dynamic evidence fail-closed checks | Existing evidence/service/API/UI regressions plus the object-in-line runtime evaluator anchor; dynamic replay and full-matrix qualification remain open |

## Operator-review successor queue — selective submissions for every 1D–3D case

This five-packet batch is one design-review unit. Implementation is not authorized by
this entry; the operator explicitly requested work packages first.

| Packet | Status | Independent verification |
|---|---|---|
| WP-52 | `PARTIALLY_IMPLEMENTED__CORE_CAPABILITY_AND_RESAMPLING_GATES_OPEN` | `REVIEW_BLOCKED` |
| WP-53 | `PARTIALLY_IMPLEMENTED__RUNTIME_AND_REJECTION_PROOF_GATES_OPEN` | `REVIEW_BLOCKED` |
| WP-54 | `PARTIALLY_IMPLEMENTED__DYNAMIC_AND_PRODUCTION_RUNTIME_GATES_OPEN` | `REVIEW_BLOCKED` |
| WP-55 | `PARTIALLY_IMPLEMENTED__DYNAMIC_AND_PRODUCTION_RUNTIME_GATES_OPEN` | `REVIEW_BLOCKED` |
| WP-56 | `PARTIALLY_IMPLEMENTED__VISUAL_AND_HIGHER_RUNTIME_GATES_OPEN` | `REVIEW_BLOCKED` |

<!-- WP52-56-DESIGN-PAYLOAD-BEGIN -->

### Frozen originating operator request

> for the submissions i want you to add specific submissions for each subcase, what
> you think makes most sense. e.g. for the first 1D cases i thought it was nice to add
> subcases like this constant velocity thing, or if it is priotrtized to follow the line
> or do smooth transitions between lines like how many points before it steers at and
> so on. then once it has that capability of course it does not have to be implemented
> for every missions or tried out for every mission again, so maybe for a different
> problem maybe something else is interesitng. so for same path have mutlibple
> submissions. you can look at the same for 3 drones already done, i want you to think
> hard on that note and if needed (oyu dont have to do unnessary ones if you cant think
> of ones) for each cases in all 1d to 3D. add work packages first for this

### Frozen design identity and preimages

- Design date: 2026-08-11.
- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Working-tree condition: the campaign implementation is already materially dirty.
  This batch binds the exact preimages below and never identifies its scope as merely
  “the dirty diff.” Existing edits and retained run/case identities are operator-owned.
- Originating requirements: `REQ-MIS-001` through `REQ-MIS-009`, `REQ-REU-001`
  through `REQ-REU-006`, `REQ-MOT-001` through `REQ-MOT-012`, `REQ-PLN-001`
  through `REQ-PLN-013`, applicable `REQ-RPL`, `REQ-EVI`, and `REQ-UI` requirements,
  the eleven-question variation-admission gate, and `REQ-WFL-013` through
  `REQ-WFL-027` in `docs/project/WORKFLOW_AND_REQUIREMENTS.md`.
- Ledger/workflow preimages: `docs/work-packages/ACTIVE.md`
  `538f3ab4e362486284aac1112ca2795fa79a76b1ee5d1054824f2be8c5bcf852`;
  `docs/project/WORKFLOW_AND_REQUIREMENTS.md`
  `c0efd0bafa1e936433e1aa8ee4291a81d176f54ef0e35f45a09bba0261121652`.
- Core campaign preimages: `models.py`
  `81a818caaf6be1db84fca05bee763a37338a826e59c9d9e64102c0e377e334ee`;
  `submissions.py`
  `bd67ff8f2c2465ecd66cf0731305fcaf3fdeece2f15080e314a16af707ca8ca6`;
  `planner.py`
  `6b28d64277f94f7b554e1ddb5da243f1b8b54df035d53e4ec182afa827ce0f49`;
  `trajectory.py`
  `f672289b1519df8b54269ce0ce375b654b1e7fb9529c6469be836102e6567931`;
  `service.py`
  `d5e156f64a5be6a24c2c6f6b55b8f6fde86b1b58445d66d0a375338a579df5af`;
  `runtime_executor.py`
  `eff68869fcc5943adbc5d3b1e258f5304f213417121d9207f312b7d2bd5a3e38`;
  `execution_head.py`
  `a6510c17f13a0f6d8b82ef450c2442b3271b32046932d6c6a7de245dba43e5bc`;
  `qualification.py`
  `9e85e43c6ebfa03389453b44061de2d3a7345f1f73997bef5cbf052435cd2082`;
  `semantic_audit.py`
  `78420241b129477f8e623acab8ee2e79040604266835dc01d92a17ca2c658158`.
- Generator/surface preimages: `scripts/campaign_case_specs.py`
  `5c02700b2638af8ae57223d6ee24418e592a56913ac6588a4ca24f3228d48af9`;
  `CampaignLab.tsx`
  `b3d4a38d965fc0dfe6714b885e1699d0295b341354699d4476a84805eb315b58`;
  UI `models.ts`
  `a396a2ff2cd77956703bfe8b1f0a891b006fd685950f3df16bbfd3d328f88baa`;
  UI `api.ts`
  `7feb12cade8a83f426c1b2017a45ec4d33c28d1a8d0fac366de426ba1d7be29d`.
- UI design-contract preimage: `design.md`
  `4aa78f82633f94dde9310157bc14341e906b24f03ee08f2f4d355f93319e24ca`.
- Together with the entries above and the case-catalog entries below, the following is
  the complete additional dirty/untracked preimage allowlist for the production,
  evidence, API, UI, generator, and test boundaries authorized by this design. A clean
  tracked dependency is identified by the base commit. A future implementation must
  freeze its own exact starting manifest and may not silently absorb a different
  operator-owned postimage.

  ```text
  715afda601bb517482cc868b5ae91b0e8a61e434702f31049fc3f39c2c5167a0  scripts/generate_campaign_catalog.py
  391b34854455672b1a75f9d009fbf1cc8e46c7ef4a41c4888d4378d72d0c76f0  scripts/qualify_altitude_profiles.py
  ff0c1853a0366e21088908ae77c6993463e328a61aa249a03728f70842a0a98b  scripts/qualify_campaign_catalog.py
  7895fc2a942a534cf1b6d28649438a38f1a87382023cde90369e7c9aa2eccf64  scripts/qualify_campaign_runtime.py
  11321ee473aebfb34ddead8122141456358ab571f398bad007f313f0c4ed55fb  scripts/qualify_constraint_directed_planning.py
  f757d136f91b05baa824ce5cb87c6f2bbb32e40e0fa426a2563079d56bbff0a0  src/crazyswarm_app/api/app.py
  ae78fa0502d73b28625e01df41364b9517237838b574ec28daf714eda151026e  src/crazyswarm_app/api/models.py
  b257d952d3ac15bed827c862c7e9891ab005f31a18ca438474cc8c8e93064072  src/crazyswarm_app/api/runtime.py
  b62c7c942dc37d9f9573dba1f650383961b934c2a7b57dc5237f9102cf168b12  src/crazyswarm_app/campaign/analyzer.py
  7f095e3730c8d18c6a13b343cd759ea57444123ec83158d4f5d6a3ad5f31e8c1  src/crazyswarm_app/campaign/api_models.py
  2111911ac0c36602cb660e1e01dc61f6fae10e691c7c4795a1270e577e974b2c  src/crazyswarm_app/campaign/catalog.py
  d6d7b335dbe97633badab7245a5cd21862c0eb5c52e9f981f4a1192afb997f16  src/crazyswarm_app/campaign/execution.py
  62f88d27be13148f04c7dafd04f0ecd2246a93f4727350ad790463399ff02f68  src/crazyswarm_app/campaign/geometry.py
  eff748b46a565c3dc61366821cdc99cbb598db090fb9c165532fb0f71862ad3f  src/crazyswarm_app/campaign/replanning.py
  c7e3ddeee88b235551ba2c31c639ef73da0edddfc46eb94cd5a83c24d96ef221  src/crazyswarm_app/campaign/scenario.py
  cd5a1024a49e2a4a8d515d382025625dd077f33ab6d3a94c1664ab5fae336dda  src/crazyswarm_app/campaign/scheduling.py
  f94e6ad3da7a1024e316615c1ce565f19a67223f1fe3517e480dd397513b7f46  src/crazyswarm_app/observability/evaluation.py
  aa3e3abc76751e4f840145500c50dc419867a0120de53dfe3c9d0223a50dc689  src/crazyswarm_app/observability/storage.py
  403de08a0dab34da533352b2f7c4d33a324bb7503a7264a0bdf2ab944c8778ef  tests/api/test_campaign.py
  5aec0e14811ba7f280a43a9a91d3a1e6ed1a83f8ddcd6ce3222618c608845dc7  tests/api/test_missions_and_replay.py
  f1fd0ba50a3671a5a6b8bb526f06c6bfc4ae8ae51df1c0c6030304ae51ff91ad  tests/campaign/test_campaign_execution.py
  c7d8b414e8613fc84d85b777ffb17100d31c5e916a0cc74b40ceba23c893cdc3  tests/campaign/test_campaign_lab.py
  d6800c6e3e19380498cd80dce7c3e71aa58188cd18d3fea0c2ee92b2c437a615  tests/campaign/test_campaign_service.py
  d738e36db61b43fda145c7d30afc885eab394d8a7fb0b192b8aaae093e6920c5  tests/campaign/test_constraint_directed_planner.py
  c7181495757086bb4d984ecaf83e92a54d7d88dad9ea9b831d0e81e0a0d889f2  tests/campaign/test_constraint_qualification.py
  91611639c62feb62615b024f3164e338e5bb1480c7b79d1ae71fcb38790f04e4  tests/campaign/test_dynamic_replanning.py
  40d4bc26a87e153ec0b3c2a902318cf8540b9d2467acaffc00fb001b61c9b9d0  tests/campaign/test_evidence_reconciliation.py
  e0564c2d4fb402e264109f211b4c961b6176e8b1715175fc4a079b03428fa7f6  tests/campaign/test_geometry.py
  9ba8fae005981f5c58a1f4d7663e98478f90b7327ac269cbff144007c264f042  tests/campaign/test_submissions.py
  19d58f5dd210f01081bb64f55a336e5bc7de214ce21e4584d33a621e8cebd4ca  tests/observability/test_evaluation.py
  dd29794bc632e49010bc3ce51a2b2622934f823bb3d8d0817ee011d90297452f  tests/observability/test_storage.py
  8d8b95d8280648298594dfc088223ffbbda29d9e1550fb2f41eef440856e7df9  ui/app/components/ControlCenter.tsx
  63c65e5b852cef9e7913426cec4c7a52b439066374e86bb9da1524429b3a8d05  ui/app/components/RoomScene.tsx
  8597b063d755bcc1a26f7617ed3b9abc57430fcf717165b87814eb31cde5baf7  ui/app/components/TelemetryDock.tsx
  d98f94235a11cf58090e1ee667f4da1945e2da712d62058d8dcf0b954ab39566  ui/app/globals.css
  9d8f2209e00e88129aed8010aa843ac78058d8b94d896739de1eaedca3ba8427  ui/app/lib/api.generated.ts
  10a71f64d8081cc9d902709baf9a6cb75834cc7a29b3ced085c2ab2601249204  ui/app/lib/campaign-telemetry.ts
  018206d9395a3eb5da8576c9929258359e14500a2a6b337c23fa78a6627d51b2  ui/app/lib/playback.ts
  583189224036bf36f0ef6240abc071800ddb659347109979f0aca86d897b88b0  ui/openapi.json
  30d09e3e7d247f32b96a2414af8cbeff33dbff4576b640547caf64bc29d2929e  ui/tests/api-adapter.test.ts
  674963897a21871454ff1c8d333c81f20f694c5cc31d83c23626be07958671cb  ui/tests/campaign-lab.test.tsx
  115111a470a53e95c500e292a4428694fcb0735151fee16d198c2cb08d53c1f8  ui/tests/campaign-telemetry.test.ts
  68ab86d2bb92566eb89a73b325d0c9304b4b389080b4cf1fd2210c4d402edf77  ui/tests/components.test.tsx
  efa7de3004595d42977706131dae50628906f2d2637b9d5ec816f68d153abd86  ui/tests/playback.test.ts
  aa4526ce9822a2b5a7a350f6483e900d624b20d63640e084a3f57c712a3acd05  ui/tests/renderer-boundary.test.ts
  37d4d9d785408ab287d61f0269a1c8b0b1cf769de48eea60321c34d33b5d8a52  ui/tsconfig.tsbuildinfo
  2c4e17ea5e31235eadba18b6bafd242bf99938fdb2a5bd4939cf7489fd9cb5c3  ui/pnpm-lock.yaml
  6359bd8f75433097f29658553521374ccd6ed4ab214ba2723312aaee39502484  ui/pnpm-workspace.yaml
  ```
- Planned new registry paths
  `missions/campaigns/sim/submissions/capabilities-v1.yaml`,
  `missions/campaigns/sim/submissions/case-submissions-v1.yaml`, and their retained
  admission/qualification manifests are absent at this design gate. No deletion is
  authorized.
- Exact catalog preimages, covering all 54 currently discovered cases:
  `basic-flight-and-route-following/1d-cases-v1.yaml`
  `964aa81d6a112103365bc8842b2cf55d1ea9a5713ad521bc543920363e0ab617`;
  `constraints-and-optimization/1d-cases-v1.yaml`
  `5a7083ab682a170f2019c21015b02cb68fcd4f176abeb75cf869fb03f4f35769`;
  `constraints-and-optimization/2d-cases-v1.yaml`
  `a4235c6f8253cb6f81329c769d712032f9961ea3e6a7aa5f8b4e08b765724abd`;
  `constraints-and-optimization/3d-cases-v1.yaml`
  `48675d50499927d9717b0a6221e470f32b414ccbce3195330d49567cc9a5388c`;
  `coordination-and-allocation/2d-cases-v1.yaml`
  `dd8b48613c58e0a360b8dd4fc5212922eec9fe38ee984317c8a6e6f248426bed`;
  `coordination-and-allocation/3d-cases-v1.yaml`
  `a0c5bd3df40c2e0cb621a4d09d1c2f9c185e6dc6519419d5cd92113afc59f787`;
  `failure-recovery-and-replanning/1d-cases-v1.yaml`
  `e9e99f6f00ace10d19cf18afca0a3160434ed806d5cf66ce854c979f0627e3ad`;
  `failure-recovery-and-replanning/2d-cases-v1.yaml`
  `6d0464c7eefd5d7beba27da2432f9bfab8dc808ae1350f77c6a912d659bc3cac`;
  `failure-recovery-and-replanning/3d-cases-v1.yaml`
  `3a1cf2e3db5bbeaf683d38c528a2c0664f21f71022cb84ae5609a41ace2b1579`;
  `geometric-conflict-resolution/2d-cases-v1.yaml`
  `2d05a0020eb8f88e95cfaf3eeffc30c98eb041bd15ae9c0dd094ba43adfdbe78`;
  `geometric-conflict-resolution/3d-cases-v1.yaml`
  `76a2c1d439bcbcc3f02b28e574722cd9e671d4e425ab8d8f77244426036cf6d5`.

### Batch objective, interpretation, and invariants

Audit every currently discovered 1D, 2D, and 3D case, then give the same immutable
case/path multiple operator-visible submissions only where a distinct causal question
survives the variation-admission gate. Preserve the existing baseline submission for
every case. Develop reusable motion/planning capabilities once at the lowest meaningful
anchor, then bind them by capability identity when a later case needs an integration
check; do not clone the experiment into every mission.

The operator-facing term **Submission** means a resolved planning package. It combines
one case-bound planning submission with an optional execution-profile/core-capability
request while retaining separate component hashes. In the matrices below:

- `P` is a planning submission: authority, adherence, objective, or coordination policy;
- `E` is a case-bound execution-profile experiment used to qualify a time/control law;
- `C` is a reusable core capability request bound without a copied catalog experiment;
- `R` is a planning submission whose differentiator is replan/cutover/fallback policy;
- `BASELINE_ONLY` means the case was explicitly audited and another operator choice
  would be redundant, unsafe, or would change immutable event/world truth.

The following invariants apply to WP-52 through WP-56:

1. Existing case bytes, hashes, historical submissions, and retained runs remain
   immutable. A world, event, start/goal, vehicle, or hard-success-condition change is
   a successor case, never a submission.
2. A submission may tighten but never weaken case safety, geometry, dynamics, energy,
   freshness, authorization, terminal, atomicity, or failure gates. Unsupported rows
   remain `PLANNED_NOT_EXECUTABLE` and issue no provision/arm/takeoff command.
3. A label, objective reorder, or parameter change is admitted only if it changes a
   behavior-driving input and produces an independently observed feasible-set, accepted
   plan, trajectory, command, event decision, or retained evidence difference. If two
   proposed submissions compile to the same semantic fingerprint and observed behavior,
   they collapse to one; prose may not rescue them.
4. Comparisons vary one principal causal variable. Every admission record names fixed
   inputs, reused evidence, expected difference, independent oracle, backend support,
   safety bounds, operator comparison, bounded-search claim, and maintenance value.
5. “How many points before it steers” is not stored as point count because resampling
   would change its meaning. `lookahead_time_s` is the sole authored lookahead input.
   The compiler derives `lookahead_distance_m` from certified entry speed and the
   versioned derivation rule, then caps it by free space and adjacent segment length.
   The request hash binds the time; the resolved-package hash binds time, derived
   distance, `turn_blend_radius_m`, knot/region requirements, deviation, and limiting
   constraint. Validation recomputes the distance and rejects disagreement.
6. The initial steering anchors are deliberately bounded: fidelity-first starts from
   `lookahead_time_s = 0.20` with centerline deviation no larger than the smaller of
   `0.03 m` and 25% of local protected free clearance; smooth-transition starts from
   `lookahead_time_s = 0.60`. The same versioned compiler deterministically derives a
   blend-radius candidate in `0.08..0.25 m`, capped by half the adjacent segment
   length, admitted route tube/free space, and speed/acceleration/jerk feasibility.
   Thus lookahead time, not radius as a second request, is the experiment input.
   Infeasible compiled values fail closed; qualification may narrow them but may not
   broaden safety or silently change the frozen objective.
7. Constant path speed remains the already established `core.constant_path_speed`
   capability. Later cases request it when relevant and test only new coupling; they
   do not repeat the canonical altitude speed sweep or copy its implementation.
8. Every selected submission/profile identity reaches accepted plan, trajectory,
   runtime authority, exact evidence, evaluation, analysis, replay, comparison, and
   download. Search success is separately certified by a continuous feasibility oracle.
9. Current 3D joint cases remain the precedent for one hash-bound fleet schedule,
   selective non-interference, fairness, atomic authority, and all-role evidence.
   New 1D/2D choices do not weaken those joint semantics, and 3D choices are split into
   auditable authority/objective alternatives rather than one overly broad option.
10. Packet implementation proceeds in evidence-sized vertical slices. WP-53, WP-54,
    and WP-55 depend on WP-52 and may otherwise proceed independently; WP-56 integrates
    only rows whose owning capability/runtime gate has passed.

### Frozen variation-admission record for the matrix

The admission decision is made in this design, not deferred to implementation. Every
non-baseline matrix cell is a bounded experiment; each semicolon-separated experiment
is evaluated independently rather than treating all choices in one row as one causal
claim. The future machine manifest serializes this frozen record and may reject an
infeasible alternative, but may not invent or broaden one.

| Gate question | Frozen answer and where the row-specific value is bound |
|---|---|
| 1. Causal question/baseline limitation | The third cell of each row names the question and the behavior the baseline cannot isolate. `BASELINE_ONLY` cells explain why no safe/nonredundant question exists. |
| 2. One changed input/fixed inputs | The experiment ID identifies one principal axis. Objective experiments change only lexicographic objective order; authority experiments change only one maneuver/fallback enum; scalar-profile experiments change only the named scalar. Case/world/event/vehicle/route/hard gates, backend, search budget, seed, and every unmentioned submission field stay fixed. |
| 3. Owning layer | The `P`, `E`, `C`, `R`, and `BASELINE_ONLY` prefixes bind the layer exactly as defined above. |
| 4. Expected semantic difference | The third cell names the expected feasible-set, plan, trajectory, command, cutover, or evidence difference. That behavior-driving field is included in the semantic fingerprint; no difference means the experiment collapses. |
| 5. Independent oracle | The final clauses in each third cell identify row-specific measurements. WP-52/WP-56 additionally require independent continuous spline/geometry, runtime command/state, authority/epoch, and terminal oracles rather than metadata regenerated by the implementation. |
| 6. Reuse/new integration gate | Packet dependencies bind reused WP-42–WP-50 evidence; each row's stated new coupling is its remaining gate. `C` rows cite the lower anchor and do not requalify it. Dynamic rows require the real source-time production entry/cutover path. |
| 7. Backend/status | Only current executable semantics may start as Fast-Sim candidates. Every row on one of the 23 current `PLANNED_NOT_EXECUTABLE` cases, or depending on an open runtime/geometry capability, inherits that status. No backend fallback is permitted; Isaac/hardware remain outside scope. |
| 8. Safety/authority bounds | All exact case hard constraints and the global invariants above remain fixed. Submission tubes, authority, objectives, or fallback choices may only tighten them; the independent feasibility certificate covers continuous clearance, dynamics, energy, terminal, freshness, and atomicity. |
| 9. Operator comparison | WP-56 fixes the preview/post-run comparison: identical case hash plus changed objective/authority/scalar, reference versus accepted route, actual transition/wait/layer/cutover, row oracle, binding constraint, and component/package hashes. |
| 10. Learning value/cost | A row is retained only to qualify a lowest-level reusable primitive or a new mission-specific coupling named in its third cell. The explicit baseline-only decisions prevent count-driven catalog growth. |
| 11. Search/completeness/certificate | The case's frozen bounded search budget/resolution and deterministic tie-break apply. Exhaustion is `SEARCH_BUDGET_EXHAUSTED`, never infeasible/success; an independently implemented continuous feasibility certificate is required before execution. |

Within an objective experiment, authority, adherence, profile parameters, and search
remain identical. Within an authority experiment, objective, adherence, profile, and
search remain identical. Within a fallback experiment, the trigger, old proven-safe
prefix/epoch, planning result, and contingency set remain identical and only the named
prevalidated fallback changes. Within a scalar-profile experiment, the scalar is the
only request change; derived retiming/blend values are outputs. Cross-experiment charts
may be exploratory, but they cannot close a one-variable causal claim.

### Affected production boundaries

- New declarative registries under `missions/campaigns/sim/submissions/` will own the
  versioned capability definitions, case-bound submission specs, prerequisite links,
  admission records, and explicit `BASELINE_ONLY` dispositions. Case YAML remains
  immutable problem truth.
- `campaign/submissions.py` and campaign models will parse/validate the registries,
  resolve planning/profile/capability composition, and remove exact-case/template
  branching as the catalog source of truth. Renamed/child cases must inherit only
  explicitly compatible capability families and receive fresh hashes.
- Planner, trajectory generation, scheduling, replanning/execution head, runtime
  locks, independent feasibility certification, evaluator/analyzer/storage, API models,
  generated UI types, Campaign Lab, replay, download, and qualification tooling are in
  scope only to carry and execute the declared semantics end to end.
- Focused unit/property tests, production-entry API/runtime tests, static catalog
  audits, accelerated Fast-Sim matrices, selected observed-realtime anchors, and exact
  retained qualification manifests are required evidence boundaries.

### Global non-goals and counterexamples

- No full Cartesian product of case × objective × maneuver × profile × speed × seed ×
  backend; no arbitrary “slow/medium/fast” grids; no new submission merely to give every
  row the same count.
- No obstacle, event timing, fault, task, priority, start/goal, route, or hard-corridor
  mutation disguised as a submission. Those require a successor case and parent hash.
- No point-count lookahead, display-only smoothness toggle, strategy label without
  units/tie-break, caller-supplied success boolean/hash as oracle, or report generated
  solely by the code under test.
- No bypass submission for stale/duplicate updates, operator approval, atomic commit,
  acknowledgement, or abort safety. A negative case is not made “interesting” by
  offering an unsafe success path.
- No promotion of currently quarantined dynamic/allocation cases from metadata alone;
  no live-Isaac, physical-flight, perception, damage, or digital-twin claim.
- Counterexamples required by every generalized capability include a renamed compatible
  case, an incompatible child with one authority dimension removed, reordered fleet
  roles, resampled but geometrically identical paths, a boundary-clearance reduction,
  a tampered component/package hash, a search timeout, and an unsupported backend.

## WP-52 — Submission registry and reusable trajectory/planning capabilities

**Objective:** establish one declarative, hash-bound submission system that can express
selective same-case alternatives without hard-coded case IDs, sample-density semantics,
or duplicated core behavior.

**Dependencies:** accepted WP-42 through WP-44 component/hash separation; open WP-45
through WP-50 gates remain dependencies for geometry, runtime replanning, replay, and
qualification claims rather than being assumed complete.

### Tasks

- Add versioned registry schemas for planning submissions, execution-profile anchors,
  reusable capability requests, replan/fallback policies, and explicit baseline-only
  audit rows. Compile every registry row against the current case hash, world/model,
  backend, required capabilities, authority dimensions, and prerequisite evidence.
- Align path adherence with `EXACT_ROUTE`, `HARD_TUBE`, `REQUIRED_REGIONS`, and
  `SOFT_REFERENCE`; retain migration compatibility for current
  `GOAL_SEQUENCE_ONLY`/`ROUTE_CORRIDOR`/`AUTHORED_CENTERLINE` records without silently
  changing their old hashes.
- Define objective terms with units, normalization or lexicographic priority, equality
  tolerance, horizon, resource budget, and `CANDIDATE_SHA256` tie-break. At minimum,
  support path/region fidelity, duration/delay, integrated squared acceleration/jerk,
  energy reserve, separation/clearance robustness, maximum wait/fairness, affected-role
  count, and cutover latency.
- Implement reusable `core.route_fidelity`, `core.corner_transition`,
  `core.energy_aware_retiming`, and the existing `core.constant_path_speed` capability
  binding. Candidate geometry is generated/certified before its time law is applied;
  a profile never grants detour, altitude, waiting, or replanning authority.
- Make the steering contract continuous and sample-density invariant. Preview and
  evidence show the reference polyline, required knots/regions, actual transition start,
  lookahead distance/time, blend radius, maximum/actual deviation, curvature,
  acceleration, jerk, and any safety retiming.
- Add semantic-fingerprint and admission audits that reject label-only rows, unbound
  units, duplicate behavior, impossible prerequisites, cross-case hashes, objective
  choices that never affect candidates, and a registry that omits any discovered case.

### Exit evidence

1. Registry/model/property tests prove exact component/package hashing, historical
   compatibility, no cross-case/profile substitution, and deterministic compilation.
2. Resampling the same route changes point count but not steering meaning or accepted
   geometry within numeric tolerance; changing lookahead/radius/tube does change the
   accepted trajectory or fails with an exact binding constraint.
3. A renamed compatible child binds by declared compatibility rather than exact ID;
   an incompatible child, removed maneuver dimension, tight boundary, or unsupported
   backend fails before provisioning.
4. An independent spline/geometry sampler—not duration metadata or the generator's own
   audit—checks knot/region capture, centerline deviation, curvature, dynamics, energy,
   terminal behavior, and continuous clearance.

## WP-53 — Selective 1D submission curriculum

**Objective:** audit all 20 current one-drone cases, use the simplest cases to qualify
reusable motion and steering capabilities, and add only later alternatives that isolate
a new route, goal, dynamic-update, or fallback question.

**Dependencies:** WP-52. Dynamic `R` rows additionally depend on real production-entry
goal/event/cutover support; until then they remain `PLANNED_NOT_EXECUTABLE`.

The historical baseline is implicit in every row and remains the comparison anchor.

| Current immutable case | Proposed case-specific submission additions or explicit disposition | Principal comparison and distinguishing oracle |
|---|---|---|
| `1d.takeoff_hover_land.canonical_nominal` | `E vertical_cycle.precision_first`; `E vertical_cycle.minimum_duration` | Same vertical route; terminal-error/settle margin versus cycle time/energy. Sampled commanded and observed vertical profiles, touchdown region, monotonic terminal deceleration, and actuator margin distinguish them. Promote the accepted vertical time-law primitive once. |
| `1d.point_to_point_relocation.canonical_nominal` | `P relocation.minimum_time`; `P relocation.energy_reserve` | Same start/goal and direct geometry; duration-first versus energy-reserve-first retiming. Collapse the pair if independent energy/runtime evidence shows no accepted time-law difference. |
| `1d.move_return.canonical_nominal` | `P turnaround.reversal_stop_first`; `P turnaround.continuity_first` | Same route tube, candidates, and authority; only lexicographic objective order changes between minimum centerline/reversal-speed error and minimum jerk/stop duration. Compare reversal count, minimum turn speed, deviation, jerk, duration, and home capture. |
| `1d.altitude_transition.canonical_nominal` | Retain current `E constant_path_speed.slow`, `E constant_path_speed.stress`, and `E ramped_segment_speed.altitude_kinks`; add nothing | This remains the reusable constant-speed/intentional-speed-transition anchor; do not manufacture another smoothing choice. Existing measured steady-window, dynamics, actuator, energy, and terminal gates remain authoritative. |
| `1d.altitude_transition.wide` | Retain current `E constant_path_speed.stress` and `E bounded_vertical_rate.wide`; add nothing | Reuse the canonical primitive and test only wide-envelope vertical tracking/headroom/energy coupling; do not repeat the full canonical sweep. |
| `1d.continuous_waypoint_sequence.canonical_nominal` | `P waypoint.centerline_first`; `P waypoint.smoothness_first` | Same ordered fly-through regions, hard tube, lookahead input, candidates, and authority; only lexicographic objective order changes between cross-track error and integrated jerk. Compare knot/region capture, transition-start distance, unintended stops, maximum deviation, curvature/jerk, and time. |
| `1d.curved_route.canonical_nominal` | `P curve.centerline_fidelity`; `P curve.jerk_first` | Same curve and required regions; radial/cross-track error versus integrated jerk. An independent dense sampler must show a real Pareto trade-off or the second choice is removed. |
| `1d.planar_shape_loop.circle` | `P loop.radial_fidelity`; `C core.constant_path_speed` for one curved-motion integration observation | Preserve circle topology; compare radial/closure error with the baseline and verify constant speed under continuous curvature without creating a copied speed experiment. |
| `1d.planar_shape_loop.rounded_square` | `E corner_transition.lookahead_0_20s`; `E corner_transition.lookahead_0_60s` | Same shape, hard tube, objective, blend derivation, speed profile, and authority; only authored `lookahead_time_s` changes. Compare actual transition start, edge coverage, corner cut, Hausdorff deviation, derived radius, curvature, jerk, and loop closure. This is the primary steering-lookahead anchor. |
| `1d.planar_shape_loop.figure_eight` | `P loop.crossover_fidelity`; `P loop.curvature_continuity` | Same lobes/crossover order: tight crossover capture versus continuity/jerk objective. Reject any smoothing result that changes lobe order or removes the crossing. |
| `1d.static_multi_goal_sequence.canonical_nominal` | `P goals.shortest_valid_capture`; `P goals.smooth_transition` | Same ordered regions and declared holds: earliest valid region entry versus smoother inter-region approach. All captures/holds remain hard; compare path, jerk, capture point, dwell timing, and unintended stops. |
| `1d.boundary_constrained_route.canonical_nominal` | `P boundary.route_fidelity`; `P boundary.robustness_first` | Same boundary/world: authored-route adherence versus maximum protected boundary margin inside required regions. Continuous boundary clearance and reference deviation must move in opposite expected directions. |
| `1d.moving_target.dynamic_nominal` | `R moving_target.earliest_intercept`; `R moving_target.smooth_intercept` | Same update generations: minimum final capture time versus minimum splice jerk/deviation. Compare accepted generation, cutover latency, future-only command replacement, capture, and dynamics. |
| `1d.mid_route_goal_replacement.dynamic_nominal` | `R goal_replacement.minimum_latency`; `R goal_replacement.smooth_splice` | Same authenticated replacement: earliest safe cutover versus later bounded smooth splice. Compare exact cutover source time, stale-command count, splice state continuity, jerk, and final capture. |
| `1d.duplicate_stale_goal_update.dynamic_nominal` | `BASELINE_ONLY` | Duplicate/older generations must always reject without route/hash/cutover change; accepting them is not a valid submission alternative. |
| `1d.planning_budget_expiry.dynamic_nominal` | `R budget_expiry.safe_prefix`; `R budget_expiry.bounded_hold` | Same expired search: continue only an independently proven-safe old prefix versus enter a prevalidated bounded hold. Compare issued authority, stop/hold region, timeout, and absence of partial candidates. |
| `1d.blocked_replan.dynamic_nominal` | `R blocked_replan.safe_prefix`; `R blocked_replan.controlled_land` | Same infeasible goal: retain a safe prefix when its horizon proves valid versus select a prevalidated landing contingency. Both must preserve hard constraints and explain infeasibility. |
| `1d.operator_approval_goal_replacement.dynamic_nominal` | `BASELINE_ONLY` | Hash-bound approval is the causal question. A bypass or auto-approval option would weaken authority; before/after approval remains event evidence, not two submissions. |
| `1d.abort_and_land_goal_fallback.dynamic_nominal` | `BASELINE_ONLY` | The case already anchors the approved abort/land fallback. Alternative destination/event truth would require a successor case. |
| `1d.failure_recovery.dynamic_nominal` | `BASELINE_ONLY` | Observation loss cannot be made interesting by speculative navigation. The existing safe recovery stays authoritative; an independently prevalidated return-home contingency would require a later explicit design/admission gate. |

### WP-53 exit evidence

1. A machine manifest contains exactly 20 1D audit rows, including every explicit
   baseline-only disposition, and losslessly serializes the frozen eleven-field
   admission record above for every proposed addition.
2. Static anchor pairs enter through the normal plan/Play path and produce independently
   measured plan/trajectory/runtime differences without changed case hashes.
3. Dynamic pairs enter through actual source-time update/cutover paths, retain zero
   stale/partial authority, and prove both intended and rejection/fallback outcomes.
4. Capability promotion records the lowest-level qualification and later bindings;
   later missions do not contain copied steering/speed/energy implementations.

## WP-54 — Selective 2D submission curriculum

**Objective:** audit all 18 current two-drone cases and expose the meaningful same-case
choices: timing versus active geometry, fidelity versus formation smoothness, assignment
objectives, and safe atomic replan/fallback policies.

**Dependencies:** WP-52 plus the relevant WP-45 through WP-50 runtime/geometry gate.
Rows on a currently `PLANNED_NOT_EXECUTABLE` case inherit that status.

| Current immutable case | Proposed case-specific submission additions or explicit disposition | Principal comparison and distinguishing oracle |
|---|---|---|
| `2d.head_on_conflict.canonical_nominal` | Retain compatibility submission; add timing experiment `P head_on.earliest_safe_release`; authority experiment `P head_on.synchronized_lateral` versus `P head_on.synchronized_vertical`; objective experiment `P head_on.path_fidelity_combined` versus `P head_on.robustness_combined` | Each experiment keeps all non-axis fields fixed: continuous timing resolution, lateral-versus-vertical active authority, or path-error-versus-clearance objective order. Active submissions require launch/route skew and overlap and cannot pass by full serialization. |
| `2d.perpendicular_crossing.nominal_equal_priority` | `P crossing.earliest_equal_release`; `P crossing.synchronized_lateral`; `P crossing.synchronized_vertical` | Equal-priority timing tie-break versus same-time geometry. Compare release, overlap, maneuver dimension, symmetry/fairness, path deviation, and separation. |
| `2d.merge.canonical_nominal` | Retain compatibility submission; objective experiment `P merge.earliest_precedence` versus `P merge.fair_release`; authority experiment `P merge.parallel_lanes` versus `P merge.vertical_stack` | The first pair changes only completion-versus-maximum-wait objective order; the second changes only lateral-versus-vertical authority under one fixed simultaneous-progress objective. A capacity option stays non-executable if current free space cannot certify it. |
| `2d.overtake.canonical_nominal` | `P overtake.speed_retimed_follow`; `P overtake.lateral_pass`; `P overtake.vertical_pass` | Same routes: remain behind by retiming versus active side/height pass. Compare passing completion, overlap, deviation/layer use, clearance, energy, and no role inversion. Case remains quarantined until production behavior exists. |
| `2d.bottleneck.canonical_nominal` | Objective experiment `P bottleneck.earliest_safe_release` versus `P bottleneck.fair_precedence`; separate authority experiment retaining/splitting current `P bottleneck.simultaneous_vertical` | The timing pair changes only completion-versus-maximum-wait objective order; the vertical experiment changes only the admitted maneuver dimension against a matched simultaneous contract. Every role's occupancy interval, wait, overlap, clearance, and binding constraint are required. |
| `2d.parallel_routes.canonical_nominal` | `P parallel.phase_locked`; `P parallel.energy_balanced` | Same nonconflicting routes: minimize source-time progress skew versus allow independent energy-aware retiming. Compare phase error, energy spread, finish skew, and separation. |
| `2d.leader_follower.canonical_nominal` | `P leader_follower.rigid_offset`; `P leader_follower.elastic_smooth` | Tight relative offset versus bounded elastic offset to reduce follower jerk/energy. Compare role binding, offset envelope, command routing, jerk, energy, and terminal capture. |
| `2d.formation_spacing.canonical_nominal` | `P formation.spacing_fidelity`; `P formation.centroid_smoothness` | Pairwise spacing error versus centroid/trajectory smoothness while both remain hard-bounded. Report complete pair and per-role evidence. |
| `2d.role_allocation.canonical_nominal` | `P allocation.capability_first`; `P allocation.energy_reserve` | Same tasks/vehicles: lexicographic capability/priority versus feasible assignment with maximum remaining reserve. Unique ownership and no wrong-role command remain invariant. |
| `2d.duplicate_assignment_rejection.dynamic_nominal` | `BASELINE_ONLY` | Atomic duplicate rejection has no safe “accept duplicate” alternative; role reorder is a counterexample run, not a submission. |
| `2d.unequal_priority.canonical_nominal` | `P priority.strict_lexicographic`; `P priority.bounded_fairness` | Same priorities: minimize high-priority delay versus retain priority while minimizing maximum wait/starvation. Compare precedence, each wait, inversions, and completion. |
| `2d.constrained_border_height.canonical_nominal` | `P constrained_height.timing_only`; `P constrained_height.lateral_only` | Ceiling remains immutable and vertical is forbidden. Compare minimum release with a continuously certified side detour; no vertical candidate may appear. |
| `2d.no_hover_crossing.canonical_nominal` | `P no_hover.ground_release`; separate authority experiments `P no_hover.speed_only` and `P no_hover.lateral_only` | Each active experiment changes exactly one allowed maneuver dimension against the same objective/adherence/search contract; speed and lateral authority are never bundled. Airborne hold duration must be zero for every choice. |
| `2d.crossing_goal_change.dynamic_nominal` | `R crossing_update.minimum_delay`; `R crossing_update.minimum_affected_set` | Same update: optimize new fleet completion versus change the fewest role programs. Compare invalidated segments, affected roles, cutover epoch, clearance, and unaffected-role delay. |
| `2d.simultaneous_conflicting_updates.dynamic_nominal` | `R conflicting_updates.source_order`; `R conflicting_updates.role_priority` | Same two updates: deterministic source-generation order versus declared role-priority arbitration. Compare accepted/rejected generations, one fleet epoch, and resulting routes; neither may combine contradictory authority. |
| `2d.partial_replacement_failure.dynamic_nominal` | `BASELINE_ONLY` | Partial commit is always forbidden. Alternative all-or-zero fallback may be a later capability, but accepting the prepared subset is never a submission. |
| `2d.leader_loss.dynamic_nominal` | `R leader_loss.promote_follower`; `R leader_loss.coordinated_land` | Same fault: hash-bound successor leadership with revalidated formation versus all-role terminal fallback. Compare lease/role generation, commands, spacing, and terminal states. |
| `2d.coordination_failure.dynamic_nominal` | `R coordination_failure.safe_old_epoch`; `R coordination_failure.coordinated_land` | Same communication failure: continue only a proven-safe old epoch versus coordinated landing. No mixed/new partial generation is permitted. |

### WP-54 exit evidence

1. The manifest contains exactly 18 2D audit rows and no hidden maneuver authority;
   each executable pair has a distinct accepted behavior or one member is removed.
2. Head-on/crossing active submissions prove simultaneous participation; bottleneck/
   merge timing submissions prove continuous release rather than a coarse delay grid.
3. Role reorder, renamed child, ceiling removal/tightening, no-hover enforcement,
   insufficient lateral/vertical capacity, and partial prepare/commit are exercised as
   independent counterexamples.
4. Every two-role result reconciles both roles' commands, separation/geometry,
   ownership/epoch, terminal state, and exact submission/package hashes.

## WP-55 — Selective 3D submission curriculum

**Objective:** audit all 16 current three-drone cases and turn their existing joint
problems into explicit, comparable planning/fallback submissions while preserving one
global schedule/epoch and complete fleet evidence.

**Dependencies:** WP-52 plus relevant WP-45 through WP-50 gates. Existing 3D behavior
is the baseline, not evidence that every proposed alternative already executes.

| Current immutable case | Proposed case-specific submission additions or explicit disposition | Principal comparison and distinguishing oracle |
|---|---|---|
| `3d.single_pair_conflict.canonical_nominal` | `P single_pair.selective_timing`; `P single_pair.selective_lateral`; `P single_pair.selective_vertical` | Resolve Alpha/Beta by one admitted dimension while minimizing Gamma impact. Compare changed-role set, Gamma path/delay, overlap, maneuver, and fleet clearance. |
| `3d.simultaneous_center_conflict.joint_schedule_v2` | Separate timing experiment `P center.global_earliest_schedule`; authority experiment `P center.synchronized_lateral` versus `P center.synchronized_layers`; objective experiment `P center.earliest_combined` versus `P center.robust_combined` | Each experiment changes only timing resolution, lateral-versus-vertical authority, or completion-versus-clearance objective order. Every pair edge, overlap, priority/wait, and one schedule hash are required. |
| `3d.merge.canonical_nominal` | Objective experiment `P merge.fifo_fair` versus `P merge.priority_precedence`; authority experiment `P merge.parallel_capacity` versus `P merge.vertical_capacity` | The first pair changes only fairness-versus-priority objective order; the second changes only lateral-versus-vertical capacity authority under a fixed overlap objective. Capacity rows fail closed if free space cannot certify all three protected envelopes. |
| `3d.bottleneck.canonical_nominal` | `P bottleneck.earliest_queue`; `P bottleneck.max_wait_fair`; `P bottleneck.direction_batch` | Minimum makespan versus minimum maximum wait versus bounded same-direction batching. Compare queue order, occupancy, direction changes, starvation, pad occupancy, and all-role terminal state. |
| `three_drone_multi_conflict` | `BASELINE_ONLY` legacy compatibility/regression | It overlaps the simultaneous-center family and receives no new catalog choices. Migration must point operators to the hash-distinct canonical successor without rewriting the legacy case/run. |
| `3d.formation_shape_transform.canonical_nominal` | `P formation.shape_fidelity`; `P formation.centroid_smoothness`; `P formation.energy_balance` | Same transform: minimize shape/phase error, centroid jerk, or fleet energy spread. Shape topology, overlap, pairwise bounds, per-role identity, and landings remain hard. |
| `3d.role_allocation.canonical_nominal` | `P allocation.capability_priority`; `P allocation.energy_reserve`; `P allocation.balanced_utilization` | Same tasks/fleet: capability/priority, total reserve, or workload spread. Compare complete assignment, idle reserve, energy, and deterministic tie-break. |
| `3d.duplicate_assignment_rejection.dynamic_nominal` | `BASELINE_ONLY` | Duplicate ownership must atomically reject for every role ordering; unsafe acceptance is not an experiment. |
| `3d.persistent_coverage_reserve_handover.dynamic_nominal` | `R handover.minimum_coverage_gap`; `R handover.maximum_reserve_margin` | Same threshold/event: fastest certified takeover versus later/safer energy-margin handover. Compare coverage gap, lease epoch, overlap, outgoing landing, reserve energy, and unaffected Beta coverage. |
| `3d.unequal_priorities.canonical_nominal` | `P priorities.strict_lexicographic`; `P priorities.bounded_fairness`; `P priorities.minimax_wait` | Same frozen 200/150/100 roles and authority; objective-order experiments compare priority delay, priority-preserving fairness, and minimum maximum wait. Report every inversion, delay, starvation bound, and completion. |
| `3d.constrained_volume.canonical_nominal` | `P constrained.timing_makespan`; `P constrained.priority_order`; `P constrained.robust_schedule` | Same volume with geometric options forbidden: completion time, priority, or temporal robustness. No lateral/vertical maneuver may leak into candidates. |
| `3d.alternative_layers_detours.canonical_nominal` | Authority experiment `P alternatives.lateral_only` versus `P alternatives.vertical_only`; objective experiment `P alternatives.energy_combined` versus `P alternatives.robust_combined` | The first pair changes only the maneuver dimension; the second keeps combined authority fixed and changes only energy-versus-clearance objective order. Retain rejected representatives and binding reasons, not generator order. |
| `3d.cascading_replan.dynamic_nominal` | `R cascade.minimum_affected_set`; `R cascade.minimum_completion`; `R cascade.robustness_first` | Same three-generation cascade: minimize changed roles, makespan, or post-cutover clearance. One bounded cascade order/epoch and no stale command are invariant. |
| `3d.acknowledgement_loss.dynamic_nominal` | `R ack_loss.safe_old_epoch`; `R ack_loss.fleet_land` | Same missing acknowledgement: continue the independently proven-safe old fleet epoch or coordinate all-role landing. Zero partial commit is invariant. |
| `3d.fleet_abort_fallback.dynamic_nominal` | `BASELINE_ONLY` | Old authority is unsafe and replacement cannot commit; coordinated all-fleet abort/landing is the defining safe outcome, not one option among weaker policies. |
| `3d.leader_follower_recovery.dynamic_nominal` | `R formation_loss.deterministic_successor`; `R formation_loss.fleet_land` | Same leader loss: rebind a declared successor and revalidate every role, or land all roles. Compare lease generation, shape/spacing recovery, affected commands, and terminals. |

### WP-55 exit evidence

1. The manifest contains exactly 16 3D audit rows and retains status-neutral explicit
   baseline-only dispositions for the executable legacy row and safety-negative rows.
2. Selective cases prove unaffected-role non-interference; global cases prove one
   schedule/epoch, all-pair feasibility, fairness/priority, and complete all-role
   terminal/ownership evidence.
3. Reordered roles/priorities, one removed layer/detour, insufficient three-envelope
   capacity, a late cascade, one missing prepare/ack, and tampered fleet-package hashes
   independently fail or select the declared fallback.
4. No three-role result is inferred from separately safe pair plans or a subset of
   role observations.

## WP-56 — Operator comparison surface, lifecycle, and qualification

**Objective:** make selective submissions understandable and reproducibly comparable,
then qualify only the rows whose real production path and owning capability gates pass.

**Dependencies:** WP-52 and the implemented subset of WP-53 through WP-55; open dynamic,
geometry, replay, realtime, high-fidelity, and hardware gates remain visibly open.

### Tasks

- Enforce `REQ-UI-001` exactly: the left navigation is case-first and shows baseline,
  admitted case-specific planning submissions, and only applicable reusable capability
  requests directly beneath the selected Mission case. Rationale, owner, feasibility,
  evidence gate, learning value, and mission-case explanation stay in the right detail
  pane. Never embed the selector inside its evidence card or flatten 54 cases globally.
- Preview fixed case/world truth separately from authority, objective, adherence tube,
  reference/accepted path, actual steering-transition start, lookahead, blend radius,
  waits/layers/detours, predicted clearance, rejected alternatives, prerequisites,
  support status, and resolved component/package hashes.
- Compare submissions on the identical case/hash. Show plan/trajectory difference,
  route fidelity, smoothness/dynamics, speed/energy, wait/fairness, geometry/separation,
  affected roles, cutover/fallback, terminal state, and raw-versus-processed provenance
  as applicable. Never average away one role, collision, stale event, unauthorized
  maneuver, failed terminal, or incomplete evaluator input.
- Generate a machine-readable 54-row coverage/admission manifest and qualification
  matrix. Static audit fails on an omitted discovered case, unexplained baseline-only
  row, duplicate semantic fingerprint, missing oracle/prerequisite, unexecutable status
  promoted to executable, or catalog choice with no production implementation.
- Group historical and new runs by case/planning-submission/profile/capability/backend/
  config semantic identity. Existing reviewed runs stay immutable and comparisons never
  mix implementation generations without a labeled boundary.
- Qualify in vertical slices: registry/model tests; independent geometry/spline oracle;
  production API/plan/Play/evidence path; intended plus rejection/boundary/generalization
  tests; accelerated Fast Sim repeats; then the minimum observed-realtime anchors for
  clock-, synchronization-, transition-, and cutover-sensitive claims.
- Meet the root `design.md` interaction contract: semantic HTML, visible focus,
  keyboard reachability and Enter/Space/arrow/Home/End/Escape behavior where applicable,
  correct focus containment/restoration, programmatic labels, non-color state cues,
  approximately 40–44 px targets, and reduced-motion/transparency behavior.
- Exercise desktop and narrow layouts with realistic long case/submission labels,
  expanded/collapsed navigation, and loading, empty, disabled, error, unsupported,
  `PLANNED_NOT_EXECUTABLE`, and overflow states. Reflow before controls/text collide;
  dialogs/sheets stay within the dynamic viewport and scroll internally.
- Run UI unit/interaction tests, type checking, linting, and the production build, then
  inspect the actual rendered Campaign Lab at its intended desktop viewport and
  narrowest supported desktop/tablet width. Retain screenshots or an equivalent visual
  inspection artifact and record overlap, clipping, unintended scroll, alignment,
  contrast/readability, focus loss, and console-error results; a build alone cannot pass.

### Batch executable exit and claim matrix

1. Static inventory evidence proves all 54 current cases were considered: 20 1D,
   18 2D, and 16 3D. Baseline-only is an evidence-backed disposition, not an omission.
2. Every visible alternative passes the eleven-question admission gate, changes one
   behavior-driving input, has a distinct fingerprint, and produces an independently
   observed behavioral difference or a precise safe rejection. No count quota applies.
3. The real production chain is traced from case/submission selection through resolved
   package, accepted plan, trajectory/fleet authority, runtime state/commands, retained
   evidence, evaluator, analyzer, replay, comparison, and download. Hashes/configured
   metadata alone are not proof.
4. Core capability claims demonstrate one anchor, a renamed/compatible generalization,
   an incompatible child/boundary rejection, and an independent oracle. Later case
   bindings test only new coupling and cite prerequisite evidence.
5. Claim boundaries are recorded per row as `MODEL_ONLY`, `COMPONENT`, `INTEGRATION`,
   or `PRODUCTION_ENTRY`; `NO_RUNTIME`, `FAST_SIM`, `LIVE_ISAAC`, or `HARDWARE`; and
   `NOT_APPLICABLE`, `ACCELERATED`, or `OBSERVED_REALTIME`. A design or reviewer pass
   never upgrades runtime/physical qualification.
6. Packet-by-packet implementation claims, checks, exact pre/post manifests, independent
   implementation verdict, residual P2 limits, ledgers, qualification artifacts, and
   operator docs reconcile before any packet moves to `COMPLETED.md`.
7. Rendered UI evidence proves the left-navigation/right-detail placement at desktop
   and narrow widths, every applicable state above, long-label wrapping, keyboard-only
   completion, visible/restored focus, semantic accessible names/state, reduced motion,
   no overlap/clipping/unintended scroll, no console errors, and a passing production
   build. `REQ-UI-001` or `design.md` failure keeps WP-56 open.

### Implementation test ownership and order

The future implementer owns missing fixtures/tests. For each packet, first make the
smallest behavior regression fail for the intended reason where practical; then run
affected registry/model and planner/trajectory/replan tests, production-entry API and
runtime tests, static/type checks, adjacent campaign regressions, deterministic
qualification generation, accelerated repeats, and only then selected observed-realtime
anchors. Frozen expectations change only through an explicit design revision. The
implementation gate uses a different fresh verifier from this design review and allows
one fix/recheck only.

<!-- WP52-56-DESIGN-PAYLOAD-END -->

### WP-52 through WP-56 design verification record

- Initial design payload SHA-256 (inclusive of delimiter lines):
  `c115615925279d7342e5fa714d95e6a983e639a61cd4e7f123950f99980c7e48`.
- Initial reviewer: `/root/wp52_56_plan_review` on 2026-08-11.
- Initial verdict: `BLOCKED_WITH_FINDINGS`. Four P1 findings identified incomplete
  dirty/untracked preimage coverage, deferred/partly multi-variable admission records,
  an incorrect `3d.unequal_priorities` priority tuple, and missing mandatory UI
  placement/interaction/render/build gates. P2 notes covered the legacy executable
  row's status wording and lookahead-time/distance consistency.
- Sole author revision: completed. It adds the complete affected dirty/untracked
  allowlist, freezes the eleven-question record and one-axis experiment rules, splits
  the cited bundled experiments, corrects the tuple to `200/150/100`, makes lookahead
  time authoritative with validated derived distance/radius, uses status-neutral legacy
  wording, and adds exact `REQ-UI-001` plus `design.md` UI gates.
- Revised design payload SHA-256 (inclusive of delimiter lines):
  `69610ffc436817b2c610be998423fd87afe589b2406e594e04744ffcfc2604d2`.
- Review scope: the exact delimited payload above as one related packet batch.
- Focused recheck: same reviewer `/root/wp52_56_plan_review` returned
  `DESIGN_VERIFIED`. All four P1 findings and both P2 notes were resolved; the reviewer
  reproduced all 48 added allowlist hashes, the `design.md` hash, absent planned registry
  paths, the 200/150/100 tuple, the revised payload hash, and found no residual P0/P1 or
  P2 issue within the focused scope. No third automatic pass was used.
- Mechanical closeout delta: only this verification record and the five separate
  `Independent verification` fields changed after verdict. The delimited payload remains
  byte-identical at the accepted hash. No implementation is authorized by this
  design-only request.

### WP-52 through WP-56 implementation-start record

- Operator authorization: 2026-08-12 request to implement all five packets.
- Accepted design SHA-256:
  `69610ffc436817b2c610be998423fd87afe589b2406e594e04744ffcfc2604d2`.
- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Exact starting post-design ledger SHA-256:
  `9fceac251681d5214a7a3e145297b57a0a31ff2cf8d47a0a6d9f76777ad94eae`.
- Production/test/UI preimages remain the exact hashes frozen in the accepted design;
  the planned submission registries and WP-52–56 qualification/audit artifacts were
  absent. The final manifest must list every actual changed/new/deleted path and exact
  postimage rather than describe the shared dirty tree.
- Implementation verification must use a different fresh verifier from
  `/root/wp52_56_plan_review`; no implementation claim is yet independently verified.

<!-- WP52-56-IMPLEMENTATION-PAYLOAD-BEGIN -->

### WP-52 through WP-56 corrected implementation payload

This is the sole consolidated correction after the initial implementation review. It
supersedes implementation payload
`c628a248ad74f518d074ce35684e40301433bca8ebcdc91454f43d1b44d3dc8b`
without changing the accepted design payload. The implementation remains independently
unverified until the same implementation reviewer completes the one permitted focused
recheck. All packets remain in `ACTIVE.md`; no runtime, realtime, high-fidelity, or
hardware gate is inferred from the static, integration, or preview evidence below.

| Packet | Canonical status | Independent verification | Implemented boundary and retained limit |
|---|---|---|---|
| WP-52 | `IMPLEMENTED` | `IMPLEMENTED_UNVERIFIED` | Explicit admission records, semantic fingerprints/collapse proofs, compatible-child/backend fail-closed rules, validated constant-speed and corner compilers, planner/trajectory consumption, exact package identity, and API exposure are implemented. Evidence reaches integration and the normal no-runtime preview entry only. Route-fidelity and energy-aware retiming remain `PLANNED_NOT_EXECUTABLE`. |
| WP-53 | `IMPLEMENTED_WITH_OPEN_PRODUCTION_RUNTIME_GATES` | `IMPLEMENTED_UNVERIFIED` | Exactly 20 1D rows are audited. Two vertical profiles, circle constant speed, and the feasible rounded-square lookahead produce independently sampled distinct trajectories and enter the normal service preview. The unsafe `0.20 s` corner choice is visibly rejected without a command. Per-row runtime/realtime execution remains open. |
| WP-54 | `PARTIALLY_IMPLEMENTED__DYNAMIC_AND_PRODUCTION_RUNTIME_GATES_OPEN` | `IMPLEMENTED_UNVERIFIED` | Exactly 18 2D rows are audited; supported static alternatives enter bounded planning. Dynamic/fallback alternatives and unavailable capabilities remain precise commandless rejections. Full pairwise runtime/evidence and the packet's dynamic counterexamples remain open. |
| WP-55 | `PARTIALLY_IMPLEMENTED__DYNAMIC_AND_PRODUCTION_RUNTIME_GATES_OPEN` | `IMPLEMENTED_UNVERIFIED` | Exactly 16 3D rows are audited with explicit global/selective authority alternatives and baseline-only dispositions. Supported static alternatives enter bounded planning; new fleet cutover/fallback and capacity execution remain open. |
| WP-56 | `IMPLEMENTED_WITH_OPEN_VISUAL_RECHECK_AND_HIGHER_RUNTIME_GATES` | `IMPLEMENTED_UNVERIFIED` | The case-first selector, rationale/evidence/learning details, disabled non-color state, comparison metadata, qualification endpoint, generated API types, responsive source, and exact production build are implemented. The earlier visual observation is invalidated because it inspected a stale release; live desktop/narrow reinspection of the corrected release and all higher runtime/state gates remain open. |

#### Corrected behavior and claim matrix

- Registry generation discovers 54 immutable cases (`20/18/16`) and serializes 111
  explicitly admitted proposals. It exposes 28 executable planning alternatives,
  compiles all 24 hidden proposals during audit, and retains their candidate fingerprint,
  equivalent visible fingerprint, baseline fingerprint, and equivalence proof. No
  collapse failure remains.
- Every experiment/value carries its explicit causal question, baseline limitation,
  behavior difference, distinguishing oracle, learning value, reused evidence, new
  integration gate, backend semantics, safety bounds, and operator comparison. Pair
  validation rejects changes outside the declared axis. `boundary.objective` now varies
  objective order only; crossing timing and authority are separate experiments.
- Exact case IDs require exact hashes. Parent inheritance requires a template explicitly
  named compatible by the reviewed source row; template fallback requires exactly one
  such row. Removed authority, unsupported backend, ambiguous/mismatched identity, and
  an unavailable requested strategy fail closed. A renamed compatible altitude child
  retains the source profiles. Intentional in-flight changed-world narrowing is confined
  to an explicit parent-bound replanning path rather than generic rebinding.
- The corner compiler derives and validates target/certified speed, adjacent-segment,
  protected-free-space and hard-path-deviation caps, dynamics cap, safety-retiming
  factor, lookahead distance, turn radius, and limiting constraint. Planner and
  trajectory generation consume the same resolution. Recomputed-self-hash tampering of
  radius or limit fails. The `0.20 s` rounded-square request is safely
  `PLANNED_NOT_EXECUTABLE`; the feasible `0.60 s` request drives the generated steering
  transition.
- `core.route_fidelity` and `core.energy_aware_retiming` are honestly downgraded to
  `PLANNED_NOT_EXECUTABLE` with no qualified backend or anchor. The registry rejects an
  `EXECUTABLE` capability without both.

| Claim | Trigger / effect / oracle | Demonstrated boundary |
|---|---|---|
| Registry admission, one-axis validation, all 24 collapses, strict child/backend behavior | Generator plus compiled registry rows; stored admission/fingerprint comparisons; rejected removed-authority, unsupported-backend, tampered, and renamed-child counterexamples | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` |
| Four executable anchors | Direct resolved-plan/trajectory construction with independent sampled path, duration, speed, transition, identity, and perturbation comparisons | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` |
| Normal application entry for those four anchors | Temporary `CampaignService.preview_active` calls producing resolved preview artifacts without starting a simulator or issuing commands | `PRODUCTION_ENTRY / NO_RUNTIME / NOT_APPLICABLE` |
| Unsafe `0.20 s` rounded-square choice | Validated compiler plus bounded planner rejects the deadline-infeasible, safety-retimed choice; no command is provisioned | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` |
| UI source and immutable production release | Responsive source, unit/accessibility assertions, generated types, build, exact source/built hashes and current release pointer; live corrected-release visual inspection pending | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE` |

The qualification claim is therefore deliberately limited to integration/no-runtime
or normal production preview/no-runtime. It makes no `FAST_SIM`, `ACCELERATED`, command,
runtime-evidence, or realtime claim.

#### Exact scoped correction manifest

Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`. `ABSENT` means absent at the accepted
design gate. There are no implementation-owned deletions. The delimited implementation
section itself is an implementation-owned section: its preimage is payload
`c628a248ad74f518d074ce35684e40301433bca8ebcdc91454f43d1b44d3dc8b` and
its exact postimage is the inclusive payload hash recorded immediately outside the end
delimiter. Additional operator-owned dirty-tree paths are excluded.

| Change | Path | Frozen preimage | Frozen postimage |
|---|---|---|---|
| modified | `src/crazyswarm_app/campaign/models.py` | `81a818caaf6be1db84fca05bee763a37338a826e59c9d9e64102c0e377e334ee` | `31c3b5067972298b9dbd4a4dc026ff3b48de96685b253a9b22d48293eb71fdf0` |
| modified | `src/crazyswarm_app/campaign/submissions.py` | `bd67ff8f2c2465ecd66cf0731305fcaf3fdeece2f15080e314a16af707ca8ca6` | `1c4633c5958432789fb3f34b369f302ebfa43d2d39a001a8b13bff44eb6e912b` |
| modified | `src/crazyswarm_app/campaign/planner.py` | `6b28d64277f94f7b554e1ddb5da243f1b8b54df035d53e4ec182afa827ce0f49` | `e652ef5b33d8e9c3bb46eac343579ac21569acfce7b5b5de0981e2f451e1aad1` |
| modified | `src/crazyswarm_app/campaign/trajectory.py` | `f672289b1519df8b54269ce0ce375b654b1e7fb9529c6469be836102e6567931` | `548c837110203e195d120eabed0dc1796d9b673f067569c37532bad15ccc5df2` |
| modified | `src/crazyswarm_app/campaign/geometry.py` | `62f88d27be13148f04c7dafd04f0ecd2246a93f4727350ad790463399ff02f68` | `916230c6ffe7ea2626c90d2eb2a6740b71aa89eb1227c51a13ab0deab67e41d6` |
| modified | `src/crazyswarm_app/campaign/service.py` | `d5e156f64a5be6a24c2c6f6b55b8f6fde86b1b58445d66d0a375338a579df5af` | `3874d7db504198ff67ea193f263e0b5bc119fc1af65616c3816664ebb0cacb37` |
| modified | `src/crazyswarm_app/campaign/replanning.py` | `eff748b46a565c3dc61366821cdc99cbb598db090fb9c165532fb0f71862ad3f` | `8a80ff02979979affe6dc1cee9d4d0550430473d36de0a3fb5d1abffe0f054e9` |
| modified | `src/crazyswarm_app/api/app.py` | `f757d136f91b05baa824ce5cb87c6f2bbb32e40e0fa426a2563079d56bbff0a0` | `071fc7283066960c23996425c2167d888e3443f675781b7ed4e9c245fd781878` |
| new | `scripts/generate_submission_registry.py` | `ABSENT` | `c755aed6f21c91e4146b24dd224e801d9599d27db0d9e49976b7111dbc9f7449` |
| new | `scripts/qualify_submission_registry.py` | `ABSENT` | `658b1de5fb9ac364aea01d6dab6a03595c00a427ef1294f44928736652f8d979` |
| new | `missions/campaigns/sim/submissions/capabilities-v1.yaml` | `ABSENT` | `7b566c1cfbb6f06f0a188173a9ab748acffdcf434e92d8f595df3a7b7fb3e67e` |
| new | `missions/campaigns/sim/submissions/case-submissions-v1.yaml` | `ABSENT` | `1f0bda6c2cdeee58ff6ad0f592af12736b3b851e499d2c461b98dab227ef8387` |
| new | `missions/campaigns/sim/qualification/selective-submission-registry-v1.json` | `ABSENT` | `04802b58725c93186890accd6d9f01005bd27bace59dcf2e3434d3e0af0de3af` |
| new | `missions/campaigns/sim/qualification/selective-submission-ui-inspection-v1.json` | `ABSENT` | `b58665ffde8ff2c8e9a09eccc78d6a12af5f2432d63bdb08693a5e81b3cb3c47` |
| modified | `tests/campaign/test_submissions.py` | `9ba8fae005981f5c58a1f4d7663e98478f90b7327ac269cbff144007c264f042` | `e51b8229da4b4aa048feea303e458491430bff8b103f227fad3b6a8481266914` |
| modified | `tests/campaign/test_dynamic_replanning.py` | `91611639c62feb62615b024f3164e338e5bb1480c7b79d1ae71fcb38790f04e4` | `d0197febfc23dea476ea2a101c49702c7ba1b4de6e8bacfd7aa08e751bb7c34d` |
| modified | `tests/api/test_campaign.py` | `403de08a0dab34da533352b2f7c4d33a324bb7503a7264a0bdf2ab944c8778ef` | `7ad266ad8048432079940d542947ed53e9f39bb9e22f159f3cf2228cdd208a70` |
| modified | `ui/app/lib/models.ts` | `a396a2ff2cd77956703bfe8b1f0a891b006fd685950f3df16bbfd3d328f88baa` | `be9c09ea870a4bcb00320b54bdc2a2b4dad46a8dc92490b38e28e28d2d3c3622` |
| modified | `ui/app/components/CampaignLab.tsx` | `b3d4a38d965fc0dfe6714b885e1699d0295b341354699d4476a84805eb315b58` | `9a7021880408b8685b7d5dcec47255bfdd80d6b291ca8a716becb8b5fdc0321e` |
| modified | `ui/app/globals.css` | `d98f94235a11cf58090e1ee667f4da1945e2da712d62058d8dcf0b954ab39566` | `291a76fb4191036cec85492f0a2b7f00969388c1da1f335ad95b2de1fda9f5ef` |
| modified | `ui/tests/campaign-lab.test.tsx` | `674963897a21871454ff1c8d333c81f20f694c5cc31d83c23626be07958671cb` | `82e0f1a12e7c76796936ce89b2ac73b9fe5d7438043fd1c712efd7835ce4dc29` |
| modified/generated | `ui/openapi.json` | `583189224036bf36f0ef6240abc071800ddb659347109979f0aca86d897b88b0` | `133cddf92760d378544c249d790a215acea75b5d72b6e831153e28802109fda2` |
| modified/generated | `ui/app/lib/api.generated.ts` | `9d8f2209e00e88129aed8010aa843ac78058d8b94d896739de1eaedca3ba8427` | `b290012068ba02d70c9dacb7cf22ac90112471b2fe59495c7481c326cd72a576` |
| modified/check artifact | `ui/tsconfig.tsbuildinfo` | `37d4d9d785408ab287d61f0269a1c8b0b1cf769de48eea60321c34d33b5d8a52` | `6807b6ea7d8a39fcd653be83ab417f46ce81a49a3c8ae7c0b98058a17ca28aa6` |
| modified symlink | `ui/.crazyswarm-builds/current` | target `release-d72142f168674e929fdf6fe26bcaf497` | target `release-wp52-56-fix1-20260812` |

The corrected immutable release is a new exact 36-file plus one-symlink tree. Every
entry is listed below; hashes are file bytes, except `node_modules`, whose hash is over
the literal symlink target.

```text
d532abb65cf9ae20634b464d954cb4a08a0de9f3cd3cdf7f9c3ec8948826d947  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/.openai/hosting.json
4f83140d5f4293ab55bd1207327e995c83258f1e7d3145b1b5d7a3d17fdfe0a7  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/.assetsignore
6e5e6df517e4fe5df79016fc416eb969a93b04f82a800d619bdc9a6c446de24d  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/.vite/manifest.json
9e55124bccd40b43dbc6e002daa777fa8f32a230420152910784ca65501d9e0f  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/_headers
58a6b173d5ca1dec92166ea3c6cb1a84a4144556d10928ac14e8e6b40e4787bd  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-8ac0455e797f/geist-001175b1.woff2
f689f638f29fff460a2d5749edb5d5c38d7bef0389f32032d871f23fc6ebb008  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-8ac0455e797f/geist-52306abf.woff2
6129fc8571c3e0cb0a4c41f5160c974a843b055009dc4ad8858bd808e18a2d86  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-8ac0455e797f/geist-875ccdd4.woff2
9b6f5ff45b278c744b5f379a2c4ecbaf858a842b8eaf82ac8d21b699ca16c608  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-8ac0455e797f/geist-98bbbccb.woff2
b7a545bbb08256bd809f11cfe66d88da3e22d169ea4407737b1ef0ec1ed3d791  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-8ac0455e797f/geist-ff2310f5.woff2
5f3d6ad60f29d6cb708414ec6887163d63bf197377ef5417d2483ff31ace6c3b  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-mono-00e989178794/geist-mono-013b2f2f.woff2
d67e4a94ba498635f764ddca7d1ec4271f5642f032eb24b426764480f66f8497  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-mono-00e989178794/geist-mono-0638449e.woff2
745994b5cd950ec201b66526375f057d540847cccfc70f4f24f5f571d26d3923  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-mono-00e989178794/geist-mono-44745446.woff2
75b3bedbebc35f347c0ae3b416aa871941555357e7b0f83767eb5987875589ed  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-mono-00e989178794/geist-mono-44e03052.woff2
16e1d48b6dd29eb240aec5db36184eb182933c082cd43de7f35af686d58087d2  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-mono-00e989178794/geist-mono-971fb274.woff2
e27f657e38d52887baa3b6b2f812bef93dfdd356f0810e40edd4ee284cc7e9f6  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/_vinext_fonts/geist-mono-00e989178794/geist-mono-f6b33328.woff2
a9b4ce28eb1fd24f44bd6afc700324f83feec30c0419725ce29a8c61bfa8996a  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/framework-bym5aI3S.js
4f18a02c900a228fa67778c794e738eb981670c8fca147d09dc49164dca95f55  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/index-Cw_Udxc3.css
07e844daf18d7219bc5d8b8873d5e98295e1067e867e96ca274c66a7e77dc68e  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/index-Dhn2lPQ4.js
580ad8c58061a4dde99bde0a56905e382f0568516ee2f5b84dbfb52085709021  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/rolldown-runtime-hePW80VL.js
ff8fb52eaa5677a8738db46d0ae960c83d120f58630ee83b6bc47bd4ff3e102d  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/router-D70qgaEF.js
c0698d40e7d2d7c135445eef8e58b2fad7d71f60455fd9427e00017384fbbfc0  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/client/assets/worker-entry-C-jYrjlj.js
cffe61eca42a443904ac9b7ce0f0d4fdd1c9b617bcae91c0c23f0733d4b156ee  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/.vite/manifest.json
fe36dd427bffa681db249ab7044313bfb4e2c71784c9a48b033927e01dabdc52  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/__vite_rsc_assets_manifest.js
4f18a02c900a228fa67778c794e738eb981670c8fca147d09dc49164dca95f55  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/assets/index-Cw_Udxc3.css
44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/image-config.json
45a7df7459de90ac443cfdfc7de2125bd103f01cb99102650cb55de5b2db9cc0  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/index.js
fe36dd427bffa681db249ab7044313bfb4e2c71784c9a48b033927e01dabdc52  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/ssr/__vite_rsc_assets_manifest.js
fb85ad1827e4ef3b5d26389573873964edce23e5744fcd7cab9f75d9ddd73777  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/ssr/assets/react-DL2WKC-E.js
c30fcad29b61cb26441246da1157592862dd6b7b1b3f5275903ee7fd9fed433a  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/ssr/assets/router-BZYWNBEh.js
3bda867166784fc501fb9995b1dc66c7f64d5db064a79353833cb2b7a519a3ff  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/ssr/assets/worker-entry-DR8JicYw.js
3ee0459819763fd0b639ed7a0bef9771b93509517552ab5765989aac877877db  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/ssr/index.js
26d6e288117d824e13a99c2d7349fafe34db46d0e9b72e33c0c774d06e6f509b  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/ssr/vinext-server.json
37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/vinext-externals.json
26d6e288117d824e13a99c2d7349fafe34db46d0e9b72e33c0c774d06e6f509b  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/vinext-server.json
2c1a2778719661f8f57c291f6f7794ab02a568b2dd85202734442f393d524b47  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/dist/server/wrangler.json
211bd21bf53c0640755efd9af1953a775681a3f71271c05e4700debf17fb38a8  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/package.json
8c91d02be0077c82c78559d981a0b731a316fbe96fb2efae44e54ebee883eada  ui/.crazyswarm-builds/release-wp52-56-fix1-20260812/node_modules -> /Users/lievenmuller/Projects/CrazySwarm/ui/node_modules
```

#### Initial-review finding dispositions and author checks

1. Steering resolution: fixed with one validated compiler, planner/trajectory
   consumption, independent sampled assertions, safe infeasible-profile rejection, and
   radius/limit tamper tests.
2. Child/backend/rename: fixed with explicit compatibility and backend gates; removed
   authority and unsupported backend reject, renamed compatible altitude retains
   profiles, and a valid object-bearing child still plans.
3. Admission/collapse: fixed by explicit per-value records, one-axis validation, the
   corrected objective/timing experiments, and compiled proof for every hidden row.
4. Unsupported capabilities: route fidelity and energy-aware retiming downgraded.
5. Qualification boundary: direct work retagged integration/no-runtime; four anchors
   additionally enter normal `CampaignService.preview_active`, still no-runtime.
6. UI evidence: the stale observation is invalidated; source and exact rebuilt release
   hashes are retained and the corrected live visual recheck remains explicitly pending.
7. Documentation: the single canonical table, packet-specific limits, claim matrix,
   qualification artifact, and this manifest now agree. The P2 documentation section
   and exact published release tree are included.

- Final Python packet suite, now including dynamic child-boundary regressions:
  `72 passed, 1 warning in 211.36s`. The warning is the existing Starlette TestClient
  deprecation notice. The focused dynamic/execution suite passed `11` tests in
  `145.13s`; `test_submissions.py` passed `30` tests.
- Ruff format/check passed over 13 implementation-owned Python source/script/test
  files. Mypy passed over 10 implementation-owned production/script files.
- Deterministic qualification passed: 54 cases (`20/18/16`), 111 proposals, 24
  collapse proofs, 28 executable planning alternatives, four integration anchors,
  four normal no-runtime production previews, one precise safe corner rejection, and
  zero planning/collapse failures. Canonical report payload SHA-256 is
  `5a3dde04fa02018b6d307d999c81190e981c7dec5aa7431fb747531ea45d0c46`;
  the JSON file SHA-256 is
  `04802b58725c93186890accd6d9f01005bd27bace59dcf2e3434d3e0af0de3af`.
- OpenAPI export and `openapi-typescript` regeneration passed. ESLint and TypeScript
  `--noEmit` passed. Vitest passed 8 files/119 tests (with the retained JSDOM canvas
  notices). Vinext production build passed with only its large-chunk advisory. The
  final built CSS equals the published CSS at
  `4f18a02c900a228fa67778c794e738eb981670c8fca147d09dc49164dca95f55`.
- The UI inspection artifact is intentionally `passed=false` with
  `visual_recheck_required=true`. That pending evidence keeps WP-56 open and is not
  hidden by the otherwise passing deterministic qualification report.

<!-- WP52-56-IMPLEMENTATION-PAYLOAD-END -->

### WP-52 through WP-56 implementation-review handoff

- Accepted design SHA-256:
  `69610ffc436817b2c610be998423fd87afe589b2406e594e04744ffcfc2604d2`.
- Initial implementation payload SHA-256 (inclusive of delimiter lines):
  `c628a248ad74f518d074ce35684e40301433bca8ebcdc91454f43d1b44d3dc8b`.
- Initial reviewer: `/root/wp52_56_impl_review`, a different fresh
  `work_packet_verifier` from the design reviewer.
- Initial verdict: `BLOCKED_WITH_FINDINGS`, with no P0 and seven P1 findings covering
  unvalidated/unconsumed steering resolution; permissive child/backend rebinding;
  self-attested admission/collapse gates; two unsupported advertised capabilities;
  overstated Fast-Sim qualification; a stale-build UI PASS artifact; and contradictory
  packet/claim status. One P2 requested exact manifest coverage of this documentation
  section.
- Sole consolidated author correction: completed in the exact delimited payload above.
- Corrected implementation payload SHA-256 (inclusive of delimiter lines):
  `7a3f4e584c5b279ff587a86a94da432c8f76ab3691785c3330b2d33453dbe9b9`.
- Sole focused recheck: same reviewer `/root/wp52_56_impl_review` on 2026-08-12.
  Verdict: `BLOCKED_WITH_FINDINGS`, with no P0, five residual P1 findings, and no P2.
  The P1 findings are point-count-dependent corner resolution; a budget-exhaustion
  result mislabeled as a proven safe infeasibility; generic/self-referential
  admission-collapse evidence; unimplemented route-fidelity, energy-retiming, and
  WP-53–56 packet exits; and the still-open rendered UI gate because the independent
  browser became unavailable.
- Independently verified corrections: both payload hashes; all 24 scoped postimages;
  the current-release pointer and all 37 immutable-release entries; both qualification
  hashes; the 30-test focused submission suite; strict child/backend/removed-authority
  behavior; corrected no-runtime claim tags; and the exact documentation manifest.
- Mechanical closeout delta after verdict: only the five canonical/independent status
  fields above and this verification record changed. The accepted design and reviewed
  corrected implementation payloads remain byte-identical. No third automatic pass is
  permitted; the batch remains active and blocked/unverified.

<!-- WP52-56-R2-DESIGN-PAYLOAD-BEGIN -->

### WP-52 through WP-56 remediation iteration R2

#### Frozen originating operator request and authority

> Ok then continue with this work packet iteration

This is a new explicitly authorized packet iteration, not a third pass of the prior
implementation review. It preserves the original selective-submission request and
accepted design payload
`69610ffc436817b2c610be998423fd87afe589b2406e594e04744ffcfc2604d2`,
the reviewed corrected implementation payload
`7a3f4e584c5b279ff587a86a94da432c8f76ab3691785c3330b2d33453dbe9b9`,
and every independently verified correction. It must close, rather than relabel, the
five P1 gaps recorded by `/root/wp52_56_impl_review` on 2026-08-12.

#### R2 goals and non-negotiable outcomes

1. Make corner steering depend on normalized path geometry, semantic corners/stops,
   protected free space, and dynamics—not raw authored point count.
2. Distinguish a proven infeasible or independently rejected choice from an incomplete
   or budget-exhausted search. No timeout may be presented as a safe-infeasibility proof.
3. Losslessly retain the row-specific causal question and oracle from the accepted
   20/18/16 matrix, then measure every visible/collapsed alternative with that oracle
   rather than generic plan hashes alone.
4. Implement and qualify `core.route_fidelity` and
   `core.energy_aware_retiming`, including production bindings, generalization, adverse
   cases, and independent observed behavior.
5. Complete the WP-53, WP-54, and WP-55 production/runtime/fleet exits for every
   accepted matrix addition. A missing implementation may remain visible while work is
   in progress but cannot satisfy the R2 exit.
6. Complete WP-56 with truthful per-row lifecycle/claim metadata and retained rendered
   evidence from the exact immutable production release.

#### Durable dependencies and invariants

- `REQ-WFL-013` through `REQ-WFL-027`, the original WP-52–56 payload, `REQ-UI-001`,
  and the root `design.md` decisions remain authoritative. R2 does not revise frozen
  cases, world/event truth, safety limits, role identities, or prior evidence.
- Previously verified strict exact-case/child/backend/removed-authority handling,
  package tamper rejection, explicit one-axis checks, no-runtime claim correction, and
  exact release/manifest accounting must not regress.
- A submission may change only its declared axis. Derived geometry, retiming, runtime
  policy, and evidence are outputs and remain bound into component/package hashes.
- All execution is Fast Sim only. This iteration makes no live-Isaac, digital-twin,
  hardware, or physical-flight claim. `OBSERVED_REALTIME` applies only to explicitly
  paced Fast-Sim runs whose source and wall clocks are both retained.
- A report generated by the implementation is never the sole oracle. Tests and
  qualification independently resample raw accepted routes, trajectories, runtime
  telemetry, event traces, fleet epochs, and terminal observations.
- All packet lifecycle claims remain per-packet. A passing subset cannot mark the batch
  `QUALIFIED` or `COMPLETE`.

#### R2 work slices

##### A. Geometry-normalized corner compiler and exact rejection semantics

- Introduce one deterministic normalized-polyline representation used by capability
  resolution and the trajectory compiler. Remove only zero-length points and interior
  collinear `FLY_THROUGH` samples under the exact rules below. Preserve endpoints,
  non-collinear turns, `CAPTURE`, `CAPTURE_AND_HOLD`, and `REVERSAL` nodes. Bind the
  normalized geometry hash and normalization-rule version into `CapabilityResolution`.
- Derive the adjacent cap from arc length to the previous/next semantic turn, stop, or
  endpoint. Inserting or deleting forward-progress collinear fly-through samples on an
  unchanged segment must not change certified speed, lookahead distance, blend radius,
  retiming factor, limiting constraints, or densely sampled accepted geometry beyond
  the exact tolerances below. Reordering semantic regions is never resampling:
  `A → 0.8 → 0.2 → B` retains its backtracking nodes and changes identity/result or
  rejects. A real corner, stop, shortened segment, or reduced clearance must change the
  result or reject.
- Retain raw required-region capture separately: normalization may not erase a required
  knot or let the generated trajectory miss it. Planner, package validator, trajectory,
  preview, runtime authority, evidence, and download must consume one recomputed
  resolution.
- Add an explicit capability-feasibility disposition and evidence record. The
  `0.20 s` rounded-square choice counts as a safe rejection only if a complete bounded
  compiler/trajectory analysis plus an independent dense dynamics/deadline oracle proves
  the exact violated constraint. `BUDGET_EXHAUSTED`, incomplete search, or a generic
  `BLOCKED` status is never proof and must be reported separately.

Required sensitivity cases are the canonical rounded square; a renamed compatible
child with 19 inserted collinear fly-through regions; a genuinely shortened adjacent
edge; a reduced protected-clearance child; a required stop inserted on the edge; a
non-collinear perturbation; tampered normalized-geometry/radius/limit identities; and an
artificially tiny planning budget that remains explicitly `BUDGET_EXHAUSTED`.

Normalization rule `semantic-polyline-v1` is frozen as follows:

- consecutive positions at Euclidean distance `<= 1e-9 m` collapse only when the later
  node is `FLY_THROUGH` and carries no distinct required-region identity;
- an interior `FLY_THROUGH` point `b` between retained neighbors `a,c` collapses only
  when its point-to-closed-segment distance is `<= 1e-9 m`,
  `(b-a)·(c-b) >= -1e-12 m²`, and projected progress lies in `[0,1]` without reversing;
- all semantic node IDs/order remain in the raw capture contract even when a geometric
  sample collapses. Any non-forward order, turn angle greater than `1e-9 rad`, semantic
  stop/hold/reversal, or off-segment displacement greater than `1e-9 m` is retained;
- normalized scalar resolution values must match under resampling to absolute
  `1e-9` in their declared SI units; normalized route Hausdorff distance must be
  `<= 1e-9 m`; independently sampled commanded positions, velocities, accelerations,
  and jerks at `0.01 s` must match to `1e-6 m`, `1e-6 m/s`, `1e-5 m/s²`, and
  `1e-4 m/s³` respectively. Larger deltas fail the invariance gate.

##### B. Row-specific admission source and independent behavior/collapse oracle

- Add a hand-authored, versioned admission source for exactly 54 rows. Each row retains
  the full accepted matrix comparison/oracle text plus structured oracle metric IDs,
  fixed inputs, reused evidence, new coupling/runtime gate, safety/authority bounds,
  operator comparison, and learning value. Each proposal adds its exact axis/value and
  no generator-created generic sentence may substitute for missing row data.
- Generation fails on an omitted case, missing field, unknown metric, duplicate
  experiment value, third-cell mismatch, or a changed field outside the experiment
  axis. Known exact records—including boundary clearance versus reference deviation,
  rounded-square transition/edge/jerk/closure, head-on both-role participation, and 3D
  unaffected-role/fleet-epoch evidence—receive literal regression assertions.
- Add an independent behavior measurement model computed from accepted route geometry,
  dense trajectory samples, feasibility certificates, schedules, event/fleet traces,
  energy/terminal observations, and the row's declared oracle metrics. The measurement
  implementation must not call semantic-fingerprint or candidate-hash helpers.
- A collapsed row retains both semantic fingerprints, both accepted artifacts, both
  independent metric vectors/tolerances, and a reason each declared metric is
  equivalent. A visible peer is distinct only when at least one declared metric differs
  outside its frozen tolerance. Hash equality alone is insufficient for either claim.

The independent measurement contract is frozen before implementation:

- Commanded trajectories are sampled at `0.01 s`, including exact knots and phase/event
  boundaries. Runtime samples use raw telemetry rows from first nonzero thrust through
  motor cut; source-time event metrics use the retained event clock, never receipt order.
- `SP_CAPTURE` is maximum distance outside each required region (`0` inside);
  `SP_REFERENCE` is maximum shortest distance to the ordered reference polyline;
  `SP_RADIAL`, `SP_CLOSURE`, `SP_CORNER_CUT`, `SP_SPLICE_POSITION`, `SP_FORMATION`,
  `SP_SPACING`, `SP_OFFSET`, and `SP_UNAFFECTED_PATH` are their named maximum Euclidean
  errors; `SP_CLEARANCE` and `SP_BOUNDARY` are the minimum independently continuous-
  geometry-certified margins. No endpoint-only substitute is allowed.
- `TM_DURATION`, `TM_SETTLE`, `TM_TRANSITION_START`, `TM_DWELL`, `TM_RELEASE`,
  `TM_OVERLAP`, `TM_WAIT`, `TM_CUTOVER`, `TM_COVERAGE_GAP`, `TM_FINISH_SKEW`,
  `TM_PHASE_ERROR`, `TM_STARVATION`, `TM_HOLD`, and `TM_HORIZON` use exact trajectory,
  schedule, contact, event, or epoch timestamps in seconds. `TM_TRANSITION_START` is
  arc-length distance from the semantic corner despite its historical name and is in m.
- `DY_SPEED_MIN`, `DY_SPEED_TRACKING`, `DY_VERTICAL_TRACKING`, `DY_ACCELERATION`,
  `DY_JERK`, and `DY_CURVATURE` are respectively the minimum/steady-window speed, RMS
  commanded-versus-observed speed or vertical-position error, maximum acceleration,
  maximum jerk, and maximum curvature over the declared route phase. Windows exclude
  takeoff/landing and are bounded by the exact route-start/route-finish events.
- `EN_ENERGY_WH` is trapezoidal `Σ((V_i I_i + V_{i+1} I_{i+1})/2) Δt / 3600` from raw
  `battery_voltage_v` and nonnegative `battery_current_a`; `EN_BATTERY_PP` is initial
  minus terminal state of charge in percentage points; `EN_RESERVE_PP` is terminal
  reserve; `EN_SPREAD_PP` is max-minus-min fleet reserve; `EN_ACTUATOR_HEADROOM_N` is
  the minimum retained per-motor thrust headroom. Missing raw signals fail the metric.
- `DS_*` metrics are exact discrete values/sets/sequences: topology/lobe order,
  reversal/unintended-stop/direction-change/priority-inversion/partial-commit/stale-
  command counts, maneuver/fallback/disposition, generation, route/package identity,
  affected/prepared/acknowledged role sets, queue/role/assignment order, schedule/epoch,
  lease generation, command ownership, terminal states, and all-role completion.

For no-runtime artifact comparisons, spatial equality is `<=1e-4 m`, time equality is
`<=1e-4 s` (`TM_TRANSITION_START <=1e-4 m`), speed equality is `<=1e-4 m/s`,
acceleration equality is `<=1e-3 m/s²`, jerk equality is `<=1e-2 m/s³`, curvature
equality is `<=1e-3 1/m`, and predicted energy equality is `<=1e-5 Wh`; discrete
metrics require exact equality. For Fast-Sim repeat medians the equality limits are
`0.005 m`, `0.02 s`, `0.005 m/s`, `0.01 m/s²`, `0.05 m/s³`, `0.01 1/m`, and
`0.0005 Wh`. A distinct continuous result requires the expected direction plus at
least `0.01 m`, `0.10 s`, `0.02 m/s`, `0.05 m/s²`, `0.10 m/s³`, `0.05 1/m`, or
`max(0.0005 Wh, 2% of baseline Wh)` respectively. A discrete difference must be exact.
A delta between the equality and distinct thresholds is inconclusive: it can neither
collapse nor qualify a peer. Every non-energy runtime comparison uses three accelerated
repeats per peer and the median, with every repeat passing hard safety/terminal gates.

Exact row/proposal metric coverage is below. Every proposal in a row inherits the whole
listed set; an axis-specific record may add but never remove a metric. `BASELINE_ONLY`
rows use their listed negative/fallback metrics.

```text
1d.takeoff_hover_land.canonical_nominal: SP_CAPTURE,TM_SETTLE,TM_DURATION,DY_VERTICAL_TRACKING,DY_ACCELERATION,DY_JERK,EN_ENERGY_WH,EN_ACTUATOR_HEADROOM_N,DS_TERMINAL_STATE
1d.point_to_point_relocation.canonical_nominal: TM_DURATION,EN_ENERGY_WH,EN_RESERVE_PP,DY_ACCELERATION,DY_JERK,SP_CAPTURE,DS_TERMINAL_STATE
1d.move_return.canonical_nominal: DS_REVERSAL_COUNT,DY_SPEED_MIN,SP_REFERENCE,DY_JERK,TM_DURATION,SP_CAPTURE
1d.altitude_transition.canonical_nominal: DY_SPEED_TRACKING,DY_ACCELERATION,DY_JERK,EN_ENERGY_WH,EN_ACTUATOR_HEADROOM_N,SP_CAPTURE,DS_TERMINAL_STATE
1d.altitude_transition.wide: DY_VERTICAL_TRACKING,DY_SPEED_TRACKING,DY_ACCELERATION,DY_JERK,EN_ENERGY_WH,EN_ACTUATOR_HEADROOM_N,SP_CAPTURE
1d.continuous_waypoint_sequence.canonical_nominal: SP_CAPTURE,TM_TRANSITION_START,DS_UNINTENDED_STOP_COUNT,SP_REFERENCE,DY_CURVATURE,DY_JERK,TM_DURATION
1d.curved_route.canonical_nominal: SP_RADIAL,SP_REFERENCE,SP_CAPTURE,DY_CURVATURE,DY_JERK,TM_DURATION
1d.planar_shape_loop.circle: SP_RADIAL,SP_CLOSURE,DY_SPEED_TRACKING,DY_CURVATURE,DS_TOPOLOGY,EN_ENERGY_WH
1d.planar_shape_loop.rounded_square: TM_TRANSITION_START,SP_CAPTURE,SP_CORNER_CUT,SP_REFERENCE,DY_CURVATURE,DY_JERK,SP_CLOSURE
1d.planar_shape_loop.figure_eight: SP_CAPTURE,SP_REFERENCE,DY_CURVATURE,DY_JERK,DS_TOPOLOGY,DS_LOBE_ORDER
1d.static_multi_goal_sequence.canonical_nominal: SP_CAPTURE,TM_DWELL,TM_DURATION,DY_JERK,DS_UNINTENDED_STOP_COUNT
1d.boundary_constrained_route.canonical_nominal: SP_BOUNDARY,SP_REFERENCE,SP_CAPTURE
1d.moving_target.dynamic_nominal: DS_GENERATION,TM_CUTOVER,DS_STALE_COMMAND_COUNT,SP_SPLICE_POSITION,DY_JERK,SP_CAPTURE,DS_TERMINAL_STATE
1d.mid_route_goal_replacement.dynamic_nominal: DS_GENERATION,TM_CUTOVER,DS_STALE_COMMAND_COUNT,SP_SPLICE_POSITION,DY_JERK,SP_CAPTURE,DS_TERMINAL_STATE
1d.duplicate_stale_goal_update.dynamic_nominal: DS_DISPOSITION,DS_GENERATION,DS_ROUTE_IDENTITY,DS_STALE_COMMAND_COUNT,DS_PARTIAL_COMMIT_COUNT
1d.planning_budget_expiry.dynamic_nominal: DS_FALLBACK,TM_HOLD,SP_CAPTURE,DS_PARTIAL_COMMIT_COUNT,DS_DISPOSITION
1d.blocked_replan.dynamic_nominal: DS_FALLBACK,TM_HORIZON,SP_CAPTURE,SP_CLEARANCE,DS_TERMINAL_STATE
1d.operator_approval_goal_replacement.dynamic_nominal: DS_DISPOSITION,DS_GENERATION,DS_COMMAND_OWNERSHIP,DS_PARTIAL_COMMIT_COUNT
1d.abort_and_land_goal_fallback.dynamic_nominal: DS_FALLBACK,DS_TERMINAL_STATE,SP_CAPTURE,DS_COMMAND_OWNERSHIP
1d.failure_recovery.dynamic_nominal: DS_FALLBACK,DS_COMMAND_OWNERSHIP,DS_TERMINAL_STATE,SP_CAPTURE
2d.head_on_conflict.canonical_nominal: TM_RELEASE,TM_OVERLAP,DS_MANEUVER,SP_REFERENCE,SP_CLEARANCE,DS_AFFECTED_ROLES,DS_ALL_ROLE_COMPLETION
2d.perpendicular_crossing.nominal_equal_priority: TM_RELEASE,TM_OVERLAP,DS_MANEUVER,TM_WAIT,SP_REFERENCE,SP_CLEARANCE
2d.merge.canonical_nominal: TM_RELEASE,TM_WAIT,TM_OVERLAP,DS_MANEUVER,SP_CLEARANCE,DS_ROLE_ORDER
2d.overtake.canonical_nominal: TM_DURATION,TM_OVERLAP,DS_MANEUVER,SP_REFERENCE,SP_CLEARANCE,EN_ENERGY_WH,DS_ROLE_ORDER
2d.bottleneck.canonical_nominal: DS_OCCUPANCY_INTERVALS,TM_WAIT,TM_OVERLAP,SP_CLEARANCE,DS_MANEUVER,DS_ALL_ROLE_COMPLETION
2d.parallel_routes.canonical_nominal: TM_PHASE_ERROR,EN_SPREAD_PP,TM_FINISH_SKEW,SP_CLEARANCE
2d.leader_follower.canonical_nominal: DS_COMMAND_OWNERSHIP,SP_OFFSET,DY_JERK,EN_ENERGY_WH,SP_CAPTURE,DS_TERMINAL_STATE
2d.formation_spacing.canonical_nominal: SP_SPACING,DY_JERK,DS_ALL_ROLE_COMPLETION,SP_CLEARANCE
2d.role_allocation.canonical_nominal: DS_ASSIGNMENT,DS_COMMAND_OWNERSHIP,EN_RESERVE_PP,DS_ALL_ROLE_COMPLETION
2d.duplicate_assignment_rejection.dynamic_nominal: DS_DISPOSITION,DS_ASSIGNMENT,DS_COMMAND_OWNERSHIP,DS_PARTIAL_COMMIT_COUNT
2d.unequal_priority.canonical_nominal: DS_ROLE_ORDER,TM_WAIT,DS_PRIORITY_INVERSION_COUNT,TM_DURATION
2d.constrained_border_height.canonical_nominal: TM_RELEASE,DS_MANEUVER,SP_CLEARANCE,SP_REFERENCE
2d.no_hover_crossing.canonical_nominal: TM_RELEASE,DS_MANEUVER,TM_HOLD,SP_CLEARANCE
2d.crossing_goal_change.dynamic_nominal: DS_AFFECTED_ROLES,DS_FLEET_EPOCH,TM_CUTOVER,SP_CLEARANCE,TM_WAIT,DS_ALL_ROLE_COMPLETION
2d.simultaneous_conflicting_updates.dynamic_nominal: DS_GENERATION,DS_DISPOSITION,DS_FLEET_EPOCH,DS_ROUTE_IDENTITY,DS_PARTIAL_COMMIT_COUNT
2d.partial_replacement_failure.dynamic_nominal: DS_PREPARED_ROLES,DS_ACKNOWLEDGED_ROLES,DS_PARTIAL_COMMIT_COUNT,DS_FLEET_EPOCH,DS_DISPOSITION
2d.leader_loss.dynamic_nominal: DS_LEASE_GENERATION,DS_COMMAND_OWNERSHIP,SP_SPACING,DS_TERMINAL_STATE,DS_ALL_ROLE_COMPLETION
2d.coordination_failure.dynamic_nominal: DS_FLEET_EPOCH,DS_FALLBACK,DS_PARTIAL_COMMIT_COUNT,DS_TERMINAL_STATE,DS_ALL_ROLE_COMPLETION
3d.single_pair_conflict.canonical_nominal: DS_AFFECTED_ROLES,SP_UNAFFECTED_PATH,TM_WAIT,TM_OVERLAP,DS_MANEUVER,SP_CLEARANCE,DS_ALL_ROLE_COMPLETION
3d.simultaneous_center_conflict.joint_schedule_v2: DS_SCHEDULE,SP_CLEARANCE,TM_OVERLAP,DS_ROLE_ORDER,TM_WAIT,DS_FLEET_EPOCH,DS_ALL_ROLE_COMPLETION
3d.merge.canonical_nominal: DS_ROLE_ORDER,TM_WAIT,DS_MANEUVER,TM_OVERLAP,SP_CLEARANCE,DS_ALL_ROLE_COMPLETION
3d.bottleneck.canonical_nominal: DS_QUEUE_ORDER,DS_OCCUPANCY_INTERVALS,DS_DIRECTION_CHANGE_COUNT,TM_STARVATION,DS_ALL_ROLE_COMPLETION
three_drone_multi_conflict: DS_ROUTE_IDENTITY,DS_SCHEDULE,DS_ALL_ROLE_COMPLETION
3d.formation_shape_transform.canonical_nominal: SP_FORMATION,DY_JERK,EN_SPREAD_PP,TM_OVERLAP,SP_CLEARANCE,DS_ALL_ROLE_COMPLETION
3d.role_allocation.canonical_nominal: DS_ASSIGNMENT,DS_COMMAND_OWNERSHIP,EN_RESERVE_PP,EN_SPREAD_PP,DS_ALL_ROLE_COMPLETION
3d.duplicate_assignment_rejection.dynamic_nominal: DS_DISPOSITION,DS_ASSIGNMENT,DS_COMMAND_OWNERSHIP,DS_PARTIAL_COMMIT_COUNT
3d.persistent_coverage_reserve_handover.dynamic_nominal: TM_COVERAGE_GAP,DS_LEASE_GENERATION,TM_OVERLAP,DS_TERMINAL_STATE,EN_RESERVE_PP,SP_UNAFFECTED_PATH
3d.unequal_priorities.canonical_nominal: DS_ROLE_ORDER,DS_PRIORITY_INVERSION_COUNT,TM_WAIT,TM_STARVATION,TM_DURATION,DS_ALL_ROLE_COMPLETION
3d.constrained_volume.canonical_nominal: TM_DURATION,DS_ROLE_ORDER,SP_CLEARANCE,DS_MANEUVER,DS_ALL_ROLE_COMPLETION
3d.alternative_layers_detours.canonical_nominal: DS_MANEUVER,EN_ENERGY_WH,SP_CLEARANCE,SP_REFERENCE,DS_AFFECTED_ROLES,DS_ALL_ROLE_COMPLETION
3d.cascading_replan.dynamic_nominal: DS_AFFECTED_ROLES,TM_DURATION,SP_CLEARANCE,DS_GENERATION,DS_FLEET_EPOCH,DS_STALE_COMMAND_COUNT,DS_ALL_ROLE_COMPLETION
3d.acknowledgement_loss.dynamic_nominal: DS_ACKNOWLEDGED_ROLES,DS_PARTIAL_COMMIT_COUNT,DS_FALLBACK,DS_FLEET_EPOCH,DS_TERMINAL_STATE,DS_ALL_ROLE_COMPLETION
3d.fleet_abort_fallback.dynamic_nominal: DS_FALLBACK,DS_TERMINAL_STATE,DS_COMMAND_OWNERSHIP,DS_ALL_ROLE_COMPLETION
3d.leader_follower_recovery.dynamic_nominal: DS_LEASE_GENERATION,SP_FORMATION,SP_SPACING,DS_AFFECTED_ROLES,DS_TERMINAL_STATE,DS_ALL_ROLE_COMPLETION
```

##### C. Complete reusable capability bindings

- Implement `core.route_fidelity` as a planning-owned request/binding, separate from an
  execution-profile request. The sole authored axis is
  `PATH_ADHERENCE_MODE`: `GOAL_SEQUENCE_ONLY` versus `EXACT_ROUTE` with an exact
  `1e-6 m` centerline bound. Objective terms/order, maneuver authority, coordination,
  search, execution profile, case-required regions/stops, backend, seed, and safety
  remain byte-identical. A stop or in-tube transition required by exact-route geometry
  is a derived output, not a second authored field. It may not silently cut the line.
- Qualify route fidelity as a separate `C core.route_fidelity` request on the baseline
  package for `1d.curved_route.canonical_nominal`, then on a renamed compatible child.
  It is not injected into either peer of `waypoint.centerline_first` versus
  `waypoint.smoothness_first`, whose sole axis remains objective order, or either
  rounded-square peer, whose sole axis remains `lookahead_time_s`. Those accepted pairs
  keep identical adherence/objective fields respectively. An incompatible child,
  removed path authority, tightened tube, or unsupported backend rejects before
  provisioning.
- Implement `core.energy_aware_retiming` as a bounded compiler-selected time law rather
  than a caller-selected duration label. Its request has no scalar parameter. The exact
  candidate duration factors are `(0.80, 0.90, 1.00, 1.15, 1.30)` applied to the same
  accepted geometry; all other profile fields stay at baseline. Candidates failing any
  case deadline, speed, acceleration, jerk, terminal, or energy-reserve constraint are
  rejected before ranking.
- Predicted energy uses the exact `crazyflie-6dof` model version `2.0.0` and its hashed
  `BATTERY_COUPLED_V2` powertrain configuration. Sample each candidate at `0.01 s`,
  derive required collective thrust from model mass, gravity and commanded acceleration,
  distribute it equally across four motors with zero yaw demand, solve the versioned
  battery load line, and trapezoidally integrate terminal voltage × total current into
  Wh. Bind model/config hash, all five candidate dispositions/Wh values, selected factor,
  and limiting constraint. Rank lowest predicted Wh; ties within `1e-5 Wh` use lower
  peak current, then shorter duration, then smaller factor.
- Qualify energy-aware retiming on
  `1d.point_to_point_relocation.canonical_nominal` and one renamed compatible child;
  exercise new two-role coupling on `2d.parallel_routes.canonical_nominal`. Raw Fast-Sim
  telemetry must show the selected time law changes command timing and improves measured
  battery/energy versus the exact baseline without violating dynamics, tracking,
  separation, or terminal gates. If no candidate improves measured energy, the
  capability fails qualification rather than changing the threshold after observation.

Energy qualification uses three isolated accelerated repeats for baseline and selected
factor at seed/config/model equality. Raw `EN_ENERGY_WH` is integrated over first nonzero
thrust through motor cut; `EN_BATTERY_PP` is a secondary reconciliation. The selected
median must improve Wh by at least `max(0.0005 Wh, 2% of baseline median Wh)`, every
selected repeat must use less Wh than its same-index baseline repeat by at least
`0.0002 Wh`, and command duration must differ by at least `0.10 s`. All repeats must
pass case dynamics/separation/terminal limits; tracking RMS may worsen by no more than
`0.01 m`, actuator headroom may not become negative, and terminal reserve may not fall.
Observed Wh and state-of-charge delta must agree in direction. Any missing signal,
inconclusive delta, failed repeat, or prediction choosing a factor whose observed median
is worse fails qualification. These gates are immutable for R2.

##### D. Production runtime completion for the 1D–3D submission matrix

- Every final `EXECUTABLE` catalog choice enters through normal
  `CampaignService.run_active`, provisions the exact resolved package, issues the
  intended Fast-Sim commands, retains raw telemetry/evaluation/analysis/event trace, and
  passes the row-specific independent oracle. Same-case peer comparisons use identical
  backend, seed, configuration, and frozen case hash.
- Every accepted non-baseline `P`, `E`, `C`, or `R` matrix addition must finish R2 in
  exactly one defensible state: independently distinct and runtime-qualified;
  independently equivalent and collapsed; or independently proved unsafe/infeasible
  with an exact constraint. `PLANNED_NOT_EXECUTABLE` solely because production code or
  evidence is missing is an R2 failure.
- Generalize the execution head beyond environment obstacles for the event kinds present
  in the 54 frozen cases: authenticated/stale/duplicate goal and peer updates, bounded
  budget/infeasibility, vehicle/telemetry loss, battery reserve handover, assignment
  conflict, acknowledgement loss, and coordinated abort. Event policy remains
  submission-bound and cannot change immutable event truth.
- WP-53 dynamic pairs must execute through source-time update/cutover and prove future-
  only command replacement, zero stale authority, exact accepted generation, terminal
  capture, and the selected latency/smoothness/fallback difference. Duplicate/stale,
  approval-required, blocked, and abort-only rows retain zero unauthorized command.
- WP-54 results reconcile both roles. Static alternatives prove participation/timing or
  maneuver differences; dynamic alternatives prove one atomic fleet epoch, complete
  affected-role accounting, and zero partial commit. Role reorder, no-hover, ceiling,
  capacity, late update, and partial acknowledgement are independent counterexamples.
- WP-55 results reconcile all three roles and every pair edge. Selective alternatives
  prove unaffected-role non-interference; global alternatives prove one schedule/epoch,
  complete fleet feasibility, declared fairness/priority, and terminal/ownership state.
  Reordered roles, removed layer/detour, insufficient three-envelope capacity, late
  cascade, missing prepare/ack, and tampered fleet package must fail or choose the exact
  fallback.
- Retain a versioned runtime qualification artifact with case/submission/package/run IDs,
  raw artifact hashes, claim boundary, clock mode, independent measurement vector,
  peer/baseline delta, counterexample result, and command/epoch/terminal reconciliation.
  Temporary qualification runs must not alter operator-owned review lifecycle state.

The accelerated matrix covers every executable choice. Minimum paced Fast-Sim realtime
anchors cover the rounded-square fidelity/smoothness pair, one accepted 2D source-time
fleet update, and one 3D atomic/fallback case. Realtime results must agree with the
accelerated semantic outcome. Each realtime peer/anchor runs once after its three
accelerated repeats. Source-versus-wall elapsed ratio must remain within `±5%` of the
configured realtime factor after excluding preflight, each all-role route-start skew
must be `<=0.10 s`, event/cutover timestamp reconciliation must be `<=0.02 s`, and the
realtime row-metric vector must stay within the runtime equality limits above of the
accelerated median unless that row's accepted axis is itself a clock metric. A missed
deadline, late/partial epoch, or larger semantic delta fails; no retry is used to replace
a completed failing realtime run.

##### E. Operator UI and exact rendered-release gate

- Preserve the existing case-first selector and detail-pane hierarchy. Add no new
  competing UI pattern. Show authoritative support/qualification boundary, row-specific
  question/oracle, baseline/peer delta, binding constraint, runtime evidence state, and
  unavailable reason with progressive disclosure and non-color cues.
- Test loading, empty, error, long-label, disabled, unsupported,
  `PLANNED_NOT_EXECUTABLE`, overflow, expanded/collapsed navigation, keyboard menu
  navigation, Escape, focus containment/restoration, reduced motion/transparency, and
  approximately 40–44 px targets.
- Build a new immutable release from the exact reviewed source. Publish `current` only
  after source/build hashes match. Serve that release against the real local API and
  retain screenshots plus a structured inspection artifact at `1440x900` and `820x900`.
  The inspection records overlap, clipping, unintended scrolling, one-column narrow
  reflow, long-label wrapping, link/action layout, focus, keyboard selection, disabled
  state, console warnings/errors, and exact release/source/built-asset identities.
- A build hash or source assertion cannot set UI `passed=true`. Missing browser/rendered
  evidence leaves WP-56 blocked.

#### Exact implementation and evidence sequence

1. Add failing sensitivity tests for collinear resampling and budget-exhaustion
   misclassification; add exact known-row admission assertions.
2. Implement slices A and B; run focused model/registry/planner/trajectory tests and
   deterministic registry qualification.
3. Add failing capability anchors, implement slice C, and run independent preview plus
   Fast-Sim anchor tests.
4. Implement slice D by event/coordination family, always running the smallest affected
   runtime test before the full matrix. Preserve failed candidates/runs and exact reasons.
5. Implement/verify slice E using `design.md`, UI unit/accessibility checks, generated
   API types, lint/typecheck/build, and the exact rendered-release inspection.
6. Run the complete affected Python/UI suites, deterministic artifact regeneration,
   accelerated matrix, and minimum realtime anchors; then freeze a new exact
   implementation manifest for a different fresh verifier.

No expected result, tolerance, status, or claim boundary may be weakened merely to make
the implementation pass. If a frozen expectation is impossible, stop and obtain an
explicit reviewed design revision.

#### Executable exit evidence and claim boundaries

| R2 claim | Required independent evidence | Boundary / environment / clock |
|---|---|---|
| Geometry-normalized steering | Collinear-resampling property plus shortened-edge, stop, non-collinear, clearance and tamper counterexamples; dense geometry/dynamics sampler | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` |
| Exact infeasibility | Complete compiler/search disposition and independent trajectory/dynamics/deadline oracle; timeout perturbation remains timeout | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` |
| Admission/collapse | Exact hand-authored row record plus independent per-metric artifact measurements for visible and hidden peers | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` |
| Route-fidelity and energy capabilities | Normal package/preview path, renamed child and incompatible boundary, raw Fast-Sim command/telemetry comparison | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` plus the declared rounded-square realtime anchor |
| WP-53/54/55 executable rows | Normal `run_active`, retained command/evidence/evaluator/analyzer chain, row oracle, peer delta, and packet-specific adverse case | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` |
| Clock/cutover/fleet anchors | Raw source/wall timing, all-role commands, one epoch, acknowledgement/fallback and terminal evidence | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |
| WP-56 rendered surface | Exact immutable release, real API, screenshots/structured observations, keyboard/focus/console evidence | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE` |

R2 passes only when all five packet-specific exit sets pass. Reviewer acceptance is
necessary but does not upgrade any row beyond its retained boundary. Live-Isaac,
digital-twin, hardware, and physical transfer remain outside scope.

#### Base identity and relevant preimages

- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Pre-draft `ACTIVE.md` SHA-256:
  `4fc762476ba5c0b8b09c426fe02826056d48d573e72508dedac448b308c9319f`.
  It is reproducibly reconstructed from the current ledger by removing from the R2
  begin marker through the line before `## Future mission-family application`, then
  changing the five R2 `DRAFT_UNVERIFIED` fields back to their prior
  `BLOCKED_WITH_FINDINGS` values. The exact read-only reconstruction is:
  `awk 'BEGIN{skip=0} /<!-- WP52-56-R2-DESIGN-PAYLOAD-BEGIN -->/{skip=1}
  /^## Future mission-family application/{skip=0} !skip{print}' ACTIVE.md | sed
  's/`DRAFT_UNVERIFIED`/`BLOCKED_WITH_FINDINGS`/g'`; its bytes hash to the value above.
- Root UI decision guide `design.md` SHA-256:
  `4aa78f82633f94dde9310157bc14341e906b24f03ee08f2f4d355f93319e24ca`.
- Detailed UI contract `docs/project/DESIGN.md` SHA-256:
  `27dfe90670911c535ba8a54a24d8e43003788933acc54e8ae9a26b37fdcf797f`.
- Frozen case-YAML tree-manifest SHA-256:
  `6ce5e32f43738d11783e56f04b43a04037a82eea9bc690ae641921abf0e14e4d`.
- Exact current release target: `release-wp52-56-fix1-20260812`; 36-file tree-manifest
  SHA-256 `2ee0ba1fe6aed9e9a06342a68d403bbccda212b75fcb2e2b51945c260688e8fc`;
  `node_modules` literal-target digest
  `7ad7cb1cc1019818337aa29f96cd694f86e3d5291bffd769fed376b271b1430e`;
  `current` literal-target digest
  `fb12711c71367c896f3584b9791077b8b9305dccdb7460deda7b0d7193383d02`.

```text
31c3b5067972298b9dbd4a4dc026ff3b48de96685b253a9b22d48293eb71fdf0  src/crazyswarm_app/campaign/models.py
1c4633c5958432789fb3f34b369f302ebfa43d2d39a001a8b13bff44eb6e912b  src/crazyswarm_app/campaign/submissions.py
e652ef5b33d8e9c3bb46eac343579ac21569acfce7b5b5de0981e2f451e1aad1  src/crazyswarm_app/campaign/planner.py
548c837110203e195d120eabed0dc1796d9b673f067569c37532bad15ccc5df2  src/crazyswarm_app/campaign/trajectory.py
916230c6ffe7ea2626c90d2eb2a6740b71aa89eb1227c51a13ab0deab67e41d6  src/crazyswarm_app/campaign/geometry.py
3874d7db504198ff67ea193f263e0b5bc119fc1af65616c3816664ebb0cacb37  src/crazyswarm_app/campaign/service.py
eff68869fcc5943adbc5d3b1e258f5304f213417121d9207f312b7d2bd5a3e38  src/crazyswarm_app/campaign/runtime_executor.py
a6510c17f13a0f6d8b82ef450c2442b3271b32046932d6c6a7de245dba43e5bc  src/crazyswarm_app/campaign/execution_head.py
8a80ff02979979affe6dc1cee9d4d0550430473d36de0a3fb5d1abffe0f054e9  src/crazyswarm_app/campaign/replanning.py
f94e6ad3da7a1024e316615c1ce565f19a67223f1fe3517e480dd397513b7f46  src/crazyswarm_app/observability/evaluation.py
b62c7c942dc37d9f9573dba1f650383961b934c2a7b57dc5237f9102cf168b12  src/crazyswarm_app/campaign/analyzer.py
071fc7283066960c23996425c2167d888e3443f675781b7ed4e9c245fd781878  src/crazyswarm_app/api/app.py
c755aed6f21c91e4146b24dd224e801d9599d27db0d9e49976b7111dbc9f7449  scripts/generate_submission_registry.py
658b1de5fb9ac364aea01d6dab6a03595c00a427ef1294f44928736652f8d979  scripts/qualify_submission_registry.py
7b566c1cfbb6f06f0a188173a9ab748acffdcf434e92d8f595df3a7b7fb3e67e  missions/campaigns/sim/submissions/capabilities-v1.yaml
1f0bda6c2cdeee58ff6ad0f592af12736b3b851e499d2c461b98dab227ef8387  missions/campaigns/sim/submissions/case-submissions-v1.yaml
04802b58725c93186890accd6d9f01005bd27bace59dcf2e3434d3e0af0de3af  missions/campaigns/sim/qualification/selective-submission-registry-v1.json
b58665ffde8ff2c8e9a09eccc78d6a12af5f2432d63bdb08693a5e81b3cb3c47  missions/campaigns/sim/qualification/selective-submission-ui-inspection-v1.json
e51b8229da4b4aa048feea303e458491430bff8b103f227fad3b6a8481266914  tests/campaign/test_submissions.py
f1fd0ba50a3671a5a6b8bb526f06c6bfc4ae8ae51df1c0c6030304ae51ff91ad  tests/campaign/test_campaign_execution.py
d0197febfc23dea476ea2a101c49702c7ba1b4de6e8bacfd7aa08e751bb7c34d  tests/campaign/test_dynamic_replanning.py
7ad266ad8048432079940d542947ed53e9f39bb9e22f159f3cf2228cdd208a70  tests/api/test_campaign.py
9a7021880408b8685b7d5dcec47255bfdd80d6b291ca8a716becb8b5fdc0321e  ui/app/components/CampaignLab.tsx
291a76fb4191036cec85492f0a2b7f00969388c1da1f335ad95b2de1fda9f5ef  ui/app/globals.css
82e0f1a12e7c76796936ce89b2ac73b9fe5d7438043fd1c712efd7835ce4dc29  ui/tests/campaign-lab.test.tsx
133cddf92760d378544c249d790a215acea75b5d72b6e831153e28802109fda2  ui/openapi.json
b290012068ba02d70c9dacb7cf22ac90112471b2fe59495c7481c326cd72a576  ui/app/lib/api.generated.ts
be9c09ea870a4bcb00320b54bdc2a2b4dad46a8dc92490b38e28e28d2d3c3622  ui/app/lib/models.ts
ABSENT  scripts/qualify_submission_runtime.py
ABSENT  missions/campaigns/sim/submissions/admission-records-v1.yaml
ABSENT  missions/campaigns/sim/qualification/selective-submission-runtime-v2.json
ABSENT  missions/campaigns/sim/qualification/selective-submission-ui-inspection-v2.json
ABSENT  tests/campaign/test_submission_runtime_qualification.py
```

The final implementation manifest must identify every actual changed/new/deleted path,
published release entry, and implementation-owned delimited documentation section with
exact pre/post hashes. It may not absorb other dirty-tree changes by describing “the
diff.”

<!-- WP52-56-R2-DESIGN-PAYLOAD-END -->

### WP-52 through WP-56 remediation R2 design-review handoff

- Originating request: 2026-08-12 explicit authorization to continue this packet
  iteration.
- Review unit: WP-52 through WP-56 together; the original accepted design plus the five
  residual implementation findings are mandatory context.
- Independent verification: `BLOCKED_WITH_FINDINGS`.

- Initial R2 design payload SHA-256:
  `d6189e46a60b30091313f4766f1a8df1ab28f437a536b383ba9ab7bd4b3253fa`.
- Reviewer: fresh project-scoped `/root/wp52_56_r2_design_review`, different from both
  prior reviewers. Initial verdict: `BLOCKED_WITH_FINDINGS`, with five P1 findings and
  one P2: unspecified geometry/metric tolerances and unsafe reorder wording; deferred
  admission metric coverage; multi-axis route-fidelity mapping; unspecified energy
  search/oracle gates; unreproducible ledger-preimage instructions; and the missing
  detailed UI-contract hash.
- Sole author revision: completed. It freezes forward-only normalization and numeric
  invariance; exact metric definitions/windows/equality/distinction thresholds plus all
  54 row mappings; the adherence-only route-fidelity axis; the five-factor physical-v2
  energy compiler and three-repeat acceptance gates; realtime tolerances; reproducible
  ledger reconstruction; and both UI-contract identities.
- Revised R2 design payload SHA-256:
  `31e1da61fffff490416e1e9cf7cbafabcd697c68b9a21a9a40461e15b917740e`.
- Sole focused recheck: same reviewer `/root/wp52_56_r2_design_review` on 2026-08-12.
  Verdict: `BLOCKED_WITH_FINDINGS`, with no P0, two residual P1 findings, and no new P2.
  The complete per-proposal qualification metric set/direction was not frozen because
  the payload still permitted implementation-added metrics, and the claim table
  incorrectly attached the rounded-square realtime anchor to route-fidelity/energy
  capabilities that are explicitly excluded from that comparison.
- Independently accepted corrections include the exact forward-only normalization and
  tolerances, ledger reconstruction, adherence-only route-fidelity mapping, physical-v2
  energy search/repeat gates, both UI-contract identities, and the 54-row inventory.
- Mechanical closeout delta after verdict: only the five independent-verification fields
  and this review record changed. The revised R2 payload remains byte-identical. No
  third automatic design pass is permitted; implementation was not started.

<!-- WP52-56-R3-DESIGN-PAYLOAD-BEGIN -->

### WP-52 through WP-56 remediation iteration R3

#### Frozen originating request and scope

> Ok continue

R3 is a new explicitly authorized design/implementation iteration. It adopts the
accepted parts of R2 payload
`31e1da61fffff490416e1e9cf7cbafabcd697c68b9a21a9a40461e15b917740e`
unchanged and resolves only its two residual P1 ambiguities: the qualification oracle
must be closed per proposal before implementation, and clock boundaries must not be
borrowed across capabilities. The original operator request, accepted WP-52–56 design,
prior reviewed implementation, workflow requirements, all R2 numeric/model/runtime/UI
contracts, and the five packet exits remain mandatory. R3 does not narrow them.

#### Closed per-proposal qualification oracle

The R2 54-row metric mapping is the complete metric set. Implementation may neither add
nor remove a metric for qualification, collapse, or distinctness. Diagnostic values may
be retained but are explicitly non-qualifying. Every metric not named as a
distinguishing relation below is `GUARDRAIL`: it must pass its case hard bound and
packet all-role/terminal requirements, but it cannot establish distinctness. The exact
R2 equality/distinct thresholds, sampling windows, units, repeat policy, and missing-
signal failure rules apply.

Relation grammar is frozen:

- Every proposal and collapse has exactly one comparator:
  `BASELINE(<case_id>)`, meaning the accepted plan/trajectory/runtime produced from the
  exact immutable case, default authority, default objective, default profile, fixed
  backend/configuration/seed, and no case-specific submission. The `<case_id>` is the
  text to the left of `/` on that oracle line. There is no peer-to-peer comparator,
  nearest-peer choice, or all-peer selection, even in experiments with two or more
  proposals. This identity is retained in each admission record and independently
  regenerated before any proposal is compiled.
- `MIN(x)` / `MAX(x)` requires the R2 distinct threshold in the named direction against
  that exact `BASELINE(<case_id>)` comparator.
- `CAT(x=v)` requires the independently observed categorical value exactly; symbolic
  values such as `earliest_feasible` or `capability_priority_optimum` are recomputed by
  an exhaustive independent oracle over the frozen bounded candidate/assignment set.
  It establishes distinctness only when the exact baseline category differs; otherwise
  it is an axis guard and another named relation must establish the required delta.
- `DIFF(x)` requires exact categorical inequality from `BASELINE(<case_id>)` and a
  declared allowed value; it cannot accept an unknown or unauthorized category.
- `ZERO(x)` requires exact numeric/count zero. `SET(x={...})` requires exact role/set
  equality. `ORDER(x=...)` requires exact sequence equality. `PASS(x)` is a named hard
  safety/terminal condition, not a source of distinctness.
- `MIN_CARDINALITY(x)` is permitted only for a frozen set-valued `DS_*` metric. It
  requires a cardinality at least one smaller than `BASELINE(<case_id>)` and exact
  equality to the lexicographically first role set among every independently enumerated
  feasible minimum-cardinality set (`Alpha < Beta < Gamma`). Cardinality and tie-break
  are derived from the existing set value and do not add a qualification metric.
- `COLLAPSE_ALL` requires every metric in that row's complete R2 set to be within its
  equality tolerance and every discrete metric exactly equal to
  `BASELINE(<case_id>)`. Any delta outside equality is an R3 failure for that
  predeclared collapse; it cannot be promoted using the observed delta.
- `REJECT(c)` is allowed only when a complete bounded compiler/search plus independent
  oracle proves exact constraint `c`. Budget exhaustion or missing implementation is
  never `REJECT`.

A visible proposal qualifies only if all its named relations and every guardrail pass.
If its relations do not pass, it may collapse only when `COLLAPSE_ALL` is explicitly
listed below; otherwise the row is inconclusive/failed. Thus neither implementation nor
qualification may select a convenient metric or direction after observing results.
The baseline comparator rule above also removes any equality/distinctness conflict:
each collapse is tested against its case baseline, and every visible peer is tested
independently against that same baseline, never against the collapsed proposal.

`PASS` is non-vacuous. For spatial, dynamics, energy, terminal, capture, ownership,
hold, dwell, and completion metrics it means the exact positive/finite R2 hard bound or
exact required state; a null, absent, zero-capacity, or diagnostic-only bound fails the
proposal instead of satisfying `PASS`. For every `PASS(TM_OVERLAP)` below it means
independently measured simultaneous airborne progress of at least `2.0 s` and route
start skew no greater than `0.20 s`, regardless of a weaker case default. The identical
overlap/start-skew overlay is hash-bound into every proposal that names
`PASS(TM_OVERLAP)` and therefore is never the changed experiment axis. Author audit of
the complete relation list found no other `PASS` whose retained R2 bound is absent,
null, or vacuous; implementation must assert this mechanically before qualification.

The following 24 proposals are the complete, immutable `COLLAPSE_ALL` set:

```text
1d.continuous_waypoint_sequence.canonical_nominal/waypoint.smoothness_first
1d.curved_route.canonical_nominal/curve.jerk_first
1d.move_return.canonical_nominal/turnaround.reversal_stop_first
1d.planar_shape_loop.figure_eight/loop.curvature_continuity
1d.point_to_point_relocation.canonical_nominal/relocation.minimum_time
1d.point_to_point_relocation.canonical_nominal/relocation.energy_reserve
1d.static_multi_goal_sequence.canonical_nominal/goals.shortest_valid_capture
2d.bottleneck.canonical_nominal/bottleneck.fair_precedence
2d.formation_spacing.canonical_nominal/formation.spacing_fidelity
2d.formation_spacing.canonical_nominal/formation.centroid_smoothness
2d.leader_follower.canonical_nominal/leader_follower.rigid_offset
2d.leader_follower.canonical_nominal/leader_follower.elastic_smooth
2d.merge.canonical_nominal/merge.earliest_precedence
2d.parallel_routes.canonical_nominal/parallel.phase_locked
2d.parallel_routes.canonical_nominal/parallel.energy_balanced
2d.unequal_priority.canonical_nominal/priority.bounded_fairness
3d.constrained_volume.canonical_nominal/constrained.priority_order
3d.formation_shape_transform.canonical_nominal/formation.shape_fidelity
3d.formation_shape_transform.canonical_nominal/formation.centroid_smoothness
3d.formation_shape_transform.canonical_nominal/formation.energy_balance
3d.merge.canonical_nominal/merge.fifo_fair
3d.merge.canonical_nominal/merge.priority_precedence
3d.unequal_priorities.canonical_nominal/priorities.bounded_fairness
3d.unequal_priorities.canonical_nominal/priorities.minimax_wait
```

All remaining proposals have the following complete distinguishing relation. Case IDs
are included even where submission IDs happen to repeat:

```text
1d.blocked_replan.dynamic_nominal/blocked_replan.safe_prefix: CAT(DS_FALLBACK=safe_prefix),PASS(SP_CLEARANCE),PASS(DS_TERMINAL_STATE)
1d.blocked_replan.dynamic_nominal/blocked_replan.controlled_land: CAT(DS_FALLBACK=controlled_land),PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)
1d.boundary_constrained_route.canonical_nominal/boundary.route_fidelity: MIN(SP_REFERENCE),PASS(SP_BOUNDARY),PASS(SP_CAPTURE)
1d.boundary_constrained_route.canonical_nominal/boundary.robustness_first: MAX(SP_BOUNDARY),PASS(SP_REFERENCE),PASS(SP_CAPTURE)
1d.continuous_waypoint_sequence.canonical_nominal/waypoint.centerline_first: MIN(SP_REFERENCE),PASS(SP_CAPTURE),ZERO(DS_UNINTENDED_STOP_COUNT)
1d.curved_route.canonical_nominal/curve.centerline_fidelity: MIN(SP_RADIAL),MIN(SP_REFERENCE),PASS(SP_CAPTURE)
1d.mid_route_goal_replacement.dynamic_nominal/goal_replacement.minimum_latency: MIN(TM_CUTOVER),ZERO(DS_STALE_COMMAND_COUNT),PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)
1d.mid_route_goal_replacement.dynamic_nominal/goal_replacement.smooth_splice: MIN(SP_SPLICE_POSITION),MIN(DY_JERK),ZERO(DS_STALE_COMMAND_COUNT),PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)
1d.move_return.canonical_nominal/turnaround.continuity_first: MIN(DY_JERK),PASS(SP_CAPTURE),CAT(DS_REVERSAL_COUNT=1)
1d.moving_target.dynamic_nominal/moving_target.earliest_intercept: MIN(TM_CUTOVER),ZERO(DS_STALE_COMMAND_COUNT),PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)
1d.moving_target.dynamic_nominal/moving_target.smooth_intercept: MIN(SP_SPLICE_POSITION),MIN(DY_JERK),ZERO(DS_STALE_COMMAND_COUNT),PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)
1d.planar_shape_loop.circle/loop.radial_fidelity: MIN(SP_RADIAL),MIN(SP_CLOSURE),CAT(DS_TOPOLOGY=closed_circle)
1d.planar_shape_loop.circle/core.constant_path_speed: MIN(DY_SPEED_TRACKING),CAT(DS_TOPOLOGY=closed_circle),PASS(SP_CLOSURE)
1d.planar_shape_loop.figure_eight/loop.crossover_fidelity: MIN(SP_CAPTURE),MIN(SP_REFERENCE),CAT(DS_TOPOLOGY=figure_eight),CAT(DS_LOBE_ORDER=authored)
1d.planar_shape_loop.rounded_square/corner_transition.lookahead_0_20s: MIN(TM_TRANSITION_START),MIN(SP_CORNER_CUT),PASS(SP_CAPTURE),PASS(SP_CLOSURE) OR REJECT(DEADLINE_VIOLATION)
1d.planar_shape_loop.rounded_square/corner_transition.lookahead_0_60s: MAX(TM_TRANSITION_START),MIN(DY_JERK),PASS(SP_CAPTURE),PASS(SP_CLOSURE)
1d.planning_budget_expiry.dynamic_nominal/budget_expiry.safe_prefix: CAT(DS_FALLBACK=safe_prefix),ZERO(DS_PARTIAL_COMMIT_COUNT),CAT(DS_DISPOSITION=blocked_budget)
1d.planning_budget_expiry.dynamic_nominal/budget_expiry.bounded_hold: CAT(DS_FALLBACK=bounded_hold),PASS(TM_HOLD),ZERO(DS_PARTIAL_COMMIT_COUNT),CAT(DS_DISPOSITION=blocked_budget)
1d.static_multi_goal_sequence.canonical_nominal/goals.smooth_transition: MIN(DY_JERK),PASS(SP_CAPTURE),PASS(TM_DWELL),ZERO(DS_UNINTENDED_STOP_COUNT)
1d.takeoff_hover_land.canonical_nominal/vertical_cycle.precision_first: MIN(DY_VERTICAL_TRACKING),MIN(TM_SETTLE),MAX(TM_DURATION),PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)
1d.takeoff_hover_land.canonical_nominal/vertical_cycle.minimum_duration: MIN(TM_DURATION),PASS(DY_VERTICAL_TRACKING),PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)
2d.bottleneck.canonical_nominal/constraint_directed.bottleneck.simultaneous_vertical: CAT(DS_MANEUVER=vertical),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.bottleneck.canonical_nominal/bottleneck.earliest_safe_release: MIN(TM_WAIT),CAT(DS_OCCUPANCY_INTERVALS=earliest_feasible),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.constrained_border_height.canonical_nominal/constrained_height.timing_only: CAT(DS_MANEUVER=timing),MIN(TM_RELEASE),PASS(SP_CLEARANCE)
2d.constrained_border_height.canonical_nominal/constrained_height.lateral_only: CAT(DS_MANEUVER=lateral),MIN(SP_REFERENCE),PASS(SP_CLEARANCE)
2d.coordination_failure.dynamic_nominal/coordination_failure.safe_old_epoch: CAT(DS_FALLBACK=safe_old_epoch),ZERO(DS_PARTIAL_COMMIT_COUNT),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.coordination_failure.dynamic_nominal/coordination_failure.coordinated_land: CAT(DS_FALLBACK=coordinated_land),ZERO(DS_PARTIAL_COMMIT_COUNT),SET(DS_TERMINAL_STATE={Alpha:landed,Beta:landed})
2d.crossing_goal_change.dynamic_nominal/crossing_update.minimum_delay: MIN(TM_CUTOVER),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.crossing_goal_change.dynamic_nominal/crossing_update.minimum_affected_set: MIN_CARDINALITY(DS_AFFECTED_ROLES),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.head_on_conflict.canonical_nominal/constraint_directed.head_on.same_path: CAT(DS_MANEUVER=retained_combined),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release: CAT(DS_MANEUVER=timing),MIN(TM_RELEASE),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)
2d.head_on_conflict.canonical_nominal/head_on.synchronized_lateral: CAT(DS_MANEUVER=lateral),PASS(TM_OVERLAP),PASS(SP_CLEARANCE),SET(DS_AFFECTED_ROLES={Alpha,Beta})
2d.head_on_conflict.canonical_nominal/head_on.synchronized_vertical: CAT(DS_MANEUVER=vertical),PASS(TM_OVERLAP),PASS(SP_CLEARANCE),SET(DS_AFFECTED_ROLES={Alpha,Beta})
2d.head_on_conflict.canonical_nominal/head_on.path_fidelity_combined: MIN(SP_REFERENCE),PASS(TM_OVERLAP),PASS(SP_CLEARANCE),SET(DS_AFFECTED_ROLES={Alpha,Beta})
2d.head_on_conflict.canonical_nominal/head_on.robustness_combined: MAX(SP_CLEARANCE),PASS(TM_OVERLAP),SET(DS_AFFECTED_ROLES={Alpha,Beta})
2d.leader_loss.dynamic_nominal/leader_loss.promote_follower: CAT(DS_COMMAND_OWNERSHIP=declared_successor),PASS(SP_SPACING),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.leader_loss.dynamic_nominal/leader_loss.coordinated_land: CAT(DS_COMMAND_OWNERSHIP=no_successor),SET(DS_TERMINAL_STATE={Alpha:landed,Beta:landed}),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.merge.canonical_nominal/constraint_directed.merge.flexible_geometry: CAT(DS_MANEUVER=retained_combined),PASS(SP_CLEARANCE)
2d.merge.canonical_nominal/merge.fair_release: MIN(TM_WAIT),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)
2d.merge.canonical_nominal/merge.parallel_lanes: CAT(DS_MANEUVER=lateral),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)
2d.merge.canonical_nominal/merge.vertical_stack: CAT(DS_MANEUVER=vertical),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)
2d.no_hover_crossing.canonical_nominal/no_hover.ground_release: CAT(DS_MANEUVER=ground_release),ZERO(TM_HOLD),PASS(SP_CLEARANCE)
2d.no_hover_crossing.canonical_nominal/no_hover.speed_only: CAT(DS_MANEUVER=speed),ZERO(TM_HOLD),PASS(SP_CLEARANCE)
2d.no_hover_crossing.canonical_nominal/no_hover.lateral_only: CAT(DS_MANEUVER=lateral),ZERO(TM_HOLD),PASS(SP_CLEARANCE)
2d.overtake.canonical_nominal/overtake.speed_retimed_follow: CAT(DS_MANEUVER=speed),ORDER(DS_ROLE_ORDER=leader_before_follower),PASS(SP_CLEARANCE)
2d.overtake.canonical_nominal/overtake.lateral_pass: CAT(DS_MANEUVER=lateral),ORDER(DS_ROLE_ORDER=follower_passes_leader),PASS(SP_CLEARANCE)
2d.overtake.canonical_nominal/overtake.vertical_pass: CAT(DS_MANEUVER=vertical),ORDER(DS_ROLE_ORDER=follower_passes_leader),PASS(SP_CLEARANCE)
2d.perpendicular_crossing.nominal_equal_priority/crossing.earliest_equal_release: CAT(DS_MANEUVER=timing),MIN(TM_RELEASE),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)
2d.perpendicular_crossing.nominal_equal_priority/crossing.synchronized_lateral: CAT(DS_MANEUVER=lateral),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)
2d.perpendicular_crossing.nominal_equal_priority/crossing.synchronized_vertical: CAT(DS_MANEUVER=vertical),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)
2d.role_allocation.canonical_nominal/allocation.capability_first: CAT(DS_ASSIGNMENT=capability_priority_optimum),PASS(DS_COMMAND_OWNERSHIP),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.role_allocation.canonical_nominal/allocation.energy_reserve: MAX(EN_RESERVE_PP),PASS(DS_COMMAND_OWNERSHIP),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta})
2d.simultaneous_conflicting_updates.dynamic_nominal/conflicting_updates.source_order: CAT(DS_DISPOSITION=source_order),ORDER(DS_GENERATION=source_sequence),ZERO(DS_PARTIAL_COMMIT_COUNT)
2d.simultaneous_conflicting_updates.dynamic_nominal/conflicting_updates.role_priority: CAT(DS_DISPOSITION=role_priority),ORDER(DS_GENERATION=declared_role_priority),ZERO(DS_PARTIAL_COMMIT_COUNT)
2d.unequal_priority.canonical_nominal/priority.strict_lexicographic: ORDER(DS_ROLE_ORDER=declared_priority),ZERO(DS_PRIORITY_INVERSION_COUNT)
3d.acknowledgement_loss.dynamic_nominal/ack_loss.safe_old_epoch: CAT(DS_FALLBACK=safe_old_epoch),ZERO(DS_PARTIAL_COMMIT_COUNT),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.acknowledgement_loss.dynamic_nominal/ack_loss.fleet_land: CAT(DS_FALLBACK=fleet_land),ZERO(DS_PARTIAL_COMMIT_COUNT),SET(DS_TERMINAL_STATE={Alpha:landed,Beta:landed,Gamma:landed})
3d.alternative_layers_detours.canonical_nominal/alternatives.lateral_only: CAT(DS_MANEUVER=lateral),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.alternative_layers_detours.canonical_nominal/alternatives.vertical_only: CAT(DS_MANEUVER=vertical),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.alternative_layers_detours.canonical_nominal/alternatives.energy_combined: MIN(EN_ENERGY_WH),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.alternative_layers_detours.canonical_nominal/alternatives.robust_combined: MAX(SP_CLEARANCE),PASS(EN_ENERGY_WH),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.bottleneck.canonical_nominal/bottleneck.earliest_queue: CAT(DS_QUEUE_ORDER=earliest_feasible),PASS(DS_OCCUPANCY_INTERVALS),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.bottleneck.canonical_nominal/bottleneck.max_wait_fair: MIN(TM_STARVATION),PASS(DS_OCCUPANCY_INTERVALS),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.bottleneck.canonical_nominal/bottleneck.direction_batch: MIN(DS_DIRECTION_CHANGE_COUNT),PASS(DS_OCCUPANCY_INTERVALS),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.cascading_replan.dynamic_nominal/cascade.minimum_affected_set: MIN_CARDINALITY(DS_AFFECTED_ROLES),ZERO(DS_STALE_COMMAND_COUNT),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.cascading_replan.dynamic_nominal/cascade.minimum_completion: MIN(TM_DURATION),ZERO(DS_STALE_COMMAND_COUNT),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.cascading_replan.dynamic_nominal/cascade.robustness_first: MAX(SP_CLEARANCE),ZERO(DS_STALE_COMMAND_COUNT),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.constrained_volume.canonical_nominal/constrained.timing_makespan: MIN(TM_DURATION),CAT(DS_MANEUVER=timing),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.constrained_volume.canonical_nominal/constrained.robust_schedule: MAX(SP_CLEARANCE),CAT(DS_MANEUVER=timing),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.leader_follower_recovery.dynamic_nominal/formation_loss.deterministic_successor: CAT(DS_LEASE_GENERATION=2),PASS(SP_FORMATION),PASS(SP_SPACING),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.leader_follower_recovery.dynamic_nominal/formation_loss.fleet_land: CAT(DS_LEASE_GENERATION=1),SET(DS_TERMINAL_STATE={Alpha:landed,Beta:landed,Gamma:landed}),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.merge.canonical_nominal/merge.parallel_capacity: CAT(DS_MANEUVER=lateral),PASS(TM_OVERLAP),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.merge.canonical_nominal/merge.vertical_capacity: CAT(DS_MANEUVER=vertical),PASS(TM_OVERLAP),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.persistent_coverage_reserve_handover.dynamic_nominal/handover.minimum_coverage_gap: MIN(TM_COVERAGE_GAP),PASS(EN_RESERVE_PP),PASS(SP_UNAFFECTED_PATH)
3d.persistent_coverage_reserve_handover.dynamic_nominal/handover.maximum_reserve_margin: MAX(EN_RESERVE_PP),PASS(TM_COVERAGE_GAP),PASS(SP_UNAFFECTED_PATH)
3d.role_allocation.canonical_nominal/allocation.capability_priority: CAT(DS_ASSIGNMENT=capability_priority_optimum),PASS(DS_COMMAND_OWNERSHIP),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.role_allocation.canonical_nominal/allocation.energy_reserve: MAX(EN_RESERVE_PP),PASS(DS_COMMAND_OWNERSHIP),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.role_allocation.canonical_nominal/allocation.balanced_utilization: MIN(EN_SPREAD_PP),PASS(DS_COMMAND_OWNERSHIP),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.simultaneous_center_conflict.joint_schedule_v2/center.global_earliest_schedule: CAT(DS_SCHEDULE=earliest_feasible),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.simultaneous_center_conflict.joint_schedule_v2/center.synchronized_lateral: CAT(DS_SCHEDULE=synchronized_lateral),PASS(TM_OVERLAP),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.simultaneous_center_conflict.joint_schedule_v2/center.synchronized_layers: CAT(DS_SCHEDULE=synchronized_vertical_layers),PASS(TM_OVERLAP),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.simultaneous_center_conflict.joint_schedule_v2/center.earliest_combined: MIN(TM_WAIT),PASS(TM_OVERLAP),PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.simultaneous_center_conflict.joint_schedule_v2/center.robust_combined: MAX(SP_CLEARANCE),PASS(TM_OVERLAP),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
3d.single_pair_conflict.canonical_nominal/single_pair.selective_timing: CAT(DS_MANEUVER=timing),SET(DS_AFFECTED_ROLES={Alpha,Beta}),PASS(SP_UNAFFECTED_PATH),PASS(SP_CLEARANCE)
3d.single_pair_conflict.canonical_nominal/single_pair.selective_lateral: CAT(DS_MANEUVER=lateral),SET(DS_AFFECTED_ROLES={Alpha,Beta}),PASS(SP_UNAFFECTED_PATH),PASS(SP_CLEARANCE)
3d.single_pair_conflict.canonical_nominal/single_pair.selective_vertical: CAT(DS_MANEUVER=vertical),SET(DS_AFFECTED_ROLES={Alpha,Beta}),PASS(SP_UNAFFECTED_PATH),PASS(SP_CLEARANCE)
3d.unequal_priorities.canonical_nominal/priorities.strict_lexicographic: ORDER(DS_ROLE_ORDER=Alpha,Beta,Gamma),ZERO(DS_PRIORITY_INVERSION_COUNT),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
```

The no-submission inventory has two distinct lifecycle classes:

- The nine `BASELINE_ONLY` rows remain governed by their complete R2 negative/fallback
  metric sets and require all discrete dispositions, authority, partial-commit, and
  terminal values exactly as frozen in the original matrix. They are not submission
  proposals and cannot be used to add a catalog alternative.
- `1d.altitude_transition.canonical_nominal` and `1d.altitude_transition.wide` are the
  two `RETAIN_EXISTING_ONLY` rows, not negative/fallback rows. Canonical retains exactly
  `E constant_path_speed.slow`, `E constant_path_speed.stress`, and
  `E ramped_segment_speed.altitude_kinks`; wide retains exactly
  `E constant_path_speed.stress` and `E bounded_vertical_rate.wide`. All five remain
  covered by the existing execution-profile compiler and the authoritative
  `scripts/qualify_altitude_profiles.py` gates/artifact
  `missions/campaigns/sim/qualification/altitude-profile-runtime-qualification-v1.json`:
  accepted profile identity/trajectory distinction, the full corresponding R2 metric
  set at lines 2398–2399, hard dynamics/actuator/energy/capture/terminal bounds, two
  accelerated repeats per admitted case/profile, canonical/wide stress comparison, and
  the retained observed-realtime anchor. They are not counted among the 111 registry
  proposal keys and R3 neither clones nor requalifies them as case submissions.

#### Corrected capability and clock claim matrix

Evidence is non-transferable across these rows:

| Claim | Exact anchor | Maximum claim boundary |
|---|---|---|
| `core.route_fidelity` | `1d.curved_route.canonical_nominal` adherence-only capability request plus renamed compatible/incompatible children | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` |
| `core.energy_aware_retiming` | `1d.point_to_point_relocation.canonical_nominal`, renamed compatible child, and `2d.parallel_routes.canonical_nominal` coupling under the R2 three-repeat energy gates | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` |
| `core.corner_transition` lookahead behavior | rounded-square `0.20 s` exact rejection and `0.60 s` execution; the paced rounded-square lookahead comparison only | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` for this corner claim alone |
| 2D source-time fleet cutover | one accepted 2D update with both-role command/epoch evidence | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` for that cutover claim alone |
| 3D atomic/fallback | one declared three-role atomic/fallback case with all-role evidence | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` for that fleet claim alone |
| Remaining executable matrix rows | exact normal `run_active` row evidence | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` |
| Rendered UI | exact immutable release and real API screenshots/interaction inspection | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE` |

The rounded-square realtime run cannot upgrade route fidelity or energy retiming; the
2D/3D realtime runs cannot upgrade another event/capability; accelerated evidence cannot
be labeled realtime. Live-Isaac, hardware, digital-twin, and physical transfer remain
outside scope.

#### R3 exit, identity, and review boundary

R3 changes no R2 implementation task, numeric gate, test sequence, non-goal, or file
preimage. Implementation may start only after this exact R3 payload is
`DESIGN_VERIFIED`; then it must implement the entire combined R2+R3 design and undergo a
different fresh implementation review. The final manifest includes every changed path
and both delimited design sections.

- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Pre-R3 `ACTIVE.md` SHA-256:
  `abdac66cf8fc47bbb4ac05d3a982803af1b9484daecb75f14a6588abd58c6d83`.
  It is reproduced byte-for-byte from the current ledger by removing from the R3 begin
  marker through the line before `## Future mission-family application`, then changing
  the five R3 `DRAFT_UNVERIFIED` fields back to their pre-R3
  `BLOCKED_WITH_FINDINGS` values. The exact read-only reconstruction is:
  `awk 'BEGIN{skip=0} /<!-- WP52-56-R3-DESIGN-PAYLOAD-BEGIN -->/{skip=1}
  /^## Future mission-family application/{skip=0} !skip{print}' ACTIVE.md | sed
  's/`DRAFT_UNVERIFIED`/`BLOCKED_WITH_FINDINGS`/g'`; its bytes hash to the value above.
- Adopted R2 payload SHA-256:
  `31e1da61fffff490416e1e9cf7cbafabcd697c68b9a21a9a40461e15b917740e`.
- Original accepted design and reviewed implementation SHA-256:
  `69610ffc436817b2c610be998423fd87afe589b2406e594e04744ffcfc2604d2`
  and `7a3f4e584c5b279ff587a86a94da432c8f76ab3691785c3330b2d33453dbe9b9`.
- All other relevant source/artifact/case/release/UI-contract preimages are exactly the
  ones reproduced and frozen inside R2. R3 authorizes no pre-verdict code edit.

<!-- WP52-56-R3-DESIGN-PAYLOAD-END -->

### WP-52 through WP-56 remediation R3 design-review handoff

- Originating request: 2026-08-12 explicit `Ok continue` authorization.
- Review unit: combined R2+R3 WP-52–56 design, with R3 closing the two R2 P1s.
- Independent verification: `DESIGN_VERIFIED`.

- Initial R3 design payload SHA-256:
  `9519afc1d13a1e63f3a9c61a48789aef5bdd3124637a8a7bd3ce68ca65f698b1`.
- Initial verdict: `BLOCKED_WITH_FINDINGS`, with no P0, six P1 findings, and no separate
  P2. The initial oracle used eight out-of-row metrics; left comparator selection open
  and created peer/collapse contradictions; ordered two role sets without cardinality
  semantics; allowed the 3D merge capacity overlap gate to pass at zero; conflated nine
  baseline-only rows with two retain-existing-only altitude rows; and supplied no
  reproducible reconstruction for its asserted ledger preimage.
- Sole author revision: completed. It binds every relation/collapse to the exact
  no-submission case baseline; adds deterministic set-cardinality/tie-break semantics;
  replaces all eight illegal metric references and passes a zero-error membership
  audit; freezes `2.0 s` overlap plus `0.20 s` start skew for every overlap guard;
  splits the nine negative rows from both retained altitude/profile rows and their five
  authoritative profile bindings; and provides a reproducing pre-R3 ledger command and
  corrected hash.
- Revised R3 design payload SHA-256:
  `24c5a4e0ba50cbae1d33a3a31a121de362ba34fa3a627a4cec3b79d02d8ccf11`.
- Coverage audit: all 111 registry proposals appear exactly once in the closed oracle,
  split into 24 immutable `COLLAPSE_ALL` entries and 87 explicit qualifying relations;
  the membership audit reports zero illegal row-metric references; nine baseline-only
  rows remain explicit negative/fallback audits and two retain-existing-only altitude
  rows remain under their five authoritative execution-profile gates.
- Required reviewer: a fresh `work_packet_verifier`, different from every earlier
  WP-52–56 design/implementation verifier.
- The sole author revision has been consumed. One focused recheck by the same reviewer
  was completed on 2026-08-12. Verdict: `BLOCKED_WITH_FINDINGS`, with no P0, one
  residual P1, and no P2. Five initial P1s were resolved; the remaining P1 is that the
  `PASS(TM_OVERLAP)` proposal overlay strengthens overlap/start-skew relative to the
  unchanged `BASELINE(case_id)`, so authority experiments change both maneuver
  authority and coordination constraints. The required future correction is to compile
  the baseline under the identical hash-bound overlap/start-skew overlay while retaining
  baseline authority/objective/profile/backend/seed, or redesign affected immutable
  defaults in a separately authorized design iteration. Implementation remains
  prohibited because R3 did not reach `DESIGN_VERIFIED`; no third automatic pass is
  permitted.

<!-- WP52-56-R4-DESIGN-PAYLOAD-BEGIN -->

### WP-52 through WP-56 remediation iteration R4

#### Frozen request, inheritance, and sole correction

> Ok continue

R4 is a new explicitly authorized iteration. It adopts the original accepted WP-52–56
design, the complete R2 payload
`31e1da61fffff490416e1e9cf7cbafabcd697c68b9a21a9a40461e15b917740e`,
and the complete R3 payload
`24c5a4e0ba50cbae1d33a3a31a121de362ba34fa3a627a4cec3b79d02d8ccf11`.
All R2 numeric/runtime/capability/UI gates and all R3 metric membership, comparator,
cardinality, lifecycle-class, retained-profile, clock-boundary, and ledger contracts
remain unchanged except for the single comparator-context correction below. R4 does
not authorize implementation before `DESIGN_VERIFIED` and does not narrow any WP-52–56
exit.

#### Symmetric overlap comparison context

R3's `PASS(TM_OVERLAP)` numeric requirement remains exactly simultaneous airborne
progress `>= 2.0 s` and route-start skew `<= 0.20 s`, but it is no longer a
proposal-only overlay. It is a qualification comparison context applied identically to
both subject and comparator before the declared proposal axis is applied.

The exact canonical JSON for this context is:

```json
{"maximum_route_start_skew_s":0.2,"minimum_simultaneous_flight_s":2.0,"synchronized_route_start_required":true}
```

Its UTF-8 bytes with no trailing newline have SHA-256
`56c6501ea784fb1116ad35bffacc13a42813c1fe9925f885f58e8925dc6bdbdb` and the retained
context ID is `overlap-comparison-v1`.

For each affected proposal, qualification must:

1. Resolve the exact immutable case and default no-submission baseline from R3.
2. Apply `overlap-comparison-v1` to the baseline's coordination constraints and compile
   `BASELINE(<case_id>,overlap-comparison-v1)` with default authority, objective,
   adherence, execution profile, search, backend, configuration, seed, and safety gates.
3. Apply the byte-identical context to the subject, then apply only its one declared
   submission axis and compile the subject with every other field byte-equivalent to
   the contextual baseline.
4. Retain the context ID/hash in both admission records, resolved-package identities,
   plans, trajectories, runtime requests, metric records, and comparison evidence. A
   subject/comparator context-hash mismatch fails before planning.
5. Independently measure `TM_OVERLAP` and route-start skew for both sides. Both must pass
   the context; it is a guardrail and cannot establish distinctness. The R3 relation's
   other named `MIN`, `MAX`, `CAT`, `SET`, or `ORDER` terms establish distinctness.
6. Fail the proposal as inconclusive if either contextual baseline or subject is not
   completely certified. It may not fall back to the weaker immutable-case default,
   use an uncontextualized historical run, promote safe rejection into distinctness, or
   weaken the context after observing feasibility.

The context is an evidence-fixture input, not a mutation of the immutable catalog case,
not a planning submission field, and not an extra experiment axis: it is fixed and
identical across both sides. Whole-case hashes and historical runs remain unchanged.
The contextual baseline receives a separate resolved-package/evidence identity so it
cannot be confused with the case-default baseline.

The following 17 proposal keys are the complete immutable affected set; these and only
these R3 relations contain `PASS(TM_OVERLAP)` and therefore use
`BASELINE(<case_id>,overlap-comparison-v1)`:

```text
2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release
2d.head_on_conflict.canonical_nominal/head_on.synchronized_lateral
2d.head_on_conflict.canonical_nominal/head_on.synchronized_vertical
2d.head_on_conflict.canonical_nominal/head_on.path_fidelity_combined
2d.head_on_conflict.canonical_nominal/head_on.robustness_combined
2d.merge.canonical_nominal/merge.fair_release
2d.merge.canonical_nominal/merge.parallel_lanes
2d.merge.canonical_nominal/merge.vertical_stack
2d.perpendicular_crossing.nominal_equal_priority/crossing.earliest_equal_release
2d.perpendicular_crossing.nominal_equal_priority/crossing.synchronized_lateral
2d.perpendicular_crossing.nominal_equal_priority/crossing.synchronized_vertical
3d.merge.canonical_nominal/merge.parallel_capacity
3d.merge.canonical_nominal/merge.vertical_capacity
3d.simultaneous_center_conflict.joint_schedule_v2/center.synchronized_lateral
3d.simultaneous_center_conflict.joint_schedule_v2/center.synchronized_layers
3d.simultaneous_center_conflict.joint_schedule_v2/center.earliest_combined
3d.simultaneous_center_conflict.joint_schedule_v2/center.robust_combined
```

Every other R3 proposal and collapse keeps `BASELINE(<case_id>)` with no comparison
context. A mechanical audit must extract exactly 17 `PASS(TM_OVERLAP)` relations and
prove set equality with the list above; duplicate, missing, or extra bindings fail the
gate.

#### R4 identity and review boundary

- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Pre-R4 `ACTIVE.md` SHA-256:
  `ab2087bbb5519d5f078650d0d06db989338be54552ad161064a50e4487014fef`.
  It is reproduced from the current ledger by removing from the R4 begin marker through
  the line before `## Future mission-family application`, then changing the five R4
  `DRAFT_UNVERIFIED` fields back to their pre-R4 `BLOCKED_WITH_FINDINGS` values:
  `awk 'BEGIN{skip=0} /<!-- WP52-56-R4-DESIGN-PAYLOAD-BEGIN -->/{skip=1}
  /^## Future mission-family application/{skip=0} !skip{print}' ACTIVE.md | sed
  '/^| WP-5[2-6] |/ s/`DRAFT_UNVERIFIED`/`BLOCKED_WITH_FINDINGS`/'`.
- R3 payload SHA-256:
  `24c5a4e0ba50cbae1d33a3a31a121de362ba34fa3a627a4cec3b79d02d8ccf11`.
- All code, test, case, artifact, release, UI-contract, and absence preimages remain the
  exact R2-frozen values. R4 authorizes no pre-verdict implementation edit.

<!-- WP52-56-R4-DESIGN-PAYLOAD-END -->

### WP-52 through WP-56 remediation R4 design-review handoff

- Originating request: 2026-08-12 explicit `Ok continue` authorization.
- Review unit: combined R2+R3+R4 WP-52–56 design; R4 changes only the sole residual R3
  comparator-context finding.
- Independent verification: `DESIGN_VERIFIED`.
- R4 design payload SHA-256:
  `7a40f0f70384cef67eeb6d1fca5d09f859e001d07843bfeb7bc51d2989cab08d`.
- Author audit: the 17 R3 relations containing `PASS(TM_OVERLAP)` exactly equal the 17
  frozen R4 contextual-comparator keys, with no missing or extra binding; the pre-R4
  ledger reconstruction reproduces exactly.
- Required reviewer: a fresh project-scoped `work_packet_verifier`, different from all
  earlier WP-52–56 design and implementation reviewers.
- One author revision and one focused recheck by that reviewer are permitted.
  Fresh reviewer `/root/wp52_56_r4_design_review` returned `DESIGN_VERIFIED` on
  2026-08-12 with no P0, P1, or P2 findings; no author revision or focused recheck was
  needed. All inherited and R4 identities reproduced, the 17-key sets were exactly
  equal, every affected relation retained a non-`PASS` distinctness term, and the
  symmetric context/history/fail-closed boundaries passed independent counterexamples.
  Implementation of the combined verified R2+R3+R4 design is authorized.

<!-- WP52-56-R5-DESIGN-PAYLOAD-BEGIN -->

### WP-52 through WP-56 remediation iteration R5 and workflow retrospective

#### Frozen request, inheritance, and scope

> Ok contie, but i also want you to add the knowledge and learning from all repetitions
> and revisions and iterations to the workflow file so maybe in future not do many
> revisions have to be done

R5 is a new explicitly authorized design iteration. It adopts the original accepted
WP-52–56 design and the complete accepted R2, R3, and R4 payloads, while correcting
only contradictions exposed by the independent executable metric/context audit and
making those failure modes durable in `WORKFLOW_AND_REQUIREMENTS.md`. It does not
weaken a safety, runtime, UI, capability, evidence, or claim-boundary exit. No R5 code,
registry, artifact, release, or status implementation is authorized until this exact
payload is `DESIGN_VERIFIED`.

The durable workflow change is part of this design review:

- workflow preimage SHA-256:
  `c0efd0bafa1e936433e1aa8ee4291a81d176f54ef0e35f45a09bba0261121652`;
- R5 workflow postimage SHA-256:
  `b311bf74776d6c4e6b27af293357187d0883b38ded37a7d2a8f435b35f6faa34`;
- new `REQ-WFL-028` through `REQ-WFL-038` require a machine-readable pre-freeze
  coverage/membership audit, numerical prototype and feasible witness, exact
  baseline/peer comparators, full-vector collapse proof, symmetric/non-vacuous/
  feasible/axis-compatible contexts, point-density invariance, exact rejection
  taxonomy, real production-trigger claim traces, literal row-record round trips,
  byte-reproducible preimages, cumulative retrospectives, and exact served-release UI
  evidence;
- the independent protocol, repeated-review learning table, feedback date, and change
  log now incorporate those requirements. This is documentation authority only; the
  workflow edit grants no implementation or runtime authority by itself.
- The R4 handoff's stale `DRAFT_UNVERIFIED` label is mechanically reconciled to its
  already-retained passing verdict, reviewer, date, and packet-table state; no R4
  payload or claim changes.

The workflow preimage is reproduced byte-for-byte from the R5 postimage by this exact
read-only command; its output hashes to the asserted `c0efd0...` identity:

```sh
awk 'BEGIN{skipstep=0;bt=sprintf("%c",96)} {if (index($0,"| Last feedback reconciliation |")==1) sub(/2026-08-12/,"2026-08-11"); if ($0 ~ /REQ-WFL-02[89]/ || $0 ~ /REQ-WFL-03[0-8]/) next; if (index($0,"2. **Audit, draft, and freeze design.**")==1){print "2. **Draft and freeze design.** Write the packet in " bt "ACTIVE.md" bt " with canonical"; print "   " bt "Status" bt " plus " bt "Independent verification: DRAFT_UNVERIFIED" bt ". Preserve the original"; print "   user request, delimit the substantive design payload, and compute its hash outside"; print "   the verification record."; skipstep=1; next} if (skipstep && index($0,"3. **Run the design gate.**")==1) skipstep=0; if (skipstep) next; if (index($0,"| WP-52 through WP-56 repeated design and implementation iterations |")==1) next; if (index($0,"| 2026-08-12 | Operator request to retain the knowledge from all WP-52 through WP-56 repetitions")==1) next; print}' docs/project/WORKFLOW_AND_REQUIREMENTS.md | shasum -a 256
```

#### Retained pre-freeze audit and corrected comparator model

The authoritative machine-readable pre-freeze audit is
`docs/work-packages/WP52_56_R5_PREDRAFT_AUDIT_2026-08-12.json`, SHA-256
`7be497ea4faba9eddd3b220ef698a8a6834e38f0a12878233e3131a9cd5ff87a`.
It binds the exact proposal/admission source hashes, derivation algorithm, counts,
complete collapse set, comparator map, relation overrides, context membership, atomic
pairs, profile axes, witness vectors, and negative checks. Loading that JSON and the
two bound YAML sources reports 54/111/29/82, three context keys, twelve unique atomic-
pair keys, lifecycle 9/2, valid same-experiment peer targets, and zero membership
errors. No R5 count or relation requires interpreting prose.

The audit also used compiled packages, the bounded planner, accepted trajectories, and
the independent `0.01 s` metric oracle. Hidden rows compile only through
`compile_registry_planning_submission(..., audit_hidden=True)` and collapse comparison
uses `measure_planning_behavior()` plus `compare_for_collapse()` over the complete row
`metric_ids`.

The frozen pre-draft results are:

- exactly 54 admission rows, 111 unique proposal keys, nine `BASELINE_ONLY` rows, two
  `RETAIN_EXISTING_ONLY` rows, and the same five retained altitude profiles;
- the R3 source contains 24 unique `COLLAPSE_ALL` proposals. Nineteen equal their exact
  case baseline. Five do not equal the baseline but each equals one exact already
  visible peer in the same experiment across the complete row metric vector:

```text
2d.bottleneck.canonical_nominal/bottleneck.fair_precedence
  -> PEER(2d.bottleneck.canonical_nominal/bottleneck.earliest_safe_release)
2d.unequal_priority.canonical_nominal/priority.bounded_fairness
  -> PEER(2d.unequal_priority.canonical_nominal/priority.strict_lexicographic)
3d.constrained_volume.canonical_nominal/constrained.priority_order
  -> PEER(3d.constrained_volume.canonical_nominal/constrained.timing_makespan)
3d.unequal_priorities.canonical_nominal/priorities.bounded_fairness
  -> PEER(3d.unequal_priorities.canonical_nominal/priorities.strict_lexicographic)
3d.unequal_priorities.canonical_nominal/priorities.minimax_wait
  -> PEER(3d.unequal_priorities.canonical_nominal/priorities.strict_lexicographic)
```

The peer is literal and cannot be selected after observing output. It must be visible,
same-case, same-experiment, independently qualified first, and bound by exact accepted
artifact and metric identities. Every other R5 collapse uses its exact contextual or
uncontextualized `BASELINE(<case_id>)`. Nearest-peer, any-peer, chained hidden-peer, and
implementation-selected comparators are forbidden.

The executable audit also found baseline-equivalent controls whose frozen relation
could never establish its claimed delta, and three hidden 1D alternatives that are the
actual learning choices requested by the operator. R5 therefore replaces the R3
24-collapse partition with the following exact 29-key partition:

```text
1d.boundary_constrained_route.canonical_nominal/boundary.route_fidelity
1d.continuous_waypoint_sequence.canonical_nominal/waypoint.centerline_first
1d.curved_route.canonical_nominal/curve.centerline_fidelity
1d.move_return.canonical_nominal/turnaround.reversal_stop_first
1d.planar_shape_loop.circle/loop.radial_fidelity
1d.planar_shape_loop.figure_eight/loop.crossover_fidelity
1d.point_to_point_relocation.canonical_nominal/relocation.minimum_time
1d.point_to_point_relocation.canonical_nominal/relocation.energy_reserve
1d.static_multi_goal_sequence.canonical_nominal/goals.shortest_valid_capture
2d.bottleneck.canonical_nominal/bottleneck.fair_precedence
2d.constrained_border_height.canonical_nominal/constrained_height.timing_only
2d.formation_spacing.canonical_nominal/formation.spacing_fidelity
2d.formation_spacing.canonical_nominal/formation.centroid_smoothness
2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release
2d.leader_follower.canonical_nominal/leader_follower.rigid_offset
2d.leader_follower.canonical_nominal/leader_follower.elastic_smooth
2d.merge.canonical_nominal/merge.earliest_precedence
2d.parallel_routes.canonical_nominal/parallel.phase_locked
2d.parallel_routes.canonical_nominal/parallel.energy_balanced
2d.unequal_priority.canonical_nominal/priority.bounded_fairness
3d.constrained_volume.canonical_nominal/constrained.priority_order
3d.formation_shape_transform.canonical_nominal/formation.shape_fidelity
3d.formation_shape_transform.canonical_nominal/formation.centroid_smoothness
3d.formation_shape_transform.canonical_nominal/formation.energy_balance
3d.merge.canonical_nominal/merge.fifo_fair
3d.merge.canonical_nominal/merge.priority_precedence
3d.simultaneous_center_conflict.joint_schedule_v2/center.global_earliest_schedule
3d.unequal_priorities.canonical_nominal/priorities.bounded_fairness
3d.unequal_priorities.canonical_nominal/priorities.minimax_wait
```

All 29 are hidden, commandless, and retain both accepted artifacts and the complete
independent row vector against their exact comparator. All other 82 proposal keys are
visible relations. This is the sole R5 classification set; the duplicated figure-eight
line in the R3 prose list is removed by machine key uniqueness rather than counted.

Three former collapses become visible, initially `PLANNED_NOT_EXECUTABLE`, because they
provide the actual reusable smoothness questions instead of a second label for the
baseline. They are execution-owned one-axis experiments—not planning objective-order
experiments—and their complete axes/relations are:

```text
1d.continuous_waypoint_sequence.canonical_nominal/waypoint.smoothness_first:
  E CAPABILITY_BINDING=corner_transition_0_60s_at_0_08m_s;
  MIN(DY_CURVATURE),MIN(SP_REFERENCE),MAX(TM_DURATION),PASS(SP_CAPTURE),ZERO(DS_UNINTENDED_STOP_COUNT)
1d.curved_route.canonical_nominal/curve.jerk_first:
  E SCALAR_PARAMETER=duration_scale_1_30;
  MIN(DY_JERK),MAX(TM_DURATION),PASS(SP_RADIAL),PASS(SP_REFERENCE),PASS(SP_CAPTURE)
1d.planar_shape_loop.figure_eight/loop.curvature_continuity:
  E CAPABILITY_BINDING=corner_transition_0_60s_at_0_08m_s;
  MIN(DY_CURVATURE),MIN(SP_REFERENCE),PASS(SP_CAPTURE),CAT(DS_TOPOLOGY=figure_eight),CAT(DS_LOBE_ORDER=authored)
```

They use the existing complete row metric sets and the exact R2 equality/distinctness
thresholds. Their comparator is the exact same-case baseline execution profile; the
planning submission, objective, authority, case, backend, seed, and every other profile
field remain identical. The implementation must reuse shared owning primitives, not
three mission-ID branches. `waypoint.smoothness_first` and
`loop.curvature_continuity` bind
the normalized semantic-polyline corner-transition compiler with exact
`lookahead_time_s=0.60` and the lowest certified path speed `0.08 m/s` while retaining
all required regions/topology. The pre-freeze production compiler witness is `READY`
for all three named cases; on waypoint and figure-eight it reduces independently
sampled maximum curvature by far more than the frozen `0.05 1/m` distinctness minimum
and reduces reference error while preserving capture/topology. `curve.jerk_first`
uses the shared duration-scale time law at exact factor `1.30`; its pre-freeze witness
is `READY`, changes duration `16.062993878978638 -> 20.88189204267223 s`, and reduces
independent maximum jerk `1.9979284112899076 -> 0.9110964272093369 m/s^3` while the
reference delta remains inside equality. The implementation must reproduce these
directions through the normal package/service path and retain full hard-gate evidence;
these prototype numbers are feasibility witnesses, not runtime qualification.

#### Corrected capacity context and synchronized atomic experiments

R5 withdraws `overlap-comparison-v1` from qualification. The frozen production
compiler cannot currently produce an accepted synchronized contextual baseline for
head-on, merge, crossing, or center, so no relation or collapse may cite that package.
The context ID/hash remain historical R4 design evidence only and are not emitted by
the R5 registry, compiler, package identity, qualifier, or UI.

The sole R5 comparison context covers the three release/wait comparisons for which a
positive active-capacity objective is required without forcing synchronized starts.
Its exact no-newline canonical JSON is:

```json
{"minimum_simultaneous_flight_s":2.0}
```

It has ID `overlap-capacity-v1` and SHA-256
`5254a2e98af7599c2d81bdf4457d94f7b44768d267a4a51d374752651b445f63`.
It overlays only the positive overlap bound on both subject and exact case baseline,
retains every other field, and is limited to:

```text
2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release
2d.merge.canonical_nominal/merge.fair_release
2d.perpendicular_crossing.nominal_equal_priority/crossing.earliest_equal_release
```

All three subject/baseline pairs have accepted pre-freeze artifacts. Head-on timing is
complete-vector equal to the contextual baseline and remains one of the 29 collapses.
Merge fair retains `MIN(TM_WAIT),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)` with witness wait
`4.0 -> 2.0 s`. Crossing timing uses
`CAT(DS_MANEUVER=timing),MIN(SP_REFERENCE),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)`; it no
longer falsely requires lower release skew than the combined-authority baseline.

The twelve synchronized authority/objective proposals below are six exact atomic
same-experiment pairs, not baseline comparisons and not comparison-context users:

```text
head_on.authority: head_on.synchronized_lateral <-> head_on.synchronized_vertical
head_on.objective: head_on.path_fidelity_combined <-> head_on.robustness_combined
merge.authority: merge.parallel_lanes <-> merge.vertical_stack
crossing.authority: crossing.synchronized_lateral <-> crossing.synchronized_vertical
merge3.authority: merge.parallel_capacity <-> merge.vertical_capacity
center.authority: center.synchronized_lateral <-> center.synchronized_layers
```

Both members freeze identical experiment inputs
`synchronized_route_start_required=true`, `maximum_route_start_skew_s=0.20`, and
`minimum_simultaneous_flight_s=2.0`; only their declared maneuver or objective axis
differs. Each pair is compiled, certified, measured, and disposed atomically. It
qualifies only when both accepted artifacts pass the shared constraints and both
opposite directional/categorical relations; otherwise both remain visible but disabled
as `PLANNED_NOT_EXECUTABLE` with their exact independent dispositions. Timeout,
unsupported behavior, or missing implementation is inconclusive and never becomes
safe rejection. A peer is never chosen dynamically and neither peer may qualify or
collapse using an infeasible neutral baseline.

`center.robust_combined` is the thirteenth former synchronized-context key. It uses the
absolute exhaustive relation
`ARGMAX_BOUNDED(SP_CLEARANCE),PASS(TM_OVERLAP),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})`
over the exact frozen R2 bounded candidate family, with the same synchronized/overlap
hard inputs. The independent oracle enumerates the family and tie-break rather than
comparing an unavailable contextual baseline.

`center.earliest_combined` has no pre-freeze feasible capacity-context witness. R5
therefore removes its `PASS(TM_OVERLAP)` comparison and retains it visibly disabled as
`OPEN(INCONCLUSIVE_MISSING_FEASIBLE_WITNESS)` / `PLANNED_NOT_EXECUTABLE`. It receives no
runtime or rejection claim in this batch. A future design may reopen it only with a
retained feasible witness; R5 does not invent one.

#### R5 implementation and exit gates

Implementation must update the literal admission source, generated registry, model
validation, compiler, contextual package identity, independent measurement, qualifier,
API/UI presentation, tests, and immutable qualification artifacts as one vertical
slice. Exact machine gates must prove:

1. The retained audit reproduces 54 rows, 111 unique proposals, 29 collapses, 82
   visible relations, exactly three `overlap-capacity-v1` keys, six synchronized atomic
   pairs, nine baseline-only rows, two retain-existing-only rows, and five retained
   altitude profiles; every proposal appears exactly once.
2. Every relation metric belongs to its frozen row set; every peer comparator exists,
   is visible/same-experiment, qualifies first or belongs to one frozen atomic pair,
   and is never selected dynamically.
3. All 29 complete-vector collapse proofs pass against their exact baseline/peer and
   accepted artifacts; perturbing any one named continuous metric beyond its R2
   tolerance or any discrete metric breaks the proof.
4. The three reopened 1D alternatives reproduce their frozen directional witness,
   normal production Fast-Sim evidence, required hard gates, and the original/densified/
   simplified/renamed/incompatible perturbations without case-ID special branches.
5. `overlap-capacity-v1` is byte/hash exact, symmetric, non-vacuous,
   history-preserving, and fail-closed. No R5 path resolves or emits
   `overlap-comparison-v1`. Each synchronized pair proves identical fixed inputs and an
   atomic all-qualified or all-disabled disposition without a neutral baseline.
6. `REJECT` and runtime/production claims obey new `REQ-WFL-033` and `REQ-WFL-034`;
   budget exhaustion is inconclusive and every production claim enters the normal
   public service/API trigger through retained execution/evaluator evidence.
7. The exact served UI release satisfies `REQ-UI-001` and `REQ-WFL-038` at desktop and
   narrow widths. A source/build-only or stale-release observation remains not run.

All inherited R2 runtime repeats, realtime anchors, route-fidelity and energy gates,
2D/3D fleet cutover/fallback gates, safety boundaries, UI states, negative cases,
claim-level environment/clock limits, and external exclusions remain mandatory.

#### R5 exact identities and review boundary

- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Pre-R5 `ACTIVE.md` SHA-256:
  `4d4a9e643fdfb214c7f3c808088d22445aacfa374421486b0dddb7f4ec9f00bd`.
  It is reconstructed by removing this R5 delimited payload and its following R5
  design-review handoff through the line before `## Future mission-family application`,
  then changing the five packet verification fields from `DRAFT_UNVERIFIED` back to
  `DESIGN_VERIFIED` and restoring the pre-R5 stale R4 handoff label. The exact command
  below reproduces the asserted hash:

```sh
awk 'BEGIN{skip=0;r4=0;bt=sprintf("%c",96)} /<!-- WP52-56-R5-DESIGN-PAYLOAD-BEGIN -->/{skip=1} /^## Future mission-family application/{skip=0} !skip{if ($0=="### WP-52 through WP-56 remediation R4 design-review handoff") r4=1; if (r4 && index($0,"- Independent verification:")==1){print "- Independent verification: " bt "DRAFT_UNVERIFIED" bt "."; r4=0; next} if (index($0,"| WP-5")==1) sub(/DRAFT_UNVERIFIED/,"DESIGN_VERIFIED"); print}' docs/work-packages/ACTIVE.md | shasum -a 256
```
- R4 payload SHA-256:
  `7a40f0f70384cef67eeb6d1fca5d09f859e001d07843bfeb7bc51d2989cab08d`;
  adopted R3/R2/original payload hashes remain
  `24c5a4e0ba50cbae1d33a3a31a121de362ba34fa3a627a4cec3b79d02d8ccf11`,
  `31e1da61fffff490416e1e9cf7cbafabcd697c68b9a21a9a40461e15b917740e`, and
  `69610ffc436817b2c610be998423fd87afe589b2406e594e04744ffcfc2604d2`.
- Relevant current code/source preimages are:
  `submissions.py` `acae7f96879aaf16525c04a81c9be732f19057ef40350dc2451f71b1dff50167`,
  `submission_measurement.py` `bdd1d903090ac1143a2a3b2b6ef302950e5342ed8f0cf5a4302b774c552494f8`,
  `planner.py` `5810ee993fa464e5230c3f584a3c95db7d95cc3fe9131483ce6bdcfbac445701`,
  `admission-records-v1.yaml` `f5304c3647fbf22dff34940a6acb34547721ba7c26ab937befb8ff046af8f79d`,
  and `case-submissions-v1.yaml` `1f0bda6c2cdeee58ff6ad0f592af12736b3b851e499d2c461b98dab227ef8387`.
- The retained R5 audit postimage is
  `7be497ea4faba9eddd3b220ef698a8a6834e38f0a12878233e3131a9cd5ff87a`.
- No post-R5 implementation-code/source hash exists before verdict. The workflow
  postimage, retained audit, R4 handoff reconciliation, and this delimited design are
  the only substantive R5 design-gate changes.

<!-- WP52-56-R5-DESIGN-PAYLOAD-END -->

### WP-52 through WP-56 remediation R5 design-review handoff

- Originating request: 2026-08-12 request to continue and retain all iteration
  learnings in the workflow.
- Review unit: combined accepted WP-52–56 design plus this R5 correction and workflow
  hardening.
- Independent verification: `BLOCKED_WITH_FINDINGS`.
- Initial R5 design payload SHA-256:
  `904c7a0daabd28f072a814854c3725b37ab84b73bdd28e5fc8b6fe50c6c79ec4`.
- Initial reviewer `/root/wp52_56_r5_design_review` returned
  `BLOCKED_WITH_FINDINGS` with no P0, three P1 findings, and no separate P2: the
  synchronized context had no accepted baseline witness; the reopened 1D rows changed
  objective and execution-profile inputs together; and the pre-freeze audit/workflow
  preimage were not retained in machine-reproducible form.
- Sole author revision: completed. It removes the infeasible synchronized contextual
  baseline, defines six exact atomic same-experiment pairs plus one absolute bounded
  oracle, reduces the only symmetric context to three accepted capacity pairs, makes
  the three 1D choices execution-owned single-axis experiments, retains audit JSON
  `7be497ea...`, and adds an exact reproducing workflow-preimage command.
- Revised R5 design payload SHA-256:
  `48317ec1dd32b353789695259dd39fb377cb96e18154ef96ace1f27a40437e3a`.
- Required reviewer: a fresh project-scoped `work_packet_verifier`, different from all
  earlier WP-52–56 design and implementation reviewers.
- The sole author revision is consumed. One focused recheck by the same reviewer is
  permitted. No implementation may resume unless the exact revised R5 payload reaches
  `DESIGN_VERIFIED`.
- Focused recheck: completed by `/root/wp52_56_r5_design_review` on 2026-08-12.
  Verdict: `BLOCKED_WITH_FINDINGS`, with no P0, one residual P1, and no P2. The revised
  identities, 54/111/29/82 counts, three capacity pairs, six atomic pairs, lifecycle
  split, comparator map, and execution-only 1D axes reproduced. The residual P1 is
  that the retained audit lacks executable prototype commands, accepted-artifact
  identities, complete row metric vectors for the numerical witnesses, and the
  enumerated/tie-broken `ARGMAX_BOUNDED` result; it also records merge wait as
  `4.0 -> 2.0 s` while the verifier replay produced `4.0 -> 0.0 s`.
- Mechanical closeout delta: only this verification record and the five packet
  independent-verification fields changed after verdict. The revised R5 payload,
  workflow, and audit bytes remain unchanged. The design did not reach
  `DESIGN_VERIFIED`; implementation remains prohibited and no third automatic R5 pass
  is permitted.

<!-- WP52-56-R6-DESIGN-PAYLOAD-BEGIN -->

## WP-52 through WP-56 numerical-remediation design R6

### Frozen originating request and revision boundary

> Continue

This request resumes the same combined WP-52 through WP-56 review unit after the R5
focused recheck. R6 inherits the original operator request, every durable requirement,
the accepted original/R2/R3/R4 design boundaries, the R5 workflow hardening, and all
R5 decisions not explicitly corrected below. It addresses the sole residual R5 P1 by
replacing prose-only numerical witnesses with a deterministic executable prototype,
complete metric and artifact records, a complete bounded-candidate enumeration, and
the corrected observed comparator outcomes. It does not grant feature-implementation,
runtime, production, qualification, or completion authority before this exact R6
payload passes independent design verification.

The R5 workflow additions `REQ-WFL-028` through `REQ-WFL-038` remain authoritative.
They already retain the learning from the repeated WP-52 through WP-56 revisions:
machine pre-draft audits, executable numerical witnesses, explicit comparator and
atomic-pair identities, fail-closed claims, exact preimage reconstruction, and served-
release UI evidence. R6 changes no workflow requirement.

### Authoritative executable numerical pre-freeze audit

The authoritative prototype command is:

```sh
./.venv/bin/python scripts/audit_wp52_56_r6_design.py --check
```

It must exit zero and print the internal audit SHA-256
`866261be59fa0651089f5450451e9a727f3526c8117da5d9b569353db25547ea`.
The script SHA-256 is
`e1fcfc5582fa8af6d217ce23c060a825e751ade24b3f08f698fbbeae088097da`.
Its byte-exact retained output is
`docs/work-packages/WP52_56_R6_NUMERICAL_PREDRAFT_AUDIT_2026-08-12.json`,
SHA-256
`43486bab53e0509fdaf7862ed814a2bc186812ec7e2d0f9e3555a60a2f636b89`.
The script and JSON are design evidence only; adding them does not modify a production
planner, compiler, service, qualifier, runtime, API, or UI path.

The JSON is the sole numerical authority where the following summary rounds values.
For every prototype it retains the exact case, submission and execution-profile
identities; plan, selected-candidate, certificate, trajectory-set, per-role trajectory,
independent-sample, observation, and capability-resolution hashes where applicable;
the complete frozen row metric vector with units, tolerances, values, and per-metric
evidence hashes; the exact relation clauses and result; and the source identities.
For the two earliest-release proposals it additionally retains every bounded candidate,
its cost, independent certificate and accepted observation, the exact argmin and tie-
break. For the two discrete 1D gates it retains dense sampled order/stop observations
and adverse reordered-traversal/interior-stop observations.
Regenerating into a temporary path and comparing bytes must be accepted as the
determinism check. A selected scalar, prose transcription, or partial vector may not
substitute for this artifact.

### Corrected exact classification and comparison relations

The executable prototype disproves one R5 collapse. Under the identical hash-bound
`overlap-capacity-v1` context, the exact contextual baseline for
`2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release` selects
`HORIZONTAL_DETOUR`, while the subject selects `GROUND_DELAY`; their complete vectors
and accepted artifacts differ. The proposal is therefore removed from `COLLAPSE_ALL`
and becomes a visible absolute timing relation:

```text
CAT(DS_MANEUVER=GROUND_DELAY),ARGMIN_BOUNDED(TM_RELEASE),
PASS(TM_OVERLAP>=2.0s for subject and comparator),
PASS(SP_CLEARANCE for subject and comparator)
```

The R6 partition is exactly 28 hidden collapses and 83 visible relations. The exact
28-key collapse set is the R5 29-key set minus only
`2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release`; every other R5
classification, exact comparator, metric set, threshold, and lifecycle decision is
unchanged. The R5 machine audit and the R6 `r6_classification_correction` object must
derive 54 rows, 111 unique proposals, 28 collapses, 83 relations, nine baseline-only
rows, two retain-existing-only rows, and five retained altitude profiles with no
duplicate or omitted proposal.

The other two capacity-context relations are retained, with corrected executable
witnesses and their complete vectors in the R6 artifact:

```text
2d.merge.canonical_nominal/merge.fair_release:
  MIN(TM_WAIT),PASS(TM_OVERLAP>=2.0s both),PASS(SP_CLEARANCE both)
  witness TM_WAIT 4.0 -> 0.0s; TM_OVERLAP 8.291237885002284 -> 12.291237885002284s

2d.perpendicular_crossing.nominal_equal_priority/crossing.earliest_equal_release:
  CAT(DS_MANEUVER=GROUND_DELAY),ARGMIN_BOUNDED(TM_RELEASE),
  PASS(TM_OVERLAP>=2.0s both),PASS(SP_CLEARANCE both)
  witness minimum accepted timing-only TM_RELEASE=4.525483399629593s
```

For head-on, all 16 generated/retained candidates are enumerated and the minimum
accepted timing-only release is `12.878060266375542 s`, selecting candidate
`4b58f90649bf145d5226192d413fc03388b73510f6a159e1bdfea0743943626c`.
For crossing, all 16 generated/retained candidates are enumerated and the minimum is
`4.525483399629593 s`, selecting
`cbd3bc0dfea31532c5b8927aedb14248eb42ff1e41d24ffd86dd0b70289f98f1`.
Both sets have `bounded_search_complete=true` and `truncated=false`. Equality uses an
exact `1e-12 s` tolerance; tied minima are ordered by the frozen subject-objective cost
vector and then candidate SHA-256. This is an absolute minimum within each exact
timing-only bounded candidate family, not a false claim that timing release precedes a
different-maneuver baseline. Delaying a subject beyond its frozen accepted minimum
fails the oracle.

All three capacity relation evaluations in the retained audit are true. These values
correct the R5 merge prose (`4.0 -> 2.0 s`) and prevent any later implementation from
choosing a different baseline, artifact, metric subset, or favorable comparator.

### Complete 1D execution-profile witnesses

The three R5 execution-owned, single-axis alternatives remain visible and keep their
R5 relations. Their exact complete vectors and artifact identities are frozen in the
R6 JSON. The independently reproduced distinguishing values are:

```text
waypoint.smoothness_first:
  SP_REFERENCE 0.05151287712880875 -> 0.0036967500461184606m
  DY_CURVATURE 14214.724114485505 -> 160.99521161255586 1/m
  TM_DURATION 18.071153416213505 -> 57.672354425667216s
  SP_CAPTURE=0 and DS_UNINTENDED_STOP_COUNT=0 on the subject

loop.curvature_continuity:
  SP_REFERENCE 0.07629210532315496 -> 0.003769942253084317m
  DY_CURVATURE 1050.0568912523079 -> 128.70429302695027 1/m
  SP_CAPTURE=0 with exact topology and authored lobe order preserved

curve.jerk_first:
  DY_JERK 1.9979284112899076 -> 0.9110964272093369m/s^3
  TM_DURATION 16.062993878978638 -> 20.88189204267223s
  SP_RADIAL and SP_REFERENCE deltas are each <=0.0001m; SP_CAPTURE=0
```

`DS_UNINTENDED_STOP_COUNT`, `DS_LOBE_ORDER`, and `DS_TOPOLOGY` in these prototype
vectors are not case metadata or constants. The independent `0.01 s` sampler applies
the case's exact `0.02 m/s` stop threshold and `0.20 s` persistence, observes ordered
region entry, and derives figure-eight topology only from the complete ordered lobe
traversal with all three center-checkpoint visits. The waypoint subject observation
has evidence hash `a417b60b...` and zero unintended stops; an inserted sampled interior
hold of `0.22 s` produces count one and rejected evidence `0a855501...`. The figure-
eight subject has evidence `6480e344...`, exact authored order and sampled topology
`figure_eight`; reversing sampled traversal produces `order_violation`, only the first
two ordered captures, and rejected evidence `32758cdd...`. Both counterexamples and
their complete observations/hashes are retained in the JSON.

All three complete relation evaluations in the retained audit are true. Qualification
still requires the R5 normal service/Fast-Sim/runtime, resampling, rename, incompatible-
case, and hard-gate evidence; a pre-freeze prototype is not runtime qualification.

### Frozen synchronized-pair and bounded-argmax dispositions

The executable audit compiles and independently certifies both members of each of the
six R5 synchronized atomic pairs under their identical frozen inputs. In every pair at
least one current member is blocked or rejected, so R6 freezes all twelve proposal
keys as visible `PLANNED_NOT_EXECUTABLE` and the six pair dispositions as
`BOTH_REMAIN_PLANNED_NOT_EXECUTABLE`. R6 does not authorize implementing or qualifying
one member alone, claiming a safe rejection from budget exhaustion, or replacing a
missing feasible witness with an assumption. Their exact bounded-search status,
blocking reason, retained candidates, and accepted observations where present are in
the R6 artifact. A later design may reopen a pair only with independently retained
feasible witnesses for both members.

`center.earliest_combined` remains visible
`OPEN(INCONCLUSIVE_MISSING_FEASIBLE_WITNESS)` / `PLANNED_NOT_EXECUTABLE` exactly as in
R5. `center.robust_combined` remains the one independently feasible absolute bounded
oracle. The R6 prototype generated and retained all 163 candidates under the frozen R2
bounds, reports `bounded_search_complete=true` and `truncated=false`, and independently
measures every accepted candidate. The maximum `SP_CLEARANCE` is
`0.010000000000000009 m`; equality uses an exact `1e-12 m` tie tolerance. Six candidate
hashes tie, and lexicographic SHA-256 tie-breaking selects
`08ef10cd30a72bdd0612c302f7d9446cf500c4a9e9b7e7e690dfa9f88af8b57a`.
The full 163-candidate family, each retained vector/artifact disposition, all six tied
hashes, and the selected observation are frozen in the R6 artifact. Qualification may
claim `ARGMAX_BOUNDED(SP_CLEARANCE)` only if production selects that exact result from
the complete family and also passes the inherited overlap and all-role-completion
hard gates.

### R6 implementation and exit boundary

Implementation may resume only after this exact payload is `DESIGN_VERIFIED`. It then
must implement the three 1D profiles, the three capacity-context relations, the 28/83
classification correction, and the robust-center bounded oracle through the shared
owning primitives and normal public production path. It must retain, visibly disable,
and truthfully explain the twelve atomic-pair proposals and `center.earliest_combined`
rather than fabricating executable evidence. All other inherited WP-52 through WP-56
implementation, perturbation, runtime, fleet, safety, evidence, API, UI, and served-
release gates remain mandatory.

Before implementation verification, the frozen numerical audit must replay byte-
exactly; all six profile/capacity relation evaluations must remain true; both complete
16-candidate release families must yield their frozen `ARGMIN_BOUNDED(TM_RELEASE)`
winner; the sampled stop and reorder counterexamples must fail their respective gates;
its 54/111/
28/83 partition and lifecycle counts must reproduce; all 163 robust-center candidates
must be retained without truncation and yield the frozen winner; each disabled atomic
pair must remain atomic; and every production/runtime/qualification claim must have
the evidence required by `REQ-WFL-028` through `REQ-WFL-038`. If production changes a
prototype value or identity legitimately, implementation must fail closed rather than
silently rewriting this design oracle; any substantive oracle change requires a new
design gate.

### R6 exact identities and reproducible preimage

- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Pre-R6 `ACTIVE.md` SHA-256:
  `4c4071276cb1f478294aadfc129cec880f61230c264e32a7a3238960447d1459`.
- R5 revised payload SHA-256:
  `48317ec1dd32b353789695259dd39fb377cb96e18154ef96ace1f27a40437e3a`.
- Workflow SHA-256:
  `b311bf74776d6c4e6b27af293357187d0883b38ded37a7d2a8f435b35f6faa34`.
- R5 pre-draft audit SHA-256:
  `7be497ea4faba9eddd3b220ef698a8a6834e38f0a12878233e3131a9cd5ff87a`.
- R6 prototype script and artifact SHA-256 values are the exact identities above.

The pre-R6 ledger is reconstructed by removing this R6 payload and its following R6
handoff through the line before `## Future mission-family application`, then restoring
the five packet verification fields from `DRAFT_UNVERIFIED` to
`BLOCKED_WITH_FINDINGS`. This exact command must reproduce the asserted preimage hash:

```sh
awk 'BEGIN{skip=0} /<!-- WP52-56-R6-DESIGN-PAYLOAD-BEGIN -->/{skip=1} /^## Future mission-family application/{skip=0} !skip{if (index($0,"| WP-5")==1) sub(/DRAFT_UNVERIFIED/,"BLOCKED_WITH_FINDINGS"); print}' docs/work-packages/ACTIVE.md | shasum -a 256
```

<!-- WP52-56-R6-DESIGN-PAYLOAD-END -->

### WP-52 through WP-56 numerical-remediation R6 design-review handoff

- Originating request: 2026-08-12 request to continue the WP-52 through WP-56 work.
- Review unit: combined accepted WP-52 through WP-56 design plus this R6 numerical
  correction; no feature implementation is included.
- Independent verification: `DESIGN_VERIFIED`.
- Initial design payload SHA-256:
  `88054ba0bb43d4d772cc8e28e4a3ec2dd1c56cc4d7f6f814a9fd7797d0db8b20`.
- Initial review: `/root/wp52_56_r6_design_review` returned
  `BLOCKED_WITH_FINDINGS` with no P0, two P1 findings, and no separate P2. The two
  earliest-release relations omitted `TM_RELEASE` and could accept later releases;
  the lobe-order/topology and unintended-stop results were copied from configuration
  or constants rather than independently sampled behavior.
- Sole author revision: completed. It freezes complete 16-candidate absolute release
  argmins for head-on and crossing, exact ties and winners, replaces the misleading
  reference-error clauses with `ARGMIN_BOUNDED(TM_RELEASE)`, derives order/topology/
  stops from dense trajectory samples, and retains meaningful reorder and stop
  counterexamples. No feature implementation is included.
- Revised design payload SHA-256:
  `6294fc5b7e246f300069313a6c1b9d23696018b5f50c390a37b82103a0a8cf93`.
- Required reviewer: a fresh project-scoped `work_packet_verifier`, different from all
  earlier WP-52 through WP-56 design and implementation reviewers.
- The sole author revision is consumed. One focused recheck by the same reviewer is
  completed; no third automatic R6 pass is permitted.
- Focused recheck: `/root/wp52_56_r6_design_review` returned `DESIGN_VERIFIED` on
  2026-08-12 with no P0/P1 regression or unresolved initial finding. It independently
  reproduced all revised identities, deterministic audit `866261be...`, both complete
  16-candidate release argmins, and the sample-derived stop/reorder counterexamples.

<!-- WP52-56-R7-DESIGN-PAYLOAD-BEGIN -->

## WP-52 through WP-56 phase-separated oracle correction R7

### Frozen request, cause, and narrow revision boundary

> Continue

This revision is required by the R6 implementation boundary itself. After the exact
R6 payload reached `DESIGN_VERIFIED`, implementation published the mandated
29-to-28 collapse correction and current R6 registry semantics. The command
`./.venv/bin/python scripts/audit_wp52_56_r6_design.py --check` then correctly reported
that the pre-draft artifact was stale because that historical prototype includes the
canonical pre-R6 registry identity. R6 nevertheless also required the command to
replay byte-for-byte before implementation review. Those two requirements cannot both
hold: the accepted registry change necessarily changes an input that the historical
artifact hashes.

R7 changes only this phase/identity contract. It inherits the original user request,
all accepted WP-52 through WP-56/R2/R3/R4/R5/R6 safety, numeric, comparator, runtime,
fleet, UI, counterexample, and completion gates. It does not change any proposal,
classification, metric, tolerance, candidate family, winner, context, lifecycle,
status disposition, runtime requirement, or claim boundary. Partially completed R6
production edits are paused at the exact preimages below; no further production edit
is authorized until this R7 payload is independently design-verified.

The reusable learning is recorded as `REQ-WFL-039`: historical pre-draft evidence and
post-implementation semantic replay have separate identities when the implementation
is required to replace a source hashed by the design artifact.

### Immutable historical oracle

The following evidence remains byte-identical and is never regenerated from the
post-R6 production tree:

- accepted R6 design payload SHA-256
  `6294fc5b7e246f300069313a6c1b9d23696018b5f50c390a37b82103a0a8cf93`;
- `scripts/audit_wp52_56_r6_design.py` SHA-256
  `e1fcfc5582fa8af6d217ce23c060a825e751ade24b3f08f698fbbeae088097da`;
- `docs/work-packages/WP52_56_R6_NUMERICAL_PREDRAFT_AUDIT_2026-08-12.json`
  SHA-256 `43486bab53e0509fdaf7862ed814a2bc186812ec7e2d0f9e3555a60a2f636b89`;
- internal R6 audit SHA-256
  `866261be59fa0651089f5450451e9a727f3526c8117da5d9b569353db25547ea`;
- every frozen case identity, metric set, unit, numeric value, tolerance, relation,
  context input, candidate-family cardinality, completeness/truncation result,
  selected candidate, tie set/tie-break, sampled stop/reorder counterexample, and
  atomic-pair disposition stored in that JSON.

The R6 JSON field that identifies the pre-R6 registry remains historical provenance;
it is not the expected current registry identity. The script and JSON hashes plus the
JSON internal hash are the implementation-gate integrity check. The earlier R6
reviewer's recorded successful byte replay proves the pre-draft generation. Running
the historical generator against required postimplementation inputs is deliberately
not a current-tree gate.

### Frozen postimplementation reconciliation contract

Implementation adds
`scripts/reconcile_wp52_56_r7_implementation.py` and retains its output at
`missions/campaigns/sim/qualification/wp52-56-r7-implementation-reconciliation-v1.json`.
Both paths are absent at this design preimage. The reconciler must:

1. verify the four immutable R6 identities above before measuring current behavior;
2. bind the exact current hashes of the registry generator, both generated registries,
   submission/compiler/planner/trajectory/measurement/service/runtime sources, the
   qualifier, tests, release, and every retained qualification artifact;
3. reproduce exactly 54 rows, 111 unique proposals, 28 hidden collapses, 83 visible
   relations, nine baseline-only rows, two retain-existing-only rows, five retained
   altitude profiles, three capacity-context keys, six atomic pairs, and no duplicate,
   omitted, or extra key;
4. execute the seven reopened R6 packages through the normal public service entry and
   independently sample their accepted trajectories. Every R6 metric is compared by
   metric ID and unit using its frozen per-metric tolerance; categorical/set values are
   exact. Missing/extra metrics, a changed relation, or a threshold relaxation fails;
5. retain all 16 head-on and all 16 crossing candidates without truncation and select
   the exact R6 release-argmin winners `4b58f90649bf145d5226192d413fc03388b73510f6a159e1bdfea0743943626c`
   and `cbd3bc0dfea31532c5b8927aedb14248eb42ff1e41d24ffd86dd0b70289f98f1`;
6. retain all 163 robust-center candidates without truncation, the exact six-way
   maximum-clearance tie, and winner
   `08ef10cd30a72bdd0612c302f7d9446cf500c4a9e9b7e7e690dfa9f88af8b57a`;
7. independently derive the zero-stop/authored-lobe observations from dense samples
   and prove the retained inserted-stop and reordered-traversal counterexamples fail;
8. prove every one of the 28 complete-vector collapses against its frozen comparator,
   every capacity/profile relation, all six atomic all-disabled pairs, the open center
   disposition, renamed/incompatible/backend/tamper/resampling/budget boundaries, and
   fail when a copied expected artifact is perturbed; and
9. report integration, production-entry, Fast-Sim, realtime, and rendered-UI evidence
   separately. It may set a boundary true only from the exact retained artifact that
   exercises that trigger; no preview or historical prototype upgrades runtime.

Implementation-owned identities expected to change are the generated registry and
admission hashes and the planning-submission, resolved-package, plan, trajectory,
capability-resolution, measurement, qualification, and release hashes derived from
the accepted R6 implementation. R7 permits replacement only for those listed identity
fields and requires their new exact hashes in the implementation manifest and
reconciliation artifact. It does not permit replacement of case/world/vehicle/backend
identity, numerical/categorical observations outside frozen tolerances, candidate
family or selected-candidate identity, comparison context, relation, or disposition.

`scripts/audit_wp52_56_r6_design.py --check` remains a pre-draft command and is removed
only from the postimplementation exit sequence. The implementation exit instead runs:

```sh
shasum -a 256 scripts/audit_wp52_56_r6_design.py \
  docs/work-packages/WP52_56_R6_NUMERICAL_PREDRAFT_AUDIT_2026-08-12.json
./.venv/bin/python scripts/reconcile_wp52_56_r7_implementation.py --check
```

All inherited R2 full accelerated/realtime runtime matrices, route-fidelity and energy
capability evidence, 1D/2D/3D dynamic/fleet exits, safety counterexamples, API/UI
presentation, exact served-release inspection, and fresh implementation verification
remain mandatory. R7 cannot be used to close a packet from the seven R6 integration
previews alone.

### Exact pre-R7 identities

- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Pre-R7 `ACTIVE.md` SHA-256:
  `632f12371b69f35d0af47e88165556dfce907827a66f6ca152e980d36c980e9d`.
- Workflow preimage SHA-256:
  `b311bf74776d6c4e6b27af293357187d0883b38ded37a7d2a8f435b35f6faa34`.
- Workflow postimage with `REQ-WFL-039` SHA-256:
  `f4d8bd19a5a4983bac5f0939412d6918d7ecf6089db34059a0b5e1ece9a8d6dc`.
- The workflow preimage is reconstructed byte-for-byte by removing exactly the new
  requirement row, R6 retrospective row, and feedback-change-log row:

```sh
awk '!/^\| `REQ-WFL-039` / && !/^\| WP-52 through WP-56 R6 implementation start / && !/^\| 2026-08-12 \| R6 implementation discovered / {print}' docs/project/WORKFLOW_AND_REQUIREMENTS.md | shasum -a 256
```

- Paused partial-implementation preimages:

```text
ee28fcbd08fa4221a100e5224219b217fce85b5aae2bdd68494197527d0b6c81  scripts/generate_submission_registry.py
51e16625e636b983fd54fe7f92599f23eece4f8b7bd938aef59644c19834acbd  missions/campaigns/sim/submissions/case-submissions-v1.yaml
c7ddb86102c63693d18c031e9498506df551b4eac7310b09d7c1a9e9b26d67dc  missions/campaigns/sim/submissions/admission-records-v1.yaml
97bf2b936ffab2b9424cacff6e270402fab232d2c8dec6996c09e1d23badc782  src/crazyswarm_app/campaign/submissions.py
337ac38968ac1a6bdaf71ce69de4a90b8946344f5aaa20d3bd29ae45fb3e2a47  src/crazyswarm_app/campaign/planner.py
00a846c86d637c73e36fb54528e76910b7696b2af30ad3302465bed9d3fc36bb  src/crazyswarm_app/campaign/submission_measurement.py
b76bbfd29a0b5f66b27ec0edbbe55ab9d8cb2d5658b76cd8093a5e9b8d01274b  scripts/qualify_submission_registry_r6.py
309f6078dd5f412f75a458de11715cdb4b429053a3d1a4c87edc0dc58728ee62  scripts/qualify_submission_registry.py
6b6b34c74ab6682d6da2128dfb7c8385254bccf535e4da9e70f33d13c9f45c9e  src/crazyswarm_app/campaign/qualification.py
ac2d085634f36dd1dcafb48197c282a466f9c3b564924b229fa4cba0c5aea7b8  missions/campaigns/sim/qualification/constraint-directed-planning-v1.json
e99803b2c2bdf6d4e3cf398da90d4a283b39b78051368f04c74186e1a81aa5d5  missions/campaigns/sim/qualification/selective-submission-registry-v1.json
4600c594812f6f9454ea1d686bef4d870f46de83aa9026043a60955892c06a75  tests/campaign/test_submissions.py
ABSENT  scripts/reconcile_wp52_56_r7_implementation.py
ABSENT  missions/campaigns/sim/qualification/wp52-56-r7-implementation-reconciliation-v1.json
ABSENT  scripts/qualify_submission_runtime.py
ABSENT  missions/campaigns/sim/qualification/selective-submission-runtime-v2.json
ABSENT  tests/campaign/test_submission_runtime_qualification.py
```

The pre-R7 ledger is reconstructed by removing this R7 payload and its following R7
handoff through the line before `## Future mission-family application`, then restoring
the five packet verification fields from `DRAFT_UNVERIFIED` to `DESIGN_VERIFIED`:

```sh
awk 'BEGIN{skip=0} /<!-- WP52-56-R7-DESIGN-PAYLOAD-BEGIN -->/{skip=1} /^## Future mission-family application/{skip=0} !skip{if (index($0,"| WP-5")==1) sub(/DRAFT_UNVERIFIED/,"DESIGN_VERIFIED"); print}' docs/work-packages/ACTIVE.md | shasum -a 256
```

<!-- WP52-56-R7-DESIGN-PAYLOAD-END -->

### WP-52 through WP-56 R7 design-review handoff

- Originating request: 2026-08-12 request to continue implementation of WP-52 through
  WP-56 and retain iteration learnings in the workflow.
- Review unit: the accepted combined WP-52 through WP-56/R2-R6 design plus this narrow
  phase-separated oracle correction.
- Independent verification: `DESIGN_VERIFIED`.
- Initial R7 design payload SHA-256:
  `3087915b0071453caad73d0d0f5c33a163fe2826f9513148b6f4787ed3b3abd0`.
- Initial review: `/root/wp52_56_r7_design_review` returned
  `BLOCKED_WITH_FINDINGS` with no P0, two P1 findings, and no separate P2. The
  workflow preimage lacked its exact reconstruction command, and the paused partial
  implementation manifest omitted the already-modified wrapper qualifier and R6
  submission test file.
- Sole author revision: completed. It adds the verified byte-exact workflow reverse
  command and freezes both omitted file hashes without changing the R7 semantic,
  runtime, safety, UI, or identity-classification contract.
- Revised R7 design payload SHA-256:
  `4a394f58ecda69b07fce919c009e090aacb20a9ef65bd44a3a7b794fb16ad0a5`.
- Required reviewer: a fresh project-scoped `work_packet_verifier`, different from all
  earlier WP-52 through WP-56 design and implementation reviewers.
- One author revision and one focused recheck by that same reviewer are permitted.
  The focused recheck is complete; no third automatic R7 pass is permitted.
- Focused recheck: `/root/wp52_56_r7_design_review` returned `DESIGN_VERIFIED` on
  2026-08-12 with no residual P0/P1/P2 finding. It reproduced the revised payload,
  both ledger/workflow preimages, both added paused-file hashes, and confirmed that
  the correction changes no numeric, semantic, runtime, safety, UI, or identity gate.

<!-- WP52-56-R8-DESIGN-PAYLOAD-BEGIN -->

## WP-52 through WP-56 relation-discriminability correction R8

### Origin, scope, and inherited contract

The operator asked to continue implementing WP-52 through WP-56 and to preserve the
knowledge from every repetition, revision, and iteration in the workflow so future
packet batches need fewer review loops. During R7 implementation, exact isolated
Fast-Sim repeats showed that two visible `EXECUTABLE` labels pass their hard runtime
gates but cannot satisfy their already-frozen distinguishing relations. R8 is a narrow
fail-closed correction for those two labels and a precise runtime-duration binding for
their two useful experiment peers. It inherits the accepted original/R2-R7 designs,
the originating operator request, every metric set and distinctness threshold, all
safety/runtime/capability/UI/evidence boundaries, the 54-row/111-proposal/28-hidden/
83-visible classification, and the nine/two lifecycle split. Nothing in R8 weakens a
case constraint or grants physical, live-Isaac, digital-twin, or hardware authority.

This exact payload cites and applies `REQ-WFL-028` through `REQ-WFL-041`. In particular,
new `REQ-WFL-041` records the reusable lesson from this implementation iteration: a
safe run and a changed hash are not evidence that a submission answers its causal
question. Every directional clause must reach the frozen distinctness threshold at the
evidence boundary named by the relation before the label is executable.

### Retained pre-draft relation and runtime audit

The exact pre-draft command is:

```sh
./.venv/bin/python scripts/audit_wp52_56_r8_design.py --check
```

The audit script and output hashes are frozen in the exact-identity section below. It
runs two exact case baselines and four subjects three times each: all 18 isolated rows
enter the normal public `CampaignService.run_active` Fast-Sim path and pass their hard
behavior/terminal gates. It retains every resolved-package, plan, schedule, trajectory,
artifact-set, evaluation, telemetry, and execution-bundle identity, plus independent
metric observations derived from those bundles rather than from the qualifier's
cross-vehicle numeric reducer.

Its machine overlay proves exactly 54 rows, 111 unique proposals, 28 hidden and 83
visible keys, lifecycle counts `43 SUBMISSIONS / 9 BASELINE_ONLY /
2 RETAIN_EXISTING_ONLY`, current statuses `25 EXECUTABLE / 86
PLANNED_NOT_EXECUTABLE`, and proposed statuses `23 EXECUTABLE / 88
PLANNED_NOT_EXECUTABLE` (`23 / 60` within the visible set). Every other key, relation,
comparator, metric set, visibility bit, and lifecycle stays unchanged. It also proves
that hidden `constrained.priority_order` remains `COLLAPSE_ALL` against the exact
visible `constrained.timing_makespan` peer, which qualifies independently first.

For `1d.takeoff_hover_land.canonical_nominal`, three-repeat medians are:

| Exact package | Source-time duration (s) | commanded-vs-observed vertical RMS (m) | contact settle (s) |
|---|---:|---:|---:|
| exact case baseline | 12.359999999999815 | 0.00399653157542231 | 0.09999999999999787 |
| `vertical_cycle.minimum_duration` | 11.303499999999827 | 0.005218052789311809 | 0.09999999999999787 |
| `vertical_cycle.precision_first` | 14.047499999999802 | 0.002959663067576934 | 0.09999999999999787 |

`vertical_cycle.minimum_duration` improves source-time duration by
`1.0564999999999873 s`, exceeding the frozen `0.10 s` distinctness minimum while
passing vertical tracking, capture, and terminal state. It remains executable.
`vertical_cycle.precision_first` is safe and longer, but its `0.0010368685078453758 m`
tracking improvement is inside the frozen `0.005 m` runtime equality band and its
settle timestamp is identical. Therefore its required
`MIN(DY_VERTICAL_TRACKING),MIN(TM_SETTLE)` clauses are inconclusive; a distinct plan,
trajectory, or duration cannot substitute for them.

For `3d.constrained_volume.canonical_nominal`, three-repeat source-time durations are
`62.9064501987774 s` for the exact baseline, `27.43731011659064 s` for
`constrained.timing_makespan`, and `62.9064501987774 s` for
`constrained.robust_schedule`. The makespan peer improves duration by
`35.469140082186755 s` and remains executable after its exact continuous release plan
passes clearance and all-role completion. Independently certified protected spatial
clearance is exactly `0.18994949366116665 m` for both the exact baseline and
`constrained.robust_schedule`. With timing-only maneuver authority, both routes have
the same endpoint-limited spatial clearance, so `MAX(SP_CLEARANCE)` is invariant under
the declared axis and cannot qualify that label.

The duration values above are the shared Fast-Sim `simulation_timestamp_s` interval
from the first retained child telemetry after admission through the last retained child
telemetry before `FLEET_TERMINAL(SUCCEEDED)`, including route-start delay. Every
`TASK_COMPLETED` role and the terminal fleet event are bound into the observation. This
is the source-time schedule/runtime interpretation already permitted by the R2
`TM_DURATION` definition and is mandatory for these two duration relations; neither
an arithmetic mean of vehicle durations nor accelerated coordinator wall time is a
fleet makespan oracle. `DY_VERTICAL_TRACKING` is independently recomputed over each
`execute_trajectory` command through its matching acknowledgement as RMS accepted-
trajectory `position_m.z` versus retained ground-truth `position_m.z`; localization
estimate-versus-truth error is not substituted. `SP_CLEARANCE` is read from the exact
plan-bound `independent-continuous-clearance-v1` certificate.

### Sole semantic correction

The proposal keys remain unique, visible, in their existing experiment, and keep their
full row metric sets. Only status/relation disposition changes as follows:

```text
1d.takeoff_hover_land.canonical_nominal/vertical_cycle.precision_first
  status: PLANNED_NOT_EXECUTABLE
  relation: OPEN(INCONCLUSIVE_RUNTIME_DELTA_BELOW_DISTINCTNESS)
  reason: DY_VERTICAL_TRACKING remains inside equality and TM_SETTLE is equal.

3d.constrained_volume.canonical_nominal/constrained.robust_schedule
  status: PLANNED_NOT_EXECUTABLE
  relation: OPEN(INCONCLUSIVE_AXIS_INVARIANT_METRIC)
  reason: timing-only authority cannot increase the frozen continuous spatial-clearance metric.
```

Neither disposition is a collapse or safe rejection, and neither issues a command.
The following peers remain visible and executable under their existing axes and hard
relations:

```text
1d.takeoff_hover_land.canonical_nominal/vertical_cycle.minimum_duration
  MIN_RUNTIME_SOURCE_TIME(TM_DURATION),PASS(DY_VERTICAL_TRACKING),
  PASS(SP_CAPTURE),PASS(DS_TERMINAL_STATE)

3d.constrained_volume.canonical_nominal/constrained.timing_makespan
  MIN_RUNTIME_SOURCE_TIME(TM_DURATION),CAT(DS_MANEUVER=timing),
  PASS(SP_CLEARANCE),SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})
```

`MIN_RUNTIME_SOURCE_TIME` does not add a metric; it fixes the already-declared
`TM_DURATION` observation boundary and requires three isolated accelerated repeats,
the median `0.10 s` distinctness threshold, and every repeat's hard gates. The exact
same-case baseline is the comparator. No implementation-selected peer is permitted.

The registry stays at 54 rows and 111 proposals, with 28 hidden and 83 visible keys.
Its visible execution-status inventory changes by two only; the two newly disabled
keys remain visible relations and do not become collapses. The generated registry,
literal admission record, API, UI, qualifier, and reconciliation artifact must all
round-trip these exact dispositions and reasons.

### Implementation and verification gates

After this exact R8 payload reaches `DESIGN_VERIFIED`, implementation must:

1. publish both disabled dispositions literally in the case-submission and admission
   sources, regenerate derived artifacts, and prove no omitted/duplicated key or
   lifecycle/count change;
2. remove any implementation-only robust-schedule candidate/objective branch that is
   unnecessary once the proposal is commandless; no dead special-case behavior may
   remain to make the label appear distinct;
3. retain three isolated accelerated baseline/subject repeats for both executable
   peers, compute source-time makespan from raw retained events, bind the exact plan,
   schedule, trajectory, package, evaluation, telemetry, and review hashes, and prove
   the frozen direction/threshold plus all hard clauses;
4. retain the two inconclusive counterexamples and mechanically fail if either is
   upgraded merely because a hash differs or a hard runtime gate passes;
5. update the R7 implementation reconciler without rewriting the immutable R6/R8
   pre-draft artifacts, then run the complete inherited runtime, realtime, dynamic,
   capability, safety, API, UI, and served-release exits; and
6. freeze one exact dirty-tree implementation manifest and submit it to a fresh
   project-scoped implementation verifier different from every design verifier.

All other R7 implementation work may resume only after this narrow design gate passes.
The normal one-revision/one-focused-recheck rule applies; unresolved P0/P1 findings
leave this batch blocked.

### Exact pre-R8 identities

- Base commit: `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Accepted R7 payload SHA-256:
  `4a394f58ecda69b07fce919c009e090aacb20a9ef65bd44a3a7b794fb16ad0a5`.
- Pre-R8 `ACTIVE.md` SHA-256:
  `df3ba0289f49baadc21eb0cd8520266407405c96e2aac414665845b561318b73`.
- Workflow preimage SHA-256:
  `a109648aa2cd1fb77e92fcf30424ee5e0fcc4e29b6084461383894a19f14be3f`.
- Workflow postimage containing `REQ-WFL-041` SHA-256:
  `ebb5b0a3201e03c5e544e73212023a31b3e05d165e4c2d34209c8e9076065972`.
- Exact paused implementation/source identities:

```text
51e16625e636b983fd54fe7f92599f23eece4f8b7bd938aef59644c19834acbd  missions/campaigns/sim/submissions/case-submissions-v1.yaml
c7ddb86102c63693d18c031e9498506df551b4eac7310b09d7c1a9e9b26d67dc  missions/campaigns/sim/submissions/admission-records-v1.yaml
b6749e62b3ff462d91cb7398eabce5f6d56b66b24f85e10884cde3eedeb3cf27  scripts/qualify_submission_runtime.py
4bed265f082def6902b6c08b86302285dfc93d45b4c46877e5fb5419866ce23c  src/crazyswarm_app/campaign/planner.py
4c374de8fb4bb653d3a8d3706687aaf4e51a3e384018ef83a086216657d9490b  src/crazyswarm_app/campaign/service.py
39b320d3a93064a751203b104ac64d4f013369e5b97df8e9b1b90d911c07dc08  src/crazyswarm_app/campaign/trajectory.py
a0b4efa108fbfe8626700425cef7d70f523b5a96ea94d1c2af9e9ed38e9ae6df  missions/campaigns/sim/qualification/wp52-56-r8-predraft-runtime-v1.json
ee28fcbd08fa4221a100e5224219b217fce85b5aae2bdd68494197527d0b6c81  scripts/generate_submission_registry.py
9b31d64b04037420b7c8e68420d2db44d4d09d9b8e3fcec1903c4dfee150f919  src/crazyswarm_app/campaign/submissions.py
00a846c86d637c73e36fb54528e76910b7696b2af30ad3302465bed9d3fc36bb  src/crazyswarm_app/campaign/submission_measurement.py
a8dc40466f897ef6e71bf176f9bed97cd33a3707df58e674cd291a73833853b9  scripts/reconcile_wp52_56_r7_implementation.py
cbe12d66444e61f818b05e374103b56ba5a7b504ca7def5a238dfb1b0429e85f  missions/campaigns/sim/qualification/wp52-56-r7-implementation-reconciliation-v1.json
456f9631194ab504ec40d3807f861003a9fe9ff22fefcc29b2a74efb90cf68a3  tests/campaign/test_submissions.py
1418efec0947dd9a86551c28bbda23009ba085e064f31eaf20f548ff76566bf8  tests/campaign/test_submission_runtime_qualification.py
1b9feaa199edeae7dc6b768cfc58b3cd4266334563dfdd94e9b9c8037cb52ecf  src/crazyswarm_app/api/app.py
06a8620e2c08512ab5e8b0d9d060bd29dc51fd0e358400a9dee0f6482165c39f  src/crazyswarm_app/campaign/api_models.py
7fd01f9ff49624502bf2d8c83d0a2de4ddf1bf200f528fa67d4dc5fe6ab792a4  ui/app/components/CampaignLab.tsx
5703e36b7cee0d448957bc69669c5622c045d4ba3e942fb120730de61f9e0a9e  ui/app/globals.css
7feb12cade8a83f426c1b2017a45ec4d33c28d1a8d0fac366de426ba1d7be29d  ui/app/lib/api.ts
be9c09ea870a4bcb00320b54bdc2a2b4dad46a8dc92490b38e28e28d2d3c3622  ui/app/lib/models.ts
a46bac04409c601eac5667657f4407046a15af6450cc1d780d27f75fa770b14f  ui/tests/campaign-lab.test.tsx
d22249523e4fc77036bbfbcd4e6b31a06f670a65d478cb0b7cf9487f6af45adc  scripts/audit_wp52_56_r8_design.py
58bb778ef1d82cefeff0ac83b2eda93c62d345d8fa4174c7a8651f9920027389  docs/work-packages/WP52_56_R8_RELATION_PREDRAFT_AUDIT_2026-08-12.json
```

The pre-R8 workflow is reconstructed by removing only the `REQ-WFL-041` row, the R8
retrospective row, and the R8 changelog row. The pre-R8 ledger is reconstructed by
removing this delimited payload and its review handoff, then restoring the five packet
verification fields from `DRAFT_UNVERIFIED` to `DESIGN_VERIFIED`.

<!-- WP52-56-R8-DESIGN-PAYLOAD-END -->

### WP-52 through WP-56 R8 design-review handoff

- Independent verification: `REVIEW_BLOCKED`.
- Initial R8 design payload SHA-256:
  `048adb208a56e9ab29c0f8016b913fcae4b3ddf981889216a9337e831ce22c93`.
- Initial review: `/root/wp52_56_r8_design_review` returned
  `BLOCKED_WITH_FINDINGS` with no P0, four P1 findings, and one P2. It found that the
  first artifact averaged vehicle durations instead of retaining fleet source-time
  makespan, substituted localization tracking for `DY_VERTICAL_TRACKING`, omitted
  certificate-bound `SP_CLEARANCE`, lacked a machine-audited proposed overlay, omitted
  relevant dirty-tree preimages, and described 18 rows as fifteen.
- Sole author revision: completed. It adds and freezes the executable 18-run R8 design
  audit, exact event/trajectory/certificate metric boundaries, the 23/88 status and
  28/83 visibility overlay, the dependent peer-collapse proof, corrected counts and
  measurements, and every relevant source/reconciler/API/UI/test preimage.
- Revised R8 design payload SHA-256:
  `80b66a7fd0786571b72f5b31ed248caa3fcb98864374316548ade817fe102578`.
- Required reviewer: a fresh project-scoped `work_packet_verifier`, different from all
  earlier WP-52 through WP-56 reviewers.
- One author revision and one focused recheck by that same reviewer are permitted.
- Focused recheck: `/root/wp52_56_r8_design_review` returned
  `BLOCKED_WITH_FINDINGS` with one residual P1. The corrected directional observations,
  two disabled dispositions, hashes, preimages, 18-run evidence, and overlay counts all
  reproduce, but the audit does not retain/evaluate every non-directional clause for
  the two surviving conjunctive relations. It hardcodes the aggregate hard-gate result,
  so maneuver and exact completion-set perturbations cannot break qualification and the
  dependent peer collapse lacks an independently qualified target.
- No third automatic R8 pass is permitted. No R8 implementation or status/relation
  publication is authorized; a new explicitly authorized design iteration is required.

## Future mission-family application

WP-44 through WP-50 establish the reusable separation between immutable problem truth,
case-bound planning authority, and execution profile. Later three-drone crossings and
formation/traffic cases should compose those qualified primitives and add only their
new joint scheduling, capacity, fairness, reservation, and atomic-authority questions.
They should not clone every strategy/profile combination or encode obstacles inside a
submission merely to reduce case count.

## Safety and claim boundary

This work may author configured routes, known static solids and traversable regions,
typed bounded source-time events, and deterministic Fast Sim fault overlays. It may
not weaken the global Safety
Supervisor, separation, volume, dynamics, freshness, authorization, evidence, or
terminal-state gates. The executor continues to use existing accepted program and
command authority; catalog metadata never directly commands a vehicle.

No package here authorizes physical Crazyflie discovery beyond existing safe software
boundaries, radio binding, props-on work, contained flight, live Isaac installation,
or `DIGITAL_TWIN`.

## Externally deferred work

The following work is not authorized by WP-35 through WP-50:

- NVIDIA/Isaac installation, live gateway execution, RTX host checks, or Isaac
  qualification.
- Crazyflie discovery beyond existing safe software boundaries, radio binding,
  props-off bench work, contained flight, multi-drone physical testing, or purchasing.
- Physical docking/charging, RF, contact, endurance, sensor, or prediction-accuracy
  claims.
- Enabling `DIGITAL_TWIN` or making a physical/high-fidelity backend the default.
- Perceived-object avoidance, mapping, SLAM, learned control, or camera reasoning.

These paths remain `EXTERNALLY_BLOCKED` until the operator has the required computer
or real aircraft and explicitly authorizes a separate gated work package. The existing
WP-25 handoff bundle grants no execution authority and records live Isaac and physical
work as `NOT_RUN`.

## Operator-review successor batch — smooth 1D reality, online replanning, and digital twin

This batch is the implementation successor to the completed 1D Campaign Lab runs and
their operator review. It does not retroactively change their immutable evidence. It
adds separate, executable contracts for motion quality, whole-route continuity,
changed-world replanning, motor-level physical truth, and a persistent real/sim digital
twin pipeline.

| Packet | Status | Independent verification |
|---|---|---|
| WP-57 — 1D retained-evidence truth and motion-quality contract | `PARTIALLY_IMPLEMENTED` | `BLOCKED_WITH_FINDINGS` |
| WP-58 — whole-route continuous flight and adaptive motion intent | `PARTIALLY_IMPLEMENTED` | `BLOCKED_WITH_FINDINGS` |
| WP-59 — one-drone sensor-sourced changed-world replanning | `PARTIALLY_IMPLEMENTED` | `BLOCKED_WITH_FINDINGS` |
| WP-60 — differential-actuation physical-reality evidence | `PARTIALLY_IMPLEMENTED` | `BLOCKED_WITH_FINDINGS` |
| WP-61 — persistent all-sensor digital twin and staged physical curriculum | `PARTIALLY_IMPLEMENTED` | `BLOCKED_WITH_FINDINGS` |

<!-- WP57-61-DESIGN-PAYLOAD-BEGIN -->

### Frozen originating request

The following is the exact operator request that originated this batch:

> - 1D
>   - Check all csv data for all done 1D missions, all data and photos and comments, the major points also noted in the comments are:
>   - for constant velocity having I dont know 95% or something not exceed the set limit is one measure if constant velocity is reached or not, another (additional) quality measure is also how shaky it is. now it remained constant velocity by making hard turns by keeping same motor speeds I believe and also therefore keeping on track. In return there are sudden velocity chackes which you can see from the IMU data. In the end it is a tradeoff of the velocity profile, acceleration and shakiness (based on mission requirements) and if you are allowed to leave paths or not like the first submission. Just be aware of that doffereence and have the capability to use them together and changing in flight based on mission requirements and changing conditions.
>   - Main bonus: make it run smoother, dont just plan to next nodge
>   - I notice how it slows down every corner, I guess this is also to fairly remain in path towards the required bound. also the same as for the other case it is a tradeoff between smoothness, velocity profile (does not matter, constant, ramped etc.) and how well it should stay on the path. but what I also noticed is that when the drone crossed the old path so basically where the node between the two paths of the figure 8 is that it slows down there as well. in that case it feels more generative and not clever that it only intentionally slows down at corners to remain on path but rather stupid you know. I will do a screenshot in run 2 to show you
>   - be aware that it stops slightly at every edge and then accelerates again, it does not move in a continous velocity movement, in the end it depends on the mission if I want continous movement or check point movement just be aware of the difference and have the capability to implement all of them or apply them based on later missions
>   - I noticed how it accelerates towards the end shortly before it foes down to land that is some weird behavior
>   - Also Reorder of missions hover and land is last right now
> - For 1 drone future
>   - If mission known based on the boundaries how far it can leave the track it should be very smooth like a real flying drone, no hesitancy or anything just flying smoothly
>   - The current missions are nice general designs but lack reality, pack them toegther for missions that can also be accessed for this behavior of smooth planning
>   - But I want you to enable a reality thing as well that includes mission replanning in real time (for one drone now), the current missions are all preplanned the drone knows exactly where it should go etc.
>   - I imagine that for example the drone has a goal e.g. it starts on one end and it has to go to the other and land there, or touch a wall or come close to it and then go back to base or something similiar to that, but then there are obstacles that are of course in the simulator simulated in there and lets say the drone has like computer vision or good sensing capabilities to sense that, so then if it e.g. blocks the direct path it has to go around it, above it, underneath it? those obstacles could be walls or rocks or whatever that block the path, not there from the beginning all at ones but like appearing before, lets say in a way that the drone has enough time to(realistically when sensors reacted and run through system to react to it), like one after another and then also disappearing again, of course not forever because the drone should arrive at some point but I want realistic missions that really test the path planning and live capabilities of the drone
> - Operation
>   - If drone moves forward doesnt the back drones have to spin faster to create more lift to lift the back up to move forward -> however all engines behave the same this is unrealistic no? > check especially all the csv and outputs for physical reality
> - Real drone as well with digital twin
>   - Implement pipeline with digital twin make everything ready, sensor connection and visualization as digital twin
>   - Start with very simple 1D tests startup and so on and then simple paths
>   - Do some test first for 1D, startup and slow hovering etc., goal is not only to test and same pipeline with me telling you what to improve and so on but also for you to read the data from all sensor and take that as real learning behavior of drone, improves with everytime flying, not overfitting as well
>
> structure wps, do the required iterations and then implement all the wps, you have my authroization to pass max 2 wps structurization iteration cycle and 2 cycles of iteration for implementation, look at workflow document for details, but you dont gave to use them so favoruably less
>
> commit and push current branch and start this iteration in a new branch

### Frozen development boundary and evidence

- Originating branch `codex/implement-wp26-34-campaign-lab` was committed at
  `7253a5d9457d8d55519eb025c880ee850a3d0e27` and pushed before this batch.
- Implementation branch: `codex/1d-replanning-digital-twin`.
- Base commit: `7253a5d9457d8d55519eb025c880ee850a3d0e27`.
- Retained Campaign workspace preimage SHA-256:
  `f26b155cbb8458650e4c2c9d70ff81a701da32a263b6f0112663b696e7c795d1`.
- Predraft evidence audit SHA-256:
  `5ee24c1382553e3168caa86825208c5c1cf116c3e6e412bcf3f2f4e7d95c0ada`;
  its canonical payload SHA-256 is
  `65f7243a5c7bf944570e6758a84dccc060882af8459c310fedb9356136bbea40`.
- Audit program SHA-256:
  `f2b1df6c4017dd3856ddfaf7f35e5b88baa87da8d2bfdc8bd1689417bd98efa8`.
- Human evidence synthesis SHA-256:
  `16f1ea6cab28078760c9108400be83352fcf7965c0950edda9dbe23b4f41f3e9`.
- Workflow postimage carrying `REQ-MOT-013` through `REQ-MOT-016`, `REQ-RPL-009`
  and `REQ-RPL-010`, and `REQ-XFR-005` through `REQ-XFR-008` SHA-256:
  `57676ec4ef8bcd673beb98a4dfc615817fb5b8de034494807e2a61726802cf21`.
- `COMPLETED.md` preimage SHA-256:
  `220a914b28ca7e736564a351457104c9b8b096185d3b38ac326cec6d0d57a062`.

The audit covers every retained done 1D review: 28 runs for 11 executed cases, every
CSV/analysis/evaluation/evidence bundle/manifest, eight comment-bearing reviews, and
both retained screenshots. It separately records four failed unreviewed altitude-run
records and the nine defined-not-run 1D cases. The exact same-clock comparisons expose
the trade: constant-speed circle reduces speed ripple from `0.306` to `0.052 m/s`, but
raises angular-rate p95 from `0.131` to `0.329 rad/s` and motor-spread p95 from `0.139`
to `0.470` percentage points. The realtime smooth-waypoint run reduces ripple from
`0.308` to `0.020 m/s`, acceleration p95 from `0.399` to `0.076 m/s^2`, and jerk p95
from approximately `0.895` to `0.478 m/s^3`, while angular rate, motor spread, and
tracking rise. Figure-eight crossover speed ratios are `0.725` and `0.773`. Twenty-six
of 28 reviewed runs contain unequal motor PWM in more than 95% of moving samples, so
the current Fast Sim already mixes differential actuation; the product currently
obscures its small magnitude. The revised literal terminal oracle finds one late-route
reacceleration peak in both curved-route comparator runs, with `0.151` and `0.107 m/s`
prominence. Neither current run passes the future zero-peak gate.

### Frozen numerical-oracle prototypes

The immutable audit's `oracle_prototypes` object contains the exact inputs and full
result vectors. Reproduce it with:

```bash
python scripts/audit_wp57_61_design.py --check \
  missions/campaigns/sim/qualification/wp57-61-predraft-1d-evidence-v1.json
```

- WP-57 terminal sampling uses final-authored-segment `0.10 s` source-clock medians.
  A rise strictly greater than `0.02 m/s` fails: the frozen `0.019` witness passes and
  the `0.021` perturbation fails. Both existing curved-route runs have one open peak.
- WP-58 witnesses make every threshold sensitive: knot ratios `0.90/0.80` bracket
  `0.85`; crossover ratios `0.97/0.94` bracket `0.95`; constant-speed samples produce
  `0.96/0.94` band coverage; jerk improvements `25%/19%` bracket `20%`; angular and
  motor-spread regressions `9%/11%` bracket `10%`; tracking deltas `0.009/0.011 m`
  bracket `0.01 m`; duration ratios `1.70/1.76` bracket `1.75`; and equivalent-route
  deviations `5e-7/1.1e-6 m` bracket `1e-6 m`. Planned-path comparison samples at
  `0.01 m` arc-length spacing; observed metrics use unique source sequence and the
  phase windows declared by WP-57.
- WP-60's independent X-layout witness fixes arm projection
  `0.046/sqrt(2) m`, thrusts `(0.065,0.075,0.075,0.065) N`, expected positive pitch
  torque `0.0006505382386916233 N·m`, and zero-rate angular acceleration
  `45.49218452388974 rad/s²`. Force/torque arithmetic uses `1e-9` absolute tolerance;
  motor/IMU samples pair one-to-one within `0.01 s` and the expected response sign must
  appear within `0.05 s`. A `0.02 s` shift fails.
- WP-61 ingestion admits at most 512 records and 1 MiB per request, 32 channels,
  `500 Hz` per channel, 4,096 buffered records, and one million records or 4 GiB per
  session. Overflow rejects the whole batch as retryable and never drops an accepted
  sample. Equal-key/equal-hash duplicates are idempotent; unequal hashes fail. Data is
  operator-owned with no automatic deletion in this batch.
- WP-61 calibration searches only mass scale `[0.85,1.15]`, linear-drag scale
  `[0.50,1.50]`, motor-time-constant scale `[0.75,1.25]`, and thrust scale
  `[0.85,1.15]`. The split freezes at least six whole sessions across two geometries:
  two training and one untouched holdout session per geometry, assigned by canonical
  session-hash rank before fitting. Promotion requires mean holdout position RMSE to
  improve both at least `10%` and `0.005 m`, altitude/velocity RMSE to regress no more
  than `5%`, every motion/safety guard to pass, three deterministic replay repeats,
  and explicit operator acceptance. Frozen pass/fail RMSE vectors are
  `(0.068,0.060)/(0.074,0.066) m` against `(0.080,0.070) m`.

Synthetic prototypes establish computability, feasibility, and sensitivity; they are
`MODEL_ONLY / NO_RUNTIME / NOT_APPLICABLE` and never qualify production behavior.

Relevant frozen production preimages are:

```text
31c3b5067972298b9dbd4a4dc026ff3b48de96685b253a9b22d48293eb71fdf0  src/crazyswarm_app/campaign/models.py
39b320d3a93064a751203b104ac64d4f013369e5b97df8e9b1b90d911c07dc08  src/crazyswarm_app/campaign/trajectory.py
c2e62b8411dc9f9938208e75adb3d5be7663263e57d0c9cb7ab4cda4c07c540a  src/crazyswarm_app/campaign/analyzer.py
8a80ff02979979affe6dc1cee9d4d0550430473d36de0a3fb5d1abffe0f054e9  src/crazyswarm_app/campaign/replanning.py
a6510c17f13a0f6d8b82ef450c2442b3271b32046932d6c6a7de245dba43e5bc  src/crazyswarm_app/campaign/execution_head.py
eff68869fcc5943adbc5d3b1e258f5304f213417121d9207f312b7d2bd5a3e38  src/crazyswarm_app/campaign/runtime_executor.py
3a9e3047ba587b0545413fb0b3564a0d774b54fd157e394fc9817e074bc23a00  src/crazyswarm_app/campaign/service.py
2111911ac0c36602cb660e1e01dc61f6fae10e691c7c4795a1270e577e974b2c  src/crazyswarm_app/campaign/catalog.py
d9c37b60d72a5d035bc07d8ad3ecfee3ed1f390aab61336de8807f1d9fe72ea1  src/crazyswarm_app/simulation/physics.py
4f5de2f3fbd8f4f769cfab34963ecb7e424e36543e0998559f99081b5c37d3d1  src/crazyswarm_app/twin/models.py
219894404160f2c726f402b3f92151b9c6702f906d3ea2c5f84ea004b9df6cbf  src/crazyswarm_app/twin/coordinator.py
7015952b033fcecaa1e36a9777ecc6c1373549fd96c3e4cc0a610a8e6d79a718  src/crazyswarm_app/api/app.py
ae78fa0502d73b28625e01df41364b9517237838b574ec28daf714eda151026e  src/crazyswarm_app/api/models.py
b257d952d3ac15bed827c862c7e9891ab005f31a18ca438474cc8c8e93064072  src/crazyswarm_app/api/runtime.py
3f0f39d058f79b3f088166c054c99bc5f79fb514d62691564429ca95a6613c11  ui/app/components/CampaignLab.tsx
9904f9462ac05f2924df48e54875089434a36814bbfb10d030baeb68ccaaa0fb  ui/app/components/ControlCenter.tsx
8597b063d755bcc1a26f7617ed3b9abc57430fcf717165b87814eb31cde5baf7  ui/app/components/TelemetryDock.tsx
7feb12cade8a83f426c1b2017a45ec4d33c28d1a8d0fac366de426ba1d7be29d  ui/app/lib/api.ts
be9c09ea870a4bcb00320b54bdc2a2b4dad46a8dc92490b38e28e28d2d3c3622  ui/app/lib/models.ts
5c02700b2638af8ae57223d6ee24418e592a56913ac6588a4ca24f3228d48af9  scripts/campaign_case_specs.py
715afda601bb517482cc868b5ae91b0e8a61e434702f31049fc3f39c2c5167a0  scripts/generate_campaign_catalog.py
04e950f5d2dea29a909bdc6639290b42caa6f95f1a9311737415bf7c742d12b1  config/qualification/reality-physical-plan-v1.json
c21508d64b1fdce2b1132151f47cc9ee10e836eeb58846c863bffab75c323b2d  design.md (pre-revision)
27dfe90670911c535ba8a54a24d8e43003788933acc54e8ae9a26b37fdcf797f  docs/project/DESIGN.md (pre-revision)
a765b02a017c9b246818d1b530f78b75b4d3ddede9a3b5beef19c0d80722fdf6  design.md (reviewed UI postimage)
04baa1fe5db91d5702df04b7531835f6f01a09e45e1e4ffcaac4d0df093579ea  docs/project/DESIGN.md (reviewed UI postimage)
```

The implementation manifest must freeze full SHA-256 preimages and postimages for
every changed or relied-upon file.

The following additional boundaries were found during independent production-path
tracing. `IMPLEMENTATION_OWNED` permits an in-scope edit; `RELIED_UPON_UNCHANGED`
means the implementation must preserve the boundary or promote it into the changed
manifest with a postimage and tests.

```text
4bed265f082def6902b6c08b86302285dfc93d45b4c46877e5fb5419866ce23c  IMPLEMENTATION_OWNED  src/crazyswarm_app/campaign/planner.py
9b31d64b04037420b7c8e68420d2db44d4d09d9b8e3fcec1903c4dfee150f919  IMPLEMENTATION_OWNED  src/crazyswarm_app/campaign/submissions.py
d6d7b335dbe97633badab7245a5cd21862c0eb5c52e9f981f4a1192afb997f16  IMPLEMENTATION_OWNED  src/crazyswarm_app/campaign/execution.py
c7e3ddeee88b235551ba2c31c639ef73da0edddfc46eb94cd5a83c24d96ef221  IMPLEMENTATION_OWNED  src/crazyswarm_app/campaign/scenario.py
f011ece2306fb5a2505818eb7dac8771a21bb72a6dffc62a8f3bcb9c30d21802  IMPLEMENTATION_OWNED  src/crazyswarm_app/campaign/geometry.py
32c235cd9b6b2212e030a7c25f4e1d7692988a0ca0f0a416abcf447abae6f446  IMPLEMENTATION_OWNED  src/crazyswarm_app/domain/trajectory.py
741a4aa9cc4a405588960eece156b82e85348bf124e61fcb16f66ebb97376f99  IMPLEMENTATION_OWNED  src/crazyswarm_app/domain/telemetry.py
5a9c4df5b8b00a4e63835bcede4b695e3cca760d4fed7965eaa95aa781d13c5d  IMPLEMENTATION_OWNED  src/crazyswarm_app/simulation/world.py
b49dd4a9a594b25201b89c3e45300e8299a8d9fe9cd667a087f1e989bc7fcba6  IMPLEMENTATION_OWNED  src/crazyswarm_app/simulation/sensors.py
c40f660b35e12b5cc01c5aa76d02f9afc2b7fc28c9b1eb6948963518f16c71e3  IMPLEMENTATION_OWNED  src/crazyswarm_app/simulation/vehicle.py
aa3e3abc76751e4f840145500c50dc419867a0120de53dfe3c9d0223a50dc689  IMPLEMENTATION_OWNED  src/crazyswarm_app/observability/storage.py
496bb5cab3c7ad68ebe082b22ab6c1aa2abcc78be07ea3f1b55af778aec845bb  IMPLEMENTATION_OWNED  src/crazyswarm_app/observability/replay.py
f94e6ad3da7a1024e316615c1ce565f19a67223f1fe3517e480dd397513b7f46  IMPLEMENTATION_OWNED  src/crazyswarm_app/observability/evaluation.py
1996e53bd87f97a7da6c1ebf946dfb27c1268247853572d927cfc6dd95786c0b  IMPLEMENTATION_OWNED  src/crazyswarm_app/vehicles/providers.py
e7ea1b9080c00c7ac4622fd440ecff373f62f8b8afed3750a639a299545ee5f0  IMPLEMENTATION_OWNED  src/crazyswarm_app/vehicles/crazyflie.py
cb101bcc2056db0a6d013f30eee790c46c16f8d467aa534919b2cfc11d6eaf5c  IMPLEMENTATION_OWNED  src/crazyswarm_app/hardware/models.py
7a7ee3d4730533fa7674b5a5d30d6b9fd8a3781db8e9470bf42097f0385634cc  IMPLEMENTATION_OWNED  src/crazyswarm_app/qualification/physical.py
bad9b04a5cc87bb9372840f016fe405815f1368f47332cdc94377f64458ed68b  RELIED_UPON_UNCHANGED src/crazyswarm_app/safety/supervisor.py
63c65e5b852cef9e7913426cec4c7a52b439066374e86bb9da1524429b3a8d05  IMPLEMENTATION_OWNED  ui/app/components/RoomScene.tsx
10a71f64d8081cc9d902709baf9a6cb75834cc7a29b3ced085c2ab2601249204  IMPLEMENTATION_OWNED  ui/app/lib/campaign-telemetry.ts
38e9e8d533591aa08d3458e69fcb2845b07fec472ea66536a23984a32a99ccb1  IMPLEMENTATION_OWNED  ui/app/globals.css
b290012068ba02d70c9dacb7cf22ac90112471b2fe59495c7481c326cd72a576  GENERATED_POSTIMAGE ui/app/lib/api.generated.ts
```

Existing tests are relied-upon regressions with preimages
`c7d8b414e8613fc84d85b777ffb17100d31c5e916a0cc74b40ceba23c893cdc3`
(`test_campaign_lab.py`),
`f1fd0ba50a3671a5a6b8bb526f06c6bfc4ae8ae51df1c0c6030304ae51ff91ad`
(`test_campaign_execution.py`),
`d0197febfc23dea476ea2a101c49702c7ba1b4de6e8bacfd7aa08e751bb7c34d`
(`test_dynamic_replanning.py`),
`90c19cf5e15a3e902854a112341303507ef40064b816ebd363ec4b7a22f20410`
(`test_coordinator.py`),
`3778eb46126969b2450b15cbab2887fe745acbc7fceb20bebfade725d907246b`
(`test_physics.py`),
`f0adf8b5ce2eb5d1b81e0d450788c73e30df7a16748211a2288be5b5d80fc26c`
(`test_physical_fidelity_v2.py`),
`4306aaecf0ef1b7dd66188e15915d70574dce16f1e95f82aa876409b2b9315ec`
(`test_contract.py`), and
`1d493eddb1c2ee71b1e1f293f316d4e469066bc0ab1a381ed907a03dccd6a7c8`
(`campaign-lab.test.tsx`). New packet-specific tests named in the child matrix are
implementation-owned new files.

### Shared intent, authority, and dependency order

The minimum useful release is a one-drone Fast Sim path that selects an explicit
motion contract, flies the entire known route continuously without artificial knot
hesitation, responds to delayed sensor observations of appearing/moving/disappearing
obstacles by dispatching a changed-world replacement, lands, and exposes route,
motion-quality, per-motor, perception, replan, and digital-twin evidence. Explicitly
requested extras are persistent sensor ingestion and a staged physical-test handoff.
Optional follow-ons are wall-touch behavior, below-obstacle route variants, live
camera perception, and learned control; they are not required to close this batch.

“Make everything ready” authorizes software, schemas, local persistence, simulator
sensor adapters, UI, qualification fixtures, and fail-closed physical handoff. It does
not authorize radio discovery, props-on operation, a real takeoff, or promotion of a
learned calibration without operator acceptance. All physical stages remain `NOT_RUN`
until their existing gates and separate operator phrases are satisfied.

Dependency order is WP-57, WP-58, WP-59, WP-60, then WP-61. WP-60 may run its oracle
alongside other implementation work but cannot weaken physics merely to match a
visual expectation. Each packet preserves source-clock ordering, immutable evidence,
accepted-program authority, the Safety Supervisor, and the declared volume, tracking,
dynamics, terminal-state, and no-command gates. A metric hash or prettier UI is never
proof of behavior.

WP-58, WP-59, and WP-61 are parent packets. Their lettered sub-packets are mandatory
implementation and evidence checkpoints, not optional notes and not separately
claimable completed work. A parent stays active until every child exit passes and the
parent end-to-end counterexample passes. The author must reconcile each child before
starting its dependent child so an early modeling defect is not hidden by later UI or
qualification work.

### WP-57 — retained-evidence truth and motion-quality contract

**Status:** `PARTIALLY_IMPLEMENTED`

**Independent verification:** `BLOCKED_WITH_FINDINGS`

Implement a typed `MotionQualityContract` carried by case intent, accepted plan,
trajectory, evidence, analysis, review bundle, and UI. It must keep separate objective
and hard-guard fields for speed compliance, speed ripple, acceleration, jerk,
angular-rate shakiness, motor differential/spread, path-tube tracking, waypoint mode,
terminal behavior, saturation, and duration. No aggregate score may hide a guard.
Profiles include `CHECKPOINT` and `CONTINUOUS_FLY_THROUGH`; cases may choose constant,
ramped, precision-first, or balanced objectives and an in-flight event may replace the
contract only through a source-time, hash-bound accepted-program amendment.

Add raw-CSV analyzers for terminal descent onset, landing handoff, speed peaks,
reversals, acceleration, angular rate, and per-motor deltas. The reported terminal
surge passes only when the literal last approach has zero unintended reversals and no
secondary speed peak exceeding `0.02 m/s` above the contract envelope. Add a motor
truth view showing individual PWM/thrust plus deltas rather than visually rounding all
four motors to equality. Reorder the 1D curriculum so
`1d.takeoff_hover_land.canonical_nominal` is first overall in the 1D Catalog—not last—
followed by point-to-point, move-return, altitude-transition, continuous-waypoint,
curved-route, planar-loop, boundary-constrained, static-multi-goal, then the dynamic
families. Variations retain deterministic authored order. A frozen family-order field
drives presentation only; prerequisite metadata—not array position or family order—
controls eligibility. Tests must reorder the source array without changing eligibility
and must assert the exact operator-facing progression.

Required counterexamples: a trace with constant scalar speed but an angular-rate spike
must fail shakiness; a smooth trace outside the path tube must fail tracking; a terminal
speed spike must fail the terminal oracle; and descriptive-only contract edits must
not change execution semantics.

### WP-58 — whole-route continuous flight and adaptive motion intent

**Status:** `PARTIALLY_IMPLEMENTED`

**Independent verification:** `BLOCKED_WITH_FINDINGS`

Replace one-next-node velocity assignment with a bounded whole-route or receding-
horizon trajectory pass that reasons over all remaining nodes, node modes, curvature,
path tube, dynamics, landing handoff, and the active motion contract. It must preserve
intentional checkpoint capture while avoiding slowdowns at collinear nodes, arbitrary
resampling points, and the non-turning figure-eight crossover. Known boundaries may
be used to trade tube margin for smoother curvature; safety guards remain hard.

For a qualified continuous case: every non-terminal fly-through knot has speed ratio
at least `0.85` to its adjacent segment target, and repeated geometric crossover
visits have ratio at least `0.95` unless a declared conflict or checkpoint applies.
For constant-speed contracts at least 95% of cruise samples lie within target
`±0.05 m/s` and p95-minus-p05 speed is at most `0.05 m/s`. Planned integrated squared
jerk improves at least 20% over the exact same-case baseline. Observed jerk may not
regress; angular-rate and motor-spread p95 may be at most 10% above baseline; RMS
tracking stays inside its tube and no more than `0.01 m` worse; saturation, safety,
and terminal gates pass; nominal duration is at most `1.75x` baseline unless the case
explicitly selects a slow profile. Equivalent route simplification/resampling must
change the sampled path by at most `1e-6 m` and preserve the verdict.

An authenticated in-flight motion-intent change must take effect once, after its source
timestamp, and produce a new hash-bound suffix; stale, duplicate, or unsafe changes
are rejected without partially changing the active trajectory.

#### WP-58 sub-packets and stop conditions

| Child | Depends on | Required artifact and exit |
|---|---|---|
| WP-58A — baseline and route-semantics freeze | WP-57 | Immutable same-case baselines, node-mode classification, crossover identity, route-equivalence fixtures, and source-time metric oracle reproduce from retained evidence |
| WP-58B — route normalization and horizon model | WP-58A | A canonical route/horizon preserves capture, intentional reversal, landing, tube, and obstacle semantics while removing only dynamically irrelevant sampling knots; rename/reorder/density perturbations preserve meaning |
| WP-58C — bounded whole-route smoother | WP-58B | Planner/trajectory output satisfies dynamics and path tube, optimizes the declared vector without collapsing guards, and passes checkpoint plus continuous child cases |
| WP-58D — atomic adaptive suffix | WP-58C | A source-time motion-contract event creates one validated replacement suffix with old/new lineage; stale, duplicate, unsafe, and partially applied events fail |
| WP-58E — production integration and qualification | WP-58D | Accepted plan, executor, evidence, analyzer, replay, API, served UI, and exact Fast Sim baseline/subject matrix round-trip the contract and meet every parent numeric gate |

WP-58A may not infer an unobserved terminal phenomenon from aggregate metrics. WP-58B
must distinguish a repeated coordinate from a repeated path-state: the figure-eight
crossover may share position while having different tangent and progress. WP-58C must
retain checkpoint behavior as a control case; making everything fly-through is a
failure. WP-58D must use the existing accepted-program replacement authority instead
of mutating an active trajectory in place. WP-58E must retain both planned and observed
metrics because an analytically smooth curve can still produce a shaky simulated
response. Any failed child blocks later children; it does not lower the parent gate.

### WP-59 — one-drone sensor-sourced changed-world replanning

**Status:** `PARTIALLY_IMPLEMENTED`

**Independent verification:** `BLOCKED_WITH_FINDINGS`

Generalize the production in-flight replanning coordinator and execution head from
the current two/three-drone restriction to one through three drones. Add one successor
reality case whose initial accepted plan contains only start, goal, permitted volume,
and initially perceived solids. Obstacles are injected into simulator world truth in
a deterministic appearing/moving/disappearing sequence but are absent from the
initial plan. A delayed simulated range/depth perception adapter emits source-timed,
bounded observations after realistic latency. Only those observations may change the
planner world model.

The production executor—not a planner-only demo—must show accepted program dispatch,
perception receipt, changed-world proposal, validation, atomic replacement dispatch,
continued flight, and terminal landing. Each replacement must avoid all currently
observed solids with the required clearance, preserve the Safety Supervisor and
accepted-authority chain, and arrive within the case deadline. A timely obstacle must
produce a nontrivial detour; removal may shorten only future motion; a late obstacle
inside the reaction horizon must cause bounded hold/abort rather than an impossible
turn. A hidden future obstacle may not influence an earlier route or evidence hash.
At least one alternate seeded sequence and an event reordering test must preserve
causal behavior without requiring byte-identical geometry.

The exact production trigger remains `POST /api/v1/campaign/runs`, followed by
`CampaignService` → `CampaignRuntimeExecutor` → `CampaignExecutionHead`. The runtime
executor passes a new bounded `PerceptionObservationSource` to the head. Simulator
world-truth events are consumed only by `simulation/world.py` and the new range/depth
adapter in `simulation/sensors.py`; the head no longer reads an authored obstacle
region or converts a `ScenarioEvent` directly. It waits for a typed observation whose
mission/run/vehicle, sensor/configuration, world revision, sequence, source/receive
clock, latency, confidence, region/extent, and raw hash are valid. That observation is
persisted in telemetry/evidence before it can revise planner world state.

Before any cutover, an independent `ChangedWorldSafetyMonitor` derives a hash-bound
`SafePrefixCertificate` from the active accepted trajectory, the latest vehicle
observation, the perceived-world revision, braking/hold dynamics, clearance, and
freshness. `commit_changed_world_replacement` accepts this certificate—not a caller
boolean—and verifies its epoch/world/trajectory identities. The certificate supplies
the safe-until source time and one exact fallback: `STOP_AND_HOLD` when the bounded
stopping/hold envelope is clear, or `ABORT_AND_LAND` only when a separately certified
route to the already accepted landing region exists. The Supervisor command,
acknowledgement, stopped/landed observation, certificate, and disposition are retained.
If neither fallback is certified, the head requests the existing Supervisor emergency
policy and records `UNQUALIFIED_EMERGENCY_FALLBACK`; it may not call the case complete.
Perturbations that set a caller `old_epoch_still_safe`, leak authored future geometry,
tamper the sensor hash/world revision, shift source time, or remove the fallback
acknowledgement must produce zero replacement dispatch.

#### WP-59 sub-packets and stop conditions

| Child | Depends on | Required artifact and exit |
|---|---|---|
| WP-59A — changed-world and perception contract | WP-58E | Typed world-truth event, sensor observation, confidence/extent, source/receive time, latency, expiry, raw hash, and planner-world revision schemas; future truth is excluded from the accepted initial plan and hash |
| WP-59B — deterministic world and sensor simulator | WP-59A | Simulator injects appear/move/disappear truth independently of the planner and emits delayed/noisy bounded observations through `PerceptionObservationSource`; authored geometry cannot enter the head |
| WP-59C — one-drone coordinator authority | WP-59B | Existing execution head/coordinator accepts one vehicle, consumes persisted observation revisions, proposes a changed-world suffix, validates it, and atomically dispatches it with no two/three-drone regression |
| WP-59D — bounded detour and reaction fallback | WP-59C | Around/above route candidates use observed free volume and current vehicle state; `SafePrefixCertificate` replaces the caller boolean and authorizes exact hold/abort commands for infeasible/late cases |
| WP-59E — reality mission and end-to-end evidence | WP-59D | New successor case runs through production service/executor with at least two sequential obstacles, one disappearance, arrival/landing, UI timeline, retained replay, alternate seed, and causal perturbations |

WP-59A must define three distinct states—world truth, perceived world, and planner
world—and the evidence hash for each transition. WP-59B may expose deterministic test
controls but may not call the planner directly. WP-59C must preserve proposal and
accepted-program identity across replacement and reject an observation for the wrong
mission, vehicle, clock window, or prior world revision. WP-59D first implements
bounded geometric sensing/planning, not camera semantics or learned perception; an
“under” option is admitted only when vehicle, floor, obstacle, and clearance geometry
make it safe. WP-59E must prove no command used future obstacle truth before its
observation and must include a child run where the direct path remains clear so the
system does not detour gratuitously.

### WP-60 — differential-actuation physical-reality evidence

**Status:** `PARTIALLY_IMPLEMENTED`

**Independent verification:** `BLOCKED_WITH_FINDINGS`

Audit every retained moving 1D CSV at motor level and add an independent rigid-body
force/torque oracle for the X-layout mixer. For forward acceleration the oracle must
derive the expected sign of pitch torque and the corresponding front/rear thrust
differential from geometry and frame conventions; yaw and lateral child cases must
exercise other mixer axes. It must compare commanded motor PWM, mapped thrust,
resulting body torque/angular acceleration, IMU response, and vehicle acceleration at
source-aligned timestamps. Equal values after UI rounding do not count as equal raw
actuation.

Production physics is changed only if this independent oracle fails. Passing existing
physics results in evidence/UI repair, not an invented imbalance. Counterexamples must
fail for swapped front/rear motor mapping, all-equal moving PWM, sign reversal, source-
time shift, and saturated motors. The claim remains Fast Sim physical consistency, not
validated Crazyflie aerodynamics.

### WP-61 — persistent all-sensor digital twin and staged physical curriculum

**Status:** `PARTIALLY_IMPLEMENTED`

**Independent verification:** `BLOCKED_WITH_FINDINGS`

Replace the ephemeral twin summary with a persistent, source-aligned stream accepting
all adapter-provided sensor and actuator samples, including pose, velocity, attitude,
IMU, battery, individual motors, estimator health, perception observations, command,
plan/replan identity, and safety state. Define explicit availability/quality markers;
missing sensors are never fabricated. Persist sessions, calibration version, source
timestamps, receive timestamps, raw sample hashes, predicted values, residuals, and
review links. Provide bounded ingestion, session/list/detail/timeline APIs, restart-
safe replay, and a served UI that overlays actual/predicted paths and graphs selectable
sensor, motor, residual, obstacle, and replan channels with source/age/quality labels.
The exact request/channel/buffer/session limits, no-drop rejection policy, retention,
and duplicate rule are the frozen WP-61 prototype above; accepted records are atomic.

Create simulator-backed stages for startup/props-off-equivalent, slow takeoff, hover,
land, straight 1D, checkpoint, continuous path, and online-obstacle mission. Reuse the
same schemas and analysis path for a real adapter. Existing physical gates remain
fail-closed and real stages remain `NOT_RUN`; no generated artifact may claim an actual
flight. Learning is bounded calibration: candidate parameters are trained from accepted
sessions, evaluated against untouched holdouts, retain at least three sessions across
two geometries, and are promoted only after improvement on the named residual without
regression of safety/motion guards and explicit operator acceptance. The stronger
qualification exit uses the frozen six-session/two-geometry whole-session split,
bounded four-parameter family, position-RMSE improvement thresholds, secondary RMSE
guards, and three-repeat policy above; three sessions alone may create a candidate but
cannot promote it. Rejected and
superseded calibrations remain auditable; automatic online control-policy learning is
out of scope.

Restart, duplicate, late, stale, missing-channel, out-of-order, corrupted-hash, and
holdout-leakage counterexamples must fail closed. The UI must remain truthful when only
Fast Sim data exists and must never label it real-flight or physical qualification.

#### WP-61 sub-packets and stop conditions

| Child | Depends on | Required artifact and exit |
|---|---|---|
| WP-61A — twin identity and durable session store | WP-60 and WP-59E | Versioned vehicle/twin/session/channel/sample schemas, atomic append, content hashes, indexes, lifecycle, restart recovery, and retention policy persist without fabricating unavailable channels |
| WP-61B — common sensor/actuator ingestion boundary | WP-61A | Fast Sim and real-adapter-shaped producers use one bounded ingestion contract with source/receive clocks, sequence, availability, units, frame, calibration, quality, and duplicate/out-of-order policy |
| WP-61C — prediction, residual, and replay engine | WP-61B | Source-aligned raw/predicted samples and residuals replay deterministically after restart; missing, stale, frame-mismatched, or hash-corrupt inputs are marked/rejected rather than interpolated into truth |
| WP-61D — operator API and served visualization | WP-61C | Session/list/detail/timeline endpoints plus actual/predicted path overlay, selectable sensor/motor/residual/obstacle/replan graphs, time cursor, age/quality labels, empty/error states, and immutable review links satisfy `design.md` |
| WP-61E — staged 1D twin curriculum | WP-61D | Simulator stages for startup, slow takeoff, hover, landing, straight path, checkpoint, continuous flight, and online obstacle replan share the production ingestion/analysis path and record stage prerequisites/results |
| WP-61F — bounded calibration and holdout promotion | WP-61E | Versioned candidate trained from accepted sessions, frozen split with at least three sessions and two geometries, untouched holdout oracle, guard-vector regression check, rejection lineage, and explicit operator promotion |
| WP-61G — physical-adapter readiness handoff | WP-61F | Existing props-off/entry/contained-flight gates consume the common schemas; disconnect, stale telemetry, bad units/frame, and partial-sensor tests fail closed; all real executions remain literal `NOT_RUN` |

WP-61A is local and restart-safe; process memory is only a cache. WP-61B preserves raw
adapter payload identity alongside normalized values so conversion errors remain
auditable. WP-61C separates prediction from measurement and never backfills a missing
measurement with a prediction. WP-61D uses the existing Control Center/Campaign Lab
surface hierarchy; any durable new graph/timeline pattern must be reflected in
`design.md`. WP-61E is the same pipeline that WP-61G will later use, not a parallel
demo. WP-61F cannot train and test on segments from the same session when that leaks
the flight identity; it must report the frozen split and compare the promoted version
to its predecessor. WP-61G makes connection and visualization ready but cannot open a
radio or issue a physical command in this batch.

### Frozen user-interface and rendered-release exit

The existing hierarchy is authoritative: the mission selector's `Digital twin` mode
sets context; `RoomScene` overlays actual cyan and predicted orange paths with planned
grey/dashed and replay violet; the expanded Essential flight readout's `Evidence`
disclosure owns the active-session summary; and Campaign Lab `Review` owns retained
run/session comparison and immutable links. The implementation may add a full timeline
inside those surfaces but may not create a competing dashboard shell. Outcome,
actual/predicted path, and primary residual appear first; provenance, hashes, frames,
calibration, and timing remain in a closed evidence disclosure. One keyboard-operable
source-time cursor controls sensor, per-motor, residual, obstacle, and replan graphs.
Every graph has units, a source/quality/age label, a visible expand/collapse control,
and a text-equivalent ordered summary. Missing data is never drawn as a prediction.

Rendered qualification first binds the production-served UI release directory/current
pointer, API process/base URL, build manifest and changed asset hashes, then exercises
the real API. Retain desktop and narrow screenshots plus accessibility assertions for:
loading; empty; simulator-only; measured-versus-modeled; missing/partial; stale;
disconnected; backend error; expanded/collapsed; overflow/scroll; keyboard cursor,
focus trap/return and visible focus; graph text alternatives; and reduced motion. It
also verifies cyan/orange/violet/grey meanings in visible legends, no color-only
result, no clipped units/source labels, and no command control in replay. Source review
and build success are prerequisites, not rendered evidence. The exact durable pattern
is recorded in the reviewed `design.md` and `docs/project/DESIGN.md` postimages above.

### Claim matrix and implementation exit

| Claim | Independent oracle and required failure |
|---|---|
| Constant velocity is also smooth | Raw source-time speed plus IMU angular/accel/jerk guards; constant speed with a shake fails |
| A route is continuous | Whole-route knot/crossover and density-invariance oracle; inserted collinear nodes cannot create hesitation |
| Replanning is live and sensed | Future obstacle omitted from initial hash, delayed observation, production replacement dispatch; clairvoyant or late-unsafe plan fails |
| Motors are physically plausible | Geometry-derived force/torque oracle plus IMU response; all-equal, swapped, or sign-reversed actuation fails |
| The twin represents reality truthfully | Persisted raw hashes, availability, timestamps, prediction/residual lineage, and restart replay; fabricated/misaligned samples fail |
| Learning improves without overfit | Frozen train/holdout split and guard vector; holdout regression or leakage blocks promotion |

Every parent and child exit is frozen below. New file names are exact intended owners;
existing owners are covered by the preimage manifest. The named test is mandatory and
does not replace adjacent regressions.

| Exit | Owner and real trigger | State/command effect and retained observation | Independent oracle, sensitivity/generalization | Boundary tag and exact test |
|---|---|---|---|---|
| WP-57 parent | `POST /campaign/runs`; `campaign/models.py`, `analyzer.py`, `observability/evaluation.py`, `catalog.py`, `CampaignLab.tsx`, `campaign-telemetry.ts` | Motion contract reaches case/package/plan/trajectory/evidence/review; terminal/motor vectors and exact first 1D catalog order render | Raw CSV vector; shake, outside-tube, `0.021 m/s` terminal peak, rounded motors, and source-array reorder fail | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; `tests/campaign/test_motion_quality_contract.py`, `ui/tests/campaign-motion-quality.test.tsx` |
| WP-58 parent | Same campaign run trigger; `trajectory.py` through `runtime_executor.py` | Whole-route trajectory and any accepted adaptive suffix are executed and retained with old/new authority | Full frozen WP-58 vector; checkpoint child, collinear density, repeated crossover and stale change falsify overgeneralization | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; `tests/campaign/test_whole_route_motion.py` |
| WP-58A | `audit_wp57_61_design.py --check`; retained workspace evidence | Exact baselines, terminal values, node modes, crossover path-state and comparator linkage reproduce | Missing metric/hash, mixed clock, different case and aggregate-only terminal data fail | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` evidence; `tests/campaign/test_wp58_baseline_oracle.py` |
| WP-58B | Route compilation in `submissions.py`/`trajectory.py`; new `campaign/route_horizon.py` | Canonical route retains semantic nodes/path-state and removes only irrelevant collinear sampling knots | Original/densified/simplified/renamed cases agree to `1e-6 m`; checkpoint/reversal/changed tangent cannot collapse | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE`; `tests/campaign/test_route_horizon.py` |
| WP-58C | `generate_smooth_trajectories`; `route_horizon.py`, `trajectory.py`, `planner.py` | Bounded whole-route smoother emits dynamics/tube-audited points and binding constraints | Exact knot/crossover/jerk/tracking/duration vector; checkpoint and stress geometry are child controls | `INTEGRATION / FAST_SIM / ACCELERATED`; `tests/campaign/test_whole_route_smoother.py` |
| WP-58D | Authenticated motion-intent event through `scenario.py` → `execution_head.py` → replacement authority | Exactly one validated suffix replaces the old future; old/new contract, source time, feasibility, command acknowledgement persist | Stale, duplicate, tampered hash, unsafe guard widening, partial validation, and after-cutover reorder dispatch zero partial changes | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED`; `tests/campaign/test_adaptive_motion_cutover.py` |
| WP-58E | `POST /campaign/runs` and Campaign Play; service/runtime/evidence/API/UI | Same package executes baseline/subject accelerated repeats and one observed-realtime run; UI round-trips all vector components | Retained replay plus raw CSV and generated trajectory oracles; alternate curve and renamed child must meet every parent gate | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; `tests/campaign/test_motion_production_qualification.py`, `ui/tests/campaign-motion-quality.test.tsx` |
| WP-59 parent | `POST /campaign/runs`; simulator world/sensor → `PerceptionObservationSource` → head/coordinator/Supervisor | At least two sensed world revisions cause certified replacement or exact fallback, then terminal landing | Future-truth exclusion, observation/hash lineage, safe-prefix certificate, detour clearance and command evidence; clairvoyant/caller-boolean paths fail | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; `tests/campaign/test_dynamic_perception_replanning.py` |
| WP-59A | Campaign-case parse and run admission; new `campaign/perception.py`, `models.py`, `scenario.py` | Separate world-truth, perceived-world and planner-world revisions have typed identities/times/quality/hashes | Unknown field, wrong mission/vehicle/clock, stale sequence, low confidence, tampered raw hash and initial future obstacle reject | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE`; `tests/campaign/test_perception_contract.py` |
| WP-59B | Runtime executor starts deterministic `simulation/world.py` events; `sensors.py` publishes only delayed observations to `perception.py` | Appear/move/remove truth produces bounded delayed/noisy sensor records before planner revision | Direct head injection, zero-latency leak, event reorder, dropout and alternate seed; planner route before observation remains identical | `INTEGRATION / FAST_SIM / ACCELERATED`; `tests/simulation/test_dynamic_obstacle_sensor.py` |
| WP-59C | `CampaignExecutionHead.execute` consumes persisted observation; `replanning.py`, `missions/base.py` | One-drone old future cancels, proposal validates, epoch commits and replacement command acknowledges without fleet regression | One/two/three-drone child cases; missing cancel/replacement ack, wrong revision and partial dispatch leave zero committed routes | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED`; `tests/campaign/test_one_drone_execution_head.py` |
| WP-59D | Observation triggers `ChangedWorldSafetyMonitor` and bounded planner in `replanning.py`, `geometry.py`, `planner.py` | Certificate supplies safe-until/fallback; feasible around/above detour dispatches, late case issues retained `STOP_AND_HOLD` or certified `ABORT_AND_LAND` | Independent clearance/braking oracle; caller boolean, under-floor route, stale certificate, unsafe hold, missing fallback ack fail | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED`; `tests/campaign/test_changed_world_safety_monitor.py` |
| WP-59E | Public Campaign Play/API on new generated reality case; service/runtime/storage/replay/UI | Two sequential obstacles and one removal are sensed, replanned, displayed, replayed, and followed by arrival/landing | Alternate seed, clear-path no-detour, reordered events, late fallback, future-hash exclusion and retained command/telemetry trace | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; `tests/campaign/test_reality_mission_e2e.py`, `ui/tests/campaign-replan-timeline.test.tsx` |
| WP-60 parent | Campaign run telemetry and exact CSV export; new `campaign/physical_truth.py`, `physics.py`, `TelemetryDock.tsx` | Per-motor PWM/thrust/current/headroom/saturation, body torque/angular acceleration and IMU/world response persist and render separately | Independent `r×F` plus reaction-torque matrix at `0.01 s`; swapped/all-equal/sign-reversed/shifted/saturated perturbations fail | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; `tests/simulation/test_motor_physical_truth.py`, `ui/tests/motor-truth.test.tsx`; `HARDWARE / NOT_RUN` |
| WP-61 parent | Twin session API plus same mission run intent; `twin/*`, API/runtime, adapters and Control Center/Campaign Review | Durable session ingests/replays all available channels, renders actual/predicted truth, qualifies simulator curriculum and retains calibration decisions | Restart/raw-hash lineage, missing-state truth, bounded split/promotion vector and physical-gate negatives | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; `tests/twin/test_twin_pipeline_e2e.py`; `HARDWARE / NOT_RUN` |
| WP-61A | `POST /twins` and session reopen; new `twin/storage.py`, `twin/models.py`, `coordinator.py` | Atomic session/channel/sample/calibration journals survive process restart with lifecycle/index/retention metadata | Kill-before/after-rename, duplicate IDs, corrupt hash, missing index and million-record/4-GiB boundary preserve or reject complete prefix | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE`; `tests/twin/test_storage.py` |
| WP-61B | `POST /twins/{id}/samples` and Fast Sim/real-adapter-shaped producer; new `twin/ingestion.py`, `domain/telemetry.py`, adapters | Bounded batch normalizes units/frame while retaining raw payload hash, source/receive clocks, sequence, quality and unavailable markers | 512/513, byte, channel/rate/buffer limits; duplicate unequal hash, bad unit/frame, out-of-order and overflow reject whole batch without drop | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED`; `tests/twin/test_ingestion.py`, `tests/api/test_twin.py` |
| WP-61C | Session timeline/report/replay request; `twin/coordinator.py`, `twin/storage.py`, `observability/replay.py` | Raw and predicted records align one-to-one; residual lineage and replay hashes survive restart | Independent recomputation; missing measurement remains unavailable, prediction cannot backfill, stale/frame/hash/source-shift perturbations fail | `INTEGRATION / FAST_SIM / ACCELERATED`; `tests/twin/test_replay.py` |
| WP-61D | `GET /twins/{id}/timeline` via production-served Control Center/Campaign Review; API and named UI owners | Actual/predicted room overlay, active summary, shared cursor and selectable graphs show source/age/quality/text alternatives | Exact rendered-release matrix in the preceding section, including desktop/narrow and keyboard/reduced-motion/error states | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME`; `tests/api/test_twin.py`, `ui/tests/twin-session.test.tsx`, retained `wp61-ui-inspection-v1.json` |
| WP-61E | Public stage selection/run through campaign service and twin ingestion; generated catalog/config | Startup, slow takeoff, hover, land, straight, checkpoint, continuous and obstacle stages record prerequisite/result/session links | Reordered catalog does not bypass prerequisite; failed stage blocks dependent stage; simulator and real-shaped adapter produce same schema | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; `tests/twin/test_curriculum.py` |
| WP-61F | `POST /twins/calibrations/candidates`, replay qualification, then explicit promotion endpoint; new `twin/calibration.py` | Six whole sessions freeze split; bounded candidate/rejected lineage and three-repeat vector persist; promotion changes only accepted model version | Independent holdout RMSE and guard recomputation; leakage, five-session set, out-of-bounds parameter, nonrepeatability, 9% gain, guard regression or absent operator acceptance blocks | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED`; `tests/twin/test_calibration.py`; physical candidate/promotion `HARDWARE / NOT_RUN` |
| WP-61G | Existing physical qualification entry and adapter connect path; hardware/qualification/providers/Crazyflie owners | Common schema and staged gate handoff are generated; every real stage remains literal `NOT_RUN` and issues no command | Disconnected/stale/partial sensor, wrong unit/frame, absent bench/entry/operator phrase and simulated-data-as-real perturbations fail closed | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE`; `tests/twin/test_physical_handoff.py`; operational boundary `HARDWARE / NOT_RUN` |

Before implementation review, run the predraft census in `--check` mode, unit and
property tests for each contract, the complete existing campaign/API/UI regression
suite, generated-catalog reconciliation, accelerated and observed-realtime Fast Sim
qualification for affected cases, retained-bundle replay, UI tests and a production-
served browser pass. Retain literal failing perturbations for every core claim. Freeze
one exact dirty-tree implementation manifest with base commit, changed/new/deleted
files, delimited generated sections, and full pre/post hashes. A different fresh
`work_packet_verifier` must trace the production path and evidence. One author revision
and one focused recheck are allowed at each gate; there is no third automatic pass.

<!-- WP57-61-DESIGN-PAYLOAD-END -->

### WP-57 through WP-61 design-review handoff

- Independent verification: `REVIEW_BLOCKED`.
- Initial design payload SHA-256:
  `2ff26512bfb766c76938d9b19f872ea9eb43cbb344f8e5962d769a5a16c0ba68`.
- Initial verifier: `/root/wp57_61_design_review` returned
  `BLOCKED_WITH_FINDINGS` with no P0 and seven P1 findings. It required an exact
  non-last hover/land order, missing-metric and artifact-link validation, pre-freeze
  numerical witnesses, a sensor-triggered independent safe-prefix certificate in
  WP-59, per-parent/child production claim rows, complete affected-boundary preimages,
  and a bound rendered/accessibility UI exit.
- Sole author revision: completed. It makes takeoff/hover/land first, revises the
  immutable audit with terminal metrics and nine-link evidence validation, freezes all
  numerical prototypes and WP-61 bounds, replaces the replanning caller boolean with
  a designed certificate/command trace, adds exact owners/tests/tags for all five
  parents and 17 children, expands preimages, and updates both UI design guides.
- Revised design payload SHA-256:
  `2096bac6a01dd437ff5f909bc63bd3b012b30927b7d270aa3f9c4644049f8c6f`.
- Focused recheck: `/root/wp57_61_design_review` returned
  `BLOCKED_WITH_FINDINGS`, with no P0, two P1 findings, and one P2 limitation. The
  unresolved P1s were an incomplete WP-61F altitude/velocity/repeatability prototype
  and absent frozen preimages for `missions/base.py`, `csv_export.py`, and
  `dashboard.py`. The P2 noted that the audit compared stored evaluation report hashes
  without recomputing them.
- The first design cycle is exhausted. The operator explicitly authorized at most two
  structuring cycles; the following narrow corrective overlay is the second and final
  design cycle. It retains the exact revised base payload unchanged and changes no
  product scope.
- Implementation remains prohibited until the composite base-plus-overlay design
  reaches `DESIGN_VERIFIED`.

<!-- WP57-61-R2-DESIGN-PAYLOAD-BEGIN -->

## WP-57 through WP-61 final corrective design overlay

This overlay incorporates the complete originating operator request and every clause
of the unchanged 51,957-byte WP-57 through WP-61 base design payload whose SHA-256 is
`2096bac6a01dd437ff5f909bc63bd3b012b30927b7d270aa3f9c4644049f8c6f`.
The base payload remains delimited above and is not restated or narrowed here. This
overlay addresses only the two P1 findings left by its focused recheck and also closes
the verifier's P2 evaluation-identity limitation. Its sole consolidated correction
closes the final-cycle verifier's three P1s: an exact WP-59 reaction/certificate
witness, isolated WP-61F motion/safety guards, and independently derived boundary
sets. There is no new product function,
weakened threshold, changed dependency, or changed WP-57/WP-58A-E/WP-59A-E/WP-60/
WP-61A-G exit.

### Frozen retrospective and identities

The required short retrospective is retained in
`docs/project/WORKFLOW_AND_REQUIREMENTS.md`. `REQ-WFL-046` now requires one isolated
failure per numerical guard; `REQ-WFL-047` derives claim, public-transit, generator,
and generated-output sets from independent sources rather than comparing two authored
lists; and new `REQ-WFL-048` requires exact sensed-world reaction/certificate/fallback
witnesses. The workflow postimage SHA-256 is
`e268966870c6f6cf7f3cc835507d3082ce56368e08f335167322027af7777544`.

The exact corrective audit is
`scripts/audit_wp57_61_r2_design.py`, SHA-256
`961d157e05a3293dbd9feef371167af070188c19e2a5eccf65a0499b47f8ec87`.
Its retained output is
`missions/campaigns/sim/qualification/wp57-61-r2-design-audit-v1.json`, file SHA-256
`0237cf6d23b08dd32e0e50705fc2572aca02db896fbeb8cf99951a883b0cd810`
and canonical payload SHA-256
`229eb2a55635df03f08855be12e5bc7f487c65e5697d5556f08f2db53ce0cc2f`.
Run this exact pre-freeze check from repository root:

```bash
python3 scripts/audit_wp57_61_r2_design.py --check missions/campaigns/sim/qualification/wp57-61-r2-design-audit-v1.json
```

The audit reproduces the unchanged base design hash, first audit script/file/payload
hashes, workflow hash, every boundary hash, all numerical results below, and all 31
stored evaluation `report_sha256` values by independently hashing the canonical
report payload with `report_sha256` excluded. Any difference fails the check.

### WP-59 sensed-world reaction, certificate, and fallback oracle

The exact `wp59-sensed-world-reaction-safety-v1` fixture uses flight volume
`(-1,-1,0)..(3,1,2) m`, start `(0,0,1) m`, goal `(2.4,0,1) m`, obstacle
`(1,-0.25,0.2)..(1.4,0.25,1.6) m`, and required clearance `0.15 m`. The future
obstacle is absent from initial-plan hash
`4458d27e7f31e528c40df1f9e79c3d43aaf9caaaeca0bbf0c546b4e6864cab18`.
Truth, persisted raw observation, and perceived-world hashes are separately
`ae08c5a0447c1bcd938d4742ba1b7350f98d68f00132264b776f8e6c2c12237a`,
`47192a53d881a41b310c6b24baf98b2690a550bd7e6cc1568c63415b580843fc`,
and `b938b0448dcde9b8ddafbfb8b8ecb090a61fdf091de96833e872f9ff73b7f6b2`.

The full event-to-cutover budget is sensor capture `0.08 s`, transport `0.04 s`,
perception processing `0.03 s`, queue `0.02 s`, planning `0.20 s`, acknowledgement
`0.04 s`, commit `0.03 s`, and cutover guard `0.10 s`: exactly `0.54 s`. Prediction
horizon is `1.50 s`. Nominal truth/capture/receive/processed/cutover/effective source
times are `2.00/2.08/2.12/2.15/2.54/3.20 s`. At state `(0.4,0,1) m` and
velocity `(0.3,0,0) m/s`, the direct path has zero obstacle clearance. The exact
detour `(0.4,0,1) -> (0.84,0.41,1) -> (1.56,0.41,1) -> (2.4,0,1)` is
`2.256134207324801 m` long and has `0.15999999999999998 m` clearance, versus the
`2.0 m` blocked direct path.

With `0.8 m/s²` braking, `0.08 m` hold drift and `0.03 m` uncertainty, the nominal
stopping/hold envelope is `0.21725 m` against `0.45 m` available. The safe-prefix
certificate is safe through `3.55 s`, covers the `2.54 s` cutover, binds the active
trajectory, observation, perceived revision, vehicle state and exact fallback, and
has SHA-256 `d5af58a9646b69f2e6c388c54e3344fd2d40b32f08be76df37e796d93a379489`.
If planning is infeasible it alone authorizes `STOP_AND_HOLD`.

The late fixture has truth/effective times `3.00/3.30 s`, only `0.30 s` lead, state
`(0.74,0,1) m`, and velocity `(0.1,0,0) m/s`. Replacement fails the `0.54 s`
reaction horizon and `STOP_AND_HOLD` fails because its `0.13325 m` envelope exceeds
`0.11 m` available. The separately accepted landing route
`(0.74,0,1) -> (0.76325,0,1) -> (0.3,0,1) -> (0.3,0,0.05)` retains
`0.23675000000000002 m` clearance and authorizes only `ABORT_AND_LAND` through
certificate `a772c7025acbf5064b383f2d223adbe1301b12d94620a95d0b81853e75fbb563`.
Zero capture latency, `0.26 s` stale observation, tampered raw hash, wrong world
revision, `0.14 m` detour clearance, `0.53 s` reaction lead, missing certificate, and
unsafe hold plus uncertified abort each produce zero replacement dispatch; the last
requests and records `UNQUALIFIED_EMERGENCY_FALLBACK` rather than completing.

### Complete WP-61F holdout and determinism oracle

WP-61F keeps the base design's frozen four-parameter bounds, six whole-session split,
two geometries, canonical session-hash assignment, untouched holdouts, motion/safety
guards, and explicit operator promotion. Its numerical oracle is now complete:

- Each geometry has three deterministic whole-holdout replay outputs. Each repeat is
  the full residual vector plus all 15 motion/safety guards below. All three canonical
  full-vector SHA-256 values must be identical and the maximum absolute spread of
  every metric must be at most `1e-12`. Both conditions are required.
- The primary relation is the arithmetic mean of all six whole-session position RMSE
  outputs. It must improve by at least `0.005 m` and at least `10%`; neither geometry
  may be worse. Altitude and velocity RMSE are secondary guards: their arithmetic
  means may regress by at most `5%` both per geometry and across all six outputs.
- The pass baseline repeats are straight
  `(0.080,0.040,0.100)` three times and curve `(0.070,0.035,0.090)` three times. The
  pass candidate repeats are straight `(0.068,0.041,0.102)` three times and curve
  `(0.060,0.036,0.092)` three times. Mean position changes from `0.075 m` to
  `0.064 m`, an improvement of `0.011 m` and `14.66666666666666%`; aggregate altitude
  regression is `2.6666666666666616%` and velocity regression is
  `2.105263157894699%`. Straight/curve altitude regressions are `2.5%` and
  `2.857142857142847%`; straight/curve velocity regressions are `2%` and
  `2.2222222222222143%`. Every primary, guard, and repeatability clause passes.
- The primary-and-guard failure candidate is straight
  `(0.074,0.043,0.106)` three times and curve `(0.066,0.038,0.096)` three times.
  Mean position is `0.070 m`: the `0.005 m` absolute boundary is met, but the
  `6.666666666666674%` relative improvement fails. Aggregate altitude regression is
  `8%` and velocity regression is `6.315789473684186%`; their per-geometry guards
  also exceed `5%`. Promotion therefore fails even though repeats are identical.
- The repeatability failure candidate otherwise uses the pass vectors, except the
  straight position repeats are `(0.068,0.068,0.068000000002)`. The computed maximum
  spread is `1.9999973899231804e-12`, and the third vector hash differs. Promotion
  therefore fails while the primary and secondary relations still pass.
- The ordered motion/safety registry is speed-compliance fraction (minimum `0.95`,
  at most `5%` regression), speed ripple (maximum `0.05 m/s`, `5%`), acceleration p95
  (`1.0 m/s²`, `5%`), jerk p95 (`8.0 m/s³`, `5%`), angular-rate p95 (`0.40 rad/s`,
  `5%`), motor-spread p95 (`0.50`, `10%`), tracking RMS (`0.05 m`, `5%`), path-tube
  maximum error (`0.05 m`, `5%`), motor saturation fraction (`0.02`, `5%`), duration
  (`17.5 s`, `5%`), terminal secondary peak (`0.02 m/s`, `5%`), terminal reversal
  count (`0`), minimum clearance (`0.15 m`, at most `5%` regression), collision count
  (`0`), and Supervisor safety gate (literal `true`). Hard and regression clauses
  both apply per repeat, per geometry, and to the six-session aggregate.
- In that exact order, straight baseline/pass guard vectors are
  `(0.970,0.040,0.600,4.000,0.250,0.250,0.035,0.040,0.005,10.000,0.010,0,0.200,0,true)`
  and
  `(0.960,0.041,0.620,4.100,0.260,0.260,0.036,0.041,0.005,10.200,0.0104,0,0.195,0,true)`;
  curve baseline/pass vectors are
  `(0.965,0.042,0.640,4.200,0.270,0.270,0.036,0.041,0.006,11.000,0.011,0,0.190,0,true)`
  and
  `(0.955,0.043,0.660,4.300,0.280,0.280,0.037,0.042,0.006,11.200,0.0114,0,0.185,0,true)`.
  Each is repeated three times and included in the same hashes as its residuals.
- Fifteen isolated failure fixtures begin from the fully passing residual and guard
  candidate and change only the named straight guard, across its three repeats, to:
  speed compliance `0.94`; ripple `0.052`; acceleration `0.700`; jerk `4.400`;
  angular rate `0.280`; motor spread `0.280`; tracking `0.038`; path-tube error
  `0.052`; saturation `0.030`; duration `10.600`; terminal peak `0.021`; reversals
  `1`; clearance `0.140`; collisions `1`; or Supervisor gate `false`. In every
  fixture position improvement, altitude/velocity guards, repeat hashes/tolerance,
  the other 14 guards, and the curve geometry still pass. Only the changed guard
  rejects promotion. The audit proves exactly one changed registry key per fixture.

The retained JSON contains every residual and motion/safety baseline/candidate repeat
vector, vector hash,
per-metric spread, per-geometry result, aggregate result, threshold, and verdict. An
implementation may not replace whole-session repeats with segments, average away a
failed geometry guard, round the relative threshold into a pass, or use its own stored
promotion verdict as the oracle.

### Closed affected-boundary manifest

The corrected audit freezes and verifies 84 existing production/design/generated
boundaries and marks 33 exact test/source/artifact owners as
`INTENDED_NEW_ABSENT_AT_DESIGN_FREEZE`. It extracts the exact ordered 22-row claim
matrix from the base payload and requires an exact 22-key owner binding; probes the
public Campaign and twin transit nodes for their real entry/import/call/serve tokens;
and independently discovers the generated-output sets by four filesystem globs. A
missing claim row/owner/transit token, changed preimage, existing supposedly-new path,
or generated set difference fails before implementation. The earlier seven logical
groups remain as an additional, not sole, check.

The prior three omitted boundaries plus the final-cycle public request/UI entry gaps
are frozen as:

```text
887e02db596015f4e27ac4d75476408d31c760c997860101b9243ef7ca371702  IMPLEMENTATION_OWNED  src/crazyswarm_app/missions/base.py
07702a86a9adb529dbdc3f309d15d5e8a256b6f89bf2a133460b090de7563126  IMPLEMENTATION_OWNED  src/crazyswarm_app/observability/csv_export.py
950f53e55caebf4c8e3f77b840a2f3f6cb079c01a044b981bdf299afaad53149  IMPLEMENTATION_OWNED  src/crazyswarm_app/dashboard.py
06a8620e2c08512ab5e8b0d9d060bd29dc51fd0e358400a9dee0f6482165c39f  IMPLEMENTATION_OWNED  src/crazyswarm_app/campaign/api_models.py
df5abbd859b591ac2644eb9acd82d5191c377c3f351cd75310b3538f4801f752  IMPLEMENTATION_OWNED  ui/app/page.tsx
```

`missions/base.py` is the mission execution contract traversed by WP-59C;
`csv_export.py` is the exact physical/motion evidence boundary traversed by WP-57 and
WP-60; `dashboard.py` serves the production UI release required by WP-57, WP-59E,
WP-60, and WP-61D; `campaign/api_models.py` owns the public run request; and
`ui/app/page.tsx` mounts the served `ControlCenter`. The generated sets are exactly 17
`missions/library/one_drone/*/mission.py` outputs, all 11 simulator case manifests
(including the three 1D manifests), four generated real-mirror manifests, and the
default development preset. Every path and preimage is explicit in the retained
audit. It also binds absent `tests/api/test_twin.py` and
`wp61-ui-inspection-v1.json` owners. The audit's `affected_boundary_closure` is the
authoritative full manifest; the focused lines above are not a replacement for the
base payload's other hashes. The implementation manifest must preserve every relied-
upon preimage or record its exact postimage and tests, and must bind every created
path listed as absent here.

### Final design-cycle gate

This composite design remains `DRAFT_UNVERIFIED`. A fresh project-scoped
`work_packet_verifier`, different from the first-cycle verifier, must reproduce the
base and corrected overlay identities, run the R2 audit, and adjudicate the three
final-cycle P1 corrections through their exact artifacts. The sole consolidated
author correction is now consumed. Only one focused recheck by that same fresh
verifier remains. An unresolved P0/P1 leaves the batch blocked; there is no further
correction or third structuring cycle. No production implementation may begin before
`DESIGN_VERIFIED`.

<!-- WP57-61-R2-DESIGN-PAYLOAD-END -->

### WP-57 through WP-61 final design-cycle handoff

- Independent verification: `REVIEW_BLOCKED`.
- Composite identity: unchanged base design SHA-256
  `2096bac6a01dd437ff5f909bc63bd3b012b30927b7d270aa3f9c4644049f8c6f`
  plus the 13,087-byte corrected final overlay SHA-256
  `e1be5e88fa91c510eb5612ee1b30d35347df53008e4fd7d563f044cbd6c67b5c`.
- Design-cycle count: first cycle exhausted after initial review, one correction, and
  focused recheck. Second/final initial verifier
  `/root/wp57_61_r2_design_review` returned `BLOCKED_WITH_FINDINGS`, no P0/P2, with
  three P1s: missing WP-59 reaction/certificate numerics, incomplete WP-61F
  motion/safety guards, and non-derived boundary closure. The sole consolidated
  correction and focused recheck by that same verifier are complete.
- Implementation is prohibited until the composite identity reaches
  `DESIGN_VERIFIED`.
- Final focused recheck: `/root/wp57_61_r2_design_review` returned
  `BLOCKED_WITH_FINDINGS`, with no P0/P2 and one unresolved P1. The exact WP-61F
  isolated guard registry correctly rejects its 15 retained guards, but does not
  cover every motion guard declared by the unchanged base design and durable
  requirements: motor headroom, energy, motor differential, and waypoint-mode
  preservation remain without pass/fail whole-session vectors or isolated
  perturbations. A calibration could therefore degrade a declared guard while still
  passing the frozen promotion oracle.
- Final disposition: `REVIEW_BLOCKED`. The operator-authorized two structuring cycles
  and the final cycle's sole correction/recheck are exhausted. No production
  implementation, third design cycle, or same-author certification is permitted.
- Verification-cost record: first cycle initial review + one correction + focused
  recheck; second cycle initial review + one correction + focused recheck. Reviewer
  model, effort, token, and elapsed-time telemetry were not exposed. Design evidence
  proxies are the 51,957-byte base payload, 13,087-byte corrective overlay, two
  retained audit artifacts, 84 existing boundary hashes, 33 absence checks, and the
  exact 22-row claim matrix.

<!-- WP57-61-R3-DESIGN-PAYLOAD-BEGIN -->

## WP-57 through WP-61 operator-authorized R3 guard-closure overlay

### Frozen authorization, value, and boundary

The unchanged originating request and all WP-57 through WP-61 parent/child scope are
the exact 51,957-byte base payload with SHA-256
`2096bac6a01dd437ff5f909bc63bd3b012b30927b7d270aa3f9c4644049f8c6f`.
The unchanged second-cycle correction is the exact 13,087-byte R2 overlay with
SHA-256
`e1be5e88fa91c510eb5612ee1b30d35347df53008e4fd7d563f044cbd6c67b5c`.
After being told that one narrow successor would close motor headroom, energy/reserve,
motor differential, and waypoint-mode promotion guards, the operator authorized this
successor with the exact request:

> Ok continue then with this cycle

This is one explicitly authorized successor design cycle under `REQ-WFL-037` and
`REQ-WFL-044`, not an automatic third pass. The affected value is the explicit request
that calibration improve the twin without overfitting or silently worsening flight
quality. The safe fallback is the unchanged unpromoted predecessor calibration: no
candidate can be promoted while this gate is blocked. The expected work is limited to
deriving the complete guard universe, freezing exact whole-session arithmetic, and
independent design review. It cannot wait until implementation because the prior
promotion oracle would allow a candidate to regress already-declared motion behavior.

R3 changes no product function, packet/child decomposition, production owner, physical
authority, dependency, runtime boundary, UI design, sensor scope, parameter-search
bound, split rule, primary/residual threshold, or WP-57 through WP-61 exit. It adds
only the missing WP-61F promotion guards and a reusable completeness rule. Production
implementation remains prohibited until the composite base+R2+R3 design reaches
`DESIGN_VERIFIED`.

### Retrospective and exact identities

The focused R2 recheck proved that self-consistency of a guard registry does not prove
semantic completeness. `REQ-WFL-049` now requires a source-to-category-to-metric map
derived from the frozen operator request, durable requirements, packet contract, and
claim/exit matrix independently of the registry. The workflow postimage SHA-256 is
`b8972dfc2c74256adf268c672ae82a5bf700c43ab65d68d98a3aca88e3973183`.

The exact R3 audit is `scripts/audit_wp57_61_r3_design.py`, SHA-256
`b137fbb720a4be831451769b8a471ef06f2acf5a8ff4bf5ec24b355049527172`.
Its retained output is
`missions/campaigns/sim/qualification/wp57-61-r3-design-audit-v1.json`, file SHA-256
`e28a293829c349208f33d3d8078f6f81d3fafd3990c310178f386146ccb33af5`
and canonical payload SHA-256
`5cbaa9d61a79a904575cff649fa1f9b8e445a161a18ad50beb8ae14d458f3070`.
The retained audit independently recomputes the predecessor identities, including the
R2 JSON canonical payload rather than trusting its stored hash. Reproduce R3 with:

```bash
python3 scripts/audit_wp57_61_r3_design.py --check missions/campaigns/sim/qualification/wp57-61-r3-design-audit-v1.json
```

At design freeze the branch base remains commit
`7a27ddbb7342253b489d72e4a2ecc90ea852019b`. The new script and artifact are design
evidence only. No production source, runtime configuration, generated mission, API,
UI, test, or operator-owned Campaign evidence changed in this cycle. R3 inherits the
R2 audit's exact 84 existing preimages, 33 absent/new owners, 22 claim bindings,
production-transit probes, generated-output sets, and every base/R2 numerical oracle.

### Independently derived complete promotion guard universe

The audit derives 17 semantic categories from exact tokens in the composite design and
durable requirements, then requires an exact one-to-one metric ownership closure. The
22 ordered promotion guards are:

1. Speed law/band: `speed_compliance_fraction`, `speed_ripple_m_s`.
2. Acceleration and jerk: `acceleration_p95_m_s2`, `jerk_p95_m_s3`.
3. Body activity: `angular_rate_p95_rad_s`.
4. Motor truth: `minimum_motor_thrust_headroom_n`,
   `motor_spread_p95_percent`, `motor_saturation_fraction`,
   `motor_differential_sign_agreement_fraction`, and
   `motor_differential_normalized_error_p95`.
5. Energy: `electrical_energy_used_j`.
6. Path truth: `tracking_rms_m`, `path_tube_max_error_m`,
   `minimum_clearance_m`, and `collision_count`.
7. Waypoint semantics: `checkpoint_hold_conformance_fraction`,
   `minimum_continuous_knot_speed_ratio`, and
   `unintended_fly_through_stop_count`.
8. Terminal/runtime safety: `terminal_secondary_peak_m_s`,
   `terminal_reversal_count`, `duration_s`, and
   `supervisor_safety_gate_passed`.

Every metric appears in exactly one semantic category, every category has a frozen
declaration probe, the registry contains no extra metric, and every metric has a
direction, hard threshold, repeat/geometry/aggregate relation, exact definition, pass
vector, metric-level isolated rejection, and independently binding clause witness. An
implementation cannot add, remove, merge, rename, or substitute a metric or omit a
binding hard/regression/geometry branch without a new reviewed design revision.

### Seven added direction-aware guards

The 15 R2 guards remain byte-exact. R3 adds seven guards:

- Motor headroom is the minimum, over every motor and source-sequence motion sample,
  of configured maximum thrust minus applied thrust. It must remain at least
  `0.030 N` and regress no more than `5%` per repeat, geometry, and six-session
  aggregate.
- Electrical energy is the trapezoidal source-time integral of measured battery
  voltage times current from accepted motion start through terminal motor cutoff. It
  must remain at most `220 J` and regress no more than `5%`. Battery percentage or a
  planned energy estimate cannot replace this observation.
- Signed differential agreement uses the independent WP-60 X-layout force/torque
  oracle, not motor spread and not a caller flag. For samples with expected nonzero
  body torque, at least `95%` of measured motor-pair differentials must have the
  expected sign and the value may regress no more than `5%`.
- Differential magnitude error is p95 absolute measured-minus-expected signed
  motor-pair differential divided by `max(abs(expected differential), 0.005 N)`. It
  must remain at most `0.10` and regress no more than `5%`. All-equal actuation during
  an independently expected maneuver therefore fails rather than looking smooth.
- Checkpoint conformance is the fraction of authored `CHECKPOINT` nodes captured
  inside their ball and held for authored dwell within `±0.02 source seconds`; it must
  equal `1.0`.
- Continuous-knot speed is the minimum observed-to-adjacent-target ratio at authored
  `CONTINUOUS_FLY_THROUGH` nodes. The straight ordinary-knot geometry must remain at
  least `0.85`; the curve geometry's repeated figure-eight path-state must remain at
  least `0.95`. The normalized value may regress no more than `5%`.
- Unintended fly-through stop count uses the frozen stop-speed/dwell oracle and must
  remain exactly zero.

Both holdout geometries contain an authored checkpoint and continuous nodes. The curve
geometry additionally binds its continuous ratio to the repeated crossover path-state
rather than coordinate equality. This proves both requested traversal modes without
turning every node into a stop or making every checkpoint a fly-through.

### Complete repeat, aggregate, and sensitivity vectors

R3 inherits the R2 pass residuals and first 15 guard values unchanged. Each baseline
and candidate number below is repeated exactly three times as a whole-session replay
for both geometries and is included in the same full-vector hash as position,
altitude, velocity, and the retained 15 guards. All three hashes per geometry must be
identical and every numeric spread must be at most `1e-12`.

In the added-guard order headroom, energy, differential-sign agreement,
differential-magnitude error, checkpoint conformance, continuous-knot ratio, and
unintended fly-through stops, the straight baseline/pass vectors are
`(0.040,150,0.980,0.060,1.0,0.920,0)` and
`(0.039,153,0.970,0.062,1.0,0.900,0)`. The curve baseline/pass vectors are
`(0.038,165,0.975,0.065,1.0,0.980,0)` and
`(0.037,168,0.965,0.067,1.0,0.970,0)`. Every hard, regression,
per-geometry, aggregate, hash, and tolerance clause passes together with the inherited
primary position improvement and altitude/velocity residual guards.

The exact isolated failures change only one named full-vector key across its three
repeats while every residual, repeatability clause, other 21 guards, and the other
geometry remain passing:

| Guard | Isolated value and rejection |
|---|---|
| Motor headroom | Straight `0.029 N`; below the `0.030 N` hard floor |
| Electrical energy | Straight `160 J`; `6.66666666666667%` regression from `150 J` |
| Differential sign | Straight `0.940`; below the `0.95` hard floor |
| Differential magnitude | Straight `0.110`; above the `0.10` hard ceiling |
| Checkpoint mode | Straight `0.5`; not every checkpoint capture+dwell conforms |
| Continuous mode | Curve crossover `0.940`; below its `0.95` hard floor |
| Fly-through stop | Straight `1`; one undeclared stop violates exact zero |

The audit also reconstructs and reruns all 15 R2 isolated failures against the expanded
22-guard vector. These 22 metric-level scenarios prove one changed key and one rejected
promotion per guard, but they are not claimed to sensitize every conjunctive clause.
The sole R3 correction adds eight regression-only whole-vector scenarios whose hard
bound, aggregate result, other geometry, other 21 guards, primary/residual relations,
and repeatability remain passing:

| Regression-only clause | Exact isolated candidate |
|---|---:|
| Straight speed ripple | `0.0421 m/s` (`5.25%` regression) |
| Straight path-tube error | `0.0421 m` (`5.25%` regression) |
| Straight saturation fraction | `0.0053` (`6%` regression) |
| Straight terminal secondary peak | `0.0106 m/s` (`6%` regression) |
| Straight minimum clearance | `0.189 m` (`5.5%` regression) |
| Straight motor headroom | `0.0379 N` (`5.25%` regression) |
| Straight differential magnitude error | `0.0631` (`5.16666666666667%` regression) |
| Straight ordinary continuous-knot ratio | `0.873` (`5.10869565217391%` regression) |

The audit now retains 30 isolated rejected promotions: 22 metric-level fixtures plus
eight clause-isolating additions. Its mechanical 23-row binding-clause map selects the
sensitive witness for every guard and separately covers the continuous guard's straight
`0.85` regression branch and curve `0.95` hard branch. Under the exact canonical
predecessor values, the map proves which hard or regression boundary is tighter; a
logically dominated companion clause is not mislabeled independently binding. Each
fixture
retains full baseline/candidate repeats, full-vector hashes, per-geometry and aggregate
arithmetic, the changed-key set, and the promotion verdict; a stored pass/fail boolean
is never the oracle.

### R3 design gate

The composite base+R2+R3 design is `DRAFT_UNVERIFIED`. Fresh verifier
`/root/wp57_61_r3_design_review` reproduced the initial R3 identities and arithmetic
but returned one P1: metric-level failures did not isolate eight tighter regression
clauses or the straight waypoint branch. The sole consolidated author correction is
now consumed by the exact 30-scenario/23-binding-witness artifact above. Only one
focused recheck by that same verifier remains. Any unresolved P0/P1 leaves the batch
`REVIEW_BLOCKED`; no implementation or same-author certification is allowed.

<!-- WP57-61-R3-DESIGN-PAYLOAD-END -->

### WP-57 through WP-61 R3 design-review handoff

- Independent verification: `DESIGN_VERIFIED`.
- Composite identity: base SHA-256
  `2096bac6a01dd437ff5f909bc63bd3b012b30927b7d270aa3f9c4644049f8c6f`, R2 SHA-256
  `e1be5e88fa91c510eb5612ee1b30d35347df53008e4fd7d563f044cbd6c67b5c`, and R3
  corrected 11,601-byte overlay SHA-256
  `6f46645b39ee279b87bede0c530e4bc77fab138552cdcd8498837d02ed23deff`.
- Initial R3 identity: 10,178-byte overlay SHA-256
  `c6917cbc591c7f338087331fb3681ea96792fc8a6de11bde61cdd8d02036876a`.
- Initial R3 review: `/root/wp57_61_r3_design_review` returned
  `BLOCKED_WITH_FINDINGS`, no P0/P2 and one P1. Eight independently tighter
  regression clauses and the straight waypoint branch lacked sensitive isolated
  witnesses even though every metric had one failing scenario.
- Sole author correction: consumed. The corrected artifact retains 22 metric-level
  failures, eight regression-only additions, and an exact 23-row binding-clause map.
- Focused-recheck budget: consumed; no further author revision is permitted in R3.
- Focused recheck: `/root/wp57_61_r3_design_review` returned `DESIGN_VERIFIED` with no
  remaining P0/P1/P2 findings. It independently reproduced the corrected identities,
  all 30 isolated scenarios, all 23 binding-clause witnesses, and zero arithmetic
  errors. The residual boundary is design-only `MODEL_ONLY / NO_RUNTIME`; production,
  Fast Sim, realtime, rendered UI, and hardware evidence remain implementation and
  qualification obligations.
- Composite design accepted; implementation is authorized from this exact identity.

### WP-57 through WP-61 implementation-review handoff

- Independent verification: `BLOCKED_WITH_FINDINGS`.
- Initial implementation payload: staged patch SHA-256
  `3c9cd9bf0e65e35c72e50db74015b0e8429800d9cf7c396291b27d009568d735`;
  exact 87-file pre/post manifest in
  `missions/campaigns/sim/qualification/wp57-61-implementation-manifest-v1.md`.
- Fresh verifier: `/root/wp57_61_implementation_review`; initial review and the one
  permitted focused recheck are consumed. No further automatic implementation pass is
  permitted.
- Sole fix overlay: SHA-256
  `a9dd5636b86b29e8c21a93d44e3554cc3d4c6491fb90ffe6ba29a810afdb340b`.
  The verifier confirmed WP-59A/B/E future-truth exclusion is resolved: hidden future
  environment geometry/timing changes execution identity but cannot enter or change
  the initial planner view, case identity, or plan identity.
- Remaining P1 findings: nominal sensed changes still stop-and-hold before replanning;
  adaptive motion-intent replacement is not connected to production; motion and
  physical-truth guard failures do not block qualification; calibration promotion
  trusts caller-supplied results instead of replay-derived session evidence; yaw is
  absent from the motor oracle; and required served/realtime UI evidence is not
  available. These keep the smallest affected WP-57 through WP-61 scopes partial and
  unverified.
- Retained P2: the first four twin curriculum labels reuse one mission without
  stage-specific independent oracles.
- Real-aircraft evidence remains literal `NOT_RUN`. The interrupted UI dependency tree
  prevented lint/build/browser execution and is recorded as an evidence limitation,
  not a passing result.

## Operator-review successor batch — stable goal-seeking replanning and compact 1D missions

This is a narrow successor to the partially implemented WP-57 through WP-61 batch. It
does not reopen that batch's exhausted implementation review, inherit its unverified
claims, or authorize implementation. It converts the latest two failed realtime runs
and the operator's clarified product model into five independently reviewable design
packets.

| Packet | Status | Independent verification |
|---|---|---|
| WP-62 — realtime replanning runtime stability and recovery | `DEFINED_NOT_STARTED` | `DESIGN_VERIFIED` |
| WP-63 — five-major-mission 1D curriculum and plain preparation controls | `DEFINED_NOT_STARTED` | `DESIGN_VERIFIED` |
| WP-64 — whole-route motion trade-offs and motor-realism regression | `DEFINED_NOT_STARTED` | `DESIGN_VERIFIED` |
| WP-65 — source-time graph-to-flight review cursor | `DEFINED_NOT_STARTED` | `DESIGN_VERIFIED` |
| WP-66 — start-goal dynamic replanning cluster and online-obstacle mission | `DEFINED_NOT_STARTED` | `DESIGN_VERIFIED` |

<!-- WP62-66-DESIGN-PAYLOAD-BEGIN -->

### Frozen originating requests

The following is the exact operator request that originated this successor batch:

> next work packet iteration or improvement
>
> - 1D
>   - Compact current missions into 5 major missions with the same path planning and so on (in basic flight & routes, hovering, move to target, follow path same altitude, follow path with changing altitudes windshief and so on, like the ones before, figure 8 and different shape as submissions e.g.
>     - The basic movement was fine, general path planning is good, constant velocity can be done, it can hover land etc., follow line
>     - Only thing is that e.g. in curved route: you see how at the kink it still slows down even though it didnt have to slow down because the turn was easy to do not that harsh, that is also the quality measure that I am talking about like maybe also let me adjust for the paramters, constant velocity, waypoint holding max accuaracy to the limit it can go off the planned path, if I set it to 100m then it could go straight you know if no obstacle there, thats what I am talking about I want this kind of econtrol hewn preparing a mission with a path so it does a tradeoff between velocity amount and stability, control acceleration and realness (it cannot change velocity suddenly for 100° corners or something), so basically basic mission with case, then choose between subcases like now and also let me choose these measurements
>     - Just make the submission like one simple slider with one word not planner retimed baseline doubled, also remove this eligible shit it is not needed
>     - Test if movement is better, more realistic motor movement
>     - Do you know e.g. when looking at mission velocity profile one bump then exactly what the drone did there at this moment or where it was -> if not implement that capability for better post analysis
>
> - Replanning Flexible dynamic
>   - Then you can extend the online obstacle replan
> -
> The replanning flexible dynamic mission is currently not what I expected. There are multiple issues. I think the issue is that, so, as I said above as well, you should structure between this basic flight and routes where you have, like, this pre-planned mission, and then I want another, like, mission cluster. So I don't want this, like, this single online obstacle replan mission within the basic flight and routes. I want you to introduce another mission cluster, which is just this, like, dynamic replanning thing. Of course, then the easiest one would be the one that you are currently doing, but there are multiple issues there. First of all, I think the issue is that you are still pre-planning a path. So this was valid for the first thing where we had a clear path, no obstacles, and everything. But the thing here is you only have, for the live iteration obstacle thing, you shouldn't pre-plan a path, because what you're doing right now is you're pre-planning a path, then an object appears, and then you go suddenly all the way to the right or to the left or whatever, which is physically also not possible, but it's not smooth. So that's the first thing. For example, you could slow down or you could go left, for example, very, like, smoothly, but you shouldn't, maybe this immediate, like, measure or avoidance thing would be, could be valid if, for example, it would be very close to the object. So the closer the object and the higher the velocity of the drone, then the more immediate this thing could be. Otherwise, you can also replan it very smoothly. So there should be this measurement as well, taking into account the velocity of the drone and also the distance to the object, which is then, of course, bound to a sensor measurement data, which is now known. And for the real drone, we have to see for obstacle avoidance. But this is just for mission planning right now. And then if the obstacle disappears, you go back to this center line. But this is the wrong approach because you should only have one start and one goal, like one start and one goal, and then you should always steer to that goal. Now, if there's no obstacles, then of course, the ideal line would be a straight line. But then if there's an obstacle, you should go around it smoothly. Then if there's another obstacle, you go around that one. Or if you can't go further, then, for example, you can also stop, you can relocate, you can turn, and then you can fly around it. So that should be this approach. So only, so it's really like an algorithm, for example. dyxtra algorithm or manhattan distance or something just like if you have tree branches when you steer to a goal or something. so for this mission cluster get rid of this preplanned mission and steering back to it. analze the csv as well, dont bother to plan other missions for now we have to get the reaction right first so keep this online obstacle thing just structure into this new mission cluster
>
> structure work packets for this

The following exact follow-up expands the stability and implementation-review scope:

> also fo9r the online obstacle it is not stable at all and it crashes often so the sim being down
>
> also i want you to analze the latest implementations espeically considering this online replanning bedcaue now the execution i think was fairly bad but so many tokens were burned

### Frozen intent/value and scope

- Minimum useful outcome: the existing local product remains recoverable across
  repeated realtime runs, and one online-obstacle mission flies from one start to one
  goal using only current perceived free space without an unnecessary stop for an
  ample-margin obstacle.
- Explicit value: compact the current 1D curriculum into five understandable major
  missions; expose the speed/accuracy/smoothness choice in plain controls; improve
  whole-route physical continuity; and connect a plotted anomaly to the exact drone
  position and source sample.
- Necessary prerequisites: truthful source/receive/realtime clock handling, continuous
  telemetry during plan/cutover work, immutable hard safety bounds, and an independent
  accepted-trajectory certificate.
- Scope priority: implement WP-62 first, then the smallest WP-64 motion-core slice
  needed by WP-66, then WP-66. Do not spend implementation time on the catalog polish,
  review cursor, wind fixture, or any new dynamic mission until the final WP-66
  realtime gate passes.
- Deferred: additional dynamic mission families, digital-twin calibration, hardware,
  live computer vision, mapping/SLAM, learned control, and physical-flight claims.
  The `Wind shift` name is reserved under `3D path` and remains
  `PLANNED_NOT_EXECUTABLE` until the online reaction gate passes; the existing
  source-timed force-impulse model is its future fixture boundary.

### Frozen development boundary and pre-freeze audit

- Branch: `codex/1d-replanning-digital-twin`.
- Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.
- `ACTIVE.md` preimage before this batch:
  `2fb892b71b06f97f33b8249e4496e055dc6a515e534fa447b8b0ff3ef4cff1bd`.
- Durable requirements postimage:
  `77c722f00a98b0e861393a096e8538dbc799ebd3348f10f873743b853aef767e`.
- UI-guide postimages: `design.md`
  `30628d07cb3476f74495fe4c12f81c4892d754bf944a92549f1a8b1cac8c234a`
  and `docs/project/DESIGN.md`
  `ece20b42853194b2e820bbfe2768f3c9d0731a6e9428d5ee5724aa7a795d7b05`.
- Machine-readable design audit:
  `missions/campaigns/sim/qualification/wp62-66-design-audit-v1.json`, 212,758
  bytes, SHA-256
  `0d48bce6b7b5326ba1a402e87ac8ed8a3e9318974650f14b5a8ec96f78099a16`.
- Audit program: `scripts/audit_wp62_66_design.py`, SHA-256
  `6fe8e3646008be372bbe0b661915d0039a4c8bd18a1165bb6bbf8185dd931dfd`.
- Reproduce exact group coverage, current evidence hashes, boundary closure, response
  arithmetic, reaction certificates, speed/distance monotonicity, and adverse cases:

```bash
.venv/bin/python scripts/audit_wp62_66_design.py \
  missions/campaigns/sim/qualification/wp62-66-design-audit-v1.json
```

The audit maps all 12 current 1D basic/route case IDs exactly once into the five
operator groups. Its boundary manifest contains 154 classified existing paths: direct
AST import discovery from five production roots contributes 59 paths and a clean
temporary generator run contributes 67 exact simulator/template/real-mirror outputs.
It also freezes eight absent/new implementation paths and binds both latest run
manifests, analyses, and CSVs by hash. These hashes intentionally include pre-existing
user edits in the shared dirty tree; implementation must preserve or explicitly
incorporate them and may not revert them.

### Latest-implementation and CSV assessment

The latest broad implementation commit `9621591` changed 88 files with 10,559 added
and 3,088 deleted lines. It combined motion, sensed replanning, motor evidence,
digital-twin/calibration, API, and UI work. Its independent implementation review and
focused recheck are exhausted with P1 findings, including the unconditional
stop-and-hold reaction and missing production connection of adaptive motion intent.
This successor therefore separates the minimum runtime/reaction path from the deferred
work instead of treating that broad commit as qualified.

| Evidence | Observed result |
|---|---|
| `campaign-run-dd31f5156c7ad2adbb67` | `ABORTED`; 308 CSV rows; no perceived obstacle; realtime factor `0.7762462302035557`; `TELEMETRY_STALE`/stale-fleet abort; terminal `EMERGENCY` |
| `campaign-run-b2657ba1f323a160070f` | `ABORTED`; 603 CSV rows; one observation and one replacement dispatch; realtime factor `0.7886796105394428`; the same stale-fleet abort; terminal `EMERGENCY` |

The second run perceived the obstacle at source `5.027430402413535 s` and receive
`5.147430402413535 s`. Planning took `0.08945066599972051 s`; total recorded reaction
was `0.310043290999347 s`; the old prefix certificate reported
`0.952651849579511 m` clearance. Nevertheless, production
`CampaignExecutionHead.run()` calls `stop_and_hold_for_replan()` for every accepted
observation before planning, and the evidence labeled the drone stopped while its
observed speed was still `0.16009514752424556 m/s` against a `0.02 m/s` stop
threshold. The replacement then formed a rectangular lateral detour from approximately
`(-1.223, 0.003, 0.400)` through `y=-0.382` to the original goal, rather than a
velocity-continuous local route from the current state.

Both analyses attribute the abort to a wall-clock watchdog expiring while the
source-clock schedule continued. Fleet freshness uses wall-clock time since the
supervisor's last telemetry receive, while replanning preempts the active command and
waits for planning/cutover. This is the evidence-backed likely integration cause; WP-62
must prove the exact publisher/clock defect through a failure-first test rather than
assume it. Neither CSV records a collision (`collision_count=0`); the later emergency
descent and approximately `2.294 m/s` raw vertical excursion explain the visual crash
impression but do not establish modeled physical impact.

The existing accelerated end-to-end test currently fails before perception with:

```text
ValueError: dynamic activation requires passing static baselines:
1d.point_to_point_relocation.canonical_nominal
```

The current worktree decouples review from lifecycle selection while that test still
assumes review approval supplies the prerequisite. WP-62 must repair the production
contract or its fixture explicitly; an accelerated component success remains
insufficient evidence for the realtime claim. At design time the backend and served UI
are reachable, but post-failure recoverability has not been demonstrated.

### WP-62 — realtime replanning runtime stability and recovery

**Status:** `DEFINED_NOT_STARTED`

**Independent verification:** `DRAFT_UNVERIFIED`

Own the source/receive/wall-clock boundary from Fast Sim telemetry publication through
the supervisor session and fleet freshness watchdog while planning and cutover work is
active. Remove false starvation caused by route preemption, task cancellation, or
blocking planner work. Preserve the existing `0.25 s` freshness limit and `0.8`
minimum realtime factor; changing either value is an oracle failure. Ensure every
terminal path performs bounded cleanup and leaves the API, simulator vehicle, Campaign
workspace, and next-run authority usable.

Required implementation slices:

1. Add a failure-first realtime test that reproduces the current stale abort while an
   observation is validated/planned/committed and traces the missing telemetry receive
   update to its production owner.
2. Make telemetry publication independent of the replanning command task, and compare
   source progress, receive freshness, and realtime performance on their correct
   clocks. Do not manufacture heartbeat samples or mark old data fresh.
3. Reconcile route cancellation, replacement authority, emergency/landing cleanup,
   active-run persistence, and the static-prerequisite lifecycle used by the true E2E
   fixture.
4. Retain health and authority evidence before the run, after every terminal result,
   and at the start of an immediate retry.

Exit evidence:

- Three consecutive `OPERATOR_OBSERVED_REALTIME` executions of the current online case
  reach at least the first two trusted observations without `TELEMETRY_STALE`,
  `STALE_FLEET_OBSERVATION`, timing-caused `EMERGENCY`, or a realtime factor below
  `0.8`. Each run may still fail on an explicit planner/motion gate before WP-66, but
  the failure must be recoverable and correctly classified.
- An immediate fourth run starts normally without process restart, stale authority,
  retained obstacle leakage, or a stuck active-run record; API health and the served
  Campaign workspace remain available after each terminal result.
- One isolated authoritative-telemetry dropout longer than `0.25 s` produces the
  expected single safe abort. A receive-clock-only delay, source-clock freeze, and
  planner compute pause are independently distinguishable in retained evidence.
- The corrected production E2E test enters the sensed-world path; accelerated-only
  success cannot close the packet. Exact pre/post CSV, faults, missing sequences,
  realtime factor, cleanup events, and service health are retained per repeat.

### WP-63 — five-major-mission 1D curriculum and plain preparation controls

**Status:** `DEFINED_NOT_STARTED`

**Independent verification:** `DRAFT_UNVERIFIED`

Add a versioned grouping registry over immutable cases and runs. The operator-facing
major missions and exact current mapping are:

| Major mission | Current variants |
|---|---|
| `Flight` | Take off, hover, land |
| `Target` | Move to target; move and return |
| `Level path` | Continuous waypoints; curved route; multi-goal/checkpoint route; boundary-constrained route |
| `3D path` | Altitude transition; wide altitude transition; reserved disabled `Wind shift` |
| `Shape` | Circle; rounded square; figure eight |

Normal preparation shows one `Balance` slider (`0..100`, default `50`) whose endpoints
are `Accuracy` and `Flow`. It resolves monotonically through each case's declared
feasible endpoints; it never changes hard guards. A closed `Tune` disclosure exposes
one-word `Speed`, `Accuracy`, and `Smoothness` sliders. `Speed` requests cruise speed,
`Accuracy` requests maximum soft-reference/tube deviation, and `Smoothness` requests
the relative acceleration/jerk/angular/motor-spread objective. Units, requested value,
resolved feasible value, and any binding safety cap appear beside the focused control.
A request such as `100 m` may permit a straight shortcut through admitted free space,
but it can never relax obstacles, vehicle geometry, flight volume, dynamics, actuator,
energy, or terminal guards.

Replace visible technical labels such as `Planner-retimed baseline` with the plain
control state. Remove routine `Eligible` badges. An unavailable variant is disabled
with one concise reason; internal submission/profile IDs, hashes, eligibility and full
resolution evidence remain in the closed technical disclosure. Persist the resolved
typed motion contract and its hash, not only slider positions.

Exit evidence:

- Machine tests prove all 12 current IDs appear exactly once under the five labels,
  reordered source files do not change grouping, a renamed/unknown case fails closed,
  and every retained run remains reachable under its immutable case ID.
- Slider endpoint/midpoint fixtures prove monotonic resolution, hard-bound capping,
  requested-versus-resolved retention, and that `100 m` cannot escape the volume or
  intersect an obstacle.
- Served desktop and narrow UI evidence covers keyboard sliders, disclosure, disabled
  reason, loading/empty/error states, focus return, and absence of `Eligible` and
  technical planner labels from the normal path.

### WP-64 — whole-route motion trade-offs and motor-realism regression

**Status:** `DEFINED_NOT_STARTED`

**Independent verification:** `DRAFT_UNVERIFIED`

Finish the reusable whole-route/receding-horizon motion capability that WP-58 did not
connect to production. Plan velocity, acceleration, jerk, and path deviation over the
meaningful future geometry from the current position/velocity/acceleration. Preserve
explicit `CHECKPOINT` holds while treating ordinary fly-through knots, equivalent
subdivision, and the figure-eight crossover as geometry rather than stop commands.
Resolve speed, tube/free-space accuracy, acceleration, jerk, angular activity,
individual-motor headroom/spread/saturation, energy, and terminal behavior together;
no single smoothness score may hide a hard regression.

The implementation priority inside WP-64 is only the shared motion core and curved /
figure-eight / altitude anchors required by WP-66. The reserved wind-shift fixture may
be enabled only after WP-66 passes, using the existing source-timed force impulse and
the same pre/post oracle; it does not authorize a new aerodynamic-fidelity claim.

Exit evidence:

- Equivalent collinear subdivision changes sampled geometry/time law by at most
  `1e-6 m`; an easy continuous bend and repeated-coordinate crossover retain at least
  `0.95` of their admitted approach speed, while a 100-degree bend visibly obeys the
  acceleration/jerk envelope instead of changing velocity instantaneously.
- At least `95%` of every declared steady window lies in its requested speed band;
  checkpoint dwell and continuous fly-through are each independently perturbed and
  verified.
- Three accelerated repeats per curved-route, figure-eight, and altitude anchor plus
  one realtime repeat per anchor retain the full pre/post vector from `REQ-EVI-013`.
  Every hard motion, safety, contact, motor, energy, and terminal guard passes every
  repeat; an average cannot hide a failure.
- An independently sampled trajectory oracle, not the production parameterizer,
  computes curvature, speed continuity, tracking, acceleration/jerk, and hard bounds.
  Raw CSV extrema reconcile with processed values, and individual motors show the
  signed differential response expected from body acceleration without saturation or
  reduced headroom relative to the retained baseline.

### WP-65 — source-time graph-to-flight review cursor

**Status:** `DEFINED_NOT_STARTED`

**Independent verification:** `DRAFT_UNVERIFIED`

Replace independent static chart inspection with one retained source-sequence cursor
shared by all Campaign review plots and the room/replay marker. Clicking, tapping, or
keyboard-moving a velocity-profile bump selects the nearest actual CSV source sample,
not a screen-space estimate. The focused readout shows source sequence/time, exact
recorded position, accepted plan/reference sample, commanded and observed velocity,
IMU, individual motors, perceived objects, replan/cutover identity, and safety state
available at that sequence. Missing fields are `Unavailable`; derived or interpolated
values state their method and never present as exact measurements.

Exit evidence:

- A fixture with a unique velocity bump and deliberately offset receive timestamps
  selects the correct source sequence and exact position; reordering CSV rows,
  duplicate receive times, missing channels, and an interpolation gap do not move or
  fabricate the source truth.
- Every graph shares the cursor, retains unit/source/quality labels, has a text
  alternative and keyboard operation, and can expand without turning the entire chart
  into a conflicting button target.
- Served desktop/narrow/reduced-motion evidence proves velocity-bump selection moves
  the room marker and shows the same source sequence across plot, spatial view, and
  download row.

### WP-66 — start-goal dynamic replanning cluster and online-obstacle mission

**Status:** `DEFINED_NOT_STARTED`

**Independent verification:** `DRAFT_UNVERIFIED`

Add the enum/API/catalog/UI cluster `DYNAMIC_REPLANNING`, labeled `Dynamic
replanning`, and move only `1d.online_obstacle_replan.dynamic_nominal` into it. Do not
add or plan another dynamic mission in this batch. Replace that case's route intent
with a goal-seeking contract containing one start state, one goal/landing region,
immutable safety/dynamics bounds, and the current perceived-world generation. Supplying
an authored reference route, centerline, or rejoin waypoint is rejected. Historical
case and run identities remain inspectable; a versioned successor contract records the
semantic change.

Use a bounded A* free-space corridor search over `0.05 m` X/Y cells and eight headings.
Its primitive family is exactly the eight adjacent cells; diagonal corner cutting is
forbidden and obstacles are inflated by the `0.055 m` nominal radius, `0.05 m`
uncertainty, and `0.15 m` policy clearance. Its lexicographic cost is path length in
metres, integrated absolute heading change in radians, negative minimum clearance in
metres, then canonical state key. Euclidean distance is the admissible primary-cost
heuristic. The hard bounds are 8,192 expansions and `0.09 s`; either exhaustion returns
`NO_COMMAND_BUDGET_EXHAUSTED`. Neighbor/candidate enumeration order and obstacle IDs
cannot affect the selected point vector. A found corridor is not motion authority: the
WP-64 layer must build a position/velocity/acceleration-continuous trajectory from the
fresh committed state and the independent `0.01 m` swept sampler must certify it;
failure rejects the corridor.

The exact prototype returns a `2.6 m` no-obstacle path after 52 expansions and a
`3.01421356238 m` obstacle path with `2.356194490191 rad` integrated turn,
`0.3 m` minimum center clearance, and 4,060 expansions. Reversed candidate enumeration
and renamed obstacle IDs return the identical point vector. Removing the obstacle from
the frozen current state reduces path length from `2.419238815547 m` to `1.8 m`.
One-expansion exhaustion returns `BUDGET_EXHAUSTED`; an enclosing wall proves
`NO_SOLUTION` after 2,530 expansions. Recede and repeat this process on every accepted
addition, movement, or removal; never optimize return to an old line.

Response urgency uses the exact audited relation:

```text
T = sense/process + validate + plan + acknowledge + commit
response_distance = speed*T + jerk_limited_stop_distance(speed, acceleration, jerk)
required_surface_distance = vehicle_radius + uncertainty + policy_clearance
                            + response_distance
margin = perceived_center_to_surface_distance - required_surface_distance
urgency = clamp(1 - margin/0.25 m, 0, 1)
```

The hard independent certificates remain authoritative over this scheduling measure.
With zero initial acceleration, `1.0 m/s²` acceleration and `8.0 m/s³` jerk, the
independent oracle derives a `0.105 m` jerk-limited stop from `0.4 m/s`. At `T=0.33 s`,
the `0.95 m` witness therefore has exactly `0.458 m` margin and urgency `0`, so it
continues with a moving replan. At the same speed, `0.50 m` yields `0.008 m` margin and
urgency `0.968`, so it blends jerk-limited deceleration/turn; `0.35 m` has `-0.142 m`
margin and no certified braking/hold/abort response, so it fails closed instead of
claiming avoidance. At `0.2 m/s` and `0.50 m`, the derived stop is `0.0325 m`, margin is
`0.1465 m`, and urgency is `0.414`, proving speed as well as distance affects response.

No command is selected from a caller-supplied certificate flag. The audit independently
samples the braking route at `0.01 m`, computes the invariant hold set, samples the
vertical abort route, authenticates the payload hash, and evaluates source/receive
freshness and generation. Separate full witnesses cover stale generation, late source,
late receive, tampering, a certified hold, a certified abort/land, and a state with no
certified response. Every route/hold/abort/decision certificate has its own computed
hash and pass/fail output.

Exit evidence:

- Schema and production-trigger tests reject authored route/centerline/rejoin input and
  prove the initial planner cannot observe future obstacle geometry or event timing.
- With no obstacle the certified plan approaches the straight start-goal solution.
  With the nominal obstacle it continues moving through a smooth detour without an
  unconditional `stop_and_hold_for_replan`; obstacle removal shortens safe goal cost
  from the current state without returning to the old centerline.
- Independent perturbations cover left/right choice, changed obstacle geometry,
  high-speed/near obstacle, late/stale/tampered update, no solution, safe hold,
  turn/relocate, and abort/land. Candidate exhaustion never dispatches an uncertified
  route.
- Three consecutive realtime runs process all four current sensor events, dispatch
  acknowledged continuous replacements, reach the goal, land/disarm, pass every
  motion/safety/physical guard, meet realtime factor `>=0.8`, and leave the next run
  healthy. One deliberately late event triggers the exact certified fallback. Every
  repeat retains raw CSV, response arithmetic, candidate/rejection set, certificate,
  cutover, post-cutover tracking, motor evidence, and terminal result.
- The qualification guard registry contains 28 direction-aware metrics derived from
  `MotionQualityContract`, WP-62, WP-64, and WP-66: speed-band coverage/ripple, path
  tube, acceleration, jerk, angular rate, motor headroom/spread/saturation/differential
  sign and magnitude, energy, clearance/contact, checkpoint/continuous/crossover
  semantics, unintended stops, terminal peak/reversals/duration/state, supervisor,
  goal/landing error, realtime factor, and stale aborts. A full passing vector plus one
  isolated failing override per metric proves every comparator is sensitive; every
  required repeat must pass every applicable guard.

### Claim, counterexample, and production-boundary matrix

| Claim | Intended production path | Independent oracle and counterexample | Required boundary |
|---|---|---|---|
| WP-62 truthful/recoverable realtime execution | Campaign Play → runtime executor → simulation telemetry → supervisor session → fleet freshness → terminal cleanup → immediate retry | Independent source/receive sequence monitor; real dropout must abort while planner pause must not | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |
| WP-63 compact preparation | Catalog generation → API models → Campaign catalog → resolved motion contract | Exact 12-ID set oracle; reorder/unknown case, `100 m` cap, and disabled choice | `PRODUCTION_ENTRY / NO_RUNTIME / NOT_APPLICABLE`, plus served UI |
| WP-64 whole-route motion | Prepared motion contract → planner → sampled trajectory → runtime commands → CSV/analyzer | Independent arc-length/dynamics sampler; subdivision, crossover, checkpoint, hard bend, motor-sign perturbations | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME` |
| WP-65 exact review cursor | Retained CSV/evidence → API → review plots → room/replay marker | Exact source-sequence lookup; row reorder, duplicate receive time, missing/interpolated channel | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`, plus served UI |
| WP-66 goal-seeking online replanning | Dynamic cluster Play → sensed observation → perceived world → urgency/search → independent certificate → acknowledged cutover → goal/landing | Independent geometry/clock certificate; route-input rejection, nominal/near/late/tampered/no-solution/removal cases | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |

The machine audit carries classified claim-owner paths, AST-discovered direct
production transits, preimage hashes, relied-upon tests, and generator outputs derived
by executing the current generator into a clean temporary root and comparing every
result with the repository, plus absent/new test, curriculum, and dynamic-cluster
paths. The audit explicitly includes perception, scenario, execution, sensors, Safety
Supervisor, API runtime/telemetry cleanup, public campaign API models, Control Center,
served page, generated API client, and all current simulator/template/real-mirror
outputs. Any implementation-owned path absent from these independently derived sets
requires an explicit design revision. The later implementation manifest freezes every
changed/new/deleted path with pre/post hashes and preserves unrelated dirty-tree edits.

### Dependency, completion, and non-goals

The value-first implementation order is WP-62, the minimal reusable WP-64 core, and
WP-66. WP-63 and WP-65 follow only after the final WP-66 realtime gate; the wind-shift
fixture follows those and remains disabled in this design. WP-65 depends on WP-62's
stable retained evidence. WP-66 depends on WP-62 and the WP-64 continuity core. No
packet can claim another packet's exit evidence.

This design authorizes no implementation, service restart, mission run, history
transition, commit, push, hardware action, digital-twin calibration, or new dynamic
mission. A later implementation request begins only from a recorded
`DESIGN_VERIFIED` identity and must use a fresh implementation verifier.

<!-- WP62-66-DESIGN-PAYLOAD-END -->

### WP-62 through WP-66 design-review handoff

- Initial design identity: 27,245-byte payload SHA-256
  `46ba656c0a76b3a4fa75e793eb9115b604ef20c4200aa70f7d87f96f956ba0f3`.
- Initial review: fresh read-only verifier `/root/wp62_66_design_review` returned
  `BLOCKED_WITH_FINDINGS` on 2026-08-14 with no P0 and four P1 `MUST_FIX_NOW`
  findings: caller-authored fallback/certificate flags and contradictory arithmetic;
  underspecified/unfalsifiable search; self-reconciled boundary lists that omitted
  production owners; and an incomplete, insensitive motion/motor guard registry.
- Sole consolidated author correction: consumed. The correction replaces braking with
  a jerk-limited derivation; independently samples route, hold, abort, and decision
  certificates; adds isolated stale/late/tampered/hold/abort/no-certificate witnesses;
  freezes the exact A* lattice, cost, heuristic, bounds, deterministic invariances and
  numerical outputs; derives imports with AST and all generator outputs through a clean
  temporary run; classifies 154 manifest paths; and prototypes all 28 required guards
  with one isolated failure each.
- Corrected design identity: 30,040-byte payload SHA-256
  `52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6`.
- Corrected audit identity: 212,758-byte artifact SHA-256
  `0d48bce6b7b5326ba1a402e87ac8ed8a3e9318974650f14b5a8ec96f78099a16`;
  audit program SHA-256
  `6fe8e3646008be372bbe0b661915d0039a4c8bd18a1165bb6bbf8185dd931dfd`.
- Focused recheck: consumed by the same verifier. The independent verdict is
  `BLOCKED_WITH_FINDINGS`; no implementation or third automatic design pass is
  permitted.
- Resolved initial P1s: fallback/certificate decisions now come from independent
  executable geometry/clock oracles rather than caller booleans, and affected
  boundaries now derive from production imports and a clean generator run rather than
  self-reconciled lists.
- Remaining P1 `MUST_FIX_NOW` in WP-66 search evidence: the prototype freezes a
  `0.09 s` wall budget but has no wall-time cutoff. Independent timing measured the
  4,060-expansion obstacle witness at median `0.313 s` and the 2,530-expansion
  no-solution witness at median `0.136 s`; both currently return a completed result
  instead of `BUDGET_EXHAUSTED`. The frozen search claim therefore does not satisfy its
  own bound.
- Remaining P1 `MUST_FIX_NOW` in the shared WP-64/WP-66 guard vector: the 28-metric
  registry includes maximum path-tube error but omits retained `tracking_rms_m`, despite
  `REQ-EVI-013` and the packet exit requiring tracking. Persistent RMS degradation
  could pass the declared registry.
- Final state: all five packets remain `DEFINED_NOT_STARTED / REVIEW_BLOCKED`. The
  frozen corrected payload stays identified by SHA-256
  `52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6`;
  the status/verdict text above is the permitted mechanical closeout record. A new
  operator-authorized design iteration is required to change the search budget/proof
  and guard universe before implementation.

<!-- WP62-66-R2-DESIGN-PAYLOAD-BEGIN -->

## WP-62 through WP-66 R2 implementation-entry correction

### Frozen authorization and scope

The exact operator authorization for this successor iteration is:

> ok then start implementation

Implementation remains conditional on `DESIGN_VERIFIED`. This R2 overlay changes only
the two P1 `MUST_FIX_NOW` findings left by the exhausted base-design recheck. It does
not reopen resolved findings, change the five packets, add a dynamic mission, enable
wind shift, expand hardware/digital-twin scope, or alter unrelated user work.

- Base design: 30,040 bytes, SHA-256
  `52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6`.
- R2 audit: `missions/campaigns/sim/qualification/wp62-66-r2-design-audit-v1.json`,
  121,075 bytes, SHA-256
  `6960c59284a0d98ed28492cd187c6e16805b939f22fa041a2ce683f6d1ea687f`.
- R2 audit program: `scripts/audit_wp62_66_r2_design.py`, SHA-256
  `d694035b002db0754d87aa6c5a5eb647b8f1e702073cdcea4996f222f340862a`.
- Reproduce the composite correction:

```bash
.venv/bin/python scripts/audit_wp62_66_design.py \
  missions/campaigns/sim/qualification/wp62-66-design-audit-v1.json
.venv/bin/python scripts/audit_wp62_66_r2_design.py \
  missions/campaigns/sim/qualification/wp62-66-r2-design-audit-v1.json
```

### R2-A — enforced, feasible search timing

The deterministic expansion bound remains 8,192. The hard wall-clock search budget is
corrected from the disproven `0.09 s` to `0.5 s`, which remains inside the immutable
case planning budget of `2.0 s`. The deadline covers all search and independent path
certification work: the search checks `time.monotonic()` before every expansion and
again after certification, before publishing a path. Reaching either bound returns
`BUDGET_EXHAUSTED / NO COMMAND`; it may not finish or report a plan after the deadline.

The exact same 4,060-expansion obstacle witness completes with its unchanged certified
`3.01421356238 m` path. Five pre-freeze wall-time samples are
`(0.22960458399938943, 0.22534387499945296, 0.22835112500069954,
0.22378625000055763, 0.2245147920002637) s`. The enclosing-wall no-solution witness
completes after 2,530 expansions with samples
`(0.13022362499941664, 0.13043441599984362, 0.1305727079998178,
0.12966625000080967, 0.12972999999874446) s`. Every retained sample is below `0.5 s`.
A zero-wall-budget perturbation performs zero expansions and returns
`BUDGET_EXHAUSTED`, proving the expansion-side wall check is behavior-driving. A
separate straight-path witness injects `0.51 s` only during certification and must
discard the otherwise valid path as `BUDGET_EXHAUSTED / NO COMMAND`, proving the
post-certificate check. The audit independently reruns the exact output witnesses three
times and rejects any result/path/hash change.

The conservative reaction envelope now uses the complete corrected maximum:

```text
T = 0.12 sense/process + 0.02 validate + 0.50 search
    + 0.0006 acknowledge + 0.0994 commit = 0.74 s
```

At `0.4 m/s`, the retained jerk-limited stop distance is `0.105 m`, so response
distance is `0.401 m` and required protected surface distance is `0.656 m`. The
`0.95 m` nominal observation retains `0.294 m` margin and urgency `0`; the `0.75 m`
witness has `0.094 m` margin and urgency `0.624`; `0.50 m` is insufficient with
`-0.156 m` margin and urgency `1`. At `0.2 m/s` and `0.75 m`, required distance is
`0.4355 m`, margin is `0.3145 m`, and urgency is `0`. These values replace only the
base payload's superseded `0.09 s` timing and dependent reaction numbers.

The R2 audit regenerates the complete eleven-witness reaction set at `T=0.74 s`, not
only the scalar envelope. Every witness freezes source/receive/generation clocks,
vehicle state, protected-distance terms, search result, braking-path certificate,
hold certificate, vertical abort certificate, selected command, and a hash of the full
decision. The nominal, progressive, lower-speed, and insufficient-clearance commands
are respectively `CONTINUE_WITH_MOVING_REPLAN`,
`JERK_LIMITED_DECELERATE_AND_TURN`, `CONTINUE_WITH_MOVING_REPLAN`, and
`NO_CERTIFIED_RESPONSE_FAIL_CLOSED`. Stale-generation, late-source, late-receive, and
tampered observations are rejected into a certified hold. The three blocked-goal
child cases select `CERTIFIED_HOLD`, `CERTIFIED_ABORT_AND_LAND`, and
`NO_CERTIFIED_RESPONSE_FAIL_CLOSED`. These R2 witnesses supersede the base payload's
`T=0.33 s` clocks, distance terms, commands, and hashes wherever they depend on search
timing; the immutable base artifact remains provenance rather than executable R2 truth.

Implementation and exit evidence must enforce both bounds through the production
planner clock. A test-injected `0 s`/expired deadline and an expansion-limit fixture
must dispatch no replacement. Five local production repeats of the obstacle and
no-solution searches must each complete below `0.5 s`; a faster median cannot hide one
deadline miss. Runtime evidence records actual planning time and the budget disposition.

### R2-B — complete tracking guard

Add `tracking_rms_m <= 0.05 m` to the shared WP-64/WP-66 qualification guard vector.
It is distinct from maximum path-tube error: RMS detects persistent degradation while
the maximum detects a localized excursion. The full registry now contains 29 unique,
direction-aware metrics.

The complete passing vector uses `tracking_rms_m=0.049`; its isolated failure changes
only that key to `0.051`, which must reject qualification while the other 28 guards
remain passing. Conversely, every other isolated failure retains tracking RMS at
`0.049`. The implementation analyzer, evaluation, review bundle, CSV comparison, and
qualification gate must treat a missing RMS value as failure whenever tracking applies.
Every accelerated and realtime repeat passes RMS individually; aggregate or median
tracking cannot hide a failed run.

Tracking RMS applies to every `MotionQualityContract` repeat and has no N/A branch.
The exact required repeat identities are `accelerated-1`, `accelerated-2`,
`accelerated-3`, and `realtime-1`. Qualification requires all four records, each with
`applicable=true`, a non-null value, and `tracking_rms_m <= 0.05 m`. The audit executes
the passing vector `(0.047, 0.048, 0.049, 0.049)` and proves four distinct failures:
one missing record, an attempted `applicable=false`/N/A record, one `0.051 m` repeat,
and an aggregate-cheat vector `(0.049, 0.049, 0.049, 0.053)` whose arithmetic mean is
exactly `0.05 m` but whose realtime repeat still fails.

### R2 implementation entry

After this composite design is independently verified, implementation begins in the
already frozen value order: WP-62 runtime stability, the minimum WP-64 motion core,
then WP-66 online goal-seeking replanning. WP-63 and WP-65 remain after the WP-66
realtime gate. The later implementation manifest must bind the verified base+R2 design
identities, preserve all pre-existing dirty-tree changes, and enter a fresh independent
implementation gate before any packet can become verified or complete.

**Status:** `DEFINED_NOT_STARTED`

**Independent verification:** `DRAFT_UNVERIFIED`

<!-- WP62-66-R2-DESIGN-PAYLOAD-END -->

### WP-62 through WP-66 R2 design-review handoff

- Initial R2 payload submitted for review: 5,074 bytes, SHA-256
  `783bd2e4d1fbbc4b1a3f238a31e325b86350a4a5beb7b072ba631155b2b94fb8`.
- Independent design verifier: `/root/wp62_66_r2_design_review`
  (`work_packet_verifier`, fresh for this successor design).
- Initial verdict: `CHANGES_REQUIRED` with three P1 findings: the deadline did not
  include post-search certification, the corrected scalar reaction latency did not
  regenerate the complete dependent witness/certificate set, and tracking RMS lacked
  executable repeat/applicability semantics.
- Sole consolidated author correction: consumed. It adds a post-certificate hard-wall
  failure witness, regenerates and hashes all eleven reaction decisions at `T=0.74 s`,
  and executes missing/N/A/per-repeat/aggregate-cheat tracking cases.
- Corrected R2 payload: 7,092 bytes, SHA-256
  `4201ea8a858e1d91b3f5877bdfacbd4716b5fa59b42cac9ac9d796cf38477806`.
- Corrected audit artifact: 121,075 bytes, SHA-256
  `6960c59284a0d98ed28492cd187c6e16805b939f22fa041a2ce683f6d1ea687f`.
- Corrected audit program: SHA-256
  `d694035b002db0754d87aa6c5a5eb647b8f1e702073cdcea4996f222f340862a`.
- Focused recheck: consumed by the same verifier. The independent verdict is
  `BLOCKED_WITH_FINDINGS`; a third automatic pass is not permitted.
- Resolved on recheck: the hard deadline now covers certification and returns no
  command, and all eleven `T=0.74 s` reaction decisions and subordinate certificates
  independently recompute to the frozen commands and hashes.
- Remaining P1 `MUST_FIX_NOW`: the RMS evaluator keys only the unscoped IDs
  `accelerated-1..3` and `realtime-1`. Duplicate IDs across the curved-route,
  figure-eight, and altitude anchors can overwrite a failed repeat; WP-66's required
  `realtime-2` and `realtime-3` are treated as unexpected; and non-finite `NaN` passes
  the current numeric comparison. The executable repeat identity must include packet,
  case/anchor, mode, and ordinal; reject duplicates, missing/unexpected records,
  non-finite values, and every per-run threshold failure.
- Independent verification: `BLOCKED_WITH_FINDINGS`.

<!-- WP62-66-R3-DESIGN-PAYLOAD-BEGIN -->

## WP-62 through WP-66 R3 repeat-universe correction

### Frozen authorization, provenance, and scope

The exact operator authorization for this successor correction and implementation is:

> ok yes i authorize

This overlay corrects only the remaining R2 P1 concerning executable per-repeat
tracking RMS identity and fail-closed evaluation. It does not reopen the independently
resolved R2 search-deadline or reaction-certificate findings, change any mission
semantics, add a case, enable wind shift, or expand the implementation boundary.

- Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.
- Base design payload: 30,040 bytes, SHA-256
  `52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6`.
- R2 design payload: 7,092 bytes, SHA-256
  `4201ea8a858e1d91b3f5877bdfacbd4716b5fa59b42cac9ac9d796cf38477806`.
- `ACTIVE.md` preimage before R3: SHA-256
  `5ec66c3387cd076ffa51c019b00d31c565c5a49222b53ee2674094a927143ad2`.
- Durable requirements and UI-guide identities remain unchanged:
  `docs/project/WORKFLOW_AND_REQUIREMENTS.md`
  `77c722f00a98b0e861393a096e8538dbc799ebd3348f10f873743b853aef767e`,
  `design.md`
  `30628d07cb3476f74495fe4c12f81c4892d754bf944a92549f1a8b1cac8c234a`,
  and `docs/project/DESIGN.md`
  `ece20b42853194b2e820bbfe2768f3c9d0731a6e9428d5ee5724aa7a795d7b05`.
- R3 audit artifact:
  `missions/campaigns/sim/qualification/wp62-66-r3-design-audit-v1.json`,
  96,549 bytes, SHA-256
  `4a0d9b3e665ba1b1a8d29450368cfc5c7b334d5749419f1a4a18f49b4fb56d46`.
- R3 audit program: `scripts/audit_wp62_66_r3_design.py`, SHA-256
  `71fb40f59ab0c519a2179c18b7cd25d6f1211c5fe49016b15ad486adc1acc52a`.
- Reproduce the exact R3 policy and counterexamples with:

```bash
.venv/bin/python scripts/audit_wp62_66_r3_design.py \
  missions/campaigns/sim/qualification/wp62-66-r3-design-audit-v1.json
```

### Exact tracking-RMS repeat universe

`tracking_rms_m <= 0.05 m` remains required and has no N/A branch. A repeat identity
is the exact tuple `(packet_id, case_id, mode, ordinal)`; labels such as
`accelerated-1` alone are invalid. The complete expected universe is:

| Packet and case | Mode | Required ordinals |
|---|---|---|
| WP-64 — `1d.curved_route.canonical_nominal` | `AUTOMATED_ACCELERATED` | 1, 2, 3 |
| WP-64 — `1d.curved_route.canonical_nominal` | `OPERATOR_OBSERVED_REALTIME` | 1 |
| WP-64 — `1d.planar_shape_loop.figure_eight` | `AUTOMATED_ACCELERATED` | 1, 2, 3 |
| WP-64 — `1d.planar_shape_loop.figure_eight` | `OPERATOR_OBSERVED_REALTIME` | 1 |
| WP-64 — `1d.altitude_transition.canonical_nominal` | `AUTOMATED_ACCELERATED` | 1, 2, 3 |
| WP-64 — `1d.altitude_transition.canonical_nominal` | `OPERATOR_OBSERVED_REALTIME` | 1 |
| WP-66 — `1d.online_obstacle_replan.dynamic_nominal` | `OPERATOR_OBSERVED_REALTIME` | 1, 2, 3 |

The universe therefore contains 15 distinct records. Qualification rejects duplicate,
missing, unexpected, or malformed identities before aggregation. It also rejects
`applicable` unless it is exactly `true`, missing/non-numeric values, every non-finite
value including `NaN`, positive infinity, and negative infinity, and any finite value
below zero or above `0.05 m`. Identity records contain exactly the four declared
fields; packet, case, and mode have exact non-empty string types, while the ordinal has
exact Python/JSON integer type and is at least one. Booleans and integral-looking
floats are not ordinals. Qualification handles every malformed record as retained
rejection output rather than raising or aborting evaluation; oversized integers are
compared without a lossy float conversion. Every record is evaluated even after
another failure; insertion order cannot change the outcome. No dictionary overwrite,
mean, median, percentile, or packet-level aggregate may substitute for the individual
comparisons.

The R3 audit executes all 15 passing identities and proves reordering invariance. Its
isolated adverse cases cover the exact R2 counterexample—a failing duplicate followed
by a passing duplicate—plus a missing WP-66 realtime ordinal 2, unexpected WP-66
ordinal 4, attempted N/A, one `0.051 m` run, `NaN`, both infinities, and an
aggregate-cheat vector whose mean remains below `0.05 m` while one repeat is `0.053 m`.
The sole correction adds isolated scalar/missing-field/extra-field identity records,
a non-mapping record, Boolean and float ordinals, missing and standalone non-numeric
values, negative RMS, and an oversized integer. Each case retains its exact rejection
reason, and every adverse case fails without an exception. The repeated ordinals
across distinct WP-64 case IDs remain valid because case and packet are part of the
identity.

### R3 implementation entry

Once this base+R2+R3 composite is independently `DESIGN_VERIFIED`, the existing
implementation authorization becomes active. Work begins with WP-62 runtime stability,
then the minimum WP-64 continuity core and WP-66 online goal seeking. WP-63 and WP-65
remain gated behind the WP-66 realtime result. The implementation manifest and fresh
implementation verifier must bind all three design identities and preserve unrelated
dirty-tree work.

**Status:** `DEFINED_NOT_STARTED`

**Independent verification:** `DRAFT_UNVERIFIED`

<!-- WP62-66-R3-DESIGN-PAYLOAD-END -->

### WP-62 through WP-66 R3 design-review handoff

- Initial R3 payload: 4,483 bytes, SHA-256
  `94e039ef8c15c383b393e14ddb2a0c8b2ce9f414a18a04893089f9ae3d60f232`.
- Independent design verifier: `/root/wp62_66_r3_design_review`
  (`work_packet_verifier`, fresh for R3).
- Initial verdict: `CHANGES_REQUIRED` with one P1: incomplete schema validation
  accepted Boolean/float ordinals and negative RMS, raised on malformed/oversized
  inputs, and lacked isolated malformed/missing/non-numeric witnesses.
- Sole consolidated correction: consumed. It enforces exact identity and evidence
  field types, non-negative finite RMS, total no-throw rejection, and retained exact
  reasons for all requested boundary cases.
- Corrected R3 payload: 5,216 bytes, SHA-256
  `5c24eb560133232cf5fb9e7a5105a727083f78854f07cba85c86c2d5ee6c3b5d`.
- Corrected audit artifact: 96,549 bytes, SHA-256
  `4a0d9b3e665ba1b1a8d29450368cfc5c7b334d5749419f1a4a18f49b4fb56d46`.
- Corrected audit program: SHA-256
  `71fb40f59ab0c519a2179c18b7cd25d6f1211c5fe49016b15ad486adc1acc52a`.
- Focused recheck: consumed by the same verifier. The independent verdict is
  `BLOCKED_WITH_FINDINGS`; a third automatic pass is not permitted.
- Resolved on recheck: all original schema counterexamples now return the exact
  retained rejection without exceptions, including malformed/non-mapping records,
  Boolean/float ordinals, missing/string/Boolean/negative/non-finite RMS, and an
  oversized RMS integer.
- Remaining P1 `MUST_FIX_NOW`: a positive ordinal such as `10**9999` passes the exact
  integer-type check, then raises during diagnostic string conversion instead of
  returning `UNEXPECTED` plus the corresponding `MISSING` identity. The identity
  validator must bound ordinals to the declared repeat universe before any string
  conversion and retain this oversized-ordinal rejection witness.
- Independent verification: `BLOCKED_WITH_FINDINGS`.

<!-- WP62-66-R4-DESIGN-PAYLOAD-BEGIN -->

## WP-62 through WP-66 R4 bounded-identity correction

### Frozen authorization and provenance

The exact operator authorization for this successor correction and implementation is:

> ok yes i authorize

R4 changes only the remaining oversized-ordinal failure in the executable tracking-RMS
qualification policy. It inherits the packet scope, boundaries, durable requirements,
search timing, reaction witnesses, 15-repeat universe, and all other accepted
base/R2/R3 decisions without reopening them.

- Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.
- Base design SHA-256:
  `52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6`.
- R2 design SHA-256:
  `4201ea8a858e1d91b3f5877bdfacbd4716b5fa59b42cac9ac9d796cf38477806`.
- Corrected R3 design SHA-256:
  `5c24eb560133232cf5fb9e7a5105a727083f78854f07cba85c86c2d5ee6c3b5d`.
- `ACTIVE.md` preimage before R4: SHA-256
  `f02383fe28acd963a6f9ea9abedd3043451629ddbd3bcaf14446b3eb5424fae8`.
- R4 audit artifact:
  `missions/campaigns/sim/qualification/wp62-66-r4-design-audit-v1.json`,
  122,248 bytes, SHA-256
  `dc09f1af28b9439b9c88c8e1e39682c87579b6a1564cbf7c5cc2578812da71ee`.
- R4 audit program: `scripts/audit_wp62_66_r4_design.py`, SHA-256
  `d7f72cb0cf422f47fc9f2586178bb04f17898b376415b5adc5f75a94b447b810`.
- Reproduce with:

```bash
.venv/bin/python scripts/audit_wp62_66_r4_design.py \
  missions/campaigns/sim/qualification/wp62-66-r4-design-audit-v1.json
```

### Bounded identity before diagnostics

The repeat identity remains `(packet_id, case_id, mode, ordinal)`. Before membership
testing, hashing, sorting, or diagnostic conversion, the evaluator requires exactly
those four fields, non-empty strings bounded respectively to 5, 96, and 32 characters,
and an exact non-Boolean integer ordinal in the closed interval `1..3`. Values outside
that schema return `INVALID_IDENTITY` using only the bounded record index; untrusted
identity values are never formatted. A schema-valid bounded identity that is absent
from the exact 15-record universe returns `UNEXPECTED`, and its expected counterpart
remains `MISSING`.

The audit replays every R3 success and adverse class, including order invariance,
duplicate overwrite, missing/unexpected identities, N/A, malformed identities and
records, Boolean/float/zero/four ordinals, missing/non-numeric/Boolean/negative/
non-finite RMS, oversized RMS, threshold failure, and aggregate masking. It adds the
exact `ordinal=10**9999` counterexample and an overlong identity string; both return
retained `INVALID_IDENTITY` plus the missing expected identity without raising. It
also rejects a non-list record container. Serialization records injected non-JSON
numbers by bounded descriptors rather than converting their complete decimal value.

### R4 implementation entry

If the base+R2+R3+R4 composite is independently `DESIGN_VERIFIED`, the existing
authorization immediately opens implementation in the frozen order: WP-62, minimum
WP-64, WP-66, then WP-63 and WP-65. The later exact implementation manifest and fresh
implementation verifier bind all four design hashes and preserve unrelated dirty-tree
work.

**Status:** `DEFINED_NOT_STARTED`

**Independent verification:** `DRAFT_UNVERIFIED`

<!-- WP62-66-R4-DESIGN-PAYLOAD-END -->

### WP-62 through WP-66 R4 design-review handoff

- Initial R4 payload: 3,221 bytes, SHA-256
  `34d6640165a86a86ad741fbc16202f4f4ec22fe6a06f18de701bec6900a99a1b`.
- Independent design verifier: `/root/wp62_66_r4_design_review`
  (`work_packet_verifier`, fresh for R4).
- Independent verdict: `DESIGN_VERIFIED` with no P0, P1, or P2 findings. The verifier
  independently reproduced every frozen identity and the pre-R4 ledger preimage,
  exercised huge positive/negative ordinals, bounded/unbounded strings, renamed and
  absent children, both duplicate orders, field and record reordering, all inherited
  malformed/non-finite cases, and aggregate masking.
- No author correction or focused recheck was consumed.
- Independent verification: `DESIGN_VERIFIED`.

## WP-62 through WP-66 implementation candidate

<!-- WP62-66-IMPLEMENTATION-PAYLOAD-BEGIN -->

This section is the author-frozen implementation candidate for the accepted base + R2
+ R3 + R4 design. It does not alter any accepted design payload. The exact file and
section identities are retained separately in
`missions/campaigns/sim/qualification/wp62-66-implementation-manifest-v1.json`.

| Packet | Status | Independent verification |
| --- | --- | --- |
| WP-62 — realtime replanning runtime stability and recovery | `IMPLEMENTED` | `IMPLEMENTED_UNVERIFIED` |
| WP-63 — five-major-mission 1D curriculum and plain preparation controls | `IMPLEMENTED` | `IMPLEMENTED_UNVERIFIED` |
| WP-64 — whole-route motion trade-offs and motor-realism regression | `IMPLEMENTED` | `IMPLEMENTED_UNVERIFIED` |
| WP-65 — source-time graph-to-flight review cursor | `IMPLEMENTED` | `IMPLEMENTED_UNVERIFIED` |
| WP-66 — start-goal dynamic replanning cluster and online-obstacle mission | `IMPLEMENTED` | `IMPLEMENTED_UNVERIFIED` |

### Initial implementation-review verdict and sole correction

The first fresh implementation verifier returned `BLOCKED_WITH_FINDINGS`. Its six P1
findings were accepted as the correction scope: no production-path telemetry-dropout
abort/cleanup/retry evidence; no `100 m` Accuracy obstacle boundary; raw kinematics and
tracking-oracle qualification that could mask failure; timestamp-only sibling-chart
selection; author-asserted rather than served UI evidence; and replacement commit that
accepted caller-supplied acknowledgement sets before real Supervisor dispatch.

This is the single permitted author correction. It adds a production dropout and
immediate-retry run, the `100 m` hard-boundary child case, raw/processed gate
reconciliation plus an independent source-time quintic P/V/A oracle, exact
timestamp-and-sequence cursor joins, retained served-browser screenshots, and
hash-bound Supervisor preparation receipts that must be consumed for the exact active
and replacement trajectories before atomic commit. A missing or tampered receipt
produces zero commits and zero replacement dispatches. The correction also retains the
source-clock authority before initial trajectory dispatch so a cancelled old epoch
cannot lose temporal-oracle identity, and it preserves an isolated-planner startup
failure through unconditional cleanup instead of masking it with mission-unregister
cleanup.

### Implementation and failure analysis

The unstable online runs were not a simulator or vehicle crash. The retained aborts
were `STALE_FLEET_OBSERVATION`: CPU-heavy planning/certification ran beside the 100 Hz
control path, while a zero-sleep source-clock wait repeatedly called the full mission
observation boundary. That combination starved telemetry and retained tens of
thousands of duplicate full observations. Individual evidence bundles grew from about
`218 kB` after correction to as much as roughly `300 MB` before correction. The large
JSON/CSV payloads also explain much of the poor analysis efficiency and token use: the
same duplicate state was repeatedly serialized, searched, and summarized.

The production repair pre-warms one isolated planner process before takeoff, keeps A*
and trajectory certification outside the control process, reads the Supervisor's
canonical telemetry cache while waiting, sleeps for a bounded `1..10 ms`, and retains
full observations only at planning/cutover evidence boundaries. Runtime cleanup now
closes the planner process, terminates fleet tasks, clears dynamic obstacles, and
removes completed runtime coordinator graphs. The accelerated dynamic regression uses
the qualifying realtime source/wall-time basis so an artificial clock multiplier
cannot move the vehicle into an obstacle envelope while the isolated planner is still
certifying an earlier state.

### Packet claim reconciliation

| Packet | Implemented production path and observation | Author evidence boundary |
| --- | --- | --- |
| WP-62 | Campaign Play → `FastSimCampaignExecutor` → pre-warmed isolated execution head → Supervisor telemetry cache → terminal cleanup and immediate retry. Real stale telemetry still fails closed; planner work no longer manufactures stale telemetry or unbounded retained observations. | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME`; four consecutive clean online runs, including the required three plus immediate retry. |
| WP-63 | Catalog generation and API expose exactly five major groups—Flight, Target, Level path, 3D path, Shape—with all 12 current 1D static cases exactly once. Normal preparation exposes `Balance`; closed `Tune` exposes Speed, Accuracy, Smoothness. Wind shift remains disabled and normal UI contains no Eligible badge or internal planner label. | `PRODUCTION_ENTRY / NO_RUNTIME / NOT_APPLICABLE`, plus built and served 1280 × 720 UI; narrow behavior is automated render/CSS coverage. |
| WP-64 | The resolved preparation request reaches the motion contract, whole-route planner, P/V/A-continuous trajectory, runtime commands, CSV analyzer, per-motor truth oracle, and strict repeat evaluator. Gentle bends retain speed; hard changes receive bounded physical retiming; terminal-only goal capture is not converted into an energy-heavy crawl. | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`; all 12 curved-route, figure-eight, and altitude repeat identities pass individually and the exact 15-record RMS universe passes at `<= 0.05 m`. |
| WP-65 | Retained telemetry CSV → API review payload → all graph sliders → exact source-sequence lookup → text readout and room marker. Receive time is displayed but is never the cursor key; absent channels remain explicitly unavailable. | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME`, plus built and served UI. Browser observation selected exact source sequence `1944`; all six graphs, the readout, and the room marker reported sequence `1944`. |
| WP-66 | The online mission is the sole case in the Dynamic replanning cluster. Its initial authority is only current start, terminal goal/landing, immutable limits, and perceived-world generation. Each sensed add/move/remove event runs distance/speed urgency, deterministic bounded eight-neighbor A*, independent safe-prefix/corridor/cutover certification, exact Supervisor preparation receipt consumption before atomic commit, and direct goal continuation; authored centerline/reference/rejoin fields reject. | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME`; every one of four events was persisted, recertified, committed, and dispatched in each of four consecutive runs, followed by captured landing. Nominal, rename/reorder, budget, no-solution, late/unsafe, missing/tampered/partial acknowledgement, and malformed-route counterexamples are executable tests. |

### Retained author evidence

- Runtime qualifier:
  `missions/campaigns/sim/qualification/wp62-66-runtime-qualification-v1.json`,
  file SHA-256
  `7fc513ded453b9364ec07767f63ccbda685bc0407673d4dd9bdcda30bcdab711`,
  payload SHA-256
  `6fe4bdca44610d725dbd5434e38c95d7e79f9202ba5763adb8045242d5c7ef07`.
  It reports `all_required_repeats_and_retry_passed: true`, four online statuses
  `SUCCEEDED`, realtime factors `0.999842`, `0.999872`, `0.999732`, and
  `0.996414`, no failed/missing motion guards, all four event IDs persisted,
  recertified, and dispatched, and clean runtime state after every run.
- The strict tracking evaluator observed exactly 15 expected identities, 15 unique
  expected identities, no failures, and no aggregate substitution. All 12 WP-64
  anchors and all three required WP-66 realtime repeats passed individually.
- The four retained online execution bundles are `223,063`, `222,755`, `223,036`,
  and `224,179` bytes. Each qualified online child retained exactly `9`
  `observations_read`, below the independent cap of `12`; the runs retain only the planning/cutover
  observations needed for causal review.
- UI inspection:
  `missions/campaigns/sim/qualification/wp62-66-ui-inspection-v1.json`, file SHA-256
  `765fb2b5086233503aa517a8bf38ae2601e05ec46fe16d33c24881e1105cfdfd`.
  The actually served viewport was `1280 × 720` with no horizontal overflow. The
  browser capability ignored the requested narrow override, so narrow and
  reduced-motion behavior are claimed only from automated render/CSS checks. Five
  group labels and counts are `Flight 1`, `Target 2`, `Level path 4`, `3D path 2`,
  `Shape 3`; normal preparation shows Balance/Tune and zero Eligible labels; all six
  graphs, the readout, and the room marker reported exact source sequence `1944`; no
  browser console warning/error was observed. Five screenshot paths, byte sizes, and
  SHA-256 identities are retained in the inspection artifact.
- Backend author checks: the final packet-focused suite reports `170 passed`, including
  the production online E2E, source-contract boundaries, and isolated-planner cleanup;
  the complete runtime qualifier passes; focused Ruff and targeted Mypy pass. A
  broader compatibility run reported `172 passed, 2 failed`.
  Both failures remain visible and are outside the frozen 1D review unit: the legacy
  three-drone 40-second ground-wait fixture aborts Gamma for stale telemetry, and a
  synthetic 2D head-on dynamic fixture expects dispatch where the new protected
  response/certification boundary fails closed. Neither is relabeled as passing or as
  qualified by WP-62 through WP-66.
- UI author checks: ESLint and TypeScript pass; Vitest reports `13` files and `133`
  tests passed; the production Vinext build completes; rendered HTML reports `3`
  tests passed. JSDOM's expected missing-canvas diagnostic and the build's existing
  large-chunk advisory are non-failing.

### Residual limits and gate state

No hardware, physical-flight, Live Isaac, or aerodynamic-fidelity claim is made.
Wind shift remains the explicitly disabled reserved fixture, and no second dynamic
mission was introduced. The two broader compatibility failures above remain explicit
out-of-scope limitations; the implementation does not extend or qualify multi-role
dynamic replanning. The implementation is author-complete but remains
`IMPLEMENTED_UNVERIFIED` pending the original fresh verifier's one focused correction
recheck of the revised exact manifest, production paths, retained evidence, and
meaningful counterexamples.

<!-- WP62-66-IMPLEMENTATION-PAYLOAD-END -->

### WP-62 through WP-66 implementation-review handoff

- Frozen implementation manifest:
  `missions/campaigns/sim/qualification/wp62-66-implementation-manifest-v1.json`,
  file SHA-256
  `5b329227c61bf7f0e39ca05dceda6dba91d8f53a7ff8992000c88e61986c54fd`,
  canonical payload SHA-256
  `c42f28cab3b4d2346ae3b85ce94510ca39667b35759e5ed5449f7a6ad8d8c857`.
- Independent implementation verifier: `/root/wp62_66_impl_review`
  (`work_packet_verifier`, fresh for implementation).
- Initial verdict: `BLOCKED_WITH_FINDINGS` with six P1 findings. The single permitted
  correction and focused recheck resolved the WP-63 `Accuracy=100 m` obstacle child,
  WP-64 raw/processed kinematics and independent temporal oracle, WP-65 exact
  source-identity lookup, and WP-66 acknowledgement-before-commit findings.
- Focused-recheck verdict: `BLOCKED_WITH_FINDINGS`. Two P1 findings remain. First,
  independent execution reproduced one fault-free immediate retry that aborted for
  `STALE_FLEET_OBSERVATION`; the same test passed in isolation, so the claimed retry
  stability remains nondeterministic. Second, all retained served screenshots are
  `1280 x 720`, reduced-motion media did not match, and the cursor screenshot does not
  visibly retain source sequence `1944`, the correlated room marker, or the download
  row; automated assertions and author-transcribed inspection values do not satisfy
  the accepted served narrow/reduced-motion/correlation evidence boundary.
- The sole implementation correction and focused recheck are consumed. No third
  automatic pass is permitted for this review unit. WP-62 through WP-66 remain
  `IMPLEMENTED_UNVERIFIED`; the corrected implementation may not be accepted as
  `QUALIFIED` or `COMPLETE`.
- Residual qualification remains limited to software Fast Sim and local UI. No
  hardware, physical-flight, Live Isaac, or aerodynamic qualification is established.

### 2026-08-15 online-obstacle operator defect follow-up

Three consecutive observed-realtime runs stopped briefly after the obstacle reveal,
then resumed the original terminal leg through the obstacle. The retained traces show
that the changed-world child tried to resolve the run-generated prepared-motion
profile through the static registry, rejected it as not admitted, executed a certified
`STOP_AND_HOLD`, and then allowed the accepted program to continue into its direct
landing correction. The rendered dynamic obstacle was also absent from Fast Sim's
authoritative collision world.

This follow-up preserves the already-frozen WP-62 through WP-66 payloads above. Its
bounded correction is to carry the exact resolved execution profile and capability
into every changed-world child; make a certified fallback terminate the superseded
accepted program; expose the source-time dynamic-world timeline to simulator physics
and retained evidence; and use deterministic stratified appearance variation. Exit
evidence is focused regression coverage for prepared-motion replan admission,
fallback termination without a subsequent landing move, swept dynamic-obstacle
collision, and seeded variation repeatability/distribution, followed by a new
observed-realtime mission run. This correction does not upgrade the existing
`IMPLEMENTED_UNVERIFIED` packet status or erase the two retained verifier findings.

<!-- WP67-70-DESIGN-PAYLOAD-BEGIN -->

## WP-67 through WP-70 — flexible dynamic replanning correction

### Frozen authorization, intent, and value

Originating operator request on 2026-08-17:

> ok implement those changes

The authorized antecedent is the immediately preceding Runs 2–6 synthesis: replace
the misleading Accuracy control for online goal seeking with an explicit safe margin;
make more than two appearing objects configurable; prevent unnecessary hard braking,
stale-cutover rejection, beneficial-event fallback, and route-side churn; safety-cap
infeasible speed; separate fixed repeats from seeded stress; retain exact planning and
source evidence; and correct dynamic path-tube, stop, and failure classification.

| Intent/value category | Frozen content |
| --- | --- |
| Minimum useful operator outcome | A three-object online-replanning run can be prepared with a visible minimum drone-to-object clearance, the required full opening is shown, ordinary obstacle updates remain moving replans, and the resulting evidence explains every accepted or failed cutover. |
| Explicitly requested behavior | More than two objects with a set amount; no Accuracy filter for a route-free online mission; a minimum safe margin; repair the observed refusal/hesitation/hard-brake/second-object behavior. |
| Necessary prerequisites | Hash-bound preparation inputs; speed feasibility cap; fixed repeat identity; fresh-state moving cutover; truthful path/stop/root-cause evaluation; exact event/search/cutover evidence. |
| Optional experiment | One four-object fixed-world stress run and a distinct seeded-stress identity. Failure here may remain a declared stress limit if the default three-object outcome passes safely. |
| Non-goals | No physical-flight, Live Isaac, learned perception, SLAM, damage, multi-drone dynamic-replanning, or mathematical continuous-space completeness claim; no clearance below the case's existing `0.15 m` hard minimum; no wider freshness or Supervisor start tolerance. |

- Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.
- Dirty-tree rule: every scoped preimage is the exact byte hash in
  `missions/campaigns/sim/qualification/wp67-70-design-audit-v1.json`; the commit is
  provenance, not a substitute for those hashes.
- `ACTIVE.md` preimage before this payload: SHA-256
  `e6cd3612e69603b2ef234ac414fc92d7c25786ae7941084b3d690b1a54d299d8`.
- Pre-freeze audit program: `scripts/audit_wp67_70_design.py`, SHA-256
  `b4224a7ca06789f8355385730d0e863d6cda44cff24b8b1173238a527939b747`.
- Pre-freeze audit artifact:
  `missions/campaigns/sim/qualification/wp67-70-design-audit-v1.json`, SHA-256
  `039d0b9332ff3e17c3de72f63694286b37a9ec52955d42a958e4b8d60cffda6c`.
- Reproduce before review with:

```bash
.venv/bin/python scripts/audit_wp67_70_design.py \
  missions/campaigns/sim/qualification/wp67-70-design-audit-v1.json
```

The audit passes exact control-key, boundary-coverage, opening-formula, gap-boundary,
speed-cap, event-cardinality, and event-identity checks. Existing focused baseline
checks report `39 passed, 4 failed`: one pre-existing catalog-count mismatch and three
missing historical `run-files` fixtures in `tests/api/test_campaign.py`. They are
retained as pre-existing limits and may not be attributed to this batch.

### Frozen shared contracts

1. **Preparation identity.** `MotionPreparationRequest` gains an optional, typed
   `dynamic_replanning` object. It is legal only for a one-drone goal-seeking dynamic
   case and is included in the resolved-package hash, API preview/download/run request,
   locked inputs, runtime context, and evidence. The fields are:
   `minimum_clearance_m=0.15..0.30` in `0.01 m` steps (default `0.15`), exact integer
   `obstacle_count=1..4` (default `3`), and `variation_mode=FIXED|SEEDED_STRESS`
   (default `FIXED`) with a bounded explicit seed. Other cases reject these fields.
2. **Clearance meaning.** `minimum_clearance_m` is the surface margin between the
   nominal vehicle envelope and every solid after localization/prediction uncertainty;
   it may only tighten the case's `0.15 m` minimum. The read-only minimum full opening
   is `2 × (0.055 m vehicle radius + 0.05 m uncertainty + requested clearance +
   0.05 m spline/search reserve)`. Therefore the default opening is exactly `0.61 m`;
   `0.59 m` rejects, `0.61 m` admits at the `1e-9 m` numeric boundary, and `0.63 m`
   admits. Evidence retains every component rather than only the sum.
3. **No path Accuracy for goal seeking.** The dynamic UI labels the control
   `Clearance`, never `Accuracy`. Its motion-quality contract has no path-tube guard
   and removes `PATH_ADHERENCE` from the objective vector because there is no authored
   reference route. Temporal tracking of each accepted initial/replacement trajectory,
   obstacle clearance, dynamics, goal capture, and landing remain hard evidence.
4. **Bounded object population.** One exact shared resolver creates the runtime event
   list used by preview scheduling, static event admission, perception truth, and
   evaluation. Counts `1,2,3,4` produce respectively `3,4,5,6` events: add/move the
   first object, add each further distinct object once, then remove the first. Event
   sequences/generations are contiguous, IDs and solid IDs are unique, each event
   retains the existing `3.0 s` observation lead, the maximum simultaneous population
   equals the requested count, and extra objects use bounded authored template
   geometry that leaves an independently checked outer passage. Future objects remain
   absent from initial planner truth.
5. **Repeat identity.** `FIXED` materializes the same exact dynamic-world geometry and
   event timing for the same case/package/seed regardless of run ID. `SEEDED_STRESS`
   additionally binds the run ID and therefore produces a distinct retained truth
   identity. Fixed and stress results are never aggregated as repeats of one world.
6. **Reaction speed cap.** Dynamic goal-seeking preparation resolves any request above
   `0.30 m/s` to `0.30 m/s` before Play and names the dynamic reaction envelope as the
   binding cap. With the existing `0.74 s` complete latency, `1.0 m/s²` acceleration,
   `8.0 m/s³` jerk, `0.055 m` radius, `0.05 m` uncertainty, and `0.15 m` clearance,
   the retained witnesses require center-to-surface distances `0.529775 m` at
   `0.29 m/s`, `0.540750 m` at `0.30 m/s`, and `0.781250 m` at `0.50 m/s`.
   Runtime urgency remains authoritative and can still brake/fallback on a genuinely
   late or close observation.
7. **Continuity-aware search.** Goal-corridor A* takes the observed horizontal
   velocity as its initial heading when speed exceeds the stop threshold. Its frozen
   primary cost is `path_length_m + 0.10 m/rad × integrated_absolute_heading_change`;
   path length, integrated turn, protected clearance, and canonical grid state remain
   deterministic tie-break evidence. This penalizes a large corridor-side reversal
   but never admits a blocked gap or weakens clearance.
8. **Fresh handoff.** Planning remains isolated from the control loop. Immediately
   before Supervisor preparation, the execution head captures one final source-time
   observation and rebases/recertifies the exact trajectory. The normal path requires
   observation age `<=0.25 s` and exact start error `<=0.10 m`; it does not widen the
   existing Supervisor limit. At most one full fresh search may follow an unusable
   stale corridor. A retry record is appended before starting it and retains initial,
   retry, rebase, and cumulative latency even when the retry times out. Budget
   exhaustion is `INCONCLUSIVE_BUDGET`, never geometrical `NO_SOLUTION`.
9. **Beneficial events.** `OBSTACLE_REMOVED` and `PASSAGE_OPENED` can never select an
   immediate fallback solely because another retained solid is close. They still
   reoptimize and certify from fresh state; invalid, late, or stale evidence may fail
   closed normally.
10. **Truthful evaluation.** Dynamic path-tube is explicitly not applicable. An
    unintended stop requires speed `<=0.02 m/s` continuously for at least `0.20 s`,
    strictly between moving intervals in the same accepted authority epoch; command,
    acknowledgement, cutover, initial stabilization, and final capture boundaries do
    not each create stops. Root cause classification matches normalized reason/fault
    codes from authoritative terminal fields and exact execution-head dispositions;
    configured words elsewhere in the bundle cannot classify a watchdog failure.
11. **Retained explanation.** Each event record retains the resolved preparation and
    source-code identities, observed state age/speed, response witness, search
    disposition/expansions/wall time, inflation components, required opening, selected
    path/objective, rejected/no-solution/budget reason, rebase attempt/latency,
    preparation start error or structured Supervisor error, receipt/commit/dispatch,
    and post-cutover observation. Dirty runtime source is identified by exact hashes of
    the production modules used for preparation, world materialization, planning,
    replanning, execution, and evaluation.

### Work packets

#### WP-67 — Dynamic preparation and operator controls

**Status:** `IN_PROGRESS`

**Independent verification:** `DRAFT_UNVERIFIED`

Implement the typed dynamic preparation, hash transit, three-object default, bounded
one-to-four object population, fixed/stress repeat identity, `0.15..0.30 m` Clearance,
computed Opening readout, and `0.30 m/s` preflight speed cap. In the Campaign workspace,
dynamic Motion keeps `Balance`, `Speed`, `Clearance`, and `Smoothness`; a compact
Environment row directly below contains `Obstacles` and `Variation`. Static missions
retain the existing Accuracy control. Update the durable UI guide because this is a
new case-specific preparation pattern.

#### WP-68 — Moving-replan continuity and cutover freshness

**Status:** `PLANNED`

**Independent verification:** `DRAFT_UNVERIFIED`

Implement velocity-seeded continuity cost, final fresh rebase before preparation,
bounded single retry, complete failed-attempt evidence, and beneficial-event handling.
No solution, budget exhaustion, stale state, and Supervisor rejection remain distinct
safe outcomes; no safety tolerance or planning authority is widened.

#### WP-69 — Dynamic evidence and evaluator truth

**Status:** `PLANNED`

**Independent verification:** `DRAFT_UNVERIFIED`

Remove the inapplicable goal-seeking path-tube guard; join motion observations to the
accepted trajectory epoch; make stop detection phase/authority aware; classify exact
terminal causes; and retain the complete event/search/handoff/source identity described
above through bundle, evaluator, offline analyzer, API, and download artifacts.

#### WP-70 — Reproducible qualification and served handoff

**Status:** `PLANNED`

**Independent verification:** `DRAFT_UNVERIFIED`

Add independent component and production-entry counterexamples and run the bounded
matrix below. Rebuild/restart the affected local API/UI only after confirming that no
active mission would be interrupted, then inspect the actual served desktop and narrow
surface. This establishes software Fast Sim behavior only.

### Claim and evidence matrix

| Claim | Trigger / production transit | State or command effect | Independent oracle and counterexample | Boundary |
| --- | --- | --- | --- | --- |
| Dynamic controls are truthful | Campaign dynamic case → UI request → preview/package/run API → resolved package | Clearance changes both planning solid policy and motion clearance; object count changes the resolved event set; Accuracy is absent | Recompute package hashes and opening from independent constants; reject clearance `<0.15`/`>0.30`, Boolean/non-integer counts, and dynamic fields on a static case | `PRODUCTION_ENTRY / NO_RUNTIME / NOT_APPLICABLE` |
| Object population is bounded and repeatable | Resolved package → schedule/scenario/perception source | Exactly the requested distinct/max-simultaneous objects appear; fixed run IDs share truth while stress IDs differ | Independently enumerate event/solid IDs and timeline occupancy; reorder source templates and rename a child without changing cardinality | `INTEGRATION / FAST_SIM / ACCELERATED` |
| Nominal updates remain moving replans | Source-time sensor event → isolated search → fresh rebase → Supervisor receipt → commit/dispatch | Accepted replacement preserves motion and reaches goal/landing without certified fallback | Raw telemetry and exact event trace; removal near another solid, stale state, insufficient gap, no solution, and exhausted budget perturbations | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |
| Gap and route selection are explainable | Fresh perceived geometry → A* → spline/cutover certificate | Gap below required opening rejects; continuity cost prefers a feasible committed side without weakening clearance | Independent `0.59/0.61/0.63 m` geometry oracle plus mirrored/reordered obstacles and opposite initial headings | `COMPONENT + INTEGRATION / FAST_SIM / ACCELERATED` |
| Evaluation reports actual dynamic behavior | Retained CSV/context → evaluator → analyzer/API | No path-tube verdict for route-free goal seeking; stops and root cause use exact epochs/codes | Hand-built CSV stop intervals and terminal fields; configured `watchdog` prose with a replanning-budget failure must not classify `SIM_TIMING` | `INTEGRATION / FAST_SIM / ACCELERATED` |
| Served preparation is usable | Current built assets and API → Campaign workspace | Dynamic case visibly shows Clearance, Opening, Obstacles, and Variation; static case still shows Accuracy | Desktop/narrow rendered inspection, keyboard operation, long values, disabled/error state, and request capture | `PRODUCTION_ENTRY / NO_RUNTIME / NOT_APPLICABLE` |

### Executable exit evidence

1. Pre-freeze audit remains byte-identical and passing; a separate implementation
   manifest binds postimages without rewriting this design artifact.
2. Focused Python tests cover request validation, hash sensitivity, 1–4 populations,
   fixed/stress identity, watchdog reserve, speed cap, gap boundaries, velocity-heading
   mirroring, beneficial removal, fresh-start preparation, retry timeout evidence,
   path-tube N/A, stop intervals, and exact cause classification.
3. Existing dynamic, planner, motion-quality, evaluation, API, documentation-routing,
   and generated-contract tests pass except explicitly frozen unrelated baseline
   failures. Ruff, targeted Mypy, ESLint, TypeScript, Vitest, and the production UI
   build pass.
4. Three consecutive default `obstacle_count=3`, `FIXED`, `0.29 m/s`, observed-realtime
   production-entry runs have identical dynamic-world truth identity, persist and
   dispatch every configured event, contain no `SAFE_FALLBACK`, complete goal capture
   and landing, retain protected clearance `>=0`, local estimate/truth RMS `<=0.03 m`,
   no unintended route stop, start error `<=0.10 m`, observation age `<=0.25 s`, and
   cumulative replanning latency `<=2.0 s` per event. Every repeat passes individually.
5. One fixed four-object run exercises all four simultaneous objects. It must remain
   collision-free and evidence-complete; a budget fallback may remain a declared P2
   stress limitation only if the default three-object gate above passes and the UI
   labels four objects as stress rather than nominal.
6. The served UI inspection binds API/assets and verifies desktop and narrow layout,
   keyboard labels, dynamic/static control swap, computed opening, obstacle count,
   fixed/stress choice, speed-cap explanation, loading/disabled/error behavior, and no
   horizontal overflow or console error.

### Model, cost, and review route

- Author route: frontier reasoning at high effort because this batch crosses
  safety-sensitive geometry, reaction timing, authority cutover, generated API, and
  served UI boundaries. Exact model name, token count, and wall time are not exposed;
  proxies are four packets, one design review/recheck maximum, one implementation
  review/recheck maximum, declared run count, and the frozen implementation file list.
- Design review count: `0`; correction count: `0`.
- Implementation review count: `0`; correction count: `0`.
- Safe fallback if a claim cannot close: retain the current `0.15 m` safety minimum,
  cap dynamic speed at `0.30 m/s`, keep four objects labeled stress, and leave the
  affected packet `IMPLEMENTED_UNVERIFIED` without qualifying runtime or served UI.

<!-- WP67-70-DESIGN-PAYLOAD-END -->

### WP-67 through WP-70 initial design-review handoff

- Initial payload: 16,544 bytes, SHA-256
  `f90a8af102f675df870729b00fd8f4210f7c0ce0b5f734603bc4a32568b67f42`.
- Independent design verifier: `/root/wp67_70_design_review`
  (`work_packet_verifier`, fresh for this review unit).
- Initial verdict: `BLOCKED_WITH_FINDINGS` with six P1 findings. The accepted
  correction scope is limited to lattice-phase opening truth, independently derived
  motion/continuity guards, a complete sensed-world witness, independently discovered
  transit boundaries, separation of immutable resolved-world identity from motion
  policy, and the prior-run transition before new qualification evidence.
- Sole consolidated design correction: consumed below. The same verifier receives one
  focused recheck; no third automatic pass is permitted.

<!-- WP67-70-R2-DESIGN-PAYLOAD-BEGIN -->

## WP-67 through WP-70 R2 consolidated design correction

R2 supersedes only the six erroneous or incomplete contracts named above. Every other
initial WP-67 through WP-70 decision remains frozen. The originating operator request,
base commit, and initial payload hash remain unchanged.

- Initial design SHA-256:
  `f90a8af102f675df870729b00fd8f4210f7c0ce0b5f734603bc4a32568b67f42`.
- `ACTIVE.md` preimage before R2: SHA-256
  `c35b70ff67e2567fa6d7caa17cde9f236935ce15a72d77e46f57c3dd41c50956`.
- R2 audit program: `scripts/audit_wp67_70_r2_design.py`, 26,742 bytes,
  SHA-256 `895866b2a450485f7368b3f819c7f02e16091780b60f0d5ab6cf1f5797316e58`.
- R2 audit artifact:
  `missions/campaigns/sim/qualification/wp67-70-r2-design-audit-v1.json`,
  56,223 bytes, SHA-256
  `760501d2fa9a7a609d41ee9bc46fd9a440e541d8cf3c992a77ae305aea4d483e`.
- Reproduce with:

```bash
.venv/bin/python scripts/audit_wp67_70_r2_design.py \
  missions/campaigns/sim/qualification/wp67-70-r2-design-audit-v1.json
```

The audit imports the production corridor search, reaction-horizon, urgency,
perception, scenario-event, and canonical-hash boundaries. It passes all 15 frozen
checks. Its source-to-transit manifest is discovered from production symbol
occurrences, classifies every discovered node `MODIFY`, `PRESERVE`, `NEW`, or
`GENERATED`, and derives both generated API outputs from `ui/package.json` rather than
from the author claim table.

### R2-1 — physical opening versus planner guarantee

`minimum_clearance_m` remains the nominal vehicle-envelope-to-solid surface margin
after localization/prediction uncertainty. Its legal range is corrected to
`0.15..0.25 m`, step `0.01 m`; a larger value must be rejected, never silently
weakened. The upper bound preserves a useful outer route in the exact four-object
world below.

Two read-only values are retained and shown with their meanings:

- physical protected opening =
  `2 × (0.055 radius + 0.05 uncertainty + clearance + 0.05 spline/search reserve)`;
- planner-guaranteed opening = physical protected opening + one `0.05 m` cell for
  arbitrary lattice phase.

At the default clearance these are `0.61 m` physical and `0.66 m` guaranteed. At
`0.25 m` they are `0.81 m` and `0.86 m`. The UI primary readout is
`Opening ≥ 0.66 m` and describes it as the discrete planner guarantee. It may expose
the `0.61 m` physical value only as subordinate diagnostic text.

The executable oracle uses the real `search_goal_corridor`: a `0.61 m` gap centered
on the grid is selected; `0.61 m` and `0.63 m` gaps shifted by `0.025 m` return
`NO_SOLUTION`; a `0.66 m` shifted gap is selected. Mirroring and source-object
reordering must preserve those dispositions. This is a discrete-grid guarantee, not a
continuous-space completeness claim.

### R2-2 — separately hashed world/case truth

Dynamic world preparation is not nested in `MotionPreparationRequest` and never
changes a motion-profile hash. The public request contains two sibling components:

1. `MotionPreparationRequest` owns `speed_m_s`, `minimum_clearance_m`, and
   `smoothness`; for route-free goal seeking it rejects Accuracy/path-tube input.
2. `DynamicWorldPreparationRequest` owns exact integer `obstacle_count=1..4`,
   `variation_mode=FIXED|SEEDED_STRESS`, and an explicit bounded integer
   `variation_seed`.

Before preview, download, scheduling, or Play, one resolver materializes an immutable
`ResolvedDynamicWorld` with separate `dynamic_world_definition_sha256`,
`dynamic_event_set_sha256`, and `resolved_dynamic_world_sha256`. It then derives an
immutable successor `CampaignCase` whose ID is
`<source-case-id>.world-<first-12-world-hash>` and whose case hash includes the exact
scenario events and parent source-case hash. `ResolvedPlanningPackage.case`, planning
submission, execution profile, schedule, perception timeline, lock, runtime context,
manifest, and evaluation all bind this resolved child case/hash. The lock also keeps
the selected source case ID/hash for catalog grouping. The child snapshot is retained
inside the package and run evidence and is not registered as a second visible catalog
entry.

The existing authored source case and its base two-object world remain byte-immutable.
Changing obstacle count, seed, geometry, timing, or hard world truth creates a new
resolved child case/hash. Changing only clearance or speed creates a new motion/
planning component and package hash while preserving the resolved world and child-case
hash. A run ID never participates in world materialization. `FIXED` defaults to seed
`42`; `SEEDED_STRESS` exposes its explicit seed. Equal mode/seed inputs are exact
repeats across run IDs; different stress seeds are distinct worlds and are never
pooled as repeats.

### R2-3 — exact one-to-four-object sensed-world witness

All event source clocks use `campaign-scenario`. Sensor observations use
`simulated-depth-range`, configuration hash from `PerceptionModelConfig(latency_s=0.12,
expiry_s=0.50)`, exact source sequence/world generation, and the resolved child-case
and event-set identities. Every event has `duration_s=3.0`, so its effective source
time is trigger plus `3.0 s`.

| Event | Trigger / effective source s | Exact solid bounds `(xmin,ymin,zmin)..(xmax,ymax,zmax)` m |
| --- | --- | --- |
| add 1 | `2.0 / 5.0` | `sensed-rock-1: (-0.15,-0.20,0.10)..(0.20,0.20,0.70)` |
| move 1 | `5.5 / 8.5` | `sensed-rock-1: (0.20,-0.25,0.10)..(0.50,0.15,0.70)` |
| add 2 | `7.5 / 10.5` | `sensed-wall-2: (0.85,0.45,0.00)..(1.00,0.90,0.80)` |
| add 3 | `9.25 / 12.25` | `sensed-wall-3: (0.55,-0.80,0.00)..(0.75,-0.45,0.80)` |
| add 4 | `11.0 / 14.0` | `sensed-wall-4: (0.90,-0.80,0.00)..(1.10,-0.45,0.80)` |
| remove 1 | `12.5 / 15.5` | remove exact `sensed-rock-1` identity |

For count `N`, include add/move 1, adds `2..N`, and remove 1. Renumber event sequence
and generation contiguously `1..N+2`. Counts `1..4` therefore produce `3..6` events
and exact maximum simultaneous populations `1..4`. Received source time is trigger
plus `0.12 s`; sensor expiry is trigger plus `0.62 s`. Future truth is absent from
initial planning view. The exact extra-object geometry leaves a lower outer passage at
the maximum admitted `0.25 m` clearance; implementation tests certify that route with
the real planner and its boundary margin.

The complete reaction witness binds these latency components:
`0.12 sensing + 0.02 validation/queue + 0.50 planning + 0.0006 acknowledgement +
0.0994 cutover guard = 0.74 s`. Event lead and prediction horizon are `3.0 s`, sensor
expiry is `0.50 s`, normal freshness is `<=0.25 s`, planning budget is `<=2.0 s`, and
trajectory prediction step is `0.02 s`. At `0.30 m/s`, required center-to-surface
distance is `0.540750 m` at clearance `0.15 m` and `0.640750 m` at clearance
`0.25 m`; both are tested, along with isolated margin failures and the preflight speed
cap.

The nominal sensed event must produce a safe-prefix certificate, selected/certified
corridor, hash-bound preparation receipt, atomic commit, and moving replacement
dispatch. A late observation with a certified stationary prefix may dispatch
`STOP_AND_HOLD`; without such a prefix it requires an abort-route certificate and
`ABORT_AND_LAND`. Missing/tampered receipts or missing certificates produce zero
replacement commits and zero replacement dispatches. Stale, no-solution, budget, and
Supervisor-rejection outcomes retain distinct codes.

### R2-4 — independently derived hesitation and continuity guards

The guard registry in the R2 artifact is derived from the frozen operator text plus
the durable motion, replanning, mission, planning, and evidence requirements. The
implementation may not prove completeness by comparing two author-maintained copies
of the same list. Every default three-object repeat must independently pass:

| Guard | Exact nominal threshold | Isolated meaningful failure |
| --- | --- | --- |
| Speed | accepted-epoch band coverage `>=0.95`, excluding takeoff, cutover, and final-capture windows | replace moving samples with `0.10 m/s` |
| Temporal tracking | RMS to the exact accepted trajectory epoch `<=0.03 m` | offset observations `0.04 m` |
| Hard braking / jerk | route peak deceleration `<=1.0 m/s²`; peak jerk `<=8.0 m/s³` | inject `1.1 m/s²` brake |
| Route continuity | replacement initial heading change `<=π/2`; zero nominal corridor-side reversals | mirror one replacement to the other feasible side |
| Unintended stop | zero intervals at speed `<=0.02 m/s` for `>=0.20 s` strictly inside a moving accepted epoch | inject `0.21 s` zero speed |
| Clearance / collision | nominal envelope-to-solid margin `>=requested clearance`; zero collisions | move one solid `0.01 m` inside margin |
| Event completeness | every configured event joins observation, certificate, receipt, commit, and dispatch | remove one receipt |
| Freshness / budget | age `<=0.25 s`, start error `<=0.10 m`, cumulative search `<=2.0 s` | age final observation to `0.251 s` |
| Goal / landing | both captured within the case terminal limits | omit landing completion |

Raw and processed acceleration/jerk must reconcile; raw failure cannot be masked by a
percentile. Heading change uses the observed pre-cutover velocity and first replacement
tangent. Corridor side is the sign of cross product against the immutable start-goal
chord, ignores direct/collinear paths, and is evaluated only between successive
accepted detours around the same retained blocking set. The beneficial removal/direct
goal continuation cannot manufacture a side reversal.

### R2-5 — complete boundary and generated-output manifest

The R2 artifact scans production Python/TypeScript for the actual preparation,
package, API, scenario, perception, planning, replanning, execution, evaluation,
analysis, and Campaign UI symbols and records exact line witnesses and preimage hashes.
Every discovered node is classified. The explicit edit set additionally covers the
catalog/source-child identity, API runtime and persistence/export owners, simulation
world/sensor owners, mission entry point, durable UI/system maps, tests, and the exact
case fixture. `ui/openapi.json` and `ui/app/lib/api.generated.ts` are `GENERATED` and
are derived from the real `generate:api` command. The implementation manifest must
compare this discovered R2 set with actual postimages and explain every added, changed,
preserved, generated, or deleted node; a hand-maintained subset cannot close the gate.

### R2-6 — prior-run transition and qualification order

Runs 2–6 are historical evidence for the pre-correction implementation and cannot be
pooled with the corrected world/package identity. After the implementation revision is
committed and before any new retained affected campaign run:

1. confirm no active mission or preparation would be interrupted;
2. run `scripts/mark_campaign_runs_old.py` for case
   `1d.online_obstacle_replan.dynamic_nominal`, the exact applied revision identity,
   actor, and reason `WP-67..70 dynamic-world/preparation semantics replaced`;
3. retain the command, prior/new counts, changed run IDs, and revision hash;
4. restart the affected API/runtime under REQ-WFL-053 and verify state; and
5. only then collect the three default fixed repeats and optional four-object stress
   evidence.

If no committed revision identity or transition authority exists, implementation tests
may run against isolated temporary stores, but no new retained campaign run may be
claimed as qualification. Old rows are preserved, never deleted or rewritten.

### Corrected packet and gate state

| Packet | Status | Independent verification |
| --- | --- | --- |
| WP-67 — dynamic preparation and operator controls | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |
| WP-68 — moving-replan continuity and cutover freshness | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |
| WP-69 — dynamic evidence and evaluator truth | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |
| WP-70 — reproducible qualification and served handoff | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |

Implementation remains closed until the same independent verifier returns
`DESIGN_VERIFIED` for the initial+R2 composite. If verified, implementation must bind
both design hashes, retain unrelated dirty-tree work, and freeze an exact pre/post
manifest before a different fresh implementation verifier is spawned.

<!-- WP67-70-R2-DESIGN-PAYLOAD-END -->

### WP-67 through WP-70 R2 recheck handoff

- Corrected R2 payload: 12,313 bytes, SHA-256
  `3cfdb3ae05bb3f2f45e125a835df92fd677d23bf06005ff75a9f4d7bac881840`.
- Design-review count: `1`; consolidated correction count: `1`.
- Focused recheck: consumed by the same verifier.
- Focused-recheck verdict: `BLOCKED_WITH_FINDINGS`. Opening/lattice truth and the
  Runs 2–6 transition order are resolved. Four P1 findings remain: the guard registry
  and prose perturbations are not independently computed; the sensed-world witness
  does not execute certificates/receipts/commit/dispatch and the frozen three-/four-
  object geometry exhausts the 8,192-state production search; the 34-path transit
  manifest omits API runtime, generator, transition-script, and test owners; and the
  child-case witness uses a placeholder parent hash while stress seeds alter metadata
  but not behavior-driving event geometry.
- The sole correction and focused recheck are consumed. No third automatic pass is
  permitted for this review unit. Production implementation remains closed.
- Independent verification: `BLOCKED_WITH_FINDINGS`.

## Active implementation track — 2D conflict curriculum and motion parity

Status: `IMPLEMENTED`

This ordinary implementation track records the 2026-08-20 operator feedback without
recasting it as a new work packet. Existing retained case and run identities remain
immutable; corrected cases and catalog groupings reference them as baselines.

### Operator intent

- A two- or three-drone route reuses the same qualified single-drone continuous-flight
  primitive. Drone count changes coordination, not vehicle physics, waypoint traversal,
  controller behavior, or the default speed law.
- An ordinary fly-through node does not command a stop or a node-local slowdown. Speed
  changes are admitted only by authored checkpoints, terminal capture, real curvature,
  dynamics/actuator bounds, path-fidelity limits, or an active separation constraint.
- Head-on conflict, bottleneck, merge, and perpendicular crossing answer different
  causal questions. A synchronized conflict cannot pass by leaving one vehicle on the
  ground until the other completes.
- Timing experiments expose a bounded start-gap/release control and report the resolved
  earliest safe value. Geometry experiments instead require simultaneous participation
  and compare lateral detour with vertical layering; recovery experiments use actual
  source-time changes and atomic replanning.
- The 2D catalog presents one behavior-focused hierarchy. Constraint variants remain
  subordinate to the owning conflict mission instead of appearing as duplicate mission
  families in both `GEOMETRIC_CONFLICT_RESOLUTION` and
  `CONSTRAINTS_AND_OPTIMIZATION`.

### Dependencies and implementation tasks

1. Preserve the exact retained run/case artifacts cited by the existing WP-54 and
   operator-review records; add successor presentation or case identities where mission
   truth changes.
2. Remove drone-count branching from continuous fly-through tangent allocation and add
   parity tests using equivalent one- and two-role route geometry.
3. Correct the bottleneck successor to use fly-through corridor nodes; retain explicit
   checkpoints only for genuine multi-goal missions.
4. Bind ground waits to each vehicle source clock, keep all required fleet children alive
   through admitted release windows, and prove both-role takeoff/completion for head-on,
   merge, bottleneck, and crossing anchors.
5. Add bounded coordination preparation for start gap/release and keep hard separation,
   geometry, dynamics, and authorization authoritative when a requested value is unsafe.
6. Publish a compact 2D mission curriculum that groups timing, lateral, vertical, and
   recovery variants under distinct conflict questions and removes duplicate default
   navigation paths.

### Non-goals

- No physical-flight or impact-fidelity claim from Fast Sim.
- No weakening of collision, protected-clearance, workspace, dynamics, or terminal gates.
- No mutation or deletion of retained runs, evidence, or historical case identities.
- No mission-local copy of the single-drone time law or controller tuning.

### Measurable exit gates

1. Equivalent one- and multi-drone fly-through polylines compile with the same internal
   knot-speed rule and zero undeclared stops; authored checkpoint cases still stop.
2. The four 2D conflict anchors generate and execute commands for every required role.
   Synchronized submissions meet their launch-skew and overlap contracts; timing-only
   submissions retain continuous earliest-release evidence.
3. Bottleneck fly-through interior speed remains above the declared continuous-knot
   ratio unless the retained plan names the binding dynamics, curvature, path-fidelity,
   or separation constraint.
4. The operator can vary the bounded start gap before Play and sees requested versus
   resolved release plus an exact blocked reason when the request cannot be certified.
5. The served 2D catalog exposes one non-duplicated conflict hierarchy with distinct
   bottleneck, head-on, merge, crossing, geometry, and recovery questions; desktop and
   narrow rendered states pass `design.md` criteria.
6. Targeted campaign, planner, trajectory, API, and UI tests pass, followed by one
   accelerated anchor per strategy class and a realtime operator handoff without a
   qualification overclaim.

### Implementation evidence — 2026-08-20

- Two-role trajectory allocation now uses the same continuous fly-through tangent rule
  as the qualified one-role primitive. Bottleneck staging nodes remain continuous and
  only authored checkpoints declare a stop.
- The retained second-role non-start was traced to a finite-step source-clock residue in
  admitted ground wait. A source-time tolerance removes the zero-progress loop without
  weakening fleet freshness, mission timeout, or separation supervision.
- The bottleneck, head-on, merge, and perpendicular-crossing anchors each completed an
  accelerated end-to-end run with both `Alpha` and `Beta` present in final analysis.
- Exact launch-gap preparation is independently planned in both role orders. Bottleneck
  requests reuse the same certified passage geometry as automatic earliest release;
  unsafe requested gaps still fail closed.
- `2d-conflict-missions-v1` exposes all 18 simulation 2D cases exactly once under
  Crossing, Traffic, Merge, Coordination, and Recovery. The default 2D catalog no longer
  exposes the older duplicate cluster navigation.
- Focused backend, UI, API-adapter, typecheck, production-build, and in-app visual checks
  pass. The realtime operator handoff named by exit gate 6 remains an operator validation
  step and is not represented as simulation qualification.

<!-- WP71-75-DESIGN-PAYLOAD-BEGIN -->

## WP-71 through WP-75 — first physical Crazyflie readiness ladder

This packet batch is one design-review unit. It converts the current application from
a simulator with partial physical scaffolding into a deliberately staged path toward
one contained Crazyflie flight. It does not authorize a radio scan, a connection, a
motor command, or a flight during design or implementation verification.

### Frozen request and current verdict

The originating detailed physical-flight request is already frozen verbatim in the
WP-57 through WP-61 design payload above. The successor request that selects this
packet structure is frozen exactly as received:

> ok so what is the verdict what do you want to do first will you structure it in work packets or how do you want to imlement

Verdict at the design base: the application is **not ready for a props-on first
flight**. `TWIN` provisioning is rejected by the API, the production vehicle provider
does not construct a Crazyflie adapter, the physical curriculum is rejected as
`NOT_RUN`, the first four curriculum stages resolve to the same takeoff/hover/land
case, motor truth required by physical handoff is unavailable, the immediate stop is
hidden behind an Engineering confirmation, there is no keyboard authority, and the
link path has no active command watchdog lifecycle. One targeted baseline has 125
passing tests and one failing physical-plan schema test. These observations are
preimages, not completion evidence.

Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.

### Intent/value card

- **Operator:** one operator with one Crazyflie, one configured radio URI, an
  independent observer, and a contained indoor test area.
- **Decision:** determine safely whether observation, props-off actuation, basic
  controlled motion, and finally a 0.3 m hover are each ready to advance.
- **Minimum useful outcome:** even if flight packets do not advance, the normal served
  application can connect to one exact vehicle in observation-only mode and explain
  every unavailable or blocked state without implying flight readiness.
- **Evidence consumer:** the operator reviewing the live Control Center, plus the
  retained physical qualification record and later independent implementation
  verifier.
- **Hard stop:** any missing identity, telemetry freshness, permit, preflight, watchdog,
  observer, containment, or command acknowledgement leaves the next stage blocked.

### Frozen boundaries and audit

The machine-readable prefreeze artifact is
`missions/campaigns/sim/qualification/wp71-75-design-audit-v1.json`. It freezes the
base commit, the preimage of this ledger before this payload, 43 production/UI/test/
documentation boundaries, both generated API outputs, six intended new files, all
six public claims, dependencies, and required requirement IDs. Its audit command is:

`./.venv/bin/python scripts/audit_wp71_75_design.py`

At draft time the audit reports zero errors. UI contract regeneration remains one
atomic pair: `ui/openapi.json` and `ui/app/lib/api.generated.ts`. Because this batch
introduces a physical service owner and changes public transit and primary test
boundaries, implementation must update `docs/system/README.md` as well as the durable
surface rules in `design.md` and `docs/project/DESIGN.md` where the new patterns land.
An implementation manifest must compare this complete discovered set with exact
postimages; naming a hand-written diff is insufficient.

### Batch invariants and non-goals

1. **One intent, environment-specific adapters.** The same canonical takeoff, hold,
   relative-move, land, and abort intent and evidence envelope crosses Fast Sim and the
   physical adapter. Simulation success never substitutes for observed hardware.
2. **Exact identity, no discovery.** Physical entry uses one explicitly configured,
   pinned Crazyflie radio URI. The application must never scan for or select an
   arbitrary nearby vehicle. The first binding requires a visible operator identity
   confirmation; later mode selection may reconnect only that retained binding.
3. **Connect is not arm.** Selecting Digital twin may establish an observation-only
   link. It may not arm, grant a permit, start a mission, spin motors, or auto-resume a
   prior mission. Reconnection after restart, link loss, or emergency stop remains
   observation-only.
4. **Physical state is literal.** Missing battery, estimator, deck, motor, link, or
   acknowledgement channels remain explicit `UNAVAILABLE`; no simulated or derived
   placeholder may satisfy a physical gate.
5. **Safety authority preempts ownership.** Emergency stop must bypass mission and
   fleet leases and reach the link immediately. Controlled landing may preempt a
   mission only while link, estimator, height, and command acknowledgement remain
   healthy; otherwise the supervisor escalates to emergency stop.
6. **No arbitrary low-PWM ritual.** Props-off motor testing uses the official firmware
   system/motor health path or a bounded, named adapter primitive with explicit
   props-removed and restrained attestations. It does not expose general PWM or motor
   sliders in the UI.
7. **No qualification by absence.** Until the radio exists and an authorized operator
   runs a stage, all hardware results are literally `NOT_RUN`. Unit mocks and Fast Sim
   prove software behavior only.
8. **Contained scope.** No multi-drone operation, outdoor flight, obstacle avoidance,
   dynamic replanning, autonomous calibration promotion, arbitrary routes, or claim of
   complete simulation/physical equivalence is in this batch.

### Packet state and dependency order

| Packet | Status | Independent verification | Depends on | Minimum independently useful value |
| --- | --- | --- | --- | --- |
| WP-71 — exact observation-only physical entry | `PLANNED` | `DRAFT_UNVERIFIED` | — | Select Digital twin, connect/reconnect only the pinned identity, and show live or honestly unavailable physical state without command authority. |
| WP-72 — non-bypassable safety authority | `PLANNED` | `DRAFT_UNVERIFIED` | WP-71 | Preflight cannot be bypassed and Space/Enter provide visible emergency-stop/controlled-land authority during a hot physical session. |
| WP-73 — props-off truth and fault drills | `PLANNED` | `DRAFT_UNVERIFIED` | WP-71, WP-72 | Retain real sensor, firmware health/motor, watchdog, disconnect, and restart evidence without fabricated channels. |
| WP-74 — paired basic mission pipeline | `PLANNED` | `DRAFT_UNVERIFIED` | WP-73 | Execute distinct startup, hover, land, and short-move stages through the same intent/evidence pipeline in sim and hardware. |
| WP-75 — contained first-hover release | `PLANNED` | `DRAFT_UNVERIFIED` | WP-74 | Authorize and retain only a tightly bounded first physical hover after all preceding gates pass. |

Implementation is strictly sequential. A packet may remain independently useful
without advancing its successor; a failure does not collapse stages into one release.

### WP-71 — exact observation-only physical entry

**Ownership:** runtime and API provisioning, physical service lifecycle, provider and
Crazyflie adapter/link boundaries, configuration, public API models/generated pair,
Control Center environment selector and telemetry presentation, system/UI maps, and
production-entry/UI tests named by the prefreeze artifact.

**Design:** add one application-owned physical service that constructs and registers
the Crazyflie adapter from the pinned URI. `TWIN` becomes the paired physical-plus-
simulation observation environment, not an alias for Fast Sim. Selecting it performs
an idempotent connect only after first-bind identity confirmation. A missing radio,
driver, deck, log variable, or link yields a typed state and remedy in the normal
surface; it never silently falls back to simulation. Mode switching away disconnects
cleanly and cannot leave a command stream alive. Measured telemetry and the matched
simulation estimate use distinct labels, clocks, freshness, and provenance.

**Exit:** served UI selection triggers the real provisioning path with a fake link
oracle; exact URI and confirmed identity are preserved across reconnect; wrong
identity, absent radio, timeout, stale telemetry, and restart are isolated failures;
zero arm/permit/mission/motor calls occur. The physical device result remains
`NOT_RUN` until the radio is available.

### WP-72 — non-bypassable safety authority

**Ownership:** safety supervisor, physical qualification plan schema, domain command
contract, mission/fleet preparation and execution preemption, link watchdog lifecycle,
Control Center flight controls/hotkeys, API/generated types, and safety/API/UI tests.

**Design:** reconcile the physical plan loader and make a valid, current preflight
receipt mandatory for every physical takeoff or motor-test command even when firmware
reports an auto-armed state. Enable flight hotkeys only after a deliberate visible
“physical controls hot” action, while the physical surface has focus and no editable
field is focused. In that state, Space calls immediate emergency stop, prevents the
browser default, and needs no modal or typed confirmation; Enter requests controlled
landing. Both actions are also permanent visible buttons outside Engineering. The UI
shows the active mapping and last acknowledgement. Emergency stop bypasses mission/
fleet ownership, cancels future dispatch, emits the lowest-level stop immediately,
and keeps the onboard command watchdog active through the whole command-capable
session. Controlled landing is bounded and supervisor-owned; unhealthy state escalates
to stop. Correct the manual forward-axis mapping to the canonical positive-X contract.

**Exit:** production-path tests prove preflight rejection despite auto-arm; Space-to-
link dispatch latency is bounded by the application deadline and does not wait for a
lease, modal, or network retry; missing acknowledgement, stale link, watchdog expiry,
mission ownership, page focus, editable focus, repeated keydown, and process restart
have explicit safe dispositions. Hardware remains `NOT_RUN`.

### WP-73 — props-off truth and fault drills

**Ownership:** physical curriculum and handoff schema, adapter telemetry/health
channels, qualification recorder/storage, physical service, Control Center check
surface, and hardware/twin/API/UI tests.

**Design:** expose an ordered, resumable props-off checklist: identity; battery and
charger state; estimator/static pose stability; required positioning-deck presence and
quality; firmware system health; motor/propeller assignment inspection; official
firmware motor health/test result; bounded adapter motor-test result if and only if the
official interface supports it; emergency-stop acknowledgement; watchdog silence;
link removal; and clean restart to observation-only. Before any actuation the operator
must attest battery restraint, props removed, clear area, and observer presence. The
application stores source variable, firmware result, timestamp, freshness, units, and
availability for every item. A missing motor channel makes physical handoff fail
explicitly instead of copying simulation truth.

**Exit:** fake-link and schema tests preserve raw observed values and prove that
missing/tampered/stale motor or estimator truth cannot pass; props-attestation loss,
watchdog lapse, radio disconnect, and application restart each cut authority and never
auto-resume. On real hardware, the stage is not passable until an authorized props-off
run is retained.

### WP-74 — paired basic mission pipeline

**Ownership:** curriculum catalog, canonical mission/command contracts, twin
coordinator/ingestion/handoff, mission runner, physical adapter primitives,
qualification storage, Campaign Lab/Control Center stage UI, and mission/twin/UI
tests.

**Design:** replace the duplicated early curriculum cases with distinct stages and
exact bounds:

1. observation/startup only;
2. static sensor stability for 10 s;
3. props-off emergency/watchdog drill;
4. take off vertically to `0.30 m`, hover `3 s`, and land at origin;
5. take off to `0.30 m`, translate `0.10 m` on +X at at most `0.15 m/s`, hold `2 s`,
   return to origin, and land; and
6. take off to `0.30 m`, translate `0.10 m` on +X, land at the displaced target.

Every stage has its own immutable case identity, canonical intent, requested and
resolved bounds, command acknowledgements, source-clock telemetry, supervisor events,
and environment-qualified verdict. Simulation and hardware results are shown side by
side but never pooled. Stages 4–6 cannot be scheduled until WP-73 has a current pass;
advancement is manual and one stage at a time.

**Exit:** real adapter test doubles and Fast Sim consume the same canonical intent;
rename/reordering and axis-sign counterexamples preserve identity and displacement;
takeoff, hover, relative move, return, land, abort, stale telemetry, missed
acknowledgement, and restart paths retain exact evidence. Real-stage results remain
`NOT_RUN` until explicitly run.

### WP-75 — contained first-hover release

**Ownership:** physical release policy, permit lifecycle, served Control Center
readiness/flight view, recorder/export, containment checks, operator docs, and
end-to-end production-entry tests.

**Design:** the first props-on authorization is only stage 4 from WP-74: vertical
takeoff to `0.30 m`, three-second hover, and origin landing. The permit binds the exact
vehicle, firmware/configuration, positioning system, charged battery, completed
props-off run, operator, independent observer, indoor containment attestation, `0.50 m`
horizontal containment radius, altitude limit, low-speed profile, emergency mapping,
and one execution. Any material change invalidates it. The UI presents a linear
readiness ladder, measured position/quality/battery/link/watchdog, abort controls, and
the exact blocking gate. Three successful, separately initiated shakedowns are needed
before the packet can qualify later motion stages. An intentional airborne emergency
stop is not a success requirement; its simulated and props-off proof remains required,
and it remains available to the operator during flight.

**Exit:** served end-to-end tests prove permit one-shot behavior, no auto-advance,
containment and altitude rejection, disconnect/quality/battery/observer failures,
controlled landing, emergency preemption, retained export, and restart invalidation.
Only an observed physical run can turn the hardware verdict from `NOT_RUN` into pass or
fail. No test in the current radio-absent environment may claim that result.

### Production-claim matrix

| Claim | Real trigger and authoritative path | Retained observation | Independent oracle | Meaningful failure/counterexample |
| --- | --- | --- | --- | --- |
| Exact observation entry (WP-71) | Served Digital twin selection -> API physical service -> provider -> Crazyflie adapter -> exact pinned link | confirmed identity, URI hash, link state, raw telemetry provenance/freshness, zero authority | fake link records exact lifecycle and commands | wrong identity/absent radio produces typed block and zero commands |
| Non-bypassable authority (WP-72) | Served Space/Enter or visible control -> API -> supervisor preemption -> adapter/link | key/control source, supervisor decision, dispatch/ack clocks, watchdog state | link spy plus independent monotonic deadline | active mission lease, auto-arm, or missing ack cannot delay/bypass stop/preflight |
| Props-off truth (WP-73) | Served checklist -> API qualification service -> live firmware/log variables and official health primitive | raw values, units, source names, availability, attestations, fault transitions | fake firmware table plus retained schema replay | delete/tamper motor channel or lapse watchdog and handoff fails |
| Paired simple mission (WP-74) | Served stage Play -> canonical intent -> runner -> sim or physical adapter -> recorder | immutable case/intent, commands/acks, telemetry, supervisor events, environment verdict | independent geometric/time reconstruction | rename/reorder or flip axis and exact 0.10 m displacement oracle catches it |
| Contained first hover (WP-75) | Served one-shot permit -> stage 4 -> supervisor -> real adapter -> recorder/export | permit inputs/hash, observer/containment, live state, full flight/abort/land trace | independent altitude/containment reconstruction from raw observations | stale quality, `>0.30 m` target, `>0.50 m` radius, reuse, or restart blocks |
| Served physical UI (WP-75) | Production build and served application, not a component harness | screenshots/DOM state plus correlated API/run identifiers | browser test against served API with controlled physical fake | narrow viewport, disconnected state, or hidden safety control fails handoff |

All hardware rows require `HARDWARE + OBSERVED_REALTIME` evidence. Mocks, accelerated
clocks, and Fast Sim are subordinate software oracles only.

### Implementation and verification order

1. Implement WP-71 only, run its declared checks, freeze exact pre/post hashes and
   production traces, and obtain a fresh independent implementation verdict.
2. Repeat the implementation gate independently for WP-72, WP-73, WP-74, and WP-75;
   do not batch flight authority into the observation packet.
3. No packet may use the unavailable radio as a reason to fabricate a pass. WP-71 can
   qualify its absent-radio failure path in software; real connection and all physical
   stages remain pending operator authorization and hardware availability.
4. This design request stops at `DESIGN_VERIFIED`. Implementation begins only after an
   explicit implementation request and then only with WP-71.

<!-- WP71-75-DESIGN-PAYLOAD-END -->

<!-- WP76-79-DESIGN-PAYLOAD-BEGIN -->

## WP-76 through WP-79 — 1D terminal behavior and curriculum truth repair

### Frozen originating request and observed boundary

The originating operator request is frozen as follows:

> Analyze all 1D runs; investigate the shaky end that appears to snap into the goal;
> mark all analyzed 1D runs Old; and correct the misleadingly easy recovery/replanning
> missions, old Python files, and catalog grouping.

The operator then asked, “ok then what do you recommend to fix this?” and authorized
this batch with, “ok then now structure work packets for this and do one iteration on
the implementation”. The authorized implementation iteration is **WP-76 only**.
WP-77, WP-78, and WP-79 remain design-only in this iteration.

The pre-design run analysis covered `85` retained 1D run records across `14` discovered
cases. `70` route-to-landing transitions had usable terminal evidence; their last
route sample was a median `0.043 m` from the exact landing center, `61/70` were more
than `0.02 m` from center, and the maximum was `0.0645 m`. Only two transitions showed
a true post-route component reversal. The causal finding is therefore not general
terminal flutter: after a valid region capture, the command path still imposed a
minimum `0.5 s` exact-center alignment phase before descent. All `85` analyzed records
were explicitly marked `Old` under revision
`operator-review-1d-2026-08-20:40cd9947f87e` at
`2026-08-20T17:37:48.133168Z`; this batch may inspect them as history but may not use
them as current prerequisite, baseline, comparison, promotion, or qualification
evidence (`REQ-EVI-007`, `REQ-WFL-052`).

### Frozen design identity and mechanically closed boundary

| Field | Frozen value |
| --- | --- |
| Base commit | `40cd9947f87eb9bf2719d72e7c72ea867eab9977` |
| Design audit | `missions/campaigns/sim/qualification/wp76-79-design-audit-v1.json` |
| Design-audit SHA-256 | `514e77fd633dbec3f73d655fa66391e08ba48525299d74711e4b3f004d0e642f` |
| Audit command | `./.venv/bin/python scripts/audit_wp76_79_design.py` |
| Boundary derivation | Transit-symbol discovery over production, mission, campaign, UI, test, curriculum, and dynamic-case roots plus explicit packet-owned paths |
| Boundary count | `83` current files with exact dirty-worktree preimage hashes |
| Implementation selection | `WP-76` only |
| Design-only successors | `WP-77`, `WP-78`, `WP-79` |

The audit artifact freezes the exact originating requests, packet graph, six
canonically tagged production-claim rows, four executable numeric region witnesses,
eight isolated safety witnesses, an eight-entry legacy lifecycle inventory, an exact
eight-row qualification matrix and guard vector, durable requirement set, production
transit nodes, discovered path set, classifications, current dirty-worktree preimage
hashes, intended new paths, and base commit. Its production trace closes the public
API/service/executor/mission/supervisor/simulator/result/recorder/storage/evaluation/
analyzer path rather than beginning at an already accepted program. This ledger
section and that artifact are one design review unit. Existing unrelated edits are not
part of this implementation; the implementation manifest must compare WP-76
postimages to these exact preimages instead of describing the repository merely as
“dirty”.

### Intent/value card and invariants

| Item | Frozen decision |
| --- | --- |
| Operator problem | Valid 1D arrivals visibly “snap” or “click” to the landing center, while completion, quality, and catalog names imply more than the evidence supports. |
| Smallest useful outcome | Remove the artificial center-seeking phase after a valid region capture and retain proof of the actual capture-to-descent handoff. |
| Primary beneficiary | The operator reviewing ordinary 1D Fast Sim missions. |
| Safety invariant | Descent remains forbidden until a fresh, valid, in-region, within-speed capture; contact-aware descent and post-contact disarm remain unchanged. |
| Authority invariant | Estimated state authorizes control; simulator ground truth remains evidence only. |
| Identity invariant | Historical case and run identities remain immutable; new groupings and successors reference rather than rewrite them. |
| Scope invariant | No controller-gain tuning, dynamic-world implementation, physical-flight authority, or weakening of hard safety/terminal gates. |
| Failure invariant | Outside-region, overspeed, stale/invalid, and unsafe-correction cases fail closed before nominal descent authority. |

Durable coverage is `REQ-EVI-003` through the relevant evidence gates including
`REQ-EVI-004`, `REQ-EVI-005`, `REQ-EVI-007`, `REQ-EVI-011`, and `REQ-EVI-013`;
`REQ-MIS-001`, `REQ-MIS-003`, `REQ-MIS-009`, and `REQ-MIS-010`; `REQ-MOT-010` and
`REQ-MOT-011`; `REQ-RPL-006` and `REQ-RPL-009`; and workflow gates `REQ-WFL-014`,
`017`, `018`, `020`, `023`, `028`, `029`, `034`, `036`, `039`, `042`, `046`, `047`,
`052`, and `053`. WP-76 must clarify `REQ-EVI-005`: a point target aligns to its
admitted point,
while an admitted region authorizes descent from the fresh accepted capture point and
must not silently reinterpret “region” as “exact center”.

### Packet graph and verification state

| Packet | Canonical Status | Independent verification | Depends on | Minimum valuable outcome |
| --- | --- | --- | --- | --- |
| WP-76 — region-native terminal capture and landing handoff | `PLANNED` | `BLOCKED_WITH_FINDINGS` (R2 final) | — | An accepted in-region pose descends at its accepted XY with no center-alignment command. |
| WP-77 — outcome, evidence-completeness, and motion-quality truth | `PLANNED` | `BLOCKED_WITH_FINDINGS` (R2 final) | WP-76 | Completion, evidence completeness, and quality are separate verdicts with separate reasons. |
| WP-78 — recovery and dynamic-replanning catalog truth | `PLANNED` | `BLOCKED_WITH_FINDINGS` (R2 final) | WP-77 | Current catalog names/grouping match real executed behavior; legacy artifacts remain immutable history. |
| WP-79 — post-boundary 1D qualification and handoff | `PLANNED` | `BLOCKED_WITH_FINDINGS` (R2 final) | WP-76, WP-77, WP-78 | A bounded fresh matrix proves the successor generation without Old-run leakage. |

The blocked WP-67 through WP-70 dynamic-world batch remains blocked with its two
automatic design passes exhausted. WP-78 may correct presentation, provenance, and
successor naming, but it may not claim or implement WP-67–70 changed-world behavior,
nor may this successor batch be used as a third review pass for those packets.

### Frozen numeric witnesses

The independent design audit retains the machine-readable values. These examples fix
the boundary semantics before code changes:

| Witness | Center X | Captured X / speed | Expected authority |
| --- | ---: | ---: | --- |
| Accepted offset | `1.35 m` | `1.30 m` / `0.10 m/s` | Descent target X is `1.30 m`; commanded capture-to-descent XY is at most `1e-9 m`. |
| Inclusive edge | `1.35 m` | `1.45 m` / `0.10 m/s` | Descent is authorized at the inclusive `0.10 m` region boundary. |
| Outside edge | `1.35 m` | `1.450001 m` / `0.10 m/s` | No nominal descent without a separately admitted correction. |
| Overspeed | `1.35 m` | `1.30 m` / `0.100001 m/s` | No descent when the maximum capture speed is `0.10 m/s`. |

Goal-ID rename and case reordering must not change any numeric outcome. A diversion is
an explicit point target and retains point-alignment semantics; it is not evidence for
the nominal region-native claim.

### WP-76 — region-native terminal capture and landing handoff

**Ownership:** landing requirement/reference contract, public campaign API and service
transit, goal-capture authority, simulated landing execution, mission-result payload,
recorder/storage/evaluation/analyzer transit, retained goal-capture evidence, and
production-path plus mission/simulator regression tests. The implementation-owned
files remain the eight paths classified in the audit; every other traced owner is
`RELIED_UPON_UNCHANGED` and must retain its preimage or enter the exact implementation
manifest if the implementation proves it must change.

**Design:** the last aligned `GoalCaptureAttempt.estimated_position_m` is the nominal
descent XY authority. `MissionContext.capture_and_land` passes that exact XY and the
admitted landing Z through the ordinary Supervisor and `LandCommand` path. A
goal-bound `LandCommand` admits any nominal target inside the immutable horizontal
goal region at the immutable landing height; an explicit diversion remains admissible
only at its declared point. `SimulatedVehicle._land` omits the separate horizontal
alignment move only for a nominal in-region target. It retains the descent controller,
contact gate, bounded settle, and disarm-after-contact behavior. Goal-capture evidence
is versioned to retain the authorized capture position, descent target, and commanded
pre-descent horizontal adjustment. Ground truth is never command authority.

**Production trace:** `POST /campaign/runs` -> `CampaignService.run_active` ->
`FastSimCampaignExecutor` -> `FleetCoordinator` -> `MissionRunner` -> accepted
execution program -> `ScriptMission` -> `MissionContext.capture_and_land` ->
`SafetySupervisor.land` -> `LandCommand` -> `SimulatedVehicle._land` ->
`MissionResult` -> `MissionResultPayload` -> observability bridge/recorder ->
`EvidenceStore` materialization/evaluation -> campaign analyzer/intake -> campaign
review API. The audit freezes every transit owner and exact preimage.

**Independent oracle:** reconstruct the commanded XY delta from the retained accepted
capture and descent target; require zero (within `1e-9 m`) for the nominal region
claim, `alignment_duration_s == 0`, contact before disarm, and terminal truth inside
the immutable region. Inspect landing-phase exact telemetry independently for a
center-seeking pre-descent segment. The executable prefreeze audit recomputes all four
region/speed witnesses rather than trusting expected booleans and independently
evaluates invalid, stale, wrong-Z, out-of-volume correction, contact/disarm-order, and
exact/off-point diversion perturbations. The regression must first fail on the frozen
preimage. `docs/reference/LANDING_GOAL_REGION_V1.md` is an implementation-owned
contract owner and must be reconciled with `REQ-EVI-005`.

**Exit:** accelerated and realtime ordinary mission tests pass; inclusive edge,
outside-edge, overspeed, renamed-goal, explicit-diversion, and unsafe-correction cases
have typed outcomes; the exact 1D regression has no separate center-alignment phase;
all pre-existing contact and safety gates pass. WP-76 then becomes
`IMPLEMENTED_UNVERIFIED` and receives a fresh independent implementation verifier.

### WP-77 — outcome, evidence-completeness, and motion-quality truth

**Ownership:** analyzer verdict contract, API schema/generated clients, Campaign Lab
run/review status, exact-CSV reconciliation, and analyzer/UI tests.

**Design:** expose three orthogonal verdicts: (1) execution disposition such as
completed, rejected, aborted, or failed; (2) evidence completeness/identity status;
and (3) motion-quality status with terminal behavior as one explicit component.
`all_required_behavior_oracles_passed` may inform quality but may not rewrite the
execution disposition. Every failed or unavailable component carries an exact reason,
source window, threshold, and raw/processed reconciliation. The UI shows these next
to one another rather than a single optimistic or pessimistic badge.

**Exit:** a completed run with terminal flutter remains execution-completed and
quality-failed; an incomplete bundle remains evidence-incomplete; a hard mission
failure remains failed even if available quality metrics look good. Exact CSV,
analyzer, API, generated-client, and served UI identities reconcile.

### WP-78 — recovery and dynamic-replanning catalog truth

**Ownership:** versioned curriculum grouping, case/projection provenance, catalog/API
presentation, Campaign Lab navigation, and catalog/runtime semantic tests.

**Design:** keep existing case IDs, retained runs, and legacy Python projections
immutable and inspectable, but label data-only or predecessor artifacts as historical
provenance rather than current executable missions. The current Recovery grouping may
contain only a case that injects the declared fault and retains the recovery/fallback
effect. The Dynamic replanning grouping may contain only successors that traverse the
real changed-world runtime and retain trigger, invalidation, replacement/fallback, and
cutover evidence. Easy static routes receive plain truthful names and stay under the
five current 1D major missions. Presentation-only grouping never grants execution or
qualification authority.

The lifecycle inventory is exact and machine-checked. These eight existing projections
receive exactly one `HISTORICAL_PROJECTION` disposition; no file is deleted or treated
as current runtime proof:

| Family | Immutable projection path |
| --- | --- |
| `abort_and_land_goal_fallback` | `missions/library/one_drone/abort_and_land_goal_fallback/mission.py` |
| `blocked_replan` | `missions/library/one_drone/blocked_replan/mission.py` |
| `duplicate_stale_goal_update` | `missions/library/one_drone/duplicate_stale_goal_update/mission.py` |
| `failure_recovery` | `missions/library/one_drone/failure_recovery/mission.py` |
| `mid_route_goal_replacement` | `missions/library/one_drone/mid_route_goal_replacement/mission.py` |
| `online_obstacle_replan` | `missions/library/one_drone/online_obstacle_replan/mission.py` |
| `operator_approval_goal_replacement` | `missions/library/one_drone/operator_approval_goal_replacement/mission.py` |
| `planning_budget_expiry` | `missions/library/one_drone/planning_budget_expiry/mission.py` |

The mechanically closed boundary also includes the 1D recovery YAML, dynamic YAML,
catalog generator, semantic audit, catalog/model/service/UI owners, and every
production runtime owner discovered from these family symbols. A later WP-78
implementation must state per family whether its current case is an easy historical
projection, a truthful static/failure exercise, or a still-blocked dynamic successor;
names alone cannot decide that disposition.

**Exit:** removing a behavior-driving event makes the dynamic/recovery claim fail;
renaming or reordering does not change identity or qualification; legacy Python/data
projections are absent from the current executable surface but remain traceable; no
WP-67–70 behavior is upgraded from its blocked state; all eight lifecycle keys have
exactly one retained disposition with no missing or extra row.

### WP-79 — post-boundary 1D qualification and operator handoff

**Ownership:** bounded qualifier, generation/revision reconciliation, retained
manifests, ordinary runtime invocation, and operator runbook/handoff evidence.

**Design:** after WP-76–78 individually pass implementation verification, run exactly
the eight rows below. Every row selects execution profile
`planner_retained_baseline` and planning submission `case_planning_authority`; no
nearest/current/post-result selection is permitted.

| Row | Exact case ID | Clock evidence | Repeat |
| --- | --- | --- | ---: |
| `flight-a1` | `1d.takeoff_hover_land.canonical_nominal` | `ACCELERATED` | 1 |
| `flight-a2` | `1d.takeoff_hover_land.canonical_nominal` | `ACCELERATED` | 2 |
| `flight-a3` | `1d.takeoff_hover_land.canonical_nominal` | `ACCELERATED` | 3 |
| `target-a1` | `1d.point_to_point_relocation.canonical_nominal` | `ACCELERATED` | 1 |
| `level-path-a1` | `1d.continuous_waypoint_sequence.canonical_nominal` | `ACCELERATED` | 1 |
| `3d-path-a1` | `1d.altitude_transition.canonical_nominal` | `ACCELERATED` | 1 |
| `shape-a1` | `1d.planar_shape_loop.circle` | `ACCELERATED` | 1 |
| `flight-r1` | `1d.takeoff_hover_land.canonical_nominal` | `OBSERVED_REALTIME` | 1 |

Each row requires execution `SUCCEEDED`, complete identities/evidence, commanded
capture-to-descent XY at most `1e-9 m`, `alignment_duration_s == 0`, terminal region
margin at least zero, `SIMULATED_GROUND_CONTACT`, contact no later than disarm, every
required behavior oracle passing, and no Old-run eligibility. The three accelerated
Flight rows additionally require exact equality of case, execution-profile,
planning-submission, and resolved-package hashes; maximum pairwise truth-path-length
difference is `0.10 m` and maximum pairwise tracking-RMS difference is `0.02 m`, using
the existing frozen comparison bounds. The aggregate passes only with exactly `8/8`
passing rows. All runs use new IDs and bind exact plan, program, trajectory, simulator,
and revision hashes. The qualifier fails if any Old run enters a prerequisite,
baseline, peer/mode comparison, promotion, or aggregate. It reports each run; no
average hides a failure. The served API/UI must be rebuilt/restarted and correlated to
the retained qualification before handoff.

**Exit:** the exact eight-row fresh matrix passes identity/completeness, terminal region, no-snap,
motion-quality, repeatability, and Old/current separation or reports an exact failed
row and isolated guard. No new mission count is a success criterion, no row may be
substituted after results are visible, and no pre-boundary run is promoted.

### Production-claim matrix

| Claim | Execution boundary | Environment | Clock | Ordinary trigger and effect | Retained observation / independent oracle | Meaningful counterexample |
| --- | --- | --- | --- | --- | --- | --- |
| Region-native landing accelerated (WP-76) | `PRODUCTION_ENTRY` | `FAST_SIM` | `ACCELERATED` | `POST /campaign/runs` through service, executor, mission, supervisor, command, simulator, recorder, store, evaluator, and review | Retain capture/target/alignment/contact; independently reconstruct XY and landing telemetry | Rename goal; inclusive/outside edge; overspeed; stale/invalid; wrong Z; unsafe correction; diversion |
| Region-native landing realtime (WP-76) | `PRODUCTION_ENTRY` | `FAST_SIM` | `OBSERVED_REALTIME` | Same public path in `OPERATOR_OBSERVED_REALTIME` mode | Retain source/receive clocks and bundle identity; independently reconstruct source-time handoff | Rename goal and reorder selected variant |
| Orthogonal verdicts (WP-77) | `PRODUCTION_ENTRY` | `FAST_SIM` | `ACCELERATED` | Retained bundle through analyzer, API, and review UI changes displayed verdicts | Retain disposition/completeness/all quality reasons; independently recompute exact CSV | Completed run with flutter; incomplete bundle; hard failure with good partial metrics |
| Truthful catalog (WP-78) | `PRODUCTION_ENTRY` | `NO_RUNTIME` | `NOT_APPLICABLE` | Versioned grouping through catalog service changes Campaign Lab presentation only | Retain identity/status/event/runtime/predecessor; semantic fingerprint and runtime evidence remain separate | Rename/reorder, remove event, or omit one of eight legacy entries |
| Fresh generation accelerated (WP-79) | `PRODUCTION_ENTRY` | `FAST_SIM` | `ACCELERATED` | Fixed seven accelerated rows through ordinary campaign runtime | Retain new IDs/exact inputs/metrics/eligibility; independently reconcile manifest and CSV | Inject Old run, mismatched input, or substitute a row |
| Fresh generation realtime (WP-79) | `PRODUCTION_ENTRY` | `FAST_SIM` | `OBSERVED_REALTIME` | Fixed `flight-r1` row through ordinary realtime campaign runtime | Retain source/receive clocks and terminal handoff; independently reconstruct exact CSV | Substitute accelerated or superseded evidence |

### Implementation and verification order

1. Obtain one fresh independent design verdict for this exact delimited payload and
   audit artifact. Permit at most one correction and one focused recheck by that same
   verifier. Unresolved P0/P1 findings leave all four packets blocked.
2. If and only if the batch reaches `DESIGN_VERIFIED`, implement WP-76 as the single
   vertical slice authorized in this iteration. WP-77–79 remain `PLANNED`.
3. Run WP-76’s declared regression and relevant existing suites, freeze exact
   pre/post hashes and changed sections against the audit preimages, then use a
   different fresh implementation verifier.
4. Do not begin WP-77–79 implementation and do not run the WP-79 qualification matrix
   during this iteration. A served-product handoff is required only when their later
   implementation actually changes or claims the served API/UI.

<!-- WP76-79-DESIGN-PAYLOAD-END -->

### WP-76 through WP-79 design-review handoff and consolidated correction

- Initial delimited payload: 15,002 bytes, SHA-256
  `09047471734dc8ba1e116cfe7349fe41150937ade46567638ba6b639f915bb26`.
- Initial prefreeze artifact: SHA-256
  `18a66e9abc0baed3237336914236f9fa25ce3772f1f246c46634039e5e6426ca`.
- Reviewer: `/root/wp76_79_design_verifier` (`work_packet_verifier`), initial review
  on 2026-08-20.
- Initial verdict: `BLOCKED_WITH_FINDINGS`; four P1 groups, one P2, no P0.
- P1 dispositions in the single allowed correction: refreshed unstable preimages;
  replaced noncanonical claim labels with separate execution/environment/clock tags;
  extended WP-76 from the public campaign API through persistence/evaluation/review;
  converted configured examples into executable region and isolated safety witnesses;
  added the landing reference owner; froze eight legacy Python projection dispositions
  and all related runtime/generator owners; and froze eight exact qualification rows,
  submission IDs, per-row guards, repeat guards, and `8/8` aggregate semantics.
- P2 disposition: this dedicated handoff now precedes the unrelated WP-71–75 handoff,
  so hashes and verdicts cannot be attributed to the wrong packet batch.
- Revised delimited payload: 20,533 bytes, SHA-256
  `0d75a609b79354b5e9d228127eb4ca7f627598b6ff972c4cc0402f03f00b7343`.
- Revised prefreeze artifact: SHA-256
  `514e77fd633dbec3f73d655fa66391e08ba48525299d74711e4b3f004d0e642f`;
  `83` exact boundary preimages, six claim rows, four numeric witnesses, eight
  isolated safety witnesses, eight lifecycle rows, and eight qualification rows.
- Design review count: `1`; correction count: `1`; focused recheck count: `1`.
- Model/effort: primary and verifier runtime names/effort are not exposed; frontier
  reasoning was required by the cross-layer control/safety and independent-adjudication
  triggers in `REQ-WFL-045`. Token/time usage: not available. Proxies: one review turn,
  one correction pass, zero runtime runs, eight implementation-owned paths.
- Focused recheck verdict: `BLOCKED_WITH_FINDINGS`; implementation is unauthorized
  and the automatic design-review budget is exhausted.
- Remaining P1 findings: two classified boundary files changed during the recheck;
  witness-set membership and the real `MissionObservation.age_s` freshness relation
  remain unproved; WP-77 omits generated OpenAPI/client owners; WP-78 omits the
  `moving_target` projection from its lifecycle inventory; and WP-79 guard/aggregate
  metadata has no isolated executable sensitivity vectors.
- Resolved on recheck: the revised payload/artifact identities reproduced at recheck
  start, canonical claim tags were present, the principal public API-to-review trace
  and landing reference owner were closed, and the durable handoff identity was clear.
- Final reviewer: `/root/wp76_79_design_verifier`; no P0 and no residual P2 findings.
- Mechanical status-only closeout changed the reviewed payload from 20,533 bytes,
  SHA-256 `0d75a609b79354b5e9d228127eb4ca7f627598b6ff972c4cc0402f03f00b7343`
  to 20,477 bytes, SHA-256
  `3ff9c0195f6b7d1d3cc242e3df2e0cafbd6a96ef1306084b231ee30a96b6e0aa`;
  only the four verification cells changed from “R2 recheck pending” to “R2 final”.

### WP-71 through WP-75 initial design-review handoff

- Delimited design payload (inclusive of markers): 17,786 bytes, SHA-256
  `2eb524ed441d4ea6e5351da913b092f108f31d9a5b765849cd45ad07e7e2524f`.
- Prefreeze artifact: SHA-256
  `c674e2e6909f834bccd631b577e2945a75de9b224935d3c2dd74e3d86a8cbf39`.
- Audit implementation: SHA-256
  `7f6e4062dda4c09e338120155c36f3f11c325df633c5c8d993ca6fe94563792a`.
- Design-review count: `0`; correction count: `0`; focused recheck count: `0`.
- Hardware evidence: `NOT_RUN` (radio unavailable; no physical action authorized).
- Independent verification: `DRAFT_UNVERIFIED`.


<!-- WP71-75-R1-DESIGN-PAYLOAD-BEGIN -->

## WP-71 through WP-75 R1 consolidated design correction

This is the sole author correction permitted after the initial independent review. It
is additive to, and where inconsistent supersedes, the initial payload. It addresses
`WP71-75-DES-001` through `WP71-75-DES-006` only; it does not authorize
implementation or hardware activity.

### R1-1 — exact originating request

The full operator request that originated this physical-flight successor is frozen
verbatim here:

> ok the drone is there but radio not yet so you cannot connect to it yet but i want you to anazle the Application for its readiness for doing the first real-life test with the drone. So I expect this basically for real flight to be just the same as simulation, just as, you know, I switch between simulation and digital twin. So if I click digital twin, then it will, of course, then connect. If it has not been connected before, then it will connect to the drone. And then, yeah, I don't know. I expect this to look the same. So of course I only have one drone now, so it's only 1D. But basically, of course, I cannot start with all those, like, basic flight routes. I need to start much slower. So I want you to search the internet for tests that can be done first, I don't know, symmetry checks, not really, or maybe also testing sensors or something, and then going step by step, maybe having motors rotate for a couple of seconds, but not with max speed to, you know, take off. Something like that, test abort commands. So for example, if I'm on the digital twin mode and I press the space key, the space bar, for example, it will shut off the drone immediately. If I press, I don't know, Enter, then it will slowly decrease the altitude, let's say, for example, if I just went airborne, emission normally, then it would, you know, go down. So this is like, the first class should be, like, setting checks like that, and then, of course, then more feedback and stuff like that, but that can also work on another mission class, or mission cluster could be very slow to hover, stay there for a couple of seconds, then land again, or hover, yeah, go to another location, land there, stuff like that. And I think that is enough for now for setting the checks and very basic, simple missions to test it out, see how the drone behaves. And then after I've done all these checks, we can go on to more complicated tasks, yeah.

The successor packet-structure question remains frozen in the initial payload. The
operator's “same as simulation” expectation means one familiar surface and one
canonical intent contract; it does not permit simulated values to masquerade as real
measurements or permit a simulator to command the aircraft.

### R1-2 — protocol-accurate, permit-independent safety authority

On the first confirmed physical binding, the application creates an authenticated
`PhysicalSafetyAuthority` bound to operator session, exact observed vehicle identity,
and exact pinned URI. It is distinct from a motion `CommandPermit` and remains usable
after a motion permit expires or is cleared. Only immediate emergency stop, watchdog
keepalive lifecycle, and the application-controlled land fallback may use it.

Immediate emergency stop is classified before `_require_permit()` and bypasses motion
permit, preflight receipt, mission/fleet lease, current mission phase, and normal
command queue. It still requires the authenticated safety authority and exact active
link binding. One non-repeating Space keydown generates exactly one CRTP emergency
stop packet; browser key repeat and transport code never retry it automatically. The
host retains `KEY_CAPTURED`, `API_RECEIVED`, and `CRTP_DISPATCH_ATTEMPTED` monotonic
events plus synchronous dispatch success/error. These are dispatch facts, **not an
aircraft acknowledgement**. The Bitcraze emergency-stop and watchdog packets have no
response. When the link remains readable, a separate later supervisor-bitfield
observation may record `isLocked`; its absence is `UNKNOWN_OUTCOME`, never motor-off.

Emergency stop and watchdog expiry latch the Crazyflie locked until a physical reboot.
The application never auto-recovers, auto-rearms, auto-retries, or resumes. After every
E-stop/watchdog test or event, it requires operator-confirmed power-cycle/reboot,
reconnects observation-only, re-verifies identity and supervisor state, and requires
new preflight and motion permits.

The watchdog is disabled during WP-71 observation. It is activated by its first
keepalive only after physical controls are explicitly hot and before any props-off
actuation or props-on arm. The host sends every `0.100 s`; nominal maximum measured
gap is `0.250 s`, preserving `0.750 s` against the firmware's `1.000 s` timeout. It
continues across motion-permit expiry, cancel, and application-controlled landing.
After confirmed ground/disarm it is deliberately allowed to latch, and reboot recovery
is required before another session. Process death, worker death, or link loss ceases
keepalives; the firmware is expected to latch no later than `1.100 s` after the last
accepted keepalive. With no readable link, outcome stays `UNKNOWN_OUTCOME` until the
locked state is directly observed; silence is not credited.

Enter is not a firmware-supervisor controlled landing. It is an application safety
request that bypasses ordinary mission ownership and uses the Crazyflie high-level
commander only while the link is connected/fresh, supervisor reports flyable and not
locked/tumbled/crashed, estimator/height are fresh, and the watchdog loop is healthy.
It sends a `0.0 m` high-level landing target over `3.000 s`, observes descent/ground,
disarms, and then completes the latching/reboot lifecycle above. If those prerequisites
are absent, the application makes one best-effort immediate E-stop dispatch when a
link exists; if the link does not exist, it stops keepalives and records
`UNKNOWN_OUTCOME`. It never claims a ground-controlled landing over a lost link.

### R1-3 — executable safety and first-flight numerical witness

The corrected prefreeze artifact
`missions/campaigns/sim/qualification/wp71-75-design-r1-audit-v2.json` is the
machine-replayable witness for the following frozen inputs and computed results.

#### Host emergency/watchdog timing

All host durations use monotonic clocks. `UI_DISPATCH` is browser key-handler entry to
request-start. `SERVER_DISPATCH` is ASGI handler entry to the call into the link's
`send_emergency_stop`; neither includes radio processing or a nonexistent response.
In a served production build with a controlled local API/link spy, execute 100
independent non-repeating Space events: every `UI_DISPATCH <= 0.050 s`, every
`SERVER_DISPATCH <= 0.025 s`, their per-repeat sum `<= 0.100 s`, and p99 sum
`<= 0.075 s`. Timer tolerance is `0.001 s`; equality passes. The same canonical input
must produce the same safety-command hash in all repeats; run IDs and timestamps are
excluded from that hash. The expired-permit and cleared-permit variants must retain the
same dispatch count and safety-command hash. An active lease must also remain one
dispatch. Editable focus and a repeating keydown must produce zero dispatches.

The watchdog nominal vector uses a virtual monotonic clock for 100 keepalives at
`0.100 s` and a separate 10-second props-off observed run. Every gap must be
`<=0.250 s`. A `0.251 s` isolated host gap fails the host-health guard but remains
inside firmware margin; a `1.001 s` gap produces the latching fallback disposition.
The protocol has no acknowledgement field. A readable-link observation of `isLocked`
within `1.100 s` is retained when available; link removal yields
`UNKNOWN_OUTCOME_REBOOT_REQUIRED`, not pass.

#### Fixed first-flight command envelope

The accepted bench record and onsite Flow2/surface/light matrix remain prerequisites;
their hardware values are `NOT_RUN` and therefore block WP-75 today. Flight bounds are
fixed before implementation output:

- exact required decks: `deck.bcFlow2=1` and `deck.bcMultiranger=1`;
- preflight battery: measured `pm.vbat >= max(3.800 V, pm.lowVoltage + 0.300 V)`,
  not charging, both variables fresh within `0.250 s`; a missing firmware threshold or
  value one millivolt below the computed bound blocks;
- estimator convergence: ten `kalman.varPX/PY/PZ` samples at `0.500 s`; each axis
  range must be strictly `<0.001`; equality fails;
- static pose: 100 consecutive samples over `10.000 s` at achieved rate `>=10 Hz`,
  no invalid value/dropout, and per-axis position range `<=0.050 m`; the accepted
  WP-73 surface/light condition must match the flight setup;
- takeoff: relative target `(0,0,+0.300 m)`, high-level duration `3.000 s`, commanded
  vertical speed cap `0.150 m/s`;
- hover: `3.000 s` at the accepted target;
- land: high-level target `0.000 m`, duration `3.000 s`, followed by up to `2.000 s`
  to observe ground/disarm before safety shutdown;
- hard command caps for this batch: altitude `<=0.350 m`, horizontal radius
  `<=0.500 m`, scalar translation speed `<=0.100 m/s`, acceleration `<=0.500 m/s²`,
  and jerk `<=2.000 m/s³`; equality passes;
- first move stages use exactly `+0.100 m` canonical world X and zero Y, never body
  “forward” ambiguity; stage 5 returns to origin, stage 6 lands at the displaced point.

The time parameterizer owns speed/acceleration/jerk limits; the high-level controller
owns onboard tracking. The UI cannot enlarge hard caps. The runtime rejects isolated
`0.351 m` altitude, `0.501 m` radius, `0.101 m/s` speed, `0.501 m/s²` acceleration,
and `2.001 m/s³` jerk vectors before dispatch. A missing/failed bench matrix,
`0.001` estimator-range equality, stale battery, deck mismatch, or non-+X command also
blocks. Software qualification executes every isolated perturbation with all other
fields nominal. Physical qualification requires three separately initiated stage-4
runs, each with a distinct one-shot permit and review; all three must pass, and a
failure or anomaly stops the sequence without averaging or automatic retry.

These limits establish command and software-safety feasibility, not external physical
accuracy. Onboard position cannot validate itself. Any onsite evidence that indicates
the fixed envelope is unsafe blocks the flight and requires a new design review; it
cannot silently retune these values after implementation.

### R1-4 — actual paired twin entry in WP-71

WP-71 owns the physical service plus predicted simulator, twin models/storage,
`TwinCoordinator`, ingestion, and the twin API/UI lifecycle. One confirmed binding
creates three immutable identities:

- observed vehicle ID `physical:<binding-id>` mapped only to the exact pinned URI and
  confirmed firmware identity;
- predicted vehicle ID `fast-sim:<binding-id>` mapped only to a separately registered
  Fast Sim adapter initialized from the first valid measured pose; and
- twin session ID `twin:<binding-id>:<session-sequence>` mapping those two distinct
  vehicle IDs as observed/predicted roles.

`binding-id` is the first 16 hexadecimal characters of SHA-256 over the canonical
confirmed vehicle identity plus canonical pinned URI; the session sequence is a
monotonic persisted integer and is not part of either vehicle identity. This resolves
the provider's one-ID/one-backend constraint without aliasing the sources.

Selecting Digital twin connects the observed adapter first. Only after exact identity,
fresh initial pose, units, frames, source clock, and sequence validate does it register
the predicted adapter, create the coordinator/session, and start paired ingestion. Each
sample retains source vehicle/role, source clock and sequence, source time, receive
monotonic time, units, frame, validity, and availability. Residuals are computed only
for channel/time pairs admitted by the existing tolerance contract and stored by
`TwinStorage`; unavailable channels stay unavailable. The simulator is observation-
only relative to the aircraft and cannot dispatch, correct, land, or stop it.

Absent radio/wrong identity leaves no predicted adapter or twin session. Failure after
predicted registration rolls back that adapter and session atomically and disconnects
the observed link. Re-selecting uses the retained confirmed binding but creates a new
session sequence; restart never reuses a live session and begins observation-only.
WP-71 exits only when a production trace proves served selection -> physical service ->
observed adapter -> predicted provider -> `TwinCoordinator.create_session` -> paired
ingestion -> `TwinStorage`, with a residual oracle and disconnect/rollback tests. The
radio-absent physical result remains `NOT_RUN`.

### R1-5 — remove the WP-74/WP-75 physical dependency cycle

The corrected dependency and claim split is:

| Packet | Corrected dependency | Corrected closeable claim |
| --- | --- | --- |
| WP-71 | — | Served exact-identity observation plus real/predicted twin-session software path; hardware connection remains `NOT_RUN`. |
| WP-72 | WP-71 | Protocol-accurate safety authority and watchdog software path; hardware remains `NOT_RUN`. |
| WP-73 | WP-71, WP-72 | Props-off checklist/recorder and fault software path; physical pass requires an authorized onsite run. |
| WP-74 | WP-73 software contract | Distinct canonical curriculum and Fast Sim/physical-adapter-double parity only; no props-on hardware claim and all hardware stages remain `NOT_RUN`. |
| WP-75 | WP-73 physical pass, WP-74 software pass | The sole props-on release: stage 4 only, three separately reviewed 0.30 m shakedowns. |

WP-74 never authorizes or executes physical stages 4–6. WP-75 may release only stage 4
after WP-73 has an accepted real props-off record. Stages 5–6 remain blocked outside
this batch until the three WP-75 hover shakedowns pass and a future separately reviewed
physical-motion packet explicitly releases them. Thus WP-75 depends on a closeable
software WP-74, while no WP-74 claim depends on WP-75.

### R1-6 — independently closed boundary, requirement, and generated-output audit

The V2 audit replaces the initial subset audit. It extracts packet/dependency rows and
claim keys from this delimited correction payload, scans production symbols and API/UI
serving/generator sources to derive transit owners, parses the real `generate:api`
command to derive the exact generated pair, checks routed mission/motion/evidence/
fidelity/UI/workflow requirement IDs, and compares each independently derived set with
the V2 manifest. Removing any discovered owner such as `safety/supervisor.py`, the
physical plan, mission base/authority, twin models/storage, CSV export, dashboard/
served page, or OpenAPI exporter fails it.

The manifest now includes the real
`config/qualification/reality-physical-plan-v1.json`,
`docs/guides/REALITY_WP04_06_PHYSICAL_PROCEDURE.md`, mission authority/base, twin
models/storage/pipeline, evidence exporter, UI page/package, dashboard service,
OpenAPI exporter, domain requirements, and their primary tests. Existing paths have
exact classifications and hashes; intended new paths are asserted absent. The audit
checks current `HEAD`, packet ordering and acyclicity, initial and R1 payload identities,
artifact self-hash handoff, and the byte-exact initial ledger preimage using:

`awk '/<!-- WP71-75-DESIGN-PAYLOAD-BEGIN -->/{exit}{print}' docs/work-packages/ACTIVE.md | sed '$d' | shasum -a 256`

The expected reconstruction is
`db07518867f2372b8e9e40968f85756dd366dc8dc968b797940acbdf0ecf1254`.
The exact routed set is `REQ-MOT-001`, `REQ-MOT-003`, `REQ-MOT-005`,
`REQ-MOT-006`, `REQ-MOT-007`, `REQ-MOT-008`, `REQ-MOT-009`, `REQ-MOT-010`,
`REQ-MOT-011`, `REQ-MOT-013`, `REQ-MOT-017`; `REQ-MIS-001`, `REQ-MIS-002`,
`REQ-MIS-003`, `REQ-MIS-004`, `REQ-MIS-006`, `REQ-MIS-008`, `REQ-MIS-009`,
`REQ-MIS-010`; `REQ-REU-001`, `REQ-REU-002`, `REQ-REU-003`, `REQ-REU-004`;
`REQ-EVI-001`, `REQ-EVI-003`, `REQ-EVI-004`, `REQ-EVI-005`, `REQ-EVI-008`,
`REQ-EVI-011`, `REQ-EVI-012`, `REQ-EVI-014`; `REQ-XFR-001`, `REQ-XFR-002`,
`REQ-XFR-004`, `REQ-XFR-005`, `REQ-XFR-006`, `REQ-XFR-008`; `REQ-UI-001`,
`REQ-UI-002`; and `REQ-WFL-014`, `REQ-WFL-017`, `REQ-WFL-018`, `REQ-WFL-020`,
`REQ-WFL-023`, `REQ-WFL-024`, `REQ-WFL-025`, `REQ-WFL-029`, `REQ-WFL-034`,
`REQ-WFL-038`, `REQ-WFL-042`, `REQ-WFL-043`, `REQ-WFL-046`, `REQ-WFL-047`,
`REQ-WFL-048`, `REQ-WFL-053`.

### R1 corrected production-claim matrix

| Claim key | Environment/clock | Corrected authoritative trace and oracle |
| --- | --- | --- |
| `exact_paired_twin_entry` | software production entry plus later `HARDWARE/OBSERVED_REALTIME` connection | Served selector -> physical service -> exact observed adapter -> separate Fast Sim adapter -> coordinator -> ingestion -> storage; independent residual and atomic rollback oracle. |
| `permit_independent_emergency` | software production entry plus later props-off hardware | Served Space/button -> authenticated safety authority -> supervisor preemption -> permit-bypassing single CRTP dispatch; dispatch events and separate state observation, never an acknowledgement. |
| `watchdog_latching_fallback` | software virtual clock plus later props-off observed realtime | 100 ms keepalive lifecycle -> 1,000 ms firmware timeout -> locked/reboot-required disposition; 0.251 s and 1.001 s isolated gaps and link-loss unknown-outcome oracle. |
| `props_off_truth` | software schema plus later `HARDWARE/OBSERVED_REALTIME` | Served checklist -> qualification service -> live firmware logs/params -> recorder/export; delete/tamper/stale/attestation failures cannot pass. |
| `paired_basic_mission_software` | Fast Sim and physical-adapter double; no hardware qualification | Served stage -> canonical intent -> runner -> adapter -> evidence; exact +X, timing, cap, rename/reorder, and isolated guard vectors. |
| `contained_first_hover` | `HARDWARE/OBSERVED_REALTIME`, initially `NOT_RUN` | One-shot permit -> WP-74 stage 4 intent -> supervisor -> real adapter -> recorder/export; all three separate shakedowns, cap/bench/observer/restart failures, no averaging. |
| `served_physical_ui` | served production build | Browser surface -> production API and correlated retained IDs; desktop/narrow/disconnected/hotkey-focus/visible-safety-control oracle. |

### R1 corrected state

| Packet | Status | Independent verification |
| --- | --- | --- |
| WP-71 | `PLANNED` | `DRAFT_UNVERIFIED` |
| WP-72 | `PLANNED` | `DRAFT_UNVERIFIED` |
| WP-73 | `PLANNED` | `DRAFT_UNVERIFIED` |
| WP-74 | `PLANNED` | `DRAFT_UNVERIFIED` |
| WP-75 | `PLANNED` | `DRAFT_UNVERIFIED` |

Implementation remains closed. The same initial verifier receives one focused recheck
of the initial+R1 composite; no third automatic design pass is permitted.

<!-- WP71-75-R1-DESIGN-PAYLOAD-END -->

### WP-71 through WP-75 R1 focused-recheck handoff

- Initial verifier verdict: `BLOCKED_WITH_FINDINGS` with two P0 and four P1
  `MUST_FIX_NOW` findings (`WP71-75-DES-001` through `WP71-75-DES-006`).
- R1 payload (inclusive of markers): 18,786 bytes, SHA-256
  `b33775b8349d32142232bfad6418223b9d48d38eb32872125dc6d1919d87083c`.
- V2 artifact: SHA-256
  `a13236989333676dedba805faa29242b336073058da3c91bf9b8af8840b49541`.
- V2 audit implementation: SHA-256
  `d32baddf64ab6d164715a48016618f0c7c20f59c32badcb0456f1c473fd99d10`.
- V2 audit result: zero errors; 72 frozen boundaries, 48 independently
  discovered production boundaries, seven claims, five acyclic packets, 55 routed
  requirements, and the two generated API outputs.
- Design-review count: `1`; correction count: `1`; focused recheck count: `1`.
- Hardware evidence: `NOT_RUN`.
- Independent verification: `BLOCKED_WITH_FINDINGS` after the same verifier's focused
  recheck.

### WP-71 through WP-75 final design-gate outcome

| Packet | Status | Independent verification |
| --- | --- | --- |
| WP-71 | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |
| WP-72 | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |
| WP-73 | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |
| WP-74 | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |
| WP-75 | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |

The focused recheck resolves `WP71-75-DES-001`, `003`, `004`, and `005`. Two gate
failures remain and the sole correction/recheck is consumed:

- `WP71-75-DES-002` (P0): the artifact records authored emergency timing and flight
  thresholds, but not the 100 exact emergency input/output vectors or a production-
  planner-derived takeoff/landing speed, acceleration, jerk, and secondary-guard
  witness. The physical link accepts height/duration while the real planner uses its
  own derived relations, so the claimed envelope remains self-certified.
- `WP71-75-DES-006` (P1): boundary discovery is still a fixed set plus selected symbol
  lookup rather than production import/transit closure. Direct dependencies including
  `fleet/artifacts.py`, `domain/models.py`, `vehicles/base.py`, and
  `observability/bus.py` can be omitted without failing the audit.

No third automatic review is permitted. Implementation remains closed. Hardware
evidence remains `NOT_RUN`; no connection, permit, motor command, or flight occurred.

<!-- WP80-DESIGN-PAYLOAD-BEGIN -->

## WP-80 — observation-only physical/predicted Digital Twin entry

Status: `IN_PROGRESS`

Independent verification: `DRAFT_UNVERIFIED`

WP-80 is a narrow successor to the review-blocked WP-71 through WP-75 batch. The
operator has now explicitly requested implementation:

> ok implement

The complete originating physical-flight request is frozen verbatim in the WP-71
through WP-75 R1 payload. This successor implements only the minimum safe first slice
selected there: one exact-identity, observation-only Crazyflie connection paired with
one predicted Fast Sim vehicle and one persisted twin session. It makes no command,
timing, motor, watchdog, landing, or flight-envelope claim, so unresolved
`WP71-75-DES-002` is outside and disabled rather than bypassed.

Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.

Ledger preimage SHA-256:
`2ac50325be922703c9798e1ed20f6c2d4dbc92c0f4b15020698c0237585db78e`.

### Intent/value and authority boundary

- **Operator value:** selecting Digital twin in the served Control Center connects to
  one pinned Crazyflie when available, shows measured and predicted state in the same
  familiar surface, and explains absent-radio/identity/telemetry failures without
  silently falling back to simulation.
- **Minimum useful outcome now:** with no radio, the production path and UI retain a
  typed `RADIO_UNAVAILABLE`/disconnected result, create no predicted vehicle or twin
  session, and expose the exact remediation. With a controlled fake link, the same
  path proves binding, reconnect, pairing, ingestion, persistence, and rollback.
- **Authority:** this packet may call only adapter `connect`, `snapshot`, telemetry
  stream, and `disconnect`. It never creates or installs a `CommandPermit`, never calls
  `Vehicle.execute`, never arms, never enables hotkeys/watchdog, and never changes the
  supervisor to a command-capable physical mode.
- **Evidence class:** software production-entry qualification only. Real connection is
  `HARDWARE / OBSERVED_REALTIME / NOT_RUN` until the radio exists and the operator
  separately authorizes it.

### Exact binding and lifecycle

The served API owns a two-phase, persisted binding state under the application cache:

1. `PUT /physical-twin/binding` accepts one complete URI matching the existing
   Crazyflie URI grammar, one operator-chosen vehicle label, and an explicit exact-URI
   confirmation. It never scans. It stores the URI locally, returns only a redacted URI
   plus SHA-256, and does not connect.
2. `POST /physical-twin/connect` is idempotent. It constructs `CrazyflieVehicle` with
   `CflibCrazyflieLink`, calls `connect` on only the pinned URI, and derives an observed
   identity hash from canonical URI, returned URI, firmware identity, protocol version,
   deck parameters, and adapter contract. A first or changed observed identity returns
   `IDENTITY_CONFIRMATION_REQUIRED`; the observed adapter remains connected only for
   observation and no predicted vehicle/session exists.
3. `POST /physical-twin/confirm` accepts the pending connection nonce and exact observed
   identity hash. A mismatch disconnects and clears the pending connection. A match
   persists the confirmed binding hash, registers distinct IDs
   `physical:<binding-id>` and `fast-sim:<binding-id>`, initializes the Fast Sim vehicle
   from the first fresh measured world-frame pose, creates a `TwinCoordinator` session,
   starts paired ingestion, and returns the session plus source/provenance state.
4. After confirmation, later Digital twin selections call `connect` and automatically
   create a fresh monotonically sequenced twin session only when the observed identity
   still matches. Restart never restores a live link/session; it restores only the
   confirmed binding and begins disconnected/observation-only.
5. `POST /physical-twin/disconnect`, mode switching away, startup rollback, and runtime
   shutdown cancel ingestion, mark an existing session complete/failed as applicable,
   disconnect and unregister both vehicles, clear transient state, and retain the
   confirmed binding. No command authority survives because none was ever created.

`binding-id` is the first 16 hexadecimal characters of SHA-256 over the canonical
confirmed observed identity payload. Observed and predicted IDs are distinct, satisfying
the registry's one-ID/one-backend invariant. The selected URI is never discovered or
substituted, and a returned URI mismatch fails closed.

### Paired observation and truthfulness

The new `ObservationTwinService` is application-owned and uses existing
`ApplicationRuntime`, `CrazyflieVehicle`, `SoftwareBackendVehicleProvider` or the same
Fast Sim construction boundary, `TwinCoordinator`, `TwinIngestionBoundary`, and
`DurableTwinStore`. Every `0.100 s` while connected it snapshots both sides and emits
the existing common twin schema with distinct `OBSERVED`/`PREDICTED` roles, vehicle
IDs, sequence, source time, receive monotonic time, units, frames, availability,
quality, and raw/sample hashes. It ingests at most ten batches per second. Missing
physical battery, motor, range, flow, estimator, or other channels emit `MISSING` with
`value=null`; simulated values never fill the observed side. Residuals are derived only
by the existing alignment/unit/frame contract.

The predicted vehicle is a model estimate, not ground truth and not physical safety
authority. The UI labels columns `Measured` and `Predicted`, shows model/session/source
identity and freshness, and never labels either `actual` or `ground truth`. Absent radio,
pending confirmation, stale telemetry, missing channel, rollback, and disconnected
states remain visible in the ordinary Control Center rather than Engineering.

### Public contracts and UI

Add typed binding/status/connect/confirm/disconnect response models to the API and
regenerate `ui/openapi.json` plus `ui/app/lib/api.generated.ts` atomically using the
real `generate:api` command. `ui/app/lib/api.ts` owns the client calls; the Control
Center selector calls `connect` on Digital twin selection, opens the first-bind identity
confirmation when required, and calls `disconnect` when switching back to Simulation.
The selector remains usable with a configured binding even when the radio is absent so
the operator sees the typed failure. Without any binding it opens exact-URI setup.

The new durable interaction pattern and changed physical-service/public-test boundaries
must update `design.md`, `docs/project/DESIGN.md`, and `docs/system/README.md`.

### Claim matrix and independent oracles

| Claim | Production trace | Retained result | Independent oracle and counterexample |
| --- | --- | --- | --- |
| Exact no-scan binding | served selector -> physical-twin API -> service -> `CrazyflieVehicle.connect` -> `CflibCrazyflieLink.connect(exact_uri)` | redacted URI, URI hash, returned-URI/firmware/protocol/deck identity hash, state | fake link records its only URI; wrong returned URI, malformed URI, absent radio, and second-nearby identity produce zero scan and zero session |
| Two-phase first identity | connect -> pending nonce -> served confirm -> persisted binding | pending/confirmed identity hashes and transition | wrong nonce/hash disconnects; restart before confirmation retains no binding and creates no session |
| Paired production session | confirm/reconnect -> physical registration -> predicted registration -> `TwinCoordinator.create_session` -> ingestion -> store | distinct role IDs, session/config, samples/residuals/provenance | independently reconstruct binding ID and first aligned position residual; same-ID, session-create failure, and ingestion failure roll back both registrations |
| Literal availability | adapter snapshots -> common channel mapper -> ingestion/storage -> served timeline/status | source-side availability/value/unit/frame/hash | delete each physical source family in turn; observed side remains `MISSING/null` even when prediction is available |
| Observation-only authority | every public physical-twin route and lifecycle | command/permit counters fixed at zero | spy adapter fails test on `install_command_permit` or `execute`; connect, confirm, reconnect, disconnect, rollback, mode switch, and shutdown all retain zero |
| Served operator surface | production build -> Control Center -> production API | correlated binding/session/source IDs and visible state | desktop/narrow tests cover unconfigured, absent radio, pending identity, paired, stale, and disconnected states; safety/motor/flight controls remain unavailable |

### Boundary closure and tests

The prefreeze artifact
`missions/campaigns/sim/qualification/wp80-design-audit-v1.json` and
`scripts/audit_wp80_design.py` derive the complete recursive local-import closure from
the production seeds, compare it to exact per-path preimage hashes/classifications,
derive the generated pair from `ui/package.json`, validate base/ledger/payload identity,
and assert intended new paths absent. This directly closes the import/transit omission
that blocked WP-71 through WP-75. The implementation manifest must compare this frozen
closure with exact postimages and explain every added, changed, generated, relied-upon,
or deleted path.

Declared implementation checks:

- new service/model production-path tests for binding, first confirmation, reconnect,
  session creation, ingestion, persistence, rollback, absence, and zero authority;
- existing Crazyflie adapter, twin coordinator/ingestion/storage, runtime, API, and
  dashboard tests;
- OpenAPI regeneration drift check and UI component tests, including narrow layout;
- a production-build served browser test against a controlled fake physical link;
- the WP-80 design audit followed by the implementation manifest audit.

### Non-goals and exit

No physical connection is attempted in this implementation environment. No scanning,
permit, preflight, watchdog, E-stop, motor test, arm, takeoff, landing, mission routing,
flight hotkey, model calibration/promotion, or physical qualification is introduced.
WP-72 through WP-75 and their successor work remain blocked.

WP-80 exits only when the full production slice is implemented, declared checks pass,
an exact dirty-tree-safe implementation manifest is frozen, and a fresh independent
implementation verifier returns a passing verdict. Design verification must pass first.

<!-- WP80-DESIGN-PAYLOAD-END -->

### WP-80 design-review handoff

- Delimited payload: 10,430 bytes, SHA-256
  `34eb1e8364f26ecff21ec38eb7c6a945350119241fd74ae0dbd73f49b6c5b903`.
- Recursive-closure artifact: SHA-256
  `b21fedc2c3749345ea265826ac0cebef7bf75e48f7a51811b6371a1fb8e74365`.
- Audit implementation: SHA-256
  `12143dce69a7c1ecd58d57bcfee01fbd51f68edcdf8161f7ef7def07c522352d`.
- Audit result: zero errors; 111-file recursive Python closure, 12-file recursive
  UI closure, 144 total frozen boundaries, and the exact generated API pair.
- Review count: `0`; correction count: `0`; focused recheck count: `0`.
- Hardware evidence: `NOT_RUN`; physical command authority: absent by design.
- Independent verification: `DRAFT_UNVERIFIED`.

<!-- WP80-R1-DESIGN-PAYLOAD-BEGIN -->

## WP-80 R1 consolidated design correction

This is WP-80's sole design correction. It resolves the initial verifier's five P1
findings; the P2 lifecycle details are frozen here only to the minimum needed for a
deterministic production boundary. Where inconsistent, R1 supersedes the initial
WP-80 payload.

### R1-1 — service-private observation adapters and zero authority

Neither physical nor predicted adapter is registered in `ApplicationRuntime.vehicles`,
`SafetySupervisor`, `ParameterService`, fleet providers, mission runners, or active/
selected vehicle state. `ObservationTwinService` owns a private
`CrazyflieObservationAdapter` and a private read-only predicted observer. Their IDs
exist only in the `TwinSessionConfig` and twin store. Consequently every existing
select, mode, connect, preflight, manual command, mission, fleet, and parameter route
receives an unknown vehicle ID if given `physical:<binding-id>` or
`fast-sim:<binding-id>`; tests exercise every command-entry family and assert zero link
command calls.

`CrazyflieObservationAdapter` exposes only `connect`, `snapshot`, `telemetry_stream`,
and `disconnect`; it has no permit installation or execute method. It may share
Crazyflie telemetry conversion internals, but the existing command-capable
`CrazyflieVehicle` validation and behavior remain unchanged. This packet does not add
an observation authority to the general `Vehicle` protocol or registry.

### R1-2 — observation-only connection validation

The observation adapter calls the link with exactly the pinned URI and requires:

- the returned URI exactly equals the pinned URI;
- a non-empty firmware identity or explicit `UNAVAILABLE` identity field;
- a finite protocol version when supplied, exact source/receive clocks, and at least
  one parseable telemetry sample before pairing; and
- no scan/discovery call.

Protocol `<12`, missing Flow2/Multi-ranger, missing high-level commander, controller,
estimator, firmware version, log family, or the pinned cflib version are retained as
`COMMAND_READINESS_UNQUALIFIED` issues and literal unavailable channels; they do not
block observation or first identity confirmation. This relaxation exists only in the
new observation adapter. It can never construct or upgrade to `CrazyflieVehicle` in
place. Any future command-capable transition must disconnect and pass the existing
full command adapter/preflight packet outside WP-80.

### R1-3 — explicit clock, epoch, frame, and predicted tick contract

Each service connection creates a session clock with `session_epoch_monotonic_s` at
the first accepted physical sample. Every retained sample adds these provenance fields
to the twin stream contract:

- `source_clock_id`: exact producer identity (`crazyflie-firmware`,
  `fast-sim-observer`, or `test-fixture`);
- `source_epoch`: integer starting at one and incremented on a raw timestamp rollback;
- `raw_source_timestamp_s`: the unmodified producer time; and
- existing `source_timestamp_s`: session-relative time computed as zero at the first
  sample and thereafter from non-negative within-epoch deltas, while receive monotonic
  time remains separately retained.

Observed firmware and Fast Sim raw clocks are never compared directly. Alignment and
residual derivation use session-relative source time plus receive-time pairing. An epoch
reset invalidates cross-epoch residual pairing and begins a new strictly increasing
stream sequence; raw rollback is retained, not hidden.

Crazyflie position is `HOME`, not `WORLD`. WP-80 stores the first valid HOME pose as a
session origin and may label observed/predicted pose `home` only. It performs no
HOME-to-WORLD transform. If an existing channel definition requires `world`, both pose
sides emit `INCOMPATIBLE/null` until a separately configured transform exists; WP-80
does not invent one. The first required residual oracle therefore uses a compatible
scalar channel such as battery voltage when both sides actually provide it, otherwise
it retains an explicit unavailable residual. It never requires a fabricated position
residual.

The private predicted observer has a read-only `advance_observation(dt_s=0.100)` path
that advances Fast Sim's fixed-step physics/telemetry without accepting commands or
mission intent. Exactly one service loop owns it. Each loop advances once, snapshots
both sides, and ingests one batch; the target period is `0.100 s`, with the existing
500 Hz hard bound remaining authoritative. Tests prove the second and later predicted
timestamps strictly increase, ten batches in one second are admitted, an eleventh
same-window delivery is rejected by the 10 Hz service guard, offset raw clocks align by
session time, epoch reset separates residuals, and frame mismatch stays incompatible.

### R1-4 — fake-link provenance cannot become measured evidence

The link factory returns an immutable provenance kind. Only the production
`CflibCrazyflieLink` factory may request `MEASURED_REAL`, and that result still remains
`HARDWARE / OBSERVED_REALTIME / NOT_RUN` in this radio-absent implementation. Any
injected fake, spy, replay, or test link forces observed and predicted source classes
to `TEST`, creates `TwinSessionConfig(test_only=True)`, and surfaces `Test fixture` in
the status and UI instead of `Measured`. The service rejects a fake factory that claims
`MEASURED_REAL`. Negative tests assert fake sessions are excluded from ordinary
hardware session lists/qualification and cannot emit measured or physical evidence.

### R1-5 — serialized persisted lifecycle

`GET /physical-twin/status` is the single reload/status source. One service-owned
`asyncio.Lock` serializes configure, connect, confirm, disconnect, and shutdown for the
single binding. A pending identity nonce is single-use, bound to the observed identity
hash, expires after `300 s`, and is never persisted. Expiry or mismatch disconnects and
clears pending state. The persisted binding schema is versioned and atomically replaced;
invalid JSON/schema/hash returns `CONFIGURATION_INVALID`, creates no link, and requires
explicit replacement. Idempotent retry while `CONNECTING`, `PENDING_CONFIRMATION`, or
`PAIRED` returns that same transition/session. A new session is created only after a
completed disconnect and new connect transition. Runtime shutdown invokes the same
serialized disconnect path.

### R1-6 — corrected closure, claims, and generated contract

The V2 audit uses these independent production seeds in addition to the initial set:
`src/crazyswarm_app/dashboard.py`, `src/crazyswarm_app/dashboard_service.py`,
`ui/app/layout.tsx`, `ui/app/globals.css`, and `ui/worker/index.ts`. UI traversal parses
side-effect CSS imports as well as TypeScript imports. Python and UI recursive closures
are recomputed from repository sources, not copied from the artifact.

The V2 artifact stores structured claim rows with exact owner/entry paths. The audit
extracts the six backticked claim keys below from this payload, compares them to those
rows, requires every claim owner and entry in the recursively discovered/fixed
manifest, derives the OpenAPI pair from `ui/package.json`, validates current exact
preimages after generated-output drift, and retains the initial payload plus R1 hashes,
base commit, and byte-exact ledger preimage.

### R1 corrected claim matrix

| Claim key | Exact owners/entries | Focused failure oracle |
| --- | --- | --- |
| `exact_no_scan_binding` | physical-twin API, observation service, observation adapter, cflib link | absent/wrong URI and a scan-spy yield zero scan/session/command |
| `two_phase_first_identity` | physical-twin models/API, persisted service state | wrong/expired nonce or corrupt state disconnects and creates no session |
| `paired_production_session` | service-private physical/predicted observers, coordinator, ingestion, store | later ticks, offset clocks, epoch reset, frame mismatch, rollback |
| `literal_availability` | observation mapper, twin models/ingestion/replay/store, status/UI | remove each channel; no predicted-to-observed substitution |
| `observation_only_authority` | private service plus all existing vehicle/mode/preflight/manual/mission/fleet/parameter entries | submit both private IDs to every entry family; all reject and link command count stays zero |
| `served_operator_surface` | dashboard/service, FastAPI route, app layout/CSS/page, Control Center/API client, worker proxy | served desktop/narrow unconfigured/test/pending/paired/stale/disconnected states |

The corrected audit artifacts are
`missions/campaigns/sim/qualification/wp80-r1-design-audit-v2.json` and
`scripts/audit_wp80_design_r1.py`. All other initial WP-80 non-goals, requirements,
software-only evidence class, implementation checks, and implementation-verification
gate remain in force.

### R1 state

Status: `PLANNED`

Independent verification: `DRAFT_UNVERIFIED`

Hardware evidence: `NOT_RUN`; physical/predicted adapters remain service-private and
command-inert.

<!-- WP80-R1-DESIGN-PAYLOAD-END -->

### WP-80 R1 focused-recheck handoff

- Initial verdict: `BLOCKED_WITH_FINDINGS` (five P1 `MUST_FIX_NOW`, one deferred P2).
- R1 payload: 9,060 bytes, SHA-256
  `d27618ace58b7a125221688c45465e75d780187a7cc83d87ec55fa05fe2fb1c9`.
- V2 closure/claim artifact: SHA-256
  `71f0f96f57d35cb0ad72beded06a49b7aba0fa4161f82a1b72d9cac9947c12cb`.
- V2 audit implementation: SHA-256
  `9aa2421a4aa41658f5b1214715379c19b26492689533dafc2752ce003e1ce645`.
- V2 audit result: zero errors; 113-file recursive Python closure, 15-file
  recursive UI/worker/CSS closure, 149 total frozen boundaries, six reconciled claim
  rows, and the exact current generated API pair.
- Review count: `1`; correction count: `1`; focused recheck count: `1`.
- Hardware evidence: `NOT_RUN`; test links are forced to `TEST` provenance.
- Independent verification: `DESIGN_VERIFIED`.

### WP-80 design-gate verdict

Status: `IMPLEMENTED`

Independent verification: `BLOCKED_WITH_FINDINGS`

The focused recheck resolves all five P1 findings and the minimum P2 lifecycle
ambiguity. The prior numerical-flight finding is safely outside scope. Implementation
is authorized only for the initial+R1 observation-only composite; payload hashes and
the V2 audit identities above are binding.

<!-- WP80-IMPLEMENTATION-PAYLOAD-BEGIN -->

### WP-80 implementation handoff

Accepted design SHA-256: initial
`34eb1e8364f26ecff21ec38eb7c6a945350119241fd74ae0dbd73f49b6c5b903`; R1
`d27618ace58b7a125221688c45465e75d780187a7cc83d87ec55fa05fe2fb1c9`.

Status: `IMPLEMENTED`

Independent verification: `BLOCKED_WITH_FINDINGS`

Implemented production boundary:

- one atomic, versioned exact-URI binding with no discovery call;
- one service-private observation facade exposing connect, snapshot, telemetry stream,
  and disconnect only, with no permit or execute surface;
- first-seen identity nonce/confirmation, confirmed reconnect, corrupt-state failure,
  serialized lifecycle, shared shutdown cleanup, and redacted served status;
- confirmed-identity-owned `physical:<binding-id>` / `fast-sim:<binding-id>` private
  IDs, with no URI-hash identity substitution;
- one private Fast Sim predictor advanced at 0.100 s by the observer loop, an explicit
  ten-batch-per-second admission guard, one-based rollback epochs, raw producer
  clock/time plus mapped session time, and no cross-reset residual reach-back;
- all 28 common channels on both roles for every accepted batch, with literal
  `MISSING/null` sensor families and explicit `HOME` to `WORLD`
  `INCOMPATIBLE/null` pose/velocity instead of a fabricated transform;
- authenticated physical-twin lifecycle routes and the existing Control Center
  Simulation/Digital twin selector with exact binding, identity confirmation, source
  telemetry/freshness/missing-state cards, sample count, readiness gaps, disconnect on
  Simulation selection, and observation-only campaign/mission Play lock;
- partial session-creation and asynchronous stream failures close both adapters and
  retain only failed session evidence, never an orphan active/ready session;
- physical mission Play, hotkeys, permits, motors, arm, takeoff, landing, and all
  existing vehicle/fleet/mission/parameter command routes remain outside and locked.

Software evidence:

- focused Python qualification: 58 passed across the API contract, dashboard/release,
  Crazyflie adapter, observation service, twin persistence/pipeline, and simulation
  contracts; the final packet-specific subset is 10 passed;
- UI unit qualification: 140 passed, including unconfigured Digital twin setup and
  exact binding/test-provenance API behavior, measured/predicted source state,
  Simulation-mode disconnect, and the Digital Twin Play lock;
- production UI build, TypeScript typecheck, packet-owned ESLint, Ruff, mypy, OpenAPI
  regeneration, and generated TypeScript all pass;
- the broader API suite retains a pre-existing concurrent campaign-catalog mismatch
  (`case_count` 54 versus a stale expected 55), outside WP-80 paths;
- the production dashboard served HTTP 200 locally. The in-app browser could not
  reach either localhost or the host bridge, so live visual inspection is explicitly
  `NOT_RUN`; rendered component tests and the production build do not upgrade it.

Hardware evidence: `NOT_RUN`. No radio scan, radio connection, permit, motor command,
or flight occurred. Injected links are forced to `TEST` and cannot create ordinary
measured/hardware evidence.

Independent implementation review fix pass: the initial implementation verdict was
`BLOCKED_WITH_FINDINGS` with five P1 findings. This single permitted fix pass addresses
identity ownership, clock/epoch/10 Hz semantics, full common-schema/operator state,
session/stream rollback, and mode-switch/Play cleanup. The sole focused recheck
reproduced all five code corrections, the 149-boundary manifest, generated contracts,
and targeted Python/UI evidence. It retained one original P1 because the production
build was not reachable for a served in-app-browser inspection; `REQ-WFL-038` forbids
promoting jsdom/rendered-HTML/build evidence to that evidence class. The final gate
verdict is therefore `BLOCKED_WITH_FINDINGS`; no third automatic review is permitted.

Frozen manifest:
`missions/campaigns/sim/qualification/wp80-implementation-manifest-v1.json`, generated
and checked by `scripts/freeze_wp80_implementation.py`.

<!-- WP80-IMPLEMENTATION-PAYLOAD-END -->

<!-- WP81-DESIGN-PAYLOAD-BEGIN -->

## WP-81 — region-native landing handoff integration slice

### Origin, predecessor, and intent/value card

The operator asked to remove the shaky 1D terminal behavior that appears to “snap” or
“click” into an exact goal even though landing is admitted by a region, then explicitly
said, “ok implement”. WP-76 through WP-79 could not pass their batch design gate because
unrelated catalog/UI/qualification boundaries drifted and three successor contracts
remained incomplete. WP-81 is a new, smaller successor for the explicitly requested
minimum value only; it does not reopen or upgrade WP-76 through WP-79.

| Item | Frozen decision |
| --- | --- |
| Minimum useful outcome | A fresh valid pose already admitted by the immutable landing region becomes the nominal descent XY, with no separate center-seeking alignment command. |
| Necessary prerequisites | Existing goal-region capture, Supervisor command authority, contact-aware simulated descent, MissionRunner, and retained mission result. |
| Optional work excluded | Catalog cleanup, verdict separation, broad qualification, public Campaign API/UI proof, and new freshness policy. |
| Safety invariant | Region, speed, landing-height, correction, contact, and disarm gates are not weakened. Ground truth remains evidence, never command authority. |
| Point-target invariant | An explicit diversion remains an exact point target and retains point-alignment behavior. |
| Historical invariant | Existing cases/runs and the previously applied 85-run Old boundary remain unchanged. |

### Frozen design identity

| Field | Value |
| --- | --- |
| Base commit | `40cd9947f87eb9bf2719d72e7c72ea867eab9977` |
| Artifact | `missions/campaigns/sim/qualification/wp81-design-audit-v1.json` |
| Artifact SHA-256 | `38eccb9074be29fdad131eb8913b6b4e9258b52ba98b1b690467e85520f2a33e` |
| Audit command | `./.venv/bin/python scripts/audit_wp81_design.py` |
| Exact current boundaries | `15` paths: seven implementation-owned and eight relied upon unchanged |
| Canonical Status | `PLANNED` |
| Independent verification | `BLOCKED_WITH_FINDINGS` (R2 final) |

The audit freezes exact dirty-worktree preimages, not the ambient diff. The seven
implementation-owned paths are:

1. `docs/project/requirements/EVIDENCE_AND_REVIEW.md`
2. `docs/reference/LANDING_GOAL_REGION_V1.md`
3. `src/crazyswarm_app/domain/commands.py`
4. `src/crazyswarm_app/domain/goals.py`
5. `src/crazyswarm_app/missions/base.py`
6. `src/crazyswarm_app/simulation/vehicle.py`
7. `tests/missions/test_trajectory_execution.py`

The unchanged transit boundary is `domain/trajectory.py`, `missions/models.py`,
`missions/observation.py`, `missions/authority.py`, `missions/runner.py`,
`missions/script.py`, `safety/policy.py`, and `safety/supervisor.py`. The audit parses
the source tree independently and requires unique owners for `MissionRunner`,
`ScriptMission`, `MissionContext`, `MissionFleetAuthority`, `SafetySupervisor`,
`LandCommand`, `SimulatedVehicle`, `GoalCaptureRecord`, and `MissionResult`; every
discovered owner must appear in the exact manifest. Any required edit outside the
seven owned paths invalidates this design rather than silently widening it.

### Contract and production transit

`REQ-EVI-005` is clarified without weakening it: a landing **point** requires
horizontal alignment to that point; a landing **region** requires capture inside its
horizontal/vertical/speed bounds and then authorizes descent at the fresh accepted
capture XY. “Honor the region” does not mean “move to its exact center”. Contact-aware
descent and disarm-after-contact remain mandatory. Coverage also includes
`REQ-MOT-010`, `REQ-MOT-011`, and workflow requirements `REQ-WFL-014`, `017`, `018`,
`020`, `023`, `029`, `034`, `036`, `039`, `042`, `046`, and `047`.

The intended integration transit is:

`MissionRunner` -> accepted `LandExecutionOperation` -> `ScriptMission` ->
`MissionContext.capture_and_land` -> `MissionFleetAuthority.execute` ->
`SafetySupervisor.land` -> `LandCommand` -> `SimulatedVehicle._land` ->
`GoalCaptureRecord` -> `MissionResult`.

This packet claims that integration path only. It does not claim public Campaign API,
storage/materialization, analyzer, or served UI qualification.

### Exact behavior and evidence changes

1. `MissionContext.capture_and_land` stores the estimated position from the aligned
   `GoalCaptureAttempt` and uses its X/Y plus the immutable landing Z as the nominal
   `LandCommand.target_position_m`.
2. `LandCommand` accepts a goal-bound nominal target only when its X/Y lies inside the
   immutable horizontal region and its Z equals the immutable landing Z. For a
   `DIVERT` goal, the declared diversion point remains the only admissible out-of-region
   target.
3. `SimulatedVehicle._land` skips the separate horizontal `_move_to` only when the
   explicit target is inside the nominal goal region. It records
   `alignment_duration_s == 0`; generic point landings and diversions keep the existing
   alignment phase.
4. Each `GoalCaptureAttempt` retains the observation source timestamp needed to bind
   the independent telemetry window. `GoalCaptureRecord` advances to schema v3 and retains
   `authorized_capture_position_m`, `descent_target_position_m`,
   `commanded_pre_descent_horizontal_adjustment_m`, and `alignment_duration_s`.
   Rejected records retain no invented descent values. Representative v1 and v2
   payload fixtures omit every v3 field and must parse with those values remaining
   `None`; no migration may invent descent evidence.
5. Terminal success remains region-relative. The previous test expectation of exact
   center error at most `0.02 m` is replaced by the immutable region tolerance plus the
   new exact command-handoff oracle; this is not a widened landing region.

### Executable prefreeze witnesses

The audit validates exact witness and result set equality, recomputes each result, and
fails if a witness/result is missing, duplicated, or changed:

| Witness | Expected result |
| --- | --- |
| Offset capture: center `1.35`, capture/target `1.30`, tolerance `0.10`, speed `0.10` | Command valid, descent authorized, capture-to-target XY `0`. |
| Inclusive edge: capture/target `1.45` | Command valid and descent authorized. |
| Outside edge: capture/target `1.450001` | Nominal command invalid and descent unauthorized. |
| Overspeed: capture `1.30`, speed `0.100001` | Region command is geometrically valid; capture does not authorize descent. |
| Wrong landing Z: `0.000001` for goal Z `0` | Command invalid. |
| Exact diversion point: declared/commanded X `0.25` | Command valid; explicit point semantics retained. |
| Off diversion point: commanded X `0.249999` | Command invalid. |
| Vertical miss: approach Z `0.30`, capture Z `0.350001`, tolerance `0.05` | Descent unauthorized while the landing command geometry remains valid. |
| Invalid observation at otherwise valid pose/speed | Descent unauthorized. |
| `DIVERT` goal captured nominally inside its original region | Nominal region target remains valid; diversion point is not forced. |

The independent telemetry oracle binds samples at or after the accepted attempt’s
source timestamp and ends immediately before observed altitude drops more than
`0.005 m` below the accepted capture Z. Using retained estimated `position_m`, it
requires both maximum horizontal displacement from the accepted capture and maximum
progress toward the exact region center to be at most `0.010 m`. The audit freezes a
stationary passing vector and a hidden-center-seek failing vector that moves from X
`1.30` through `1.325` to center X `1.35` before descending. Removing either vector,
changing either threshold, or flipping either expected disposition fails the audit.

No new stale-observation threshold is part of WP-81. `SafetySupervisor.observe`
continues to request a current adapter snapshot and `MissionObservation.valid` remains
required; a broader source/receive freshness contract requires a future independently
designed packet.

### Test sensitivity and exit evidence

Before the implementation edit, add the retained-evidence assertions to the existing
MissionRunner integration test and confirm failure because schema-v2 evidence lacks
the capture/target/alignment fields and the old command targets the exact center. Then:

- run the canonical route in `ACCELERATED` and `OBSERVED_REALTIME` Fast Sim modes;
- require `MissionStatus.SUCCEEDED`, zero commanded capture-to-target XY within
  `1e-9 m`, zero nominal alignment duration, terminal truth inside the immutable
  region, contact before disarm, and motors cut after contact;
- independently sample the pre-descent telemetry window and require both frozen
  `0.010 m` anti-centering bounds, so implementation-reported zero alignment cannot
  conceal observed center-seeking motion;
- exercise inclusive/outside, overspeed, vertical miss, invalid observation, wrong-Z,
  renamed-goal, exact/off-point diversion, and a `DIVERT` goal captured nominally in
  its original region;
- parse representative schema-v1 and schema-v2 goal-capture payloads without v3
  fields and require all new evidence values to remain `None`;
- retain the existing bounded-correction and unsafe-correction regressions; and
- run the focused mission file plus adjacent command/simulator tests needed by any
  failure, without claiming the blocked broader qualification.

### Claim matrix

| Claim | Trigger/effect | Retained observation | Independent oracle | Counterexample | Boundary / environment / clock |
| --- | --- | --- | --- | --- | --- |
| Region-native accelerated landing | MissionRunner accepted program changes nominal land target and simulator alignment phase | v3 capture, command target, attempt source time, alignment duration, contact/disarm | Reconstruct capture-to-target XY and enforce `0.010 m` pre-descent displacement/center-progress telemetry bounds | Outside/vertical/invalid/overspeed/wrong-Z and DIVERT child cases | `INTEGRATION / FAST_SIM / ACCELERATED` |
| Region-native realtime landing | Same integration transit under realtime clock | v3 capture plus source-clock terminal evidence | Same exact telemetry-window reconstruction without trusting reported alignment | Renamed goal, hidden-center vector, and clock-mode comparison | `INTEGRATION / FAST_SIM / OBSERVED_REALTIME` |

### Non-goals and implementation order

WP-81 does not change controller gains, trajectory generation, dynamic replanning,
catalog grouping, API schemas/generated clients, review verdicts, run-history state,
or physical/higher-fidelity behavior. It does not claim that a convenient current XY
outside the region is acceptable.

Implementation begins only after a fresh independent `DESIGN_VERIFIED` verdict for
this exact payload. After the author test loop, WP-81 becomes
`IMPLEMENTED_UNVERIFIED`, receives an exact pre/post implementation manifest, and is
reviewed by a different fresh implementation verifier. One review plus one recheck is
the maximum at each gate.

<!-- WP81-DESIGN-PAYLOAD-END -->

### WP-81 design-review handoff and consolidated correction

- Initial payload: 8,886 bytes, SHA-256
  `ae4f89b0dcc3424dc132d70faaf46f01b183af71c0e6695e6fdfc252a9775843`.
- Initial artifact: SHA-256
  `68122a906a30a893d7e21e8b4f1e22665a1fce0792b79b5b83f1ff16b899a6fc`.
- Reviewer: `/root/wp81_design_verifier` (`work_packet_verifier`), 2026-08-20.
- Initial verdict: `BLOCKED_WITH_FINDINGS`; three P1 and one P2.
- Consolidated correction: added independently discovered transit-class ownership and
  `MissionFleetAuthority`; froze an executable telemetry anti-centering oracle with
  passing and hidden-center-seek vectors; added vertical, invalid-observation, and
  nominal-capture-on-DIVERT witnesses; and froze v1/v2 compatibility fixtures.
- Revised payload: 11,093 bytes, SHA-256
  `a7a9d10dc69dec8ce98f2146758f02ce3631698284917f63917b2c244366c628`.
- Revised artifact: SHA-256
  `38eccb9074be29fdad131eb8913b6b4e9258b52ba98b1b690467e85520f2a33e`;
  15 exact boundaries, two claim rows, ten capture witnesses, two telemetry vectors,
  and two historical-schema fixtures.
- Review count: `1`; correction count: `1`; focused recheck count: `1`.
- Model/effort and token/time usage: not exposed. Proxies: one review, one correction,
  zero runtime runs, seven implementation-owned paths.
- Focused recheck verdict: `BLOCKED_WITH_FINDINGS`; implementation is unauthorized
  and the automatic design-review budget is exhausted.
- Resolved on recheck: vertical, invalid-observation, and nominally captured `DIVERT`
  variants are isolated; v1/v2 compatibility fixtures and assertions are declared;
  all revised identities and preimages reproduced.
- Remaining P1 findings: transit discovery still begins from a hand-authored symbol
  seed and does not independently derive `LandExecutionOperation`; the telemetry
  oracle stops before descent and can miss a center-seeking move that begins during
  descent but before contact.
- Final reviewer: `/root/wp81_design_verifier`; no third automatic pass is permitted.
- Mechanical status-only closeout changed the reviewed payload from 11,093 bytes,
  SHA-256 `a7a9d10dc69dec8ce98f2146758f02ce3631698284917f63917b2c244366c628`
  to 11,082 bytes, SHA-256
  `bb888d7ef47a33c1b4d7d81420a5d0d2aade838acd64f0a81e1367146e45672a`;
  only the verification field changed from recheck-pending to final.

<!-- WP82-DESIGN-PAYLOAD-BEGIN -->

## WP-82 — P1 closure for region-native landing integration

### Authorization, value, and predecessor boundary

The operator explicitly authorized this successor with “ok continue with the p1”.
WP-82 resolves only the two P1 gates left by review-blocked WP-81 and, if independently
design-verified, implements the same minimum useful outcome: an accepted in-region
capture remains the nominal XY through landing instead of snapping to the exact region
center. It does not reopen WP-81’s exhausted review or the broader WP-76–79 batch.

| Item | Frozen value |
| --- | --- |
| Minimum outcome | Remove nominal center-seeking after valid region capture and retain independently checkable evidence through contact. |
| Necessary prerequisite | A mechanically complete integration transit and a telemetry oracle sensitive before and during descent. |
| Safe fallback | Current exact-center behavior remains unchanged until both gates pass. |
| Non-goals | Catalog/UI/API qualification, new freshness policy, controller tuning, dynamic replanning, physical claims, and broad run qualification. |
| Canonical Status | `PLANNED` |
| Independent verification | `REVIEW_BLOCKED` |

### Frozen identity and exact boundary

| Field | Value |
| --- | --- |
| Base commit | `40cd9947f87eb9bf2719d72e7c72ea867eab9977` |
| Prefreeze artifact | `missions/campaigns/sim/qualification/wp82-design-audit-v1.json` |
| Artifact SHA-256 | `18177db4ebd5645164a71cd4c5c9f76cf25a500be6ffc1053d6c0239a0001f43` |
| Audit implementation | `scripts/audit_wp82_design.py` |
| Audit SHA-256 | `a18d5a5908fd269c2f179896dc29514b3eb204a5ca8530c6cf5da7f242812050` |
| Reproduction | `./.venv/bin/python scripts/audit_wp82_design.py` |
| Executed transit | `37` production files called independently by each of the existing accelerated and realtime MissionRunner integration routes |
| Exact manifest | `43` paths with dirty-worktree preimage hashes and edit classification |

The boundary is not seeded from an expected symbol or path list. The audit loads the
existing `tests/missions/test_trajectory_execution.py::_run_route` fixture, executes it
separately in `ACCELERATED` and `REALTIME` modes under `sys.setprofile`, requires each
mission result to be `SUCCEEDED`, and records every called function whose source is
under `src/crazyswarm_app`. The exact per-clock called-file sets, function names,
preimages, the eight implementation-owned paths, and relied-upon design support are one
frozen artifact. Validation reruns both integrations and requires exact per-clock
runtime-transit equality.
Removing any called owner—including `domain/trajectory.py` or
`missions/authority.py`—fails mechanically without relying on a hand-authored transit
seed.

The eight implementation-owned paths are:

1. `docs/project/requirements/EVIDENCE_AND_REVIEW.md`
2. `docs/project/REQUIREMENTS_CHANGELOG.md`
3. `docs/reference/LANDING_GOAL_REGION_V1.md`
4. `src/crazyswarm_app/domain/commands.py`
5. `src/crazyswarm_app/domain/goals.py`
6. `src/crazyswarm_app/missions/base.py`
7. `src/crazyswarm_app/simulation/vehicle.py`
8. `tests/missions/test_trajectory_execution.py`

All other runtime-discovered paths are `RELIED_UPON_UNCHANGED`. An implementation edit
outside the owned set invalidates this design instead of widening it silently.

### Contract retained from WP-81

`REQ-EVI-005` distinguishes point from region semantics. A point target aligns to its
point. A region authorizes descent only after valid horizontal, vertical, and speed
capture, then uses the accepted estimated capture XY and immutable landing Z. Ground
truth remains evidence only. Contact-aware descent, terminal region membership, and
disarm-after-contact remain unchanged. Coverage includes `REQ-MOT-010`,
`REQ-MOT-011`, and `REQ-WFL-014`, `017`, `018`, `020`, `023`, `029`, `034`, `036`,
`039`, `042`, `046`, and `047`. Because this operator correction changes a durable
landing preference, `REQ-WFL-003` also requires the requirements changelog update;
`scripts/check_requirement_catalog.py` is frozen as relied-upon validation support.

The implementation transit is discovered from the running integration and includes:

`MissionRunner` -> `LandExecutionOperation` -> `ScriptMission` ->
`MissionContext.capture_and_land` -> `MissionFleetAuthority.execute` ->
`SafetySupervisor.land` -> `LandCommand` -> `SimulatedVehicle._land` ->
`GoalCaptureRecord` -> `MissionResult`.

WP-82 claims `INTEGRATION / FAST_SIM / ACCELERATED` and
`INTEGRATION / FAST_SIM / OBSERVED_REALTIME`, not public API or served UI behavior.

### Full capture-to-contact telemetry oracle

The independent oracle uses the retained estimated `position_m` signal and the closed
source interval from the accepted attempt through contact. The attempt, every selected
sample, and contact must retain the same `source_clock_id` and clock epoch; sequence
numbers must strictly increase and source timestamps must be nondecreasing. It requires:

- at least four samples in the interval;
- the final included sample timestamp and sequence to equal the retained contact pair;
- final estimated Z at most `0.010 m`;
- maximum horizontal displacement from the accepted capture XY at most `0.015 m`; and
- maximum progress toward the exact region center at most `0.010 m`.

The executable audit retains thirteen exact vectors with full computed outputs:

1. stationary capture through descent/contact: pass;
2. center seek before descent: fail;
3. center seek during descent after Z has already dropped: fail; and
4. one isolated failing vector for each of sample count, contact coverage, horizontal
   displacement, center progress, terminal Z, wrong clock, epoch reset, sequence
   reorder, and timestamp reorder; and
5. one all-numeric-threshold equality vector that passes exactly at every bound.

The during-descent vector starts at `(1.30, 0, 0.30)`, remains at X `1.30` while Z
drops, then moves through X `1.325` and center X `1.35` before contact. It must fail.
The audit requires exact witness/result membership and recomputes every metric. For
each isolated vector it proves that exactly the named guard fails while every other
guard passes. Removing a vector, changing a threshold, weakening clock binding, or
flipping an outcome fails mechanically.

### Implementation and evidence schema

After `DESIGN_VERIFIED` only:

1. retain the aligned observation source timestamp, clock ID, epoch, and sequence in
   `GoalCaptureAttempt`;
2. use that aligned estimated X/Y plus immutable landing Z as the nominal
   `LandCommand.target_position_m`;
3. validate nominal target X/Y inside the immutable region and Z at the immutable
   landing height, while an out-of-region diversion remains valid only at its exact
   declared point;
4. skip the simulator’s separate horizontal alignment only for a nominal in-region
   target; generic point/diversion landing retains alignment;
5. advance `GoalCaptureRecord` to schema v3 with
   `authorized_capture_position_m`, `descent_target_position_m`,
   `commanded_pre_descent_horizontal_adjustment_m`, `alignment_duration_s`, and the
   contact clock ID/epoch/sequence paired with contact time;
6. retain v1/v2 readability with absent v3 values remaining `None`; and
7. clarify the durable requirement/reference contract without widening the admitted
   landing region.

The inherited executable capture witnesses remain exact: offset and inclusive-edge
success; outside-edge, overspeed, vertical miss, invalid observation, wrong landing Z,
and off-diversion rejection; exact diversion success; and nominal region capture on a
goal that declares `DIVERT` success. Compatibility is no longer asserted with schema
descriptors: the audit freezes complete v1 and v2 `GoalCaptureRecord` payloads, parses
both through the production model, and requires every v3 record/attempt field to remain
`None`. The WP-82 audit also imports and recomputes the frozen WP-81 capture witnesses
so resolved safety findings cannot disappear.

### Regression sensitivity and exit

Before production edits, add assertions to the existing MissionRunner integration test
for the v3 handoff evidence and the full capture-to-contact telemetry oracle. Run that
test on the preimage and retain failure because the old code targets the exact center,
reports a positive alignment duration, and lacks v3 evidence. Then implement the
vertical slice and require:

- accelerated and observed-realtime canonical routes succeed;
- capture-to-command XY is zero within `1e-9 m`;
- nominal alignment duration is zero;
- all capture-to-contact telemetry bounds pass independently;
- terminal truth remains inside the immutable goal region;
- contact precedes disarm and motors cut after contact;
- all inherited boundary/child/schema cases pass; and
- existing bounded-correction, unsafe-correction, command, and simulator regressions
  remain green.

Self-authored evidence supports only `IMPLEMENTED_UNVERIFIED`. The author then freezes
exact pre/post hashes and changed sections against this artifact and uses a different
fresh implementation verifier.

### Claim matrix

| Claim | Real trigger/effect | Retained observation | Independent oracle | Counterexamples | Boundary |
| --- | --- | --- | --- | --- | --- |
| Accelerated region-native landing | Executed MissionRunner integration changes nominal descent target/alignment | Attempt/contact source identity, capture/target, alignment, telemetry, contact/disarm | Clock-bound full capture-to-contact displacement and center-progress reconstruction | Pre/during-descent seek plus nine isolated guards and equality pass | `INTEGRATION / FAST_SIM / ACCELERATED` |
| Realtime region-native landing | Independently executed and profiled transit under realtime source clock | Same v3 evidence and complete clock-bound contact interval | Same oracle with realtime source identity | Same isolated guards, renamed goal, DIVERT child | `INTEGRATION / FAST_SIM / OBSERVED_REALTIME` |

### Review order and cost boundary

Use one fresh design verifier. Permit one consolidated correction and one focused
recheck. Implementation starts immediately only after `DESIGN_VERIFIED`. Model/effort
and token/time usage are recorded when exposed; otherwise use review, correction,
runtime-run, and changed-file counts without inventing cost.

<!-- WP82-DESIGN-PAYLOAD-END -->

### WP-82 design-review handoff and consolidated correction

- Frozen design payload reviewed initially: 9,184 bytes, SHA-256
  `5e5bb1ee502e6f19d6186908ae24b7ebae84320de7a71b3c289239b7c4bec979`.
- Initial independent verdict: `REVIEW_BLOCKED` with five P1 findings and no P0:
  telemetry guard vectors were not isolated; source clock/epoch/sequence identity was
  not bound through contact; historical schema inputs were descriptors rather than
  complete production-parsed records; the `REQ-WFL-003` changelog/check boundary was
  absent; and only the accelerated transit was executed.
- Single permitted consolidated correction: thirteen vectors now include one isolated
  failure per guard and an all-threshold equality pass; full source identity and order
  are checked; complete v1/v2 payloads are parsed through `GoalCaptureRecord`; the
  requirement changelog and catalog checker are frozen; and accelerated plus realtime
  routes are independently executed and profiled.
- Corrected artifact: SHA-256
  `18177db4ebd5645164a71cd4c5c9f76cf25a500be6ffc1053d6c0239a0001f43`;
  corrected audit: SHA-256
  `a18d5a5908fd269c2f179896dc29514b3eb204a5ca8530c6cf5da7f242812050`.
- Corrected exact design payload submitted for the one focused recheck: 10,366 bytes,
  SHA-256 `a3100a5b8601dce00f3e9ae0ff410a50acb1b9cc9801e18578d2361fa4cab3d1`.
- Focused recheck verdict: `BLOCKED_WITH_FINDINGS`, no P0 and one remaining P1.
  `WP82-DES-002` showed that a window whose first sample occurs after the accepted
  capture timestamp/sequence passes every frozen guard, leaving capture-to-first-sample
  motion invisible. The single correction/recheck allowance is exhausted; WP-82 is
  not authorized for implementation.

<!-- WP83-DESIGN-PAYLOAD-BEGIN -->

## WP-83 — capture-endpoint closure for region-native landing

### Authorization and minimum outcome

The operator’s “ok continue with the p1” authorizes this fresh successor after WP-82’s
exhausted focused recheck. WP-83 carries forward the independently accepted WP-82
corrections and resolves only its remaining P1: prove that retained telemetry covers
the accepted capture endpoint as well as contact before implementing the region-native
landing slice.

| Item | Frozen value |
| --- | --- |
| Minimum outcome | Accepted capture timestamp/sequence is the first sample in the independently checked capture-to-contact interval. |
| Safe fallback | Exact-center landing behavior remains unchanged until design and implementation gates pass. |
| Non-goals | New freshness policy, controller tuning, dynamic replanning, physical claims, UI/API/catalog qualification, and broad run qualification. |
| Canonical Status | `IMPLEMENTED` |
| Independent verification | `IMPLEMENTATION_VERIFIED` |

### Frozen identity, boundary, and requirements

| Field | Value |
| --- | --- |
| Base commit | `40cd9947f87eb9bf2719d72e7c72ea867eab9977` |
| Originating request | `ok continue with the p1` |
| Predecessor | `WP-82 BLOCKED_WITH_FINDINGS` |
| Prefreeze artifact | `missions/campaigns/sim/qualification/wp83-design-audit-v1.json` |
| Artifact SHA-256 | `91665b666888d30577b3c3374ad49fa175388742459432ba1bb6929b66a7fe04` |
| Audit implementation | `scripts/audit_wp83_design.py` |
| Audit SHA-256 | `7ec389a99b7bbe9c91e86175fde10f65f2816a7b9d494335ccd1c5a628dbcaf8` |
| Reproduction | `./.venv/bin/python scripts/audit_wp83_design.py` |
| Executed transit | `37` production files independently called in each of accelerated and realtime modes |
| Exact manifest | `44` hashed paths: eight implementation-owned, both predecessor audits and catalog checker relied upon, plus runtime transit |

The implementation-owned set remains exactly
`docs/project/requirements/EVIDENCE_AND_REVIEW.md`,
`docs/project/REQUIREMENTS_CHANGELOG.md`,
`docs/reference/LANDING_GOAL_REGION_V1.md`,
`src/crazyswarm_app/domain/commands.py`,
`src/crazyswarm_app/domain/goals.py`,
`src/crazyswarm_app/missions/base.py`,
`src/crazyswarm_app/simulation/vehicle.py`, and
`tests/missions/test_trajectory_execution.py`. Any substantive implementation edit
outside that set invalidates the design. The frozen requirements are `REQ-EVI-005`,
`REQ-MOT-010`, `REQ-MOT-011`, and `REQ-WFL-003`, `014`, `017`, `018`, `020`, `023`,
`029`, `034`, `036`, `039`, `042`, `046`, and `047`.

The audit executes the existing MissionRunner integration fixture under
`sys.setprofile` separately in accelerated and realtime modes, requires both results
to succeed, freezes every called production file/function and preimage, parses full
v1/v2 `GoalCaptureRecord` payloads through the production model, and recomputes all
inherited capture and telemetry witnesses.

### Closed capture-to-contact oracle

In addition to WP-82’s accepted sample-count, contact-coverage, source clock, epoch,
strict sequence, nondecreasing timestamp, horizontal displacement, center progress,
and terminal-Z guards, WP-83 adds `covers_capture`. The first selected sample timestamp
must equal `GoalCaptureAttempt.source_timestamp_s` within `1e-9 s`, and its sequence
must equal the attempt source sequence. The stationary pass explicitly freezes
sequence 99 before capture, 100 at capture, 104 at contact, and 105 after contact.

The fourteenth vector begins only at timestamp `5.1`, sequence 101 for a capture at
timestamp `5.0`, sequence 100. It otherwise has four samples, covers contact, retains
the same clock/epoch, is ordered, stationary in XY, and reaches Z zero. The audit proves
that exactly `covers_capture` fails. This closes the invisible capture-to-first-sample
motion counterexample without changing any numeric tolerance.

### Implementation contract and declared evidence

After `DESIGN_VERIFIED`, first add integration assertions and retain their failure on
the preimage. Then implement the unchanged vertical slice:

1. retain attempt source timestamp, clock ID, epoch, and sequence;
2. command accepted estimated capture X/Y plus immutable landing Z for nominal region
   capture, while exact diversion/point semantics remain unchanged;
3. skip separate simulator horizontal alignment only for that nominal in-region target;
4. emit schema-v3 capture/target/alignment and contact source-identity evidence while
   complete frozen v1/v2 records keep all v3 values `None`;
5. reconstruct the closed capture-through-contact estimated-position interval for both
   clock modes and require all ten guards independently; and
6. update the durable requirement, reference, and `REQ-WFL-003` changelog entry.

Declared checks are the preimage regression failure; accelerated and realtime
MissionRunner route tests; inherited goal capture/command/simulator regressions;
historical schema parsing; `scripts/check_requirement_catalog.py`; and the WP-83 audit.
Self-authored checks can establish only `IMPLEMENTED_UNVERIFIED`. A different fresh
implementation verifier must trace the production path and exercise an independent
counterexample before any `QUALIFIED` or `COMPLETE` transition.

### Cost and review boundary

Use one fresh design verifier, with one consolidated correction and one focused
recheck maximum. This successor contains one new guard and one new isolated witness;
it does not reopen accepted or rejected predecessor scope. Record observed run/review
counts without inventing unavailable model, token, or time measurements.

<!-- WP83-DESIGN-PAYLOAD-END -->

### WP-83 independent design verdict

- Fresh verifier verdict: `DESIGN_VERIFIED`; no P0/P1 findings.
- Reproduced payload: 5,645 bytes, SHA-256
  `d7fe1b62e8afb2d8ceab3a5dc14a63574520767ca4fd39f2ab57dc0a272d51a4`;
  audit/artifact hashes and both 37-file clock-mode traces matched with zero errors.
- Retained P2: build the production interval from the capture `(timestamp, sequence)`
  identity, because timestamp-only selection could reject an earlier same-tick sample.
- Mechanical status-only closeout changes only `DRAFT_UNVERIFIED` to
  `DESIGN_VERIFIED`; implementation is now authorized within the frozen eight-file
  owned boundary.

<!-- WP84-DESIGN-PAYLOAD-BEGIN -->

## WP-84 — flexible dynamic-replanning successor correction

### Authorization, predecessor boundary, and minimum value

The operator authorized a fresh successor to the exhausted WP-67 through WP-70 review
unit and authorized implementation only after this successor reaches
`DESIGN_VERIFIED`. WP-67 through WP-70 remain immutable
`REVIEW_BLOCKED / BLOCKED_WITH_FINDINGS`; this packet is not a third review pass and
does not claim that WP-76 through WP-83 implemented any of their behavior.

Originating operator objective and correction request on 2026-08-20:

> Configure more than two appearing obstacles; replace route Accuracy with a
> meaningful minimum drone-to-object clearance; show the planner-guaranteed minimum
> opening; reduce hesitation, hard braking, stale cutovers, route-side switching, and
> unnecessary fallback; and analyze and address failures observed in Runs 2–6. Create
> the next fresh successor packet, obtain a fresh `DESIGN_VERIFIED` verdict before
> production implementation, preserve the dirty worktree, use a different fresh
> implementation verifier, regenerate API artifacts, run backend/UI perturbations,
> freeze exact dirty-tree pre/post identities, and transition Runs 2–6 to Old only
> after an applied committed revision and before replacement retained evidence.

The successor must close the four predecessor P1 findings: independently computed
guard oracles; feasible sensed-world and actual certificate/receipt/commit/dispatch
witnesses; complete independently discovered production/test/generated boundaries;
and real source-child plus behavior-driving seeded world identity.

| Intent/value category | Frozen content |
| --- | --- |
| Minimum useful outcome | A route-free one-drone goal-seeking run accepts a configured three-object world, displays `Clearance` and the planner-guaranteed opening, performs moving certified replacements without routine fallback or side churn, and reaches goal capture and landing with complete truthful evidence. |
| Explicit behavior | Configure `1..4` appearing objects; default to three; expose `0.15..0.25 m` minimum drone-envelope-to-object clearance; show `Opening ≥ 0.66 m` at the default; cap unsafe requested speed; distinguish no-solution, budget, stale, preparation, commit, and dispatch failures. |
| Necessary prerequisites | Separate immutable world truth from motion policy; exact source-child hashes; feasible real-planner geometry; complete latency/safe-prefix/abort/receipt/commit/dispatch authority; independent guard vectors; generated API/UI transit; historical-run boundary and served restart. |
| Optional experiment | One four-object fixed-world stress run after the three-object minimum passes. It may remain a labeled stress limit but may not weaken or block the default three-object value. |
| Safe fallback | Preserve the hard `0.15 m` minimum, `0.30 m/s` dynamic speed cap, certified hold/abort behavior, zero dispatch without exact certificates/receipts, and current two-object source case until the verified successor is fully connected. |
| Non-goals | Physical flight, Live Isaac, learned vision/SLAM, damage/contact fidelity, multi-drone online replanning, continuous-space completeness, wider freshness/start tolerances, or requalification of unrelated WP-71 through WP-83 work. |

Canonical **Status:** `PLANNED`
**Independent verification:** `DRAFT_UNVERIFIED`

### Short successor retrospective and durable requirements

The WP-67 through WP-70 focused recheck is recorded in
`docs/project/retrospectives/REPEATED_PACKET_REVIEWS.md`. Its reusable failures were
already codified by `REQ-WFL-046` through `REQ-WFL-049`: complete numerical vectors,
independently discovered boundary closure, executable sensed-world/certificate
witnesses, and independently derived guard-universe closure. No new durable rule is
invented here. WP-84 applies those existing rules together and keeps the
case-specific geometry/identity findings inside this packet.

Applicable requirements are `REQ-MIS-002`, `003`, `006`, `009`; `REQ-MOT-001`,
`011` through `017`; `REQ-PLN-003`, `004`, `009` through `013`; `REQ-GEO-002`,
`003`, `007`, `009`; `REQ-RPL-001` through `013`; `REQ-EVI-003` through `007`,
`011`, `013`; `REQ-UI-002`; and `REQ-WFL-001`, `002`, `005` through `012`, `014`
through `027`, `029`, `032` through `040`, and `042` through `053`.

### Frozen pre-design identities and executable audit

| Field | Frozen identity |
| --- | --- |
| Base commit | `40cd9947f87eb9bf2719d72e7c72ea867eab9977` |
| Dirty-tree rule | Base commit is provenance only; every scoped existing path uses the exact byte preimage in the audit artifact. No unrelated edit may be reset, reverted, overwritten, or attributed to WP-84. |
| `ACTIVE.md` preimage before WP-84 | `afc691b4c562da3e7acdd27b3d767c87a1d8024a5d86b2d2a1269c642d09f790` |
| Successor retrospective postimage | `6a0ce39707fa63a415d49699c72e3bc450280745f0805816c3b7f7366b93ba8d` |
| Audit program | `scripts/audit_wp84_design.py`, SHA-256 `60dd7295f843ca21e769a829ebff20575eb2bbbb186d3f4ce94dda3008459d41` |
| Audit artifact | `missions/campaigns/sim/qualification/wp84-design-audit-v1.json`, SHA-256 `3e5720bbca22c1c4a888a9fee9638e92f1a7c16a8d5b44238de833366fe6633c` |
| Real source case | `1d.online_obstacle_replan.dynamic_nominal`, SHA-256 `24790c25d4bba4716ea63f4424335f5c7039d1bc6d3d8e9157adfac9171e713d` |
| Frozen predecessors | WP-67–70 initial `f90a8af102f675df870729b00fd8f4210f7c0ce0b5f734603bc4a32568b67f42`; R2 `3cfdb3ae05bb3f2f45e125a835df92fd677d23bf06005ff75a9f4d7bac881840` |

Reproduce before review with:

```bash
.venv/bin/python scripts/audit_wp84_design.py \
  missions/campaigns/sim/qualification/wp84-design-audit-v1.json
```

The audit passes 13 checks. It derives 14 guard conjuncts from the frozen operator
terms, durable requirement IDs, and real production model fields; computes one whole
passing vector and one isolated failure per conjunct; exercises the real corridor
planner for six event stages at both admitted clearance extremes; binds the real
source-case hash; proves fixed/same-seed identity across run IDs and geometry/timing
change across stress seeds; executes the current production service transit through
four safe-prefix certificates, four real Supervisor receipts, four atomic commits,
and four dispatches with zero fallback; executes accepted and missing/tampered
certificate/receipt commit gates with respectively one and zero eligible dispatches;
and reconciles 70 production, API/runtime, script, test, UI, and generated paths from
runtime-module, symbol, explicit public/test, owner, and real generator sources.

The current transit's outer run/review/evaluation remains `FAILED` despite completing
all four replacement transactions. This is retained as the pre-fix evaluator witness,
not presented as qualification: route-free dynamic evidence is still judged by the
old route Accuracy/path-tube and stop semantics.

### Corrected public preparation and identity contracts

1. **Sibling policy and world requests.** The API request carries sibling components:
   `MotionPreparationRequest` owns `speed_m_s`, `minimum_clearance_m`, and
   `smoothness`; `DynamicWorldPreparationRequest` owns exact integer
   `obstacle_count=1..4`, `variation_mode=FIXED|SEEDED_STRESS`, and explicit bounded
   integer `variation_seed`. These fields are legal only for the one-drone
   `START_GOAL_CURRENT_WORLD` family. Dynamic goal seeking rejects Accuracy/path-tube
   input; static route/checkpoint cases retain Accuracy unchanged.
2. **Clearance and opening truth.** `minimum_clearance_m=0.15..0.25` in exact `0.01 m`
   increments means nominal vehicle-envelope surface to solid after the separately
   retained `0.05 m` localization/prediction uncertainty. It only tightens case
   safety. Physical protected opening is
   `2 × (0.055 vehicle radius + 0.05 uncertainty + clearance + 0.05 spline/search reserve)`.
   The guarantee for arbitrary `0.05 m` lattice phase adds one cell. At default
   clearance the physical value is `0.61 m` and the displayed primary value is
   `Opening ≥ 0.66 m`; at `0.25 m` they are `0.81 m` and `0.86 m`. The guarantee is
   discrete-planner feasibility, not continuous-space completeness.
3. **Immutable resolved world.** One resolver runs before preview, download, schedule,
   or Play. It binds the real source case ID/hash and emits separate
   `dynamic_world_definition_sha256`, `dynamic_event_set_sha256`, and
   `resolved_dynamic_world_sha256`. It derives one hidden resolved child ID
   `<source-case-id>.world-<first-12-world-hash>` and case hash from the real parent
   hash plus exact geometry/events. The child snapshot is retained in the resolved
   package, locked inputs, execution request, manifest, bundle, evaluation, replay,
   and download, but is not registered as a second visible catalog item.
4. **Truth is separate from motion.** Obstacle count, seed, geometry, timing, or event
   truth changes the resolved world and child-case hash. Clearance, speed, smoothness,
   or later run ID changes only the policy/package/run identity and never silently
   rewrites immutable world truth. The planning submission and execution profile are
   explicitly rebound to the compatible resolved child through an exact source
   authority record; no permissive registry fallback is allowed.
5. **Repeat identity.** `FIXED` defaults to seed `42`; identical source case/count/mode/
   seed produces byte-identical event/world/child identities across run IDs.
   `SEEDED_STRESS` exposes its seed and applies bounded deterministic offsets to solid
   X/Y geometry and trigger/effective timing. Equal stress seeds repeat exactly;
   different seeds change those behavior-driving inputs and are never pooled as fixed
   repeats.

### Feasible sensed-world and authority contract

For count `N`, materialize add/move obstacle 1, adds `2..N`, then remove obstacle 1;
renumber sequences/generations `1..N+2`. Counts `1..4` therefore create `3..6` events
and maximum simultaneous populations `1..4`. Every event has a `3.0 s` observation
lead; perception latency remains `0.12 s`, expiry `0.50 s`, normal freshness
`<=0.25 s`, complete response envelope `0.74 s`, planning budget `<=2.0 s`, and
trajectory verification step `0.02 s`. Future solids remain absent from initial
planner truth.

The fixed geometry is:

| Solid/event | Bounds `(xmin,ymin,zmin)..(xmax,ymax,zmax)` m | Trigger / effective source s |
| --- | --- | --- |
| `sensed-rock-1` add | `(-0.15,-0.20,0.10)..(0.20,0.20,0.70)` | `2.0 / 5.0` |
| `sensed-rock-1` move | `(0.20,-0.25,0.10)..(0.50,0.15,0.70)` | `5.5 / 8.5` |
| `sensed-wall-2` add | `(0.70,0.75,0.00)..(0.85,1.05,0.80)` | `7.5 / 10.5` |
| `sensed-wall-3` add | `(0.35,0.85,0.00)..(0.50,1.10,0.80)` | `9.25 / 12.25` |
| `sensed-wall-4` add | `(1.00,0.85,0.00)..(1.15,1.10,0.80)` | `11.0 / 14.0` |
| `sensed-rock-1` remove | exact solid identity | `12.5 / 15.5` |

Unlike R2's lower-side walls, the additional upper-side solids preserve a lower outer
passage across the complete `0.15..0.25 m` clearance range. The real 8,192-state
planner selects all 12 event-stage/clearance witnesses with at most `3,846`
expansions. Budget exhaustion remains `INCONCLUSIVE_BUDGET`, never geometrical
infeasibility. The implementation must execute this same geometry through preview,
scenario/perception truth, planning, continuous feasibility certification, runtime
physics, and retained evaluation rather than substitute a component-only fixture.

For every nominal event, the execution head must obtain a current observation, an
independent safe-prefix certificate and abort-route certificate, a selected corridor
with independent feasibility/moving-cutover certificates, one exact Supervisor
preparation receipt, one accepted atomic epoch commit, and one post-commit replacement
dispatch. Missing/tampered safe-prefix or abort authority, feasibility/cutover
certificate, proposal/receipt identity, or receipt cardinality causes zero replacement
commits and zero replacement dispatches. Late trusted state may execute a certified
stationary prefix; otherwise only a certified abort route may command
`ABORT_AND_LAND`. Unqualified evidence never becomes a normal replacement.

### Motion continuity, freshness, and truthful evaluation

1. Dynamic preparation safety-caps a request above `0.30 m/s` before Play and retains
   requested/resolved values plus the reaction envelope as binding reason. Runtime
   urgency still grows from signed clearance, observed speed, uncertainty, jerk-
   limited stopping/turn authority, and the complete latency envelope.
2. Corridor search seeds its initial heading from fresh observed horizontal velocity
   above the `0.02 m/s` stop threshold. Selection is lexicographic over path length,
   `0.10 m/rad × integrated absolute heading change`, protected clearance, and
   canonical state. Source enumeration/object order never decides the side.
3. Immediately before preparation, capture a final source-time observation and
   rebase/recertify the exact trajectory. Normal limits remain age `<=0.25 s` and
   start error `<=0.10 m`. At most one complete fresh search follows an unusable stale
   corridor, and initial/retry/rebase/cumulative timing is retained even on failure.
4. `OBSTACLE_REMOVED` and `PASSAGE_OPENED` reoptimize from fresh committed state and
   cannot trigger immediate fallback solely because another retained solid is near.
   A beneficial direct continuation is collinear and cannot manufacture a side
   reversal.
5. Dynamic route Accuracy/path-tube and `PATH_ADHERENCE` objective are not applicable.
   Evaluation instead joins every sample to its accepted initial/replacement authority
   epoch and independently checks temporal trajectory tracking, clearance, dynamics,
   continuity, goal capture, and landing.
6. An unintended stop is speed `<=0.02 m/s` continuously for `>=0.20 s` strictly
   inside one moving accepted epoch. Takeoff/stabilization, observation, preparation,
   acknowledgement, cutover boundary, final capture, landing, and completed authority
   do not each create a stop. Root cause comes from normalized terminal codes and exact
   execution-head dispositions, not configured prose.

### Independent guard oracle

The authoritative guard universe is derived from the originating operator terms,
named durable requirement rows, and real production contracts in the audit artifact.
The complete default three-object repeat uses these independently computed conjuncts:

| Conjunct | Passing boundary | Isolated failure |
| --- | --- | --- |
| Speed lower / upper / coverage | `0.24..0.34 m/s` around target `0.29`, accepted moving-epoch coverage `>=0.95` | `0.239`, `0.341`, and `0.949` independently |
| Acceleration | raw route peak `<=1.0 m/s²` | `1.001 m/s²` |
| Jerk | raw route peak `<=8.0 m/s³` | `8.001 m/s³` |
| Initial heading change | `<=π/2` from observed pre-cutover velocity to first replacement tangent | `π/2 + 0.001` |
| Side reversal | zero reversals between accepted detours around the same retained blocking set | one sign reversal |
| Clearance | nominal envelope-to-solid surface margin `>=0.15 m` or requested tighter value | `0.149 m` at default |
| Collision | exactly zero | one configured contact |
| Freshness | final observation age `<=0.25 s` | `0.251 s` |
| Start error | rebased replacement start `<=0.10 m` | `0.101 m` |
| Budget | cumulative search `<=2.0 s` | `2.001 s` |
| Goal capture | captured inside the immutable terminal region | missing capture |
| Landing | admitted target/contact/disarm evidence complete | missing landing completion |

Every failure vector changes only its named input and leaves all other conjuncts
passing. Raw acceleration/jerk/contact extrema may not be hidden by percentile or
resampling. Corridor side is the signed cross product against the immutable start-goal
chord, ignores direct/collinear paths, and compares only successive accepted detours
around the same blocking set.

### Operator surface and retained explanation

In the Campaign workspace, dynamic Motion uses `Balance`, `Speed`, `Clearance`, and
`Smoothness`; static mission Motion keeps `Accuracy`. A compact Environment row below
Motion provides `Obstacles` and `Variation`, with the explicit seed visible only for
seeded stress. The primary calculated readout is `Opening ≥ <planner guarantee>` with
units and concise meaning; physical opening and inflation components remain in closed
technical detail. Requested and resolved speed/clearance values and binding caps remain
truthful. This durable case-specific pattern updates `design.md` and
`docs/project/DESIGN.md` and follows `[SIM-01..03]`, `[TXT-01..02]`, `[LAY-01..02]`,
`[CMP-01..02]`, `[STA-01]`, `[RSP-01]`, `[A11Y-01]`, `[TRU-01]`, and `[VAL-01]`.

Each event record retains resolved source/child/world/package identities, observation
source/receive/effective clocks, state/speed/age, response witness, search disposition/
expansions/wall/cumulative time, inflation and opening components, selected path and
side/heading costs, feasibility/cutover/safe-prefix/abort certificates, final rebase,
Supervisor receipt, commit epoch, dispatch acknowledgement, post-cutover observation,
and exact failure code. Manifest and download retain exact dirty production source
hashes. API OpenAPI and TypeScript outputs are regenerated through the real
`generate:api` command.

### Complete affected-boundary and implementation contract

The audit's 70-path manifest is authoritative for implementation reconciliation. It
unions runtime-loaded modules, exact symbol occurrences, explicit public/test owners,
implementation owners, and generated outputs; every path is classified `MODIFY`,
`PRESERVE`, `NEW`, or `GENERATED` with an exact preimage or absent/new state. It
explicitly includes previously omitted `api/runtime.py`, `export_openapi.py`,
`mark_campaign_runs_old.py`, API/dynamic/evaluation/UI tests, `ui/openapi.json`, and
`api.generated.ts`. The implementation manifest must compare the actual postimage
against this independently discovered set, explain every added/changed/preserved/
generated/deleted path, and fail if a newly traversed owner or output is absent.

The intended change owns request/package/world resolution, planning/corridor,
replanning/execution head, simulator truth, evaluator/analyzer/storage, API/runtime,
generated contracts, Campaign UI, design/system maps, and focused tests. New proposed
owners are `campaign/dynamic_obstacles.py`, `test_dynamic_preparation.py`, and
`test_dynamic_guard_oracle.py`. Paths classified `PRESERVE` are mandatory regression
boundaries, not permission to edit them. Any substantive implementation edit outside
the verified manifest invalidates the design and requires operator-authorized scope,
not silent expansion.

### Claim and exit-evidence matrix

| Claim | Real trigger / production transit | State or command effect | Independent oracle / counterexample | Boundary |
| --- | --- | --- | --- | --- |
| Preparation and identity are truthful | Campaign UI/request → API model → service resolver → package/lock/download/run | Clearance changes policy/package only; count/seed changes exact hidden world/child; dynamic Accuracy rejects | Recompute real parent/world/event/child/package hashes; same seed across run IDs equal; seeds 43/44 change geometry+timing; static dynamic-field and dynamic Accuracy inputs reject | `PRODUCTION_ENTRY / NO_RUNTIME / NOT_APPLICABLE` |
| Opening and population are feasible | Resolved child → preview/planner → schedule/scenario/perception | `1..4` objects produce `3..6` events; displayed lattice guarantee matches planner | Exact `0.61/0.66` and `0.81/0.86` arithmetic; all 12 stage/clearance searches select below 8,192; R2 lower-wall geometry reproduces exhaustion | `INTEGRATION / FAST_SIM / ACCELERATED` |
| Nominal events remain moving replans | Perception source → execution head → safe-prefix/abort → plan/rebase → Supervisor receipt → atomic commit → dispatch | Each event replaces one authority epoch without routine fallback and reaches goal/landing | Actual retained receipts/certificates/commands; missing/tampered cert or receipt yields zero commit/dispatch; late/close event uses only certified fallback | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED + OBSERVED_REALTIME` |
| Hesitation and side churn fail independently | Accepted epoch telemetry + trajectory/certificate records → evaluator/analyzer/API | Exact 14-conjunct vector and named root causes; dynamic path tube N/A | Whole passing vector plus one isolated failure each; mirrored heading, reordered obstacles, beneficial removal, raw-extrema counterexamples | `INTEGRATION / FAST_SIM / ACCELERATED` |
| Served surface is usable and truthful | Current API/release/assets → Campaign workspace | Dynamic controls swap Accuracy→Clearance, show Opening/Environment, bind requests; static Accuracy unchanged | Desktop/narrow, keyboard/focus, long values, loading/disabled/error, seed visibility, request capture, no overflow/console error | `PRODUCTION_ENTRY / NO_RUNTIME / NOT_APPLICABLE` |
| Historical boundary precedes retained replacement evidence | No-active-run check → committed revision → mark-old script → API restart/state reload | Runs 2–6 remain inspectable Old and ineligible; later runs remain current | Exact revision/actor/reason/count/run IDs; active-run rejection and idempotence; persisted old/current state after restart | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |

Implementation evidence must include:

1. Failure-first focused regressions where practical, then request/hash/world identity,
   `1..4` populations, fixed/stress repeat identity, speed cap, opening/lattice,
   feasible three/four-object planner stages, fresh rebase/retry, beneficial events,
   certificate/receipt/commit/dispatch tamper cases, exact guard vectors, path-tube N/A,
   stop/root-cause semantics, goal capture/landing, API persistence/export, and
   generated-contract tests.
2. Ruff, targeted Mypy, documentation routing/map checks, focused backend tests,
   ESLint, TypeScript, Vitest, and a production UI build. Unrelated dirty-tree failures
   are retained with exact commands and attribution; expectations are not weakened.
3. Three isolated default `obstacle_count=3`, `FIXED`, seed `42`, requested
   `0.29 m/s`, accelerated repeats before operator evidence. World/event/child identity
   must match across run IDs; every repeat individually passes all 14 guards, every
   event certificate/receipt/commit/dispatch join, goal capture, landing, and zero
   fallback/collision.
4. One distinct seeded-stress child and one fixed four-object run. Both retain exact
   geometry/timing identity and execute all configured events. Four objects may remain
   a P2 stress limit only after default three-object success and truthful UI labeling.
5. After implementation verification and an applied committed revision identity—but
   before any new retained affected campaign run—confirm no active mission/preparation,
   execute `scripts/mark_campaign_runs_old.py` for the exact affected source and hidden
   child scope with actor and reason
   `WP-84 dynamic-world/preparation/replanning semantics replaced`, retain prior/new
   counts and run IDs, restart the campaign-state API, and verify persisted state.
   The current broad `operator-review-1d-2026-08-20:40cd9947f87e` Old marker is not a
   substitute for the WP-84 applied revision boundary; idempotent reconciliation must
   preserve existing Old records and explicitly report whether Runs 2–6 required zero
   additional changes.
6. Before served qualification, verify no active unsafe operation, regenerate OpenAPI
   and TypeScript, rebuild/restart affected API/UI/worker/state owners, bind exact
   served release/API/assets, and inspect the real desktop and narrow interface with
   keyboard and failure states under `REQ-WFL-038` and `053`.

Self-authored evidence establishes at most `IMPLEMENTED_UNVERIFIED`. After the author
loop, freeze exact base commit, every scoped preimage/postimage, changed/new/deleted
path or delimited section, generated artifacts, commands/results, and implementation
payload hash. A different fresh `work_packet_verifier` must trace the real production
path and independently perturb certificates, receipts, identity, geometry, guards,
and served state before `IMPLEMENTATION_VERIFIED`. Only mechanical verification/status
records may follow a passing verdict.

### Model, cost, and stop boundary

- Author/design route: frontier/high reasoning is justified by the inherited
  cross-layer safety/authority, geometry, identity, dirty-tree, generated-contract,
  and served-release dependencies. Exact token/time telemetry is unavailable; proxies
  are one fresh packet, one design review plus at most one focused recheck, one
  implementation review plus at most one focused recheck, 70 frozen boundary paths,
  14 isolated guard conjuncts, 12 planner geometry witnesses, and declared runtime
  runs.
- Once `DESIGN_VERIFIED`, implementation is concrete and follows `REQ-WFL-050`: edit
  the smallest complete production slices, run focused checks once, and avoid another
  open-ended design cycle.
- One consolidated design correction and same-verifier recheck are the maximum. A
  remaining `MUST_FIX_NOW` P0/P1 blocks implementation. P2 polish or optional
  four-object limitations are retained/disabled without reopening unaffected default
  value. Any `SCOPE_CHALLENGE` stops for operator direction.

<!-- WP84-DESIGN-PAYLOAD-END -->

### WP-84 design verification handoff

- Frozen design payload: inclusive bytes from `WP84-DESIGN-PAYLOAD-BEGIN` through
  `WP84-DESIGN-PAYLOAD-END`, `25,638` bytes, SHA-256
  `c993df7c80b18a5fe5b4e3fe950d94ce736d1fb6c851dbb9b69cf2f2cc17d4a0`.
- Reproduced author audit: all 13 checks passed; audit-program SHA-256
  `60dd7295f843ca21e769a829ebff20575eb2bbbb186d3f4ce94dda3008459d41` and
  artifact SHA-256
  `3e5720bbca22c1c4a888a9fee9638e92f1a7c16a8d5b44238de833366fe6633c`.
- Gate state remains `DRAFT_UNVERIFIED`. No production implementation is authorized
  until a fresh project-scoped verifier records `DESIGN_VERIFIED` for this exact
  payload. One consolidated correction and one focused same-verifier recheck are the
  maximum permitted design-review loop.

### WP-84 initial independent design verdict

- Fresh project-scoped verifier reproduced the 25,638-byte payload and audit
  byte-for-byte, accepted the opening arithmetic, parent identity, and 12 bounded
  searches, and returned `BLOCKED_WITH_FINDINGS` with no P0 and five P1
  `MUST_FIX_NOW` clusters.
- The P1 clusters were: non-independent/incoherent guard vectors; no coherent
  proposed-world production transit or real negative dispatch proof; incomplete
  boundary discovery/preimage reconstruction; metadata-only seed collisions; and
  incomplete Runs 2--6 watchdog/Run-5 gates plus circular Old/review/run ordering.
- The following R1 overlay is the one permitted consolidated correction. It does not
  edit or erase the initially reviewed bytes. The same verifier may perform one
  focused recheck; no further automatic design pass is permitted.

<!-- WP84-DESIGN-R1-PAYLOAD-BEGIN -->

## WP-84 design R1 — consolidated correction overlay

This overlay supersedes the initial payload where the two conflict. Everything not
changed here remains frozen by initial payload SHA-256
`c993df7c80b18a5fe5b4e3fe950d94ce736d1fb6c851dbb9b69cf2f2cc17d4a0`.
Canonical **Status:** `PLANNED`; **Independent verification:** `DRAFT_UNVERIFIED`.
Production implementation remains unauthorized pending the focused recheck.

### R1 executable identities and limitations

| Artifact | Frozen R1 identity |
| --- | --- |
| Audit program | `scripts/audit_wp84_design.py`, SHA-256 `38b61ff58f203cf34953a98ef5dbe72eb639ac93206ed35902baf34c289e555b` |
| Audit artifact | `missions/campaigns/sim/qualification/wp84-design-audit-v1.json`, SHA-256 `8140602daeb08845dc242f5e3be94620e37b3fcbedab83c87e8d31e05bfbabab` |
| Base/provenance | `40cd9947f87eb9bf2719d72e7c72ea867eab9977`; dirty-tree preimages remain path-specific |
| Retrospective | SHA-256 `6a0ce39707fa63a415d49699c72e3bc450280745f0805816c3b7f7366b93ba8d`, implementation-preserved |

The earlier whole-file `ACTIVE.md` hash is historical provenance only and is not used
as a reconstructable implementation preimage. R1 instead freezes the immutable
initial payload and this exact delimited overlay independently. After
`DESIGN_VERIFIED`, the implementation preimage manifest captures every existing
boundary byte, while ledger identity uses only these delimited payloads and later
mechanical verdict/status sections. The audit artifact and ledger are self-referential
freeze outputs, so their identities are owned by this external handoff rather than
embedded recursively inside the JSON.

The R1 audit passes 15 checks and records 29 required guards, three explicit
not-applicable classifications, 29 coherent isolated failures, 12 planner snapshots,
one normal-entry sequential three-object run, a passed abort/landing certificate, the
complete 35-seed stress domain, the Runs 2--6 table, and 76 classified boundaries.

### Corrected independent guard universe and coherent vectors

The production motion-guard membership is parsed from the AST literal check IDs in
`_motion_guard_verdict` and reconciled with `MotionQualityVector` and
`MotionQualityContract`; online-transition membership is parsed from the named
`REQ-RPL-003`, `005`, `011`, `012`, and `REQ-EVI-005` rows. The originating speed
request splits the existing production speed-compliance guard into p05 lower, p96
upper, and in-band coverage conjuncts. The audit does not compare two adjacent
hand-written guard registries.

The 29 required gates are: p05/p96/coverage speed; acceleration; jerk; speed ripple;
angular activity; motor headroom, spread, saturation, sign agreement, and normalized
differential error; energy; temporal tracking RMS; clearance; collision; continuous
knot speed; unintended stop; terminal secondary peak and reversal; Supervisor safety;
initial replacement heading; accepted-detour side reversal; observation freshness;
replacement start error; cumulative planning budget; normal-event fallback count;
goal capture; and complete landing. Dynamic path tube is explicitly
`NOT_APPLICABLE_ROUTE_FREE_DYNAMIC_GOAL_SEEKING`; checkpoint hold is not applicable to
continuous fly-through; duration has no case maximum. None is silently dropped.

Each speed fixture contains 100 time-ordered moving-epoch samples. The passing fixture
contains 100 samples at `0.29 m/s`. The isolated lower failure has five samples at
`0.239` and 95 at `0.29`, so p05 fails while coverage remains exactly `0.95`; the
upper failure is symmetric with five at `0.341`; the isolated coverage failure has
three low, 94 in-band, and three high samples, so coverage is `0.94` while p05/p96
remain in band. All other isolated vectors change one real signal only.

Initial heading is computed from the final fresh observation's horizontal velocity
to the first non-zero replacement tangent. Side reversal is computed from the signed
cross product against the immutable start-goal chord for successive accepted detours
sharing the same blocking-set hash; direct/collinear paths are excluded. Freshness is
`decision_source_s - final_observation_source_s`. Budget is the sum of initial,
optional one retry, and rebase search latencies retained in the execution-head record.
Landing requires captured outcome plus contact source identity, disarm time,
post-contact settling, and motor cut—not contact alone. Run-5 raw/p95 non-regression
gates remain independently visible rather than hidden by the new dynamic metrics.

Implementation must use the evaluator/analyzer production calculation and a separate
test oracle over coherent telemetry/event/authority fixtures. It must perturb sample
order, obstacle order, route-point order, blocking-set identity, clock age, and raw
extrema and prove the intended single or joined failures. The AST-derived set and
the independently computed results must be exact-equal; additions cannot pass merely
because an authored subset remains internally consistent.

### Corrected world identity domain

`FIXED` has no behavior-driving seed. The API may display the conventional default
`42`, but the resolver canonicalizes it to `variation_seed=null` before geometry,
event, world, child-case, package, preview, execution, and download identity. Fixed
requests with supplied seeds 42 and 43 therefore resolve to identical behavior and
world/child identities; alternatively the public validator may reject the supplied
seed. It may not hash irrelevant seed metadata.

`SEEDED_STRESS` admits exactly integer seeds `0..34`. The deterministic X residue
modulo seven and Y/timing residue modulo five form an injective behavior tuple over
that full Chinese-remainder domain. R1 exhaustively resolves all 35 seeds and proves
35 distinct geometry/event behavior hashes. Same seed across run IDs is identical;
different admitted seeds change behavior before identity is computed. Values outside
`0..34`, booleans, floats, and strings reject. Clearance, speed, smoothness, and run
ID remain excluded from immutable world truth.

### Corrected coherent sensed-world and dispatch evidence

R1 registers a temporary `replan.wp84-three-object-design-prototype` child from the
real parent hash and executes the normal entry:

`CampaignService.run_active → FastSimCampaignExecutor → CampaignExecutionHead →`
`Supervisor preparation → atomic commit → execute_replanned_trajectory`.

No off-loop planning or analysis method is substituted. The five sequential events
(add/move object 1, add objects 2 and 3, remove object 1) use the corrected upper-side
geometry, reach maximum simultaneous population three, and derive each next state
from the preceding accepted replacement epoch. The trace retains five observations,
five safe-prefix certificates, five Supervisor receipts, five commits, five actual
dispatches, five distinct resulting world/trajectory identities, and zero fallback.
The outer bundle still fails under the pre-fix evaluator and has no final capture
record; this is an explicit implementation target and is not qualification evidence.

Four-object feasibility remains independently bounded by the real planner at every
stage and both clearance extremes. Implementation must additionally run one coherent
four-object normal entry after the three-object default passes; a failure remains a
labeled optional stress limitation, never a claim that the default failed.

R1 also constructs a passed abort-route certificate with protected clearance
`0.155 m` and a bound safe-prefix certificate whose actual command is
`ABORT_AND_LAND`. The pre-fix commit gate proves missing/tampered safe-prefix and
Supervisor receipt inputs yield zero commit-eligible replacements, but R1 no longer
mislabels those records as actual device dispatches. The implementation's
failure-first tests must drive missing/tampered safe-prefix, abort-route, feasibility,
moving-cutover, proposal, and receipt identities through `CampaignExecutionHead` with
a command-boundary spy. Every negative must produce a normalized rejection and
exactly zero `execute_replanned_trajectory` calls; incidental `AttributeError` is a
failure. The accepted control must produce exactly one real call. Those tests are
required before self-authored `IMPLEMENTED_UNVERIFIED` and will be independently
perturbed by the implementation verifier.

### Corrected affected-boundary discovery

The 76-path R1 manifest is the exact union of: runtime-loaded repository modules;
full-repository semantic-symbol occurrences; explicit API/runtime/persistence/export/
test owners; intended production owners; generator inputs and outputs; source/config
inputs; and frozen design files. The closure check compares the classified manifest
to that union with exact set equality, rejects empty discovery provenance, excludes
`.venv`, and reports `40 MODIFY`, `3 NEW`, `2 GENERATED`, and `31 PRESERVE`.

Newly explicit preserved inputs include `config/app.yaml`,
`config/worlds/one_drone.yaml`, the dynamic source-case YAML, `ui/package.json`, the
audit program/artifact, the WP-84 ledger payloads, and the retrospective. Newly
explicit production transit owners include the Supervisor, fleet coordinator, and
simulated vehicle command boundary. Generated OpenAPI and TypeScript remain derived
from the real package command. Frozen design material is implementation-preserved;
mechanical verdict/status appendices do not mutate the reviewed payload.

At implementation freeze, rediscover the union from the postimage and require exact
set equality with the verified classifications. Capture whole-byte pre/post hashes
for ordinary files, absent/new identities for additions, generator input/output
hashes, and delimited hashes for the two WP-84 design payloads. Any newly traversed
owner or output is a scope change requiring operator direction.

### Runs 2--6 translation and non-circular execution order

| Run | Retained status | Stops | Frozen repair gates |
| --- | --- | ---: | --- |
| 2 / `campaign-run-3ff32ba7a8b626401142` | succeeded | 12 | Dynamic path tube N/A; source-epoch stop semantics; speed band remains truthful. |
| 3 / `campaign-run-bca84c9fe606b1633c03` | failed | 8 | Source schedule progressed while wall watchdog expired; dynamic evidence incomplete. |
| 4 / `campaign-run-c090c0065373b905b128` | failed | 6 | Same watchdog/source-clock defect and incomplete evidence. |
| 5 / `campaign-run-cd4e1c1dfb0638bd83fb` | failed | 2 | Same watchdog defect plus acceleration, ripple, angular activity, motor spread, and tracking regressions. |
| 6 / `campaign-run-9f9e042f474753fa29b0` | failed | 6 | Same watchdog/source-clock defect and incomplete evidence. |

The watchdog follows authoritative source-clock progress in accelerated execution;
wall delay alone cannot expire a progressing source schedule. A separate injected
counterexample freezes source progress and ages authoritative telemetry beyond
`0.50 s`, which must fail with normalized `AUTHORITATIVE_TELEMETRY_LOST`. Tests cover
both, plus paused execution and genuine executor deadlock. The stop oracle counts only
`<=0.02 m/s` continuously for `>=0.20 s` strictly inside one moving accepted epoch;
the named preparation/cutover/terminal exclusions are derived from authority epochs,
not prose labels.

The required order is now two-phase and non-circular:

1. Implement only after `DESIGN_VERIFIED`; run failure-first tests, focused backend/UI
   checks, generated-contract checks, and isolated temporary campaign runs in a fresh
   temporary state/evidence directory. Include three accelerated fixed repeats, one
   accelerated stress run, one four-object stress run, and one realtime smoke. These
   are verifier inputs, not retained operator campaign evidence.
2. Freeze exact pre/post identities and obtain a different fresh implementation
   verifier. One fix/recheck maximum; unresolved P0/P1 blocks deployment.
3. After `IMPLEMENTATION_VERIFIED`, commit exactly the reviewed production bytes and
   record the commit/revision identity. Confirm no active mission, preparation,
   queued run, or dispatch.
4. Do not rewrite existing Old metadata. Runs 2--6 were prematurely marked Old by
   `operator-review-1d-2026-08-20:40cd9947f87e`; retain that immutable historical
   limitation. Append a separate WP-84 evidence-generation boundary record binding
   exact source/hidden-child scope, reviewed commit, actor, reason, the five run IDs,
   and prior marker. Enhance `mark_campaign_runs_old.py`/storage so this append-only
   boundary is recorded even when the selected runs are already Old; idempotent repeat
   produces the same boundary identity and no duplicate.
5. Restart/rebuild the affected API, worker/state owner, and UI; verify health, exact
   served release/API/assets, persisted Old state, new generation boundary, and no
   active unsafe state.
6. Only then collect retained operator evidence: three fixed accelerated repeats,
   one seeded stress, one fixed four-object stress, and one realtime run. Evaluate
   every run individually against all applicable gates; do not pool a failed repeat.

This sequence replaces the initial exit-evidence items 3--6. Retained evidence is
qualification after implementation verification and deployment boundary, not an
input used circularly to earn implementation verification.

<!-- WP84-DESIGN-R1-PAYLOAD-END -->

### WP-84 R1 focused-recheck handoff

- Frozen correction overlay: inclusive bytes from
  `WP84-DESIGN-R1-PAYLOAD-BEGIN` through `WP84-DESIGN-R1-PAYLOAD-END`, `13,381`
  bytes, SHA-256
  `1dc093e440d8e2e624e060d8fb37370f761ca99b4d68506bc7927e0076641c73`.
- Accepted base candidate for the focused recheck is the immutable initial payload
  SHA-256 `c993df7c80b18a5fe5b4e3fe950d94ce736d1fb6c851dbb9b69cf2f2cc17d4a0`
  plus this R1 overlay. Audit identities are frozen inside R1 and reproduce all 15
  checks.
- Gate state remains `DRAFT_UNVERIFIED`. This is the one permitted correction; the
  same verifier's focused recheck is the final automatic design pass.

### WP-84 final independent design verdict

- Canonical **Status:** `REVIEW_BLOCKED`.
- **Independent verification:** `BLOCKED_WITH_FINDINGS`.
- The same fresh verifier completed the one permitted focused recheck. No P0 was
  found. Two P1 `MUST_FIX_NOW` findings remain, so production implementation is not
  authorized and no third automatic WP-84 design pass may occur.
- Remaining P1: the negative audit still stops at the direct commit gate and treats
  an incidental missing-certificate `AttributeError` as zero-dispatch success. It
  does not yet drive the accepted control plus missing/tampered safe-prefix, abort,
  feasibility, cutover, proposal, and receipt cases through
  `CampaignExecutionHead` to an actual `execute_replanned_trajectory` command spy.
- Remaining P1: the audit-local stress resolver accepts `True`, `False`, and `1.0`
  because Python considers them members of `range(35)`. The frozen oracle therefore
  does not yet execute the specified exact-integer public boundary or retain boolean,
  float, string, and out-of-range rejection vectors.
- Retained P2: the normal-entry three-object witness reproducibly satisfies its 15
  semantic checks, but run-local decision/trajectory/world identities make the whole
  JSON byte hash non-reproducible. A successor should label it a single-run structural
  witness and compare stable fields, or deterministically normalize run-local fields.
- The verifier otherwise accepted the corrected 29-guard universe/coherent vectors,
  positive sequential three-object transit, planner feasibility, 76-path boundary
  manifest, Runs 2--6 translation, seed behavior domain, and non-circular historical/
  restart ordering.

<!-- WP85-DESIGN-PAYLOAD-BEGIN -->

## WP-85 — final flexible dynamic-replanning successor correction

### Authorization, value, and predecessor boundary

On 2026-08-21 the operator explicitly authorized continuing with WP-85 after WP-84
exhausted its design review and focused recheck. The operator also instructed that,
after the work is genuinely complete, the scoped changes be committed and pushed.
Unrelated dirty-tree changes remain operator-owned and may not be staged, reset,
reverted, overwritten, or attributed to WP-85.

WP-85 is a fresh review unit, not a third WP-84 pass. It adopts the immutable WP-84
initial payload and R1 overlay as its full baseline and supersedes only the two final
P1 findings plus the retained evidence-reproducibility P2. A fresh verifier must
review the complete composite rather than treating predecessor acceptance as an
automatic verdict.

| Intent/value category | Frozen WP-85 content |
| --- | --- |
| Minimum useful outcome | The WP-84 minimum remains unchanged: a route-free one-drone, three-object default shows Clearance and planner-guaranteed Opening, performs moving certified replacements without routine fallback or side churn, and reaches capture/landing with complete truthful evidence. |
| Required correction | Prove every named missing/tampered authority causes zero actual replacement command calls through `CampaignExecutionHead`; enforce an exact-integer `0..34` stress-seed domain; make the focused evidence byte-reproducible through a stable semantic projection. |
| Necessary inherited behavior | The verified candidate still includes the 29-guard oracle, feasible `0.15..0.25 m` geometry, `0.61/0.66 m` opening truth, world/policy separation, full request/API/UI/generated transit, source-clock watchdog fix, append-only Old boundary, restart, and retained qualification order specified by WP-84 R1. |
| Optional experiment | A fixed four-object stress run remains optional after the three-object default succeeds. |
| Safe fallback | Keep the current source case and `0.15 m` clearance/`0.30 m/s` cap; no replacement command may dispatch without all exact authorities. |
| Non-goals | No physical flight, multi-drone online replanning, learned perception, continuous-space completeness, or unrelated WP-71 through WP-83 requalification. |

Canonical **Status:** `PLANNED`
**Independent verification:** `DRAFT_UNVERIFIED`

### Frozen composite and author evidence

| Field | Identity |
| --- | --- |
| Base commit provenance | `40cd9947f87eb9bf2719d72e7c72ea867eab9977` |
| `ACTIVE.md` preimage before WP-85 | `faec8e6656860ad460017db3b0ba62e8a3c30ae202681601c2d5f2c293214e0e` |
| WP-84 initial payload | 25,638 bytes, SHA-256 `c993df7c80b18a5fe5b4e3fe950d94ce736d1fb6c851dbb9b69cf2f2cc17d4a0` |
| WP-84 R1 overlay | 13,381 bytes, SHA-256 `1dc093e440d8e2e624e060d8fb37370f761ca99b4d68506bc7927e0076641c73` |
| WP-85 audit program | `scripts/audit_wp85_design.py`, SHA-256 `23fe4eb07788443c41c0757620c487f105c4850d45147b09e7b8a6bdb6c060c0` |
| WP-85 audit artifact | `missions/campaigns/sim/qualification/wp85-design-audit-v1.json`, SHA-256 `e0ad016d537059d413830aca3c4e19c924acbba73f8ed8fb8cb84b0bd9cbe81e` |
| Durable feedback requirement | `REQ-WFL-054`; cost/scope file SHA-256 `790358ffc3d55f1fcae3d3cd669ebcb5bdf4d6d90921b56a01b121c8617c5a6f` |
| Requirements index/check | index `ab22a90174ccd19c0c13a496dd114d78eb460f1726fc9bd66cb9fcec774a5235`; checker `84b49da15fd95b1fc72f0f61aa54654d542031c16b0060f62b11244df941eadd` |
| Changelog/retrospective | `d24e0426bc93f5d00caf9245311a165fffd33085da5ad50e0e1dd6e2ffee1ebf`; `bdbc5d3c14002bf66579030fff09ffb66ab80a452fc56f4585c05060298c07a6` |

Reproduce with:

```bash
.venv/bin/python scripts/audit_wp85_design.py /tmp/wp85-design-replay.json
shasum -a 256 \
  missions/campaigns/sim/qualification/wp85-design-audit-v1.json \
  /tmp/wp85-design-replay.json
```

Both hashes must equal
`e0ad016d537059d413830aca3c4e19c924acbba73f8ed8fb8cb84b0bd9cbe81e`.
The audit passes seven checks. `scripts/check_requirement_catalog.py` independently
reports 148 unique definitions.

### Exact public seed contract and identity oracle

`DynamicWorldPreparationRequest` uses strict validation. `variation_mode=FIXED`
rejects a supplied public seed or canonicalizes the UI-only default out before
identity. `variation_mode=SEEDED_STRESS` requires `type(seed) is int` and
`0 <= seed <= 34`. Because Python booleans are integer subclasses and JSON clients
may coerce numeric types, validation explicitly rejects `false`, `true`, `1.0`,
`1.5`, `"1"`, `null`, `-1`, and `35`; it accepts exact integers `0`, `1`, and `34`.
The API request, resolver, package lock, generated OpenAPI/TypeScript types, UI request
capture, and replay/download round trip the same exact type/domain result.

Only the validated integer enters seeded geometry/timing. The WP-84 exhaustive
behavior-injectivity proof over all 35 values remains inherited. Tests independently
recompute geometry/event behavior identity for all admitted seeds, confirm fixed mode
has no seed identity, confirm the same seed is identical across run IDs, and reject
all type/range aliases before catalog child, package, preview, or run mutation.

### Actual execution-head command-boundary oracle

The WP-85 audit drives thirteen cases through the real
`CampaignExecutionHead._orchestrate` production sequence. It uses real planning,
changed-world proposal construction, moving-cutover rebase boundary, safe-prefix and
abort monitor, Supervisor-shaped preparation receipt, atomic commit, and the actual
context method named `execute_replanned_trajectory`. A command spy is attached only
at that final device-command boundary.

The accepted control makes exactly one replacement-command call and no fallback.
Each of the following twelve isolated cases makes exactly zero replacement-command
calls and never ends in incidental `AttributeError`:

- missing and tampered safe-prefix certificate;
- missing and tampered abort-route certificate;
- missing and tampered feasibility certificate;
- missing and tampered moving-cutover certificate;
- missing and tampered proposal identity;
- missing and tampered Supervisor preparation receipt.

Upstream missing/tampered planning or safety authority rejects with normalized
`ValueError`; cases that reach the existing certified fallback terminate with the
normalized domain `CrazySwarmError` and retain the fallback acknowledgement. The
production implementation must preserve this zero-command relation with explicit
error codes rather than rely on the audit's injection labels. It must additionally
assert zero atomic accepted epoch for pre-commit failures, discard any preparation
receipt, retain exact failure stage/identity, and ensure the accepted control still
has one receipt, one commit, and one dispatch.

Failure-first tests are mandatory in
`tests/campaign/test_one_drone_execution_head.py`,
`tests/campaign/test_dynamic_perception_replanning.py`, and
`tests/campaign/test_dynamic_replanning.py`. The implementation verifier must create
its own tamper values and observe the real command spy; replaying the author artifact
alone is insufficient.

### Deterministic evidence projection

The WP-84 normal-entry three-object run is explicitly reclassified as
`SINGLE_RUN_STRUCTURAL_PREIMAGE`. Fresh-state decision, trajectory, observation, and
replacement-world hashes remain valid within-run join identities but are not claimed
equal across independent runs. The WP-85 artifact serializes only stable semantic
fields: normal production entry, no off-loop substitution, maximum population three,
five ordered events, five observations/certificates/receipts/commits/dispatches, zero
fallback, and distinct within-run epoch identities. It excludes the actual run-local
hash values from the cross-run projection.

Two independent WP-85 audit executions are byte-identical. Implementation evidence
must retain both layers: complete unnormalized per-run artifacts for traceability and
a versioned normalized semantic projection whose exact bytes/hash are reproducible.
Changing event order, dropping a receipt/commit/dispatch, adding fallback, or claiming
cross-run equality for local transaction hashes fails the projection.

### Composite affected-boundary contract

WP-85 inherits the independently discovered 76-path WP-84 manifest and exact-unions
six focused successor owners, producing 82 classified paths. The delta is:

- `docs/project/REQUIREMENTS_CHANGELOG.md`;
- `docs/project/requirements/README.md`;
- `docs/project/requirements/workflow/COST_SCOPE_AND_HANDOFF.md`;
- `scripts/check_requirement_catalog.py`;
- `scripts/audit_wp85_design.py`;
- `missions/campaigns/sim/qualification/wp85-design-audit-v1.json`.

The audit program/artifact, requirements feedback, retrospective, and immutable WP-84
payloads are implementation-preserved. `ACTIVE.md` uses delimited payload and
mechanical verdict identities. All 82 paths must be rediscovered and reconciled at
implementation freeze; any additional traversed production owner requires an
operator-authorized scope revision. Whole-file hashes are used except for externally
frozen self-output/delimited ledger identities.

### Implementation and evidence sequence

After and only after `DESIGN_VERIFIED`, implement the complete composite production
transit from WP-84 initial + R1 + this correction. The inherited implementation and
exit matrix remains binding, with these refinements:

1. Add the strict sibling motion/world preparation contracts, real parent-bound hidden
   child resolver, feasible 1--4 object schedule, clearance/opening readout, dynamic
   evaluator/stop/watchdog semantics, deterministic corridor continuity, complete
   certificates/receipts/commit/dispatch evidence, API/runtime/storage/export, UI,
   generated artifacts, design/system maps, and focused tests.
2. Run failure-first strict-type and execution-head command-spy tests, then the
   inherited 29-guard, planner, identity, watchdog, evaluator, API, UI, generation,
   Ruff, Mypy, ESLint, TypeScript, Vitest, build, and requirement/map checks.
3. Use only isolated temporary campaign state/evidence for author and implementation-
   verifier runs. Freeze exact dirty-tree pre/post identities and obtain a different
   fresh implementation verifier, with at most one correction/recheck.
4. After `IMPLEMENTATION_VERIFIED`, create a local commit containing exactly the
   reviewed scoped production bytes. Do not stage unrelated dirty changes. This commit
   is the applied revision identity required by `REQ-WFL-052`; defer pushing until the
   final closeout so the operator's “after done” instruction is honored.
5. Confirm no active mission/preparation/queued run/dispatch. Append the exact WP-85
   generation boundary without rewriting the premature Old marker, rebuild/restart
   all affected state/API/worker/UI services, wait for health, and verify the exact
   served release/API/assets and persisted state.
6. Only then collect retained fixed accelerated repeats, seeded stress, optional fixed
   four-object stress, and realtime evidence. Reconcile qualification/ledger records.
   If this closeout changes only evidence and mechanical packet records, create a
   second scoped closeout commit. Push the complete scoped commit chain to the current
   branch. Report commit hashes, remote branch, and push result.

No production code, generated API, service restart, historical transition, retained
replacement run, commit, or push is authorized before the applicable gate/order.

### Review economy and stop boundary

This successor exists only because two safety/identity P1s survived WP-84's final
recheck and the operator explicitly authorized WP-85 under `REQ-WFL-044`. The design
review unit is the complete composite but the new proof surface is seven checks,
thirteen command-spy cases, eight rejected seed aliases, and six boundary deltas.
One design review and one consolidated correction/recheck are the maximum. Any
remaining P0/P1 `MUST_FIX_NOW` blocks implementation; P2 polish is explicitly deferred
unless it makes the minimum outcome or a user-visible claim false.

<!-- WP85-DESIGN-PAYLOAD-END -->

### WP-85 design verification handoff

- Frozen inclusive design payload: `12,179` bytes, SHA-256
  `e3ec8097c64e0af93f735ed6a59615b5ad1b2e8883e00e7105e9cd0863d5ef3d`.
- Composite review inputs are the immutable WP-84 initial/R1 payloads plus this exact
  WP-85 payload. The focused audit is independently byte-reproducible and passes all
  seven checks.
- Gate state remains `DRAFT_UNVERIFIED`. A fresh project-scoped verifier must return
  `DESIGN_VERIFIED` before any production implementation. One consolidated correction
  and one focused same-verifier recheck are the maximum.

### WP-85 initial independent design verdict

- The fresh verifier reproduced all three composite payload identities, the real
  source-case identity, the strict seed/type vectors, and the byte-stable projection,
  but returned `BLOCKED_WITH_FINDINGS` with no P0 and three P1 `MUST_FIX_NOW` items.
- The three findings were: label-triggered exceptions instead of malformed authority
  objects at real consumption boundaries; a false 82-path closure that omitted the
  transitive runner/watchdog/perception/export transit; and a requirement checker that
  allowed the index to display total 147 while 148 definitions existed.
- The following overlay is the one permitted consolidated correction. The same
  verifier may perform one focused recheck; no further automatic WP-85 design pass is
  permitted.

<!-- WP85-DESIGN-R1-PAYLOAD-BEGIN -->

## WP-85 design R1 — semantic mutation and transitive-boundary correction

This overlay supersedes conflicting WP-85 initial clauses. The immutable initial
WP-85 payload remains SHA-256
`e3ec8097c64e0af93f735ed6a59615b5ad1b2e8883e00e7105e9cd0863d5ef3d`.
Canonical **Status:** `PLANNED`; **Independent verification:** `DRAFT_UNVERIFIED`.

### Corrected focused identities

| Artifact | R1 identity |
| --- | --- |
| Audit program | SHA-256 `f2b7828aa00a0de61b30d0b1e4aec496d403934c337c8535a0246e1bdbe90caf` |
| Audit artifact | SHA-256 `e3a47e7128d42a8ad4197c52e7b3bab47d3817b76a37c1ea8665570d465f1da7` |
| Requirements index | SHA-256 `6e4995ede722a9302cae51a81885ee4ea007f5efa8197416b3cdd47d9c7285ed` |
| Requirement checker | SHA-256 `bcc12ab5f58e1757adab3ce7a97f4990929883510b7763b70b43abd0f9cefeea` |

Two independent audit runs produce exact artifact SHA-256
`e3a47e7128d42a8ad4197c52e7b3bab47d3817b76a37c1ea8665570d465f1da7`.
The revised audit passes eight checks.

### Authority-semantic command-spy oracle

The audit no longer branches on display labels. Each case is an immutable
`Mutation(boundary enum, fault enum, label)` where behavior uses only the semantic
boundary/fault. Three mutations are rerun with unrelated renamed labels; boundary,
fault, actual command count, fallback count, error type, regression status, and
expected post-fix result remain identical.

Every case first constructs the real changed-world proposal. The semantic mutator then
passes the exact malformed value to its real consumer:

- safe-prefix: the monitor returns `None` or an exact certificate with wrong case;
- abort: the monitor passes `None` or a wrong-case abort certificate into safe-prefix
  certification;
- feasibility: the real proposal's `BoundedPlanningResult` receives a missing
  certificate or a certificate whose passed verdict is false;
- cutover: the real `rebase_changed_world_replacement` runs, then the rebased proposal
  receives a missing cutover certificate or a failed certificate with a violation;
- proposal: the planner boundary returns `None` or the real proposal with a wrong
  proposal hash;
- receipt: the preparation boundary returns `None` or a real receipt with a wrong
  proposal hash.

The accepted control runs real proposal construction and real rebase, then reaches
one actual `execute_replanned_trajectory` call. The audit does not manufacture passing
exceptions for the negatives. Instead it truthfully records the current pre-fix
production result:

| Current result | Cases |
| --- | --- |
| Already fail closed with zero command and normalized domain outcome | tampered safe-prefix; tampered receipt |
| Zero command but unnormalized missing-authority failure | missing safe-prefix, abort, feasibility, cutover, proposal, receipt |
| Incorrectly reaches one replacement command | tampered abort, feasibility, cutover, proposal |

All twelve freeze `expected_post_fix_replacement_command_calls=0`. A design check
passes only when at least one genuine pre-fix regression is observed, all already
fail-closed cases remain zero/normalized, every semantic boundary/fault pair is
covered, and rename perturbations are invariant. Implementation must make all ten
retained failures pass by adding production validators/error normalization, while
preserving the two current fail-closed cases and one-command accepted control. This is
the mandatory failure-first regression set and may not be replaced with injected
exceptions.

Implementation evidence adds, for each pre-commit negative, zero accepted epoch, zero
replacement command, discarded preparation, exact normalized error code, and retained
fault boundary/authority identity. The different implementation verifier must mutate
new values at the same real consumers and reject any label-based behavior.

### Transitive production-boundary closure

The initial 82-path assertion is withdrawn. R1 starts from six named normal-entry
roots—API app/runtime, Campaign service/runtime executor/execution head, and retained
storage—and parses Python AST imports recursively for repository-local
`crazyswarm_app` modules. It exact-unions that 112-path transitive production closure
with the 76-path predecessor manifest and focused design owners, yielding 170 unique
classified paths with exact preimages or external self-output identity.

This mechanically includes the verifier's omitted examples:
`campaign/execution.py`, `missions/runner.py`, `campaign/perception.py`,
`observability/csv_export.py`, `campaign/geometry.py`, `domain/commands.py`,
`fleet/preparation.py`, `missions/script.py`, `simulation/clock.py`, and
`vehicles/providers.py`. The execution compiler and mission runner are now explicit
owners of source/wall watchdog repair; perception owns observation/world identity;
CSV export owns retained download bytes.

Existing WP-84 classifications remain binding. Newly discovered transitive paths are
`PRESERVE` unless implementation tracing proves the verified behavior requires a
listed owner to be `MODIFY`; such a reclassification is allowed only within this
170-path verified union and must retain the exact preimage plus rationale. A path
outside the union is a scope change. The implementation freeze reruns the AST closure
from the same roots on the postimage and requires exact equality, while the
implementation verifier independently traces the API → service → executor → runner/
execution-head → evaluation/storage/export sequence.

### Requirement-index reconciliation

The ownership index now displays total `148`. The checker no longer validates source
definitions alone: it parses the displayed ownership rows, requires exact equality to
the expected prefix/range/owner/count tuples, requires the displayed-row sum to equal
the discovered definition count, and requires the displayed total to equal that same
count. It still validates unique definitions, sequential IDs, canonical owner files,
non-normative separation, links, and AGENTS routing.

Both human index and executable checker now agree on 148 definitions and `WFL=54`.
Implementation evidence runs both plain and JSON checker modes and retains empty error
output. The requirements index/checker and all frozen design artifacts are preserved
during production implementation except mechanical verified-status records.

### R1 stop boundary

The complete accepted candidate is WP-84 initial + WP-84 R1 + WP-85 initial + this
overlay. The strict seed and stable projection corrections remain unchanged. No
production implementation, generation, restart, retained run, commit, or push is
authorized until the same verifier's one focused recheck returns `DESIGN_VERIFIED`.

<!-- WP85-DESIGN-R1-PAYLOAD-END -->

### WP-85 R1 focused-recheck handoff

- Frozen correction overlay: 6,730 bytes, SHA-256 `c604a4d8fdd6833490ae166878f7a10809f0a2881c764671ffbf33f0ccceb6eb`.
- Accepted composite: WP-84 initial `c993df7c80b18a5fe5b4e3fe950d94ce736d1fb6c851dbb9b69cf2f2cc17d4a0` plus WP-84 R1 `1dc093e440d8e2e624e060d8fb37370f761ca99b4d68506bc7927e0076641c73` plus WP-85 initial `e3ec8097c64e0af93f735ed6a59615b5ad1b2e8883e00e7105e9cd0863d5ef3d` plus this R1 overlay.
- Corrected audit script: `f2b7828aa00a0de61b30d0b1e4aec496d403934c337c8535a0246e1bdbe90caf`.
- Corrected retained audit artifact: `e3a47e7128d42a8ad4197c52e7b3bab47d3817b76a37c1ea8665570d465f1da7`.
- Gate remains `DRAFT_UNVERIFIED`; this is WP-85's only correction, and the same verifier's focused recheck is final.

### WP-85 final independent design verdict

- **Status:** `REVIEW_BLOCKED`.
- **Independent verification:** `BLOCKED_WITH_FINDINGS`.
- The authority-semantic command-spy oracle and exact 148-definition requirement-catalog reconciliation passed the focused recheck.
- One P1 `MUST_FIX_NOW` remains: the claimed exact transitive boundary closure did not include parent-package `__init__.py` execution and imports introduced by those initializers. An independent fresh-process comparison found 128 actually loaded repository modules versus the declared 112-module AST closure, leaving seventeen runtime-loaded paths outside the 170-path final manifest, including the API, campaign, domain, fleet, missions, observability, safety, simulation, and vehicles initializers plus the Isaac vehicle/package transit.
- WP-85 consumed its one revision and focused recheck. No third automatic WP-85 design pass is permitted, and no production implementation, qualification, commit, or push is authorized from this blocked design.

### WP-83 implementation handoff

- Exact implementation manifest:
  `missions/campaigns/sim/qualification/wp83-implementation-manifest-v1.json`, SHA-256
  `ade996ffe2723105e1a0f3efa389711bacec42751b5dfa2133a0448894401115`.
- The manifest freezes all eight owned files with artifact-derived preimage hashes and
  whole-file postimage hashes; no implementation file was added, deleted, or renamed.
- Preimage regression failed as intended at `schema_version 2 != 3`. Postimage evidence:
  9/9 trajectory tests, 13/13 simulator vehicle tests, 20/20 supervisor tests, 2/2
  mission-authority tests, and the long-duration landing qualification test pass.
  Ruff, mypy, requirement-catalog validation, and complete v1/v2 production parsing
  also pass.
- Retained out-of-boundary failures: one simulator collision test expects an older
  contact receipt, and API repeat-run suites encounter the workspace’s existing
  unknown-vehicle/404 cleanup defect. Neither failure traverses a WP-83-owned path.
- Status remains `IMPLEMENTED_UNVERIFIED` pending a different fresh verifier’s
  production-path, oracle-sensitivity, regression, and documentation review.

### WP-83 independent implementation verdict

- Fresh verifier verdict: `IMPLEMENTATION_VERIFIED`; no P0/P1 findings.
- All 44 frozen boundary identities matched. Both production clock modes retained 316
  capture-through-contact samples with exact endpoint identity, 6.9 mm maximum XY
  displacement, 5.4 mm maximum centerward progress, zero terminal Z, and zero nominal
  alignment duration.
- Independent perturbations removing capture coverage and injecting center-seeking
  failed the oracle. Exact diversion retained a 0.5 s alignment phase; wrong-Z,
  near-diversion, and outside-region commands were rejected. Historical v1/v2 parsing,
  44 affected tests, Ruff, mypy, and all 147 requirement definitions passed.
- Retained P2: the schema-v3 model permits a manually constructed `CAPTURED` record
  with new evidence fields absent. The verified WP-83 production path always emits the
  complete evidence, so this is a bounded future model-hardening item rather than a
  false integration claim.
- This verification record and the verification-field change are mechanical closeout
  only; the reviewed eight-file implementation payload is unchanged.
<!-- WP86-DESIGN-PAYLOAD-BEGIN -->

## WP-86 — truthful quick-switch Digital Twin projection and props-off diagnostics

Status: `PLANNED`

Independent verification: `DRAFT_UNVERIFIED`

Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.

Ledger preimage SHA-256:
`831eb89d5681cdd0eb978f8e1c96c82ed08530024860d262fca0666ba9c5d638`.

WP-86 is the bounded successor to WP-80's implementation-blocked observation entry.
It does not reopen or upgrade WP-80's verdict. It uses the operator's first real-radio
sessions to correct source-context projection, expose useful observation-only sensor
truth, and repair paired-session time before any residual is trusted.

### Frozen originating operator request

> the jump from x y could be because i picked it up so delete that data there, i now
> started a second sample read that data and maybe take that data, for the others of
> coruse you can also use those data for the successor wp, so i have it running now
> anazle again with your previous finding etc. just be aware that i think it is ok that
> it is connected to the drone while in simulation so it is meant to be quick switch,
> just make sure that then e.g. in digital twin no planned missions e.g. here
> bottleckenc from simulation are in and it claims there two drones there, there is
> only one and it should be called by the name it was given in the edit mode. ok so
> scan again and structure the wp
>
> also can it be theat the measured batery is measured once at the beginning because
> it always drops lower when i restart the conenction but does not move while it
> catching samples

The operator then stopped the observer and confirmed that the retained second sample
was sufficient. The pickup-contaminated session
`twin-43d3f75cb2374a00ba0c63c69be472ae` was removed from the active append-only twin
journal after disconnect. A timestamped recovery copy exists outside the active
journal; this operational cleanup is evidence curation, not a WP-86 product feature.

### Intent/value card

- **Minimum useful operator outcome:** Simulation and Digital twin switch quickly
  without reconnecting an already paired command-inert observer, while Digital twin
  shows exactly one observation subject named with the configured operator label and
  contains no simulation mission, campaign, plan, fleet, target, or quick-action
  state.
- **Explicitly requested behavior:** preserve the observation link in the background
  when selecting Simulation; remove `Bottleneck` or any other simulation plan from the
  Digital twin context; replace the false two-drone/simulation count with one
  `Drone#1 - Nike` subject; use the clean props-off data to make battery, IMU, Flow,
  range, estimator, freshness, and sample semantics understandable.
- **Necessary prerequisites:** retain WP-80's service-private zero-command boundary;
  make backend status authoritative over the edit form; separate simulation command
  state from the Digital twin presentation model; repair the paired-session clock so
  source-aligned diagnostics do not compare unrelated raw producer clocks.
- **Optional experiments:** later firmware A/B comparison, Flow surface/lighting
  experiments, world calibration, residual thresholds, and retained-session charts.
  They remain visible future evidence needs and are not required to implement WP-86.
- **Non-goals:** no Crazyflie firmware update, calibration promotion, HOME-to-WORLD
  transform, trustworthy position residual, scan, command permit, preflight, motor,
  arm, takeoff, hover, landing, hotkey, emergency-stop, or physical-flight authority.

### Frozen clean hardware observation

The design input is completed session
`twin-f33a1e55c4f2431480f1f41cd6f45a19`, labeled `Drone#1 - Nike`, with exact URI
identity already retained by WP-80. It is `HARDWARE / OBSERVED_REALTIME` observation
evidence only, has no ground truth, and does not qualify physical accuracy.

- 1,264 paired observation cycles produced 70,784 channel records: 28 observed and 28
  predicted records per cycle. UI copy must say `channel samples` or show cycles and
  records separately; it must not call 70,784 independent time steps.
- Measured battery has 1,263 available readings and eight exact quantized values. It
  changes from 3.9061584473 V to 3.8692083359 V; therefore it is not sampled only at
  connection time. Two-decimal rendering hides the approximately 5.279 mV steps.
- Props-off motion evidence is quiet: median acceleration norm 9.8214 m/s², 95th
  percentile angular-rate norm 0.00842 rad/s, and attitude spans 0.01624/0.02380/
  0.00683 rad. This supports a stationary interpretation for this session only.
- Observed Flow is reported `VALID` by the existing model but has 3.529% median
  quality, 3.846 m/s median horizontal velocity, 7.005 m/s 95th percentile velocity,
  and 0.018 m median ground distance. WP-86 must show the literal raw status and
  numeric quality and must keep usability `UNQUALIFIED`; it may not present this as
  real motion or invent a new acceptance threshold.
- The estimator is unconverged in 1,232 of 1,263 available readings. Position variance
  grows from x/y/z 3.5223/3.4714/0.00853 m² to
  6.7814/5.0028/0.01533 m². The retained x/y drift is therefore an estimator/Flow
  diagnostic, not observed world displacement.
- The first observed cycle is a missing placeholder at mapped time 0. The next real
  observation arrives with raw firmware time 1,933.909 s and is incorrectly mapped to
  that value. After the same 1,264 paired cycles, observed mapped time is 2,271.529 s
  while predicted mapped time is 126.300 s. Until corrected, all cross-source time
  alignment and residuals remain unavailable/incompatible.

### Quick-switch lifecycle and source isolation

Simulation/Digital twin is a presentation/source-context selector, not the observer
connection switch. Selecting Simulation while the observer is `PAIRED` keeps the
private physical and predicted observation adapters connected and recording. Selecting
Digital twin while already paired performs a status refresh only and reuses the same
session; it must not reconnect or create another session. Explicit `Disconnect
observer`, edit/rebind, service shutdown, connection failure, and application shutdown
retain the existing serialized disconnect path.

The background observer remains command-inert. A simultaneous Simulation mission can
target only registered Fast Sim vehicles. Private `physical:*` and
`fast-sim:*` observation IDs never enter command target, fleet, selected-vehicle,
mission, Engineering, parameter, or SafetySupervisor registries. A persistent observer
therefore improves switching latency without weakening WP-80's zero-command boundary.

Simulation may show one quiet `Observer connected` state beside the Digital twin
selector. It must not merge measured telemetry into simulation values, counts, paths,
or command targets. Simulation continues to show its own configured scenario and
mission state.

### Digital twin presentation projection

When the source context is Digital twin, the served Control Center derives a dedicated
observation projection instead of continuing to render `DashboardModel` simulation
selection state:

1. The top mode is `SHADOW`, reinforced by `Observation only`; it is not `LIVE` and
   never implies command authority.
2. The subject capsule shows exactly the configured binding label, for example
   `Drone#1 - Nike`, and `1 observed`. The predicted source is a model for that subject,
   not a second drone. Private IDs remain in technical detail only.
3. `RoomScene` receives no simulation vehicles, mission preview, planned path, campaign
   fleet, home bases, command selection, or replay state. With HOME-only position it
   shows one named observation subject and `Position unavailable in world frame`; it
   does not place a fabricated world marker.
4. Mission deployment, simulation campaign/Python mission content, Run action,
   simulation quick actions, Run files, Engineering command targeting, and simulation
   flight readout are absent. The bottom source capsule reads `Drone#1 - Nike` and
   `Digital twin · Observation only`, with no retained `Bottleneck` or other mission
   title.
5. Switching back to Simulation restores the unchanged simulation presentation while
   the observer continues recording until explicit disconnect.

Disconnected, error, pending-confirmation, and configured states keep the same
single-subject projection. A refresh may default the presentation to Simulation even
while the private observer is paired, matching the operator's quick-switch choice; the
quiet connection state must remain truthful.

### Authoritative edit/transition reconciliation

`GET /physical-twin/status` remains authoritative. The UI polls it while the observer
is `CONNECTING`, `PENDING_CONFIRMATION`, or `PAIRED`, including while Simulation is the
selected presentation. A successful binding save exits edit mode before connect is
awaited. Any authoritative `CONNECTING`, `PENDING_CONFIRMATION`, or `PAIRED` response
clears the local edit flag and renders that state immediately. An operator-entered
edit form remains only while the backend is disconnected/error/configuration-invalid;
an obsolete error stays hidden during that deliberate edit.

The regression oracle starts in error, opens Edit, saves a confirmed exact URI, makes
the connect response time out locally while the backend advances to
`PENDING_CONFIRMATION`, and then observes the pending identity prompt without reload.
The negative case keeps the form and unchecked exact-URI guard when the backend remains
disconnected and configuration has not been saved.

### Props-off diagnostic surface

Add `TwinObservationReadout` inside the existing bottom-right readout boundary; it is
not a second dashboard. Its compact state shows the configured label, connection and
freshness, measured battery to three decimals, paired-cycle/channel-record counts, and
the explicit `Observation only` authority. Its expanded state exposes current measured
and predicted battery; measured IMU acceleration/angular velocity; attitude; Flow raw
status, quality, body velocity, and range height; six-direction range values/statuses;
estimator convergence and x/y/z variance; source/raw/alignment clocks; epoch; and
availability/quality for each family.

The physical-twin status contract may add typed current diagnostic fields from the
already-held latest envelopes; no model value fills a missing observed value. Flow
quality remains numeric and `UNQUALIFIED` until a separately frozen hardware policy
defines usability. Estimator `converged=false` is degraded and prominent. Battery uses
three decimals and freshness so its measured quantization is visible. Technical IDs,
raw hashes, and exact clocks remain in the existing disclosure hierarchy.

The completed session remains reviewable after disconnect through its retained
session/timeline identity, but multi-page historical plots and a new deletion product
surface are deferred. Missing, stale, disconnected, first-placeholder, partial-sensor,
and incompatible-frame states have explicit text equivalents.

### Paired-session clock correction

WP-86 supersedes only WP-80 R1's mapped-time algorithm. Each accepted service pair
already has one authoritative admission monotonic timestamp. The service establishes a
session origin from the first non-placeholder pair and assigns both OBSERVED and
PREDICTED samples in that pair the same session-relative
`source_timestamp_s = admitted_monotonic_s - origin`. Raw producer clock ID, raw time,
and producer epoch remain unchanged in their existing fields. An all-measured-channels-
missing placeholder neither establishes the origin nor emits a retained pair.

Raw firmware jumps do not move paired session time. Admission-time jitter does, because
it is real observation cadence. Raw rollback increments the affected producer epoch;
residual derivation still rejects cross-epoch pairing. The frozen prototype covers:

- nominal admission times 100.00/100.11/100.21 s with observed raw times
  1933.909/1934.603/1935.071 s and predicted raw times 0.1/0.2/0.3 s, producing
  0.00/0.11/0.21 s on both mapped sides;
- a raw-clock perturbation to 10/5000/5001 s with identical admissions, producing the
  same mapped vector while preserving the changed raw vector;
- an admission perturbation to 100.00/100.15/100.28 s, producing
  0.00/0.15/0.28 s and proving the oracle is not a constant; and
- an all-missing placeholder that emits no pair and establishes no clock origin.

No position residual is enabled. A battery residual may become available only when
unit, frame, epoch, availability, and paired-session time all pass the existing
independent ingestion oracle.

### Claim and exit matrix

| Claim key | Production entry and effect | Retained observation | Independent oracle / counterexample | Boundary |
| --- | --- | --- | --- | --- |
| `background_observer_isolation` | served selector changes presentation only; explicit disconnect remains the sole ordinary stop action | one unchanged paired session ID/count continues while Simulation commands target only `sim01` | fake command-spy plus real route family rejects both private IDs; Simulation mission changes only Fast Sim while observer samples advance | `PRODUCTION_ENTRY / FAST_SIM+HARDWARE / OBSERVED_REALTIME` |
| `single_subject_projection` | Digital twin projects binding/status instead of simulation dashboard selection | `Drone#1 - Nike`, `1 observed`, SHADOW, no campaign/plan/fleet/quick actions | seed Simulation with renamed `Bottleneck` and reordered two-drone preview, then switch context; neither name nor fleet survives and no world marker appears for HOME-only position | `PRODUCTION_ENTRY / SERVED_UI / OBSERVED_REALTIME` |
| `authoritative_transition_reconciliation` | status poll overrides stale edit state | pending confirmation appears without refresh after local connect timeout | backend stays disconnected before save: edit values and unchecked guard remain; obsolete error stays hidden | `PRODUCTION_ENTRY / SERVED_UI / OBSERVED_REALTIME` |
| `literal_props_off_diagnostics` | latest envelopes -> typed status -> `TwinObservationReadout` | battery 3 decimals, cycle/record counts, IMU, Flow, range, estimator, freshness and authority | remove each observed family while prediction remains; UI says missing and never substitutes. Low-quality `VALID` Flow stays raw/UNQUALIFIED, not motion | `PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME` |
| `paired_session_clock` | accepted pair admission time -> mapper -> ingestion -> timeline/residual | identical mapped pair time, preserved raw clocks/epochs, no placeholder anchor | frozen nominal/raw/admission/placeholder vectors plus rollback/cross-epoch rejection | `INTEGRATION / HARDWARE-LIKE FIXTURE / OBSERVED_REALTIME` |

### Exact implementation boundary

Production ownership is limited to:

- `src/crazyswarm_app/hardware/observation_twin.py` for background lifecycle status,
  typed latest diagnostics, cycle/record semantics, placeholder rejection, and paired
  admission time;
- `src/crazyswarm_app/twin/ingestion.py` and `src/crazyswarm_app/twin/models.py` only
  if needed to preserve explicit quality/epoch/residual fail-closed semantics;
- `src/crazyswarm_app/api/app.py`, `ui/openapi.json`, and
  `ui/app/lib/api.generated.ts` for the generated typed status contract;
- `ui/app/lib/api.ts` and `ui/app/lib/models.ts` for exact adaptation;
- `ui/app/components/ControlCenter.tsx`, `RoomScene.tsx`, `TelemetryDock.tsx`, and new
  `TwinObservationReadout.tsx` for source projection and diagnostics;
- `ui/app/globals.css`, `design.md`, and `docs/project/DESIGN.md` for the corrected
  durable quick-switch/SHADOW pattern; no responsibility owner or entry point moves,
  so `docs/system/README.md` is relied upon unchanged; and
- focused existing tests plus new `ui/tests/twin-observation-readout.test.tsx`.

The machine audit derives recursive Python and UI transit closures from the production
seeds, derives the OpenAPI output pair from `ui/package.json`, hashes every existing
boundary, marks both intended new UI files absent, and reconciles claim owners/entries
to the manifest. Implementation must freeze a separate postimage reconciliation
manifest because production and generated identities are expected to change.

### Declared implementation evidence

1. Establish sensitivity with failing pre-fix UI tests for the two-drone/Bottleneck
   leak, persistent-observer switch, renamed binding label, edit-to-pending race,
   two-decimal battery concealment, missing family, and HOME-only marker rejection.
2. Add service tests for same-session background recording, explicit disconnect,
   zero command calls, current typed diagnostics, exact cycle/record counts, placeholder
   rejection, paired admission mapping, raw-clock perturbation, admission perturbation,
   rollback epoch, and cross-epoch residual rejection.
3. Run focused Python/UI tests, typecheck, ESLint, Ruff, mypy, generated OpenAPI drift,
   production build, and the WP-86 audit/implementation manifest.
4. Rebuild/restart the managed service only with no active mission/observer, bind the
   exact release/API/asset identities, and inspect port 3001 at desktop and narrow
   widths. Served states include Simulation with background observer, Digital twin
   paired/disconnected/pending/error/edit, expanded/collapsed diagnostics, missing
   sensors, keyboard/focus, and reduced motion.
5. Use a controlled fake link for automated paired interaction. No additional real
   radio connection or firmware change occurs without separate operator authorization.

### Exit and limits

WP-86 exits the design gate only after an independent verifier accepts this exact
payload and its audit. This request is design/structure work; implementation does not
begin in this packet turn. Later implementation remains `IMPLEMENTED_UNVERIFIED` until
a different fresh verifier checks the exact postimage manifest and served release.

Success does not qualify estimator position, Flow usability, world calibration,
battery model accuracy, command readiness, motors, or flight. The safe fallback for
any blocked UI projection is to keep Digital twin observation-only, suppress every
simulation mission/fleet/command surface in that context, and show unavailable data
literally.

<!-- WP86-DESIGN-PAYLOAD-END -->

### WP-86 design-review handoff

- Delimited payload: 18,386 bytes, SHA-256
  `33aff815719a6ce14a9973b2d9f19ed58c66415f80432a63035442955aa269e4`.
- Pre-freeze artifact: `missions/campaigns/sim/qualification/wp86-design-audit-v1.json`,
  SHA-256 `0de38f83213b06068f6c294ce674a212ae7ef772b4e20912fd624d47c3201ad5`.
- Audit implementation: `scripts/audit_wp86_design.py`, SHA-256
  `13ed0de359ee8422a26b51a897a8d3d034b4c75de9cf19848e80540133d74f0c`.
- Audit result: zero errors; 114-file recursive Python closure, 15-file recursive
  UI/worker/CSS closure, 150 total frozen boundaries, five reconciled claim rows,
  exact generated API pair, and sensitive nominal/raw/admission/placeholder clock
  witnesses.
- Review count: `0`; correction count: `0`; focused recheck count: `0`.
- Model route: author used frontier reasoning because hardware clock semantics,
  source/command isolation, and user-visible truth cross safety-relevant boundaries.
  Token/time counts are not exposed; proxies are one hardware session analysis, one
  served release inspection, one deletion/recovery operation, two changed design files,
  and one generated audit artifact.
- Hardware authority: observation only; command/motor/flight authority absent.
- Independent verification: `DRAFT_UNVERIFIED`.

<!-- WP86-R1-DESIGN-PAYLOAD-BEGIN -->

## WP-86 R1 — consolidated design correction

Status: `PLANNED`

Independent verification: `DRAFT_UNVERIFIED`

This is the one permitted consolidated design correction. It supersedes only the
conflicting lifecycle, clock/residual, evidence-boundary, hardware-freeze, exact
implementation-boundary, and declared-evidence text in the initial WP-86 payload.
All other initial scope and safety limits remain frozen. No implementation is
authorized by this correction.

### Active Simulation operation guard

Quick switching is permitted only when it cannot hide an active Simulation
operation. Define `simulationOperationActive` from the existing production state as:

- a fleet execution whose `runStatus` is `SCHEDULED`, `PREPARING`, `READY`, or
  `RUNNING`;
- a non-terminal Python mission represented by `runningRunId` or a latest run whose
  status is `RUNNING`; or
- a campaign run whose status is `QUEUED` or `RUNNING`.

An abort/cancel request does not clear this guard: the operation remains active until
the authoritative run becomes terminal (`SUCCEEDED`, `ABORTED`, `FAILED`, or
`CANCELLED_BEFORE_LAUNCH`, as applicable). While the guard is true, the Digital twin
selector is disabled with the visible reason `Finish or abort the active Simulation
run before opening Digital twin.` The Control Center stays in Simulation and retains
the live run, progress, and Abort and land control. It may not switch presentation
first and thereby conceal the operation.

When no Simulation operation is active, selecting Digital twin changes presentation
only. A `PAIRED` observer is reused without reconnecting; a disconnected observer is
shown as disconnected and is connected only by an explicit `Connect observer` action.
Selecting Simulation never disconnects a paired observer. Explicit `Disconnect
observer` remains the ordinary connection stop action. Thus the requested background
observer and quick switch do not redefine or obscure Simulation execution ownership.

The counterexample seeds a `Bottleneck` fleet in `SCHEDULED`, `RUNNING`, and an
abort-requested-but-not-terminal state: Digital twin remains disabled, Simulation and
Abort and land remain visible, and the observer session/sample count may continue.
After the run becomes terminal the selector enables; Digital twin then shows one
configured-label observation subject and no `Bottleneck`, plan, fleet, deployment,
command target, quick action, or Simulation flight readout.

### Exact pair and epoch semantics

The initial promise to compare by mapped-time proximity and reject numerically unequal
producer epochs was underspecified. Producer epochs are independent: an observed
Crazyflie rollback can legitimately increment its raw epoch while the predictor raw
epoch stays unchanged. R1 replaces nearest-neighbour residual alignment with an exact
service-pair contract:

1. After rejecting an all-measured-channels-missing placeholder, the observation
   service increments a positive `pair_sequence` once per admitted observed/predicted
   envelope pair. It derives an unambiguous `pair_id` from the session ID,
   `pair_sequence`, and admitted monotonic timestamp. Every emitted channel sample on
   both sides carries that same pair identity and the same session-relative admitted
   `source_timestamp_s`.
2. The service owns a positive `alignment_epoch`. It begins at one and increments
   before emission whenever either producer clock ID or producer epoch changes. Both
   sides of that exact admitted pair receive the new common alignment epoch. Raw
   producer clock ID, raw timestamp, and producer epoch remain unchanged and separate.
3. A residual can be `AVAILABLE` only for samples with the same session, channel,
   unit, frame, `pair_id`, `pair_sequence`, and `alignment_epoch`, with both samples
   available and subtractable. The retained residual identifies both input hashes,
   both raw producer epochs, the common alignment epoch, and the pair identity.
   Mapped-time nearest-neighbour reach-back is removed for paired hardware sessions.
4. A producer rollback therefore creates a new common alignment segment. Observed raw
   epoch 2 and predicted raw epoch 1 may be compared only when they belong to the same
   newly admitted pair and common alignment epoch; observed pair 2 can never borrow
   predicted pair 1. Numeric equality between independent raw epochs is not an oracle.
5. Historical samples without retained pair identity never fall back to time-nearest
   matching. Their residual is `MISSING / UNQUALIFIED` until an exact pair identity is
   available. No position residual becomes available because HOME/WORLD remains
   incompatible.

The executable rollback witness admits pair 1 in alignment epoch 1, then rolls only
the observed producer and admits pair 2 in alignment epoch 2. Exact pair 2 is
available when both inputs exist; removing predicted pair 2 produces
`MISSING / UNQUALIFIED` and cannot select predicted pair 1. The executable partial-
sensor witness emits the pair when IMU is available but observed battery is missing:
the IMU residual may be available, while battery is `MISSING / UNQUALIFIED` and never
uses predicted battery as measured truth. The all-measured-channels-missing witness
emits no pair, consumes no `pair_sequence`, and establishes no session-clock origin.

This makes `src/crazyswarm_app/twin/replay.py` and
`tests/twin/test_replay.py` implementation-owned claim boundaries, alongside the
initial service, ingestion, and model owners.

### Canonical claim/evidence boundaries

All implementation claims use the exact `REQ-WFL-018` vocabularies. Controlled link
and served-browser fixtures exercise changed production entries under `FAST_SIM`; they
cannot close a new `HARDWARE` implementation claim. The retained real-radio run is a
separate pre-change observation baseline and diagnostic input only.

| Claim key | Production entry and effect | Independent oracle / counterexample | Boundary / environment / clock |
| --- | --- | --- | --- |
| `background_observer_isolation` | served selector changes presentation only; explicit disconnect stops observation | controlled link command-spy rejects private IDs; samples advance in Simulation while Fast Sim commands target only `sim01` | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |
| `single_subject_projection` | Digital twin derives one configured-label observation projection | renamed/reordered two-drone `Bottleneck` fixture cannot leak; active run disables switching and keeps Abort visible; terminal run enables it | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |
| `authoritative_transition_reconciliation` | served status poll overrides stale edit state | connect response times out while status advances to pending; disconnected-before-save retains guarded edit | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |
| `literal_props_off_diagnostics` | latest controlled envelopes traverse typed status into the served readout | remove each observed family while prediction remains; UI renders missing and never substitutes; low-quality `VALID` Flow remains raw/UNQUALIFIED | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |
| `paired_session_clock` | controlled pair admission traverses service, ingestion, retained timeline, and residual derivation | executable raw/admission perturbations, rollback/reach-back rejection, partial-sensor and all-missing placeholder witnesses | `INTEGRATION / FAST_SIM / OBSERVED_REALTIME` |
| `retained_hardware_observation` | existing production observer session, before WP-86 implementation | deterministic journal reconstruction and normalized-sample hash; no ground truth or changed-code claim | `PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME` |

The implementation gate must report the changed-code hardware row as `NOT_RUN` unless
the operator separately authorizes another real-radio observation. Existing hardware
data may be replayed through changed readers as `INTEGRATION / FAST_SIM /
OBSERVED_REALTIME`; replay does not promote it to a new hardware result.

### Reconstructable clean hardware observation

The retained clean session is frozen in
`missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json`. The extractor
validates every exact-session journal envelope and compressed-batch hash, removes
run-random sample IDs/hashes and receipt clocks from the normalized projection, sorts
70,784 samples by sequence/side/channel, and hashes all remaining causal observation
fields. Reconstruction is:

`python scripts/extract_wp86_hardware_observation.py --check missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json`

The immutable facts are 1,266 exact-session journal envelopes, 1,264 paired cycles,
35,392 records per side, 70,784 normalized channel records, and normalized SHA-256
`d2a4a91399f4a5f902e9e01fdce7a9da9c7bbb44df19efc6343421692c80e1b7`.
The artifact independently reconstructs battery, Flow, estimator, stationary-check,
and clock-counterexample summaries. With its explicit linear percentile rule, Flow
horizontal-speed p95 is 7.0050827846 m/s; this replaces the initial rounded value from
a different percentile convention and does not change `UNQUALIFIED` usability.

This artifact closes only the `retained_hardware_observation` baseline. Its label and
binding context remain status/identity evidence outside the telemetry journal; the
artifact does not fabricate them or physical ground truth.

### Corrected exact boundary and evidence

Add the following to the initial implementation-owned boundary:

- `src/crazyswarm_app/twin/replay.py` for exact-pair residual selection and fail-closed
  legacy behavior; and
- `tests/twin/test_replay.py` for direct residual sensitivity and counterexamples.

Add the following frozen design-evidence boundaries, relied upon unchanged during
implementation:

- `scripts/extract_wp86_hardware_observation.py`;
- `missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json`;
- `scripts/audit_wp86_design_r1.py`; and
- `missions/campaigns/sim/qualification/wp86-r1-design-audit-v2.json`.

Implementation evidence must include failing-before/fixed-after tests for the active-
operation switch guard, terminal re-enable, paired-observer preservation in both
presentation contexts, explicit disconnect, disconnected Digital twin with no implicit
connect, and one-subject mission-free projection. Clock tests must execute nominal,
raw-clock perturbation, admission perturbation, observed-only rollback, removed-current-
prediction reach-back, partial-sensor, all-missing placeholder, incompatible frame,
and legacy-no-pair cases through the real residual owner. Served evidence remains on
port 3001 and uses a controlled link; no additional hardware connection, firmware
change, motor action, or flight authority is authorized.

<!-- WP86-R1-DESIGN-PAYLOAD-END -->

### WP-86 R1 focused-recheck handoff

- Initial independent verdict: `BLOCKED_WITH_FINDINGS`; no P0 and four P1
  `MUST_FIX_NOW` findings covering active-run concealment, non-executable epoch
  rejection, noncanonical/mixed evidence labels, and an unreconstructable hardware
  summary.
- Frozen initial payload: 18,386 bytes, SHA-256
  `33aff815719a6ce14a9973b2d9f19ed58c66415f80432a63035442955aa269e4`.
- Frozen R1 correction: 10,868 bytes, SHA-256
  `c7532e883502314bdb79b1fa71767bfe41c8d6edb4c01b2ff4b2a1c3d98e0791`.
- Corrected audit: `scripts/audit_wp86_design_r1.py`, SHA-256
  `6a1505079a0f1f92fb2e6a058bd27d4b574a24585a422b70dc89b2b546d56f94`.
- Corrected audit artifact:
  `missions/campaigns/sim/qualification/wp86-r1-design-audit-v2.json`, SHA-256
  `4b5e224f331e39481bc44fb7331c8b4511d0fb7678d8ea0fd7915f0827e2c84c`.
- Hardware extractor: `scripts/extract_wp86_hardware_observation.py`, SHA-256
  `e363b7ece3c676928503c422b639468ace08c0146e9657384a2da4016131b57a`.
- Reconstructable hardware artifact:
  `missions/campaigns/sim/qualification/wp86-hardware-observation-v1.json`, SHA-256
  `b70e38c8bfafb2693a7d250a14d51061847e6559b1d83354364c6d469804d5fd`;
  70,784 normalized samples, normalized SHA-256
  `d2a4a91399f4a5f902e9e01fdce7a9da9c7bbb44df19efc6343421692c80e1b7`.
- Audit result: zero errors across 154 exact boundaries, six executable pair/rollback/
  partial/legacy witnesses, canonical claim triples, and live journal reconstruction.
- Review count: `1`; correction count: `1`; focused recheck count: `0`.
- Hardware authority: retained observation baseline only; changed-code hardware claim
  `NOT_RUN`; command/motor/flight authority absent.
- Independent verification remains `DRAFT_UNVERIFIED`. This is the sole correction;
  the same verifier's focused recheck is the final automatic WP-86 design pass.

### WP-86 final design-gate outcome

Status: `PLANNED`

Independent verification: `DESIGN_VERIFIED`

- The same verifier completed the sole focused recheck and found no residual P0/P1.
  All four initial P1 findings are resolved by the exact initial payload
  `33aff815719a6ce14a9973b2d9f19ed58c66415f80432a63035442955aa269e4`
  plus R1 payload
  `c7532e883502314bdb79b1fa71767bfe41c8d6edb4c01b2ff4b2a1c3d98e0791`.
- Reviewer: `/root/wp86_design_verifier`; initial review count `1`; correction count
  `1`; focused recheck count `1`. The design-review cycle is exhausted.
- Verdict: `DESIGN_VERIFIED`. WP-80 remains `BLOCKED_WITH_FINDINGS`; this successor
  verdict does not upgrade WP-80.
- Changed-code hardware evidence remains `NOT_RUN`. Implementation authority is
  observation-only and excludes firmware, command, motor, and flight behavior.

### WP-86 fast-loop implementation handoff

Status: `IMPLEMENTED`

Independent verification: `BLOCKED_WITH_FINDINGS`

- Implemented the accepted bounded projection, diagnostics, authoritative edit-state
  reconciliation, and exact-pair clock/residual behavior without adding command,
  motor, mission, or flight authority.
- Normal author checks passed: 20 focused backend tests, Ruff, mypy, 62 focused UI
  tests, targeted ESLint, UI typecheck, and the production UI build.
- Published managed UI release `release-ca6aa2d0e52549c4bbcda890aca108d1`
  and exercised the served workflow on port 3001. Digital twin showed `SHADOW`,
  configured label `Drone#1 - Nike`, `1 observed`, no simulation mission/fleet/control
  surfaces, no implicit connection, and a successful return to Simulation.
- Final observer state is `DISCONNECTED`; changed-code hardware evidence remains
  `NOT_RUN`. The operator explicitly chose the fast feedback loop, so no independent
  implementation gate was run. Operator behavioral review is the next step.

<!-- WP87-88-DESIGN-PAYLOAD-BEGIN -->

## WP-87 and WP-88 — Digital Twin flight safety and basic-flight laboratory

This related pair is one design-review unit but preserves two responsibility owners.
WP-87 is the separately requested flight-safety packet. WP-88 is the Digital Twin
Campaign Laboratory and its first one-drone mission cluster. A mission may depend on
WP-87, but no mission definition, catalog selection, browser state, or calibration
candidate may implement or relax WP-87 safety authority.

### Frozen originating request

> Design and independently verify a separate flight-safety packet covering arming,
> limits, containment, abort, landing, and emergency behavior.
>
> i thik i already did tell you this but now again, same as simulation where it is
> structured in different campaign laboratory and you can choose different clusters
> here as well just for digital twin
>
> so know mission cluster 1 should be basic behavior like takeoff, arming whatver you
> think as next step if drone has never flown before, checking beahvior at different
> battery levels, checking flight hover stability, sensor drift, implement calibration
> pipeline of sensors bla bla but only that not use any sensors just basic flight
> missions like spinning motors 30%, 40%, ..., takeoff to set distance keep that
> distacne for x seconds, in another move forward backward, spin around, do a circle
> whatever build up, imagine which missions could be implemented there

Design interpretation: “only that not use any sensors” means Cluster 1 adds no
perception, obstacle, ranging, sensor-drift, or calibration experiment. Physical
flight still requires source-qualified position/height, attitude, battery, link, and
firmware-supervisor observations for safety; unavailable safety observations block
flight instead of being bypassed. The cluster records those observations but does not
turn them into a sensor mission or automatically tune a model.

Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.

Ledger preimage before this payload: SHA-256
`39a90e2d66b7a520e61e791d1388195e3013f506b190154441576ac2d0e99776`.

### Intent/value card

- **Minimum useful outcome:** Digital twin has a selectable Campaign Laboratory whose
  first cluster teaches one never-flown Crazyflie from ground authority through
  takeoff, hover, basic translation, yaw, simple shapes, battery behavior, and safety
  drills, while every propeller-capable action remains blocked by one separate,
  non-bypassable flight-safety authority.
- **Explicitly requested:** separate arming/limits/containment/abort/landing/emergency
  design; Digital twin-only cluster selection; first-flight basics; bounded motor,
  takeoff/hold, forward/back, turn, circle, hover-stability, and battery cases.
- **Necessary prerequisites:** exact paired identity; qualified command-capable
  Crazyflie adapter; source-qualified safety telemetry; current bench and flight-entry
  records; one-shot permit; operator and observer; approved physical containment;
  onboard emergency-stop watchdog; immutable case/plan/evidence identity; and normal
  API/Play-path integration.
- **Optional experiments:** a direct 30% or 40% collective props-off diagnostic and
  low-but-admissible battery comparison. They remain disabled until their additional
  gates pass and do not block ordinary official motor diagnostics or high/mid battery
  basics.
- **Non-goals:** perception or obstacle missions, sensor drift qualification,
  autonomous calibration or promotion, arbitrary PWM controls, physical battery
  override/deep discharge, multi-drone flight, outdoor flight, dynamic replanning,
  payload tests, or physical-accuracy claims from Fast Sim.
- **Safe fallback:** retain the current observation-only Digital twin projection and
  preparation-only catalog. No radio, command, motor, or flight action is authorized
  by this design review.

### Current production trace and claim boundary

The current served path selects Digital twin in `ControlCenter.tsx`, calls only the
authenticated `/api/v1/physical-twin/*` observation service, and deliberately keeps
the private observer outside `ApplicationRuntime.vehicles` and `SafetySupervisor`.
Both mission and campaign Play return an observation-only lock message. The existing
Crazyflie adapter can translate arm, takeoff, hover, move, land, abort, and emergency
payloads, but its observation-only instance rejects permits and commands. In the
current adapter, `_require_permit()` runs before the emergency payload is classified,
so emergency stop does not yet provide the permit-independent safety preemption this
packet requires. There is no Digital Twin campaign execution entry point.

The accepted implementation must trace:

`served Digital twin selection -> exact case/variant -> immutable plan and one-shot permit -> campaign/mission execution owner -> SafetySupervisor + WP-87 flight authority -> command-capable Crazyflie adapter -> pinned link -> source-qualified observations -> recorder/export/evaluator -> Campaign Review`.

The official Crazyflie supervisor contract says emergency stop immediately stops all
motors, is latching until reboot, and sends no response. Evidence therefore separates
host dispatch from a later observed supervisor state; it never fabricates an
acknowledgement. The onboard watchdog is activated for every command-capable session.
The official commander supplies smooth takeoff/go-to/land trajectories and its
watchdog behavior remains authoritative. The official motor self-test is preferred;
direct ratios are not treated as normal flight profiles.

Primary references:

- [Bitcraze supervisor CRTP contract](https://www.bitcraze.io/documentation/repository/crazyflie-firmware/master/functional-areas/crtp/crtp_supervisor/)
- [Bitcraze commander framework](https://www.bitcraze.io/documentation/repository/crazyflie-firmware/master/functional-areas/sensor-to-control/commanders_setpoints/)
- [Bitcraze cflib supervisor API](https://www.bitcraze.io/documentation/repository/crazyflie-lib-python/master/api/cflib/crazyflie/supervisor/)
- [Bitcraze Flow deck first-flight guidance](https://www.bitcraze.io/documentation/tutorials/getting-started-with-flow-deck/)

### Packet state and dependency order

| Packet | Status | Independent verification | Depends on | Owner and value |
| --- | --- | --- | --- | --- |
| WP-87 — non-bypassable Digital Twin flight safety | `PLANNED` | `DRAFT_UNVERIFIED` | accepted WP-71–75 design; implemented WP-80/WP-86 observation boundary | Safety supervisor, physical flight authority, permits, adapter/link, evidence, and always-available operator safety actions. |
| WP-88 — Digital Twin Campaign Laboratory, Cluster 1 | `PLANNED` | `DRAFT_UNVERIFIED` | WP-87 `IMPLEMENTATION_VERIFIED` plus retained hardware/permit gates | Twin-specific cluster catalog and staged one-drone basic-flight learning cases using the normal mission/evidence pipeline. |

This request is design-only. Implementation must start with WP-87 and obtain a fresh
implementation verdict before WP-88 may send any physical command. Catalog structure
may be implemented preparation-only earlier, but Play remains locked.

### WP-87 — non-bypassable Digital Twin flight safety

WP-87 owns arming, hard limits, containment, abort, landing, emergency behavior,
permit lifecycle, safety audit, and the server-side authority behind visible controls.
Its rules apply independently of the selected case.

1. **Arming.** Connect, identity verification, observation, preflight, permit issue,
   and arm are separate states. Arm requires the exact pinned vehicle/session, a
   fresh approved preflight, firmware `canBeArmed`/`canFly` truth as applicable,
   landed/not-flying state, valid positioning, battery/link/health gates, operator and
   observer presence, containment, and an unconsumed one-shot case-bound permit. Arm
   is followed immediately by its bounded action or disarm; there is no indefinite
   armed idle state or browser-only authority.
2. **Limits.** The permit freezes requested and safety-resolved altitude, horizontal
   extent, speed, vertical rate, yaw rate, acceleration, duration, battery reserve,
   observation freshness, watchdog, landing region, and allowed command kinds. A
   mission may tighten but never relax them. Cluster 1 commands stay at or below
   `0.40 m` height, `0.15 m/s` horizontal speed, `0.20 m/s` vertical speed,
   `30 deg/s` yaw rate, `0.50 m/s²` acceleration, and `45 s` airborne duration; lower
   measured limits win.
3. **Containment.** A permit binds an inspected physical containment/exclusion volume,
   launch point, conservative vehicle swept radius, localization uncertainty, warning
   center radius, hard center radius, observer, and stop criteria. The initial
   horizontal contract uses a `0.10 m` commanded route radius, `0.20 m` warning center
   radius, `0.35 m` hard center radius, and `0.50 m` physical containment radius.
   Boundary prediction triggers supervised braking/hold/land before the hard radius;
   a missing certificate blocks arming or escalates an active flight.
4. **Abort.** Abort is a distinct supervisor-owned action that preempts mission/fleet
   ownership, atomically cancels undispatched future commands, and performs a bounded
   controlled landing only while link, estimator, height, landing region, and command
   outcome remain trustworthy. It never reports mission success.
5. **Landing.** Normal and aborted landing use an immutable landing goal region.
   Descent starts only after fresh capture and speed checks; accepted X/Y is retained
   through descent, and disarm occurs only after observed landed/not-flying supervisor
   state. A command return alone is not touchdown evidence. If controlled landing can
   no longer be certified, emergency policy owns the next action.
6. **Emergency.** A permanent visible control and Space hotkey, enabled only for the
   deliberately hot exact physical session and suppressed in editable fields, invoke
   one immediate lowest-level motor cutoff without modal confirmation, mission lease,
   or ordinary permit dependency. Repeated keydown is deduplicated. Dispatch is
   recorded separately from later state because the firmware command has no response.
   The result is `EMERGENCY`, never successful landing, and the command-capable session
   remains locked until physical reboot and fresh observation/preflight.
7. **Battery.** Takeoff requires the maximum of configured minimum, mission energy plus
   reserve, and a physically validated voltage floor. Critical/reserve crossings stop
   useful work and request bounded landing. No physical run-anyway override exists.
8. **Priority and cleanup.** Emergency preempts containment/abort; containment and
   critical health preempt mission behavior; abort/land preempts useful work. Browser,
   API task, adapter, link, or recorder failure cannot leave future commands, permits,
   leases, or watchdog state live. Restart returns observation-only.

An airborne emergency cut is not a success test and is never intentionally required.
Props-off dispatch/watchdog evidence and controlled failure injection prove the
software path; the operator retains real emergency authority during every flight.

### WP-88 — Digital Twin Campaign Laboratory and Cluster 1

Digital twin receives its own catalog source and the same numbered preparation
hierarchy used in Simulation:

1. `Mission cluster`
2. `Major mission`
3. `Variant`
4. `Motion`

The initial catalog exposes exactly one real cluster, `Basic flight commissioning`.
Future clusters appear only when they contain behaviorally admitted cases; no empty
sensor/calibration placeholders are created. Simulation selections never leak into
Digital twin. Selecting a Twin case binds its first descendant immediately, but Play
is absent/locked until WP-87 and all case prerequisites pass. The default surface
shows the next safe step and exact blocking gate; hashes, permits, and raw evidence
stay in technical detail. Abort/land and emergency remain outside the catalog and
visible whenever physical controls are hot.

Cluster 1 progression is manual and one drone only:

- **Stage 0 — Ground checks:** props-off arm/disarm and official motor sequence.
  Requested 30% and 40% collective steps are listed but disabled until exact motor
  command semantics, current/thermal bounds, props-removed restraint, and a calibrated
  mapping all pass. No generic PWM slider is added.
- **Stage 1 — First lift:** take off to `0.30 m`, hold `3 s`, land at origin; repeat as
  separately initiated trials before promotion. Negative start-battery and containment
  admission cases must reject before arm.
- **Stage 2 — Hover and abort:** hold `0.30 m` for `10 s`, then `30 s`; measure drift,
  speed, attitude/body-rate activity, motor balance/headroom, energy, and landing.
  Execute a controlled abort-from-hover drill. These are vehicle-behavior metrics, not
  sensor-calibration missions.
- **Stage 3 — One-axis motion:** bounded vertical step, `0.10 m` +X out/back, `0.10 m`
  +Y out/back, and `+30/-30 deg` yaw return.
- **Stage 4 — Combined basics:** slow `360 deg` yaw, `0.10 m` square, and `0.10 m`
  radius circle only after their one-axis primitives pass. The circle is a smooth
  continuous route, not stop-and-go waypoints.

The same hover case is compared across naturally observed battery bands: `HIGH`
(`>=75%`), `MID` (`>=50%` and `<75%`), `LOW_ALLOWED` (derived admission floor through
`<50%`), and `REJECTED` (below the derived floor). Battery is run/environment truth,
not a cloned mission identity. Every band retains raw voltage, reported percentage,
load/current when available, start/minimum/end values, and the derived admission
floor. No physical “set battery” control, run-anyway bypass, or intentional deep
discharge is permitted.

### Core claim and exit-evidence matrix

| Claim | Real trigger / production path | Retained observation | Independent oracle | Failure / counterexample | Boundary |
| --- | --- | --- | --- | --- | --- |
| Non-bypassable safety | Served Play or safety action -> API -> flight authority -> supervisor -> adapter/link | permit, state, command/dispatch, telemetry, watchdog, terminal audit | independent state/geometry/clock reconstruction plus link spy | stale/mismatched/expired permit; browser loss; active lease; missing telemetry | `PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME` |
| Twin cluster hierarchy | Served Digital twin selector -> twin catalog API -> exact cluster/major/variant binding | selected source, case/hash, lifecycle, prerequisite block | DOM/API set equality and renamed/reordered fixture | Simulation selection or unavailable cluster leaks into Twin | `PRODUCTION_ENTRY / NO_RUNTIME / NOT_APPLICABLE` |
| Basic progression | Served Twin Play -> canonical case -> WP-87 -> hardware -> evidence/review | case/permit/plan hashes, commands, telemetry, outcome, promotion state | independent route/time/terminal reconstruction | child/renamed case, skipped prerequisite, wrong axis, or premature promotion | `PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME` |
| Battery comparison | Same hover case selected under observed start band | voltage/percent/source, start/min/end, energy, dynamics, terminal result | independent band/floor recomputation and per-run guard vector | forced percentage, below-floor start, or average hiding a failed repeat | `PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME` |
| Props-off diagnostics | Served Stage 0 action -> bench permit -> supervisor -> adapter official diagnostic | attestations, command mapping, current/thermal evidence, motor result | link spy plus raw firmware variables and physical restraint record | props installed, no restraint, arbitrary ratio, stale attestation | `PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME` |
| Served safety controls | Hot physical session -> visible control/Space/Enter -> authenticated server safety action | focus/session identity, dispatch clock, later observed state | browser event plus monotonic link trace | editable focus, key repeat, modal/lease delay, stale session | `PRODUCTION_ENTRY / HARDWARE / OBSERVED_REALTIME` |

### Numerical pre-freeze witness

The machine contract below freezes the design arithmetic, not measured aircraft
qualification. At `0.15 m/s`, a `0.25 s` complete response budget and `0.50 m/s²`
minimum certified deceleration require `0.060 m`, below the `0.15 m` warning-to-hard
center interval. A `0.90 s` response requires `0.1575 m` and fails. The nominal
`0.10 m` route plus `0.10 m` swept radius and `0.05 m` uncertainty occupies `0.25 m`,
inside the `0.50 m` physical containment. The `0.40 m` maximum command plus `0.05 m`
overshoot and `0.05 m` height uncertainty reaches the `0.50 m` hard height exactly;
`0.41 m` is rejected. These authored budgets must be replaced by equal-or-tighter
measured evidence at implementation/physical entry; missing deceleration, timing,
geometry, or uncertainty evidence blocks flight.

<!-- WP87-88-MACHINE-CONTRACT-BEGIN -->

```json
{
  "packets": [
    {"packet_id": "WP-87", "depends_on": []},
    {"packet_id": "WP-88", "depends_on": ["WP-87"]}
  ],
  "guard_registry": [
    {"category": "arming", "metric": "exact state/identity/preflight/permit conjunction", "pass_relation": "all required fields current and exact before arm", "isolated_failure": "expired case-bound permit produces zero arm dispatch"},
    {"category": "battery", "metric": "observed start percent/voltage versus derived admission floor", "pass_relation": "start >= max(configured minimum, mission need + reserve, validated voltage floor)", "isolated_failure": "one value immediately below the derived floor rejects before arm"},
    {"category": "flight_limits", "metric": "raw and reconstructed altitude/speed/rate/acceleration/duration extrema", "pass_relation": "every raw and reconstructed maximum <= frozen resolved limit", "isolated_failure": "one 0.41 m command exceeds the 0.40 m Cluster 1 command cap"},
    {"category": "containment", "metric": "continuous protected occupancy and stopping reach versus physical and hard bounds", "pass_relation": "protected occupancy <= physical bound and certified stopping reach < warning-to-hard interval", "isolated_failure": "0.90 s response budget exceeds the warning-to-hard interval"},
    {"category": "abort", "metric": "preemption-to-future-cancel and controlled terminal trace", "pass_relation": "no superseded command dispatch and observed landed/disarmed terminal state", "isolated_failure": "missing landing observation prevents ordinary abort completion"},
    {"category": "landing", "metric": "capture interval, descent target, terminal membership/speed/state/contact", "pass_relation": "fresh capture through observed landed/not-flying and disarmed terminal state", "isolated_failure": "command completion without landed telemetry remains incomplete"},
    {"category": "emergency", "metric": "hot-session input-to-lowest-level dispatch and later observed latch", "pass_relation": "one immediate dispatch independent of lease/ordinary permit; no fabricated acknowledgement", "isolated_failure": "editable focus/repeat is suppressed while a valid Space press still dispatches once"}
  ],
  "mission_inventory": [
    {"key": "ground.arm_disarm_props_off", "major": "Ground checks", "stage": 0, "prerequisites": [], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can exact physical authority arm then disarm without lift or stale authority?", "oracle": "supervisor state changes and zero flight command/airborne observation", "enablement_gates": ["props_removed", "restrained", "bench_permit"]},
    {"key": "ground.official_motor_sequence_props_off", "major": "Ground checks", "stage": 0, "prerequisites": [], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Does the official bounded motor sequence preserve identity/order and return disarmed?", "oracle": "firmware result plus per-motor raw evidence and terminal disarm", "enablement_gates": ["props_removed", "restrained", "official_interface"]},
    {"key": "ground.collective_30_percent_props_off", "major": "Ground checks", "stage": 1, "prerequisites": ["ground.official_motor_sequence_props_off"], "disposition": "PLANNED_NOT_EXECUTABLE", "causal_question": "Does a calibrated 30 percent bench command remain bounded and symmetric?", "oracle": "independent current/thermal/motor comparison under exact mapping", "enablement_gates": ["props_removed", "restrained", "calibrated_mapping", "current_thermal_bound"]},
    {"key": "ground.collective_40_percent_props_off", "major": "Ground checks", "stage": 2, "prerequisites": ["ground.collective_30_percent_props_off"], "disposition": "PLANNED_NOT_EXECUTABLE", "causal_question": "Does a calibrated 40 percent bench command add a distinct bounded load point?", "oracle": "independent current/thermal/motor comparison and 30-to-40 response delta", "enablement_gates": ["props_removed", "restrained", "calibrated_mapping", "current_thermal_bound"]},
    {"key": "takeoff.takeoff_0_30_hold_3_land", "major": "Takeoff and landing", "stage": 1, "prerequisites": ["ground.arm_disarm_props_off", "ground.official_motor_sequence_props_off"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can the never-flown vehicle lift vertically, hold 0.30 m, and land at origin?", "oracle": "independent altitude/time/containment/landing reconstruction", "enablement_gates": ["contained_flight_permit", "observer", "watchdog"]},
    {"key": "hover.hover_0_30_10", "major": "Hover", "stage": 2, "prerequisites": ["takeoff.takeoff_0_30_hold_3_land"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Is 10 second hover stable within the first-flight envelope?", "oracle": "drift/speed/attitude/body-rate/motor/energy/landing guard vector", "enablement_gates": ["three_first_lift_passes"]},
    {"key": "hover.hover_0_30_30", "major": "Hover", "stage": 3, "prerequisites": ["hover.hover_0_30_10"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Does stability persist for 30 seconds without hiding a failed repeat?", "oracle": "per-repeat hover guard vector and time-window comparison", "enablement_gates": ["two_hover_10_passes"]},
    {"key": "vertical.vertical_step_0_30_0_40_0_30", "major": "Vertical motion", "stage": 3, "prerequisites": ["hover.hover_0_30_10"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can the vehicle make one bounded vertical step and return without overshoot?", "oracle": "independent Z/rate/settling/headroom reconstruction", "enablement_gates": ["hover_10_qualified"]},
    {"key": "translation.x_out_back_0_10", "major": "Translation", "stage": 3, "prerequisites": ["hover.hover_0_30_10"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can the vehicle move +X 0.10 m and return to origin?", "oracle": "signed HOME-frame displacement and landing reconstruction", "enablement_gates": ["hover_10_qualified"]},
    {"key": "translation.y_out_back_0_10", "major": "Translation", "stage": 3, "prerequisites": ["hover.hover_0_30_10"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can the vehicle move +Y 0.10 m and return to origin?", "oracle": "signed HOME-frame displacement and landing reconstruction", "enablement_gates": ["hover_10_qualified"]},
    {"key": "turn.yaw_plus_minus_30", "major": "Turn", "stage": 3, "prerequisites": ["hover.hover_0_30_10"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can yaw move +30 then -30 degrees while position remains bounded?", "oracle": "unwrapped yaw, yaw rate, position drift, and landing reconstruction", "enablement_gates": ["hover_10_qualified"]},
    {"key": "turn.yaw_full_360_slow", "major": "Turn", "stage": 4, "prerequisites": ["turn.yaw_plus_minus_30"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can one slow complete turn preserve hover and yaw continuity?", "oracle": "unwrapped 360 degree progress without modulo shortcut plus drift guard", "enablement_gates": ["yaw_30_qualified"]},
    {"key": "shape.square_side_0_10", "major": "Shapes", "stage": 4, "prerequisites": ["translation.x_out_back_0_10", "translation.y_out_back_0_10"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can two qualified axes compose into a bounded square and return?", "oracle": "ordered corner regions, containment, return, and landing reconstruction", "enablement_gates": ["x_y_translation_qualified"]},
    {"key": "shape.circle_radius_0_10", "major": "Shapes", "stage": 4, "prerequisites": ["translation.x_out_back_0_10", "translation.y_out_back_0_10", "turn.yaw_plus_minus_30"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Can the vehicle follow one continuous 0.10 m radius circle without waypoint stops?", "oracle": "independent radial error, continuity, speed, containment, return, and landing reconstruction", "enablement_gates": ["x_y_yaw_qualified"]},
    {"key": "battery.start_below_admission_reject", "major": "Battery behavior", "stage": 1, "prerequisites": ["ground.arm_disarm_props_off"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Does an observed below-floor battery block flight before arm?", "oracle": "independent floor recomputation and zero arm/takeoff dispatch", "enablement_gates": ["observed_battery_truth"]},
    {"key": "safety.controlled_abort_from_hover", "major": "Safety drills", "stage": 2, "prerequisites": ["takeoff.takeoff_0_30_hold_3_land"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Does controlled abort cancel future work and land while state remains healthy?", "oracle": "link dispatch trace plus independent landing/terminal reconstruction", "enablement_gates": ["contained_flight_permit", "landing_state_healthy"]},
    {"key": "safety.containment_boundary_reject", "major": "Safety drills", "stage": 1, "prerequisites": ["ground.arm_disarm_props_off"], "disposition": "EXECUTABLE_AFTER_GATE", "causal_question": "Does a plan outside protected containment reject before arm?", "oracle": "independent protected-occupancy calculation and zero command dispatch", "enablement_gates": ["containment_contract"]}
  ],
  "battery_policy": {
    "bands": ["HIGH", "MID", "LOW_ALLOWED", "REJECTED"],
    "physical_override_allowed": false,
    "case_identity_rule": "same_case_grouped_by_observed_start_band"
  },
  "sensor_scope": {
    "perception_missions": false,
    "automatic_calibration": false,
    "required_safety_observations": ["position_height", "attitude", "battery", "link", "firmware_supervisor"]
  },
  "claims": [
    {"claim_id": "non_bypassable_flight_safety", "boundary": "PRODUCTION_ENTRY", "environment": "HARDWARE", "clock": "OBSERVED_REALTIME", "trigger": "served Play, abort, land, or emergency action", "effect": "server flight authority admits, preempts, lands, or cuts motors", "observation": "permit/state/dispatch/watchdog/telemetry/terminal audit", "oracle": "independent state geometry and clock reconstruction plus link spy", "counterexample": "expired or mismatched permit, active lease, stale telemetry, and browser loss"},
    {"claim_id": "digital_twin_cluster_hierarchy", "boundary": "PRODUCTION_ENTRY", "environment": "NO_RUNTIME", "clock": "NOT_APPLICABLE", "trigger": "served Digital twin selection and catalog load", "effect": "Twin-specific cluster/major/variant hierarchy binds exact case", "observation": "API and DOM selection identities and locked Play state", "oracle": "catalog-to-DOM set equality", "counterexample": "renamed/reordered Simulation selection cannot leak"},
    {"claim_id": "basic_flight_progression", "boundary": "PRODUCTION_ENTRY", "environment": "HARDWARE", "clock": "OBSERVED_REALTIME", "trigger": "served Twin case Play after gates", "effect": "one bounded canonical intent executes through WP-87", "observation": "case/plan/permit/command/telemetry/outcome/promotion identities", "oracle": "independent route time terminal reconstruction", "counterexample": "skipped prerequisite, wrong axis, renamed child, or premature promotion"},
    {"claim_id": "battery_band_comparison", "boundary": "PRODUCTION_ENTRY", "environment": "HARDWARE", "clock": "OBSERVED_REALTIME", "trigger": "same hover case under naturally observed start battery", "effect": "run is admitted/rejected and grouped without changing case identity", "observation": "voltage/percent/source/start/min/end/energy/terminal result", "oracle": "independent band and admission-floor recomputation", "counterexample": "forced battery value, below-floor start, or failed repeat hidden by average"},
    {"claim_id": "props_off_motor_diagnostics", "boundary": "PRODUCTION_ENTRY", "environment": "HARDWARE", "clock": "OBSERVED_REALTIME", "trigger": "served Stage 0 action under bench permit", "effect": "official diagnostic executes or optional ratio stays blocked", "observation": "attestations/mapping/raw motor/current/thermal/result/disarm", "oracle": "link spy and raw firmware variable comparison", "counterexample": "props installed, no restraint, stale attestation, or uncalibrated ratio"},
    {"claim_id": "served_safety_controls", "boundary": "PRODUCTION_ENTRY", "environment": "HARDWARE", "clock": "OBSERVED_REALTIME", "trigger": "visible control or valid Space/Enter input in hot session", "effect": "immediate emergency dispatch or supervised abort/land", "observation": "focus/session/input/dispatch and later state clocks", "oracle": "browser event trace correlated with monotonic link trace", "counterexample": "editable focus, repeat, modal delay, lease conflict, or stale session"}
  ],
  "numerical_witness": {
    "horizontal": {
      "route_center_radius_m": 0.10,
      "warning_center_radius_m": 0.20,
      "hard_center_radius_m": 0.35,
      "physical_containment_radius_m": 0.50,
      "vehicle_swept_radius_m": 0.10,
      "position_uncertainty_m": 0.05,
      "maximum_speed_m_s": 0.15,
      "response_budget_s": 0.25,
      "late_response_budget_s": 0.90,
      "minimum_deceleration_m_s2": 0.50,
      "expected_nominal_protected_radius_m": 0.25
    },
    "vertical": {
      "maximum_commanded_height_m": 0.40,
      "overshoot_budget_m": 0.05,
      "height_uncertainty_m": 0.05,
      "hard_height_m": 0.50,
      "perturbed_commanded_height_m": 0.41
    },
    "battery": {
      "configured_takeoff_minimum_percent": 30.0,
      "mission_need_percent": 15.0,
      "reserve_percent": 20.0,
      "validated_voltage_floor_as_percent": 40.0,
      "passing_start_percent": 55.0,
      "failing_start_percent": 39.9
    }
  }
}
```

<!-- WP87-88-MACHINE-CONTRACT-END -->

### Affected boundaries and implementation ownership

The pre-freeze audit recursively discovers the Python and UI production closure from
the API, campaign, observer, safety, adapter, recorder, Campaign Lab, Control Center,
and API-client entry points. It additionally binds the routed requirements, safety and
landing contracts, system/design maps, generated OpenAPI pair, focused API/campaign/
hardware/safety/UI tests, existing real mirror catalog, and intended new physical
catalog/authority/test paths. Implementation must update `docs/system/README.md`
because it introduces a flight-authority owner and public Digital Twin campaign
transit, and must update `design.md`/`docs/project/DESIGN.md` because Twin-specific
cluster selection plus always-available physical safety controls are durable surface
patterns.

The retained audit command is:

`./.venv/bin/python scripts/audit_wp87_88_design.py`

Its artifact is
`missions/campaigns/real/qualification/wp87-88-design-audit-v1.json`. The artifact
binds every current preimage by exact hash, every intended new path as absent, the
payload hash, the source-derived guard coverage, exact mission/claim sets, dependency
order, generated outputs, and isolated numerical failures. An implementation manifest
must reconcile this discovered set rather than naming “the dirty diff.”

### Measurable exit gates

WP-87 exits only when:

1. Normal served Play and every safety action traverse the production API, exact
   flight authority, SafetySupervisor, command-capable adapter, link, and retained
   evidence path with no observer-ID or generic vehicle-route bypass.
2. Each arming, battery, limit, containment, abort, landing, emergency, cleanup, and
   priority guard has intended, isolated failure, and boundary evidence. No command is
   sent for stale/missing/mismatched identity, permit, telemetry, geometry, or battery.
3. Emergency is one permit/lease-independent lowest-level dispatch, has no fabricated
   acknowledgement, latches session state until reboot, and remains available while
   every ordinary command path is blocked or busy.
4. Controlled abort cancels future commands and either reaches observed landed/
   disarmed state or truthfully escalates; normal landing satisfies the frozen landing
   region contract through terminal observation.
5. Props-off, controlled-fake, and Fast Sim evidence may verify software paths, but
   real command/flight claims remain `NOT_RUN` until authorized hardware evidence is
   retained. Source check, tests, and a design-verdict do not authorize flight.

WP-88 exits only when:

1. Digital twin shows the exact four-level hierarchy and only behaviorally admitted
   Twin clusters; Simulation state cannot leak, and Play is locked with the exact
   prerequisite reason until WP-87 and case gates pass.
2. All 17 inventory rows exist exactly once. The 30%/40% rows remain disabled until
   their four additional gates pass; no arbitrary motor/PWM UI exists.
3. Every enabled case executes the same backend-neutral intent through the normal
   production path and retains independent geometry/time/terminal evidence plus its
   declared negative/renamed/reordered/boundary case.
4. Progression is manual, dependency-ordered, and based on per-repeat evidence. One
   pass, an average, a Simulation run, or a battery-band label cannot promote a later
   hardware stage.
5. Hover battery comparison reuses one immutable case across naturally observed
   bands, retains raw source values, and rejects below-floor starts with zero arm/
   takeoff dispatch. No physical battery override exists.
6. Served desktop/narrow, loading, empty, blocked, paired, hot-control, failure,
   keyboard/focus, and reduced-motion states pass `design.md`; exact served release,
   API, and assets are bound before rendered evidence.

### Implementation and verification order

1. This design gate reviews WP-87 and WP-88 together for scope and dependency truth.
2. Implementation begins only on explicit request, with WP-87. The implementation
   author must freeze exact pre/post hashes, evidence, production traces, and physical
   `NOT_RUN` limits, then use a fresh implementation verifier.
3. WP-88 may implement its preparation-only catalog while flight remains locked, but
   no command-capable Play route may merge or deploy before WP-87 receives
   `IMPLEMENTATION_VERIFIED` and the hardware permit prerequisites are actually met.
4. Physical actions require explicit later operator authorization and present
   hardware. Design verification is not flight authorization.

<!-- WP87-88-DESIGN-PAYLOAD-END -->

### WP-87 and WP-88 design-review handoff

- Status: `PLANNED`.
- Independent verification: `DRAFT_UNVERIFIED`.
- Design audit/reviewer identity and verdict are recorded outside the immutable
  payload so the verifier can reproduce the payload hash without self-reference.

### WP-87 and WP-88 initial independent review

- Reviewer: `/root/wp87_88_design_verifier`.
- Initial payload: 35,197 bytes; SHA-256
  `8b5a1cb6a0241395b3b63a176aac36a42169621aad716b3e98ce73bc21c0537b`.
- Initial audit artifact: SHA-256
  `78cfdd69628cf44a92f5496e23617a59a335972b5274d5f2b84e3e82987971e9`;
  authored audit reported zero errors across 152 boundaries, seven guard categories,
  17 mission rows, and six claims.
- Verdict: `BLOCKED_WITH_FINDINGS`; two P0 and five P1 `MUST_FIX_NOW` findings.
- P0 scope: strict-margin containment/landing/stopping evidence and exact emergency/
  watchdog timing/lifecycle.
- P1 scope: blocked-predecessor dependency, guard-vector completeness, exact catalog
  hierarchy/progression, real serving-boundary closure, and preimage/cost record.
- Review count: `1`; correction count before R1: `0`; focused recheck count: `0`.

<!-- WP87-88-R1-DESIGN-PAYLOAD-BEGIN -->

## WP-87 and WP-88 R1 — consolidated safety-oracle and catalog correction

This is the sole permitted consolidated design correction. It is authoritative over
every conflicting threshold, dependency, catalog stage/key, oracle, and claim in the
initial payload. The original request, intent/value card, non-goals, observation-only
safe fallback, packet split, and design-only stop remain unchanged.

### Blocked predecessor and corrective retrospective

WP-71 through WP-75 did **not** produce an accepted design. Their final state is
`REVIEW_BLOCKED / BLOCKED_WITH_FINDINGS`, with `WP71-75-DES-002` (self-certified
emergency/flight-envelope arithmetic) and `WP71-75-DES-006` (non-transitive boundary
closure) unresolved. The current operator request explicitly authorizes WP-87/WP-88
as a successor. WP-87 supersedes only the blocked safety, physical-command, and basic
physical-curriculum scope of WP-71–75; it does not upgrade those packets.

The reusable failure modes are already codified by `REQ-WFL-047`, `REQ-WFL-048`, and
`REQ-WFL-049`: derive the production transit from real roots, freeze exact
clock/geometry/certificate vectors, and derive every guard metric independently of its
registry. R1 applies those requirements directly. WP-80 remains an observation-only
implementation with `BLOCKED_WITH_FINDINGS` at its implementation gate. WP-86 is a
`DESIGN_VERIFIED`, fast-loop `IMPLEMENTED_UNVERIFIED` observation/presentation
successor. Neither supplies flight authority, motor authority, physical landing
evidence, or changed-code hardware qualification. WP-87 depends only on the currently
implemented observation boundary as an unverified integration preimage; it must
independently verify every new command/safety transit.

### Strict physical containment and landing contract

Cluster 1 flight is confined to an inspected **netted cylindrical enclosure**, not a
software geofence plus an open exclusion zone. Its measured inner usable volume is a
HOME-frame cylinder of radius `0.50 m`, from the launch floor `z=0` to `z=0.60 m`.
The conservative vehicle swept envelope is a cylinder of radius `0.10 m` and vertical
half-height `0.05 m`; position and height uncertainty are each `0.03 m`. A separately
identified observer signs the measurement method, dimensions, timestamp, enclosure
identity, launch-center mark, photo/video hash, and clear-volume inspection. Without
that independent cage record, every props-on case is `BLOCKED`.

The commanded center path remains within radius `0.10 m`. The warning center radius
is `0.18 m`; the hard estimated-center radius is `0.34 m`. At the hard radius, vehicle
envelope plus uncertainty reaches `0.47 m`, retaining a strict `0.03 m` radial margin
inside the physical net. The maximum commanded height is corrected from `0.40 m` to
`0.35 m`. With `0.03 m` overshoot, `0.03 m` uncertainty, and `0.05 m` vehicle
half-height, protected occupancy reaches `0.46 m`, leaving a strict `0.14 m` physical
ceiling margin. The hard estimated-center height is `0.45 m`; a `0.41 m` commanded
target fails the `0.35 m` command cap even though it does not touch the cage.

The Fast-Sim-only landing-goal-region contract remains a planning/evidence precedent,
not physical contact proof. Implementation must add
`docs/reference/PHYSICAL_LANDING_TERMINAL_V1.md` and its typed record. Physical
terminal success requires one closed source-clock descent interval, fresh range and
state capture, raw firmware `isArmed=false` and `isFlying=false`, downward range at or
below `0.05 m`, an independent observer record that the aircraft is settled on the
enclosure floor/landing mat, and no simulated-contact field. Without an external
position reference, the result is a functional contained-flight baseline only; it
does not qualify centimeter landing accuracy, tracking truth, or digital-twin model
accuracy.

### Full clock, jerk, response, and certificate witness

The complete worst-case source-to-command-effect budget is `0.22 s`: source sampling
`0.10`, source-to-receive `0.03`, freshness validation `0.02`, Safety Kernel compute
`0.01`, host dispatch `0.02`, radio transport `0.02`, and firmware apply `0.02`.
Admission allows at most `0.25 s`, retaining `0.03 s` budget reserve. These are design
limits to be met by measured evidence; any unavailable component blocks flight.

At `0.15 m/s`, minimum independently demonstrated deceleration `0.50 m/s²`, and
maximum jerk `2.0 m/s³`, deceleration ramps for `0.25 s`. Including the complete
`0.25 s` response delay, jerk ramp, and constant-deceleration tail gives a stopping
reach of approximately `0.07745 m`, strictly inside the `0.16 m` warning-to-hard
interval. A `0.90 s` late source gap produces approximately `0.17495 m` and fails.
At the warning threshold the accepted result is `STOP_AND_HOLD` only when the exact
hold set remains certified, followed by controlled landing after fresh recapture.
Missing/tampered pre-arm certificates reject with zero commands. Stale, late,
insufficient-clearance, or lost active-flight certificates invoke emergency stop
inside the physical cage; they never continue an uncertified prefix.

The numerical artifact freezes isolated nominal-warning, certified-land, stale,
tampered, late, insufficient-clearance, missing-certificate, and lost-certificate
vectors with exact resulting commands. It also freezes original/densified/simplified
circle and square geometry, renamed/reordered children, axis inversion, incompatible
child, and yaw-modulo counterexamples.

### Emergency and watchdog lifecycle

One valid hot-session emergency input must reach the lowest-level link call within
`0.100 s` on every one of `100` exact production-route software vectors; equality is
accepted only for that dispatch deadline. Firmware sends no response, so the event is
`DISPATCHED_UNCONFIRMED_REBOOT_REQUIRED` until a later raw state is observed. An
active lease, expired ordinary permit, busy mission, or recorder failure cannot delay
the link call. Editable focus and repeated keydown remain zero-dispatch cases.

The emergency watchdog begins with the first command-capable session keepalive, runs
on a monotonic owner outside the browser/mission task at `0.25 s`, budgets `0.10 s`
scheduler jitter and `0.10 s` link stall, and accepts only a maximum observed gap
strictly below `0.50 s`. The firmware timeout is `1.0 s`. A gap equal to `0.50 s` is a
failed margin vector; link/process loss deliberately lets the onboard timeout stop
motors and enters `LOCKED_REBOOT_REQUIRED`. Because the protocol exposes no disable,
even a normal command session continues keepalives through observed landing/disarm
and then ends as `REBOOT_REQUIRED_AFTER_COMMAND_SESSION`. No reconnect, new permit,
or observation-to-command promotion occurs until physical reboot and fresh identity,
observation, preflight, cage, operator, and observer checks.

### Exact Digital Twin catalog projection and progression

R1 freezes one catalog projection over exactly 17 rows. Every row has the same cluster
ID, one exact major ID, one exact variant ID, one exact motion ID, one stage enum/order,
an acyclic prerequisite set, repeat count, acceptance profile, and promotion rule.
The five stages are consistently `GROUND_CHECKS`, `FIRST_LIFT`,
`HOVER_AND_ABORT`, `ONE_AXIS`, and `COMBINED_BASICS`. The 30% and 40% collective rows
remain Ground checks but have repeat count zero and
`DISABLED_UNTIL_NEW_DESIGN`; their internal prerequisite order does not promote them
to later flight stages. The vertical mission is corrected to `0.30 -> 0.35 -> 0.30 m`
and receives a successor key; the initial `0.40 m` draft key is not implemented.

The accepted motion registry freezes HOME/BODY frame, route coordinates, dwell,
traversal, direction, and analytic shape identity. The square is centered on HOME with
five closed vertices at `(+/-0.05, +/-0.05, 0.30)`. The circle is the analytic HOME
circle centered `(0,0,0.30)`, radius `0.10 m`, one CCW turn, continuous fly-through;
32 samples are preview serialization only, and 16/32/64-sample evidence must agree
within the same analytic oracle. Full yaw uses unwrapped `+360 deg`; modulo-zero alone
cannot pass. Signed +X/+Y progress catches axis inversion.

Acceptance profiles freeze hover drift/RMS/speed/attitude/body-rate/motor thresholds,
translation/yaw/vertical progress and error, square/circle tube/radial/closure and
no-stop gates, landing, abort, and zero-dispatch negative cases. Every required repeat
must pass every guard; no mean or median hides a failed repeat. Promotion is manual
after all prerequisite repeats pass and no anomaly remains. Typed public stage,
repeat, sample-count, and emergency-vector fields reject booleans, integral/fractional
floats, strings, null, and out-of-range values.

Battery comparison names the immutable `hover.hover_0_30_10` case. It is descriptive,
not a promotion or physical-accuracy qualification: HIGH and MID each require two
safe passing runs; LOW_ALLOWED is optional and only above the derived floor plus the
`5%` start-margin guard; REJECTED is the zero-dispatch negative case. HIGH is the
frozen display comparator, all fixed inputs besides naturally observed battery are
identical, and every run is reported individually with deltas for hover position RMS,
drift, speed P95, attitude/body-rate activity, motor current/headroom/saturation,
energy, and landing. No between-band delta is declared “better” or “qualified” in
this packet.

### Complete guard and boundary closure

The R1 audit independently derives 45 metric IDs from the operator request,
requirements, claim/exit matrix, and cleanup priority. Its immutable specification
records category, exact direction/threshold, independent oracle, numeric tolerance,
per-repeat/aggregate semantics, one passing whole-repeat value, and one isolated
failure value per metric. The retained artifact contains the full specification and
computed pass/fail vector for each ID; the payload binds the exact registry identity
and ID set. Replacing any metric with prose, an implementation success flag, or an
unlisted metric changes the artifact or fails the audit.

Boundary discovery now starts from the actual `cli.py`, dashboard, dashboard service,
API app/runtime, UI `page.tsx`, layout, and worker roots, follows recursive Python and
UI imports, and unions independently derived safety, adapter/link, persistence,
export, analyzer/review, generator, test, requirements, and generated-output owners.
An independent claim-owner map requires every API/UI/safety/adapter/recorder/serving
transit to be present. It explicitly includes `ui/vite.config.ts`, the OpenAPI pair,
CSV export, storage, Campaign analyzer, and both catalog/OpenAPI generators. Removing
any root or owner fails set reconciliation before review.

<!-- WP87-88-R1-MACHINE-CONTRACT-BEGIN -->

```json
{
  "supersedes": ["WP-71", "WP-72", "WP-73", "WP-74", "WP-75"],
  "guard_registry_identity": "wp87-flight-safety-guard-registry-v2",
  "guard_metric_ids": [
    "identity_exact", "preflight_age_s", "permit_case_exact", "permit_unconsumed",
    "firmware_can_arm", "landed_disarmed_before_arm", "operator_observer_present",
    "position_observation_age_s", "battery_start_margin_percent",
    "battery_voltage_margin_v", "battery_terminal_reserve_percent",
    "maximum_height_m", "height_protected_margin_m",
    "maximum_horizontal_speed_m_s", "maximum_vertical_speed_m_s",
    "maximum_yaw_rate_rad_s", "maximum_acceleration_m_s2", "maximum_jerk_m_s3",
    "maximum_airborne_duration_s", "motor_saturation_count", "motor_current_margin_a",
    "nominal_physical_margin_m", "hard_physical_margin_m", "stopping_margin_m",
    "independent_containment_record_present", "abort_future_cancel_s",
    "superseded_dispatch_count", "abort_terminal_observed", "landing_capture_age_s",
    "terminal_height_m", "terminal_speed_m_s", "terminal_armed", "terminal_flying",
    "observer_settled", "simulated_contact_used", "emergency_input_to_link_s",
    "emergency_dispatch_count", "emergency_ack_claimed", "watchdog_max_gap_s",
    "reboot_required", "emergency_lease_independent", "live_permit_count",
    "live_lease_count", "pending_command_count", "restart_observation_only"
  ],
  "motion_registry_identity": "wp88-basic-flight-motion-registry-v2",
  "motion_ids": [
    "motion.no-command", "motion.arm-disarm", "motion.official-motor-sequence",
    "motion.collective-30", "motion.collective-40",
    "motion.takeoff-030-hold-3-land", "motion.hover-030-10", "motion.hover-030-30",
    "motion.vertical-030-035-030", "motion.x-out-back-010", "motion.y-out-back-010",
    "motion.yaw-plus-minus-30", "motion.yaw-360", "motion.square-side-010",
    "motion.circle-radius-010", "motion.abort-from-hover"
  ],
  "catalog_projection": [
    {"key": "ground.arm_disarm_props_off", "cluster_id": "basic-flight-commissioning", "major_id": "ground-checks", "variant_id": "arm-disarm-props-off", "motion_id": "motion.arm-disarm", "stage": "GROUND_CHECKS", "stage_order": 0, "prerequisites": [], "repeat_count": 3, "acceptance_profile": "acceptance.ground-authority", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "ground.official_motor_sequence_props_off", "cluster_id": "basic-flight-commissioning", "major_id": "ground-checks", "variant_id": "official-motor-sequence-props-off", "motion_id": "motion.official-motor-sequence", "stage": "GROUND_CHECKS", "stage_order": 0, "prerequisites": [], "repeat_count": 3, "acceptance_profile": "acceptance.ground-authority", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "ground.collective_30_percent_props_off", "cluster_id": "basic-flight-commissioning", "major_id": "ground-checks", "variant_id": "collective-30-percent-props-off", "motion_id": "motion.collective-30", "stage": "GROUND_CHECKS", "stage_order": 0, "prerequisites": ["ground.official_motor_sequence_props_off"], "repeat_count": 0, "acceptance_profile": "acceptance.disabled-collective", "promotion_rule": "DISABLED_UNTIL_NEW_DESIGN"},
    {"key": "ground.collective_40_percent_props_off", "cluster_id": "basic-flight-commissioning", "major_id": "ground-checks", "variant_id": "collective-40-percent-props-off", "motion_id": "motion.collective-40", "stage": "GROUND_CHECKS", "stage_order": 0, "prerequisites": ["ground.collective_30_percent_props_off"], "repeat_count": 0, "acceptance_profile": "acceptance.disabled-collective", "promotion_rule": "DISABLED_UNTIL_NEW_DESIGN"},
    {"key": "takeoff.takeoff_0_30_hold_3_land", "cluster_id": "basic-flight-commissioning", "major_id": "takeoff-and-landing", "variant_id": "takeoff-030-hold-3-land", "motion_id": "motion.takeoff-030-hold-3-land", "stage": "FIRST_LIFT", "stage_order": 1, "prerequisites": ["ground.arm_disarm_props_off", "ground.official_motor_sequence_props_off"], "repeat_count": 3, "acceptance_profile": "acceptance.first-lift", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "hover.hover_0_30_10", "cluster_id": "basic-flight-commissioning", "major_id": "hover", "variant_id": "hover-030-10", "motion_id": "motion.hover-030-10", "stage": "HOVER_AND_ABORT", "stage_order": 2, "prerequisites": ["takeoff.takeoff_0_30_hold_3_land"], "repeat_count": 2, "acceptance_profile": "acceptance.hover", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "hover.hover_0_30_30", "cluster_id": "basic-flight-commissioning", "major_id": "hover", "variant_id": "hover-030-30", "motion_id": "motion.hover-030-30", "stage": "HOVER_AND_ABORT", "stage_order": 2, "prerequisites": ["hover.hover_0_30_10"], "repeat_count": 2, "acceptance_profile": "acceptance.hover", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "vertical.vertical_step_0_30_0_35_0_30", "cluster_id": "basic-flight-commissioning", "major_id": "vertical-motion", "variant_id": "vertical-030-035-030", "motion_id": "motion.vertical-030-035-030", "stage": "ONE_AXIS", "stage_order": 3, "prerequisites": ["hover.hover_0_30_10"], "repeat_count": 2, "acceptance_profile": "acceptance.vertical", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "translation.x_out_back_0_10", "cluster_id": "basic-flight-commissioning", "major_id": "translation", "variant_id": "x-out-back-010", "motion_id": "motion.x-out-back-010", "stage": "ONE_AXIS", "stage_order": 3, "prerequisites": ["hover.hover_0_30_10"], "repeat_count": 2, "acceptance_profile": "acceptance.translation", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "translation.y_out_back_0_10", "cluster_id": "basic-flight-commissioning", "major_id": "translation", "variant_id": "y-out-back-010", "motion_id": "motion.y-out-back-010", "stage": "ONE_AXIS", "stage_order": 3, "prerequisites": ["hover.hover_0_30_10"], "repeat_count": 2, "acceptance_profile": "acceptance.translation", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "turn.yaw_plus_minus_30", "cluster_id": "basic-flight-commissioning", "major_id": "turn", "variant_id": "yaw-plus-minus-30", "motion_id": "motion.yaw-plus-minus-30", "stage": "ONE_AXIS", "stage_order": 3, "prerequisites": ["hover.hover_0_30_10"], "repeat_count": 2, "acceptance_profile": "acceptance.yaw", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "turn.yaw_full_360_slow", "cluster_id": "basic-flight-commissioning", "major_id": "turn", "variant_id": "yaw-full-360-slow", "motion_id": "motion.yaw-360", "stage": "COMBINED_BASICS", "stage_order": 4, "prerequisites": ["turn.yaw_plus_minus_30"], "repeat_count": 2, "acceptance_profile": "acceptance.yaw", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "shape.square_side_0_10", "cluster_id": "basic-flight-commissioning", "major_id": "shapes", "variant_id": "square-side-010", "motion_id": "motion.square-side-010", "stage": "COMBINED_BASICS", "stage_order": 4, "prerequisites": ["translation.x_out_back_0_10", "translation.y_out_back_0_10"], "repeat_count": 2, "acceptance_profile": "acceptance.square", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "shape.circle_radius_0_10", "cluster_id": "basic-flight-commissioning", "major_id": "shapes", "variant_id": "circle-radius-010", "motion_id": "motion.circle-radius-010", "stage": "COMBINED_BASICS", "stage_order": 4, "prerequisites": ["translation.x_out_back_0_10", "translation.y_out_back_0_10", "turn.yaw_plus_minus_30"], "repeat_count": 2, "acceptance_profile": "acceptance.circle", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "battery.start_below_admission_reject", "cluster_id": "basic-flight-commissioning", "major_id": "battery-behavior", "variant_id": "start-below-admission-reject", "motion_id": "motion.no-command", "stage": "GROUND_CHECKS", "stage_order": 0, "prerequisites": ["ground.arm_disarm_props_off"], "repeat_count": 1, "acceptance_profile": "acceptance.negative-zero-dispatch", "promotion_rule": "NEGATIVE_CASE_PASSES_ON_ZERO_DISPATCH"},
    {"key": "safety.controlled_abort_from_hover", "cluster_id": "basic-flight-commissioning", "major_id": "safety-drills", "variant_id": "controlled-abort-from-hover", "motion_id": "motion.abort-from-hover", "stage": "HOVER_AND_ABORT", "stage_order": 2, "prerequisites": ["takeoff.takeoff_0_30_hold_3_land"], "repeat_count": 3, "acceptance_profile": "acceptance.abort", "promotion_rule": "ALL_REPEATS_PASS_AND_MANUAL_PROMOTION"},
    {"key": "safety.containment_boundary_reject", "cluster_id": "basic-flight-commissioning", "major_id": "safety-drills", "variant_id": "containment-boundary-reject", "motion_id": "motion.no-command", "stage": "GROUND_CHECKS", "stage_order": 0, "prerequisites": ["ground.arm_disarm_props_off"], "repeat_count": 1, "acceptance_profile": "acceptance.negative-zero-dispatch", "promotion_rule": "NEGATIVE_CASE_PASSES_ON_ZERO_DISPATCH"}
  ],
  "battery_comparison": {
    "case_key": "hover.hover_0_30_10",
    "qualification_bearing": false,
    "comparator_band": "HIGH",
    "required_bands": ["HIGH", "MID"],
    "optional_bands": ["LOW_ALLOWED"],
    "required_repeats_per_required_band": 2,
    "fixed_context": "same case, vehicle, firmware, cage, motion, safety limits, and evidence profile",
    "aggregate": "median shown only after every repeat passes; all repeats remain visible"
  },
  "safety_geometry": {
    "frame": "HOME",
    "physical_enclosure": "NETTED_CYLINDER",
    "enclosure_radius_m": 0.50,
    "enclosure_height_m": 0.60,
    "vehicle_swept_radius_m": 0.10,
    "vehicle_half_height_m": 0.05,
    "position_uncertainty_m": 0.03,
    "height_uncertainty_m": 0.03,
    "route_center_radius_m": 0.10,
    "warning_center_radius_m": 0.18,
    "hard_center_radius_m": 0.34,
    "independent_source": "SIGNED_CAGE_INSPECTION_WITH_MEASUREMENT_AND_PHOTO_HASH"
  },
  "clock_and_stopping_witness": {
    "sense_to_effect_budget_s": {
      "source_sampling": 0.10,
      "source_to_receive": 0.03,
      "freshness_validation": 0.02,
      "safety_compute": 0.01,
      "host_dispatch": 0.02,
      "radio_transport": 0.02,
      "firmware_apply": 0.02
    },
    "admitted_budget_s": 0.25,
    "speed_m_s": 0.15,
    "deceleration_m_s2": 0.50,
    "jerk_m_s3": 2.0,
    "late_source_gap_s": 0.90
  },
  "reaction_vectors": [
    {"vector_id": "nominal_warning", "resulting_command": "STOP_AND_HOLD_THEN_LAND"},
    {"vector_id": "certified_land", "resulting_command": "CONTROLLED_LAND"},
    {"vector_id": "stale_active_state", "resulting_command": "EMERGENCY_STOP"},
    {"vector_id": "tampered_prearm_certificate", "resulting_command": "REJECT_ZERO_COMMAND"},
    {"vector_id": "late_active_observation", "resulting_command": "EMERGENCY_STOP"},
    {"vector_id": "insufficient_active_clearance", "resulting_command": "EMERGENCY_STOP"},
    {"vector_id": "missing_prearm_certificate", "resulting_command": "REJECT_ZERO_COMMAND"},
    {"vector_id": "lost_active_certificate", "resulting_command": "EMERGENCY_STOP"}
  ],
  "vertical_witness": {
    "commanded_height_m": 0.35,
    "overshoot_m": 0.03,
    "uncertainty_m": 0.03,
    "vehicle_half_height_m": 0.05,
    "hard_estimated_center_height_m": 0.45,
    "perturbed_commanded_height_m": 0.41,
    "expected_positive_margin_m": 0.14
  },
  "watchdog_contract": {
    "keepalive_period_s": 0.25,
    "scheduler_jitter_budget_s": 0.10,
    "link_stall_budget_s": 0.10,
    "maximum_accepted_gap_s": 0.50,
    "firmware_timeout_s": 1.0,
    "gap_relation": "STRICTLY_LESS_THAN",
    "emergency_input_to_link_deadline_s": 0.10,
    "software_repeat_count": 100,
    "normal_end_state": "REBOOT_REQUIRED_AFTER_COMMAND_SESSION",
    "timeout_end_state": "LOCKED_REBOOT_REQUIRED",
    "no_response_state": "DISPATCHED_UNCONFIRMED_REBOOT_REQUIRED"
  },
  "physical_landing_terminal": {
    "contract_path": "docs/reference/PHYSICAL_LANDING_TERMINAL_V1.md",
    "required_clauses": [
      "raw_supervisor_disarmed", "raw_supervisor_not_flying",
      "fresh_downward_range_at_or_below_0_05_m", "independent_observer_settled",
      "no_simulated_contact_claim"
    ],
    "claim_limit": "FUNCTIONAL_CONTAINED_FLIGHT_BASELINE_WITHOUT_EXTERNAL_POSITION_TRUTH"
  },
  "typed_integer_domains": [
    {"name": "stage_order", "minimum": 0, "maximum": 4},
    {"name": "repeat_count", "minimum": 0, "maximum": 10},
    {"name": "route_sample_count", "minimum": 8, "maximum": 128},
    {"name": "emergency_vector_count", "minimum": 100, "maximum": 100}
  ],
  "semantic_perturbations": [
    "renamed_child", "reordered_catalog", "circle_samples_16", "circle_samples_64",
    "square_collinear_densification", "axis_sign_flip", "incompatible_child",
    "yaw_modulo_shortcut"
  ]
}
```

<!-- WP87-88-R1-MACHINE-CONTRACT-END -->

### R1 reconstruction, exit evidence, and stop rule

The initial ledger preimage is reconstructed exactly with:

`perl -0pe 's/\n<!-- WP87-88-DESIGN-PAYLOAD-BEGIN -->[\s\S]*\z//' docs/work-packages/ACTIVE.md | shasum -a 256`

It must equal
`39a90e2d66b7a520e61e791d1388195e3013f506b190154441576ac2d0e99776`.
The R1 audit asserts that value, the unchanged initial payload and audit identities,
the complete R1 payload identity, 45 exact metrics/vectors, 17 catalog rows, motion
and acceptance specifications, all integer alias probes, the full numerical
certificate matrix, actual serving roots, claim-owner sets, generated outputs, and
every existing/new boundary preimage.

The retained command is:

`./.venv/bin/python scripts/audit_wp87_88_design_r1.py`

The retained artifact is:

`missions/campaigns/real/qualification/wp87-88-r1-design-audit-v2.json`.

WP-87 implementation exit additionally requires the new physical landing contract,
100/100 exact emergency software vectors, watchdog nominal/equality/late/link-loss/
process-loss/normal-end vectors, independent cage record schema and negative cases,
every 45-metric whole-repeat/isolated-failure vector through the real public trigger,
and `NOT_RUN` for every absent physical observation. WP-88 implementation exit
requires exact API/DOM set equality to the 17-row projection, every motion/acceptance
profile and semantic perturbation, descriptive battery contexts, and Play locked until
WP-87 is independently implementation-verified plus all hardware/permit gates pass.

This is the only correction. The same verifier receives one focused recheck. Any
remaining P0/P1 leaves WP-87/WP-88 `BLOCKED_WITH_FINDINGS`; no third automatic design
pass or implementation is permitted.

<!-- WP87-88-R1-DESIGN-PAYLOAD-END -->

### WP-87 and WP-88 R1 focused-recheck handoff

- Status: `PLANNED`.
- Independent verification: `DRAFT_UNVERIFIED`.
- Initial review count: `1`; correction count: `1`; focused recheck count: `0`.
- Author model/effort route: Codex GPT-5 frontier safety/control reasoning; exact
  effort setting, token count, and wall time are not exposed. Escalation trigger was
  real-aircraft emergency, containment, and landing authority plus two verifier-owned
  P0 findings.
- Reviewer model/effort: `work_packet_verifier`; exact underlying model, effort,
  tokens, and wall time are not exposed.
- Cost proxies: one initial review, one consolidated correction, two packet IDs,
  three packet-owned files before the R1 artifact, and zero runtime/hardware runs.
- R1 payload: SHA-256
  `4e0dee8365eee642067def27de2e7870e0387b2afb1051150591eb5980c33c0e`.
- R1 audit implementation: `scripts/audit_wp87_88_design_r1.py`; exact preimage is
  bound inside the V2 artifact.
- R1 audit artifact: SHA-256
  `24bde83b72269b0a1ef925298180737af7cf12e68122164db6eeb2afc77bcc4c`.
- R1 audit result: zero errors across 162 exact boundaries, 45 independently derived
  metrics with one whole-pass vector and 45 isolated-failure vectors, 17 catalog rows,
  16 motion contracts, 11 acceptance profiles, eight certificate/reaction vectors,
  four typed-integer alias matrices, and the exact generated API pair.

### WP-87 and WP-88 final design-gate outcome

| Packet | Status | Independent verification |
| --- | --- | --- |
| WP-87 | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |
| WP-88 | `REVIEW_BLOCKED` | `BLOCKED_WITH_FINDINGS` |

- Reviewer: `/root/wp87_88_design_verifier`.
- Initial review count: `1`; correction count: `1`; focused recheck count: `1`.
  The formal design-review cycle is exhausted.
- Accepted/reproduced identities: initial payload
  `8b5a1cb6a0241395b3b63a176aac36a42169621aad716b3e98ce73bc21c0537b`;
  R1 payload
  `4e0dee8365eee642067def27de2e7870e0387b2afb1051150591eb5980c33c0e`;
  V2 audit artifact
  `24bde83b72269b0a1ef925298180737af7cf12e68122164db6eeb2afc77bcc4c`.
- Resolved on focused recheck: strict containment/stopping/physical-landing evidence;
  emergency/watchdog deadlines and reboot lifecycle; blocked-predecessor
  supersession; actual serving-boundary closure; and exact preimage/model/cost record.
- Residual `WP87-88-DES-004` (P1 `MUST_FIX_NOW`, smallest scope WP-87): the guard
  registry still combines independently binding arming, preflight, link, positioning,
  health, permit, landing-clock/region, and emergency-input clauses. An incomplete
  safety implementation could therefore satisfy the authored 45-metric audit.
- Residual `WP87-88-DES-005` (P1 `MUST_FIX_NOW`, smallest scope WP-88): square and
  circle identities do not freeze HOME-to-shape entry, canonical circle phase/start,
  exit/return connectors, or their evidence windows. Multiple behaviorally different
  command sequences can satisfy the current analytic shape oracle.
- Verdict: `BLOCKED_WITH_FINDINGS`. No implementation, connection, permit, arming,
  motor action, or physical flight is authorized. Hardware evidence remains
  `NOT_RUN`. A successor correction requires explicit operator authorization; it may
  address only the two residual P1 scopes and must start a new bounded design cycle.

## Operator-present fast loop — hover evidence and physical-flight readability

- Status: `IMPLEMENTED`.
- Independent verification: `IMPLEMENTED_UNVERIFIED`.
- Operator feedback date: `2026-08-23`.
- Scope: analyze the retained `20260823` Digital Twin hover/move/shape runs; preserve
  the Digital Twin flight projection across a temporary observer reconnect; separate
  measured takeoff capture from horizontal motion; and enlarge the checkpoint shapes
  without exceeding the retained contained-flight center-radius boundary.
- Baseline evidence: the two complete 12-second hover commands
  `twin-basic-real-6ae0eb9cd9d0452981cad904f2c48cac` and
  `twin-basic-real-306dfde6f93d40b49424bdba6aa6b11d`, plus the bounded failed hover
  windows and the successful forward-return and L-shape runs retained under
  `run-files/20260823T*`.
- Disturbance classification: the operator reports deliberately blowing down on and
  touching the aircraft during one hover, but has not bound that event to a retained
  run identity. Treat that run only as disturbance-recovery evidence once identified;
  the current two-run range is descriptive and is not a clean-repeat qualification.
- Causal findings: complete hovers show about `1.5 cm` lateral estimator RMS around
  their run mean, `2.5 cm` p95 radial deviation, a repeatable roughly `1.2 s` sway,
  and `8–13 deg` yaw range; failed hover attempts are dominated by command-link loss
  and unknown acknowledgement rather than a recorded controller rejection. The
  successful forward-return run issued translation only milliseconds after the
  two-second takeoff command completed, while measured altitude was still about
  `0.14 m` with upward velocity about `0.21 m/s`.
- Tuning disposition: do not change onboard PID gains from these runs. Ground truth,
  retained controller targets, and ordinary-flight motor output are unavailable, so
  the current evidence cannot separate true aircraft drift, estimator drift, and
  downstream control response strongly enough for a bounded gain decision.
- Implementation bounds: the scene anchor resets only at a physical-flight boundary
  or measured vehicle identity change, not at a reconnect epoch; task motion starts
  only after three distinct samples are within `0.05 m` of target altitude and at or
  below `0.03 m/s` vertical speed; checkpoint L/square/triangle geometry is
  centered on HOME with `0.40 m` legs/sides, `<=0.10 m/s` motion, and maximum authored
  center radius below `0.29 m`. The retained `0.10 m` mission identities remain
  unchanged in the catalog but are no longer physical-enabled; the larger geometry
  uses successor IDs.
- Exit gates: focused Twin shadow tests cover reconnect epoch continuity and new-flight
  reset; physical-flight tests cover takeoff capture ordering, centered shape bounds,
  motion duration, and updated catalog copy; relevant UI/Python tests pass without
  touching the live dashboard or hardware runtime.
- Author checks: `33` basic-flight tests and `20` Crazyflie-adapter tests passed; the
  final successor-ID/authority adjustment passed `4` focused flight-lab tests; `19`
  focused UI tests, the generated-schema API contract test, ESLint, TypeScript, Ruff,
  the requirement-catalog check, and the project-map check passed. No live service
  restart, radio connection, or flight was performed.

## Operator-present fast loop — controller-fixture survey markers

- Status: `IMPLEMENTED`.
- Independent verification: `IMPLEMENTED_UNVERIFIED`.
- Operator feedback date: `2026-08-25`.
- Scope: retain the physical box survey in the Controller characterization & tuning
  fixture; use the closest inner floor corner as origin, the short side as `+X`, the
  long side as `+Y`, and expose the actual five marked calibration placements A–E.
- Survey inputs: preliminary scan-derived A–D centers and base footprint; direct
  measurements `EC = 0.268 m`, `EB = 0.441 m`, and `EA = 0.502 m` for the newly added
  E marker; four horizontal ranger optical centers `0.012 m` from the drone center;
  and a baseline placement with the drone centered over the selected floor X, front
  toward `+Y` at `0 deg`, turning toward `+X` through `+45 deg` to `+90 deg`.
- Derived value: least-squares trilateration against the scan-derived A/B/C anchors
  places E at approximately `(0.603, 0.665) m`, with about `0.0042 m` RMS distance
  residual. Preserve the three direct measurements as source observations rather than
  replacing them with only the derived coordinate.
- Non-goals: no survey-complete claim, fixture-baseline acceptance, controller/gain
  change, hardware deployment, radio connection, motor action, or flight. Wall height,
  bowed wall profiles, flight stations, ranger angular uncertainty, and other
  characterization inputs stay open and advisory. Implemented B–E commands remain
  operator-selectable; F–H remain raw because they have no command workflow.
- Exit gates: the strict fixture contract validates the corner frame, unique A–E
  markers, distance endpoints, and base bounds; Mission A catalog variants bind A–E;
  range prediction, heading conversion, horizontal-ranger selection, and flight-relative
  station commands remain correct under the corner-origin frame; focused Python/UI
  contract checks pass.
- Author checks: `43` focused controller-tuning/basic-flight Python tests and `34`
  focused Twin/API-adapter UI tests passed; Ruff, ESLint, TypeScript, generated OpenAPI,
  JSON parsing, the requirement-catalog check, and the project-map check passed. No
  live service restart, radio connection, motor action, or physical flight occurred.

## Operator-present fast loop — physical link dropout and stale presentation

- Status: `IMPLEMENTED`.
- Independent verification: `IMPLEMENTED_UNVERIFIED`.
- Operator feedback date: `2026-08-25`.
- Observed evidence: the station-B observation was deleted at the operator's request
  and is not retained as evidence for this finding. The following station-C operation
  was stopped before ordinary retention completed. Later observer sessions failed
  after the installed cflib `0.1.32` transport emitted
  repeated `Too many packets lost` callbacks. This establishes an abrupt radio-ACK
  loss, but it does not by itself identify the environmental source of that RF loss.
- Software finding: a completed SSE frame marked `CURRENT` could remain cached in the
  readout and override a later lifecycle poll reporting `STALE` or `ERROR`. The
  backend also kept the failed session's last presentation pointers populated after
  durable failure retention. Together these paths made frozen values remain visible
  after the connection had stopped.
- Implementation: cflib's consecutive missed-ACK disconnect budget is raised from
  its library default of `100` to `1,000`, leaving the application's measured
  one-second freshness watchdog as the authoritative fail-closed boundary. The exact
  cflib connection-loss reason now reaches the snapshot/status path. Stream failure
  retains the failed journal session but clears its live presentation pointers, and
  the UI refuses to let an older current frame mask an authoritative stale/error
  lifecycle state.
- Safety boundary: the larger cflib ACK budget does not extend usable telemetry or
  command authority. `CrazyflieVehicle.snapshot` still rejects a sample older than
  the configured one-second timeout, after which the existing bounded disconnect,
  recovery, and operation-stop paths apply. No automatic command retry was added.
- Author checks: `48` focused Crazyflie-adapter/observer tests and `25` focused
  physical-twin UI tests passed; Ruff, TypeScript, ESLint, and diff-whitespace checks
  passed. An adjacent `36`-test flight/API run had `35` passes and one existing-checkout
  catalog expectation mismatch for the unrelated cushioned-acrobatics setup state.
  No dashboard restart, hardware deployment, radio connection, motor command, or
  physical flight was performed for this fix.

## Operator-present fast loop — Mission A baseline analysis and advisory-only flight availability

- Status: `IMPLEMENTED`.
- Independent verification: `IMPLEMENTED_UNVERIFIED`.
- Operator feedback date: `2026-08-25`.
- Durable policy: implemented Controller characterization & tuning motions B–E are not
  unlocked by survey completion, baseline acceptance, earlier mission results,
  coverage, amplitude progression, or per-mission enable flags. Those gate fields were
  deleted from the fixture schema and runtime. Missing wall geometry, clearance, and
  uncertainty remain visible characterization advisories. Exact marker/heading/height,
  command inputs, default-PID/Kalman experiment identity, and the shared generic
  link/supervisor/permit/abort/stop-integrity boundary remain authoritative.
- Retained batch: the main heading-0 observations at A–E completed for approximately
  30 seconds each. At heading 90, A and D completed; E retained 28.5 seconds, C retained
  13.3 seconds, and B retained 4.4 seconds before `Crazyflie telemetry is unavailable`.
  A separate 2.9-second D attempt failed the same way before its successful repeat.
  Those shorter records are partial observations, not equivalent completed repeats.
  The deliberately deleted run `twin-tuning-real-39b9b2dedc16489f9cd4122991e53b37`
  was not restored or analyzed.
- Raw-range finding: all retained rows in the post-19:19 batch reported valid
  front/back/left/right ranges. Per-run channel standard deviations were approximately
  `1.4..2.3 mm`; first-versus-last-fifth drift stayed within `1.4 mm` for the meaningful
  windows. This supports a quiet short-term ranger-noise baseline at this setup, not a
  controller conclusion.
- Rectangle/placement finding: against the preliminary `1.062 m x 1.260 m` base and
  12 mm optical-center offsets, the five successful heading-0 runs had individual mean
  residuals from about `-28..+16 mm` and opposing-pair inconsistencies of
  `0.7..24.9 mm`. The fixed-rectangle opposing-range position estimates differed from
  the configured marker coordinates by A `(-1.1,+4.5) mm`, B `(-15.6,+5.0) mm`,
  C `(-5.4,+0.6) mm`, D `(-6.9,-8.7) mm`, and E `(-11.4,+7.5) mm`. The two complete
  heading-90 runs gave A `(-10.5,+8.2) mm` and D `(-2.4,-7.7) mm`. This is consistent
  with a combination of manual centering/heading error, preliminary marker coordinates,
  sensor offsets/bias, and height-dependent bowed walls; this batch cannot separate
  those causes.
- Height/attitude limitation: the operator states that the horizontal measurements
  were made at `0.144 m` to avoid close-to-ground artifacts. Historical run preparation
  nevertheless retained `target_height_m=null` and `height_m=0.0`; down-range means
  varied from about `0.098..0.147 m`. Therefore `0.144 m` is operator-supplied batch
  context, not hash-bound per-run height evidence, and this batch cannot fit a
  height-indexed wall profile. Static estimator tilt also varied by placement (up to
  about `2.9 deg` roll or pitch), while estimator yaw stayed near zero for both entered
  headings and cannot independently verify manual heading. The swapped range geometry
  does support the intended 0/90-degree orientation change.
- Disposition: `NO_CONTROLLER_CHANGE`. Mission A characterizes sensor/fixture/placement
  effects only. Mission B should collect default-PID takeoff/hover/landing telemetry and
  landing surveys before any controller diagnosis, and no gain tuning follows from this
  baseline alone.
- Implementation: removed the fixture-baseline, default-PID-baseline,
  enabled-amplitude, yaw-enable, and speed/position-enable schema fields and every
  runtime/UI unlock derived from them; converted incomplete characterization to one
  non-blocking warning; retained local command prerequisites and generic runtime
  integrity. No live dashboard deployment or physical action was performed in this
  change, so the persistent service continues serving its prior release until the
  operator explicitly authorizes deployment.
- Author checks: `45` focused controller-tuning/basic-flight hardware tests, `15`
  physical-twin/API contract tests, `36` focused UI component/adapter tests, Ruff,
  TypeScript, ESLint, OpenAPI export/type regeneration, the 150-definition requirement
  catalog check, the project-map check, and diff-whitespace validation passed. These
  are author checks only; no independent verification is claimed.

## Controller-fixture A–E run workflow and tuning evidence plan

- Status: `PLANNED`.
- Independent verification: `DRAFT_UNVERIFIED`.
- Operator feedback date: `2026-08-25`.
- Objective: turn the existing controller-characterization catalog into a repeatable
  physical experiment workflow in which A–E are reusable placement variants, heading
  and height are exact run inputs, post-landing trilateration is retained evidence, and
  measured fixture geometry can support truthful analysis without becoming a software
  flight unlock.
- Implementation progress: the catalog had hard-coded motion IDs and the run request
  originally contained only `motion_id`. The first implemented slice now
  projects floor markers A–E as variants in every implemented major mission, accepts
  typed `0..90 deg` heading and optional height, binds them with the fixture hash into
  the operation marker and retained run, and keeps implemented B–E commands directly
  operator-selectable. Repetition indexing, landing measurements, compressed bowed-wall
  geometry, and the complete geometry-aware resolver remain open. This section does not
  authorize flight or gain changes.
- Setup refinement: the heading and height inputs now appear in a prominent `Run setup`
  card in the selected mission pane. Flight runs require an explicit height. Global
  readiness no longer treats the obsolete named-station grid or descriptive lighting,
  finish, and texture metadata as missing A–E geometry; the draft now reports the two
  unresolved characterization values exactly: wall height and wall safety clearance
  including the drone envelope. The repeated controller-tuning setup banner and all
  survey/baseline/progression flight gates are removed. One non-blocking
  `Characterization incomplete` warning preserves the exact missing fields.
  Mission-specific named targets remain local command prerequisites for motions that
  directly use them.
- Operator deployment: after confirming motor actuation `IDLE` with
  `stop_required=false` and terminal flight state with `stop_required=false`, the
  dashboard was deployed once as release `release-e02cf3314d4f418ebed0483d98e697ee`.
  Rendered-page inspection confirmed a visible, editable Heading input for A and B,
  the required B flight-height input, and no visible `Setup required` copy. The service
  is healthy and owns the canonical hardware lane; observer reconnection currently
  reports `RADIO_UNAVAILABLE` because no Crazyradio dongle is detected.
- Implemented-slice author checks: `46` focused Python hardware/API tests and `12`
  focused Campaign Laboratory UI tests passed; Ruff, TypeScript, ESLint, generated
  OpenAPI, and diff-whitespace checks passed. The catalog probe reports A–E variants
  for each major mission A–E and `Raw` only for F–H. No dashboard restart, radio
  connection, motor command, or physical flight occurred.

### WP-CT-1 — Immutable fixture source and compressed geometry

1. Import the unchanged `Scaniverse 2026-08-25 185658.glb` source into a retained
   fixture-survey artifact location and record its `11,967,612` byte size and SHA-256
   `0546087236cc762792d0b464de8655679952e738f1138cec7503b61825d214e5`.
   Do not depend on a mutable Downloads path or conversation memory.
2. Generate a compact derived artifact that records the source hash, GLB-to-fixture
   transform, inner floor boundary, A–E coordinates/uncertainties, and wall profiles at
   relevant ranger/vehicle heights. Preserve raw E–A/B/C distances beside the derived E
   coordinate.
3. Represent bowed cardboard walls with height-indexed profiles and uncertainty, not
   one constant rectangle. Version any material, wall-shape, marker, or coordinate-frame
   change as a new fixture baseline.
4. Exit: regeneration is deterministic; source and derived hashes are retained; known
   A–E distances reproduce within declared uncertainty; malformed or mismatched source
   metadata fails closed.

### WP-CT-2 — Parameterized preparation and exact run identity

1. Replace heading/station motion proliferation with an immutable preparation contract:
   `major_mission`, `station_id`, `heading_deg`, `height_preset/target_z_m`,
   `motion_id`, `movement_frame`, fixture/version/geometry hash, controller/estimator
   snapshot, and an automatically assigned repetition index.
2. Use A–E as the layer-3 variants in every implemented major mission. Heading is a
   numeric input with default `0`, initial range `0..90`, and the fixture convention
   `0 = front +Y`, `45 = between +Y/+X`, `90 = front +X`. Height uses surveyed presets;
   Mission A starts with grounded ranger height unless a measured jig is selected.
3. Motion labels must state whether displacement is BODY or fixture/HOME relative.
   Never present an ambiguous `X` move when those frames differ. The selected setup is
   frozen before Play and displayed in Active run and Review.
4. Remove repetitive per-row setup copy. Show incomplete fixture characterization once
   as a non-blocking supporting warning and expose exact missing values in the closed
   technical disclosure. F–H retain one truthful `Raw` state.
5. Exit: API, generated schema, adapters, UI, retained artifacts, reload/recovery, and
   tests preserve exact inputs; changing a field creates a distinct run identity; Play
   remains unavailable only when an implemented command lacks required direct inputs or
   the shared runtime-integrity checks do not permit execution.

### WP-CT-3 — Mission A fixture/ranger baseline

1. Major A exposes variants A, B, C, D, and E and one `Observe baseline` motion. The
   operator centers the drone over the selected red X, types the heading, chooses the
   admitted height, and starts one motors-off observation.
2. Retain raw front/back/left/right ranges and validity, source/receive timestamps,
   estimator pose/attitude, sensor offsets, predicted wall intersections, per-sensor
   residuals, and opposing-range consistency. Up and down remain excluded from the
   horizontal wall model.
3. Use A–D to fit or characterize the baseline and reserve E as the default holdout.
   E remains fully selectable and reports validation error; it is not silently folded
   into a refit. Repeats are separate Play actions and coverage is shown as a
   station × heading × height matrix rather than a chat checklist.
4. Exit: range predictions use the bowed-wall profile at the actual ranger height,
   invalid readings remain invalid, residual distributions and repeat spread are
   visible, and no baseline is accepted automatically.

### WP-CT-4 — Mission B hover and landing survey

1. Major B reuses variants A–E and the same heading/height preparation. One Play action
   performs one default-PID takeoff, settled hover, landing, and disarm at the selected
   placement; the operator manually repositions between repetitions.
2. Bind command targets, estimator state, ranges, attitude/body rates, battery, motor
   activity when available, controller/estimator readback, and exact preparation to the
   run. Operational completion and manual external evaluation are separate states.
3. After landing, Campaign Review marks the run `AWAITING_LANDING_SURVEY` and accepts
   planar distances from the vertical floor projection of the drone center to at least
   three non-collinear A–E markers. Four or five are preferred. Retain marker IDs, raw
   distances, stated uncertainty, units, solver/version, derived `(x,y)`, covariance or
   uncertainty, and every residual. A correction is a new revision; contradictory
   circles produce `INCONSISTENT`, never a silently averaged success.
4. Compare command versus estimator, estimator versus fixture/ranges, and command
   versus externally reconstructed final position as separate error chains. Landing
   truth does not prove the airborne path, overshoot, settling time, or speed.
5. Exit: a landing form cannot attach to the wrong run; three-marker synthetic cases,
   redundant good measurements, one perturbed measurement, impossible circles, unit
   errors, and revision history are tested.

### WP-CT-5 — Missions C–E and geometry-aware analysis

1. Mission C recommends BODY-labeled 5 cm forward/back/left/right probes and return
   before 15 cm and 30 cm motions, but does not lock any implemented amplitude. Mission D
   applies small bounded yaw holds/sweeps relative to the typed initial heading, while
   keeping the resolved absolute heading inside the initial `0..90 deg` domain. Mission
   E compares only margin-rich slow profiles before any higher-stress speed.
2. A run resolver transforms the selected A–E start, heading, height, and BODY/HOME
   motion into the fixture frame. It reports the swept vehicle envelope,
   sensor-center rays, return path, landing region, and stopping reach against the
   height-indexed wall profiles after subtracting safety clearance, geometry/placement
   uncertainty, estimator allowance, and vehicle radius. Checking endpoints alone is
   insufficient.
3. The UI and backend report the resolved amplitude, speed, yaw, height, and any known
   wall-margin shortfall for the exact setup. Missing or adverse characterization does
   not disable an implemented command and must not be presented as measured safety.
4. Reuse the Mission B landing survey for every flight. Use the final reconstructed
   position only for endpoint/return/landing error; derive trajectory and dynamic
   metrics from retained in-flight evidence.
5. Exit: boundary starts, `0/45/90 deg`, each station, each height preset, every motion
   direction, bowed-wall slices, stopping reach, return, and landing are covered by
   analysis tests that distinguish known, violated, and unavailable margins without
   changing command availability.

### WP-CT-6 — Analysis checkpoint before any controller change

1. Do not tune after only A and B. First pass Mission A model/holdout checks, collect
   repeatable Mission B baselines, then execute the margin-rich Mission C 5 cm probes
   plus a small Mission D yaw and Mission E slow-profile guard set. Broader station and
   heading coverage may continue without forcing a full Cartesian product before the
   first analysis checkpoint.
2. Diagnose ranger/wall-model error, estimator error, command tracking, axis/yaw
   coupling, and final-position error separately. Use repeats and show every run; no
   average may hide a failed or disturbed run.
3. Any candidate change happens only while landed and disarmed: change one bounded
   parameter family, retain old/new values and readback, then create a new run. No live
   airborne tuning and no automatic gain persistence are permitted.
4. A–E remain characterization/evidence missions. F controller comparison, G bounded
   gain refinement, and H robustness confirmation remain raw until a separate design
   defines their commands, rollback, comparison oracle, and promotion criteria.
5. Exit: the analysis produces a bounded diagnosis and either `NO_CHANGE` or a future
   F/G design proposal. It cannot label a gain set better, accepted, or qualified from
   A/B hover averages or touchdown coordinates alone.

### Recommended operator progression after implementation

1. Complete Mission A at A–E for the planned headings, repeating outliers or unstable
   readings; accept the geometry/ranger baseline only after E holdout error is credible.
2. Fly Mission B as separate station/heading repetitions and enter the landing survey
   immediately after each run so measurements cannot be attached to the wrong run.
3. Run only 5 cm Mission C probes, then the smallest D yaw and slow E guard cases that
   resolve the diagnosis. Expand coverage where repeat spread or position dependence
   requires it.
4. Stop for offline analysis while disarmed. Do not select larger/faster motions or
   implement F/G solely because a mean plot looks improved.

### Plan-level non-goals and safety boundary

- No hardware deployment, radio ownership, arming, motor command, flight, fixture
  acceptance, controller/gain write, or service restart is authorized by this plan.
- No automatic movement between physical A–E markers, live in-flight tuning, chat-only
  placement identity, GLB-in-memory assumption, rectangular-wall claim, or conversion
  of landing distances into claimed airborne trajectory truth.
- The existing persistent hardware runtime remains untouched until the operator
  explicitly requests deployment or a physical run in a later task.

## WP-89 — switchable sparse-ranger basic avoidance

Status: `PLANNED`

Independent verification: `DRAFT_UNVERIFIED`

Originating operator request date: `2026-08-27`.

<!-- WP89-DESIGN-PAYLOAD-START -->

### Intent and value

- Minimum useful outcome: place one explicit avoidance toggle immediately beside the
  physical Play control and carry its frozen value through the real start request so
  the operator can compare the same hover/translation mission with and without
  enforcement.
- Explicit behavior: reject stale, missing, and out-of-range closing-direction ranger
  data; project measured and commanded horizontal velocity onto each horizontal
  ranger ray; compute a speed-, latency-, uncertainty-, and braking-dependent protected
  distance; progressively slow a not-yet-dispatched translation; and fail closed via
  the existing controlled abort/land path if an enforced in-flight evaluation becomes
  unsafe.
- Necessary prerequisites: range-value receive freshness must survive normalization;
  the selected mode and latest decision summary must survive status polling and the
  durable operation marker; existing physical permit, containment, Abort, telemetry,
  and operator-owned-runtime boundaries remain authoritative.
- Optional later value, excluded here: a commander-priority takeover that can certify
  an indefinite stop-and-hold, bounded retreat, wall following, corridor centering,
  corner escape, mapping, and localization recovery.
- Safe fallback: `MONITOR_ONLY` is the default and preserves the exact authored
  command payload. `ENFORCED` never claims a physical hold; when safe progressive
  limiting is no longer possible after dispatch it terminates the mission through the
  existing abort/land recovery path.

### Frozen contract and invariants

1. The public request admits exactly `MONITOR_ONLY` and `ENFORCED`; aliases such as
   booleans, numbers, `ON`, `OFF`, and null are rejected. The value freezes at Play,
   is disabled for editing while an operation is active, and is returned by status.
   UI copy is `Avoidance off` for `MONITOR_ONLY` and `Avoidance on` for `ENFORCED`.
2. The toggle is shown only for physical flight motions. Props-off observation,
   arm/disarm, and cushioned acrobatics send `MONITOR_ONLY` and do not advertise an
   enforcement choice in this slice.
3. The policy evaluates front/back/left/right only. For body ray `u_i`, closing speed
   is `max(0, u_i dot v_body_measured, u_i dot v_body_commanded)`. HOME velocity is
   rotated by measured yaw before projection. A missing yaw or velocity blocks only an
   `ENFORCED` horizontal move that needs that projection; it cannot fabricate zero.
4. A range is usable only when its direction status is `VALID`, its finite distance is
   present and below the declared maximum, and its receive age is at most `0.4 s`.
   `STALE`, `UNAVAILABLE`, `CLIPPED`, and `NO_HIT` are rejected. Invalid data in a
   non-closing direction does not block motion away from it; invalid data in a closing
   or commanded direction blocks a new enforced translation or requests recovery once
   airborne.
5. Ranger distance is measured from the sensor origin. The protected center distance
   is:

   `0.055 m vehicle radius + 0.050 m position uncertainty + 0.020 m range uncertainty
   + 0.050 m margin + closing_speed * 0.800 s complete latency
   + jerk_limited_stop(closing_speed, 1.0 m/s^2, 8.0 m/s^3)`.

   The required sensor range subtracts the surveyed `0.012 m` horizontal sensor-origin
   offset. These are conservative provisional software bounds for the existing
   `<=0.10 m/s` laboratory motions, not measured braking qualification or controller
   gains.
6. Safe speed is the greatest speed in `[0, 0.10] m/s` whose required sensor range is
   no greater than measured clearance. It is solved deterministically to `1e-6 m/s`.
   A horizontal move above that value has duration increased to preserve displacement;
   no endpoint or direction changes. Values below `0.02 m/s`, invalid closing data, or
   negative margin block dispatch in `ENFORCED`.
7. While a guarded hover or move is executing, each adapter sample is reevaluated.
   `MONITOR_ONLY` records transitions and extrema but never changes a command, raises
   an intervention, or changes the existing success/failure path. `ENFORCED` requests
   recovery when the current measured closing speed exceeds the newly safe speed or
   the binding direction becomes invalid. The already-dispatched command outcome is
   retained as unknown where appropriate, and the existing physical failure recovery
   performs controlled abort/land. No emergency motor stop is introduced.
8. Existing hard containment, estimator convergence, permit, link freshness, motor
   stop, operator Abort, landing, disarm, and stop-confirmation logic cannot be disabled
   by either avoidance mode. No live service, radio, or aircraft is touched by this
   packet's implementation or verification.

### Claim and evidence matrix

| Claim | Real trigger / production entry | Effect and retained observation | Independent oracle and counterexample | Boundary |
| --- | --- | --- | --- | --- |
| `WP89-C1-TOGGLE_TRANSIT` | Bottom-left physical Play start through `/api/v1/physical-twin/lab/physical-flight/start` | Frozen mode in request, active status, and marker; toggle locks during run | Captured API body/status plus invalid typed-mode and retoggle cases | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` |
| `WP89-C2-DYNAMIC_POLICY` | Normalized Crazyflie ranges, pose, velocity, yaw, and requested motion | Per-ray margin, binding ray, maximum safe speed, decision | Independently recomputed exact numerical vectors; clearance/latency/uncertainty monotonic perturbations | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE` |
| `WP89-C3-PHYSICAL_COMMAND_GUARD` | Contained-flight command helper and adapter sample loop | Unchanged monitor payload, lengthened safe enforced duration, or existing abort/land recovery | Fake-link command capture; stale closing ray, near obstacle, moving-away, and mid-command clearance-loss cases | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` |
| `WP89-C4-RETAINED_TRUTH` | Status polling, command evidence, telemetry artifact, and marker reload | Mode plus counts, minimum margin, last decision, and intervention reason remain attributable | Marker restart/reload and terminal artifact assertions with run-local IDs normalized | `INTEGRATION / FAST_SIM / ACCELERATED` |

### Affected-boundary manifest and pre-freeze oracle

The exact existing/new/generated manifest, preimage hashes, typed-mode perturbations,
policy constants, numerical vectors, and claim-owner closure are retained by
`scripts/audit_wp89_design.py` in
`missions/campaigns/real/qualification/wp89-design-audit.json`. The audit derives the
OpenAPI pair from `ui/package.json`, requires every claim owner in the manifest, and
fails if an intended-new path already exists.

The numerical witness contains zero, half, and maximum speed plus isolated increased
latency and increased uncertainty perturbations. Implementation tests must recompute
the relation independently rather than importing expected results from the policy.

### Implementation ownership

- Policy and sensor truth: `src/crazyswarm_app/safety/avoidance.py`,
  `src/crazyswarm_app/domain/telemetry.py`, and
  `src/crazyswarm_app/vehicles/crazyflie.py`.
- Physical production transit and durable evidence:
  `src/crazyswarm_app/hardware/basic_flight_lab.py` and
  `src/crazyswarm_app/api/app.py`.
- Public/generated/UI transit: `ui/app/lib/api.ts`, `ui/app/lib/models.ts`,
  `ui/openapi.json`, `ui/app/lib/api.generated.ts`,
  `ui/app/components/TwinBasicFlightLab.tsx`, and `ui/app/globals.css`.
- Durable maps: `design.md` and `docs/system/README.md`.
- Test owners: `tests/safety/test_avoidance.py`,
  `tests/hardware/test_crazyflie_adapter.py`,
  `tests/hardware/test_basic_flight_lab.py`,
  `ui/tests/api-adapter.test.ts`, and
  `ui/tests/twin-basic-flight-lab.test.tsx`.

### Exit evidence and limits

1. The pre-freeze audit passes and its payload hash is reproduced before design review.
2. New policy tests fail against the absent implementation for the intended reason,
   then pass intended, invalid/stale, monotonic, moving-away, and boundary vectors.
3. API/component tests enter through the normal start control and prove exact mode
   transit, lockout, default, and invalid input behavior.
4. Fake-link contained-flight tests prove command identity in `MONITOR_ONLY`, increased
   duration without changed displacement in `ENFORCED`, and the existing abort/land
   recovery after a mid-command adverse sample. No hardware claim follows.
5. OpenAPI regeneration, Python and UI focused suites, Ruff, TypeScript, ESLint,
   requirement-catalog validation, project-map validation, and diff whitespace pass.
6. One isolated simulation/software verification run exercises the production request
   and fake Crazyflie link. Environment is `FAST_SIM`, clock is `ACCELERATED`; physical
   stopping distance, realtime latency, illumination robustness, and hardware safety
   remain `NOT_RUN` and unqualified.

### Non-goals

- No physical deployment, dashboard restart, radio ownership, motor command, flight,
  PID/estimator tuning, lighthouse dependency, SLAM, mapping, general exploration,
  certified stop-and-hold, retreat, wall following, corridor centering, or corner
  escape.
- No claim that five sparse rays prove free space between rays or behind `NO_HIT` data.
- No use of avoidance to relax another safety or readiness gate.

<!-- WP89-DESIGN-PAYLOAD-END -->

### WP-89 design-review handoff

- Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.
- Author model/effort route: frontier safety/control reasoning because this crosses a
  real-aircraft command boundary; exact effort, token count, and wall time are not
  exposed. Cost proxies before review: one packet, four claims, zero correction passes,
  zero runtime/hardware runs.
- Independent verification remains `DRAFT_UNVERIFIED` until a fresh verifier reproduces
  the design payload and audit identities.

## WP-89 R1 — consolidated freshness, uncertainty, oracle, and scope correction

Status: `PLANNED`

Independent verification: `DRAFT_UNVERIFIED`

This is the single correction permitted after findings `WP89-D1` through
`WP89-D4`. The initial payload remains immutable above. This R1 payload supersedes
it for implementation eligibility.

<!-- WP89-R1-DESIGN-PAYLOAD-START -->

### Originating request and partial-slice truth

The originating operator request is retained verbatim:

> “ok then make a detailed plan for 2 avoidance for this second
>
> 2. Implement basic avoidance before mapping
> Make this a general command-safety layer, not a mission behavior. Every requested
> movement passes through it—manual control, planned routes, exploration or
> return-to-home.
> The first version should:
> Reject stale, missing and out-of-range sensor data.
>
> Project the drone’s velocity toward each sensed obstacle.
>
> Calculate a dynamic protected distance:
> vehicle radius + uncertainty + latency travel + braking distance + margin
>
> Progressively limit forward speed as clearance decreases.
>
> Stop and hold when stopping remains safe.
>
> Land or retreat only when hold is unsafe or localization becomes invalid.
>
> This is better than a fixed rule such as “stop at 30 cm”: the safe threshold must
> grow with speed, latency and uncertainty.
>
> After reliable stopping, add wall following, corridor centering and bounded escape
> from corners. Pure reactive rules can deadlock, so these remain local
> safety/navigation primitives, not yet general exploration.
> The Multi-ranger provides five sparse distance directions and no avoidance
> automatically; software must interpret them.
>
> make it switchable on and off for now as a simple toggle next to the play button
> bottom left so i can test hover tests with and without”

The implementation authorization is also retained verbatim:

> “ok start implementation and do one isolated verifaction run like in the
> workpacket workflow”

WP-89 is explicitly the first partial vertical slice of that broader request, not its
completion. It serves the immediately requested A/B hover and slow-translation test
control plus dynamic sparse-ranger limiting. A certified commander-takeover
stop-and-hold is a prerequisite for the requested hold-before-land hierarchy and
remains open. Until that later primitive is designed and verified, WP-89 uses the
existing controlled abort/land recovery after an unsafe post-dispatch sample and must
not be presented as general avoidance, hold, retreat, mapping, or exploration.

### Intent/value card

- Minimum useful outcome: a toggle immediately beside physical Play whose exact
  `MONITOR_ONLY` or `ENFORCED` value freezes into the real request, status, marker,
  and evidence; a dynamic policy can leave, retime, block, or recover slow laboratory
  hover/translation commands without changing another safety gate.
- Required prerequisites: per-variable freshness for ranges, yaw, horizontal velocity,
  and estimator variance; measured uncertainty; full reaction budget; exact public/UI
  transit; deterministic policy evidence; existing abort/land recovery.
- Optional/deferred: low-level commander takeover and certified indefinite hold,
  bounded retreat, wall following, corridor centering, corner escape, SLAM, mapping,
  and mission-independent integration outside this physical laboratory entry.
- Non-goals: physical qualification, realtime latency proof, measured braking
  qualification, controller or estimator tuning, live deployment, radio access, motor
  action, or flight.
- Safe fallback: default `MONITOR_ONLY` preserves authored command identity. In
  `ENFORCED`, failure to prove a safe new translation blocks dispatch; loss of a
  binding certificate after dispatch invokes existing controlled abort/land.

### Exact input, clock, and uncertainty contract

1. The public request admits exactly `MONITOR_ONLY` and `ENFORCED`. Pydantic strict
   typing rejects booleans, integer/fractional numbers, `ON`, `OFF`, empty string,
   and null. The UI labels them `Avoidance off` and `Avoidance on`, defaults to
   `MONITOR_ONLY`, freezes the selection at Play, and disables it until the operation
   reaches a backend-terminal state. Observation, arm/disarm, and acrobatics remain
   fixed `MONITOR_ONLY` and do not show the control.
2. The adapter preserves host monotonic receive timestamps independently for
   `range.front/back/left/right`, `stabilizer.yaw`, `stateEstimate.vx/vy`, and
   `kalman.varPX/varPY`. A timestamp is the exact
   `CrazyflieRawSample.value_received_at_monotonic_s` entry for that variable. An
   empty timestamp map is admitted only by injected test links, where the enclosing
   raw sample receive time is the explicit fallback; a partially populated map never
   fabricates a missing variable timestamp.
3. Effective evaluation time is host monotonic time sampled once per policy
   evaluation. Every binding variable must have
   `0 <= effective_time - variable_received_time <= 0.400000 s`. Negative age,
   missing timestamp, age `>0.4 s`, missing/non-finite value, or a reset clock epoch
   rejects the binding certificate. Firmware source timestamp remains evidence but is
   not subtracted from the host clock.
4. HOME `vx/vy` rotates through the fresh measured yaw into body velocity. BODY
   commands are already body-relative; HOME commands rotate by the same yaw. For body
   ray `u_i`, closing speed is
   `max(0, dot(u_i, measured_body_velocity),
   dot(u_i, commanded_body_velocity))`. Front/back/left/right rays are
   `(+x,-x,+y,-y)`. During hover, missing or stale yaw/velocity means closing motion
   is unknown and requests recovery in `ENFORCED`; it is not treated as zero.
5. A binding range is usable only with status `VALID`, a finite distance in
   `[0,max_range_m)`, and fresh receive time. `STALE`, `UNAVAILABLE`, `CLIPPED`,
   `NO_HIT`, null, non-finite, negative, equality with maximum range, and greater
   values reject it. Invalid data on a ray proven non-closing by fresh measured and
   commanded velocity is ignored for that ray only.
6. Position uncertainty is
   `max(0.050 m, 2 * sqrt(max(varPX,varPY)))` using fresh, finite, nonnegative
   variances. Missing/stale/negative/non-finite variance rejects the certificate.
   Thus the adapter's `0.01 m^2` convergence edge contributes `0.200 m`, rather
   than being understated by a fixed `0.050 m` allowance.

### Numerical policy and reaction budget

The range measurement begins at the horizontal sensor origin. For closing speed
`v`, required sensor range is:

`0.055 vehicle radius + measured position uncertainty
+ 0.020 range uncertainty + 0.050 policy margin
+ v * 0.800 complete latency + jerk_limited_stop(v, 1.0 m/s^2, 8.0 m/s^3)
- 0.012 sensor-origin offset`.

The provisional `0.800 s` complete latency is the sum of independently named
budgets:

| Budget | Seconds | Clock boundary |
| --- | ---: | --- |
| Maximum already-accepted per-variable sample age | 0.40 | host variable receive to effective evaluation |
| Host evaluation and next adapter poll | 0.02 | effective evaluation to dispatch decision |
| Command transport and acknowledgement | 0.08 | host dispatch to acknowledged delivery |
| Onboard commit and braking onset | 0.30 | delivery to assumed deceleration onset |

These bounds are deliberately provisional and conservative for software tests. No
physical or observed-realtime claim may use them until measured.

The jerk-limited stop relation is identical in shape to the existing replanning
oracle: triangular when `v <= a^2/j`, otherwise acceleration-ramp, constant
deceleration, and ramp-out. Maximum safe speed is the greatest value in
`[0,0.10] m/s` whose required sensor range is no greater than measured range,
resolved by deterministic bisection to `1e-6 m/s`.

- Requested speed at or below safe speed remains unchanged.
- A not-yet-dispatched horizontal move above safe speed but with safe speed
  `>=0.02 m/s` retains displacement/direction/yaw and changes duration to
  `horizontal_distance / safe_speed`.
- Safe speed below `0.02 m/s`, a negative margin, or rejected binding input blocks a
  new enforced move.
- `MONITOR_ONLY` computes and retains the same decision but never changes duration,
  displacement, command ordering, outcome, or recovery.
- During an executing hover or move, each adapter sample is reevaluated. If current
  measured closing speed exceeds the new safe speed, or a binding input becomes
  invalid, `ENFORCED` raises a typed avoidance intervention. The dispatched command
  is retained as outcome-unknown and the existing contained-flight failure path sends
  controlled Abort/land. No emergency-stop or no-op `StopAndHoldCommand` is used.

### Claim/evidence matrix

| Claim | Real trigger / production entry | Effect and retained observation | Independent oracle and counterexample | Boundary |
| --- | --- | --- | --- | --- |
| `WP89-C1-TOGGLE_TRANSIT` | Bottom-left physical Play through `/api/v1/physical-twin/lab/physical-flight/start` | Exact mode in request, status, operation marker, and disabled active control | Captured request/status; boolean, numeric, alias, null, observation, arm/disarm, acrobatics, and active-retoggle cases | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` |
| `WP89-C2-DYNAMIC_POLICY` | Fresh per-variable Crazyflie observation plus requested motion | Per-ray closing speed/margin, binding ray, measured uncertainty, safe speed, decision | Independent zero/equality/adjacent/minimum/maximum/high-variance/yaw-rotation/moving-away vectors and monotonic perturbations | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE` |
| `WP89-C3-PHYSICAL_COMMAND_GUARD` | Contained-flight command helper and adapter sample loop | Unchanged monitor payload, retimed enforced move, pre-dispatch block, or existing abort/land | Fake-link command capture for nominal, retimed, invalid/stale, below-floor, moving-away, hover-drift, and mid-command loss | `PRODUCTION_ENTRY / FAST_SIM / ACCELERATED` |
| `WP89-C4-RETAINED_TRUTH` | Status polling, command evidence, telemetry artifact, and marker reload | Mode, evaluation count, minimum margin, binding ray, last decision, and intervention reason | Marker restart/reload and terminal artifact comparison after normalizing run-local identity/timing | `INTEGRATION / FAST_SIM / ACCELERATED` |

### Complete guard and counterexample registry

The design oracle derives these semantic categories from the retained request,
requirements, and matrix: typed mode authority; range validity; range freshness;
kinematic freshness; estimator uncertainty; vehicle/sensor geometry; complete reaction
latency; braking authority; speed cap/floor; post-dispatch recovery; and retained
truth. Each has at least one isolated perturbation while the remaining inputs pass.

Required vectors include exact zero, `0.02`, `0.05`, and `0.10 m/s` relations;
equality, `-1e-6 m`, and `+1e-6 m` clearance; yaw `0` and `pi/2`; moving away;
stale/missing/`NO_HIT`/`CLIPPED`/out-of-range; stale yaw, vx, vy, and variance;
missing variance; a high-variance state; `0.10 m` retimed from one to two seconds at
the exact `0.05 m/s` boundary; monitor command identity; and mid-command clearance
loss selecting outcome-unknown plus existing abort/land. Detour, certified hold,
retreat, and no-certificate hold vectors are inapplicable because those capabilities
are explicitly excluded, not silently passed.

### Independently derived affected-boundary closure

`scripts/audit_wp89_design.py` derives claim keys from this matrix, generated outputs
from `ui/package.json`, and production/test transit paths by scanning for the public
request, API start, Crazyflie raw/link, component, and route symbols. It compares
those independently derived sets with the paths declared here and freezes every
preimage or intended-new state:

- policy/sensor/link: `src/crazyswarm_app/safety/avoidance.py`,
  `src/crazyswarm_app/domain/telemetry.py`,
  `src/crazyswarm_app/vehicles/crazyflie.py`,
  `src/crazyswarm_app/vehicles/crazyflie_link.py`, and
  `src/crazyswarm_app/vehicles/_cflib_link.py`;
- physical owners/transits: `src/crazyswarm_app/hardware/basic_flight_lab.py`,
  `src/crazyswarm_app/hardware/controller_tuning_lab.py`,
  `src/crazyswarm_app/hardware/observation_twin.py`, and
  `src/crazyswarm_app/api/app.py`;
- UI/public/generated: `ui/app/components/TwinBasicFlightLab.tsx`,
  `ui/app/components/ControlCenter.tsx`, `ui/app/lib/api.ts`,
  `ui/app/lib/models.ts`, `ui/app/globals.css`, `ui/openapi.json`, and
  `ui/app/lib/api.generated.ts`;
- tests: `tests/safety/test_avoidance.py`,
  `tests/hardware/test_basic_flight_lab.py`,
  `tests/hardware/test_controller_tuning_lab.py`,
  `tests/hardware/test_crazyflie_adapter.py`,
  `tests/hardware/test_observation_twin_service.py`,
  `tests/api/test_physical_twin.py`, `ui/tests/api-adapter.test.ts`, and
  `ui/tests/twin-basic-flight-lab.test.tsx`, and
  `ui/tests/control-api-timeout.test.ts`;
- durable maps and generator inputs: `design.md`, `docs/system/README.md`, and
  `scripts/export_openapi.py`.

The retained R1 artifact is
`missions/campaigns/real/qualification/wp89-design-audit-r1.json`. It contains the
exact boundary manifest, claim/category closure, typed aliases, clocks and latency
budgets, complete numerical vectors, resulting commands/recovery actions, and payload
identity. Its `--check` mode compares byte-for-byte without rewriting.

### Exit gates and implementation limits

1. The same design verifier reproduces the R1 payload/artifact and returns
   `DESIGN_VERIFIED` before implementation.
2. Independent policy tests recompute the formulas without importing implementation
   expected values and cover every frozen vector and monotonic direction.
3. API/UI tests prove exact request/status/marker transit, default, lockout, scope
   exclusions, and strict alias rejection through normal entry points.
4. Fake Crazyflie integration proves per-variable freshness, monitor command identity,
   progressive retiming, blocked dispatch, and mid-command existing abort/land.
5. The isolated run uses only injected links and a temporary cache/evidence store.
   It records `FAST_SIM / ACCELERATED`; hardware and observed realtime remain
   `NOT_RUN`.
6. Generated OpenAPI/types, focused Python/UI suites, Ruff, TypeScript, ESLint,
   requirement catalog, project map, and whitespace checks pass. Failures outside the
   scoped manifest remain explicit.
7. Implementation completion language is limited to this WP-89 slice. The originating
   general avoidance and hold/retreat hierarchy remains open.

<!-- WP89-R1-DESIGN-PAYLOAD-END -->

### WP-89 R1 focused-recheck handoff

- Initial review: one; consolidated correction: one; focused recheck: pending.
- Initial payload SHA-256:
  `fe259a07bf682c45b731104f66be235281db15e752ad3dd45ab40270c6e41512`.
- Initial retained artifact SHA-256:
  `5d003f99b4eb74ac629375b617a3b3f8d7039f1019e7cbfb015a1b4c93d9f9cd`.
- Findings addressed: `WP89-D1` per-variable freshness and measured uncertainty;
  `WP89-D2` clocks, latency breakdown, inverse/command/recovery vectors, and isolated
  guards; `WP89-D3` current exact preimages and independently derived transit closure;
  `WP89-D4` verbatim request plus explicit partial-slice status.
- Author model/effort remains frontier safety/control reasoning; exact tokens, effort,
  and wall time are not exposed. Cost proxies: one review, one correction, zero runtime
  or hardware runs.
- R1 payload SHA-256:
  `18a7d8186543ba688c52fdabe4a196998f5eecbf860827b804ce1317e3ff4089`.
- R1 audit artifact SHA-256:
  `2572e5e7ac90130705d1734a1bd2f6d3576ef0da41a17f65916c9452fadbf094`;
  `--check` reproduces byte-for-byte with 31 exact boundaries and zero errors.

### WP-89 final design-gate outcome

Status: `REVIEW_BLOCKED`

Independent verification: `BLOCKED_WITH_FINDINGS`

- Reviewer: `/root/wp89_design_verifier`; initial review: one; consolidated
  correction: one; focused recheck: one. The permitted design cycle is exhausted.
- Resolved: `WP89-D1` per-variable kinematic/range/variance freshness and measured
  two-sigma position uncertainty; `WP89-D4` verbatim originating request and truthful
  partial-slice boundary.
- Remaining `WP89-D2` (P1 `MUST_FIX_NOW`, C2/C3): the improved pre-freeze oracle still
  declares its guard categories rather than deriving a complete
  source-to-category-to-metric map. It lacks isolated executable perturbations for
  geometry, braking authority, retained truth, negative/non-finite variance, partial
  timestamp maps, negative clock age, and the existing recovery production trace.
- Remaining `WP89-D3` (P1 `MUST_FIX_NOW`, exact design identity): during the focused
  recheck, concurrent preimages changed for
  `src/crazyswarm_app/vehicles/_cflib_link.py` (current prefix `c383352e`, retained
  `9cee7837`) and `src/crazyswarm_app/vehicles/crazyflie_link.py` (current prefix
  `42c68007`, retained `03b35add`). The required `--check` therefore became stale and
  no longer identifies the current implementation base.
- Verdict: `BLOCKED_WITH_FINDINGS`. No implementation, isolated runtime run, service
  restart, radio connection, motor action, or physical flight is authorized by this
  packet. A successor design needs explicit operator authorization and a fresh bounded
  gate; it may address only the two remaining P1 scopes.

## WP-90 — WP-89 D2/D3 successor correction

Status: `PLANNED`

Independent verification: `DRAFT_UNVERIFIED`

Operator authorization: `2026-08-27`, verbatim: “WP-89 successor correction for D2
and D3”.

<!-- WP90-DESIGN-PAYLOAD-START -->

### Scope and inherited design

WP-90 is limited to the two authorized residuals:

- `D2`: replace the declared guard list with a mechanically closed
  source-to-category-to-metric registry, one whole-pass input, one isolated sensitive
  failure per binding metric, complete numerical command vectors, and an executable
  injected-link trace of the existing abort/land fallback plus its landing-failure
  counterexample.
- `D3`: bind the current implementation base through exact file hashes and
  syntax-delimited hashes for the two shared link files, so unrelated edits outside
  the receive-timestamp contract do not invalidate the gate while changes to the
  relevant raw-sample/log-callback sections do.

All product behavior, constants, limitations, original operator requests, claim
matrix, and exit gates in the WP-89 R1 payload with SHA-256
`18a7d8186543ba688c52fdabe4a196998f5eecbf860827b804ce1317e3ff4089`
are incorporated unchanged. In particular this remains a partial physical-laboratory
slice: `MONITOR_ONLY` versus `ENFORCED`, dynamic ranger limiting, and existing
controlled abort/land after an unsafe dispatched sample. It is not certified
stop-and-hold, retreat, general avoidance, mapping, hardware qualification, or
observed-realtime evidence.

### Independently derived semantic sources

The successor audit extracts these source IDs and required categories from this table
before reading its metric registry:

| Source ID | Immutable source meaning | Required categories |
| --- | --- | --- |
| `SRC-OP-SENSOR` | Operator: reject stale, missing, and out-of-range sensor data | `RANGE_VALIDITY`, `RANGE_FRESHNESS` |
| `SRC-OP-PROJECTION` | Operator: project drone velocity toward each sensed obstacle | `KINEMATIC_VALUE`, `KINEMATIC_FRESHNESS` |
| `SRC-OP-DISTANCE` | Operator: radius + uncertainty + latency travel + braking + margin | `ESTIMATOR_UNCERTAINTY`, `GEOMETRY`, `LATENCY`, `BRAKING` |
| `SRC-OP-LIMIT` | Operator: progressively limit speed as clearance decreases | `SPEED_LIMITING` |
| `SRC-OP-TOGGLE` | Operator: on/off toggle beside bottom-left Play | `MODE_AUTHORITY` |
| `SRC-RPL-012` | Runtime urgency depends on clearance, speed, uncertainty, authority, and full latency | `GEOMETRY`, `LATENCY`, `BRAKING`, `SPEED_LIMITING` |
| `SRC-WFL-017-024-048` | Production claims need retained observation, independent oracle, adverse path, clocks, geometry, and resulting command | `RECOVERY_TRACE`, `RETAINED_TRUTH` |
| `SRC-WP89-D1` | Resolved contract requires fresh yaw/vx/vy/variance and measured 2-sigma uncertainty | `KINEMATIC_VALUE`, `KINEMATIC_FRESHNESS`, `ESTIMATOR_UNCERTAINTY` |

No metric category may exist without one of those sources, and every required category
must contain at least one binding metric. The machine artifact retains exact metric
definitions, pass direction, source IDs, and mutations.

### Complete metric and isolated-vector contract

The registry distinguishes every binding subclause rather than collapsing a category:

- exact mode enum and monitor-only payload identity;
- range status, presence, finiteness, nonnegativity, strict below-maximum bound,
  receive-timestamp presence, nonnegative clock age, and `<=0.4 s` age;
- yaw, vx, and vy presence, finiteness, per-variable timestamp presence, nonnegative
  age, and maximum age independently;
- varPX and varPY presence, finiteness, nonnegativity, timestamp presence,
  nonnegative age, and maximum age independently;
- positive vehicle radius, sensor offset bounded inside the vehicle radius,
  nonnegative range uncertainty and margin;
- nonnegative accepted-age, host, transport/ack, and onboard-commit latency components;
- positive acceleration and jerk authority; positive speed cap; controllable floor
  inside the cap; monotonic inverse safe speed; displacement-preserving retiming;
- successful fallback land dispatch, grounded confirmation, and fail-closed
  `stop_required=true` when landing acknowledgement fails;
- retained exact mode, decision, evaluation count, minimum margin, binding ray, and
  intervention reason.

One canonical whole-pass input satisfies every metric. For each metric, exactly one
input is perturbed while all other inputs remain the canonical pass values. The
independent design evaluator must report exactly that metric and no other failure.
Required aliases include missing, `NaN`, negative, equality/just-over bounds,
partial timestamp maps, and negative clock age.

### Numerical and command oracle

The corrected audit independently evaluates the unchanged WP-89 formula and freezes:

- speeds `0`, `0.02`, `0.05`, and `0.10 m/s`;
- exact required-range equality and `±1e-6 m` perturbations;
- yaw `0` and `pi/2`, closing and moving-away rays;
- higher latency and higher estimator variance monotonicity;
- `0.10 m` displacement at `0.10 m/s` unchanged with ample clearance;
- the same displacement retimed from `1.0` to `2.0 s` at the exact `0.05 m/s`
  safe-speed boundary;
- below-`0.02 m/s` pre-dispatch block;
- `MONITOR_ONLY` byte-equivalent command projection;
- post-dispatch clearance loss mapped to outcome-unknown and the existing
  controlled abort/land recovery.

Expected values come from the successor's independent prototype, not from the future
implementation.

### Executable existing-recovery trace

Before design review, the audit executes these existing production-entry tests with
injected links and a temporary cache/evidence store:

- `tests/hardware/test_basic_flight_lab.py::test_airborne_stability_guard_uses_existing_failure_abort_and_land_path`
  enters `BasicFlightLabService.run_physical`, creates an airborne adverse sample,
  asserts one landing command, and independently confirms the firmware flying bit is
  clear.
- `tests/hardware/test_basic_flight_lab.py::test_recovered_observer_ground_state_clears_unconfirmed_abort`
  perturbs landing acknowledgement to fail, asserts `FAILED` with
  `stop_required=true` and outcome-unknown, then confirms only a fresh grounded
  observation reconciles the stop.

The retained artifact records the exact command, test node IDs, exit code, and
normalized semantic result without nondeterministic test duration. These tests run
without hardware-authority environment variables and cannot open the radio.

### Stable exact preimage identity

The affected-boundary closure remains the independently discovered WP-89 R1 set.
Existing implementation files receive exact full-file preimage hashes except:

- `src/crazyswarm_app/vehicles/crazyflie_link.py` is preservation-only and binds the
  syntax-delimited `CrazyflieRawSample` class containing
  `value_received_at_monotonic_s`;
- `src/crazyswarm_app/vehicles/_cflib_link.py` is preservation-only and binds
  `LOG_GROUPS`, `CflibCrazyflieLink._cached_sample`, and
  `CflibCrazyflieLink._on_log_data`.

The successor implementation is forbidden to edit either preservation-only link file.
Any change to a bound section invalidates the design. Unrelated changes elsewhere in
those already-dirty files are outside the payload identity and remain operator-owned.
Every intended-new path is frozen as absent. The design payload hash excludes its
verification record and self-referential artifact.

`scripts/audit_wp90_design.py` extracts the source/category table, derives the
required category universe independently of the metric registry, checks exact
source/category/metric coverage, executes every isolated vector, computes numerical
and command outputs, runs the two injected-link recovery tests, derives generated
outputs and production transit, and freezes the full/section preimages in
`missions/campaigns/real/qualification/wp90-design-audit.json`.

### Successor exit and stop rules

1. A fresh `work_packet_verifier` reproduces the payload, audit, preimages, 60-metric
   whole-pass/isolated-failure matrix, and recovery trace before returning
   `DESIGN_VERIFIED`.
2. One consolidated correction and one focused recheck are the maximum for WP-90.
3. After design verification, implementation may change only the R1 implementation
   owners that are not preservation-only, must derive its tests from the frozen metric
   and claim matrices, and remains `IMPLEMENTED_UNVERIFIED` until a different fresh
   implementation verifier accepts the exact manifest.
4. Author and verifier runs use injected links only. No persistent service restart,
   hardware deployment, radio connection, motor command, or flight is authorized.
5. Any missing category/metric/vector, non-isolated mutation, stale bound section,
   failed recovery trace, or claim beyond the partial slice blocks the smallest
   affected gate.

<!-- WP90-DESIGN-PAYLOAD-END -->

### WP-90 design-review handoff

- Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.
- Author model/effort: frontier safety/control reasoning due the command-recovery
  boundary and prior P1 findings; exact token/time/effort counters are unavailable.
- Review/correction/runtime proxies before review: zero reviews, zero corrections, one
  packet, two authorized residual findings, two injected-link recovery test nodes,
  zero live-runtime/hardware runs.
- Independent verification remains `DRAFT_UNVERIFIED` until the frozen identities
  below are reproduced.
- WP-90 payload SHA-256:
  `d1ebe1a395856fe52b520ea426fcf5eb977840f7646cc5c9b7ae3b3f38b4be0b`.
- WP-90 audit artifact SHA-256:
  `dc49c57a4740da542b7145e8bbd9557bde673add60f500b2c590bdb5cb01c3a7`.
- Pre-freeze result: `PASS`; 12 independently derived categories, 60 unique metrics,
  one whole-pass input, 60 exact isolated failures, 32 exact boundaries, and two
  injected-link recovery nodes passed. Hardware/realtime evidence remains `NOT_RUN`.

## WP-90 R1 — consolidated oracle independence and lifecycle-identity correction

Status: `PLANNED`

Independent verification: `DRAFT_UNVERIFIED`

This is WP-90's single permitted correction for `WP90-D2A`, `WP90-D2B`, and
`WP90-D3A`. The initial successor payload remains retained above; this payload
supersedes it for implementation eligibility without changing the inherited product
behavior or scope.

<!-- WP90-R1-DESIGN-PAYLOAD-START -->

### Frozen inherited behavior

The complete WP-89 R1 behavior remains incorporated at SHA-256
`18a7d8186543ba688c52fdabe4a196998f5eecbf860827b804ce1317e3ff4089`.
The operator-authorized successor scope remains only D2/D3: oracle completeness and
exact current preimage identity. No stop-and-hold, retreat, general avoidance, mapping,
hardware, realtime, or deployment claim is added.

### Source-derived binding schema

The audit reads the originating-request and durable-requirement meanings below, then
derives the category universe and binding schema before constructing any candidate
metric registry:

| Source ID | Source meaning | Categories |
| --- | --- | --- |
| `SRC-OP-SENSOR` | reject stale, missing, and out-of-range sensor data | `RANGE_VALIDITY`, `RANGE_FRESHNESS` |
| `SRC-OP-PROJECTION` | project measured and commanded drone velocity toward each sensed obstacle | `KINEMATIC_VALUE`, `KINEMATIC_FRESHNESS` |
| `SRC-OP-DISTANCE` | radius + uncertainty + latency travel + braking + margin | `ESTIMATOR_UNCERTAINTY`, `GEOMETRY`, `LATENCY`, `BRAKING` |
| `SRC-OP-LIMIT` | progressively limit speed as clearance decreases | `SPEED_LIMITING` |
| `SRC-OP-TOGGLE` | exact on/off control beside Play | `MODE_AUTHORITY` |
| `SRC-RPL-012` | clearance, speed, uncertainty, authority, and full reaction latency bind urgency | `GEOMETRY`, `LATENCY`, `BRAKING`, `SPEED_LIMITING` |
| `SRC-WFL-017-024-048` | production effect, retained observation, independent oracle, adverse recovery, exact clocks/geometry/resulting command | `RECOVERY_TRACE`, `RETAINED_TRUTH` |
| `SRC-WP89-D1` | fresh range/yaw/vx/vy/variance, host clock ordering, measured 2-sigma uncertainty | `RANGE_FRESHNESS`, `KINEMATIC_VALUE`, `KINEMATIC_FRESHNESS`, `ESTIMATOR_UNCERTAINTY` |

The machine-readable schema parsed from this payload is:

<!-- WP90-R1-BINDING-SCHEMA-START -->
```json
{
  "mode": ["exact_enum", "monitor_input_output_identity"],
  "range": ["status_valid", "value_present", "value_finite", "value_nonnegative", "max_present", "max_finite", "max_positive", "value_strictly_below_max", "timestamp_present", "timestamp_finite", "age_nonnegative", "age_at_most_0_4"],
  "measured_kinematics": {
    "yaw": ["present", "finite", "timestamp_present", "timestamp_finite", "age_nonnegative", "age_at_most_0_4"],
    "vx": ["present", "finite", "timestamp_present", "timestamp_finite", "age_nonnegative", "age_at_most_0_4"],
    "vy": ["present", "finite", "timestamp_present", "timestamp_finite", "age_nonnegative", "age_at_most_0_4"]
  },
  "commanded_kinematics": {
    "frame": ["exact_BODY_or_HOME"],
    "vx": ["present", "finite"],
    "vy": ["present", "finite"]
  },
  "clock": {
    "evaluation_time": ["present", "finite"],
    "maximum_age": ["present", "finite", "nonnegative"]
  },
  "variance": {
    "varPX": ["present", "finite", "nonnegative", "timestamp_present", "timestamp_finite", "age_nonnegative", "age_at_most_0_4"],
    "varPY": ["present", "finite", "nonnegative", "timestamp_present", "timestamp_finite", "age_nonnegative", "age_at_most_0_4"]
  },
  "geometry": ["radius_positive", "sensor_offset_inside_radius", "range_uncertainty_nonnegative", "margin_nonnegative"],
  "latency": ["sample_age_nonnegative", "host_nonnegative", "transport_ack_nonnegative", "onboard_commit_nonnegative"],
  "braking": ["acceleration_positive", "jerk_positive"],
  "speed": ["cap_positive", "floor_inside_cap", "inverse_monotonic", "retime_preserves_displacement"],
  "recovery": ["one_land_dispatched", "ground_confirmed", "landing_failure_retains_stop_required"],
  "evidence": ["mode_exact", "decision_enum", "evaluation_count_positive_integer", "minimum_margin_finite", "binding_ray_enum", "intervention_reason_enum"]
}
```
<!-- WP90-R1-BINDING-SCHEMA-END -->

The schema mechanically expands to exactly 79 unique metrics. No separately authored
expected-category constant is permitted. Exact set equality is checked among schema
rules, generated metric IDs, source coverage, one whole-pass vector, and 79 isolated
mutations. Removing or adding any rule fails the audit.

### Independent inputs, candidate outputs, and isolated sensitivity

The canonical input contains raw values and candidate outputs, never pass booleans:

- finite evaluation time and maximum age;
- full/partial per-variable timestamp maps;
- range value/status/maximum;
- measured HOME yaw/vx/vy and explicit commanded BODY/HOME vx/vy;
- asymmetric varPX/varPY, geometry, uncertainty, latency, acceleration, jerk, speed
  cap/floor, clearance vectors, and requested command;
- candidate per-ray projection, per-clearance safe-speed vector, transformed command,
  monitor output payload, decision evidence, and structured recovery observation.

The independent evaluator recomputes yaw rotation, measured/commanded ray projections,
2-sigma uncertainty, required range, inverse safe speed, action, retimed duration,
displacement/direction preservation, and canonical payload hashes. Each isolated vector
changes exactly one raw input or candidate output and must produce exactly its one
metric failure.

Additional one-variable admissible numerical witnesses hold all other values fixed:

- radius `0.055 -> 0.065 m` increases required range;
- sensor offset `0.012 -> 0.010 m` increases required range;
- acceleration `1.0 -> 0.8 m/s^2` increases stopping distance;
- jerk `8.0 -> 6.0 m/s^3` increases stopping distance;
- varPX `0.0004 -> 0.0025 m^2` with unchanged varPY raises 2-sigma uncertainty
  from `0.05` to `0.10 m`;
- latency `0.8 -> 1.0 s` increases required range;
- less clearance never increases safe speed.

Projection and action fields in the retained artifact are computed outputs, not labels:
yaw `0`, yaw `pi/2`, moving-away, commanded-closing-only, ample-clearance
`CLEAR`, exact half-speed `LIMIT`, below-floor `BLOCK_BEFORE_DISPATCH`, monitor
identity, and post-dispatch certificate loss mapped through the observed recovery
contract.

### Structured production recovery oracle

The audit invokes `BasicFlightLabService.run_physical` and
`BasicFlightLabService.start_physical_flight/abort_physical_flight` directly with
injected `FakeCrazyflieLink` instances, temporary cache/evidence paths, and no
hardware-authority environment.

The nominal adverse-hover probe returns independently observed fields:
`exception_code=PREFLIGHT_FAILED`, `trigger=near_floor`, exact command kinds,
`land_count=1`, and `flying=false`. The landing-acknowledgement perturbation returns
`state=FAILED`, `stop_required=true`, and final
`command_phase=OUTCOME_UNKNOWN`. Each recovery metric compares its own structured
field; no recovery fact is inferred merely from one pytest exit code. The two existing
pytest nodes remain an adjacent regression check, not the source of these facts.

### Current-path and timestamp-lifecycle identity

Boundary closure is re-derived from current sources, not copied from a WP-89 artifact:

1. extract implementation paths and four claim keys from the inherited WP-89 R1
   payload;
2. scan current Python/UI/test sources for the public request, API route/start method,
   physical service, Crazyflie raw/link/adapter, and component symbols;
3. derive `ui/openapi.json` and `ui/app/lib/api.generated.ts` from
   `ui/package.json`;
4. require exact equality between discovered transits/generated outputs and the
   current manifest.

All existing non-link boundaries receive current full-file hashes. The two
preservation-only link files receive syntax-delimited hashes for every relevant
timestamp lifecycle section:

- `src/crazyswarm_app/vehicles/crazyflie_link.py`:
  `CrazyflieRawSample`;
- `src/crazyswarm_app/vehicles/_cflib_link.py`: `LOG_GROUPS`,
  `CflibCrazyflieLink.__init__`, `CflibCrazyflieLink.connect`,
  `CflibCrazyflieLink.restart_observation_logs`,
  `CflibCrazyflieLink._cached_sample`,
  `CflibCrazyflieLink._start_logs`, and
  `CflibCrazyflieLink._on_log_data`.

Implementation remains forbidden to edit either preservation-only file. A change to
any bound syntax section invalidates the design; unrelated edits elsewhere in those
already-dirty operator-owned files do not.

`scripts/audit_wp90_design.py` extracts this R1 schema/source table, generates and
executes the 79-metric oracle, runs structured and pytest recovery probes, derives
current paths/generated outputs, and retains exact identities in
`missions/campaigns/real/qualification/wp90-design-audit-r1.json`.

### R1 exit rules

1. The same verifier reproduces the R1 payload and artifact, confirms all initial
   findings resolved, and returns `DESIGN_VERIFIED`; otherwise WP-90 remains blocked.
2. Implementation may begin only after that verdict, changes no preservation-only
   file, and stays within the inherited partial-slice behavior.
3. Author checks and the one isolated software run use injected links only. A different
   fresh verifier owns the implementation gate.
4. No live service restart, hardware deployment, radio connection, motor command, or
   flight is authorized.

<!-- WP90-R1-DESIGN-PAYLOAD-END -->

### WP-90 R1 focused-recheck handoff

- Initial successor review: one; consolidated correction: one; focused recheck:
  pending.
- Initial payload:
  `d1ebe1a395856fe52b520ea426fcf5eb977840f7646cc5c9b7ae3b3f38b4be0b`.
- Initial artifact:
  `dc49c57a4740da542b7145e8bbd9557bde673add60f500b2c590bdb5cb01c3a7`.
- Correction is limited to `WP90-D2A`, `WP90-D2B`, and `WP90-D3A`; no product
  behavior or optional scope changed.
- R1 payload SHA-256:
  `7640512cac6eead362a0211cb7acefb6615898329e7aa4efe379d8c3f4bbe43d`.
- R1 audit artifact SHA-256:
  `6673a2c4a88453042a6dae724308727c0ec8084c040855040d8c06f067a5a0ee`.
- R1 pre-freeze result: `PASS`; 79 schema-derived metrics, one whole pass, 79 exact
  isolated failures, structured nominal/failure recovery observations, two adjacent
  injected-link tests, computed projections/actions/command transforms, current-path
  derivation, and eight preservation-only timestamp lifecycle sections.

### WP-90 final design-gate outcome

Status: `REVIEW_BLOCKED`

Independent verification: `BLOCKED_WITH_FINDINGS`

- Reviewer: `/root/wp90_design_verifier`; initial review: one; consolidated
  correction: one; focused recheck: one. The successor design cycle is exhausted.
- Resolved: `WP90-D3A` current production/generator derivation and exact relevant
  timestamp-lifecycle section identities; structured nominal/failure recovery evidence;
  finite/partial/negative-clock and invalid-value mutations; D2/D3 scope containment.
- Remaining `WP90-R1-D2A` (P1 `MUST_FIX_NOW`): schema leaves and metrics have equal
  counts but no exact rule-identity mapping, so a renamed/omitted semantic rule can
  leave the gate passing. Three declared source/category pairs also have no metric
  linkage.
- Remaining `WP90-R1-D2B` (P1 `MUST_FIX_NOW`): retained evidence accepts type-valid but
  semantically wrong mode-relative decisions, counts, margins, rays, and reasons. The
  variance witness does not independently exercise asymmetric varPX/varPY; HOME-frame
  yaw projection and yaw-preserving retiming are not frozen.
- Verdict: `BLOCKED_WITH_FINDINGS`. Implementation and the implementation-verification
  run remain unauthorized. No persistent service restart, hardware deployment, radio
  connection, motor command, or physical flight occurred.
- Any further design work requires a new explicit operator-authorized successor and
  may address only `WP90-R1-D2A` and `WP90-R1-D2B`.

## WP-91 — final bounded WP-90 D2 closure

Status: `IMPLEMENTED`

Independent verification: `IMPLEMENTATION_VERIFIED`

Operator authorization: `2026-08-27`, verbatim: “ok then continue with one run,
after that do the implementation and verify once and then analze what is missing i
cannot do so many work package iterations”.

Review budget: exactly one design review with no automatic correction/recheck. On a
passing design verdict, implement immediately, run one isolated injected-link author
verification, then use one different independent implementation verifier with no
automatic correction/recheck and analyze residual gaps.

<!-- WP91-DESIGN-PAYLOAD-START -->

### Exact bounded scope

WP-91 addresses only `WP90-R1-D2A` and `WP90-R1-D2B`. It incorporates unchanged:

- WP-89 R1 product behavior and limitations at
  `18a7d8186543ba688c52fdabe4a196998f5eecbf860827b804ce1317e3ff4089`;
- WP-90 R1 source schema, structured recovery, current boundary derivation, and
  timestamp-lifecycle identity at
  `7640512cac6eead362a0211cb7acefb6615898329e7aa4efe379d8c3f4bbe43d`;
- the reproduced WP-90 R1 artifact at
  `6673a2c4a88453042a6dae724308727c0ec8084c040855040d8c06f067a5a0ee`.

No product behavior, implementation owner, live-runtime authority, or capability claim
is added except the missing yaw-preservation subclause already promised by the
inherited retiming contract.

### Exact schema-rule identity closure

`scripts/audit_wp91_design.py` flattens every WP-90 R1 binding-schema leaf to its
canonical dotted identity, for example `range.status_valid`,
`measured_kinematics.vx.timestamp_finite`, and
`evidence.minimum_margin_finite`. It extends that schema with exactly
`speed.retime_preserves_yaw`.

An independently constructed rule-to-metric map must satisfy both exact equalities:

- mapping keys = all 80 flattened schema rule identities;
- mapping values = all 79 WP-90 R1 metric IDs plus
  `M_RETIME_YAW`.

Renaming, deleting, duplicating, or adding one rule or metric fails. The retained
artifact contains every rule/metric pair, not only equal cardinalities.

Every declared source/category pair must link to at least one exact metric. In
particular the previously absent links are frozen:

- `SRC-OP-DISTANCE -> LATENCY` links the four latency metrics;
- `SRC-OP-PROJECTION -> KINEMATIC_FRESHNESS` links yaw/vx/vy timestamp and age
  metrics;
- `SRC-WP89-D1 -> KINEMATIC_VALUE` links yaw/vx/vy presence and finite metrics.

The audit compares the complete source/category pair set derived from the payload with
the complete linked pair set; subset or count-only proofs fail.

### Exact retained-evidence oracle

Evidence values are recomputed from the raw canonical observation and command:

- `mode` equals the frozen request mode;
- `decision` equals the independently computed command action;
- `evaluation_count` equals the number of evaluated observations;
- `minimum_margin` equals measured binding-ray range minus independently computed
  required range within `1e-9 m`;
- `binding_ray` equals the ray producing that margin;
- `intervention_reason` is derived from the decision and input validity.

The canonical whole-pass evidence is compared with isolated type-valid wrong values:
`CLEAR -> LIMIT`, count `1 -> 999`, computed margin `->999`, front `->back`,
and `none -> unsafe_closing_speed`. Each must fail only its exact evidence metric.

### Missing generalized numerical and command vectors

1. Asymmetric estimator variance is evaluated from separate varPX/varPY:
   `(0.0025,0.0004)` and `(0.0004,0.0025)` must produce the same `0.10 m`
   2-sigma uncertainty and required range. A minimum-axis implementation produces the
   smaller baseline and fails.
2. Command projection freezes both frames at yaw `pi/2`:
   BODY `(+0.06,0)` binds `front=0.06`; HOME `(+0.06,0)` rotates to body
   `(0,-0.06)` and binds `right=0.06`. Treating HOME as BODY fails.
3. Progressive retiming preserves displacement, direction, and yaw exactly. The
   canonical input/output retain yaw `0.30 rad`; changing only output yaw to
   `0.40 rad` fails `M_RETIME_YAW`.

All values are computed by the design oracle from explicit inputs. No pass boolean,
authored action label, or single scalar variance is accepted as proof.

### Exit and execution rule

1. One fresh verifier reproduces the WP-91 payload/artifact and returns
   `DESIGN_VERIFIED` or `BLOCKED_WITH_FINDINGS`. There is no automatic correction
   or recheck.
2. On `DESIGN_VERIFIED`, implementation begins immediately against the inherited
   owners while preserving the section-bound link files.
3. Author verification is one isolated injected-link software run plus necessary
   static/generated checks; then a different verifier receives the exact manifest once.
4. Regardless of the implementation verdict, handoff analyzes remaining functionality
   and evidence without opening another automatic packet.
5. No dashboard restart, hardware deployment, radio access, motor command, or flight is
   authorized.

<!-- WP91-DESIGN-PAYLOAD-END -->

### WP-91 design-review handoff

- Base commit: `40cd9947f87eb9bf2719d72e7c72ea867eab9977`.
- Accepted-review candidate payload SHA-256:
  `8b31bb73849ea1b9b2bffc63ded11ddf6b36e5bd67d5a95eedf89f87c8013bb6`.
- Reproducible design-audit artifact SHA-256:
  corrected candidate
  `19acf0efa1e7107c841a2af6e1cc889abfd4fb5fa2258f77257d8dcb1c15c81d`.
- Model/effort route: frontier reasoning because this is the final safety-oracle gate;
  exact tokens/time/effort are unavailable.
- Cost proxies: one packet, two residual findings, zero permitted design corrections,
  one planned design review, one planned isolated author run, one planned
  implementation review, zero hardware runs.

### WP-91 final design-gate outcome

- Reviewer: `/root/wp91_design_verifier`; exactly one review, with no correction or
  recheck, as authorized.
- P1 `WP91-D1`: the recorded artifact identity has an extra leading `2`, so the exact
  supplied artifact identity is not reproducible.
- P1 `WP91-D2A`: source/category closure checks only for a nonempty list; replacing a
  linked metric with unknown `M_NOT_A_REAL_METRIC` can still pass.
- P1 `WP91-D2B`: retained evidence chooses the maximum closing-speed ray from one
  scalar range instead of the minimum margin across per-ray ranges, and missing range
  input raises rather than deriving `invalid_binding_input`.
- Verdict: `BLOCKED_WITH_FINDINGS`. The design review budget is exhausted, so no
  implementation, author run, implementation review, dashboard restart, hardware
  deployment, radio connection, motor command, or physical flight followed.

### WP-91 operator-authorized consolidated correction

- Authorization: `2026-08-27`, verbatim: “fix the issues in the work packet and then i
  need you to start implementing the shit!!” The follow-up requires the corrected
  pre-implementation state to be committed and pushed before implementation begins on
  a new branch.
- Scope remains exactly `WP91-D1`, `WP91-D2A`, and `WP91-D2B`; no product behavior or
  implementation owner changed. The delimited design payload remains byte-identical at
  `8b31bb73849ea1b9b2bffc63ded11ddf6b36e5bd67d5a95eedf89f87c8013bb6`.
- `WP91-D1`: the handoff artifact identity is corrected to the actual original
  `19acf0efa1e7107c841a2af6e1cc889abfd4fb5fa2258f77257d8dcb1c15c81d`.
- `WP91-D2A`: every linked metric is checked against the exact canonical 80-metric
  identity set, duplicate identities within a source/category list fail, the complete
  linked union must have no missing or extra identity, and replacement with
  `M_NOT_A_REAL_METRIC` is a retained failing mutation.
- `WP91-D2B`: the oracle accepts four separate ray ranges, selects the minimum
  `measured_range(ray) - required_range(ray)`, retains the front/right reviewer
  counterexample, and derives `invalid_binding_input` for a missing ray without an
  exception.
- Corrected audit program SHA-256 after the focused correction:
  `c001d41ded7273114f0a29595107c43499750bee4514feae0123798b60848023`.
- Corrected reproducible artifact:
  `missions/campaigns/real/qualification/wp91-design-audit.json`, SHA-256
  `afff2b12729789415881ad9e1a0d7b811bf1b18d13fbb35cb50d579fdcae619d`;
  generation and byte-check both pass.
- Initial correction review: `/root/wp91_final_design_verifier` returned
  `BLOCKED_WITH_FINDINGS` with two P1s. A duplicated flattened rule was hidden by set
  comparison, and a canonical-but-wrong metric could be moved into
  `SRC-OP-DISTANCE/LATENCY` without failing exact per-pair identity.
- Focused correction: the audit now rejects non-unique flattened rule lists and
  compares every source/category metric set with the exact frozen mapping. It retains
  both the duplicated-rule mutation and the canonical-but-wrong `M_MODE_ENUM`
  replacement as passing negative probes.
- The same verifier receives one focused recheck of only these two findings. A passing
  verdict changes the separate verification field to `DESIGN_VERIFIED`; a blocking
  verdict stops implementation. No third automatic review is authorized.

### WP-91 corrected design-gate outcome

- Verifier: `/root/wp91_final_design_verifier`; one initial correction review, one
  focused correction, and one focused recheck. No third review is permitted.
- The accepted payload remains
  `8b31bb73849ea1b9b2bffc63ded11ddf6b36e5bd67d5a95eedf89f87c8013bb6`.
- The verifier reproduced the corrected script and artifact hashes, generated a
  byte-identical temporary artifact, and confirmed the baseline audit remains `PASS`.
- Duplicate inherited `speed.retime_preserves_displacement` produces 81 flattened
  rules, 80 unique identities, and `FAIL` with the exact duplicate-rule error.
- Replacing the exact `SRC-OP-DISTANCE/LATENCY` member with canonical-but-wrong
  `M_MODE_ENUM` produces the exact per-pair metric-identity mismatch.
- Verdict: `DESIGN_VERIFIED`. Product implementation is authorized only after the
  requested checkpoint commit/push and creation of a new implementation branch. The
  hardware/runtime prohibitions remain unchanged.

### WP-91 implementation handoff

- The complete pre-implementation tree was committed as
  `da6d73ab7ddbea20d64dfe4d378ed8bd98757b88` and pushed to
  `origin/codex/1d-replanning-digital-twin`; implementation then began on the new
  `codex/wp91-obstacle-avoidance` branch from that exact commit.
- Exact implementation payload SHA-256:
  `78846eeab2d6ed70c255836bf59117420924cf21b921633da84bf83d6d735ad0`.
  The pre/post file hashes and author evidence are frozen in
  `missions/campaigns/real/qualification/wp91-implementation-manifest.json`.
- The implementation adds the pure per-ray evaluator, monitor/enforced request and
  status transit, pre-dispatch retiming/blocking, guarded hover and translation sample
  loops, existing abort/land recovery, durable marker/evidence retention, generated
  OpenAPI/types, and the bottom-dock switch with its scope exclusions.
- Author verification: 116 focused Python safety/adapter/contained-flight/
  controller-tuning/API tests, 38 UI adapter/component tests, 3 rendered HTML tests,
  strict mypy, Ruff, TypeScript, targeted ESLint, production UI build, project map,
  design audit, and whitespace checks pass. The isolated production trace uses only an
  injected fake link and temporary cache/evidence storage.
- `scripts/check_requirement_catalog.py` retains a pre-existing base failure:
  `REQ-XFR-011` exists while the committed index still declares XFR `10` and total
  `150` instead of `11` and `151`. WP-91 changes no requirement-catalog file.
- Hardware, dashboard service, radio, motors, and physical flight remain
  `NOT_RUN_NOT_AUTHORIZED`. A different fresh verifier receives this manifest once;
  no automatic implementation correction or recheck is authorized.

### WP-91 implementation-gate outcome

- Verifier: `/root/wp91_implementation_verifier`; one frozen implementation review,
  with no correction or recheck, as authorized.
- The verifier reproduced every manifest hash and payload
  `78846eeab2d6ed70c255836bf59117420924cf21b921633da84bf83d6d735ad0`,
  confirmed the pushed checkpoint/branch ancestry and unchanged preservation-only link
  sections, and independently reproduced the declared Python/UI/static/generated
  evidence without hardware access.
- P1 `MUST_FIX_NOW`: `MONITOR_ONLY` takes an unconditional extra pre-dispatch snapshot
  for hover/move. A transient second-read failure prevents dispatch even though the
  base path dispatched before its completion-loop sample, violating the frozen promise
  that monitor mode does not change command ordering, outcome, or recovery.
- P1 `MUST_FIX_NOW`: the exact accepted age boundary is numerically rejected. At
  ordinary monotonic values, `100.0 - 99.6` rounds slightly above `0.4`, so the current
  comparison blocks an authored `age == 0.400000 s` sample; the author test covers only
  `99.599999` and misses equality.
- Residual P2: component/jsdom semantics and generic rendered HTML pass, but no retained
  real-viewport inspection proves switch wrapping, clipping, or the 40 px touch target.
- Verdict: `BLOCKED_WITH_FINDINGS`. The implemented payload remains frozen and
  unverified. Per the explicit review budget, no automatic correction or implementation
  recheck follows; the two P1s and P2 are handed back as the exact remaining work.

### WP-91 operator-authorized implementation correction

- Authorization: `2026-08-28`, verbatim: “Ok continue by fixing the team aiming
  issues”. This new operator instruction authorizes one bounded correction of the two
  P1 findings and the retained-viewport P2, followed by the same verifier's one focused
  recheck. It does not authorize hardware or live-runtime access.
- Monitor transparency: `MONITOR_ONLY` now evaluates the adapter's already-cached
  snapshot and never adds a pre-dispatch link read. A transient second-read failure
  regression proves the move is dispatched in the same order as the avoidance-disabled
  path; only the normal completion refresh then reports the link loss.
- Inclusive age boundary: freshness uses an absolute `1e-12 s` floating-point
  tolerance around the exact `0.400000 s` upper bound while retaining strict negative
  age rejection. The exact `100.0 - 99.6` boundary passes, and samples above the bound
  by `1e-6 s` still fail.
- Viewport evidence: the existing test-only fixture gallery now renders the production
  mission-dock/switch markup and CSS. Retained browser measurements at `1280x720` and
  `390x844` prove a `40 px` switch, stable three-column labels, and no switch or dock
  scroll overflow. Evidence is frozen in
  `missions/campaigns/real/qualification/wp91-viewport-inspection.json`.
- Corrected implementation payload SHA-256:
  `52b7441391b3f3d975c0712b45b53b371edb14216b332453a03137bdbfabbe54`.
  Its 19 exact pre/post file identities and updated author checks replace the blocked
  candidate in `missions/campaigns/real/qualification/wp91-implementation-manifest.json`;
  the initial blocked payload remains recorded there and above for traceability.
- Corrected author verification: 118 focused Python tests, 177 UI unit tests, 3 rendered
  HTML tests, strict mypy, Ruff, TypeScript, ESLint, production UI build, project-map
  check, design audit, and whitespace checks pass. Hardware, dashboard service, radio,
  motors, and physical flight remain `NOT_RUN_NOT_AUTHORIZED`.
- Independent verification remained `IMPLEMENTED_UNVERIFIED` pending the same
  verifier's single focused recheck. Only the monitor-path P1, exact-boundary P1, and
  viewport P2 were in that recheck scope; no third implementation review was
  authorized.

### WP-91 corrected implementation-gate outcome

- Verifier: `/root/wp91_implementation_verifier`; one initial implementation review,
  one operator-authorized correction, and one focused recheck. No third review is
  permitted.
- The verifier reproduced the corrected manifest identity, all 19 pre/post hashes, and
  payload `52b7441391b3f3d975c0712b45b53b371edb14216b332453a03137bdbfabbe54`;
  preservation-only link files remain unchanged.
- Monitor transparency passes an independent transient-second-read probe: exactly one
  move dispatch occurs before the normal completion refresh returns
  `LINK_LOST / UNKNOWN_OUTCOME`, matching the avoidance-disabled ordering.
- The exact `100.0 - 99.6` freshness boundary is accepted; an age greater by `1e-6 s`
  and a negative age are both rejected.
- The authorized viewport fixture/evidence is internally consistent with the production
  classes and CSS. Retained desktop/narrow measurements prove the 40 px target and no
  switch/dock overflow. Residual P2: the verifier had no browser backend available and
  therefore did not independently re-observe the pixels; this does not block the gate.
- Verdict: `IMPLEMENTATION_VERIFIED`. All P0/P1 findings are resolved. Hardware,
  dashboard service, radio, motors, and physical flight remained
  `NOT_RUN_NOT_AUTHORIZED`.
