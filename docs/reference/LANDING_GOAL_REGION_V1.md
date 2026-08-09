# Landing goal-region contract v1

| Field | Value |
|---|---|
| Contract | `landing-goal-region-v1` |
| Evidence | `goal-capture-record-v1` |
| Status | `FROZEN` |
| Backend claim | Fast Sim only |
| Physical contact or docking claim | None |

## Purpose

A landing is complete only when the vehicle captures an admitted spatial and motion
region, receives descent authority, and produces terminal evidence inside the region.
Being visually near a pad, beginning a descent, or reaching zero altitude is not
mission success by itself.

Every accepted static execution program declares a world-frame landing goal with:

- immutable goal, role, vehicle, plan, and execution-program identity;
- an absolute landing target and vertically aligned approach point;
- horizontal and vertical capture tolerances;
- maximum capture speed;
- a bounded correction count and correction duration; and
- an explicit abort-and-land or diversion failure action.

The goal is part of the execution program and therefore part of the accepted mission
plan hash.

## Capture and descent

At the approach point the mission reads a fresh source-qualified observation and
records the estimate, available simulator truth, speed, errors, and remaining capture
margins. Descent is authorized only when localization is valid and all position and
speed tolerances pass.

If capture fails, an absolute approach error may be converted into a bounded,
supervisor-admitted correction. The correction remains subject to speed,
acceleration, altitude, and flight-volume policy. A rejected correction records
`DESCENT_NOT_AUTHORIZED` and cannot become ordinary mission descent. Corrections stop
after the declared attempt bound. A declared diversion has its own target; otherwise
mission recovery uses the existing supervised abort-and-land path.

## Terminal evidence

The immutable goal-capture record contains every attempt, whether descent was
authorized, terminal estimate and available truth, final speed, vehicle state,
outcome, and contact classification. Nominal Fast Sim success requires:

- outcome `CAPTURED`;
- terminal truth (or estimate when truth is unavailable) inside the goal region;
- terminal speed at or below the goal limit;
- terminal vehicle state `READY`; and
- `SIMULATED_GROUND_CONTACT`.

That contact value is simulator evidence only. It does not assert pad docking,
charging contact, contact dynamics, or physical landing accuracy.

## Evaluation boundary

The execution evaluator exposes goal identity, attempt count, descent authority,
terminal capture margin, and contact evidence per vehicle. These are derived from the
retained mission result and do not grant authority or waive a hard safety gate.
