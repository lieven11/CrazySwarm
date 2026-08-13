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
