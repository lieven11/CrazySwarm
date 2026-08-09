# Multi-drone conflict-planning contract v1

| Field | Value |
|---|---|
| Contract | `multi-drone-conflict-plan-v1` |
| Status | `FROZEN` |
| Nominal backend | Fast Sim |
| Object avoidance | Out of scope |
| Physical or live-Isaac claim | None |

## Joint conflict model

Three or more `multi-conflict-route` roles are evaluated on one global source-time
schedule. Every predicted pair below the configured warning separation plus the
0.05 m position-uncertainty allowance becomes an edge in one joint conflict graph.
Resolution is applied to the complete graph; independently selected pair resolutions
never become execution authority.

The plan records every conflicting pair, closest approach, required separation,
candidate precedence order, hold per role, predicted fleet minimum separation,
wait/fairness measures, role starvation, resulting program hashes, and the selected
candidate and plan identities.

## Bounded scheduling

For up to four roles, the reference planner enumerates every precedence permutation.
It hard-rejects a candidate when sampled separation is inadequate, an accepted program
would exceed the mission-duration limit, or a role would exceed the starvation bound.
The starvation bound is the lesser of 90 seconds and half the admitted maximum mission
duration.

Feasible candidates are ordered deterministically by:

1. priority-inversion penalty;
2. maximum role wait;
3. total wait;
4. wait spread; and
5. lexical precedence order.

For larger inputs, the contract exposes `PRIORITY_GREEDY_STAGING`: a deterministic
priority-first full-route scheduler with quadratic conflict checking. It has no global
optimality guarantee. Even the small-case exact result is exact only over the bounded
full-route staging candidates, not arbitrary continuous multi-agent trajectories.

## Deadlock and authority

If no candidate satisfies separation, duration, and starvation constraints, the plan
is `BLOCKED`, marks deadlock, declares `LAND_ALL` as its recovery policy, and contains
no selected program hashes. Mission admission then fails before provisioning, so the
safe action for a pre-launch deadlock is no launch. Runtime child-failure and separation
enforcement remain independent safety authority after launch.

A resolved plan replaces the role programs in the mission receipt. Normal Play is
authorized only for the exact selected program hashes. Fleet results and evaluator
reports retain the plan hash, strategy, predicted/observed minimum separation, and
whether every selected program completed successfully.

## Declared case family

The versioned case generator freezes five identities: central multi-conflict, merge,
temporal bottleneck, unequal priority, and constrained border. All use configured
routes and borders only. They do not introduce sensed objects, mapping, SLAM, or a
general optimal multi-agent motion-planning claim.
