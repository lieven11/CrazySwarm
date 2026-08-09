# Progressive mission curriculum contract v1

| Field | Value |
|---|---|
| Contract | `progressive-mission-curriculum-v1` |
| Template version | `1.0.0` |
| Status | `FROZEN` |
| Default backend | Fast Sim |

## Structure

The curriculum uses five versioned templates rather than one source file per test:

1. single-drone endpoint and landing capture;
2. single-drone continuous route;
3. two non-conflicting parallel routes;
4. perpendicular crossing with admitted staging; and
5. no-hover crossing restricted to continuous retiming or horizontal detour.

Each template expands over compact, nominal, and wide configured borders and seeds
109 and 811. The default manifest therefore contains 30 immutable cases. Adding seed,
border, objective, or model variants is a deterministic Cartesian expansion and does
not require editing mission source by hand.

Every case binds template/version, source and source hash, seed, clock modes, flight
volume, altitude, warning/critical separation, goal regions, permitted strategies,
hard constraints, objective ordering, thresholds, and one canonical case hash.

## Promotion

Persisted `mission-execution-evaluation-v1` reports are mapped to case hashes. A
baseline retains evaluator identity/version, report hash, execution identity,
separation counts/margin, goal margin, generated stop count, selected strategy, hard
gate findings, and its own canonical hash.

Promotion is strictly level ordered. Every case in a level must have complete evidence
and pass its hard gates, and every lower level must remain clean. A missing or failed
level-2 case blocks levels 2 through 5; a better average or soft score cannot override
that result.

Use `scripts/qualify_mission_curriculum.py` to emit the deterministic manifest. Pass
`--evaluation-map` with a JSON map from case hash to retained evaluation JSON path to
produce a promotion receipt.

## Scope

Configured borders and mission goals are in scope. Perceived objects, SLAM, learned
policies, physical calibration, live Isaac, and automatic deployment of a changed
baseline are not.
