# Planning, fleet-policy, recovery, and Safety Kernel architecture

| Field | Value |
|---|---|
| Architecture style | Modular monolith with versioned interfaces and explicit registries |
| Current implementation | WP-11 receipt plus WP-12 through WP-17 modular planning release |
| Qualification | [`../qualification/MISSION_PLANNING_WP12_17.md`](../qualification/MISSION_PLANNING_WP12_17.md) |
| Safety rule | Plugins may propose; the non-replaceable Safety Kernel authorizes |
| Backend rule | No planner/policy/recovery plugin imports or commands a vehicle adapter |

## Why this boundary exists

The Control Center should remain one coherent application and UI without becoming one
large decision-making class. Mission intent, route generation, fleet behavior,
recovery, safety authorization, execution, and vehicle consequences have different
inputs and test obligations.

The implemented flow is:

```text
MissionIntent
    |
    v
RoutePlanner --------> immutable route/timing/corridor proposal
    |
    v
FleetPolicy ---------> allocation and coordinated behavior proposal
    |
    v
RecoveryStrategy ----> bounded response proposal when conditions change
    |
    v
MissionPlan + SafetyCase receipt
    |
    v
non-replaceable Safety Kernel
    |
    v
MissionRunner / FleetCoordinator
    |
    v
backend-neutral Vehicle adapter
```

Planner, fleet policy, and recovery are replaceable registered components. Safety is a
permanent outer authority, not another optional strategy.

## Implemented boundaries

| Area | Implementation | Durable boundary |
|---|---|---|
| Mission source | Restricted Python plus package-v2 roles/tasks compile to `MissionIntent` | Existing source meaning remains explicit and supported |
| Deployment | `fleet/planning.py` derives logical fleet and assignments | Remains a core service consumed by plan compilation |
| Operational receipt | `missions/planning.py` compiles exact role previews, routes, intent graph, plugins, safety case, and findings | One common immutable receipt |
| Route planning | Registered direct, zone/obstacle, coverage, and temporal `RoutePlanner` implementations | One proposal-only input/output contract |
| Fleet decisions | Four registered policy proposals feed coordinator orchestration | Coordinator and supervisor retain lifecycle/command authority |
| Recovery | Eight registered strategies return standardized proposals | Final authority remains in Safety Kernel/Supervisor |
| Safety | Tighten-only declaration, safety case, strategic kernel, and runtime supervisor | Non-bypassable and non-pluggable |
| UI | Common Control Center reviews and approves exact receipts | Never hosts algorithms |

WP-11 is an operational compiler and admission gate, not yet a general autonomous
goal-to-route planner. That distinction must remain visible in UI and documentation.

## Common plugin manifest

Every registered planner, fleet policy, or recovery strategy declares a frozen
manifest containing at least:

- `plugin_id` and plugin kind;
- semantic implementation version;
- supported input and output schema versions;
- declared capabilities and required observations;
- deterministic/bounded execution properties;
- implementation artifact hash;
- compatible Control Center contract range; and
- qualification status/evidence identity.

Registries are explicit allow lists created by application code/configuration. The
project will not load an arbitrary file, package, network response, or UI-supplied
class as a flight strategy.

Changing a selected manifest, implementation hash, or contract version invalidates a
previous plan and operator approval.

## RoutePlanner

### Input

- mission objective, phase, role, start, goal/zone, and completion criteria;
- configured world volume, obstacles, allowed corridors, and reservations;
- vehicle capabilities and declared motion/resource limits;
- global safety limits and stricter mission constraints;
- current source-qualified observations and their freshness; and
- deterministic planning budget/seed where an algorithm requires one.

### Output

- ordered waypoints and coordinate frames;
- planned timestamps/durations and spatial corridor/time reservations;
- route length, expected energy, dynamics maxima, and expected separation;
- required observations and assumptions;
- success criteria and bounded replan triggers;
- findings/limitations; and
- a canonical route-plan hash.

A route planner never connects, arms, sends a command, mutates a lease, or decides
that an unsafe proposal may execute.

Registered capabilities are:

- direct waypoint;
- zone and zone coverage;
- configured-obstacle-aware indoor route;
- temporal multi-role conflict/separation;
- dock approach; and
- leader/follower route intent.

Implementation is incremental. A manifest may only advertise a capability backed by
the common contract tests.

## FleetPolicy

A fleet policy receives the accepted mission/deployment/route plan plus current
source-qualified fleet state. It proposes coordinated decisions such as allocation,
launch order, hold order, role behavior, handover, and task completion.

The extraction target is:

- `PersistentCoveragePolicy` for active/reserve rotation;
- `CrossingRoutePolicy` for deterministic precedence/intervention;
- `LeaderFollowerPolicy` for offset/tracking and leader-loss transition; and
- `IndependentTasksPolicy` for unrelated tasks with common safety/separation.

`FleetCoordinator` remains the lifecycle owner. It invokes policies, validates their
current identity/task/lease context, sends accepted proposals through the Safety
Kernel, records evidence, and owns cancellation/cleanup.

## RecoveryStrategy

A recovery request contains:

- typed failure/trigger and timestamp;
- current vehicle/fleet state and source/freshness;
- current role, task, phase, plan, owner, and lease generation;
- battery, link, localization, separation, obstacle/boundary, reserve, and dock state;
- available actions and deadlines; and
- the effective safety declaration.

A strategy returns a reasoned proposal such as:

- `HOLD`;
- `REPLAN`;
- `RETURN_HOME`;
- `HANDOVER`;
- `LAND`;
- `ABORT_AND_LAND`; or
- `EMERGENCY_STOP`.

The proposal includes target members/tasks, preconditions, maximum duration, fallback,
required evidence, and strategy identity/hash. Initial strategies cover low battery,
leader loss, link loss, localization loss, reserve loss, dock unavailable, and command
or acknowledgement loss.

A recovery strategy cannot grant authority, invent a healthy observation, reuse a
stale lease, or directly invoke an adapter.

## Non-replaceable Safety Kernel

The kernel surrounds every normal and recovery proposal. It owns the final decision
for:

- vehicle/run/task/lease identity and current authority;
- vehicle lifecycle and arming state;
- global policy and any stricter mission limits;
- observation presence, source, freshness, and quality;
- geofence, altitude, dynamics, battery, and watchdogs;
- critical fleet separation and conflict response;
- command timeout and acknowledgement validity;
- abort, controlled landing, emergency stop, and fail-closed behavior; and
- safety audit evidence.

A plugin may request stricter limits, a conservative hold/land, or a new plan. It may
not expand the flight volume, raise speed/acceleration/altitude, lower health or battery
minimums, suppress a watchdog, weaken separation, disable emergency authority, or send
commands around the kernel.

The current `SafetySupervisor` remains the production enforcement foundation. WP-14
formalizes the kernel boundary without replacing working guards with an unqualified
abstraction.

## Mission intent and execution

WP-15 added a higher-level intent contract for objectives, roles, phases, completion,
constraints, and allowed contingencies. Compilation selects qualified registered
capabilities and produces an immutable execution graph plus the WP-11 receipt.

Execution follows only that accepted graph. Replanning produces a new graph/hash and
invalidates stale plan authority. Replay reconstructs decisions from receipts and
events; it does not rerun arbitrary source to guess what happened.

Restricted Python remains supported for explicit-action missions while this path is
introduced. Existing mission semantics are not silently converted into a different
goal or planner.

## UI and API boundary

The common Control Center may:

- request planning/replanning;
- show selected component identities and plan/safety hashes;
- render objectives, roles, routes, corridors, timing, energy, findings, and limits;
- request approval of exact hashes;
- start, hold where supported, cancel, abort, or emergency-stop; and
- show execution/recovery/evidence state.

It may not implement a route algorithm, choose a recovery in browser state, alter a
receipt after approval, allocate a vehicle locally, or call a vehicle adapter.

## Common contract-test obligations

Every registered component must prove:

1. schema/version/manifest compatibility and deterministic canonical output;
2. bounded time, memory, cancellation, and cleanup;
3. explicit behavior for missing, stale, invalid, and conflicting inputs;
4. no direct adapter or command-authority access;
5. output validation against global and mission safety limits;
6. stable evidence identity and replay serialization;
7. stale plugin/plan/lease rejection; and
8. nominal, rejected, degraded, and recovery outcomes through the normal API/Play path.

Component unit tests alone do not qualify a plugin. WP-17 runs the shared suite and
end-to-end Fast Sim scenarios on one reviewed tree.

## Scope boundary

This architecture is software-only. It does not require or authorize NVIDIA/Isaac,
radio/hardware access, propellers, bench work, purchasing, contained flight, physical
multi-drone separation, or a digital-twin claim. Those remain separately gated and
externally deferred.
