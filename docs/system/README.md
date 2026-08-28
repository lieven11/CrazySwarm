# System responsibilities and codebase map

This document defines what belongs in a mission, what the CrazySwarm Control Center
decides, what a simulator or vehicle adapter does, and where those responsibilities
live in the repository.

The implemented modular interfaces for route planners, fleet policies, recovery strategies,
registries, and the non-replaceable Safety Kernel are defined in
[`PLANNING_AND_RECOVERY_PLUGINS.md`](PLANNING_AND_RECOVERY_PLUGINS.md).

## Fast orientation

Use this map to choose a subsystem before searching source. Do not enumerate the whole
repository or retained run-evidence trees unless the task actually crosses those
boundaries.

| Task | Start with | Then inspect |
|---|---|---|
| Mission parsing or execution | `missions/script.py`, `missions/runner.py` | mission contract, mission tests |
| Planning or submissions | `campaign/service.py`, `campaign/planner.py`, `planning/` | case/submission data, planning requirements |
| Runtime replanning | `campaign/replanning.py`, `campaign/runtime_executor.py` | safety supervisor, retained analysis/evidence |
| Fleet coordination | `fleet/coordinator.py`, `fleet/tasks.py` | preparation, policy, fleet tests |
| Vehicle safety/authority | `safety/supervisor.py`, `safety/obstacle_avoidance.py`, `missions/authority.py` | domain commands, safety policy/adapter tests |
| Fast Sim physics/tuning | `simulation/vehicle.py`, `simulation/physics.py`, `simulation/parameters.py` | world config, physics contract/tests |
| Telemetry/evidence | `observability/recorder.py`, `observability/storage.py`, `observability/csv_export.py` | telemetry/evaluation contracts and tests |
| API/operator workflow | `api/app.py`, `api/runtime.py` | API models, UI API client, focused API tests |
| Dashboard rendering | `ui/app/components/`, `ui/app/lib/` | `design.md`, UI requirements and tests |
| Digital-twin/calibration | `twin/`, `hardware/observation_twin.py`, `hardware/basic_flight_lab.py`, `hardware/controller_tuning_lab.py`, `hardware/acrobatics_lab.py`, `qualification/physical.py` | fidelity/transfer requirements and qualification records |
| Shared physical-runtime ownership | `hardware/ownership.py`, `vehicles/_cflib_link.py`, `dashboard*.py` | hardware-runtime guide, `AGENTS.md` |

Paths in this table are relative to `src/crazyswarm_app/` unless they begin with
`ui/`. The task-specific durable requirements are routed from
[`../project/requirements/README.md`](../project/requirements/README.md).

## Change-impact map

| Boundary | Production owners | Contracts/configuration | Primary tests |
|---|---|---|---|
| Missions and command authority | `missions/`, `domain/commands.py` | `MISSION_PACKAGE_V2.md`, `MISSION_PLAN_V1.md` | `tests/missions/`, mission/API tests |
| Campaign planning and analysis | `campaign/`, `planning/` | campaign YAML/JSON, planning and trajectory references | `tests/campaign/` |
| Fleet lifecycle | `fleet/` | fleet bindings and world configurations | `tests/fleet/` |
| Safety | `safety/` | safety policy and mission safety guide | `tests/safety/` |
| Simulation | `simulation/`, `vehicles/` | simulator contract, world/scenario config | simulation/vehicle tests and canonical scenarios |
| Evidence and replay | `observability/` | telemetry CSV and execution-evaluation contracts | `tests/observability/` |
| API and local serving | `api/`, `dashboard*.py` | OpenAPI and application config | `tests/api/`, dashboard tests |
| Operator UI | `ui/app/`, `ui/worker/` | `design.md`, generated OpenAPI client | `ui/tests/` |
| Twin and physical transfer | `twin/`, `qualification/`, `hardware/` | physical plans and fidelity claims | `tests/twin/`, qualification scripts |
| Hardware process ownership | `hardware/ownership.py`, `dashboard.py`, `dashboard_service.py` | `HARDWARE_RUNTIME_OWNERSHIP.md` | `tests/hardware/test_hardware_ownership.py`, dashboard tests |

Update this map when an entry point, responsibility owner, public transit boundary,
contract location, or primary test boundary changes. Ordinary internal edits do not
require map churn. `python scripts/check_project_map.py` validates mapped entry points
and test boundaries; semantic ownership still requires review when architecture moves.

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
| Physical per-ray obstacle guarding | Obstacle-avoidance evaluator and Crazyflie command adapter | Hover/translation decisions use current measured ranges and velocity and remain server-side through dispatch and recovery. |
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
  and vehicle configs. For campaign dynamic-world runs it also owns the source-time
  truth timeline used by physics and range sensing; the planner receives only delayed
  perception observations from that timeline.
- `src/crazyswarm_app/simulation/vehicle.py` applies authorized commands and advances
  one simulated vehicle, including continuous swept physical-envelope collision
  termination against static and source-time dynamic obstacles.
- `src/crazyswarm_app/simulation/physics.py` implements dynamics and configured model
  parameters.
- `src/crazyswarm_app/simulation/powertrain.py`, `sensors.py`, and `faults.py` implement
  energy/actuators, modeled observations, and deterministic injected faults.
- `src/crazyswarm_app/simulation/factory.py` constructs session vehicles from world and
  deployment inputs.
- `src/crazyswarm_app/vehicles/providers.py` binds a run-private dynamic-world timeline
  into newly provisioned or reused Fast Sim vehicles; `campaign/runtime_executor.py`
  retains the exact materialized timeline in the execution bundle.

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

`src/crazyswarm_app/dashboard.py` owns the local API/UI child-process lifecycle. Each
child runs in its own process group so dashboard stop or restart terminates helper and
worker descendants before another API can acquire the port or Crazyradio. The `serve`
entry point rejects an occupied API port before constructing the runtime or starting
hardware supervision. The macOS LaunchAgent grants the dashboard enough exit time to
run physical-output and radio cleanup before forced termination.
`src/crazyswarm_app/hardware/ownership.py` also owns the cross-process physical-operation
admission gate. Physical API mutations hold its shared side until their durable state is
visible; operator deployment holds its exclusive side, rechecks motor and flight state,
and keeps new physical starts blocked through build and service replacement.

## Digital twin boundary

`src/crazyswarm_app/hardware/observation_twin.py` owns the service-private physical
observer and predicted Fast Sim observer. The authenticated
`/api/v1/physical-twin/*` routes in `api/app.py` are its only public lifecycle
boundary. These observer IDs are deliberately absent from `ApplicationRuntime.vehicles`,
the safety supervisor, parameters, mission providers, fleet providers, and selected
vehicle state, so existing command routes reject them as unknown.

The Control Center can now persist one explicitly confirmed exact radio URI, connect
without scanning, capture its first-seen identity automatically, and inspect an
observation-only paired session. A later identity mismatch fails closed rather than
replacing the saved binding. This is
not a qualified flight-capable digital twin: test transports are labeled `TEST`, real
hardware evidence remains not run, and HOME-frame pose is not relabelled WORLD. The
general physical mission/campaign launcher remains locked. Confirmed observer IDs derive
from the observed identity rather than the URI. A latest-only compact SSE boundary at
`/api/v1/physical-twin/live` exposes measured presentation frames at 30 Hz with bounded
per-client backpressure; it never enters command or safety authority. The presentation
and evidence schedules are independent, and radio log groups stay at the measured 10 Hz
transport budget. Instruments interpolate between those truthful samples at display
refresh rate. Evidence pairing remains independently bounded to 10 Hz, and each accepted
retained batch stores all 29 common channels per role, explicit missing/incompatible
values, one-based raw-clock epochs, and operator-visible measured/predicted freshness.
`transport.radio` retains the physical transport contract, including a rolling loss
window that counts no-ACK exchanges, separate cflib retry quality, packet rates,
congestion, queue occupancy, USB errors, and the connection epoch. The same current
diagnostics cross `PhysicalTwinSourceStatus` into the existing `Link` disclosure.
`vehicles/_cflib_link.py` appends redacted transition events to
`.cache/crazyswarm/radio-transport-events.jsonl`; no full radio URI is persisted there.
Queue saturation during a no-ACK interval is recorded without invoking cflib's fatal
link callback. The telemetry watchdog still owns bounded stale reconnect, while command
dispatch checks current ACK age, loss streak, and queue capacity and never retries an
uncertain command.
The latest-only presentation contract also carries literal M1–M4 measured PWM
percentages when the Crazyflie reports all four outputs; missing physical thrust and
current remain unavailable rather than being synthesized for the UI.
`ui/app/lib/twin-shadow.ts` owns the browser-only observed-drone projection. The Control
Center admits frames to it only while a physical-flight start is in progress or backend
physical-flight state requires a stop; idle
observer motion never creates a scene drone or trace. The first admitted HOME-frame
position is the scene origin, later mission samples apply metric displacement and measured
attitude, and a source-clock reset starts a new centered trace. It does not change backend
frame compatibility or retained evidence.
The service owns persistent observation intent and bounded reconnect supervision. A
confirmed enabled binding reconnects on service startup and after transient stream
failure. Physical actions selected in Campaign Laboratory and started or stopped from
the shared bottom mission control suspend observer sampling and borrow a command view
of the observer's already-connected link. `ObservationTwinService` remains the
transport owner across observer → contained flight → observer; the borrowed
`CrazyflieVehicle` clears its permit at the operation boundary but does not close that
transport. Resume snapshots the same link and starts a fresh retained twin session
without another radio handshake. Only a stale pre-command link may receive one bounded
reconnect, before any permit or command dispatch. Repeated suspension from Abort joins
the current operation instead of disconnecting beneath it.
Explicit observer pause releases the link for the current service process without
rewriting durable intent; service restart resumes reconnect supervision. Identity
changes always return to operator confirmation. Switching the presentation to
Simulation does not disconnect the observer.

`src/crazyswarm_app/hardware/basic_flight_lab.py` owns the separate Digital Twin
Campaign Laboratory catalog and private Fast Sim rehearsal executor exposed through
`GET /api/v1/physical-twin/lab/catalog` and `POST /api/v1/physical-twin/lab/runs`.
Its Basic flight hierarchy covers ground readiness, first liftoff, hover, translation,
heading, shapes, abort, and emergency behavior. Rehearsals never register their private
simulator in the application runtime and never use the observer transport. Battery,
motor, drift, altitude, and landing values are retained as simulator-learning
candidates with `qualification_claim=NONE`; the 30% props-off motor step is modeled
only in the private simulator. The physical catalog and Digital Twin operator UI do
not expose Motor bench as a mission. The retained
`/api/v1/physical-twin/lab/motor-actuation` status boundary and idempotent
`/api/v1/physical-twin/lab/motor-actuation/stop` mutation exist only to recover stale
or uncertain direct-PWM actuation left by an earlier process or version. Failed
zero/disable writes retain `POSSIBLY_ACTIVE`/`STOP_FAILED` truth and the global dock
`Stop motors` action; the UI never offers a control that raises direct-PWM output.
Campaign Laboratory owns Digital Twin physical mission selection and preparation,
and the shared bottom mission control owns execution.
Contained flight uses the backend-owned
`/api/v1/physical-twin/lab/physical-flight` status boundary plus `/start` and `/abort`
mutations. Start schedules the operation and returns immediately; global status keeps
`Abort and land` in the bottom dock across browser refresh. Abort sends controlled
landing and disarm before cancelling the remaining plan, but its HTTP mutation returns
immediately with `ABORTING` so proxy lifetime is not flight authority. Interrupted
evidence is never reported as a completed flight. The service atomically retains the
operation, exact URI, command phase, acknowledgements, and nested failure detail before
and during command work. A replacement process restores any nonterminal marker as
`STOP_UNCONFIRMED`, blocks `/start`, and lets `/abort` reconnect the exact retained URI
to inspect fresh supervisor state and issue only the required landing/disarm sequence.
If command acknowledgement is lost, the stop remains unconfirmed until that recovery
or the read-only observer supplies current supervisor truth with both armed and flying
false. Once `ABORTED` or `COMPLETED` is confirmed, a later unrelated observer outage
does not recreate a stop requirement. A Play connection failure before the command link
opens and before any command is dispatched is terminal without inventing flight authority;
Abort during that phase cancels the pending start rather than opening a competing recovery
connection. Play/start requires a paired, current observer that explicitly reports a known
arm state and `flying=false`; missing supervisor state is unknown and blocks start.
When a manually armed grounded drone reports `armed=true`, the same `/start` operation
reconnects the exact trusted URI, sends and confirms a recorded preflight Disarm, then
continues through estimator reset, arm, and takeoff. The adapter separately reads the
firmware's automatic-arming bit. A Crazyflie 2.1 in its default automatic-arming mode
is safely grounded when current supervisor telemetry reports `flying=false`; Play does
not issue a futile Disarm that firmware would immediately reverse, and landing/abort
does not require `armed=false` in that mode. The UI remains one Play action; arming
normalization is not a separate operator workflow. These backend and UI boundaries
are covered by `tests/hardware/test_basic_flight_lab.py` and
`ui/tests/twin-basic-flight-lab.test.tsx`.
`src/crazyswarm_app/safety/obstacle_avoidance.py` owns the pure per-ray physical
translation evaluator. `CrazyflieVehicle` supplies raw, per-variable timestamped range,
HOME-velocity, yaw, and estimator-variance inputs before dispatch and throughout each
relative move. `MONITOR_ONLY` records the same decision evidence without changing the
command. Operator-selected `ENFORCED` mode can preserve displacement and yaw while
retiming a move, reject it before dispatch, or route a newly unsafe dispatched move
through the existing abort-and-land recovery boundary. The `/start` request and global
status carry mode and evidence; the Campaign Laboratory dock only exposes the switch
for contained hover/translations, never observer, arm/disarm, or acrobatics workflows.
`src/crazyswarm_app/hardware/controller_tuning_lab.py` owns the second Digital Twin
physical mission cluster, its versioned box-fixture contract, advisory characterization state,
central-ray range model, continuity-constrained range-derived pose fit, and bounded
A–E command plans. `config/fixtures/controller-tuning-box-v1.json` retains the
corner-origin survey frame, preliminary base dimensions, A–D scan-derived floor marks,
the distance-trilaterated E mark, the four 12 mm horizontal ranger offsets, and the
clockwise-from-`+Y` placement heading. Wall height, flight stations, wall labels, and
ranger uncertainty remain unset and are reported without disabling implemented B–E
commands. The fixture schema has no baseline-acceptance, enabled-amplitude, yaw-enable,
or speed/position-enable unlock fields. A floor-start
observation can retain raw ranger data without a completed survey and sends no physical
command. Motion-local target geometry may still be required when the command directly
depends on it. F–H are catalog-only raw stages with no executor path. The shared operation,
radio suspension, stop/recovery, telemetry archive, and bottom mission-control boundary
remain in `basic_flight_lab.py`; the new cluster does not create a second hardware owner.
`src/crazyswarm_app/hardware/acrobatics_lab.py` owns the third `Cushioned acrobatics`
cluster's immutable single-roll command profile. `BodyRateThrustCommand` is the public
transit contract: it carries a finite fixed-period stream of body roll/pitch/yaw rates
and collective thrust plus the captured HOME XY reference and ±0.50 m axis bound, never
raw per-motor PWM. `basic_flight_lab.py` owns the staged operation states: Play takes off
to 0.50 m, `HOVERING_READY` exposes one `FLIP` API action, `FLIPPING` consumes it once,
then recovery and landing run without browser ownership. `CrazyflieVehicle` admits the
rate command only under a contained-flight permit, polls measured position during the
stream, and asks the link to interrupt the stream on a bound violation.
`CflibCrazyflieLink` sends every sample through cflib's manual commander with rate mode
explicit, then sends the commander-priority release meta packet so the existing
high-level hover can regain control without a motor cut. The Crazyflie firmware rate PID
and X mixer own the measured-gyro-to-four-motor conversion, preserving the low-level
stabilization boundary. Profile, staged-operation, and transport oracles live in
`tests/hardware/test_acrobatics_lab.py` and `tests/hardware/test_crazyflie_adapter.py`.
Ground readiness may arm the paired drone for three seconds while recording telemetry
and then disarm. The commissioning path may reset and confirm the estimator, then arm,
take off to 0.30 m, hover for 30 seconds, land, and disarm. Additional operator-gated
physical missions reuse that exact entry, retained-operation, and abort boundary for a
12-second hover; 0.10 m cardinal and 0.20 m forward returns; small stopped L, square,
and triangle paths; a straight out-and-back path; and 0.10/0.20 m offset landings. All
flight plans reset and confirm the estimator, remain at 0.30 m and within 0.20 m of the
takeoff point, limit horizontal commands to 0.10 m/s, and exclude yaw and altitude
maneuvers. The selected mission ID and command-plan hash are retained with the run.
Admission uses the exact paired identity and a
real radio connection; reported supervisor faults are recorded but are not a software
admission gate. `supervisor.info` is consumed from the bounded firmware log stream;
the command refresh loop does not add synchronous supervisor requests. Battery data and
monitor-only range decisions remain learning observations; range data becomes a
pass/fail input only for an operator-selected enforced contained translation. A reported
supervisor crash is sent the firmware recovery
request on the next physical flight action. The physical command adapter retains every telemetry sample consumed by
preflight and command-completion polling, then archives it through the normal
`run-telemetry-v1` CSV and `run-files` manifest path for later analysis. All other
physical motions remain disabled.

A future `DIGITAL_TWIN` run requires:

1. one immutable mission and identity model shared by real and simulated execution;
2. a qualified real Crazyflie adapter and measured telemetry;
3. a synchronized simulated counterpart;
4. an independent reference for trajectory/state comparison;
5. calibrated parameters with held-out validation and declared uncertainty;
6. explicit operator authorization and safe degraded behavior when either side fails.

Until those gates pass, the app may control Fast Sim and run the observation-only twin
entry, but it must label simulated values as modeled and keep physical mission, motor,
hotkey, and flight authority disabled.

## How to add a capability

1. Put portable goals, roles, and success criteria in a mission package.
2. Put reusable fleet decisions in `fleet/`, per-vehicle safety in `safety/`, and
   physical consequences in a backend.
3. Add source-aware observations and immutable identity before relying on a new signal.
4. Test the component, then the normal Play/API path, then injected failure/restart/
   cleanup behavior.
5. Record evidence and limitations; move the package from active to completed only
   when its whole exit gate passes.
