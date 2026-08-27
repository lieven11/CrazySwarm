# Constraint-directed multi-drone planning decision

> Navigation: [requirements index](../requirements/README.md)

Historical design decision supporting planning, geometry, and replanning requirements.

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
