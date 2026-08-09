# Predictive two-drone deconfliction contract v1

| Field | Value |
|---|---|
| Contract | `fleet-deconfliction-plan-v1` |
| Status | `FROZEN` |
| Nominal backend | Fast Sim |
| Physical or live-Isaac claim | None |

## Prediction

Two accepted time-parameterized trajectories are sampled on one global source-time
schedule. The planner records predicted closest approach, the interval in which
separation is below the warning threshold plus declared position uncertainty, and one
narrow trajectory-tube reservation per role for that interval. The conflict record
does not reserve one route-wide axis-aligned box when the sampled conflict window is
narrower.

The canonical uncertainty margin is 0.05 m. It is added to the configured warning
separation before candidate admission; it is not subtracted from a hard limit.

## Candidate enumeration

The bounded deterministic planner evaluates, in declared order:

1. temporal precedence with a hold at the route's admitted staging point;
2. continuous speed retiming;
3. a smooth horizontal detour;
4. vertical separation; and
5. a bounded retiming/vertical combination.

Each candidate records feasibility, precedence/held role, added duration/path,
strategy parameters, predicted minimum separation, resulting program identity, and a
reason. Flight volume, altitude, duration, sampled speed, and sampled acceleration are
hard filters. In particular, vertical separation is rejected when the warning plus
uncertainty layer does not fit the configured ceiling.

The deterministic tie break is feasible candidate, declared strategy order, bounded
cost, then role identity. Hard constraints are never exchanged for a lower soft cost.

## Selected authority

For the canonical perpendicular crossing, equal task priorities resolve lexically:
`cross_south` receives precedence and `cross_west` holds at its initial airborne
staging point. The hold is inserted into the accepted execution program, all later
operation timestamps shift, and the updated program hashes are included in the
mission plan. Both roles execute those exact programs through the normal Play path.

Fleet results and execution evaluations retain the deconfliction plan hash, selected
strategy, predicted separation, and whether the selected program identities actually
executed. A planner resolution is therefore distinguishable from a reactive runtime
intervention.

## Independent runtime safety

Source-aware warning hold and critical pair abort remain in the Fleet Coordinator and
Safety Supervisor. They do not disappear when a nominal strategy is admitted. An
explicitly reactive crossing task qualifies the critical fallback independently; it
does not masquerade as the nominal predictive path.
