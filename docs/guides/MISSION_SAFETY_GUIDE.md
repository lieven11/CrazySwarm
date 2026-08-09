# Mission safety guide

| Field | Value |
|---|---|
| Applies now | Uploaded missions executed in Fast Sim through the Control Center |
| Planner contract | [`../reference/MISSION_PLAN_V1.md`](../reference/MISSION_PLAN_V1.md) |
| Global policy | `src/crazyswarm_app/safety/policy.py` |
| Runtime enforcement | `src/crazyswarm_app/safety/supervisor.py` and fleet coordination |
| Physical-flight authorization | None |

## Safety model

Safety is a chain of independent gates, not a label attached to a mission file:

```text
immutable mission intent
        |
        v
deterministic plan + findings
        |
        v
operator review of the exact receipt
        |
        v
provisioning + observation + runtime preflight
        |
        v
supervised commands + watchdogs + fleet intervention
        |
        v
terminal cleanup + evidence + replay
```

Passing one gate never disables the next. A plan approved from configured inputs can
still fail runtime preflight or be aborted when a live observation becomes unsafe.

## Responsibility boundaries

| Owner | Safety responsibility |
|---|---|
| Mission author | Desired objective, conservative route intent, bounded commands, role needs, completion, and declared assumptions |
| Mission planner | Compile intent, snapshot inputs, expose limitations, and reject known unsafe or incomplete plans |
| Global safety policy | Maximum authority envelope that a mission may tighten but never relax |
| Vehicle supervisor | State, leases, observation/preflight validity, command bounds, timeouts, health, abort, and emergency handling |
| Fleet coordinator | Current peer freshness, separation, ownership, intervention, recovery, and coordinated terminal behavior |
| Simulator/world | Motion and observations from configured geometry/model; never assignment or safety-policy decisions |
| Control Center UI | Display, request review/approval, cancel, abort, and emergency stop; never silently plan or command |
| Operator | Confirm identities and assumptions, review exact hashes/findings, keep emergency authority, and stop when the environment differs |

For the fuller codebase map, see [`../system/README.md`](../system/README.md).

## Mission-author checklist

Before uploading a mission:

- Keep the source backend-neutral. Do not include simulator names, radio addresses,
  adapter classes, physics values, hardware serials, or fault schedules.
- Use explicit, bounded durations for every movement, wait, and observation.
- Keep role homes, declared zones, target altitudes, and route segments inside the
  intended operating volume with margin; touching a configured limit is not margin.
- Declare every required role, capability, observation, energy estimate, reserve,
  separation threshold, and failure policy that changes mission meaning.
- Use a global/home frame for repeatable shared routes unless body-relative motion is
  intentionally required and its starting yaw assumption is understood.
- Provide explicit completion and failure behavior. Never rely on an endless loop,
  an unbounded wait, or missing telemetry becoming zero/healthy.
- Treat a reserve as prepared and disarmed until the fleet coordinator grants current
  task authority.
- Choose controlled land for recoverable safety termination, abort for immediate
  supervised mission termination, and emergency stop only for the distinct emergency
  condition defined by the system.

Objectives, phases, completion, and contingencies are first-class intent/graph
contracts. Restricted Python missions compile as explicit-action compatibility intent;
the restricted worker and runtime guards remain authoritative bounds on Python control
flow.

## Reviewer checklist before approval

Review the complete receipt, not just the 3D path:

1. Confirm mission name, source SHA-256, deployment SHA-256, role-to-vehicle mapping,
   starts, homes, and reserve states.
2. Confirm the safety-policy hash and limits match the intended room/scenario.
3. Inspect every role's command sequence, waypoint times, distance, altitude, battery
   requirement, and preview fidelity.
4. Resolve every `BLOCKER`; blockers are not operator-overridable.
5. Read every confirmation finding and its measured/configured source. Confirmation
   acknowledges a permitted simulation risk; it does not make unsafe physical flight
   acceptable.
6. Treat any observation-dependent branch as runtime-dependent even when its preview
   fidelity is `EXACT_ROLE`; exact means exact for the planning worker's inputs.
7. Confirm configured obstacles represent the intended simulated environment and note
   that unconfigured obstacles cannot be checked.
8. Re-preview after any source, deployment, scenario, policy, start, battery, obstacle,
   or relevant observation change. Approval applies only to the exact hashes shown.

## Trigger and response baseline

The table describes the current safety ownership, now frozen in a versioned mission
safety declaration and safety-case receipt.

| Trigger | Required response | Owner | Evidence |
|---|---|---|---|
| Planned target outside volume/altitude | Block before provisioning | Planner | Blocker with role, step, target, and limit |
| Planned dynamics above policy | Block before provisioning | Planner | Blocker with planned value and policy limit |
| Planned segment intersects known obstacle | Block before provisioning | Planner | Blocker with role, step, and obstacle ID |
| Critical starting separation | Block before provisioning | Planner | Pair, distance, and threshold |
| Battery below planned need or takeoff minimum | Require permitted explicit confirmation or reject | Planner/API; runtime rechecks | Observation, requirement, decision, and receipt hash |
| Missing planning-time telemetry | Record it as unavailable and require preparation observation/preflight; a mission may later require a planning-time block | Planner/preparation | Missing field, proposed value source, and preflight outcome |
| Missing/stale runtime telemetry | Hold/reject/abort according to state; never invent data | Preparation/supervisor/fleet | Source, age, required field, action, terminal status |
| Command timeout or acknowledgement loss | Stop issuing dependent commands; recover or abort safely | Supervisor/fleet | Command identity, timeout, recovery, and outcome |
| Warning peer separation | Apply deterministic fleet intervention | Fleet coordinator | Pair, distance, freshness, command, and latency |
| Critical peer separation | Do not continue the conflicting route; abort/land per policy | Fleet coordinator | Pair, minimum distance, intervention, and outcome |
| Critical battery during execution | Terminate useful work and perform bounded safe recovery | Supervisor/fleet | Battery source, threshold crossing, commands, terminal state |
| Operator cancel | Bounded controlled cancellation and cleanup | Execution owner | Request identity, child outcomes, leases, cleanup |
| Operator abort | Immediate supervised mission abort and landing where available | Supervisor/execution owner | Reason, commands, state transitions, cleanup |
| Emergency condition | Invoke distinct emergency authority; never report ordinary success | Supervisor/operator | Reason, authority, state, and terminal evidence |

## Start and execution rules

- Preview is read-only and never provisions or connects vehicles.
- Approval binds the exact plan, safety case, selected plugins, finding
  acknowledgements, and operator client. Start recompiles from current inputs and
  rejects any stale, missing, expired, consumed, or mismatched approval.
- `BLOCKED` is always rejected before provisioning.
- `REQUIRES_CONFIRMATION` is rejected unless that confirmation is explicitly allowed
  for the current simulation mode and supplied by the operator.
- Accepted planning does not arm. Provisioning, identity verification, connection,
  observation, preflight, arming, execution, and cleanup remain separate states.
- Every command still passes through current identity, task-lease, state, safety, and
  health authority.
- Adapter, simulator process, observation, or renderer failure can never become
  mission success.

## Simulation and claim limits

This guide currently supports software rehearsal and evidence in Fast Sim. It does
not authorize a propeller, real radio binding, bench action, or flight. In particular:

- a collision-free simulated route does not prove that the real room is clear;
- configured model limits do not prove measured aircraft performance;
- simulated battery does not prove endurance or safe return reserve;
- configured sensor quality does not prove localization or obstacle detection;
- a plan receipt is not an airworthiness certificate or a physical safety case; and
- no result enables `DIGITAL_TWIN`.

NVIDIA/Isaac and physical-drone paths stay deferred in
[`../work-packages/ACTIVE.md`](../work-packages/ACTIVE.md) until the operator has the
required computer or aircraft and explicitly authorizes their separate gates.
