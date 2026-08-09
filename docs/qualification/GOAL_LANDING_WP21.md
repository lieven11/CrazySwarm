# Goal-region arrival and landing WP-21 qualification

| Field | Value |
|---|---|
| Package | `WP-21` |
| Status | `COMPLETE` |
| Date | 2026-08-09 |
| Contract | [`../reference/LANDING_GOAL_REGION_V1.md`](../reference/LANDING_GOAL_REGION_V1.md) |
| Backend claim | Fast Sim |

## Exit evidence

The canonical 2.4 m single-drone route runs under both accelerated and real-time Fast
Sim clocks. Both executions capture the absolute approach region before descent and
finish with:

- one retained goal-capture record;
- `CAPTURED` outcome and explicit descent authority;
- terminal truth inside 0.10 m horizontal and 0.08 m vertical tolerances;
- final speed no greater than 0.08 m/s;
- terminal `READY`; and
- simulator-only ground-contact evidence.

The normal uploaded two-role, non-conflicting mission uses one accepted execution
program per active role. Both children independently satisfy the same terminal gate,
and the grouped deterministic evaluator retains a non-negative capture margin and
complete evidence for each vehicle.

## Recovery evidence

A displaced goal outside initial tolerance triggers one supervised absolute
correction, a second measured capture attempt, and only then descent. A deliberately
unsafe displaced goal is rejected by the unchanged geofence: its mission result is
failed, planned descent is withheld, and the retained record states
`DESCENT_NOT_AUTHORIZED`. This verifies both bounded retry and fail-closed behavior.

## Regression evidence

- Five focused trajectory/goal tests pass, including accelerated, real-time,
  correction, unsafe rejection, and unsupported-capability boundaries.
- The non-conflicting uploaded two-role API/evaluator qualification passes.
- Repository Ruff and strict MyPy pass over 183 source/test files.
- The full repository gate reaches 506 passes and one intentional live-Isaac skip;
  its only pre-closeout failure was the expected frozen ledger assertion, updated as
  part of this packet transition.

## Claim boundary

WP-21 does not claim predictive crossing deconfliction, multi-case curriculum,
three-or-more-drone planning, robustness qualification, live Isaac, physical flight,
physical contact, or docking. Those remain WP-22 through WP-25 or explicitly external
work.
