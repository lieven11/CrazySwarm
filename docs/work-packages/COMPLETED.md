# Completed work

| Field | Value |
|---|---|
| Document role | The only authoritative ledger for finished project work |
| Status | `CURRENT` |
| Last reconciled | 2026-08-11 |
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

## Implemented components from open WP-44 through WP-50

WP-44 through WP-50 remain in [`ACTIVE.md`](ACTIVE.md) because their packet exit gates
are not all closed. The following reusable components are complete within a narrower
software boundary:

- hash-bound, case-specific planning submissions and resolved packages, including
  exact package/component/runtime authority-chain validation;
- bounded static planning dispositions, continuous release candidates, admitted
  timing/lateral/vertical generators, and independent piecewise-linear cylinder/AABB
  feasibility certificates;
- named AABB solids/passages, contradiction checks, scalar protected passage capacity,
  and route-adherence checks;
- a Fast-Sim execution head for accepted obstacle/passage changes on two or three
  `AUTO_WITHIN_FROZEN_LIMITS` roles, with fresh observation, actual changed-world
  planning, software-epoch commitment, replacement dispatch, and exact evaluator
  identity evidence; and
- a deterministic 19-row regression subset. Its accepted object-in-line row is backed
  by a real changed-world proposal and per-role certificates; peer and negative rows
  are labeled `COORDINATOR_TRANSACTION_ONLY`. The report SHA-256 is
  `4f386eb18e5906cab5ad9ae74a1a823a54d300b581283386d0230723ead41d94`.

These completed components do not close composite pose-aware geometry, topology,
peer/uncertainty/goal-update runtime integration, backend-level distributed cutover,
the required successor matrix, observed-realtime anchors, or dynamic replay UI. The
packet-by-packet evidence and remaining gates are retained in
[`WP44_50_IMPLEMENTATION_AUDIT_2026-08-11.md`](WP44_50_IMPLEMENTATION_AUDIT_2026-08-11.md).
No physical, live-Isaac, damage/contact-dynamics, or perception claim is made.

## WP-51 — Independent work-packet verification and truthful qualification

**Status:** `COMPLETE`

**Independent verification:** `IMPLEMENTATION_VERIFIED`.

<!-- WP51-DESIGN-PAYLOAD-BEGIN -->

**Objective:** make independent, bounded verification automatic whenever the operator
explicitly asks Codex to create, structure, refine, implement, execute, complete,
verify, qualify, or transition one or more work packets/work packages. Ordinary small
tasks, explanations, status questions, and incidental mentions do not activate this
protocol; an explicit work-packet request does, even when its implementation is small.

**Dependencies:** the repository work-packet ledgers, durable requirements, Codex
project instructions, project-scoped custom agents, and an available independent-agent
slot. This packet does not depend on WP-44 through WP-50 implementation correctness.

### Tasks

- Add durable requirements that record the repeated WP-26–34, WP-40–43, and WP-44–50
  failure modes: author confirmation bias, assertions that mirror implementation,
  configured metadata presented as measured behavior, component/model tests presented
  as runtime evidence, exact-case special casing presented as generalized capability,
  documentation/status claims ahead of executable reality, and ambiguous dirty-tree
  review scope.
- Add a root `AGENTS.md` trigger. For a design-only request, create a
  `DRAFT_UNVERIFIED` packet and perform only the design gate. For implementation of an
  existing packet, require a recorded passing design gate first.
- Add a project-scoped, read-only `work_packet_verifier` custom agent. It never edits,
  never spawns another verifier for its own review, and owns finding severity and the
  gate verdict. The author may fix a finding or submit contrary evidence, but may not
  unilaterally dismiss a blocking finding.
- At the design gate, give a fresh verifier the originating operator request, durable
  requirements, exact delimited design-payload hash, and affected system boundaries.
  Require it to challenge coverage, dependencies, invariants, non-goals, integration
  points, feasible evidence, and counterexamples. Allow one author revision and one
  focused recheck by the same verifier; no automatic third pass.
- At the implementation gate, mark ordinary `Status` using the repository vocabulary
  and set the separate `Independent verification` field to
  `IMPLEMENTED_UNVERIFIED`. Give a different fresh verifier the original request,
  accepted design hash, exact implementation payload manifest, tests/evidence, and
  documentation claims. Allow one fix pass and one focused recheck by that verifier;
  no automatic third pass.
- For every core or generalized claim, require a chain from the real trigger and
  production entry point through the resulting state/command change to a retained
  observation and an independent oracle. Demonstrate at least one intended path and
  one meaningful failure, perturbation, rename/reordering, child-case, or boundary
  counterexample as applicable. An oracle derived from caller-supplied booleans,
  asserted hashes, configured durations, the same implementation constant, or a test
  that merely regenerates its own expected report is not independent.
- Tag each claim separately by execution boundary (`MODEL_ONLY`, `COMPONENT`,
  `INTEGRATION`, or `PRODUCTION_ENTRY`), environment (`NO_RUNTIME`, `FAST_SIM`,
  `LIVE_ISAAC`, or `HARDWARE`), and clock evidence (`NOT_APPLICABLE`, `ACCELERATED`,
  or `OBSERVED_REALTIME`). A reviewer pass is necessary but never substitutes for the
  packet's declared qualification evidence, and a lower boundary/environment may not
  close a higher claim.
- Reconcile every `implemented`, `verified`, `qualified`, runtime, end-to-end, and
  generalized-capability statement in `ACTIVE.md`, `COMPLETED.md`, qualification
  reports, and operator documentation against that claim matrix before closeout. A
  requirement-to-filename or requirement-to-test-name table is not sufficient.
- Freeze a scoped review manifest before each gate. It records the base commit,
  preimage hashes, changed/new/deleted file manifest, postimage hashes, and delimited
  payload hash. Only a mechanical verification-record/status update and unchanged move
  between ledgers may occur after verdict; any other substantive edit invalidates it.
- If no independent verifier/configuration/slot is available, fail closed as
  `REVIEW_BLOCKED` or `IMPLEMENTED_UNVERIFIED`. Do not substitute same-author review,
  recursively delegate, or loop until a pass appears.
- Add structural tests that parse the custom-agent TOML, verify required read-only and
  no-recursion instructions, verify the `AGENTS.md` trigger and bounded two-gate rules,
  and confirm the durable workflow/ledger records are present. Run patch-format and
  focused release-artifact checks.

**Non-goals:** exhaustive formal verification; replacing normal unit/integration/
runtime tests; automatically creating user-owned chats; spawning one reviewer per
packet when one related packet batch is the declared review unit; style-only review;
or repeated reviewer loops. P2/residual limitations may be recorded without blocking
rough integration acceptance; unresolved P0/P1 findings block the applicable gate.

### Exit gate

1. The project instructions activate only for explicit work-packet/package actions and
   correctly stop design-only requests after independent design verification.
2. A project-scoped verifier is parseable, read-only by default, non-delegating, and
   required to return evidence-backed findings plus a gate verdict without editing.
3. The accepted design and implementation reviews each have an exact scoped identity,
   the original operator goal, claim-by-claim evidence boundaries, mandatory
   sensitivity/counterexample checks, and no unresolved P0/P1 findings.
4. One initial review plus at most one recheck is enforced per gate. The same verifier
   performs a gate's recheck; a different fresh verifier performs implementation review.
5. Documentation status is reconciled with executable reality, and `QUALIFIED` or
   `COMPLETE` still requires the packet's declared evidence in addition to reviewer
   acceptance.
6. TOML parsing, structural regression, `git diff --check`, and the focused release
   artifact tests pass; the final implementation-review record and residual limits are
   retained before the packet moves to `COMPLETED.md`.

<!-- WP51-DESIGN-PAYLOAD-END -->

### Design verification record

- Initial reviewer: `/root/wp51_plan_review` on 2026-08-11.
- Initial verdict: `BLOCKED_WITH_FINDINGS` (five P1 findings and bounded P2
  refinements); no implementation was started.
- Frozen base: commit `4bec32a827785f5c25cb32a4f2084ced8045f3b3`.
- Pre-review SHA-256: workflow
  `cff1175322fb1c46f58b679c4dafab3db1da6969566060d333a600df0697588c`, active
  ledger `48625d8364656ab00569fe071508cb3273ff0ceb605ec14ef51524f0b4892f7e`,
  completed ledger `efa4c67bfa8b055ba3068295485149f2d96f0e5e77d7e069acfe3341aad81f13`;
  `AGENTS.md` and `.codex/agents/work-packet-verifier.toml` were absent.
- Focused recheck: `DESIGN_VERIFIED`; payload SHA-256
  `bf834569c6765965de7deecbb88383a7b91bb599a59b6ed9fd65e48424546e47` matched,
  all five P1 findings were resolved, and no P0/P1 finding remained.

### Implementation claim and documentation reconciliation

<!-- WP51-IMPLEMENTATION-EVIDENCE-BEGIN -->

| Claim | Real trigger / entry and effect | Retained observation and independent oracle | Sensitivity / counterexample | Boundary / environment / clock | Documentation reconciliation |
|---|---|---|---|---|---|
| Explicit packet actions activate the project protocol while incidental mentions and ordinary small tasks do not. | A future Codex project session loads root `AGENTS.md`; its request classifier applies the exact trigger clause before packet work. | The release-artifact test checks the complete positive verb list and complete exclusions rather than isolated keywords. | The contract test fails if a verb is removed, an exclusion is removed, or the design-only stop is reversed. Fresh-session discovery was not observed in this already-running parent session and remains a declared residual limit. | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE` | The claim is `configured`, not runtime-qualified or proof that every future Codex version loads the file. |
| Packet design receives an independent, bounded gate before implementation. | WP-51 was drafted and hash-frozen before code; fresh verifier `/root/wp51_plan_review` owned severity and verdict. | The retained initial `BLOCKED_WITH_FINDINGS`, revised design hash, and same-reviewer `DESIGN_VERIFIED` recheck are independent of the author checks. | The initial design omitted reviewer authority, exact identity, recursion/unavailability behavior, strong oracles, and lifecycle separation; those defects blocked implementation. The structural test requires the design-only stop and exactly two no-third-pass clauses. | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` | The design record names the reviewer, base/preimages, accepted hash, findings, and bounded recheck. |
| Finished implementation receives a different independent gate and at most one correction/recheck. | Different fresh verifier `/root/wp51_impl_review` received the accepted design and scoped postimages after author checks. | Its initial `BLOCKED_WITH_FINDINGS` verdict identified the weak contract test and missing claim/reconciliation evidence; the final verdict is retained outside this immutable evidence block. | The weak test itself was a meaningful counterexample: deleting trigger verbs, reversing the design-only rule, removing the no-third-pass rule, or replacing requirement bodies could still pass. The corrected test asserts those exact semantics. | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` | Until the retained recheck passes, canonical status remains `IMPLEMENTED` and independent verification remains `IMPLEMENTED_UNVERIFIED`. |
| The custom verifier is read-only, non-delegating, evidence-led, and owns severity/verdict. | Project configuration `.codex/agents/work-packet-verifier.toml` supplies the verifier contract when the parent spawns that named agent. | `tomllib` parsing and exact instruction assertions independently check the schema, read-only sandbox, no-edit/no-spawn rules, reviewer authority, production-path/oracle chain, counterexample, and both verdict vocabularies. The two WP-51 reviewers made no repository edits. | Removing `sandbox_mode = "read-only"`, the no-spawn rule, reviewer authority, the production path, the independent oracle, a counterexample, or an exact verdict makes the focused test fail. | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE` | This proves repository configuration and observed read-only review behavior, not fresh-session auto-discovery under resource exhaustion. |
| Unavailability, recursion, review count, and post-verdict mutation fail closed. | Root instructions govern the author; the verifier instructions exempt its own review and forbid delegation. | Exact structural assertions cover unavailable agent/configuration/slot behavior, verifier exemption, two no-third-pass clauses, and verdict invalidation after substantive edits. | Removing either gate's bound, the fail-closed outcomes, the recursion prohibition, or invalidation clause makes the test fail. Deliberately exhausting all agent slots and editing after a pass were not performed; those remain policy-contract evidence rather than runtime observations. | `COMPONENT / NO_RUNTIME / NOT_APPLICABLE` | No claim of operational qualification is made for unforced resource-exhaustion or future-host behavior. |
| WP-51 documentation states only what the reviewed artifacts demonstrate. | The author compared the WP-51 section, both ledgers, workflow requirements, root instructions, verifier configuration, and release-artifact test. | The exact design hash, scoped implementation manifest, focused checks, reviewer findings/verdict, and residual limits are retained with the packet. | A requirement-ID-only row, filename-only traceability, or unqualified `COMPLETE` wording is insufficient; the structural test requires substantive requirement clauses and this evidence block. | `INTEGRATION / NO_RUNTIME / NOT_APPLICABLE` | WP-51 does not silently upgrade or repair WP-44 through WP-50 runtime claims. Their documented mismatch is retained in the workflow learning table and remains owned by their concurrent audit. |

Documentation reconciliation scope: WP-51 changes root `AGENTS.md`, the project verifier
configuration, `WORKFLOW_AND_REQUIREMENTS.md`, this packet record, and the focused
release-artifact test. `COMPLETED.md` receives only the unchanged packet move after a
passing implementation verdict. WP-51 makes no `FAST_SIM`, realtime, live-Isaac,
hardware, or product-runtime qualification claim. Fresh-session custom-agent discovery,
forced concurrency exhaustion, and post-verdict invalidation were not executed; the
repository contract and mutation-sensitive structural checks are the retained evidence
for those policies.

<!-- WP51-IMPLEMENTATION-EVIDENCE-END -->

### Implementation verification record

- Reviewer: different fresh verifier `/root/wp51_impl_review` on 2026-08-11.
- Initial verdict: `BLOCKED_WITH_FINDINGS`. Two P1 findings identified a
  mutation-insensitive structural test and a missing retained claim/documentation
  reconciliation matrix. P2 limits covered manifest serialization and historical
  evidence links. This record retains the sole allowed fix pass.
- Accepted design SHA-256:
  `bf834569c6765965de7deecbb88383a7b91bb599a59b6ed9fd65e48424546e47`.
- Preimages at implementation start: workflow
  `cff1175322fb1c46f58b679c4dafab3db1da6969566060d333a600df0697588c`;
  release-artifact test
  `3d4120f13406950a49deec8151d969822a026851cd3b8693148012b7378de4ab`;
  root `AGENTS.md` and the verifier TOML absent.
- Exact scope: add `AGENTS.md` and `.codex/agents/work-packet-verifier.toml`; modify
  the existing workspace workflow file and `tests/test_release_artifacts.py`; add the
  delimited WP-51 design, evidence, and mechanical verification records to
  `ACTIVE.md`; delete nothing. `COMPLETED.md` is outside the reviewed payload until an
  unchanged closeout move.
- Reviewed payload postimages: `AGENTS.md`
  `e8205deea12d12178e1be27a24655cac55e8c3f14e55eaa5429f670b51cfda6e`;
  `.codex/agents/work-packet-verifier.toml`
  `4af0e890f900dde08e69fa6ea52870bb97e9730ea40f9e2cca65ad6e13a40906`;
  workflow `f3b6699e3e2e13940bcccb91759e2117e579680c43d14ed0de23001eba5cc1fc`;
  release-artifact test
  `995bf763b2c397e4ed7c4ebd0e958d067344928f57694da802deb4dabfd5656b`;
  delimited implementation-evidence section
  `c3e9a2a7f595973913f20a2a99d9a832cb434d0baba7d44f3306ddc7d2780dbb`.
- Canonical manifest serialization is UTF-8, LF-terminated, one literal
  `<label><space><sha256>` line in this order: `design-payload`, `AGENTS.md`,
  `.codex/agents/work-packet-verifier.toml`,
  `docs/project/WORKFLOW_AND_REQUIREMENTS.md`,
  `tests/test_release_artifacts.py`, `implementation-evidence`. SHA-256 of those six
  lines is `f432e37031dbaafee8e92cccbe9c596d1e1123c94834b19d7a1d854419ad9dea`.
- Post-fix author checks: six focused release-artifact tests passed; focused Ruff and
  scoped `git diff --check` passed.
- Focused recheck: the same reviewer reproduced the accepted design and every postimage
  hash, the delimited evidence hash, and the canonical aggregate manifest; six focused
  pytest checks, Ruff, and scoped `git diff --check` passed. Both P1 findings and the
  manifest-serialization P2 were resolved. Historical raw-chat linkage and
  fresh-session discovery remain declared P2 provenance limits.
- Implementation verdict: `IMPLEMENTATION_VERIFIED`. Only this record, verification
  status, and the unchanged ledger move are mechanical closeout changes outside the
  reviewed payload.


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
