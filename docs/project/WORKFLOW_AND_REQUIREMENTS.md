# CrazySwarm workflow and requirements

| Field | Value |
|---|---|
| Status | `ACTIVE` |
| Role | Durable operator requirements, independent work-packet verification, assisted-iteration workflow, and design-feedback memory |
| Baseline | [`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md) |
| Active implementation plan | [`../work-packages/ACTIVE.md`](../work-packages/ACTIVE.md) |
| Last feedback reconciliation | 2026-08-14 |

## Purpose and authority

This file records the durable workflow and requirements learned during operator
review so that the same design preferences and testing method do not have to be
restated for every mission family or feature. It is consulted before a mission
definition, planner behavior, review surface, feature, or work packet is changed.

This document is not a status ledger, frozen interface, or permission to implement.
Open implementation work belongs only in `docs/work-packages/ACTIVE.md`; completed
evidence belongs only in `docs/work-packages/COMPLETED.md`. A requirement added here
must still be translated into a gated work packet before code, mission data, or
campaign state changes.

Precedence is:

1. safety, authorization, and frozen interface contracts;
2. the development guide and system responsibility boundaries;
3. the active work-package ledger;
4. these durable operator requirements; and
5. an individual mission description.

A lower item may specialize a higher item but may not silently weaken it. A conflict
is recorded and resolved explicitly.

## Core design position

- Develop and qualify in simulation first, but define mission intent so that a later
  high-fidelity simulator or physical adapter can execute the same experiment without
  changing what the experiment means.
- Fast Sim evidence establishes deterministic software behavior only. It does not
  establish physical accuracy, motor calibration, contact fidelity, or a digital-twin
  claim.
- Test one main causal variable at a time. Preserve exact configuration, versions,
  backend/model identity, case identity, profile identity, seed, result, and faults.
- Prefer the smallest mission that can validate a primitive. Higher-order missions
  reuse that evidence and test only newly introduced coupling or coordination.
- Treat an authored route as a reference, tolerance tube, required corridor, or exact
  path according to an explicit path-adherence contract. Do not assume every authored
  polyline is either immutable or freely replaceable.
- Let the planner use timing, speed, lateral motion, altitude, or a bounded combination
  only when the selected submission and environment explicitly permit those degrees of
  freedom. Obstacles and occupied volumes remove options; they do not silently force a
  globally preferred strategy.
- Let an operator author, review, and download one resolved submission package that
  contains or references the complete case/world conditions and the requested planning
  authority. A single-file workflow must not collapse immutable obstacle truth and
  mutable planning permission into the same canonical identity.
- A visually plausible run is not enough. The accepted plan, runtime behavior,
  telemetry, evaluation, analysis, replay, and operator-facing explanation must agree.

## Experiment taxonomy

The catalog and evidence model must distinguish the following layers.

| Layer | Meaning | Example | Identity rule |
|---|---|---|---|
| Mission family | Reusable causal learning objective | `altitude_transition` | Groups related cases; does not command flight. |
| Mission case | Immutable problem truth: starts/goals, reference routes, environment and obstacle state, vehicle set, safety bounds, events, and behavior oracles | A head-on encounter in an open room, or the same encounter under a bridge with only an underpass available | A world, event, vehicle, or hard-success-condition change produces a new immutable case/hash. |
| Mission sub-problem | One causal coordination question within a case family | Same-time head-on resolution, merge-corridor capacity, or reaction to a newly observed obstacle | It becomes a case when problem truth changes; it may be exercised by a submission when only admitted planner authority or objective changes. |
| Planning submission | A case-bound request describing the admissible solution space and optimization intent | Earliest safe release, synchronized altitude-layer resolution, bounded lateral detour, or path-fidelity-first planning | Binds the case hash, maneuver authority, path-adherence/deviation limits, coordination policy, objective, optional execution profile, backend support, and submission-specific oracles. |
| Execution profile | A time law or control objective used by a planning submission | Planner baseline, constant path speed, or a bounded segment-speed schedule | Retains its own profile hash and owner layer; it does not grant geometric maneuver or replanning authority. |
| Run | One execution of an exact case/planning-submission/profile/backend/configuration/seed/clock tuple | Realtime repeat 2 of a simultaneous altitude-layer submission | Repetition alone is not a new case, submission, or profile. |

“Submission” is the operator-facing term for a planning submission. The currently
implemented execution-profile submission remains a narrower, hash-bound component for
time/control-law experiments and must remain readable as historical evidence. A
successor planning-submission contract composes, rather than silently reinterprets, an
eligible execution profile. The catalog should first select a mission case and then
show only the planning submissions and profiles admitted for that case. It must not
flatten every combination into a global Cartesian catalog.

The operator-facing submitted request may be transported as one file. That file must
resolve the immutable case/world snapshot, vehicle/model references, planning
submission, and optional execution profile, while retaining a separate canonical hash
for every component and for the resolved package. This preserves the requested
declarative workflow without making an obstacle, tunnel, or hard corridor a mutable
planner preference.

## Durable requirements

### Mission and variation design

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-MIS-001` | Behavior must precede labels. No case or submission may exist only to satisfy a count, naming pattern, compact/wide quota, seed grid, or requested variety. | Semantic fingerprint and retained execution must demonstrate a distinct causal question. |
| `REQ-MIS-002` | Mission problem truth, planning policy, and execution profile must be modeled separately. | The same world can be solved under different admitted maneuver/deviation policies and time laws without duplicating or mutating the case. |
| `REQ-MIS-003` | A variation must change a behavior-driving input, feasible set, accepted trajectory, event, decision, or evidence question. | A description, ID, seed, or display-only change is not a semantic variation. |
| `REQ-MIS-004` | Each proposed case, sub-problem, or submission must pass the variation-admission gate below before implementation. | Prevents unreasoned variety and combinatorial growth. |
| `REQ-MIS-005` | A comparison should change one principal causal variable at a time; secondary changes must be declared and justified. | Makes differences attributable rather than merely observable. |
| `REQ-MIS-006` | Every admitted planning submission and selected execution profile must have stable identifiers and canonical hashes included in plan, runtime command authority, evidence, evaluation, analysis, replay, and download. | Prevents a catalog choice from becoming an unrecorded runtime setting. |
| `REQ-MIS-007` | Experimental planning submissions and evidence profiles are mission-specific and are not copied into every catalog case. The qualified implementation beneath them must live once in its owning core capability layer and be bound at planning time when a mission requirement requests it. | A synchronized vertical-layer experiment may be case-specific, while a learned constant-speed time law must remain reusable without adding a new submission or copying code into each mission. |
| `REQ-MIS-008` | Unsupported or scientifically premature planning submissions or profiles remain `PLANNED_NOT_EXECUTABLE` and fail closed before provisioning. | A label must never imply that a backend can execute or qualify behavior it does not support. |
| `REQ-MIS-009` | Existing cases and retained runs remain immutable. Successor cases, planning submissions, and profiles reference their baselines instead of rewriting historical evidence. | Preserves traceability across design iterations. |

### Primitive reuse and curriculum progression

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-REU-001` | Validate a motion, controller, landing, event, or protocol primitive at the lowest meaningful mission level. | A one-drone constant-path-speed primitive should not be re-tuned from scratch inside every fleet mission. |
| `REQ-REU-002` | Higher-level cases must cite prerequisite evidence and define only the new coupling they test. | A three-drone crossing should test joint wait/layer/detour reasoning, separation, fairness, and atomic authority—not requalify ordinary straight motion. |
| `REQ-REU-003` | Reuse does not waive integration gates. Revalidate when payload, battery, altitude envelope, simultaneous maneuvering, downwash/contact model, disturbances, or controller saturation can materially alter feasibility. | “Previously validated” means evidence-backed reuse within a declared applicability boundary. |
| `REQ-REU-004` | Catalog recommendations should select the lowest unmet prerequisite, a causal follow-on, or an explicit regression. | Progression is based on learning state rather than case count or recency. |
| `REQ-REU-005` | Every accepted learning from mission testing or iteration must be classified as either a reusable core primitive, policy, model, or bounded parameter improvement implemented once in its owning production layer, or an explicit case/backend-specific limitation with retained rationale. It must not survive only as mission-local copied behavior. | Missions are learning and qualification environments; accepted behavior becomes drone/fleet capability rather than a growing collection of special-case mission implementations. |
| `REQ-REU-006` | A planner that requires a qualified core capability must request it by stable capability identity and parameters. Resolution binds it automatically to the selected case, geometry, vehicles, backend, hashes, and safety bounds; no per-mission catalog submission is required. Resolution fails closed outside the retained applicability boundary. | Future flexible planners can consume constant path speed directly while preserving traceability and integration gates. |

### Motion and control profiles

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-MOT-001` | Speed changes at path bends or altitude kinks may occur, but they must be planned, continuous within dynamics limits, visible in preview/evidence, and evaluated against the selected profile. | A permissible speed change is not the same as an unexplained controller oscillation or discontinuity. |
| `REQ-MOT-002` | Altitude-transition cases must support a constant-path-speed experiment when a feasible scalar speed exists. The controller may vary collective thrust and attitude to track the requested world/path velocity. | This directly tests coupled horizontal/vertical tracking and actuator headroom on the same geometry. |
| `REQ-MOT-003` | Different requested speeds are admitted as a small bounded sweep only when each target probes a distinct operating region and remains inside speed, acceleration, jerk, energy, and actuator margins. | Do not create arbitrary dense speed grids. Select at most a slow and a higher-stress anchor unless evidence justifies more. |
| `REQ-MOT-004` | A segment-speed schedule is admitted only when the transitions themselves are the causal question. Target changes must be ramped; instantaneous velocity jumps are invalid. | Supports deliberate slow/fast comparison at altitude changes without creating spline discontinuities. |
| `REQ-MOT-005` | “Constant motor speed” is not a normal successful trajectory profile. Fixed rotor RPM/command removes much of the thrust authority needed to track an arbitrary climbing/descending path and is not equivalent to constant vehicle velocity. | Treat it as a future low-level actuator/bench or feasibility diagnostic only, behind a calibrated motor model, explicit low-level adapter capability, containment, and separate authorization. |
| `REQ-MOT-006` | Prefer physically interpretable alternatives to constant rotor speed: constant path speed, bounded vertical rate, thrust/actuator-headroom limits, or energy-aware retiming. | These preserve controller authority and generate evidence that can later transfer to a physical or high-fidelity backend. |
| `REQ-MOT-007` | A profile must declare which layer owns the objective: path planner, time parameterizer, trajectory tracker, or low-level actuator controller. | Prevents one option from ambiguously changing several control layers. |
| `REQ-MOT-008` | “Constant path speed” applies to declared steady route interiors, not takeoff, landing, an entry/exit ramp, or a direction/speed transition window at an authored knot. The exact excluded windows, their duration, and their share of route time must be retained; every remaining steady window must contain measured evidence. | Constant speed cannot be physically instantaneous at a stopped endpoint or a direction-changing altitude kink. Explicit exclusions prevent both impossible control demands and convenient removal of unfavorable samples. |
| `REQ-MOT-009` | A constant-speed profile is qualified from the sampled commanded spline and the recorded vehicle response, never from `segment length / requested duration` alone. Report requested and safety-retimed achieved speed, steady mean, 5th/95th percentiles, 90% ripple amplitude, RMS/maximum tracking error, and per-segment results. Thresholds are declared before the run; for the current altitude-transition anchor, steady ripple must be at most `0.05 m/s` and steady tracking RMS at most `0.03 m/s`. | The reviewed 0.18 m/s runs were incorrectly reported as conforming even though the planned and recorded speed waves were much larger than the target tolerance. |
| `REQ-MOT-010` | The route-terminal speed command must decelerate monotonically from the last admitted steady speed to the declared terminal stop. Qualification must count component-velocity reversals and secondary speed peaks separately from the subsequent landing descent; repeated sign changes or peaks outside the declared tolerance are terminal flutter. | A normal landing-speed reduction is not flutter, while an underdamped settle must not be hidden inside the landing phase. |
| `REQ-MOT-011` | Correct the highest causal layer that produces the error. Repair a nonconforming planned time law before changing tracker/controller gains; tune the tracker only for residual plan-to-response error, and tune low-level actuation only with retained saturation, headroom, attitude, current, and energy evidence. | Prevents aggressive controller tuning from chasing a wavy command and converting a time-parameterization defect into motor or attitude oscillation. |
| `REQ-MOT-012` | Reusable execution/time-law capabilities compose with planner-selected geometry and fleet coordination. The planner generates admissible candidates first and then applies the required capability to each candidate; selecting constant path speed must not silently force a direct route or bypass flexible planning. | Time parameterization is an orthogonal capability, not a replacement for obstacle avoidance, deconfliction, formation, timing, or replanning authority. |
| `REQ-MOT-013` | Every motion request declares a vector of objectives and hard guards rather than one generic smoothness score: traversal mode, speed law/band coverage, path adherence/deviation, acceleration, jerk, body angular activity, motor headroom/spread/saturation, energy, and terminal behavior. Evidence reports every component and the binding trade-off. | A constant-speed circle reduced speed ripple while increasing angular activity and motor spread; one pass/fail score would conceal the exchange. |
| `REQ-MOT-014` | `CHECKPOINT` and `CONTINUOUS_FLY_THROUGH` are distinct reusable traversal modes. Only an authored stop may create a checkpoint dwell; an ordinary fly-through knot or repeated geometric crossover must not create a stop or node-local slowdown merely because it is a waypoint. | Supports both deliberate inspect/hold missions and smooth preplanned flight without silently treating every node as a destination. |
| `REQ-MOT-015` | Continuous motion is planned over the meaningful future route/horizon, not only the next node. Its curvature/speed envelope is invariant to equivalent collinear subdivision, point density, renamed child cases, and repeated coordinates whose inbound/outbound geometry remains continuous; deviation remains inside the admitted tube/free space. | Prevents generative knot braking and the figure-eight center slowdown while preserving deliberate speed changes at real bends or constraints. |
| `REQ-MOT-016` | A change of traversal mode, speed objective, smoothness guard, or path-deviation authority during flight is a source-timestamped, hash-bound replanning/cutover decision. It preserves immutable case safety and records old/new contracts, observations, feasibility, binding constraints, and fallback; it is never an unrecorded controller toggle. | Makes mission- and condition-dependent trade-offs usable in flight without creating hidden authority or untraceable tuning. |

### Constraint-directed planning and submissions

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-PLN-001` | A planning submission must declare its allowed maneuver dimensions independently: ground release/precedence, airborne wait, speed retiming, lateral detour, vertical layer, and bounded combinations. Anything not granted is forbidden. | “The planner may change the path” becomes explicit, bounded authority rather than an implementation accident. |
| `REQ-PLN-002` | A submission must declare path adherence as `EXACT_ROUTE`, `HARD_TUBE`, `REQUIRED_REGIONS`, or `SOFT_REFERENCE`, with per-segment or per-region deviation limits where needed. | Supports both accurate path following and deliberate departures around conflicts or obstacles. |
| `REQ-PLN-003` | Submission constraints may tighten the case but may never weaken case safety, vehicle, environment, terminal, or authorization limits. | Operator experiments can compare strategies without bypassing the frozen safety boundary. |
| `REQ-PLN-004` | The planner must search only the free space and timing authority admitted by the case and submission. It must consider viable left/right/above/below/under/through options when geometry leaves them open, and reject them with exact reasons when blocked. | A bridge, tunnel, wall, free side, or open ceiling should change the feasible candidate set in an explainable way. |
| `REQ-PLN-005` | Strategy choice must be driven by a declared, auditable objective and deterministic tie-break, not by generator order. Retain bounded Pareto/strategy-class representatives and the reason the selected candidate won. | Allows minimum-delay, path-fidelity, energy, robustness, and simultaneous-flight experiments to be compared honestly without requiring an unbounded candidate dump. |
| `REQ-PLN-006` | Earliest-safe-release submissions must derive release time from continuous conflict occupancy and uncertainty bounds rather than select only from a coarse fixed delay grid. | Tests the minimum time at which the second drone can proceed without violating the required margin. |
| `REQ-PLN-007` | A synchronized encounter submission must require source-time launch/route-start skew and minimum simultaneous-flight overlap, and must forbid whole-role serialization when the causal question is active avoidance. | A 24-second ground delay cannot pass a mission intended to make two drones meet and maneuver around one another. |
| `REQ-PLN-008` | Static problem geometry and planning authority are separate. Adding or moving an obstacle or changing a hard corridor creates a successor case/event; choosing altitude, lateral, timing, or combined authority for the same problem creates a planning submission. | Prevents both case duplication and hidden changes to world truth. |
| `REQ-PLN-009` | The accepted plan must identify every changed segment, selected maneuver, clearance basis, predicted closest approach, wait/release time, rejected alternative, and binding constraint. | Makes planner flexibility visible before Play and auditable afterward. |
| `REQ-PLN-010` | One resolved submission package must be able to contain or reference the complete immutable case/world conditions, vehicle/model identities, planning authority, and optional execution profile. The component hashes and resolved-package hash remain distinct and contradictions fail closed. | Gives the operator one declarative submission artifact while preserving the difference between what the world is and what the planner may change. |
| `REQ-PLN-011` | An optimization request must define objective terms, units, normalization or lexicographic priority, equality tolerance, deterministic tie-break, planning horizon, and resource budget. A strategy label alone is not an objective. | Prevents candidate order, floating-point noise, or an implicit weighting from deciding whether the planner delays, detours, or changes altitude. |
| `REQ-PLN-012` | Every accepted trajectory set must pass an independent continuous feasibility verifier and retain a certificate covering authority, route adherence, dynamics, energy, terminal conditions, obstacle clearance, vehicle clearance, and uncertainty assumptions. Search success alone may not authorize execution. | Separates finding a candidate from proving that the exact accepted result satisfies all hard constraints. |
| `REQ-PLN-013` | A bounded planner must declare its resolution/completeness claim, numerical tolerances, timeout behavior, and unsupported problem classes. Exhausting the budget or failing to prove feasibility produces no arm/takeoff command. | “No solution found” must not be confused with mathematical infeasibility, and a partial search must fail safely. |

### Vehicle geometry, obstacles, and contact truth

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-GEO-001` | Every simulated vehicle used for collision reasoning must bind versioned, source-qualified nominal collision geometry that includes the safety-relevant body/propeller swept volume, payload, and pose convention. Uncertainty and operational padding are separate protection layers. | Center-point distance alone cannot determine whether two differently shaped vehicles intersect, while uncertainty must not redefine physical shape. |
| `REQ-GEO-002` | Operational warning/critical separation, protected-occupancy clearance, and nominal physical geometry intersection are distinct gates. Evidence must report minimum center-policy separation, minimum signed protected clearance, and minimum signed nominal-shape clearance. | A policy or uncertainty-margin breach is not automatically a crash, while actual nominal intersection is unacceptable even if a center-distance metric is misconfigured. |
| `REQ-GEO-003` | Planner and runtime validation must use continuous swept-volume or conservatively bounded checks for vehicle-vehicle, vehicle-obstacle, and vehicle-boundary contact. Sample spacing may not allow tunneling between checked points. | Edge-case and limit tests must not miss an intersection that occurs between telemetry samples. |
| `REQ-GEO-004` | A configured intersection must record pair/object identity, first-contact source time, contact location, relative velocity, signed penetration/clearance, model identity, and terminal response. | Makes a collision result reproducible and useful without pretending to model damage severity. |
| `REQ-GEO-005` | Fast Sim may classify and deterministically terminate or invoke a declared safe response on contact, but it may not claim resolved impact dynamics, damage, survivability, prop strike physics, or physical crash fidelity. | Keeps the existing simulator claim boundary truthful. |
| `REQ-GEO-006` | Known environment obstacles must be modeled as bounded solid geometry plus explicit traversable/free volumes where relevant; a “bridge” or “tunnel” must express which space is blocked and which passages remain. | Enables under, over, side, or through routing according to actual configured geometry. |
| `REQ-GEO-007` | Obstacle inflation must include vehicle envelope, localization/prediction uncertainty, and the submission's clearance policy, with the applied components retained in evidence. | Prevents routes that clear a centerline but not the vehicle or uncertainty envelope. |
| `REQ-GEO-008` | Collision-limit experiments are negative simulation cases with explicit expected failure/intervention oracles. They must never make a known-contact trajectory eligible for normal or physical execution. | Allows edge testing without weakening nominal safety. |
| `REQ-GEO-009` | Nominal physical geometry, uncertainty occupancy, and operational policy clearance are three separate nested models and metrics. Nominal truth-shape intersection is the configured contact result; an uncertainty/protected-envelope breach is conservative risk, not automatically physical contact. | Prevents uncertainty from being double-counted or a safety-margin breach from being mislabeled as a crash. |
| `REQ-GEO-010` | Continuous checks must account for the full pose and orientation of every composite component over the swept interval, with a declared conservative approximation and numerical tolerance when exact geometry is unsupported. | A body or rotor envelope can intersect during tilt or between samples even when center points and endpoint poses appear clear. |
| `REQ-GEO-011` | Solids, traversable volumes, required regions, and workspace boundaries must have deterministic precedence and static contradiction checks. Free space is never created inside an authoritative solid merely because two authored primitives overlap. | Prevents an inconsistent bridge/tunnel description from yielding backend-dependent routes. |

### Runtime replanning and changing conditions

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-RPL-001` | The simulator must support bounded, source-timestamped environment and peer-trajectory update events such as obstacle appearance/movement, corridor closure, or a changed peer reservation. | Exercises realistic replanning causes without claiming live perception. |
| `REQ-RPL-002` | Every update must carry provenance, geometry/state, confidence or uncertainty, sequence/generation, validity interval, authentication, and canonical identity. Duplicate, stale, late, unauthenticated, and contradictory updates fail closed. | Dynamic planning needs the same evidence and authority discipline as goal updates. |
| `REQ-RPL-003` | Replanning starts from a fresh source-time state and preserves only the still-proven-safe old prefix/reservation plus its prevalidated contingency until one atomic, acknowledged fleet cutover epoch. No role may execute a partially committed plan set. | Avoids gaps, split authority, stale commands, and reliance on a route portion invalidated by the new event. |
| `REQ-RPL-004` | The replacement search uses the same case and planning-submission maneuver, adherence, safety, geometry, dynamics, energy, deadline, and terminal bounds as initial planning unless an authorized successor submission explicitly tightens them. | Dynamic conditions do not grant new hidden authority. |
| `REQ-RPL-005` | If no replacement is found inside the planning/freshness budget, execute the declared bounded fallback—continue a proven-safe prefix, bounded hold where allowed, or coordinated abort/landing—and record why. | A failed replan must remain safe and explainable. |
| `REQ-RPL-006` | Dynamic mission evidence must show trigger observation, world/peer update, invalidated old segments/reservations, candidate set, selected replacement, cutover acknowledgements, post-cutover tracking, and unaffected-role impact. | Proves that replanning occurred during execution rather than only in a static preflight reducer. |
| `REQ-RPL-007` | Every dynamic event fixture must declare observation lead time, end-to-end sense/validate/plan/commit latency budget, prediction horizon, and whether safety is expected through replanning or through the fallback response. An event that appears inside the unavoidable stopping/escape horizon is a declared negative intervention case, not a nominal replan claim. | Replanning cannot guarantee avoidance when new truth arrives too late for the vehicle dynamics. |
| `REQ-RPL-008` | An independent safety monitor and a prevalidated contingency trajectory or controlled-invariant hold/abort set remain authoritative throughout replanning. The old route may be continued only while it is still proven safe under the new event generation. | Avoids assuming that an invalidated old prefix remains safe until the new fleet plan is ready. |
| `REQ-RPL-009` | The production changed-world execution head supports one drone as well as a fleet. A one-drone accepted event still requires fresh sensor-source evidence, changed-world planning, an independent feasibility certificate, acknowledged old-future cancellation/replacement authority, post-cutover observation, and the declared safe fallback. | One-drone reality missions must exercise the real online path rather than a component-only planner or a fleet-only transaction model. |
| `REQ-RPL-010` | A simulated perception mission keeps future obstacles absent from initial planner truth and reveals each appearance, movement, or removal only through its versioned sensor event after declared sensing/processing latency. Events are spaced outside the unavoidable reaction horizon for nominal cases; late/contradictory events are explicit negative cases. | Tests realistic online discovery without falsely claiming computer vision and prevents a preplanned hidden obstacle schedule from being presented as sensed replanning. |

### Simulation, high-fidelity, and physical transfer

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-XFR-001` | Mission intent, geometry, safety limits, causal question, and success criteria must be backend-neutral; model- or adapter-specific inputs must be explicit overlays. | Later digital-twin or physical work should not require redefining what the mission was meant to test. |
| `REQ-XFR-002` | Each submission must declare supported backends and the semantic mapping of its control variables on each backend. There is no silent fallback. | A Fast Sim actuator command cannot be assumed to mean Crazyflie RPM, PWM, or physical thrust. |
| `REQ-XFR-003` | Fast Sim is used for logic, repeatability, authority, and bounded sensitivity. Contact, motor, aerodynamic, sensor, and physical-accuracy claims remain qualified only by the appropriate later stage gate. | Avoids optimizing only for a visually pleasing software simulation. |
| `REQ-XFR-004` | Evidence must state source/model identity and qualification status such as `CONFIGURED_UNQUALIFIED` where appropriate. | Comparisons must not imply more fidelity than the source provides. |
| `REQ-XFR-005` | Physical-reality review reconciles world motion, attitude, body IMU, and every individual motor's requested thrust/applied PWM/thrust/current/headroom/saturation. Forward/lateral acceleration must produce the expected signed differential-actuation response for the declared rotor layout, but configured Fast-Sim agreement remains `CONFIGURED_UNQUALIFIED` until bench/flight evidence closes it. | Distinguishes a real mixer defect from four nearly overlapping plots and prevents software plausibility from becoming a physical qualification claim. |
| `REQ-XFR-006` | A digital-twin session pairs the same canonical mission intent on measured and simulated sides, persists source-time-aligned raw sensor observations and residuals for every available sensor family, retains unavailable/incompatible states, and exposes provenance/model/session identities to review and visualization. It never owns physical safety authority. | Creates a usable sensor-to-visualization data plane without presenting modeled data as measured ground truth. |
| `REQ-XFR-007` | Learning from physical/twin runs creates a bounded, versioned calibration candidate. Promotion requires minimum sample/case coverage, train/holdout separation, improvement on the named residual, non-regression across earlier missions and safety guards, parameter bounds/provenance, and explicit operator acceptance. One run never rewrites safety limits, controller authority, or the active model automatically. | Allows cumulative learning while resisting overfitting and unsafe self-modification. |
| `REQ-XFR-008` | Real-aircraft progression is staged and fail-closed: observation-only startup/sensor checks, props-off bench, contained takeoff/slow hover/land, short point-to-point/return, then smooth and dynamic paths. Every stage reuses the same mission/evidence pipeline and requires the existing bench, flight-entry, operator, observer, containment, permit, and stop gates. | Makes the hardware pipeline ready in software while keeping unperformed physical tests visibly `NOT_RUN` rather than treating readiness as flight qualification. |

### Review, evidence, and landing truth

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-EVI-001` | Operator snapshots and comparisons must bind every displayed layer to exact source time. If estimate playback is buffered, truth and target overlays must either use the same effective time or show the time offset explicitly. | A 250 ms display-age difference must not be mistaken for physical tracking error. |
| `REQ-EVI-002` | Preserve operator comments as observations and add a separate neutral assessment supported by images, exact-time samples, CSV metrics, plan/evaluation data, and repeated-run comparisons. | The review record must distinguish what was seen from what the evidence supports. |
| `REQ-EVI-003` | Compare both within-case repeatability and between-case/profile deltas. Report hard failures separately; averages may not hide them. | Makes a “nothing different” observation quantitatively testable. |
| `REQ-EVI-004` | Evaluator status must be complete and identities must reconcile before evidence is used for qualification. Diagnostic phase detectors must not be presented as mission-semantic stops. | Prevents incomplete bundles or generic takeoff/landing phases from producing misleading failures. |
| `REQ-EVI-005` | Landing must honor the admitted landing target/region: align horizontally before descent, retain contact-aware descent authority, and disarm only after the declared terminal/contact gate. | Avoids accepting a convenient current XY position or motor cutoff before verified simulated contact. |
| `REQ-EVI-006` | Review feedback does not automatically change a case's lifecycle state. Selection, review, baseline, promotion, rejection, and implementation changes require their own explicit action. | Reviewing an already flagged case must not flag or transition it again. |
| `REQ-EVI-007` | Run history is a chronological investigation journal for a mission case. Ordinary reruns, changed locked inputs, changed planner/configuration hashes, comments, failures, and analysis findings remain in the current journal; none alone creates an implementation boundary. After an operator-confirmed code revision derived from designated run evidence is applied, explicitly mark every pre-revision run in that affected case/fleet scope `Old`. Retain the revision, actor, reason, and transition time. Old runs remain inspectable below a labeled divider but are ineligible as prerequisites, baselines, peer/mode comparisons, or promotion evidence for later runs. They are never deleted or silently mixed with current evidence. | Preserves the evidence that caused a revision while ensuring a new run is evaluated only against its current implementation generation. |
| `REQ-EVI-008` | Every review run with retained telemetry must expose compact, time-aligned graphs derived from its exact CSV for each drone: velocity magnitude, world-Z altitude, recorded motor output percentage, roll/pitch/yaw attitude, body-frame IMU acceleration X/Y/Z, and body-frame angular velocity X/Y/Z. Multi-drone runs use consistent metric scales and explicit drone identities so behavior can be compared visually. Applied PWM is preferred when recorded; command percentage is labeled as a fallback, unavailable signals remain visibly unavailable, and the complete row-level CSV remains downloadable for later analysis. The live instantaneous telemetry readout remains available alongside this historical review view. | Gives the operator an immediate comparable view without replacing, averaging away, or misrepresenting the retained evidence. |
| `REQ-EVI-009` | Multi-vehicle landing evidence and UI comparisons must report each vehicle relative to its own accepted landing region before comparing vehicles with one another. If role targets intentionally differ, raw spacing between the stopped vehicles is not a landing error. | Distinguishes an expected role-specific landing layout from target-relative touchdown inaccuracy. |
| `REQ-EVI-010` | A snapshot used by an operator finding must receive its exact-time neutral assessment and machine evidence references before its image payload is purged. If historical pixels are unavailable, the review must say so and may not imply that they were independently re-inspected. | Preserves honest review traceability under bounded image-retention policies. |
| `REQ-EVI-011` | Hard dynamics, safety, contact, and terminal gates must reconcile raw exact-CSV extrema with any filtered/resampled analyzer metric. Evidence must identify the signal, phase/window, filter, and reason for excluding or classifying a raw excursion; smoothing may not silently erase it. | Prevents a startup/contact transient or single hard failure from disappearing behind a lower processed peak. |
| `REQ-EVI-012` | Speed statistics must respect the selected profile. A constant-path-speed run may show one combined steady band only after per-segment gates pass. Ramped-segment-speed and bounded-vertical-rate runs must be compared against their own segment/rate targets; their intentionally different raw speeds may not be presented as one “ripple” amplitude. | Avoids classifying an authored slow/fast schedule or changing horizontal pace under a vertical-rate objective as controller oscillation. |
| `REQ-EVI-013` | Every assisted motion iteration must retain a pre/post metric table covering profile conformance, steady-window coverage/ripple, plan-to-response error, tracking, acceleration/jerk, attitude, motor headroom/saturation, energy, terminal reversals, landing, and faults. Report every run and any safety retiming; an average may not hide a failed repeat. | Makes semi-automatic tuning reviewable and prevents improvement of one graph at the expense of a different safety or control signal. |

### Catalog interaction

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-UI-001` | Case-bound submission or execution-profile selection must appear as a subordinate layer directly beneath the selected mission case in the catalog's left navigation hierarchy. The selected submission's rationale, owner, feasibility, evidence gate, and learning value remain in the right detail pane with the mission-case information. | Separates navigation from explanation, makes the case-to-submission relationship visible, and avoids embedding a selector inside its own evidence card. |

### Iteration and documentation workflow

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-WFL-001` | Treat the operator's stated general behavior and outcome as the design intent. Use comments, images, CSV, evaluation, analysis, and earlier evidence to establish the current gap and measurable baseline, not to narrow the requirement to the workflow or behavior already present in those artifacts. | Evidence explains what exists; it does not redefine the requested future capability. |
| `REQ-WFL-002` | Translate durable operator intent into dependencies, tasks, non-goals, and measurable exit gates in `ACTIVE.md` before changing implementation. | Separates analysis and planning from implementation authority while retaining the general goal. |
| `REQ-WFL-003` | Update this file when operator feedback creates or changes a durable preference. Append a change-log entry and retain stable requirement IDs; do not silently erase earlier intent. | Makes the review loop cumulative. |
| `REQ-WFL-004` | Close work only from retained evidence and record remaining limits. Requirements remain durable even after their first implementation package completes. | A completed implementation does not remove the design rule from future missions. |
| `REQ-WFL-005` | Do not encode “read comments/CSV and copy the observed workflow” as the product goal. Reconcile evidence repeatedly, but implement the generalized planning, constraint, collision, and replanning capability requested by the operator. | Prevents one reviewed run or current planner workaround from becoming the permanent design. |
| `REQ-WFL-006` | Use an assisted evidence-driven iteration loop for motion refinement: (1) freeze exact current evidence identities; (2) compute phase- and segment-specific baselines; (3) identify the causal owner layer; (4) change one bounded hypothesis; (5) run static/dynamics gates; (6) execute isolated accelerated repeats; (7) compare the full pre/post gate set; and (8) accept, revise, or revert before requesting realtime/operator reruns. Stop when declared improvement and non-regression gates pass, not when a plot merely looks smoother. | Allows the system to help iterate parameters while keeping the reasoning, stop condition, and trade-offs explicit. |
| `REQ-WFL-007` | Assisted iterations use temporary or qualification evidence stores and must not select, flag, baseline, promote, delete, or otherwise transition the operator's campaign cases or review runs. The operator-owned current iteration changes only through explicit actions; accepted implementation hashes then start a new Run-history iteration as required by `REQ-EVI-007`. | Automation may improve and qualify code, but it may not rewrite the meaning or lifecycle of retained review evidence. |
| `REQ-WFL-008` | Before an assisted search starts, record a tuning contract containing the causal hypothesis, exact baseline identities, primary metric, safety and quality guardrails, bounded parameter family, repeat policy, cross-case checks, acceptance threshold, plateau condition, and revert rule. Thresholds may not be invented after seeing candidate results. | Makes automated improvement reproducible and prevents the search from optimizing a visually attractive but incomplete result. |
| `REQ-WFL-009` | Retain a candidate ledger for every evaluated parameter set, including code/configuration and artifact hashes, derived plan/trajectory identities, run IDs, metric vector, pass/fail result, and rejection reason. Preserve failed candidates as learning evidence and do not report only the selected winner. | Prevents cherry-picking and makes future iterations reuse knowledge instead of repeating rejected experiments. |
| `REQ-WFL-010` | Qualify candidates in stages: exact-artifact and analytic sampling first, static/dynamics and semantic gates second, isolated deterministic execution repeats third, and a distinct stress/coupling case last. A candidate that fails an earlier gate is not provisioned for later execution. | Reduces unnecessary runs and separates a bad commanded artifact from tracker, controller, backend, or plant behavior. |
| `REQ-WFL-011` | Accept a candidate only when its predeclared primary objective and every non-regression gate pass. Stop and retain the existing behavior when improvement plateaus, bounds are exhausted, or a gain requires an undeclared trade-off. Record remaining limitations and the evidence that would justify reopening the search. | Gives assisted iteration a finite, auditable stop condition and a safe revert path. |
| `REQ-WFL-012` | Treat isolated software qualification as a candidate handoff, not final operational or physical validation. After acceptance, request the minimum meaningful realtime/operator reruns; later high-fidelity simulator, digital-twin, and physical-drone checks remain separate evidence layers with their own tolerances. | Keeps fast iteration useful without overstating what software-simulation evidence proves. |
| `REQ-WFL-013` | Activate the independent work-packet protocol only when the operator explicitly asks to create, structure, refine, implement, execute, complete, verify, qualify, or transition work packets/work packages. Mere mention, explanation, status inquiry, an ordinary numbered plan, or an unrelated small task does not activate it; an explicit packet request does even when the requested change is small. | Preserves lightweight chats while making the operator's work-packet keyword a reliable quality gate. |
| `REQ-WFL-014` | Before implementation, retain a delimited, hash-identified packet design containing the originating operator request, goals, invariants, dependencies, affected production boundaries, non-goals, counterexamples, and executable exit evidence. A design-only request stops after this gate. | Prevents a later summary from narrowing the original goal and prevents implementation from beginning against an unreviewed or moving plan. |
| `REQ-WFL-015` | A fresh read-only verifier owns design finding severity and the `DESIGN_VERIFIED` or `BLOCKED_WITH_FINDINGS` verdict. The author may fix a finding or provide contrary evidence, but may not unilaterally dismiss P0/P1. | Removes same-author confirmation bias while preserving evidence-based adjudication. |
| `REQ-WFL-016` | After implementation and the author's declared checks, a different fresh read-only verifier must compare the exact implementation payload with the accepted design and return `IMPLEMENTATION_VERIFIED` or `BLOCKED_WITH_FINDINGS` before independent verification is recorded as passed. | Makes post-implementation integration review independent from both packet authoring and implementation. |
| `REQ-WFL-017` | Every core or generalized claim must trace the real trigger and production entry point through the resulting state/command change to a retained observation and an independent oracle, with an intended path and a meaningful failure, perturbation, rename/reordering, child-case, or boundary counterexample as applicable. Caller-supplied booleans/hashes, configured metadata, implementation constants, or a report regenerated by the code under test are not sole proof. | Would have caught label-only missions, duration-derived speed conformance, exact-case planner wiring, and hash-only replanning transactions even when component tests passed. |
| `REQ-WFL-018` | Tag claims separately by execution boundary (`MODEL_ONLY`, `COMPONENT`, `INTEGRATION`, or `PRODUCTION_ENTRY`), environment (`NO_RUNTIME`, `FAST_SIM`, `LIVE_ISAAC`, or `HARDWARE`), and clock evidence (`NOT_APPLICABLE`, `ACCELERATED`, or `OBSERVED_REALTIME`). A lower boundary, environment, or clock mode may not close a higher claim. | Avoids conflating model validity, integration wiring, simulator fidelity, realtime observation, and physical qualification. |
| `REQ-WFL-019` | Keep the repository's canonical packet `Status` separate from `Independent verification`. Reconcile every implemented, verified, qualified, runtime, end-to-end, and generalized-capability statement in both ledgers, qualification reports, and operator documentation against the reviewed claim matrix. Reviewer acceptance is necessary but never replaces the packet's declared qualification evidence. | Prevents documentation from reaching `QUALIFIED` or `COMPLETE` while executable reality remains model-only, pre-provisioning-only, or otherwise narrower. |
| `REQ-WFL-020` | Freeze an exact scoped manifest for each gate: base commit, relevant preimage hashes, changed/new/deleted file or delimited-section list, postimage hashes, and payload hash. “The dirty diff” is not an identity. Only a mechanical verification-record/status update and unchanged ledger move may follow verdict; any substantive change invalidates it. | Makes review attributable in a shared dirty worktree and avoids a self-referential record changing the payload it claims to identify. |
| `REQ-WFL-021` | Permit one initial review plus at most one recheck per gate. The same verifier performs that gate's recheck; a different verifier handles implementation. A verifier never delegates verification of its own review. If no independent agent/configuration/slot is available or P0/P1 remains after recheck, fail closed as blocked/unverified and stop rather than self-certifying or looping. | Bounds cost and iteration while ensuring unresolved core defects remain visible to the operator. |
| `REQ-WFL-022` | Retain a compact verification record containing reviewer thread/label, date, exact design and implementation identities, scope, evidence/commands, verdict, finding dispositions, residual limits, and any mechanical closeout delta. | Lets later chats distinguish independently reviewed evidence from an author's completion statement. |
| `REQ-WFL-023` | The implementer owns the executable test plan for every work packet. Derive tests from the packet's claims and exit gates, create any missing fixtures and tests without waiting for the operator to prescribe them, and make a new regression test fail for the intended reason before the fix when that is practical. | Turns an implementation claim into reproducible evidence and prevents missing user-supplied tests from becoming an excuse for untested behavior. |
| `REQ-WFL-024` | Self-authored tests must observe behavior through the boundary being claimed and use an oracle that is meaningfully independent of the value under test. A configured constant, caller-supplied success flag/hash, or report regenerated by the implementation is not sufficient. Production/runtime claims enter through the normal production trigger and verify the resulting state, commands, retained evidence, and safe failure behavior. | Prevents a component or model test from being used to claim production execution and prevents tests from merely restating the implementation. |
| `REQ-WFL-025` | Each substantive packet claim receives at least its intended path, a meaningful failure or rejected-input case, and a generalization or boundary case appropriate to the claim. Examples include a child or renamed case, reordered roles, tampered package linkage, changed geometry, late event, partial fleet preparation, or a disallowed authority dimension. Multi-entity claims verify the complete affected set and transaction outcome. | Exposes exact-ID wiring, permissive fallback, subset-only success, and other defects that happy-path tests routinely miss. |
| `REQ-WFL-026` | Iterate in evidence-sized vertical slices: run the smallest new test first, then affected component/integration tests, static checks, adjacent regressions, and finally reproducible qualification/artifact checks. Do not weaken an oracle, broaden a tolerance, or rewrite an expected result merely to match the implementation; change a frozen expectation only through an explicit design revision with rationale. | Keeps feedback fast while preventing test adaptation from concealing a design or implementation failure. |
| `REQ-WFL-027` | At the end of every packet iteration, re-audit the implementation against each packet separately and reconcile `ACTIVE.md`, `COMPLETED.md`, qualification artifacts, and operator documentation to the strongest boundary actually demonstrated. Self-authored passing tests support `IMPLEMENTED_UNVERIFIED`; they do not replace independent verification or unperformed runtime, realtime, high-fidelity, or hardware gates. | Prevents batch-level completion language and passing subsets from overstating partially implemented packets. |
| `REQ-WFL-028` | Before freezing a packet design that contains a matrix, registry, proposal set, lifecycle inventory, metric map, or comparator map, retain a machine-readable pre-freeze audit over the exact proposed payload. It must prove unique-key coverage, lifecycle cardinalities, exactly one disposition per key, exact comparator identity, comparator existence/visibility, relation-metric membership, context membership, and no duplicate, missing, or extra row. The reviewer must be able to rerun the audit without interpreting prose. | Moves set-membership and completeness failures out of the review loop and prevents a coherent-looking table from concealing illegal metrics, duplicated entries, or missing lifecycle classes. |
| `REQ-WFL-029` | Prototype every new numerical oracle, candidate family, equality/distinctness tolerance, tie-break, and derived capability resolution against representative exact inputs before freezing it. Retain the prototype command and full result vector. A currently missing capability may deliberately produce a failing regression only when an independently constructed feasible witness and the intended failure reason are both frozen; values, candidate sets, and tolerances may not be chosen after implementation output is observed. | Prevents under-specified energy searches, post-hoc tolerances, and paper-only oracles from consuming a design revision or becoming self-certifying implementation logic. |
| `REQ-WFL-030` | Freeze the comparator for every relation and collapse explicitly. A baseline comparator names the exact case-default package. A peer comparator names one exact admitted visible proposal in the same experiment and either (a) that peer qualifies independently first or (b) the two visible peers form one explicitly frozen atomic pair whose opposite directions, shared fixed inputs, and all-or-none disposition are evaluated together. There is no nearest-peer, post-result selection, or circular collapse dependency. `COLLAPSE_ALL` compares the complete independently measured row metric vector and both accepted artifacts to its exact comparator; hashes, labels, or a match against the wrong baseline cannot prove collapse. A peer used as a collapse target must itself qualify before the dependent collapse can pass and may never rely on the collapsed proposal. | Preserves useful alternatives without keeping redundant labels, permits honest pairwise authority/objective experiments without inventing an infeasible neutral baseline, and prevents false baseline collapses or circular self-qualification. |
| `REQ-WFL-031` | A qualification comparison context is a canonical hash-bound input applied symmetrically to subject and comparator and retained in both identities. Before design freeze, independently demonstrate that the context is non-vacuous, that both sides have a feasible witness within the declared bounds, that it changes no declared experiment axis, and that it does not prohibit or force the behavior that is supposed to distinguish the axis. If different proposal classes need different contexts, freeze the exact partition and prove set equality mechanically. | Prevents zero-overlap capacity claims, proposal-only overlays, and synchronized-start fixtures that make a timing-release experiment impossible or erase its distinguishing behavior. |
| `REQ-WFL-032` | Geometry- and sampling-derived capability resolution must be invariant to semantics-preserving point density, role order, and equivalent collinear subdivision. Freeze the normalization rules and require original, densified, simplified, renamed-child, and incompatible-child perturbations before qualification. A minimum authored segment, array position, or presentation ordering is not a geometric oracle unless the operator explicitly made it semantic. | Prevents lookahead, radius, speed, and retiming results from changing merely because extra collinear waypoints were authored. |
| `REQ-WFL-033` | Distinguish proved infeasibility from budget exhaustion, timeout, unsupported capability, missing implementation, and independent-verification rejection. `REJECT(c)` requires a complete bounded search or analytic proof of the exact constraint `c` plus an independent adverse perturbation; incomplete search is retained as inconclusive/timeout and never as a safe rejection. | Prevents exhausted searches and absent implementations from being promoted into evidence-backed safety dispositions. |
| `REQ-WFL-034` | Before attaching a production/runtime claim to a packet design, execute or trace one representative request through the normal public service/API trigger, planner, trajectory, executor, retained evidence, evaluator, and analyzer. Freeze which component owns each value and which independent observation proves it. Direct construction of internal catalogs, planners, or trajectories can support component evidence only and may not be labeled `PRODUCTION_ENTRY`, `FAST_SIM`, or runtime by documentation alone. | Prevents a qualification generator that never invokes the runtime path from conferring production or accelerated-simulation claims on every row. |
| `REQ-WFL-035` | Row-specific admission, causal-question, oracle, and learning records must preserve their literal reviewed meaning or an exact structured equivalent. Generic generated boilerplate is permitted only for non-authoritative display text and may not replace the row-specific oracle, comparator, bounds, or learning question. A machine audit must round-trip the authoritative source into the retained registry without loss. | Prevents an apparently complete multi-field registry from erasing the specific question that made each submission worth retaining. |
| `REQ-WFL-036` | Every asserted gate preimage must include a byte-exact reconstruction command or an immutable retained source that reproduces the claimed hash from the current review payload. A hash that cannot be reconstructed is corrected before review; inferred edits, remembered prior text, or an approximate reverse patch are not sufficient. | Avoids spending a review iteration on an identity that cannot be independently reproduced. |
| `REQ-WFL-037` | When a `MUST_FIX_NOW` defect justifies an operator-authorized successor design after a blocked review, or an implementation oracle contradicts the accepted design on the explicitly requested minimum outcome, perform a short retrospective before drafting it. Add each genuinely reusable failure mode to this workflow and its regression/audit, while leaving case-specific findings in the packet. The next design must cite the resulting requirement IDs and the pre-freeze evidence that applies them. A `DEFER` or `SCOPE_CHALLENGE` does not start another design iteration. | Makes repeated review cumulative without turning every legitimate observation into another automatic revision. |
| `REQ-WFL-038` | UI qualification binds the exact served release, API process, and asset hashes before inspection. Source review and a successful build are prerequisites, not rendered evidence. Verify the current release/symlink, exercise the real API-backed interaction, and retain desktop plus narrow screenshots or equivalent rendered inspection for loading, empty, disabled, error, expanded, collapsed, and keyboard states as applicable. A stale release or disconnected browser is recorded as not run. | Prevents a correct source tree or stale bundle from being mistaken for visual verification of the release operators actually use. |
| `REQ-WFL-039` | Separate pre-implementation oracle identity from post-implementation semantic replay. A retained pre-draft artifact and its script stay byte-identical and prove what was frozen at design time. If the artifact includes implementation-owned source/package hashes that the accepted design requires to change, the implementation gate must use a separately frozen reconciliation contract: it binds the new exact source identities and compares the current independently measured candidate family, metric vector, tolerances, relations, and counterexamples with the immutable design oracle. It may replace only identities explicitly classified as implementation-owned; it may not rewrite the historical artifact, relax a numeric/semantic gate, or demand that mutable preimages remain current. | Prevents a design from becoming impossible by simultaneously requiring a registry or compiler to change and requiring an artifact that hashes the old registry/compiler to regenerate byte-for-byte after implementation. |
| `REQ-WFL-041` | Before a proposal is marked executable, prototype its complete qualifying relation through the same evidence boundary named by that relation. For every directional clause, retain the exact comparator and subject observations over the required isolated repeats and prove that their median delta reaches the already-frozen distinctness threshold; hard-gate success, a different plan/hash/label, or a delta that remains inside equality/inconclusive bounds is insufficient. If a declared metric is invariant under the proposal's sole authorized axis, keep the proposal visible but disabled/inconclusive and require a new design before changing the metric, axis, or comparator. | Prevents runtime-safe but scientifically indistinguishable alternatives from being advertised as useful submissions, and catches objectives such as timing-only spatial robustness that cannot affect their own frozen oracle. |
| `REQ-WFL-040` | During investigation, retain every run, operator note, neutral assessment, CSV/graph, evaluator result, failure, rejected hypothesis, and relevant configuration/implementation identity in the mission case's active journal. On the operator's explicit request, consolidate the designated journal(s) into an evidence synthesis: separate observations from supported findings, identify repeated patterns and open questions, retain contradictory or failed evidence, state the affected reusable capability and boundaries, and propose bounded improvement work packets with dependencies, non-goals, and measurable exit evidence. Gathering and synthesis do not change case lifecycle or implementation. If the operator explicitly asks to structure/create/refine those work packets, enter the independent work-packet protocol before drafting them; otherwise retain the synthesis as planning input only. | Lets exploratory runs accumulate useful knowledge before commitment, so later work packets are based on the full investigation rather than a single recent run or a reconstructed memory. |
| `REQ-WFL-042` | Before drafting or refining a packet, retain a compact intent/value card that separates the operator's minimum useful outcome, explicitly requested behavior, necessary prerequisites, optional experiments, and non-goals. Every proposed function or submission must trace to one of the first three categories. If a review finding implies a new function, changes the product question, or makes the author unsure whether the operator wants the capability at all, classify it as `SCOPE_CHALLENGE` and obtain operator direction before designing or perfecting it. | Prevents verification work from manufacturing scope and prevents extensive refinement of a technically coherent feature that does not serve the operator's actual goal. |
| `REQ-WFL-043` | The verifier assigns each finding both technical severity and the smallest affected claim, proposal, packet, or shared boundary. A `MUST_FIX_NOW` disposition is limited to safety, security/authorization, data loss, production breakage, a false user-visible claim, or failure of the explicitly requested minimum outcome. A safely isolated optional proposal, stronger evidence tier, polish item, or non-central edge case is `DEFER`: keep it disabled, inconclusive, partial, or documented without blocking unaffected value. Review may test frozen acceptance criteria but may not promote an opportunistic improvement into mandatory scope. | Preserves strictness where failure matters while avoiding all-or-nothing refinement of a large batch because one optional alternative is incomplete. |
| `REQ-WFL-044` | The default budget remains one design review with one consolidated correction/recheck and one implementation review with one consolidated correction/recheck. After either focused recheck, do not automatically create a successor revision. Non-critical residuals are deferred under `REQ-WFL-043`; a new iteration is proposed only for a remaining `MUST_FIX_NOW` defect and requires a concise operator-facing statement of affected value, safe fallback, expected work, and why the fix cannot wait. Stop immediately for `SCOPE_CHALLENGE`. | Converts the review limit into a real cost stop instead of resetting the counter through serial R2/R3/R4 revisions for every valid but non-critical finding. |
| `REQ-WFL-045` | Choose the least costly model and reasoning effort that is demonstrated adequate for the task. Use a balanced implementation model at medium/high effort for an execution-ready packet with exact files, bounded changes, tests, and no unresolved product or safety interpretation; reserve a frontier model and high/xhigh effort for ambiguous intent, architecture, control/safety boundaries, novel counterexample diagnosis, and consequential independent adjudication. Escalate only on a recorded trigger such as a specification contradiction, a cross-layer architectural dependency, a safety/authorization consequence, or two failed bounded attempts. Each gate records the model/effort, review and correction counts, outcome, and actual token/time usage when exposed; otherwise it records `not available` plus simple proxies and never invents a cost number. | Stops maximum-capability reasoning from being the unexamined default, while retaining it where marginal reasoning quality can materially change safety, scope, or correctness. |
| `REQ-WFL-046` | A numerical qualification prototype is complete only when it retains exact pass and fail inputs plus computed outputs for the primary relation and every secondary guard, defines per-repeat and aggregate semantics, and freezes the repeat-count, equality/hash rule, and numeric tolerance. It must include one isolated failure perturbation per guard whose other inputs remain passing, so a joint failure cannot conceal an ignored guard. A count of repeats or a primary-only vector cannot establish determinism or prove that secondary regressions fail closed. | Prevents an apparently complete holdout or motion oracle from leaving guard-vector arithmetic and repeatability to implementation-time interpretation. |
| `REQ-WFL-047` | Before design freeze, mechanically close the affected-boundary manifest against every owner named by the claim matrix and every production transit, persistence, export, API-serving, UI-serving, safety, generator, and generated-output boundary found by the required production-path trace. The audit derives the claim-row keys, public transit nodes, and discovered generated-output sets from their independent sources and reconciles those sets to the manifest; proving that one hand-maintained list is a subset of another is insufficient. Every existing path has an exact preimage hash and edit classification; every intended new path is marked absent/new. A missing owner, transit node, or generated output fails the audit before independent review. | Prevents a detailed claim matrix from silently omitting the mission base, request model, generated mission/config surface, evidence exporter, dashboard/server, or another real boundary that implementation must change or preserve. |
| `REQ-WFL-048` | Before freezing a sensed-world, reaction-horizon, braking/hold, or safety-fallback claim, retain an executable numerical witness with exact world and vehicle geometry, clearance, world/source/receive/effective clocks, every sensing/processing/planning/acknowledgement/commit budget, prediction horizon, dynamic bounds, computed certificate/hash, and resulting command. Include isolated nominal detour, certified hold, certified abort/land, stale/tampered/late, insufficient-clearance, and no-certificate perturbations as applicable. A caller boolean, authored future geometry, or prose-only timing budget cannot establish feasibility or fail-closed behavior. | Prevents live-replanning designs from deferring the most consequential clock/geometry/certificate choices to implementation or proving safety with the bypass they are intended to remove. |
| `REQ-WFL-049` | A guard registry is complete only when its required semantic categories are derived from the frozen operator request, durable requirements, packet contract, and claim/exit matrix independently of the registry itself. Retain a source-to-category-to-metric coverage map, exact metric definitions and directionality, and at least one sensitive isolated perturbation for every metric; conjunctive or mode-dependent categories retain and perturb each binding subclause rather than hiding them behind one authored pass boolean. The audit fails on any missing or extra category/metric and on any declared category with no passing whole-repeat vector. | Prevents a mechanically perfect isolated-failure audit from certifying an incomplete self-authored guard list that omitted headroom, energy, signed actuation, or traversal semantics already promised elsewhere in the same design. |
| `REQ-WFL-050` | After a design gate passes and the remaining implementation gap is concrete and bounded, stop open-ended exploration and implement that gap immediately in the smallest complete production-path slice. Run the declared focused checks once, broaden only when those checks pass or expose a specific dependency, then hand off to the required implementation verifier. During the permitted correction, fix only verifier-owned P0/P1 or `MUST_FIX_NOW` findings; defer optional tuning, polish, speculative redesign, and additional qualification experiments unless a concrete failed gate requires them. If no source edit is produced during an active implementation interval, report the blocker or switch to the next executable slice instead of continuing unbounded inspection. | Converts an accepted design into code without spending implementation time and tokens on another implicit design cycle, while preserving the required evidence and independent gate. |
| `REQ-WFL-051` | A new operator instruction that narrows scope immediately invalidates every broader pending plan, search, check, and optional follow-on. Inspect only the named boundary with a targeted, output-capped query; stop as soon as the stated question or known gap is resolved. Do not add repository-wide searches, extra diagnostics, tests, tuning, or “helpful” investigation unless the bounded action fails and exposes a specific required dependency. | Makes scope reduction operational, prevents inherited plans from silently continuing, and avoids unnecessary token, tool-output, and elapsed-time consumption. |
| `REQ-WFL-052` | Immediately after an operator-confirmed implementation revision is committed and before collecting the next affected campaign run, execute the run-history boundary for the exact case or fleet scope that supplied the revision evidence. Use `scripts/mark_campaign_runs_old.py` with the applied revision identity, actor, and reason; then restart the campaign-state-owning API before any further campaign mutation and confirm the persisted old/current counts. The transition applies only to runs that already exist, is idempotent, rejects active runs, leaves later runs current, and must be included in the implementation handoff even when the wider packet batch remains partial or blocked. | Makes the `Old` boundary a required post-revision operation rather than a remembered UI cleanup, prevents a stale in-memory state writer from undoing it, and prevents superseded evidence from qualifying the new implementation. |

### Reusable assisted feature-iteration method

The altitude-transition refinement established the following reusable method for
future motion, planning, control, evaluation, and review features:

1. **Define.** Convert the operator-observed behavior into a measurable tuning
   contract before testing. Name one primary objective and retain safety, tracking,
   actuator, energy, terminal, fault, and semantic non-regression gates as applicable.
2. **Freeze the baseline.** Bind the exact case, submission/profile, backend, seed,
   configuration, accepted plan, trajectory, implementation, and evidence hashes.
   Split measurements into meaningful phases and segments rather than relying on a
   whole-run average or visual impression.
3. **Diagnose ownership.** Compare authored intent, generated command, accepted
   artifact, actual response, and evaluator result. Correct the earliest causal layer
   that violates intent before changing downstream controller gains.
4. **Bound the search.** Vary one causally related parameter family at a time inside
   declared safe bounds. Include a margin-rich anchor and a meaningful stress anchor;
   avoid dense arbitrary sweeps and unrelated simultaneous changes.
5. **Screen cheaply.** Sample the exact generated artifact at adequate resolution and
   reject failures of coverage, continuity, conformance, dynamics, authority, or
   semantics before executing a run.
6. **Execute reproducibly.** Run deterministic isolated repeats, preserve every
   candidate in the ledger, and distinguish repeat jitter from a systematic defect.
   Automated runs must not change operator-owned review or campaign lifecycle state.
7. **Compare completely.** Evaluate the predeclared primary metric and all guardrails
   against the frozen baseline. Use profile-aware metrics and verify at least one
   distinct geometry, stress, or coupling case so a reusable primitive is not tuned
   only to one route.
8. **Decide and hand off.** Accept, revise, or revert according to the declared rules.
   An accepted software candidate then receives the smallest meaningful realtime
   operator rerun; digital-twin and physical validation remain subsequent layers.
9. **Retain the learning.** Record the chosen and rejected parameters, comparison
   table, decision, remaining limitation, and reopening trigger in this document or
   the linked qualification artifact before closing the work package.

The method is “half automatic”: the system may diagnose, propose bounded candidates,
run isolated checks, compare metrics, and recommend a candidate. It may not silently
change mission truth, broaden authority, transition review state, choose an undeclared
trade-off, or claim physical validity. Those boundaries remain explicit operator and
evidence decisions.

### Author-driven iterative work-packet implementation loop

The packet implementer is responsible for discovering and writing the tests needed to
demonstrate the requested behavior. The operator does not need to supply a test list,
identify every regression surface, or ask separately for negative cases. This author
loop produces implementation evidence; the independent verifier still owns the later
verification verdict. The retained
[WP-44 through WP-50 implementation audit](../work-packages/WP44_50_IMPLEMENTATION_AUDIT_2026-08-11.md)
is the worked example for auditing a previously overclaimed packet batch, creating the
missing production-path tests, repairing vertical slices, and retaining open gates.

1. **Re-audit before editing.** Read the originating request, frozen packet design,
   current ledgers, production entry points, and retained qualification evidence. Run
   the relevant baseline checks and trace the current behavior. Treat an existing
   `IMPLEMENTED`, `QUALIFIED`, or batch-completion statement as a claim to verify, not
   as proof. Record each packet's actual starting boundary and any mismatch.
2. **Turn claims into test cases.** For every exit claim, identify the real trigger,
   expected state or command effect, retained observation, independent oracle,
   execution/environment/clock boundary, and at least one failure or counterexample.
   Create the missing fixtures and automated tests as part of the packet work.
3. **Establish sensitivity.** When practical, run each new regression test against the
   pre-fix implementation and confirm that it fails for the intended behavioral reason.
   If the old behavior already passes, perturb the relevant input or boundary to prove
   that the assertion can distinguish a real defect from a tautology.
4. **Implement one complete vertical slice.** Connect the normal entry point through
   validation, state transition or command generation, runtime execution when claimed,
   and retained evaluation evidence. Avoid declaring success from a helper that is not
   reached by the actual submission or execution pipeline.
5. **Use a tight test loop.** Run the smallest affected test while editing, then its
   component and integration neighbors. Repair the earliest causal layer responsible
   for a failure. Do not modify the expected value, threshold, fixture, or evidence
   boundary simply because the current implementation produces something different.
6. **Exercise adverse and generalized cases.** Add the cases that could falsify the
   generalized claim: invalid or tampered identity chains, changed inputs, child or
   renamed cases, reordered actors, late events, partial preparation, unavailable
   authority, and safe fallback. For fleet behavior, assert all affected roles and the
   commit/cutover result rather than accepting one successful role as fleet success.
7. **Broaden verification.** After the focused tests pass, run formatting/type/static
   checks, adjacent regressions, the packet's declared matrix, and deterministic
   artifact regeneration or `--check` validation. Record failures outside the packet
   scope explicitly; do not silently omit them or misattribute a pre-existing failure.
8. **Reconcile claim boundaries.** Compare the final evidence with every packet exit
   gate. Mark packets independently as implemented, partial, qualified, or still open;
   do not let one passing row or one completed packet close a whole batch. Update all
   linked status and qualification claims while preserving unrelated concurrent edits.
9. **Hand off for independent verification.** Freeze the exact implementation payload
   and evidence only after the author loop is complete. Self-authored tests demonstrate
   disciplined implementation, but they leave the packet at
   `IMPLEMENTED_UNVERIFIED` until the independent gate passes.

### Independent work-packet verification protocol

The protocol applies to one related packet batch at a time; it does not require one
agent per packet and it does not apply to ordinary small tasks.

1. **Classify scope and value.** An explicit packet creation/refinement request receives
   the design gate only. An implementation/execution/completion request receives both
   gates; an existing packet without a retained passing design record is reviewed at
   the design gate first. Freeze the `REQ-WFL-042` intent/value card before expanding
   the design. Do not convert a verifier's interesting idea into product scope.
2. **Audit, draft, and freeze design.** Before writing the final draft, run the
   `REQ-WFL-028` through `REQ-WFL-031` pre-freeze audits that apply: exact set and
   metric membership, numerical prototype/witness, comparator/collapse mapping, and
   context symmetry/non-vacuity/feasibility. Write the packet in `ACTIVE.md` with
   canonical `Status` plus `Independent verification: DRAFT_UNVERIFIED`. Preserve the
   original user request, retain the machine-readable audit or exact reproducing
   commands, delimit the substantive design payload, and compute its hash outside the
   verification record.
3. **Run the design gate.** A fresh `work_packet_verifier` receives that original
   request, the durable requirements, payload hash, and affected boundaries. It tries
   to falsify coverage and exit evidence. It reports the smallest affected scope and a
   `MUST_FIX_NOW`, `DEFER`, or `SCOPE_CHALLENGE` disposition for each finding. The
   author gets one consolidated revision; the same reviewer gets one focused recheck.
   After that recheck, apply the `REQ-WFL-044` stop rule rather than opening another
   automatic design revision.
4. **Implement only when requested and design-verified.** The author follows the
   author-driven loop above, derives and creates the necessary tests, runs the declared
   tests, records the `REQ-WFL-045` model/effort choice, and records
   `Independent verification: IMPLEMENTED_UNVERIFIED`. A passing self-test is evidence,
   not independent acceptance.
5. **Freeze and review implementation.** Record the exact scoped payload manifest and
   use a different fresh verifier. The verifier checks the production path, independent
   oracles, sensitivity/counterexamples, regressions, and documentation-to-reality
   alignment. One consolidated fix pass and one focused recheck are allowed. A defect
   confined to an optional proposal is normally closed by disabling/deferring that
   proposal, not by blocking unrelated implemented value or silently widening scope.
6. **Close mechanically.** After `IMPLEMENTATION_VERIFIED`, only append the verification
   record, update the separate verification field, and move unchanged packet text to
   `COMPLETED.md`. Recompute the delimited payload hash to prove no substantive content
   changed. Qualification/completion still requires all packet-specific evidence gates.

Each core claim uses a compact matrix like this:

| Claim | Real trigger / production entry | State or command effect | Retained observation | Independent oracle | Sensitivity or counterexample | Boundary / environment / clock |
|---|---|---|---|---|---|---|
| Example runtime replan claim | Source-time event through the normal running-campaign entry point | Replacement command changes the active epoch | Run ID, telemetry, old/new command and certificate hashes | Independently recomputed changed-world feasibility and observed cutover | Late event fails safely; child obstacle case retains admitted authority | `PRODUCTION_ENTRY / FAST_SIM / OBSERVED_REALTIME` |

Canonical packet `Status` remains the repository lifecycle field. The separate
verification field uses `DRAFT_UNVERIFIED`, `DESIGN_VERIFIED`,
`IMPLEMENTED_UNVERIFIED`, `BLOCKED_WITH_FINDINGS`, or `IMPLEMENTATION_VERIFIED`.
P0/P1 is reserved for `MUST_FIX_NOW` or for a false claim that has not yet been removed
or disabled; it blocks the smallest relevant gate. A safely isolated `DEFER` is a P2
or declared limitation and may remain for rough integration acceptance. If a verifier
cannot run safely or reproduce evidence, it records that limit and does not upgrade
the affected claim.

### Packet review economics and model routing

At each design and implementation gate, retain this compact decision record. Actual
tokens and wall time are copied only when the system exposes them; otherwise write
`not available` and use counts of review turns, correction passes, runtime runs, and
changed files as transparent proxies.

| Decision | Required record |
|---|---|
| Product value | Minimum useful operator outcome; requested versus optional behavior; safe fallback if the claim is deferred. |
| Review value | Findings grouped as behavior/safety, claim truth, or polish/extra assurance, with the smallest affected scope. |
| Iteration decision | Stop, defer/disable, request operator scope direction, or propose one critical successor with its expected value and work. |
| Model route | Balanced execution model for exact bounded implementation; frontier reasoning for unresolved intent, architecture, safety/control semantics, novel diagnosis, and independent high-consequence adjudication. |
| Escalation | Exact trigger that justified a stronger model/effort; length or habit alone is not a trigger. |
| Cost evidence | Actual token/time usage when available, otherwise `not available`; review/correction/tool/run/file counts as non-token proxies. |

An execution-ready packet has exact ownership and files, frozen inputs and outputs,
bounded changes, executable tests, and no unresolved product, safety, or authority
interpretation. It is a good candidate for a balanced model such as the current Terra
class at medium/high effort. Ambiguous design, cross-layer control architecture,
safety-sensitive counterexamples, and final critical gate adjudication remain a good
fit for a frontier model such as the current Sol class at high/xhigh effort. Start with
the cheaper adequate route and escalate only for the triggers in `REQ-WFL-045`; do not
assume the maximum reasoning effort is automatically the best trade-off.

### WP-52 through WP-56 cost/value retrospective

Exact per-turn token telemetry was not available in the retained packet evidence, so
no exact percentage is asserted. Review generations, correction passes, runtime runs,
artifact rewrites, and the portion of usable behavior affected are the available
proxies. On those proxies, the batch delivered substantial real value, but roughly one
third to one half of the later review effort appears avoidable or safely deferrable.
That range is a qualitative process estimate, not measured token accounting.

| Work area | Value judgment | Future treatment |
|---|---|---|
| Case-specific submission registry, selector/API integration, reusable constant-speed and corner-transition capability | Central to the operator's request and worth the implementation cost. | Keep as the minimum useful outcome and deliver in small vertical tranches. |
| Point-density-dependent steering, permissive child/backend binding, unsafe rejection labels, priority/context errors, and component-only work reported as runtime/production | Critical behavior, authority, safety, or claim-truth defects. These could materially change commands or mislead an operator. | `MUST_FIX_NOW`, preferably caught once by pre-freeze perturbation and production-path audits. |
| Comparator identity, metric membership, lifecycle separation, literal row oracles, and non-vacuous symmetric contexts | Necessary for any proposal advertised as a valid causal experiment, but many failures were predictable set/contract errors. | Run one machine audit before review; disable only affected proposals if the shared application remains safe. |
| Mutable historical hashes, preimage reconstruction, and phase-separated audit identities | Useful traceability, but much of R6/R7 was process-created overhead rather than new user behavior. | Fix the workflow pattern once; do not repeatedly reopen product design for bookkeeping that can be safely reconciled separately. |
| R8 relation discriminability and complete per-clause evidence for two surviving alternatives | Scientifically valid qualification concerns, but they did not prevent most of the application from running and the alternatives had a safe disabled state. | After the allowed correction, defer/disable the two alternatives instead of opening R9 unless the operator explicitly prioritizes them. |
| Further polishing of a function whose operator value is uncertain | Worst-case waste even if technically excellent. | `SCOPE_CHALLENGE`: stop and ask before any more design or implementation. |

The main failure was therefore not that the reviews invented meaningless defects.
Most findings were valid. The inefficient decision was repeatedly coupling isolated
qualification completeness to the whole five-packet batch. Future work keeps strict
oracles, but uses a smaller blast radius and a safe disabled/deferred outcome.

### Learnings from repeated work-packet reviews

| Review episode | What appeared sufficient beforehand | What a fresh review found | Durable correction |
|---|---|---|---|
| WP-26 through WP-34 design reviews | Nine well-formed packets with dependencies and release-artifact tests | Later evaluations still added independently passable subphases, corrected circular ordering, explicit ownership, numeric gates, active-case budgets, and runtime/playback distinctions. | Independently review packet design before code; headings, links, and a coherent sequence do not prove coverage or feasible exit gates. |
| Mission-curriculum review | Unique IDs, descriptions, hashes, counts, and passing catalog tests | Many named one-, two-, and three-drone families compiled to the same small set of routes and behavior. | Generalized claims need semantic perturbation/rename tests and observed behavior differences, not label/hash uniqueness. |
| WP-40 through WP-43 implementation review | Packets were marked implemented and focused tests largely passed | Snapshot provenance used the newest row rather than exact bracketing rows; speed conformance came from requested duration rather than the generated spline; contact time was recorded after descent; a retained canonical fixture was missing; and assertions mirrored implementation. | Inspect actual produced artifacts/responses, require independent oracles, and verify retained evidence exists and round-trips. |
| WP-44 through WP-50 pre-implementation review | The original seven-packet decomposition covered planning, geometry, obstacles, replanning, cases, UI, and qualification | Review added separate nominal/protected geometry, resolved-package integrity, independent feasibility certificates, reaction horizons, single-causal matrix rows, and raw-versus-filtered reconciliation. | Design review is valuable even when the decomposition is correct; integration contracts and negative gates must be explicit. |
| WP-44 through WP-50 post-implementation review | `ACTIVE.md` and `COMPLETED.md` reported reusable Fast-Sim qualification and a passing 19-row matrix | Fresh tracing found exact-case-ID planner wiring, child-case authority fallback, pre-provisioning-only events, caller-supplied hash/boolean replans, model-only dynamic rows, and incomplete resolved-package self/cross-component validation. | Require the real production entry path, observed command/state change, independent oracle, variant counterexample, exact evidence level, and documentation reconciliation before qualification wording. |
| WP-52 through WP-56 repeated design and implementation iterations | A complete 54-row/111-proposal registry, closed metric grammar, symmetric context, passing component tests, and hash-identified artifacts appeared to close the matrix | Fresh reviews and executable perturbations found unfrozen numerical oracles, generic admission records, metric-membership errors, ambiguous/wrong collapse comparators, conflated lifecycle classes, a vacuous then infeasible overlap context, sample-density-dependent lookahead, budget exhaustion called safe rejection, and component-only generators labeled production/runtime. | Require a retained pre-freeze machine audit and numerical prototype; exact baseline/peer comparator mapping; full-vector collapse proof; context symmetry, non-vacuity, feasibility, and axis compatibility; density-invariance perturbations; exact rejection taxonomy; literal row records; reproducible preimages; and a real production-trigger trace before review. |
| WP-52 through WP-56 R6 implementation start | The verified R6 design required its numerical pre-draft audit to replay byte-for-byte after publishing the registry correction that the same audit classified. | The audit hashes and reloads the mutable pre-R6 registry, so the mandated 29-to-28 collapse correction necessarily makes the historical output stale even when every frozen numerical result remains correct. | Keep historical design evidence immutable, classify which identities are expected to change, and use a separate post-implementation semantic reconciliation artifact under `REQ-WFL-039`. |
| WP-52 through WP-56 R8 implementation evidence | All affected alternatives ran safely and deterministically, and their plans/trajectories had different hashes. | Three-repeat observations showed that vertical precision improved tracking only inside the frozen equality band and did not change settle time, while timing-only constrained robustness could not increase the endpoint-limited continuous spatial-clearance metric. | Require complete relation discriminability at the named evidence boundary under `REQ-WFL-041`; preserve scientifically useful minimum-duration/makespan alternatives and fail closed on safe but inconclusive labels. |
| WP-52 through WP-56 cost/value retrospective | Repeated fresh reviews produced legitimate findings, so each successor revision appeared justified in isolation. Exact token telemetry was unavailable; revision count, runtime runs, artifacts, and changed scope were used as proxies. | The initial feature, real production-path/runtime truth, density-invariant steering, rejection safety, authority/context correctness, and false qualification claims were worth correcting. A substantial minority of later work was avoidable process/oracle refinement: per-row completeness, mutable historical identities, and two safely disableable non-distinguishing alternatives kept reopening the whole batch although most application behavior remained usable. | Separate technical validity from product necessity. Fix shared safety, production breakage, and false minimum-outcome claims now; disable/defer isolated alternatives after one correction; stop for scope uncertainty; do not authorize another revision merely because a further improvement exists. Route exact implementation to a balanced model and reserve frontier/high-effort reasoning for ambiguity and consequential review. |
| WP-57 through WP-61 first design gate | Six-session calibration bounds, a primary position-RMSE vector, a three-repeat count, and a broad production-path manifest appeared sufficient after the permitted correction. | The focused recheck found that altitude/velocity guards and actual repeat outputs/tolerance were still undefined, while the mission base, CSV exporter, and dashboard serving boundary were absent despite being named or traversed by production claims. | Apply `REQ-WFL-046` and `REQ-WFL-047`: prototype the entire primary-plus-guard relation with explicit repeats and mechanically reconcile every claim owner and real transit boundary before the final authorized design review. |
| WP-57 through WP-61 final-cycle initial review | The corrective audit added complete residual/repeat vectors and checked hand-maintained boundary groups, while the base design described reaction timing and safety certificates in prose. | Fresh tracing found no executable sensed-world reaction/certificate witness, no isolated motion/safety calibration guard vectors, and list-vs-list closure that omitted the public request model, served page, generated 1D manifests, one-drone mission outputs, preset, and real mirrors. | Strengthen `REQ-WFL-046`/`047` and add `REQ-WFL-048`: isolate every guard, derive boundary sets from claim rows/transit/discovery, and prototype nominal detour plus exact certified hold/abort and adverse clock/geometry cases before the final recheck. |
| WP-57 through WP-61 final-cycle focused recheck | The corrected calibration audit retained exact pass/repeat/failure vectors for every one of its 15 registered motion and safety guards and proved one changed key per isolated rejection. | The registry was internally complete but was not derived from the broader frozen motion contract; motor headroom, electrical energy, signed differential actuation, and checkpoint/fly-through preservation were therefore absent and could regress during calibration without blocking promotion. | Add `REQ-WFL-049`: mechanically derive the semantic guard universe from independent frozen sources, map every category to direction-aware metrics, and prototype the complete expanded vector plus isolated failures before review. |
| WP-57 through WP-61 implementation handoff | The design was independently verified and one concrete execution-profile/quality-contract propagation gap was known. | Implementation time continued to be spent on inspection and qualification planning without producing a source edit, consuming excessive elapsed time and tokens. | Add `REQ-WFL-050`: once the accepted design leaves a bounded implementation gap, implement the smallest production slice, run the declared checks once, enter the required verifier gate, and limit correction to P0/P1 or `MUST_FIX_NOW` findings. |

### Learnings from the first altitude-transition iteration

| Observation | Durable learning for future feature tests |
|---|---|
| A duration-derived audit initially made requested and achieved speed appear equal while the sampled spline still contained large waves. | Never infer conformance from metadata alone; sample the generated command and compare it with both the request and recorded response. |
| The tracker largely followed the oscillating commanded velocity. | Locate the earliest causal owner. Fixing the time-parameterization layer was more justified than tuning downstream gains. |
| Whole-route ripple was meaningful for constant-speed profiles but misleading for intentionally ramped or vertical-rate profiles. | Declare profile-specific metrics and evaluate steady windows or segments; do not reuse an aggregate gate merely because the plotted field is the same. |
| Terminal deceleration could visually resemble flutter. | Separate intended stopping from instability with a terminal window, reversal count, secondary-peak metric, landing error, and contact/state evidence. |
| The wide case needed safety retiming and therefore did not exactly retain the requested target speed. | A bounded target may yield to declared dynamics limits; report requested, achieved, and limiting constraint rather than hiding the retiming. |
| Isolated repeats reduced constant-speed ripple and showed no saturation or terminal reversals, but used the software simulator. | Retain the quantitative improvement as software qualification only, then use realtime and later digital-twin/physical reruns to test transfer. |

## Variation-admission gate

A proposed case, sub-problem, or submission is admitted only when all answers are
explicit and evidence-checkable:

1. What single causal question is added, and why can the baseline not answer it?
2. Which exact behavior-driving input changes, and which inputs stay fixed?
3. Does the change belong to immutable case/world truth, a planning submission,
   an execution profile, a backend overlay, or merely another run?
4. What accepted plan, trajectory, command, event, or feasible-set difference will
   result, and is it part of the semantic fingerprint?
5. Which machine-evaluable oracle distinguishes success from the baseline?
6. Which lower-level evidence can be reused, and what new integration gate remains?
7. Which backends can execute the semantics without a hidden fallback?
8. What safety, authority, dynamics, energy, actuator, and terminal bounds apply?
9. What operator-facing preview and post-run comparison make the difference clear?
10. Is the expected learning value worth the additional catalog, execution, and
    maintenance cost?
11. What bounded-search completeness/resolution claim and independent feasibility
    certificate make an accepted result safe to execute?

If the only difference is repetition, seed, clock mode, or display, record another
run or backend-qualification observation rather than inventing a semantic variation.

## Constraint-directed multi-drone design decision from current review

The reviewed `2d.bottleneck.canonical_nominal`,
`2d.head_on_conflict.canonical_nominal`, and `2d.merge.canonical_nominal` evidence is
a valid baseline for the current bounded planner, but it is not the end state. All
five reviewed runs passed their current route-capture, authored start/landing-
displacement, no-undeclared-stop, and separation oracles while selecting ground delay.
The retained evaluator is incomplete and target-relative landing error is unavailable
there, so this is not landing qualification. The evidence proves deterministic safe
serialization for those exact cases; it does not prove flexible obstacle-aware
maneuvering, geometry contact detection, same-time encounter resolution, or in-flight
replanning.

The durable direction is therefore:

- preserve those reviewed cases/runs as immutable ground-delay baselines;
- make a submission express allowable planner freedom and desired trade-off, not only
  a time/control law inferred from the current route;
- add a synchronized head-on successor that cannot pass through whole-role ground
  serialization and must choose an admitted lateral, vertical, or combined maneuver;
- let route adherence range from exact to soft/reference so a mission can demand
  accuracy or permit a bounded escape around a conflict;
- describe bridges, tunnels, side openings, ceilings, and other obstacles as world
  geometry whose remaining free space controls whether under, over, side, or timing
  solutions are feasible;
- distinguish conservative policy separation from actual geometry intersection and
  retain both in planning, runtime, and evidence; and
- progress from known static obstacles to bounded source-time obstacle/peer updates
  and atomic in-flight fleet replanning, without claiming autonomous real-world
  perception or crash physics.

## Altitude-transition design decision from current review

The current canonical and wide cases remain geometry variations of the same family.
The wide case changes the altitude envelope from approximately `0.25..0.65 m` to
`0.20..0.82 m`. The current evidence shows a longer route and duration, more energy
use, and modestly larger tracking error, but no qualitatively new control policy.
Therefore:

- `canonical_nominal` is the profile-development and bounded speed-sweep anchor;
- `wide` remains a vertical-envelope stress case;
- wide does not repeat every canonical profile automatically;
- after a canonical profile is qualified, wide repeats it only when the larger
  climb/descent amplitude can plausibly expose vertical-rate, thrust-headroom,
  tracking, energy, or landing differences; and
- constant-rotor-speed flight is not admitted as an altitude-transition submission.

The implemented initial submission set is intentionally small:

| Submission | Canonical | Wide | Reason |
|---|---:|---:|---|
| Current planner-retimed baseline | Retain reviewed runs | Retain reviewed runs | Establishes existing behavior and geometric delta. |
| Constant path speed, slow anchor | Qualify | Do not duplicate initially | Establishes the primitive with generous control margin. |
| Constant path speed, higher-stress anchor | Qualify after feasibility gate | Repeat after canonical qualification | The wider vertical envelope can expose vertical authority and tracking coupling. |
| One ramped slope/segment-speed schedule | Qualify | Run only if wide adds a declared headroom question | Tests intentional speed transitions rather than arbitrary variation. |
| Bounded vertical-rate / actuator-headroom profile | Derive evidence prerequisite | Preferred stress follow-on | More specific to wide altitude motion than a generic speed copy. |
| Constant motor/rotor speed | Not executable | Not executable | Low-level calibrated diagnostic, not compatible with guaranteed path tracking. |

Exact speed targets are derived from each route's segment lengths and horizontal/
vertical tangent bounds. Bounded allocation then applies acceleration/jerk gates,
while retained execution measures controller/actuator headroom, energy, and terminal
behavior. The initial ratios intentionally produce only a margin-rich anchor and one
higher-stress anchor; they are not a dense parameter grid.

The 2026-08-11 assisted refinement established that the excessive constant-speed
wave was primarily commanded by the old quintic time law rather than created by the
tracker: the repeated 0.18 m/s evidence had an approximately `0.133 m/s` recorded
90% route-speed band, with segment deviations reaching about 55%. The corrected
profile uses explicit entry/exit and knot-transition windows with flat-speed
interiors, samples the generated spline for conformance, and retains safety retiming
when the wide altitude envelope reaches a dynamics margin. Isolated accelerated
post-change runs reduced the constant-speed 90% steady ripple to approximately
`0.019..0.024 m/s`, completed without motor saturation, and showed no component-
velocity reversals in the last two landing seconds. These are software-simulation
results, not physical-controller qualification. The ramped-speed and bounded-
vertical-rate profiles remain segment-specific comparisons and do not use the
constant-speed aggregate-ripple gate.

## Feedback change log

| Date | Source | Durable result |
|---|---|---|
| 2026-08-11 | Operator review of four `1d.altitude_transition.canonical_nominal` runs, images, comments, and CSV evidence | Added exact-time visual evidence, neutral comment assessment, evaluator completeness, landing alignment/contact, deliberate speed-law, and repeated-run requirements. |
| 2026-08-11 | Operator review of `1d.altitude_transition.wide` runs and discussion of speed/control alternatives | Added the case/sub-problem/submission taxonomy, high-reasoning variation gate, mission-specific profiles, primitive reuse, future-backend transfer, and the constant-rotor-speed exclusion. |
| 2026-08-11 | Operator instruction that both altitude-transition missions are already in review | Added the rule that analysis and planning must not repeat lifecycle transitions or flags. |
| 2026-08-11 | Operator authorization to implement WP-40 through WP-43 | Added hash-bound submission selection, prerequisite gating, exact-time review frames, neutral snapshot assessment, campaign evaluator reconciliation, contact-aware target landing, derived altitude profiles, actuator evidence, and catalog selection without changing either case or its review state. |
| 2026-08-11 | Operator review of `2d.bottleneck.canonical_nominal`, `2d.head_on_conflict.canonical_nominal`, and `2d.merge.canonical_nominal`, including comments and CSV/evaluation evidence | Generalized “submission” into a case-bound planning request; added maneuver/path-adherence authority, geometry-backed contact and clearance, structured obstacle/free-space reasoning, synchronized forced-resolution behavior, and source-time in-flight replanning requirements. Evidence remains the baseline for the gap, not the definition of the desired workflow. |
| 2026-08-11 | Review of the proposed WP-44 through WP-50 delivery plan | Added a single resolved submission-package contract without conflating world truth and planner authority; separated nominal contact from uncertainty/policy clearance; required independent feasibility certificates and bounded-search claims; added reaction-horizon guarantees for dynamic replanning; made fleet landing review target-relative; required neutral snapshot assessment before image purge; and required raw-versus-filtered hard-gate reconciliation. |
| 2026-08-11 | Operator catalog-layout review of the execution-submission selector | Added the durable rule that submission/profile selection is nested beneath Mission case on the left while its explanatory and evidence content remains in the right detail pane. |
| 2026-08-11 | Operator request to distinguish runs made before and after completed work-package implementations | Added an explicit implementation-archive boundary for Run history. Reruns, comments, and changed locked inputs remain one active investigation journal; only completed, independently verified, applied work packets may start a new current group, with prior evidence retained below a labeled divider. |
| 2026-08-11 | Operator request for compact per-drone review graphs instead of row-by-row CSV presentation | Added CSV-derived review plots for velocity magnitude, world-Z altitude, and motor output percentage over time, with comparable drone identities/scales and the raw download preserved. |
| 2026-08-11 | Operator review of the live Attitude & IMU readout | Extended each retained run's compact graphs with roll/pitch/yaw, acceleration X/Y/Z, and angular velocity X/Y/Z histories while preserving the existing instantaneous readout. |
| 2026-08-11 | Operator reruns of both altitude-transition cases and request for assisted parameter iteration | Added sampled planned/recorded constant-speed conformance, explicit transition windows, terminal flutter separation, causal-layer-first correction, profile-aware reporting, and the isolated assisted pre/post iteration workflow. The first refinement reduced steady ripple substantially without changing either case's Review state. |
| 2026-08-11 | Operator request to retain iterative-testing learnings as the default future feature-testing method | Renamed this document to `WORKFLOW_AND_REQUIREMENTS.md` and generalized the altitude refinement into a reusable tuning contract, candidate ledger, staged screening, cross-case non-regression, finite stop/revert rules, and operator/realtime/digital-twin handoff. |
| 2026-08-11 | Operator request for automatic independent review of explicitly requested work packets before and after implementation, plus reconciliation of past/current documentation mismatches | Added the two-gate `work_packet_verifier` protocol, reviewer-owned verdicts, exact dirty-tree payload identity, independent production-path oracles and counterexamples, claim-specific evidence dimensions, bounded one-recheck limits, fail-closed reviewer availability, and documentation-to-executable-reality reconciliation. |
| 2026-08-11 | Operator request to make the WP-44 through WP-50 audit and repair approach the default for iterative work packets | Added an author-driven packet loop that re-audits inherited claims, derives and creates its own sensitive tests, implements production-path vertical slices, exercises adverse/generalized cases, broadens regression checks, and reconciles each packet's demonstrated boundary before independent verification. |
| 2026-08-11 | Operator instruction that mission testing and iteration must produce reusable drone/fleet capabilities rather than copied mission-specific implementations | Required accepted learnings to enter a core owning layer, added stable capability requests with automatic case binding, retained explicit applicability gates, and required execution time laws to compose with flexible planner geometry instead of forcing direct routes. |
| 2026-08-12 | Operator request to retain the knowledge from all WP-52 through WP-56 repetitions, revisions, and iterations so future packets need fewer revisions | Added mandatory pre-freeze machine audits and prototypes; exact peer/baseline comparator and collapse-target rules; symmetric, feasible, axis-compatible comparison contexts; resampling invariance; exact rejection taxonomy; production-trigger claim tracing; literal row-record round trips; byte-reproducible preimages; cumulative retrospectives; and served-release UI evidence. |
| 2026-08-12 | R6 implementation discovered that its historical prototype hashed a registry the accepted implementation had to replace | Added phase-separated oracle identity: retain the pre-draft artifact unchanged, then reconcile current exact identities and independently measured semantics through a distinct implementation artifact instead of requiring a mutable preimage to regenerate unchanged. |
| 2026-08-12 | R8 pre-draft runtime evidence found safe, deterministic alternatives whose frozen distinguishing clauses were invariant or below the declared threshold | Added `REQ-WFL-041`: execution eligibility now requires the complete qualifying relation to be discriminable through its named evidence boundary; different hashes and hard-gate success alone cannot qualify a submission. |
| 2026-08-12 | Operator requested a durable process for gathering multiple analysis runs before asking for improvements | Added the investigation-journal-to-work-packet handoff: retain all run evidence and notes, consolidate designated journals into an evidence synthesis on request, and only enter work-packet structuring and its independent gates when explicitly requested. |
| 2026-08-12 | Operator requested a WP-52 through WP-56 token/value retrospective and a cheaper future review workflow | Added intent/value and scope-challenge gates, narrow must-fix/defer dispositions, a hard post-recheck stop with operator approval only for critical successors, transparent cost proxies when token telemetry is absent, and adaptive Terra/Sol-class model routing instead of defaulting every task to frontier xhigh reasoning. |
| 2026-08-14 | Operator synthesis request over all completed 1D runs, smoother whole-route motion, realistic one-drone sensed-obstacle replanning, motor-physics review, and a real-drone digital-twin learning pipeline | Added a multi-axis motion-quality contract; explicit checkpoint versus continuous traversal; whole-route, resampling-invariant velocity planning; hash-bound in-flight profile changes; one-drone sensor-sourced replanning; per-motor physical-truth reconciliation; source-aligned all-sensor twin evidence; bounded holdout calibration; and fail-closed staged hardware progression. |
| 2026-08-14 | WP-57 through WP-61 focused design recheck found an incomplete calibration guard/repeat oracle and three omitted production boundaries | Added complete primary-plus-secondary numerical prototype requirements with exact repeat semantics (`REQ-WFL-046`) and mechanical claim-owner/production-transit manifest closure (`REQ-WFL-047`) before design freeze. |
| 2026-08-14 | WP-57 through WP-61 final-cycle initial review found prose-only reaction safety, missing isolated motion/safety calibration vectors, and self-referential boundary closure | Strengthened isolated guard and independently derived boundary-set requirements and added an exact sensed-world reaction/certificate/fallback prototype gate (`REQ-WFL-048`). |
| 2026-08-14 | Operator-authorized WP-57 through WP-61 successor cycle after the final focused recheck found an internally complete but semantically incomplete guard registry | Added independently derived guard-universe closure (`REQ-WFL-049`) so future calibration and qualification audits cannot omit declared headroom, energy, signed actuation, or traversal-mode protections. |
| 2026-08-14 | Operator feedback that the WP-57 through WP-61 implementation handoff spent excessive time and tokens on analysis without producing code | Added the verified-design-to-code stop rule (`REQ-WFL-050`): implement a known bounded gap immediately, run the declared checks once, proceed to independent implementation verification, and restrict the correction pass to P0/P1 or `MUST_FIX_NOW` findings. |
| 2026-08-14 | Operator feedback that a later scope-narrowing instruction was acknowledged but the broader investigation continued anyway | Added the scope-reduction stop rule (`REQ-WFL-051`): invalidate the broader pending plan, use one targeted output-capped inspection, stop when the named gap is resolved, and prohibit unrequested diagnostics or follow-ons. |
| 2026-08-14 | Operator request to separate the 1D runs already used for implementation work from new post-revision evidence | Made the run-history generation boundary executable (`REQ-WFL-052`): persisted old/revision metadata, exclusion from later qualification and comparison, a visible `Old runs` divider, and an explicit post-commit cutoff command for every future affected scope. |
