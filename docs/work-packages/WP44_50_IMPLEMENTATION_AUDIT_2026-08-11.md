# WP-44 through WP-50 implementation audit — 2026-08-11

## Scope and conclusion

This audit traced the authored packet exit gates through the production submission,
planning, campaign runtime, supervisor, evidence, analyzer, qualification, API, and UI
paths. It also exercised the head-on object-in-line case through Fast Sim.

The former blanket status `IMPLEMENTED_FAST_SIM_QUALIFIED` was not supported. WP-44
and WP-47 have substantial implemented cores; WP-45, WP-46, and WP-48 remain bounded
subsets; WP-49 does not yet contain its required successor matrix; and WP-50 cannot be
qualified before those rows, repeats, realtime anchors, and dynamic replay surfaces
exist. `ACTIVE.md` now records those boundaries.

| Packet | Audited disposition | What is executable now | Principal open gate |
|---|---|---|---|
| WP-44 | Implemented, not fully qualified | Case-bound planning/profile packages, component hashes, resolved package hash, child template inheritance, exact runtime authority-chain validation | Full downstream round-trip/mutation and historical-compatibility qualification |
| WP-45 | Partial | Level-flight cylindrical vehicle proxy; continuous piecewise-linear vehicle-pair and route/AABB clearance certificate | Composite body/propeller swept pose geometry, contact kinematics/response, and one shared runtime/replay/evaluator geometry path |
| WP-46 | Partial | Named AABB solids/passages, contradiction checks, scalar protected capacity, flight-volume and adherence checks | Connectivity/topology, primitive lifetime/provenance, role/segment-specific passages, and complete preview/runtime/replay layers |
| WP-47 | Implemented core, open gates | Bounded dispositions, continuous release bisection, admitted joint generators, lexicographic static selection, independent certificate, budget-bounded first-certified in-flight mode | Complete property/repeat evidence, topology-derived generators, and runtime reproduction of retained alternatives |
| WP-48 | Partial Fast-Sim runtime integration | Two/three-role `AUTO_WITHIN_FROZEN_LIMITS` obstacle/passage events can preempt an executing route, hold, observe, plan/certify a changed world, commit one software epoch, and dispatch replacements | Peer trajectory/uncertainty/goal-update runtime paths, observed-realtime anchors, prevalidated contingency proof, and backend-level distributed prepare/commit |
| WP-49 | Partial regression subset | Nine planning, six analytic geometry, and four dynamic transaction rows pass; the object-in-line row is backed by a real changed-world proposal | Concrete bridge/tunnel/open-side/open-ceiling, fidelity, capacity, peer-runtime, negative-runtime, repeat, and realtime successor rows |
| WP-50 | Partial operator/evidence surface | Static package/planning, exact CSV, landing, snapshot, review, replacement authority, and dynamic evidence-completeness paths | Dynamic generation/invalidation/cutover replay UI and complete WP-49 accelerated/realtime qualification |

## Findings that changed the implementation

### Submission and child authority

- `ResolvedPlanningPackage` accepted a caller-supplied package hash without
  recomputing it and did not fully cross-check every case/profile/world/backend
  component. It now validates its own hash and all component identities.
- Constraint-directed submissions were keyed to three exact canonical case IDs.
  Object-bearing or other causal child cases therefore silently lost their flexible
  planning authority. They are now keyed to the immutable template and rebound to the
  child case hash.
- `CampaignExecutionRequest` previously did not carry the resolved package. It now
  proves that case, lock, profile, planning submission, plan, schedule, trajectory set,
  certificate, backend configuration, and resolved package form one authority chain.
- Child creation now rejects safety/authority widening, including flight-volume,
  backend/mode/authorization, strategy, replanning authority, separation, uncertainty,
  reserve, dynamics, freshness, planning-budget, deadline, and watchdog weakening.

### Flexible object-conditioned planning

- The original generic generators could miss a solid on a later route segment and
  independently clear routes could still cross each other in a head-on encounter.
- The planner now has deterministic all-invalidated-segment lateral/vertical doglegs,
  joint solid-directed candidates, and fleet-separated solid lanes. The object-in-line
  head-on fixture selects a certified `fleet-solid-lanes-v1` horizontal detour.
- Static canonical planning retains complete bounded selection. Causal object-bearing
  children and explicit in-flight calls can use lazy first-certified search. The latter
  is limited by the smaller of the search and frozen reaction planning budgets and
  records an explicit no-optimality claim.

### Actual in-flight execution

Before this audit, WP-48 had a coordinator transaction model whose caller supplied
world/route hashes, feasibility booleans, and acknowledgements. No campaign runtime
used it, so an accepted dynamic row did not prove that a changed world was planned or
that a replacement command flew.

The Fast-Sim campaign runtime now inserts a shared execution head between an accepted
trajectory operation and the supervisor. For each admitted object/passage event it:

1. waits on source time while the old route is executing;
2. preempts every active trajectory into a supervisor stop-and-hold;
3. captures a fresh observation for every role;
4. applies the event to a new immutable world/case;
5. rebinds the original planning submission and plans/certifies actual replacement
   trajectories inside the frozen budget;
6. validates every replacement command before granting a fleet epoch;
7. commits one all-role software authority decision and advances to one source-time
   cutover; and
8. dispatches all replacement trajectories, retaining proposal, decision, world,
   plan, trajectory, authority, reaction-horizon, prepare, and dispatch evidence.

A planning, observation, validation, reaction-horizon, or dispatch failure leaves the
fleet in the bounded hold and returns control to the existing landing/recovery path.

This is software-level atomic authority in Fast Sim. Local prevalidation is the prepare
acknowledgement; it is not a claim that independent hardware backends implement a
distributed transaction.

### Evidence and qualification truth

- The evaluator previously compared every trajectory command only with the original
  accepted plan, so a valid replacement could be reported as an identity failure. It
  now accepts only an exact replacement plan/trajectory/authority tuple from an
  accepted execution-head record.
- Static scenario reduction could satisfy `EVENT_HANDLED` before provisioning. For
  accepted object/passage changes, both evaluator completeness and the analyzer oracle
  now require runtime proposal/decision/world hashes, exact fleet role coverage,
  preparation, and replacement dispatch.
- The retained WP-49 dynamic rows formerly used fabricated hashes and
  `feasible=True`. The accepted object-in-line row now carries a deterministic real
  proposal, changed-world hash, and per-role feasibility certificates. Peer and
  negative rows are explicitly labeled `COORDINATOR_TRANSACTION_ONLY`.
- The retained 19-row report is a regression subset, not the complete matrix specified
  by WP-49. Its current report SHA-256 is
  `4f386eb18e5906cab5ad9ae74a1a823a54d300b581283386d0230723ead41d94`.

## Current claim boundary

- Environment: configured Fast Sim only. No live Isaac, hardware, perception, mapping,
  physical collision, or damage claim.
- Fleet: exactly two or three active roles for the changed-world execution head.
- Authority: `AUTO_WITHIN_FROZEN_LIMITS`; no authority widening is permitted.
- Runtime event kinds: obstacle add/move/remove and passage close/open. Passage code is
  implemented, but the retained end-to-end runtime anchor currently covers
  object-in-line obstacle addition.
- Peer updates: sequencing/reaction/atomic coordinator behavior is tested, but a peer
  trajectory hash is not sufficient planning geometry and is deliberately not accepted
  as a real changed-world proposal.
- Geometry: conservative level-flight cylinder/AABB and piecewise-linear route checks;
  not full swept, pose-aware composite aircraft geometry.
- Qualification: focused planner, proposal, runtime, and evaluator evidence exists;
  the full WP-49/WP-50 matrix and observed-realtime anchors remain open.

## Primary executable evidence

- `tests/campaign/test_submissions.py`: package self-hash/cross-case enforcement and
  object-bearing child submission inheritance.
- `tests/campaign/test_dynamic_replanning.py`: real object-in-line proposal,
  certificate, route authority, atomic decision, and negative transaction behavior.
- `tests/campaign/test_campaign_execution.py`: executing head-on route changed by an
  in-flight object, replacement dispatch for both roles, exact replacement authority,
  and evaluator `COMPLETE` status.
- `tests/campaign/test_constraint_directed_planner.py`: retained canonical
  bottleneck/head-on/merge behavior and independent certification.
- `tests/campaign/test_constraint_qualification.py`: deterministic retained subset and
  explicit dynamic qualification scope.

This audit is the controlling boundary for WP-44 through WP-50 until a later retained
qualification closes an explicitly listed gate.
