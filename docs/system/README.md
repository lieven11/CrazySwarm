# System responsibilities and codebase map

This document defines what belongs in a mission, what the CrazySwarm Control Center
decides, what a simulator or vehicle adapter does, and where those responsibilities
live in the repository.

The implemented modular interfaces for route planners, fleet policies, recovery strategies,
registries, and the non-replaceable Safety Kernel are defined in
[`PLANNING_AND_RECOVERY_PLUGINS.md`](PLANNING_AND_RECOVERY_PLUGINS.md).

## Core rule

The mission describes **intent and mission-specific behavior**. The Control Center
turns that intent into a safe, identity-bound, observable fleet execution. A backend
produces vehicle dynamics and observations and applies authorized commands; it does not
invent the mission or fleet policy. The UI displays state and requests operator intent;
it does not run coordination or safety algorithms.

```text
immutable mission package
        |
        v
parse and derive logical deployment
        |
        v
compile plan + safety findings + immutable receipt
        |
        v
provision or verify backend bindings
        |
        v
connect -> observe -> preflight
        |
        v
single MissionRunner or multi-vehicle FleetCoordinator
        |
        v
SafetySupervisor -> backend-neutral Vehicle -> Fast Sim / Isaac / Crazyflie
        |
        +-> telemetry, evidence, replay, operator view
```

## Decision ownership

| Concern | Owner | Why |
|---|---|---|
| Mission objective and completion | Mission package | It is part of the portable experiment definition. |
| Logical roles and required capabilities | Mission declaration | They must remain identical across backends. |
| Desired role-specific moves/actions | Restricted mission function | These express the behavior being tested. |
| Starting battery and physical/model state | World/backend configuration | They describe the execution environment, not mission intent. |
| Fault injection schedule | Scenario/test configuration | Faults must not be hidden inside the portable mission artifact. |
| Concrete vehicle, radio URI, Isaac prim, namespace | Backend binding/provider | Hardware and simulator identity are deployment concerns. |
| Mission-plan compilation and admission | Mission planner | It binds portable intent, logical deployment, current planning inputs, and policy into one reviewable receipt. |
| Role-to-vehicle allocation | Fleet planner/coordinator | Allocation uses current capability, energy, location, and availability. |
| Inter-vehicle separation and handover | Fleet coordinator | One authoritative policy must observe all members and avoid conflicting decisions. |
| Geofence, health, command authority, watchdog, recovery | Safety supervisor and mission runner | Safety cannot depend on optional mission code or browser health. |
| Physics, sensors, energy evolution, collisions | Simulation backend | These are modeled consequences of commands and the configured world. |
| Low-level attitude/motor stabilization | Flight controller or simulation model | It is time-critical vehicle behavior below mission planning. |
| Evidence, provenance, replay | Observability layer | Decisions and inputs must be reconstructable independently of the UI. |
| Start/cancel/emergency operator intent | UI/API | The UI requests actions; server-side policy validates and performs them. |

## What belongs in a Python mission

A mission package has two parts.

### Declarative part

Mission package v2 may declare:

- one to three logical roles and stable logical vehicle IDs;
- role names, optional home positions, and active/reserve intent;
- zones and task type/priority;
- required capabilities and estimated energy plus margin;
- warning/critical separation thresholds;
- observation freshness and child-failure policy.

These are portable requirements. They do not say which physical or virtual vehicle
will satisfy them.

### Behavioral part

The restricted `async def mission(drone)` function may call the allowed mission API,
such as takeoff, hover, relative motion, observation, and landing. `drone.role` lets
one immutable source express role-specific behavior.

The mission may define mission success, bounded decisions based on allowed observations,
and what useful work a role should attempt. It must not bypass centralized safety,
construct an adapter, open a radio/network/file, or run arbitrary imported code.

### What must not be in a mission

- `FastSimVehicle`, Isaac, ROS, Crazyflie, or radio implementation details;
- a serial number, URI, backend namespace, simulator prim, or physical address;
- mass, thrust, battery model, sensor noise, seed, world geometry implementation, or
  fault schedule;
- fleet-wide lease transfer, reserve selection, dock allocation, or global safety
  authority;
- browser presentation logic.

The frozen syntax is in
[`../reference/MISSION_PACKAGE_V2.md`](../reference/MISSION_PACKAGE_V2.md).

## Collision and separation responsibility

“Do not collide” is not a single responsibility.

1. The mission declares desired routes and conservative separation constraints.
2. The world supplies walls, obstacles, boundaries, and model parameters.
3. The backend calculates motion and reports positions/ranges/collision state.
4. The safety layer rejects unsafe command/state conditions within its known envelope.
5. The fleet coordinator compares current, source-aware peer observations and owns
   inter-vehicle intervention.
6. Evidence records the route, observations, threshold crossings, interventions, and
   terminal outcome.

The mission planner rejects known obstacle intersections and unsafe starts before
provisioning. Registered WP-13 planners produce routes and temporal reservations; WP-10
crossing-route policy and Fast Sim runtime evidence remain the dynamic intervention
boundary. A mission file alone never owns fleet-wide collision policy.

## Battery and reserve responsibility

- The mission declares how much energy a task expects and whether a reserve role exists.
- The world/backend defines starting battery and models its evolution.
- Telemetry reports current source-tagged battery/health state.
- Preparation blocks an initially unsafe assignment unless an explicit simulation-only
  test override is authorized.
- The fleet coordinator detects service risk, selects a reserve, stages it, confirms
  separation/takeover, transfers generation-numbered authority, returns the outgoing
  member, and schedules the abstract dock.
- The simulator models the resulting flight and battery state; it does not decide which
  drone owns the task.

## Control Center layers

### Mission parsing and catalog

Files:

- `src/crazyswarm_app/missions/script.py` validates restricted source and package-v2
  declarations.
- `src/crazyswarm_app/missions/catalog.py` stores immutable uploaded mission artifacts.
- `src/crazyswarm_app/missions/registry.py` registers executable missions.
- `src/crazyswarm_app/missions/_mission_worker.py` runs the restricted source in a
  bounded worker process.

### Planning and deployment

Files:

- `src/crazyswarm_app/missions/planning.py` compiles role branches, route/timing and
  safety findings into a deterministic backend-neutral mission-plan receipt.
- `src/crazyswarm_app/fleet/planning.py` derives the backend-neutral deployment and
  assignments from mission intent.
- `src/crazyswarm_app/fleet/artifacts.py` defines mission, deployment, binding, dock,
  fleet-session, and identity contracts.
- `src/crazyswarm_app/fleet/zones.py` decomposes zone tasks.
- `src/crazyswarm_app/planning/contracts.py` freezes planner, policy, recovery, route,
  safety, and selection contracts.
- `src/crazyswarm_app/planning/registry.py` owns exact allow-listed resolution.
- `src/crazyswarm_app/planning/builtins.py` implements registered route, fleet-policy,
  and recovery proposal components.
- `src/crazyswarm_app/planning/intent.py` validates intent and compiles the execution
  graph.
- `src/crazyswarm_app/planning/safety.py` implements the non-replaceable strategic
  Safety Kernel admission boundary.
- `src/crazyswarm_app/planning/approval.py` binds operator approval to exact hashes.
- `src/crazyswarm_app/fleet/tasks.py` owns task state, leases, generations, and atomic
  owner transfer.
- `src/crazyswarm_app/vehicles/providers.py` provisions virtual members or verifies
  approved backend bindings.

The deployment planner answers “what logical fleet and work are required?” The
mission planner answers “what is expected to happen with the current planning inputs,
which known risks were found, and may preparation begin?” Neither flies a vehicle or
simulates physics. The frozen receipt is documented in
[`../reference/MISSION_PLAN_V1.md`](../reference/MISSION_PLAN_V1.md).

### Preparation and execution

Files:

- `src/crazyswarm_app/fleet/preparation.py` performs declared/discovered/bound/verified,
  connection, observation, preflight, and readiness transitions.
- `src/crazyswarm_app/fleet/execution.py` owns the full one-click execution lifecycle.
- `src/crazyswarm_app/missions/runner.py` runs one child mission with command authority,
  watchdog, recovery, and cleanup.
- `src/crazyswarm_app/missions/base.py` provides the mission command/observation context.
- `src/crazyswarm_app/missions/authority.py` serializes the current fleet command binding.
- `src/crazyswarm_app/fleet/coordinator.py` coordinates multi-member launch, observation,
  separation, persistent handover, terminal policy, and child results.
- `src/crazyswarm_app/fleet/persistent.py` owns reserve selection and persistent-coverage
  state transitions.
- `src/crazyswarm_app/fleet/docks.py` owns abstract capacity, queue, confirmation, and
  modeled charging state.
- `src/crazyswarm_app/fleet/metrics.py` derives fleet performance and recovery metrics.

### Safety

Files:

- `src/crazyswarm_app/safety/supervisor.py` owns connection/preflight/control authority,
  command dispatch, online health, abort, emergency handling, and recovery.
- `src/crazyswarm_app/safety/policy.py` contains safety thresholds and validation rules.
- `src/crazyswarm_app/safety/state_machine.py` defines allowed vehicle lifecycle changes.
- `src/crazyswarm_app/safety/audit.py` records safety-relevant decisions.

Mission code cannot disable these rules. Browser failure also cannot disable them.
The author/reviewer/operator procedure is in
[`../guides/MISSION_SAFETY_GUIDE.md`](../guides/MISSION_SAFETY_GUIDE.md).

### Backend-neutral domain and adapters

Files:

- `src/crazyswarm_app/domain/commands.py` defines command envelopes, run identity, and
  fleet task binding.
- `src/crazyswarm_app/domain/telemetry.py` defines source-aware observations.
- `src/crazyswarm_app/domain/simulation.py` defines simulator contracts, provenance,
  run identity, and authority transitions.
- `src/crazyswarm_app/vehicles/base.py` is the backend-neutral vehicle interface.
- `src/crazyswarm_app/vehicles/crazyflie.py` and related link files are the real-adapter
  boundary; physical execution remains gated.
- `src/crazyswarm_app/vehicles/isaac.py` and `mock_isaac.py` implement gateway-backed
  adapter boundaries.

### Fast Simulator

Files:

- `src/crazyswarm_app/simulation/world.py` loads the room, obstacles, scenarios, clock,
  and vehicle configs.
- `src/crazyswarm_app/simulation/vehicle.py` applies authorized commands and advances
  one simulated vehicle.
- `src/crazyswarm_app/simulation/physics.py` implements dynamics and configured model
  parameters.
- `src/crazyswarm_app/simulation/powertrain.py`, `sensors.py`, and `faults.py` implement
  energy/actuators, modeled observations, and deterministic injected faults.
- `src/crazyswarm_app/simulation/factory.py` constructs session vehicles from world and
  deployment inputs.

The simulator answers “what happens when this authorized command acts on this modeled
vehicle in this modeled world?” It does not allocate roles or choose recovery policy.

### API, runtime, dashboard, and evidence

Files/directories:

- `src/crazyswarm_app/api/runtime.py` owns live application objects, runs, and tasks.
- `src/crazyswarm_app/api/app.py` exposes authenticated operator and simulation APIs.
- `src/crazyswarm_app/api/models.py` defines request/response contracts.
- `src/crazyswarm_app/observability/` records events, telemetry, storage, queries, and
  command-free replay.
- `ui/` renders the room, fleet/member state, controls, telemetry, and evidence.

The UI may upload/select a mission, review and approve an exact plan, choose an allowed
execution backend/mode, request start/cancel/abort/emergency actions, and change the displayed member. It must not
rewrite mission parameters, allocate drones, execute a control loop, or decide safety.

## Digital twin boundary

Fast Sim is currently a simulator and the application is already a control-center
architecture. That does not yet make it a qualified digital twin.

A future `DIGITAL_TWIN` run requires:

1. one immutable mission and identity model shared by real and simulated execution;
2. a qualified real Crazyflie adapter and measured telemetry;
3. a synchronized simulated counterpart;
4. an independent reference for trajectory/state comparison;
5. calibrated parameters with held-out validation and declared uncertainty;
6. explicit operator authorization and safe degraded behavior when either side fails.

Until those gates pass, the app may control Fast Sim and prepare real/Isaac boundaries,
but it must label simulated values as modeled and keep `DIGITAL_TWIN` disabled.

## How to add a capability

1. Put portable goals, roles, and success criteria in a mission package.
2. Put reusable fleet decisions in `fleet/`, per-vehicle safety in `safety/`, and
   physical consequences in a backend.
3. Add source-aware observations and immutable identity before relying on a new signal.
4. Test the component, then the normal Play/API path, then injected failure/restart/
   cleanup behavior.
5. Record evidence and limitations; move the package from active to completed only
   when its whole exit gate passes.
