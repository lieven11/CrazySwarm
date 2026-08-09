# Active and next work

| Field | Value |
|---|---|
| Document role | The only authoritative ledger for active, next, and blocked work |
| Status | `NO_ACTIVE_SOFTWARE_PACKAGE` |
| Last reconciled | 2026-08-09 |
| Completed counterpart | [`COMPLETED.md`](COMPLETED.md) |
| Default operator backend | `FAST_SIM` |
| Physical flight authorized | No |
| Digital twin enabled | No |
| Active package | None |
| Ordered next milestones | None |
| Operator loop | `SEMI_AUTOMATIC_REALTIME_REVIEW` |
| Catalog policy | `IMMUTABLE_CLUSTERED_CATALOG` |
| Default development case | `SIM / three_drone_multi_conflict` |
| Development execution budget | One active case plus at most one explicitly selected secondary case |

## Current state

WP-01 through WP-34 are closed and recorded in [`COMPLETED.md`](COMPLETED.md). No
software package is currently active and there is no ordered next software milestone.
The implemented Campaign Lab sequence and its qualification evidence are recorded in
[`../qualification/CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md`](../qualification/CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md).

The operator can browse the immutable Simulation/Real catalog by mission cluster and
fleet size, statically validate any case without launching it, and explicitly lock one
simulation case for accelerated or observed-realtime execution. Exact inputs, plans,
schedules, trajectories, artifacts, analysis, reviews, and lifecycle transitions are
retained. Real mirrors remain `NOT_AUTHORIZED`; physical and live-Isaac claims remain
externally deferred.

The primary current contracts and closeout records are:

- [`../reference/MISSION_EXECUTION_EVALUATION_V1.md`](../reference/MISSION_EXECUTION_EVALUATION_V1.md)
- [`../reference/MISSION_CURRICULUM_V1.md`](../reference/MISSION_CURRICULUM_V1.md)
- [`../reference/MULTI_DRONE_CONFLICT_PLANNING_V1.md`](../reference/MULTI_DRONE_CONFLICT_PLANNING_V1.md)
- [`../reference/MISSION_ROBUSTNESS_MATRIX_V1.md`](../reference/MISSION_ROBUSTNESS_MATRIX_V1.md)
- [`../qualification/MISSION_ROBUSTNESS_WP25.md`](../qualification/MISSION_ROBUSTNESS_WP25.md)
- [`../qualification/CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md`](../qualification/CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md)

The original operator CSVs remain diagnostic trigger evidence. A loose child CSV or
visual note is not a complete qualification artifact; the retained execution bundle
and evaluator report remain authoritative.

## Opening future software work

A future software package must be added here before implementation with a bounded
objective, dependencies, exit gate, safety/claim boundary, and explicit test evidence.
Completed scope moves to [`COMPLETED.md`](COMPLETED.md) only after its own gate passes.
No average score or operator note may relax a hard safety, identity, terminal, or
evidence-completeness requirement.

## Externally deferred work

The following work is not authorized by the WP-19-through-WP-34 software sequence:

- NVIDIA/Isaac installation, live gateway execution, RTX host checks, or Isaac
  qualification.
- Crazyflie discovery beyond existing safe software boundaries, radio binding,
  props-off bench work, contained flight, multi-drone physical testing, or purchasing.
- Physical docking/charging, RF, contact, endurance, sensor, or prediction-accuracy
  claims.
- Enabling `DIGITAL_TWIN` or making a physical/high-fidelity backend the default.
- Static or perceived-object avoidance, mapping, SLAM, or camera reasoning.

These paths remain `EXTERNALLY_BLOCKED` until the operator has the required computer
or real aircraft and explicitly authorizes a separate gated work package. The WP-25
handoff bundle grants no execution authority and records live Isaac and physical work
as `NOT_RUN`.
