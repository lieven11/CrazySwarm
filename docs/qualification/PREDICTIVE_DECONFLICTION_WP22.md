# Predictive two-drone deconfliction WP-22 qualification

| Field | Value |
|---|---|
| Package | `WP-22` |
| Status | `COMPLETE` |
| Date | 2026-08-09 |
| Contract | [`../reference/PREDICTIVE_DECONFLICTION_V1.md`](../reference/PREDICTIVE_DECONFLICTION_V1.md) |
| Backend claim | Fast Sim |

## Canonical result

The original simultaneous crossing predicts a closest approach below 0.01 m and a
bounded conflict window. Candidate enumeration selects `STAGING_HOLD`: `cross_west`
adds 19.45 s to its already declared staging hold while `cross_south` crosses in one
continuous trajectory. The resolved plan predicts approximately 1.20 m minimum
separation against the 0.80 m warning-plus-uncertainty requirement.

Normal Play in accelerated and real-time Fast Sim passes with:

- the exact accepted plan and both selected execution-program identities;
- zero warning samples, zero critical samples, and measured minimum separation above
  the 0.75 m configured warning threshold;
- no reactive stop/hold command in the nominal run;
- one continuous trajectory for each crossing route;
- captured landing goals and successful child/fleet terminal results; and
- no ordinary timeout.

The evaluator retains complete evidence, the selected strategy and plan hash,
predicted and observed separation, and confirms nominal strategy identity execution.

## Alternatives and fallbacks

Under the canonical border and dynamics constraints, continuous retiming, horizontal
detour, and bounded retiming/vertical combination candidates are feasible. Direct
vertical separation is rejected because a full 0.80 m layer above the 0.30 m route
exceeds the 1.0 m altitude/flight-volume ceiling. A no-hover planner test excludes
staging and compares feasible retiming and horizontal detour without relaxing a hard
constraint.

An explicitly reactive crossing case still drives a critical encounter and proves
warning detection, critical pair abort, supervised landing, source identity, and
bounded intervention independently of nominal planning.

## Regression evidence

- The complete coordination file passes 12 tests, including two-seed deterministic
  replay, accelerated and real-time predictive crossing, reactive critical fallback,
  cancellation/restart, and the leader/follower loss matrix.
- Planning, mission planning, trajectory, and release-artifact coverage passes 31
  tests.
- Repository Ruff and strict MyPy pass over 185 source/test files.

## Claim boundary

WP-22 is limited to two-drone configured-route deconfliction. It does not claim
three-or-more-drone scheduling, object avoidance, global optimality, robustness under
fault matrices, live Isaac, digital twin, or physical flight.
