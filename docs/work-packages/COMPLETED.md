# Completed work

| Field | Value |
|---|---|
| Document role | The only authoritative ledger for finished project work |
| Status | `CURRENT` |
| Last reconciled | 2026-08-09 |
| Active counterpart | [`ACTIVE.md`](ACTIVE.md) |
| Default operator backend | `FAST_SIM` |
| Physical flight authorized | No |
| Digital twin enabled | No |

## Meaning of “completed”

An item belongs here only when its implemented boundary and evidence are known. A
software completion never implies live Isaac, hardware, physical accuracy, or digital-
twin qualification. Implemented parts of an open package remain checked in
[`ACTIVE.md`](ACTIVE.md) until that complete package passes its exit gate.

## Completed software foundation

| Scope | Finished capability | Primary record |
|---|---|---|
| Application and UI foundation | Authenticated API/WebSocket boundary, operator dashboard, source-aware telemetry, explicit mode and lifecycle state, abort versus emergency stop, evidence and replay | [`../project/DESIGN.md`](../project/DESIGN.md) |
| Fast Simulator baseline | Deterministic fixed-step 6-DOF vehicle, commands, room/obstacles, modeled sensors and battery, fault injection, real-time/accelerated clocks, canonical scenarios, replay, and CI fallback | [`../guides/FAST_SIMULATOR.md`](../guides/FAST_SIMULATOR.md) |
| Fast Sim physical model v2 software gate | Battery-coupled powertrain, parameter/provenance contracts, structured sensor errors, reduced-order aerodynamics, compatibility, repeatability, and machine-readable fidelity | [`../reference/FAST_SIM_PHYSICS_V2.md`](../reference/FAST_SIM_PHYSICS_V2.md) |
| Mission portability / Reality WP-00–03 | Immutable restricted mission source, backend-neutral mission/vehicle boundary, online health enforcement, real-adapter software boundary, and explicit physical claim gates | [`../qualification/REALITY_RELEASE_ADDENDUM.md`](../qualification/REALITY_RELEASE_ADDENDUM.md) |
| NVIDIA architecture and mock boundary | Out-of-process gateway architecture, namespace and identity isolation, minimal scene specification, mock gateway, host precheck, and bounded live-entry runbook | [`../reference/NVIDIA_ISAAC_ARCHITECTURE_V1.md`](../reference/NVIDIA_ISAAC_ARCHITECTURE_V1.md) |

The physical-v2 gate is `SOFTWARE_QUALIFIED_CONFIGURED_UNQUALIFIED`: exact-aircraft
coefficients, endurance, sensors, contact, and prediction accuracy are intentionally
not completed.

## Completed fleet work packages

| Package | Completed result |
|---|---|
| WP-01 — Mission-derived deployment | Mission package v2 derives one to three logical members, roles, homes, capabilities, zones, tasks, and backend-neutral deployment identity. Fast Sim/mock Isaac provision; physical binding fails closed without an approved profile. |
| WP-02 — One-click preparation | The existing Play path owns validation, provisioning, identity verification, connection, observation, preflight, start, cancel, safe disconnect, and cleanup with real per-member lifecycle state. |
| WP-03 — Zone and task abstraction | Backend-independent zones/tasks, obstacle-aware decomposition, capability and energy gates, task progress, leases, retry/reassignment, and replay are implemented. |
| WP-04 — Unified execution | One role runs through `MissionRunner`; multi-role packages run through `FleetCoordinator` with isolated child runs, deterministic routing, sequential launch, separation checks, terminal evidence, and bounded cleanup. |
| WP-05 — Persistent fleet components | Deterministic allocation, two active roles plus a connected ready reserve, generation-numbered leases, confirmed takeover rules, stale-owner rejection, and degraded/failed outcomes are implemented as reusable fleet components. |
| WP-06 — Abstract dock and charging | Capacity, reservation, queue, retry/diversion, modeled landing/contact, charge confirmation, progress, and ready state exist without physical docking claims. |
| WP-07 — Metrics and qualification | Coverage, availability, separation, handover, energy, dock, recovery, command latency, evidence, replay, deterministic seed, parity, and bounded-load qualification components exist. |
| WP-08 — Mock/live-Isaac portability boundary | Fleet session identity, per-vehicle namespaces, gateway protocol `1.3.0`, mock-Isaac parity, loss handling, and Fast Sim fallback are frozen; live Isaac remains unrun. |
| WP-09 — Production persistent reserve handover | The normal Play path detects source-aware low battery, keeps the reserve ready and disarmed, flies it through `MissionRunner`/`SafetySupervisor`, confirms takeover geometry, atomically transfers task ownership to generation 2, rejects stale generation-1 commands, returns/lands the outgoing member, and records dock/charging, faults, evidence, and bounded cleanup. |
| WP-10 — Supporting coordination missions | Backend-neutral crossing-route and wide leader/follower missions run through normal Play. Source-aware warning handling gates and holds one route, releases it after the peer clears, and escalates a continuing critical crossing to abort/landing of both members. Global-offset and relative-speed evidence are bounded; leader/follower loss lands the peer; cancellation/restart cleans up; identity/task/command routing remains isolated; and normalized crossing replay is stable across declared seeds. |
| WP-11 — Deterministic operational mission planner | Immutable mission source, logical deployment, current planning observations, obstacles, and active safety policy compile into a backend-neutral hash-addressed receipt. Preview exposes the receipt; Start recompiles it, blocks unsafe or unconfirmed plans before provisioning, and binds the accepted receipt to execution evidence. Flight volume, dynamics, duration, separation, obstacle, and battery findings are qualified through the settled same-tree backend/UI gate. |
| WP-12 — Plugin contracts and registries | Frozen proposal-only `RoutePlanner`, `FleetPolicy`, and `RecoveryStrategy` contracts, semantic manifests, implementation hashes, exact allow-listed resolution, qualification state, selection binding, and a common deterministic/bounded contract harness are implemented. Plugins have no adapter/command surface and safety declarations can only tighten global policy. |
| WP-13 — Route planners and temporal corridors | Direct, zone/obstacle-aware, coverage, and temporal planners return immutable waypoint/timing/energy/corridor/completion/finding receipts. Dock and leader/follower capabilities are explicit. Temporal precedence is bounded; unresolved geometry, timing, frame, and conflict inputs fail closed. Replanning explicitly stales the previous route hash. |
| WP-14 — Fleet policy, recovery, and Safety Kernel | Persistent, crossing-route, leader/follower, and independent policies plus eight standardized recovery strategies are registered and hash-bound. `FleetCoordinator` consumes the accepted policy launch order and records Safety-Kernel-admitted low-battery and leader-loss proposals before established runtime enforcement. The non-pluggable Safety Kernel/Supervisor retains final authority. |
| WP-15 — Mission intent and execution graph | Objectives, success criteria, roles, bounded phases, completion, transitions, contingencies, and safety declarations compile into an immutable graph. Cycles, unreachable/unbounded/unknown inputs and undeclared recovery are rejected. Restricted Python remains explicit-action compatible, and execution rejects assignments absent from the accepted graph/routes. |
| WP-16 — Exact operator review and approval | The Control Center displays objective, component versions, phases, routes, timing, energy, plan/safety hashes, blockers, confirmable risks, and limitations. Approval binds the exact plan, safety case, manifests, acknowledgements, expiry, and operator client; Start recompiles and rejects missing, stale, consumed, changed, or other-client approval before provisioning. |
| WP-17 — Fast Sim planner qualification and release | Every 4 route planners, 4 fleet policies, and 8 recovery strategies pass the shared contract harness. Canonical nominal/rejection/energy/loss/cancellation/separation/conflict/recovery/contingency/cleanup cases, cross-process and repeated deterministic receipts, API/client parity, repository/UI gates, and explicit deferred-system `NOT_RUN` claims are recorded. |
| WP-18 — Persistent mission run files and bottom-control consolidation | Every terminal mission is atomically persisted as one deterministic, authenticated `run-telemetry-v1` CSV derived from checksum-verified telemetry evidence, regardless of drone count. One manifest/folder/CSV groups the mission while every row retains child run and vehicle identity; success, failure, and abort are retained under a configurable latest-100-mission policy shared with SQLite. The bottom-left Run files control sits directly after Play and shows one compact, non-expandable mission row with aggregate status, mission name, an icon-only download control, and total sample count. Reposition and Recharge remain in the right-side cluster next to Flight information without broadening Fast Sim admission or target scope. |
| WP-19 — Mission-execution evaluator and analysis baseline | Every materialized mission now has one deterministic complete execution bundle and evaluator report alongside its telemetry CSV. Accepted plan/deployment/binding, child and fleet evidence/results, commands, acknowledgements, provenance, and optional authenticated operator notes share one execution identity. Estimate/truth, inherited/new faults, target/tracking/motion/boundary/time/energy/terminal/separation metrics, explicit missing-evidence classification, concise summaries, canonical hashes, persisted downloads, and real uploaded two-role execution are qualified without changing motion or safety behavior. |
| WP-20 — Authoritative smooth trajectory execution | Eligible accepted single-role plans now carry hash-bound absolute C2 trajectories and schedule/timeout/clock contracts used as runtime motion authority. Fast Sim executes consecutive moves continuously, validates and settles by tracking tolerance, exposes explicit capability support, retains supervisor preemption, and records generation-versus-tracking evidence. The canonical 2.4 m route has zero internal stops and equivalent accelerated/real-time invariants. |
| WP-21 — Goal-region arrival and landing | Accepted programs carry hash-bound absolute landing regions. Fresh alignment and speed capture gates descent; bounded correction and fail-closed rejection are explicit; terminal estimate/truth, margins, attempts, state, and simulator-only contact evidence are retained. Canonical accelerated/real-time single and non-conflicting two-role cases finish inside their regions with bounded velocity and `READY`. |
| WP-22 — Predictive two-drone deconfliction | Time-aligned trajectory tubes expose closest approach and a narrow conflict window. Deterministic staging, retiming, horizontal, vertical, and combined candidates are hard-filtered; canonical crossing executes the exact admitted staging program in accelerated and real-time Fast Sim with no warning/critical sample or timeout. Reactive warning/critical fallback remains independent. |
| WP-23 — Parameterized mission cases and curriculum | Five versioned templates expand deterministically over compact/nominal/wide borders and two seeds into 30 immutable cases. Each binds goals, hard constraints, objectives, strategies, thresholds, source, and identity. Evaluator reports become hashed baselines; promotion is level ordered and blocks all higher levels on a lower-level regression. The no-hover crossing executes continuous retiming through normal Play. |
| WP-24 — Scalable multi-drone conflict planning | Three-role conflicts are scheduled as one joint graph. Bounded exact enumeration applies priority, wait, fairness, duration, and starvation gates; larger inputs expose a deterministic priority-greedy heuristic and explicit optimality limit. Canonical accelerated/real-time execution plus merge, bottleneck, unequal-priority, and constrained-border variants preserve exact program identity, complete goals/evidence, and zero warning/critical samples. Infeasible schedules fail admission with deadlock and safe recovery evidence. |
| WP-25 — Robustness qualification and higher-fidelity handoff | A 16-cell, seven-profile matrix binds lower-level cases to seeds, noise, latency, clock rate, observation loss, trajectory timeout, and recovery. All cells pass complete persisted evaluation, hard margin/safe-terminal gates, repeated-outcome checks, and accelerated/real-time reconciliation. A three-case backend-neutral handoff records required signals, thresholds, stop conditions, and `NOT_RUN` Isaac/physical status without granting authority. |
| WP-26 — Evidence-correct analysis and timing | Offline source-clock analysis, bounded timing traces, explicit primary-cause classification, browser-owned render timing, and numeric accelerated/realtime comparison tolerances are implemented and hash-bound. |
| WP-27 — Immutable campaign contract and catalog | Versioned cases bind goals, constraints, objectives, allowed strategies, execution settings, cluster, plain-language behavior and outcome, authorization, identity, prerequisites, and lifecycle metadata kept outside the immutable definition. |
| WP-28 — Ground-first scheduling | Joint schedules keep vehicles on the ground until their admitted launch slot, record schedule identity and energy accounting, and bound airborne wait before route execution. |
| WP-29 — Bounded 3-D conflict planner | Deterministic timing, speed, detour, altitude, and combined candidates are hard-filtered and lexicographically compared with explicit rejection reasons and optimality limits. |
| WP-30 — Smooth trajectory generation and execution | Hash-bound C2 trajectory sets, source-time tracking, exact retained-runtime execution, and supervisor preemption are integrated with campaign plans and evidence. |
| WP-31 — Campaign runner and review queue | One persistent service owns selection locks, previews, bounded runs, artifact import, analysis, mode comparison, observations, approvals, promotion, recommendations, idempotency, and fail-closed identity reconciliation. |
| WP-32 — Campaign panel | The Control Center exposes Simulation/Real, five mission clusters, fleet size, immutable case selection, immediate compatible-case switching, plain-language purpose/behavior/outcome, validation, activation, preview, run controls, and operator review. |
| WP-33 — Progressive campaign library | The generated library contains 127 simulation cases and 35 unauthorized real mirrors, physically grouped by the five mission clusters and then fleet size, with per-case Python metadata templates. |
| WP-34 — Dynamic goals and online replanning | Bounded single-goal replacement plus atomic multi-role replanning validate authority, generations, acknowledgements, planning budgets, stale/duplicate updates, replacement rollback, and declared recovery. |

Detailed fleet implementation records are retained in:

- [`../qualification/FLEET_FOUNDATION_WP01_04.md`](../qualification/FLEET_FOUNDATION_WP01_04.md)
- [`../qualification/PERSISTENT_FLEET_WP05_08.md`](../qualification/PERSISTENT_FLEET_WP05_08.md)
- [`../reference/MISSION_PACKAGE_V2.md`](../reference/MISSION_PACKAGE_V2.md)
- [`../qualification/COORDINATION_MISSIONS_WP10.md`](../qualification/COORDINATION_MISSIONS_WP10.md)
- [`../qualification/RUN_HISTORY_CSV_WP18.md`](../qualification/RUN_HISTORY_CSV_WP18.md)
- [`../qualification/MISSION_EVALUATION_WP19.md`](../qualification/MISSION_EVALUATION_WP19.md)
- [`../qualification/SMOOTH_TRAJECTORY_WP20.md`](../qualification/SMOOTH_TRAJECTORY_WP20.md)
- [`../qualification/GOAL_LANDING_WP21.md`](../qualification/GOAL_LANDING_WP21.md)
- [`../qualification/PREDICTIVE_DECONFLICTION_WP22.md`](../qualification/PREDICTIVE_DECONFLICTION_WP22.md)
- [`../qualification/MISSION_CURRICULUM_WP23.md`](../qualification/MISSION_CURRICULUM_WP23.md)
- [`../reference/MULTI_DRONE_CONFLICT_PLANNING_V1.md`](../reference/MULTI_DRONE_CONFLICT_PLANNING_V1.md)
- [`../qualification/MULTI_DRONE_CONFLICT_WP24.md`](../qualification/MULTI_DRONE_CONFLICT_WP24.md)
- [`../reference/MISSION_ROBUSTNESS_MATRIX_V1.md`](../reference/MISSION_ROBUSTNESS_MATRIX_V1.md)
- [`../qualification/MISSION_ROBUSTNESS_WP25.md`](../qualification/MISSION_ROBUSTNESS_WP25.md)
- [`../qualification/CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md`](../qualification/CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md)

## ACTIVE-WP-09 and ACTIVE-WP-10 closeout

Both packages are present and locally reconciled in this tree.

WP-09 uses one serialized current fleet binding across `ExecutionCoordinator`, child
mission context, watchdog, recovery, and cleanup. Its Fast Sim handover evidence lives
in [`../../tests/api/test_persistent_handover.py`](../../tests/api/test_persistent_handover.py),
including generation-2 takeover and direct stale-generation rejection. The detailed
component record remains
[`../qualification/PERSISTENT_FLEET_WP05_08.md`](../qualification/PERSISTENT_FLEET_WP05_08.md).

WP-10 adds
[`../../missions/qualification/crossing_route_separation.py`](../../missions/qualification/crossing_route_separation.py)
and
[`../../missions/qualification/leader_follower_recovery.py`](../../missions/qualification/leader_follower_recovery.py).
The production policies and serialized evidence are implemented in fleet software,
not in a concrete adapter or browser path. Warning separation uses a fleet-bound
supervisor hold and deterministic route release; critical separation uses the normal
child cancellation and abort/landing recovery. The full threshold, injected-fault,
cancellation/restart, replay, and claim boundary is recorded in
[`../qualification/COORDINATION_MISSIONS_WP10.md`](../qualification/COORDINATION_MISSIONS_WP10.md).

## Documentation work package

`DOCS-WP-01` is complete:

- All current planning is reduced to `COMPLETED.md` and `ACTIVE.md`.
- Product, system, guides, references, qualification records, and archive material
  have distinct directories.
- The mission/planner/control-center/simulator responsibility boundary and codebase
  map are documented in [`../system/README.md`](../system/README.md).
- Historical packet sources are retained but explicitly non-authoritative.

## Recorded verification evidence

- The last recorded broad closeout before the newest WP-09 integration passed 437
  Python tests with one intentional live-Isaac skip, Ruff, strict MyPy over 156 files,
  canonical/release/fleet qualification, UI lint/typecheck/tests/build, regenerated
  OpenAPI/client parity, and npm audit.
- On 2026-08-07, after the newer WP-09 production path appeared in the tree, the
  focused persistent-handover, authority-transition, and mission-runner selection
  passed 16 tests. After adding the documentation-structure regression, the current
  suite collected 448 tests at that reconciliation point.
- The reconciled WP-09/WP-10 tree passes 476 repository tests with one intentional
  live-Isaac host skip. The final full-load run has no lease-heartbeat or readiness-
  window failure. Repository Ruff and strict MyPy over 164 source/test files pass.
- WP-10's normal Play gate covers warning hold/release, a two-seed normalized replay,
  critical abort/landing, nominal global-offset tracking, cancellation/restart, five
  leader-loss sources, and follower loss. Its backend-neutral policy unit and
  mission-package checks also pass.
- Generated OpenAPI/client parity, UI lint, TypeScript, 69 unit tests, the production
  build, and three rendered-HTML tests pass. Canonical scenarios pass twice; fleet
  foundation, persistent fleet, and load qualification pass as software-only. Live
  Isaac and physical flight remain `NOT_RUN`.
- The WP-12 through WP-17 same-tree release passes 491 Python tests with one intentional
  live-Isaac host skip, Ruff, and strict MyPy over 177 source/test files. Generated
  OpenAPI/client parity and release-artifact checks pass. UI lint and TypeScript pass;
  71 unit tests, the production build, and three rendered-HTML tests pass.
- `planning-release-fast-sim-v1` qualifies 4 route planners, 4 fleet policies, and 8
  recovery strategies. Its canonical report SHA-256 is
  `8352fa8d0cc7e886ae10424f6521a20abbaf0f3cf1e14310a96e01a670d524fe`.
- The amended WP-18 same-tree release passes 500 Python tests with one intentional live-Isaac
  host skip, Ruff, and strict MyPy over 178 source/test files. Generated OpenAPI/client
  parity passes. UI ESLint and TypeScript pass; 80 unit tests, the production build,
  and three rendered-HTML tests pass. Its pre-reset performance gate served 20 run
  rows in 0.050935 seconds and 100 mission manifests in 0.025597 seconds through the UI
  proxy. The current contract consolidates every mission to one CSV; the focused
  two-drone test verifies both child run and vehicle IDs in that single file. The
  128-column header-only CSV fixture SHA-256 is
  `3ab3700c0b8a159b8d7cc1f3393027806ff7ce634d41a90d25767f935de9dfa1`.
- WP-19 passes 502 Python tests with the same intentional live-Isaac skip, repository
  Ruff, strict MyPy over 180 source/test files, four frozen canonical scenario families,
  regenerated OpenAPI/client parity, UI lint/typecheck, 80 unit tests, production
  build, three rendered-HTML tests, and a zero-vulnerability dependency audit. Its
  focused gates prove deterministic single and grouped two-child reports, run-scoped
  faults, complete/missing evidence, annotations, persisted hashes, and a complete real
  uploaded two-role execution bundle.
- WP-20 adds three focused trajectory qualifications. Its full regression reached 504
  passes before the expected frozen-manifest update; the corrected release/trajectory/
  load set passes, as do Ruff, strict MyPy over 182 files, regenerated API/client
  parity, UI lint/typecheck, 80 unit tests, production builds, three rendered checks,
  and a zero-vulnerability audit. Three repeated load runs preserve the 50 ms storage
  p95 budget with measured p95 between 10.3 and 11.6 ms.
- WP-21 adds five focused goal/trajectory qualifications plus the grouped two-role API
  gate. The full suite reaches 506 passes with one intentional live-Isaac skip; its
  only pre-transition mismatch was the frozen active-ledger assertion. Ruff and strict
  MyPy pass over 183 files.
- WP-22 passes all 12 coordination tests and 31 planning/trajectory/release tests.
  Accelerated and real-time nominal crossing, two-seed replay, reactive critical
  fallback, alternative candidate feasibility, and unchanged leader/follower recovery
  pass. Ruff and strict MyPy pass over 185 files.
- WP-23 passes 17 focused curriculum/package/planning/no-hover/release tests. All 30
  generated cases parse and compile; promotion accepts complete baselines and blocks
  higher levels on a level-2 regression. Ruff and strict MyPy pass over 188 files.
- WP-24 passes four focused planner tests, the canonical three-drone normal Play gate
  in accelerated and real-time Fast Sim, and four additional execution/evaluator
  variants. Its 43-test planning/mission/evaluator/release set passes. Repository Ruff
  and strict MyPy pass over 190 source/test files.
- WP-25's 16-cell normal-Play matrix passes in 108.80 seconds with 100% per-profile
  pass rates, complete live/persisted evaluator parity, reproducible expected failures,
  zero warning/critical samples, and a passing non-authorizing handoff. Final whole-tree
  coverage passes 529 Python tests with one intentional live-Isaac host skip, split into
  isolated 496-test, 19-test coordination, and 14-test persistent-handover shards. The
  realtime coordination harness collects closed runtime cycles between tests so deferred
  GC cannot occur inside a one-second safety freshness window; the production freshness
  threshold remains unchanged. Repository Ruff and strict MyPy pass over 193 source/test
  files. Four canonical families reproduce twice under the new execution-authority and
  goal-landing outcome revision, with both earlier hash generations retained.

## Frozen guarantees

1. Fast Sim remains deterministic, available without NVIDIA, and retained for CI.
2. Mission Python never imports or constructs a concrete adapter.
3. Every command is bound to vehicle, run, and—where applicable—fleet task lease.
4. Connected is not armed; detected hardware never launches automatically.
5. Missing or invalid observations never become plausible defaults.
6. Configured, simulated, measured, replayed, planned, and unavailable values remain
   distinguishable.
7. Adapter, process, network, or renderer failure cannot become mission success.
8. Mission, configuration, model, scenario, and evidence identity remain traceable.
9. `DIGITAL_TWIN` remains disabled until the external qualification gates pass.
10. CSV download is a read-only telemetry view and never grants command or replay
    authority.
11. Execution evaluation and operator annotation are read-only evidence operations and
    never grant command authority or relax a hard safety gate.
12. An accepted static trajectory is hash-bound to its plan and program; unsupported
    backends fail before launch and may not silently substitute micro-command motion.
13. Nominal landing descent requires an admitted goal-region capture; simulator
    contact evidence is never a physical docking or contact-dynamics claim.
14. A nominal crossing executes one hash-bound deconfliction strategy; reactive
    warning/critical enforcement remains independent fallback authority.
15. Curriculum promotion is case-hash and evaluator-report bound; missing or failed
   lower-level evidence cannot be averaged away.
16. Multi-role conflict authority is selected from one joint schedule; blocked,
    starved, or duration-invalid candidates cannot be composed from independent pair
    decisions or launched as accepted authority.
17. Robustness promotion is cell/configuration/report bound; hard failures cannot be
    averaged away, and a terminal API result is not durable until its refreshed
    evaluation/bundle is materialized.

## Explicitly not completed

- A compatible, qualified live Isaac host and live Isaac/ROS/PhysX execution.
- Real Crazyflie bench, contained-flight, multi-drone, docking, or charging evidence.
- Physical-model calibration, contact dynamics, camera/RTX sensors, RF fidelity, or
  cross-source accuracy qualification.
- A digital-twin release, tight formation, flocking, manipulation, or real persistent
  fleet claim.

Every unfinished item is routed through [`ACTIVE.md`](ACTIVE.md).
