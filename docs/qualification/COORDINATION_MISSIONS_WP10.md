# Fast Sim coordination missions — ACTIVE-WP-10

| Field | Value |
|---|---|
| Status | `SOFTWARE_QUALIFIED_FAST_SIM` |
| Backend exercised | `FAST_SIM` |
| Live Isaac exercised | No |
| Physical flight authorized | No |
| Mission artifacts | [`../../missions/qualification/crossing_route_separation.py`](../../missions/qualification/crossing_route_separation.py), [`../../missions/qualification/leader_follower_recovery.py`](../../missions/qualification/leader_follower_recovery.py) |
| Production policy path | [`../../src/crazyswarm_app/fleet/coordinator.py`](../../src/crazyswarm_app/fleet/coordinator.py), [`../../src/crazyswarm_app/fleet/coordination.py`](../../src/crazyswarm_app/fleet/coordination.py) |
| End-to-end evidence | [`../../tests/api/test_coordination_missions.py`](../../tests/api/test_coordination_missions.py) |

## Qualified behavior

The crossing-route artifact declares perpendicular west-to-east and south-to-north
routes that intersect without fleet intervention.
`crossing-warning-hold-critical-abort-v2` continuously samples current source-aware
telemetry. At the 0.75 m warning threshold it deterministically orders the routes by
gating one child's next path command, confirms the pause with a real
`SafetySupervisor.stop_and_hold` command under that child's current serialized fleet
binding, and keeps producing fresh held telemetry. After the peer clears the warning
region, the gate releases and both routes finish. The normal Play gate requires zero
critical observations, a minimum observed separation above the 0.40 m critical
threshold, explicit source clock/epoch/sequence evidence, an intervention latency no
greater than 0.25 s, successful child terminal states, and no runtime-resource leak.

A separate unsafe crossing variant deliberately makes both vehicles enter one long
crossing command. Because a warning hold cannot preempt an already active path
command, continued separation monitoring reaches the 0.40 m critical threshold and
cancels both child runs. Their ordinary `MissionRunner` recovery sends fleet-bound
abort-and-land commands, observes landed state, and cleans up both members. This
proves that warning-level temporal route ordering and critical-level abort/landing
are distinct production behaviors rather than test-only policy calls.

The leader/follower artifact declares a 1.10 m global-frame lateral offset. Both roles
use the same bounded low-speed route. Backend-neutral fleet software derives the
current follower setpoint from the leader position and declared offset, then records
position error, relative-speed error, separation, boundary margin, and both source
identities. The nominal Play gate requires:

- maximum position error no greater than 0.25 m;
- maximum relative-speed error no greater than 0.25 m/s;
- minimum separation greater than the 0.80 m warning threshold;
- zero critical-separation observations and nonnegative boundary margin; and
- every command to retain its assigned vehicle, task, run, and lease generation.

`leader-loss-land-follower-v1` cancels the follower mission and requests bounded
abort-and-land recovery as soon as the leader becomes stale, disconnected, loses
localization, loses command delivery, or reaches a boundary/terminal fault. The
reciprocal `follower-loss-land-leader-v1` lands the leader when the follower is lost.
The policy event must precede the peer task's terminal event, and the recorded software
intervention latency must remain within 0.25 s. No reassignment is attempted from stale
peer state.

## Failure and replay matrix

Normal Play tests cover:

1. crossing-route warning hold, supervisor confirmation, clear-region release, and
   successful completion;
2. the same normalized crossing outcome under Fast Sim seeds 109 and 811;
3. unsafe crossing escalation to fleet-bound abort/landing of both routes;
4. nominal leader/follower tracking and isolated command routing;
5. explicit cancellation, bounded cleanup, and restart of the same uploaded mission;
6. leader localization loss;
7. leader disconnect;
8. leader stale/delayed telemetry;
9. leader command drop;
10. leader geofence/terminal fault; and
11. follower disconnect.

The tests upload the real restricted mission files and start them through
`POST /api/v1/mission-files/{mission_id}/start`. They do not call coordinator policy
methods as a substitute for execution.

Fleet results retain command and task routing, source observations, intervention and
release events, minimum separation, policy/recovery decisions, child and fleet
terminal states, normalized replay identity, and cleanup evidence. The fault tests
also require the affected peer to terminate before the fleet result and require both
the mission-task and fleet-task registries to be empty.

## Qualification commands

```bash
.venv/bin/pytest -q tests/api/test_coordination_missions.py \
  tests/fleet/test_coordination.py tests/missions/test_package_v2.py
.venv/bin/ruff check src tests scripts missions
.venv/bin/mypy --strict src tests
```

Repository-wide, UI, canonical-scenario, and release gates are recorded in
[`../work-packages/COMPLETED.md`](../work-packages/COMPLETED.md).

The reconciled focused gate passes all 15 API, policy, and package checks. The final
repository gate passes 476 tests with one intentional live-Isaac host skip; Ruff and
strict MyPy over 164 source/test files also pass. Live Isaac remains `NOT_RUN`.

## Claim boundary

This package qualifies supporting coordination software in deterministic Fast Sim.
It does not qualify dense formation, flocking, wake interaction, manipulation,
physical localization, close real flight, live Isaac, or a digital twin.
