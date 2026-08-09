# Multi-drone conflict planning WP-24 qualification

| Field | Value |
|---|---|
| Package | `WP-24` |
| Status | `COMPLETE` |
| Date | 2026-08-09 |
| Contract | [`../reference/MULTI_DRONE_CONFLICT_PLANNING_V1.md`](../reference/MULTI_DRONE_CONFLICT_PLANNING_V1.md) |
| Backend claim | Fast Sim |

## Canonical result

The canonical three-drone case produces three simultaneous pair conflicts. The exact
reference evaluates all six precedence orders and selects `route_alpha`, `route_beta`,
then `route_gamma`, respecting priorities 200, 150, and 100 with zero inversion. Added
holds are 0.00, 19.45, and 38.90 seconds. The worst wait stays below the 90-second
starvation bound, and predicted minimum separation is approximately 0.849 m against
the 0.800 m warning-plus-uncertainty requirement.

Normal Play in accelerated and real-time Fast Sim passes with:

- the exact accepted plan and three selected execution-program identities;
- zero warning and critical samples and observed separation above 0.75 m;
- no reactive stop/hold command during nominal execution;
- successful goal-region capture and terminal completion for every role;
- no deadlock, starvation, or ordinary timeout; and
- a complete evaluator bundle carrying the same plan/strategy identity.

## Variants and safe failure

Merge, temporal-bottleneck, unequal-priority, and constrained-border variants each run
through normal Play and the persisted evaluator. All four complete with zero warning
or critical samples, no starvation, successful goals, and complete evidence. Together
with the canonical case, all five immutable variants also parse, compile, remain inside
their declared flight volumes, and select a deterministic joint schedule.

A 60-second duration policy makes every third-role schedule violate duration and the
derived 30-second starvation bound. That case is rejected before launch with a
deadlock marker, empty selected authority, and declared `LAND_ALL` recovery. A forced
enumeration limit also proves the named deterministic priority-greedy path and its
explicit lack of global optimality.

## Regression evidence

- Four multi-drone planner tests cover deterministic exact selection, all five
  variants, starvation/deadlock rejection, and the bounded larger-input heuristic.
- The canonical accelerated execution passes in 36.00 seconds; its real-time
  equivalence gate passes in 83.82 seconds.
- The four non-canonical execution/evaluator variants pass in 123.94 seconds.
- Planning, mission-planning, trajectory, evaluator, package, and release coverage
  passes 43 tests.
- Repository Ruff passes; strict MyPy passes over 190 source/test files.

## Claim boundary

WP-24 proves configured-route scheduling in Fast Sim. Full permutation enumeration is
bounded to small fleets; the larger-input heuristic is not globally optimal. This
package does not claim object avoidance, arbitrary continuous planning, robustness
under the WP-25 fault matrix, live Isaac, digital twin, or physical flight.
