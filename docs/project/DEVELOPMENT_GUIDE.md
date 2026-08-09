# CrazySwarm Development Guide

> Long-range product and hardware roadmap. Current implementation status lives in
> [`../work-packages/COMPLETED.md`](../work-packages/COMPLETED.md) and
> [`../work-packages/ACTIVE.md`](../work-packages/ACTIVE.md).

## Purpose

This guide turns the initial Crazyflie notes into a gated development plan for a persistent multi-drone autonomy demonstrator. The central rule is simple:

> Buy and build only what is needed to pass the next milestone.

The project should progress from one dependable indoor drone to a three-drone fleet that can divide work, replace a low-battery drone, dock, recharge, and return to service. Formation flying is not the goal; reliable mission continuity is.

Before any aircraft is purchased, the project must first produce a complete
simulation-first control setup. Missions, operator controls, communications,
telemetry, evidence, fault handling, the current deterministic simulator, and a
high-fidelity NVIDIA Isaac Sim backend are software milestones in their own right.
Hardware purchase and real flight begin only after the pre-hardware gates in this
guide and the simulator work packets have been passed.

Work-package planning has exactly two current entry points:

- [`../work-packages/COMPLETED.md`](../work-packages/COMPLETED.md) freezes finished,
  evidence-backed history.
- [`../work-packages/ACTIVE.md`](../work-packages/ACTIVE.md) defines every active,
  next, and externally blocked item.

Historical packet sources live under `docs/archive/` for traceability only. They are
not parallel plans and their open items have been reconciled into the active ledger.

## Target demonstrator

The first meaningful end-to-end system consists of:

- Three drones
- Two active mission roles
- One charged reserve drone
- One or two docking/charging positions
- Automatic replacement when an active drone reaches its return threshold
- Continued mission coverage while a drone docks and recharges

This demonstrates persistent autonomy, fleet coordination, battery-aware scheduling, recovery, and docking—the core capabilities of the concept.

Formation flight, leader–follower motion, flocking, area exploration, mapping, and distributed target search are valuable research demonstrations within the project. They are not substitutes for the primary product goal: a fleet that can keep useful work running while individual drones fail, recharge, or rotate out.

## Complete project objective

The long-term objective is a fleet of approximately two to five drones that can operate individually and cooperate without continuous manual control. Each drone should eventually be able to:

- Take off, stabilize, navigate, return, and land autonomously.
- Estimate its position, velocity, altitude, and heading with known uncertainty.
- Report battery, communication quality, health, mission state, and sensor observations.
- React safely to nearby drones and environmental obstacles.
- Maintain assigned spacing, role, or formation when a mission requires it.
- Accept a shared task and report progress or failure.
- Continue safe local behavior during brief communication delays or outages.
- Hand work to another drone before its battery becomes critical.
- Dock, confirm charging, and later rejoin the available fleet.

Several drones receiving unrelated manual commands are not a swarm. Coordination begins when vehicles use shared state or local observations to change their behavior as a group.

## System architecture

The system is divided into layers so algorithms and mission logic can later move to different aircraft.

| Layer | Responsibility |
|---|---|
| Flight controller | Attitude stabilization, altitude/position control, motor output, onboard limits, and low-level failsafes |
| Vehicle adapter | Crazyflie radio/API integration, parameters, telemetry, and command translation |
| Localization | Position, velocity, heading, altitude, uncertainty, and localization-health status |
| Perception | Obstacle ranges, markers, objects, and environmental observations |
| Vehicle supervisor | Vehicle state machine, watchdogs, battery policy, command validation, and abort handling |
| Mission layer | Zones, tasks, plans, progress, completion criteria, and recovery policy |
| Fleet manager | Allocation, roles, separation, handover, reserve selection, and dock scheduling |
| Ground station | Experiment launch, fleet display, logging, operator commands, and emergency authority |

The recommended end-state is **hybrid autonomy**:

- The ground station supplies mission objectives, fleet-wide coordination, logging, and emergency supervision.
- Each drone or its vehicle controller performs time-critical stabilization, local safety checks, and—when supported—local avoidance.
- Fleet behavior should degrade safely if centralized information is delayed.

A completely decentralized swarm is an optional research target, not an early requirement.

## Platform strategy

### Original custom-aircraft concept

The original plan considered custom aircraft built around Pixhawk-class flight controllers, PX4 or ArduPilot, frames, motors, ESCs, GNSS, telemetry radios, companion computers, and manually integrated sensors.

That route offers greater payload, flight time, outdoor capability, and sensor freedom. It also adds propulsion selection, mechanical construction, tuning, radio integration, crash repair, power-system design, and substantially higher safety risk before swarm research can begin.

### Current Crazyflie-first approach

Crazyflie is the preferred indoor research platform because it already provides stabilization, radio communication, Python access, logging, modular decks, and an ecosystem for multi-vehicle experiments. This keeps the early project focused on:

- Multi-agent control
- Localization and state estimation
- Communication behavior
- Collision avoidance
- Mission coordination
- Task allocation and distributed autonomy

The custom PX4/ArduPilot platform remains a later transition target after the architecture and algorithms work indoors.

## Hardware roles and limits

### Crazyradio

Crazyradio connects the host computer to the Crazyflies. It sends commands, receives telemetry, updates parameters, and can manage multiple vehicles. It is not the same as a conventional hobby RC transmitter. One radio should be tested with the initial fleet; add radios only when measured update rate, packet loss, or channel congestion justifies it.

### Flow Deck

The Flow Deck provides floor-relative optical flow and downward ranging. It supports early indoor hovering, relative moves, trajectory tests, and basic autonomous missions. Its error accumulates over time, and performance varies with floor texture, lighting, altitude, reflectivity, and speed.

### Multi-ranger Deck

The Multi-ranger provides sparse directional distance measurements around the drone. It is appropriate for wall detection, corridor following, safety margins, and simple reactive avoidance. It does not identify obstacles or create a complete map.

### Global indoor positioning

Precise formations and reliable inter-drone collision avoidance eventually require a shared global reference. Candidate systems include:

- **Lighthouse:** likely the most practical Crazyflie ecosystem option for accurate indoor swarm work.
- **Loco/UWB:** absolute indoor positioning using installed and calibrated anchors.
- **Motion capture:** excellent accuracy when an equipped laboratory is already available, but usually too expensive to purchase solely for this project.
- **Flow-only odometry:** useful for early work but unsuitable for tight formations or long, repeatable global trajectories.

The intended progression is:

`Flow Deck experiments → quantify drift → add global positioning → close formation and precise fleet tests`

### AI Deck and custom expansion

An AI Deck or other camera/compute module can later support marker detection, object recognition, visual localization, and target search. Breakout or prototyping decks can connect custom sensors, while LEDs or buzzers can make drone identity, role, battery warnings, and faults visible during testing. Every added deck costs mass, power, money, and integration time, so additions require a concrete test objective.

## Communication and shared state

Every drone should expose a versioned state message with at least:

- Drone ID and timestamp
- Position, velocity, altitude, and heading
- Localization quality or covariance
- Battery voltage, estimated energy state, and return threshold
- Link quality and most recent command acknowledgement
- Vehicle and mission state
- Assigned role, task, or sector
- Obstacle warning and health/fault flags

JSON is acceptable for an early simulator or diagnostic tool. Flight experiments should use the Crazyflie protocol or a compact, versioned binary representation when bandwidth matters. MAVLink becomes relevant for the later PX4/ArduPilot adapter.

Before relying on communication in flight, test stationary vehicles and record:

- Update rate
- End-to-end latency and jitter
- Packet loss
- Reconnection behavior
- Maximum useful range in the test environment
- Behavior when messages are duplicated, delayed, reordered, or missing

All messages and commands must carry a drone ID. Commands should also include a sequence number or mission/action ID so acknowledgements cannot be confused with an earlier request.

## Pre-hardware simulation and digital-twin program

### Terminology

Before hardware exists, the system is a **digital prototype** or **simulation
model**. It becomes a true digital twin only when it is connected to an identified
physical vehicle, receives measured state from that vehicle, runs a synchronized
prediction, and reports source-compatible deviations. The product may use
"digital twin" as the name of the planned capability, but the UI and evidence must
not imply that a simulation-only run has been validated against reality.

The project will use two simulator backends behind the same `Vehicle` contract:

| Backend | Primary purpose | Normal use |
|---|---|---|
| Current deterministic Python simulator | Fast tests, safety logic, failure injection, reproducible CI, offline fallback, and broad scenario sweeps | Always retained, usually invisible to the operator once Isaac Sim is ready |
| NVIDIA Isaac Sim backend | Operator-facing high-fidelity 3D rehearsal, rigid-body/contact physics, realistic environment and sensor simulation, and later twin prediction | Default visible simulation after its qualification gate |

These are not two separately tuned sources of truth. A single versioned vehicle
configuration supplies shared mass, geometry, inertia, motor, battery, sensor,
limit, frame, and provenance data. Each backend declares which parts it consumes
and which effects it actually models. Isaac Sim may add geometry, contacts,
rendering, and high-bandwidth sensors without silently changing mission meaning.

### Current simulator state

The current project is already beyond a point-mass or mission-only preview. The
Python simulator currently includes:

- Fixed-timestep deterministic six-degree-of-freedom rigid-body integration.
- Quaternion attitude, angular velocity, gravity, translational motion, drag,
  motor thrust and torque, and first-order actuator response.
- Battery state of charge, modeled current, voltage sag, and low/critical limits.
- High-level takeoff, hover, relative movement, landing, abort, and emergency-stop
  commands routed through the same supervisor used by the application.
- Configured rooms, geofences, axis-aligned obstacles, range rays, IMU, optical
  flow, independent sampled-sensor clocks/latency, modeled transport latency/loss,
  and injected failures.
- Battery-coupled motor voltage/current/thrust, X-layout rotor forces, payload/center
  of mass, per-actuator degradation, body-axis drag, and an estimator-in-loop v2
  controller whose position state is derived from sampled observations.
- Real-time and accelerated clocks, deterministic seeds, model/configuration
  hashes, evidence recording, replay, and source-aware telemetry.
- A Three.js operator view for room geometry, planned paths, observed traces,
  simulated truth, attitude, and range rays.

Its physical coefficients are `CONFIGURED_UNQUALIFIED`. A reduced-order ground-effect
term exists but is disabled by default. It does not currently model propeller RPM,
blade-resolved aerodynamics or wash, detailed contact/crash response, camera imagery,
or physical RF behavior, and it does not execute the actual Crazyflie firmware control
loop. It remains useful and must not be deleted when Isaac Sim is added.

### Why retain the current simulator

Isaac Sim can become the normal operator-facing simulator, but it is not a
replacement for every simulation task. The current simulator should remain for:

- Unit, contract, safety, and API tests that must run without an RTX machine.
- Exact reproduction from a seed and fixed timestep.
- Hundreds or thousands of accelerated failure and fleet scenarios.
- Debugging a single controller, state-machine, or evidence failure quickly.
- Development while the NVIDIA host is unavailable.
- Cross-checking high-level outcomes against an independent implementation.

The fast simulator must not receive an independent set of "better-looking"
parameters. Shared physical inputs are versioned once; backend-specific
approximations and omissions are explicit.

### What NVIDIA supplies and what the project must supply

NVIDIA Isaac Sim supplies a general robotics simulation platform: OpenUSD scenes,
PhysX rigid-body/contact physics, rendering, sensors, Python APIs, OmniGraph, and
a ROS 2 bridge. Those capabilities do not automatically constitute an accurate
Crazyflie model. The project must still define:

- Crazyflie variant, geometry, mass, center of mass, and inertia.
- Rotor positions/directions, thrust and reaction-torque behavior, actuator lag,
  motor/propeller limits, and the selected control stack.
- Battery and payload/deck configuration.
- Coordinate frames, units, simulation clock, command semantics, and timestamps.
- Sensor placement, rates, fields of view, noise, bias, latency, clipping, and
  dropout behavior.
- Room geometry, materials and lighting when camera behavior matters.
- Acceptance thresholds and, after hardware exists, calibration evidence.

CAD is helpful but not required for the first Isaac Sim model. A dimensionally
correct simplified mesh plus measured physical properties is sufficient for the
first simulation. CAD, photogrammetry, or a room scan becomes important when
collision geometry, inertia, camera images, or visual correspondence justify it.

### NVIDIA component selection

Use the smallest useful NVIDIA stack:

| Component | Decision |
|---|---|
| Isaac Sim | Required for the high-fidelity backend |
| OpenUSD | Required for versioned robot and environment assets |
| PhysX | Initial rigid-body and contact engine |
| ROS 2 Bridge and OmniGraph | Required for commands, telemetry, services, clocks, and per-vehicle namespaces |
| Isaac Lab | Deferred until a bounded learning-from-demonstration, planning, or reinforcement-learning objective exists |
| Replicator | Deferred until synthetic camera/depth/segmentation data is required |
| Isaac ROS | Deferred until the real system uses an NVIDIA-accelerated perception pipeline |
| Nucleus/Hub | Optional collaboration/asset infrastructure, not a prerequisite |
| MoveIt, manipulation, AMR navigation, and unrelated extensions | Excluded from the Crazyflie baseline |

Do not install every extension. Pin an exact compatible Isaac Sim, driver, ROS 2,
and project version after a compatibility smoke test. Recheck the current official
requirements at implementation time rather than silently tracking `latest`:

- <https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html>
- <https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html>

The current documented path targets an RTX-equipped Linux or Windows host. The
recommended project deployment is an Ubuntu RTX simulation host running Isaac
Sim, ROS 2, the gateway, and the Control Center backend; a Mac may remain the
operator browser and optional streaming client. This keeps ROS 2 and Isaac Sim
dependencies off the browser/operator machine.

### Target software topology

```text
Mac/operator browser
        |
        | HTTPS + WebSocket + optional Isaac stream
        v
Control Center API on RTX Ubuntu host
        |
        +-- FastSimVehicle -----------------> current Python simulator
        |
        +-- IsaacSimVehicle ----------------> versioned Isaac gateway
                                               |
                                               +-- ROS 2 / OmniGraph
                                               +-- Isaac Sim / PhysX / USD scene
                                               +-- virtual IMU, Flow, ranges, cameras

Later only:
Real Crazyflie adapter ---> measured telemetry ---> TwinCoordinator
IsaacSimVehicle ----------> predicted telemetry -> TwinCoordinator
```

The browser never runs a flight-control loop. ROS 2 may carry simulator commands,
clock, transforms, pose, IMU, range, camera, battery, motor, and fault topics, but
the Control Center remains the sole high-level command authority. Each vehicle
uses a separate namespace such as `cf01`, `cf02`, and `cf03`.

### Pre-hardware implementation sequence

#### Simulation Stage S0 — Reconcile and qualify the current simulator

1. Resolve documentation/model contradictions and complete the interrupted
   real-time hover work.
2. Restore a completely passing backend and UI verification baseline.
3. Freeze command, telemetry, source, unit, frame, time, model, and run-identity
   contracts that both simulators must implement.
4. Verify the 30-second hover as a real-time visible mission, including continuous
   altitude, attitude, motor, battery, Flow, range, abort, and emergency behavior.
5. Add timestep-convergence, long-duration, collision, sensor, failure, replay,
   multi-vehicle, browser, visual-regression, and load tests.
6. Mark all unvalidated physical parameters as configured assumptions rather than
   hardware truth.

Exit gate: the current simulator, mission runtime, evidence path, and dashboard
pass the Fast Simulator work packet with no unresolved type/lint/test failures.

#### Simulation Stage S1 — Define the shared high-fidelity boundary

1. Create a canonical vehicle/sensor/scene parameter schema used by both backends.
2. Define ROS 2 namespaces, topics, QoS, clock policy, coordinate transforms, and
   the network/service boundary.
3. Specify how the exact uploaded mission artifact and its SHA-256 reach either
   backend without recompilation or UI-authored changes.
4. Add an `IsaacSimVehicle` adapter and mock gateway so all integration tests can
   run before the NVIDIA installation exists.

Exit gate: the mocked Isaac backend passes the same contract suite as the current
simulator and cannot bypass the supervisor, evidence recorder, or provenance rules.

#### Simulation Stage S2 — Install and automate Isaac Sim

1. Select an RTX host and run NVIDIA's compatibility checker.
2. Install and pin the compatible NVIDIA driver, Isaac Sim, Ubuntu/Windows
   environment, ROS 2 distribution, and required bridge extensions.
3. Commit environment manifests, launch scripts, health checks, and a minimal
   headless/GUI smoke scene; do not commit proprietary caches or downloaded assets.
4. Verify remote browser access, WebSocket telemetry, simulator streaming, clean
   startup/shutdown, and recovery after the Isaac process exits.

Exit gate: a version-pinned empty scene can be started reproducibly, stepped,
observed through the gateway, stopped, and restarted without manual graph editing.

#### Simulation Stage S3 — Build the Crazyflie and room model

1. Create a simplified dimensionally correct USD Crazyflie asset.
2. Add rigid-body mass/inertia, rotor forces/torques, actuator dynamics, battery,
   controller interface, collision shapes, and declared sensor frames.
3. Build a configurable room and generate or import geometry from the same world
   description used by the fast simulator.
4. Add virtual pose, IMU, Flow-like, range, and optional camera outputs only when
   a named model produces them.
5. Keep visual meshes, collision meshes, physical parameters, and controller
   configuration separately versioned.

Exit gate: forces, rotations, frames, contacts, sensor directions, and mission
commands pass analytic and golden-scene tests for one virtual vehicle.

#### Simulation Stage S4 — Mission and operator qualification

1. Run the same immutable hover, move, abort, emergency, low-battery, link-loss,
   localization-loss, and collision scenarios through both backends.
2. Make Isaac Sim the default visible operator simulation only after command,
   telemetry, timing, safety, evidence, and UI acceptance tests pass.
3. Keep the current simulator as the automated fast-test backend and offline
   fallback; label both sources and model versions explicitly.
4. Add multi-drone namespaces, spawning, separation scenarios, deterministic
   scenario manifests, and performance budgets.

Exit gate: a user can design, run, observe, abort, replay, and compare simulation
missions entirely without physical hardware, and every displayed value identifies
its source and model.

#### Simulation Stage S5 — Prepare for later real digital-twin qualification

1. Define the future measured telemetry, tracker, synchronization, and calibration
   import contracts without pretending those measurements exist.
2. Prepare immutable comparison reports and bounded parameter-calibration output.
3. Require explicit review before a calibration changes a released model version;
   never alter live safety limits automatically.
4. Keep DIGITAL_TWIN execution disabled until a real adapter and global reference
   are independently qualified.

Exit gate: the software can accept future measured evidence without changing the
simulation mission language or allowing the simulator to control real-flight safety.

### Required simulation scenarios

- Real-time takeoff, hover, movement, controlled abort, emergency cutoff, and landing.
- Formation and leader–follower control.
- Minimum-separation enforcement and boundary handling.
- Sensor noise, bias, clipping, latency, dropout, and localization drift.
- Command latency, packet loss, stale fleet state, disconnect, and restart.
- Leader or individual-drone loss.
- Low-battery handover and duplicate task assignment.
- Obstacle contact, avoidance, and local/global planner conflicts.
- Dock occupancy, failed docking, and charging queues.
- Long-duration numerical stability and fixed-timestep convergence.

Promote a behavior to hardware only after it passes nominal and injected-failure
runs in the current simulator and all applicable Isaac Sim scenarios with recorded
metrics. A simulator disagreement is investigated; the visually richer result is
not automatically assumed to be correct.

## Swarm-control research track

The product roadmap centers on persistent mission coverage, but the following experiments develop the coordination primitives it needs.

### Leader–follower

Assign a leader trajectory and fixed relative offset to each follower:

```text
p_follower_desired = p_leader + r_offset
position_error = p_follower_desired - p_follower
```

This is the clearest first coordination demonstration because commands, errors, and failures are easy to visualize.

### Formation control

Begin with a line or wide triangle, then consider a V, square, circle, moving grid, or formation transition. Use generous spacing, low speed, low altitude, and global positioning. Measure formation error, minimum separation, latency, and recovery after a disturbance.

### Flocking

Reynolds-style flocking combines three desired-velocity terms:

```text
v_command = w_separation * v_separation
          + w_cohesion   * v_cohesion
          + w_alignment  * v_alignment
```

Tune the weights in simulation first. Clamp speed and acceleration, enforce a hard safety layer outside the flocking controller, and test pathological cases such as dense clustering and boundary corners.

### Pairwise separation

For every pair of drones `i` and `j`:

```text
d_ij = norm(p_i - p_j)
```

- Below `d_warning`, introduce a bounded repulsive or deconfliction command.
- Below `d_critical`, override the mission with a predetermined escape, stop, vertical separation, or landing policy.

Known global positions should provide the first inter-drone avoidance mechanism. Range sensors can add local protection but should not be assumed to see every nearby drone.

### Allocation, consensus, and leader replacement

Later experiments can assign or replace roles using battery, target distance, sensor capability, communication quality, or priority. Guard against two drones claiming the same task, duplicated coverage during handover, stale leader state, and fleet deadlock.

### Candidate collaborative missions

- Cooperative area scan with one sector per drone
- Leader–follower route with obstacle handling
- Distributed target search and detection broadcast
- Cooperative collection of mapping observations
- Formation transition while moving through a test area
- Persistent two-role coverage with automatic battery rotation

The last mission is the primary end-to-end demonstrator; the others are stepping stones and research extensions.

## Initial budget estimate

| Item | Quantity | Unit price | Estimated cost |
|---|---:|---:|---:|
| Crazyflie 2.1+ | 1 | $240 | $240 |
| Crazyradio | 1 | $43 | $43 |
| Flow Deck | 1 | $55 | $55 |
| Multi-ranger Deck | 1 | $95 | $95 |
| Qi charging hardware | 1 | $38 | $38 |
| Batteries | 5 | $10 | $50 |
| **Estimated total** |  |  | **$521** |

The original notes list a total of $480, but the individual figures add up to $521. Treat all prices as rough estimates and verify compatibility, availability, shipping, taxes, and whether a separate charger is required before ordering. Qi charging hardware is primarily useful for the later docking prototype and does not need to block the first flight stages.

### Starting configurations

- **Lean learning setup:** one Crazyflie, one Crazyradio, 3–5 batteries, charger, spares, and then one Flow Deck after basic flight checks.
- **Practical two-drone setup:** two Crazyflies, one Crazyradio, one Flow Deck per drone, roughly three batteries per drone, charger, spare propellers, and basic structural spares.
- **Stronger research setup:** three Crazyflies, Flow Decks, shared global indoor positioning, roughly three batteries per drone, a multi-battery charging solution, spares, and Multi-ranger Decks added as needed.

The lean setup best follows the purchase gates. The two-drone setup reduces procurement delays if the budget is already approved and the near-term goal is coordination research.

### Batteries, charging, and spares

Use batteries specified as compatible with the selected Crazyflie: correct one-cell voltage, connector, dimensions, mass, capacity, and discharge capability. Larger batteries are not automatically better because added mass changes flight behavior.

For sustained three-drone development, roughly nine batteries is a useful planning figure: one set flying, one cooling or waiting, and one charging. Charging through a drone may be adequate initially, but repeated fleet testing benefits from a compatible multi-battery solution.

Keep spare propellers and basic structural parts available. Follow LiPo precautions: reject swollen or damaged packs, prevent shorts, allow hot packs to cool, avoid deep discharge, store packs appropriately, and do not leave charging batteries unattended.

## Safety and operating rules

These rules apply at every stage:

- Use a clear indoor test area and keep people, pets, cables, glass, and fragile objects outside it.
- Wear eye protection and use propeller guards where practical.
- Define and test an emergency-stop procedure before autonomous flight.
- Begin new behaviors at low altitude and low speed.
- Test one new variable at a time.
- Never continue a test with damaged propellers, a swollen battery, an unreliable radio link, or unexplained behavior.
- Keep a physical way to disconnect power and have a suitable LiPo-safe charging and storage setup.
- Record software version, configuration, battery, environment, result, and faults for every repeatable test.
- Treat AI output as advisory. Deterministic safety logic must retain control of flight and abort decisions.
- Revisit legal, insurance, and operational requirements before any outdoor testing.

## Development principles

1. **Reliability before sophistication.** A short mission completed repeatedly is more valuable than an advanced behavior that works once.
2. **High-level software owns the mission.** Flight-control firmware stabilizes the vehicle; the project software supervises state, intent, faults, and recovery.
3. **Every stage has an exit gate.** Do not add hardware merely because it may be useful later.
4. **Failures must be visible.** Every mission ends with a clear `SUCCEEDED`, `ABORTED`, or `FAILED` result and an explanation.
5. **Safety overrides normal mission logic.** Emergency stop, loss of link, critical battery, and invalid localization take priority over all other commands.
6. **Design for replacement.** Crazyflie-specific transport and sensors should sit behind interfaces so the mission architecture can later move to PX4 or ArduPilot.

## Stage 0 — Basic platform setup

### Entry precondition

Simulation Stages S0 through S5 are the first project stages. Do not purchase or
connect project-controlled flight hardware merely to begin Stage 0. Enter this
hardware stage only after the Fast Simulator and NVIDIA Isaac Sim pre-hardware
gates have passed, or after a documented decision explicitly narrows/defer the
NVIDIA scope without weakening the mission, safety, evidence, and test gates.

### Hardware

- One Crazyflie 2.1+ or Crazyflie Brushless
- One Crazyradio
- Three to five compatible batteries
- Suitable charger and LiPo-safe storage
- Laptop

### Goal

Understand and verify the complete control chain:

`Laptop → radio link → flight controller → motors → telemetry → laptop`

### Work items

- Install and version the Bitcraze client, Python libraries, firmware, and project dependencies.
- Give every drone a unique radio address, software ID, and visible physical label.
- Connect to the drone reliably.
- Confirm firmware and client compatibility.
- Arm, disarm, and perform a basic manual flight.
- Read battery voltage, attitude, altitude, and link quality.
- Download and inspect flight logs.
- Trigger and recover from the documented emergency-stop procedure in a safe test setup.
- Establish a repeatable logging and configuration-backup process.

### Exit gate

The operator can repeatedly connect, inspect, arm, fly, land, and disarm without unexplained behavior, and can explain what the onboard flight controller does versus what the laptop controls.

## Stage 1 — Stable autonomous flight with one drone

### Additional hardware

- Flow Deck

The Flow Deck measures downward optical flow and distance to the ground. It improves indoor position holding but does not provide drift-free global room coordinates.

### Goal

Complete a short autonomous mission without manual piloting:

`take off → hover → move 1 m forward → move 1 m right → return approximately → land`

### Work items

- Automatic takeoff and landing
- Hover at a commanded height
- Short relative movements
- Stop and hold
- Approximate return to the starting area
- Operator-commanded abort and land
- Square, circle, or waypoint-sequence tests after straight movements are reliable

### Expected limitations

- Optical flow depends on floor texture and lighting.
- Position error accumulates over time.
- Yaw error changes the direction of relative movement.
- Height sensing can degrade over unsuitable surfaces.
- Battery voltage can alter behavior.

### Acceptance test

- Stable hover without large uncontrolled drift
- Short relative moves accurate to roughly 10–30 cm
- Successful takeoff and landing in at least 9 of 10 controlled trials
- No unexplained state changes during the mission
- Position error, overshoot, settling time, drift, repeatability, and battery use recorded for comparison

### Exit gate

One drone repeatedly completes the short mission without manual piloting.

## Stage 2 — Single-drone control layer

### Additional hardware

None.

### Goal

Replace ad hoc movement commands with a supervised drone abstraction.

### Minimum state model

```text
DISCONNECTED
READY
TAKING_OFF
FLYING
RETURNING
LANDING
FAULT
```

State transitions should be explicit, logged, time-bounded, and rejected when unsafe. An emergency path must be able to interrupt every normal state.

### Work items

- Command interface for takeoff, movement, return, abort, and landing
- Continuous telemetry collection
- Battery and link-quality monitoring
- Mission and vehicle state tracking
- Command acknowledgement and timeout detection
- Fault handling and emergency override
- Flight and event logging
- Repeated mission execution
- Simple operator dashboard

### Required mission record

Each run should capture:

- Drone ID and radio URI
- Software and configuration version
- Start and finish timestamps
- Battery at start, lowest point, and landing
- Commands and acknowledgements
- State transitions
- Relevant telemetry and link quality
- Mission result and failure reason

### Exit gate

Project software—not the standard Crazyflie client—supervises a complete mission and unambiguously reports success or failure.

## Stage 3 — Basic obstacle sensing

### Additional hardware

- Multi-ranger Deck

Use the Flow Deck and Multi-ranger together:

- **Flow Deck:** floor-relative motion and height
- **Multi-ranger Deck:** distances to nearby obstacles

### Goal

Perform a simple autonomous mission in a controlled room without requiring a completely open path.

### Work items

- Read and validate obstacle distances.
- Stop before a large wall.
- Maintain a configurable safety distance.
- Follow a wall.
- Navigate a simple corridor.
- Choose an alternative direction when blocked.
- Detect and escape simple reactive-avoidance traps.

### Expected limitations

- Sensors have limited fields of view.
- Thin, angled, dark, or reflective objects may be missed.
- Range readings describe distance, not object identity or shape.
- Multiple avoidance rules can conflict.
- Purely reactive behavior can deadlock in corners.

### Acceptance test

- Stops reliably before large walls
- Maintains the configured safety margin
- Completes a repeatable static obstacle course
- Avoids contact in at least 9 of 10 controlled trials

### Exit gate

One drone completes a basic mission around large static obstacles without contact.

## Stage 4 — Mission abstraction

### Additional hardware

None.

### Goal

Move from low-level commands such as “move forward 1 metre” to tasks such as “inspect Zone A.”

### Work items

- Represent zones, tasks, constraints, and completion criteria.
- Decompose a task into flight actions.
- Estimate duration and energy use.
- Track mission completion percentage.
- Pause, resume, abort, and retry missions.
- Decide whether enough energy remains to continue.
- Prioritize a safe return over task completion.

### Exit gate

The software accepts a task, converts it into actions, monitors progress, and makes an explicit complete-or-abort decision.

## Stage 5 — Two-drone fleet management

### Additional hardware

- Second Crazyflie
- Flow Deck for the second drone
- Ideally a Multi-ranger Deck for the second drone
- Additional batteries
- A second radio only if testing shows the first is a bottleneck
- Shared global positioning before close-spacing or precise formation tests

### Goal

Manage two independent vehicles safely; do not attempt sophisticated swarm behavior yet.

### First fleet mission

`Drone A → Zone A`  
`Drone B → Zone B`

Begin under centralized control. Use widely separated launch points, large horizontal spacing, low altitude, and low speed. Progress from separate hover points to synchronized vertical motion, parallel movement, leader–follower motion, and simultaneous landing.

### Work items

- Assign immutable unique drone IDs.
- Connect to and display both drones simultaneously.
- Route commands by ID and prevent cross-commanding.
- Start missions sequentially before attempting simultaneous launch.
- Monitor battery, link, mission, and faults independently.
- Stop or land one drone without stopping the other.
- Define safe behavior when either drone fails.
- Measure update rate, command latency, position quality, and minimum separation throughout each flight.
- Keep centralized position-based separation active before experimenting with onboard or distributed avoidance.

### Acceptance test

- Both drones repeatedly complete separate missions.
- No crossed IDs or incorrectly routed commands occur.
- One drone can abort or land while the other continues safely.

### Exit gate

The software treats the drones as independent managed agents rather than manually controlled vehicles.

## Stage 6 — Three drones and swarm logic

### Additional hardware

- Third Crazyflie
- Flow Deck
- Multi-ranger Deck if obstacle-aware behavior is required
- More batteries
- Additional radio only if measured communication load requires it

### Goal

Introduce allocation, reserve capacity, task reassignment, and conflict handling.

### Reference scenario

```text
Drone A → Sector 1
Drone B → Sector 2
Drone C → charged reserve

Drone A reaches return threshold
→ Drone C takes over Sector 1
→ Drone A returns
```

### Work items

- Validate a wide line or triangle formation before task-reallocation trials.
- Demonstrate leader–follower behavior and recovery after leader loss.
- Enforce pairwise warning and critical separation thresholds.
- Divide an area into sectors.
- Allocate tasks by battery, capability, and availability.
- Keep one drone in reserve.
- Reassign unfinished work after a failure or low-battery event.
- Prevent duplicate coverage during handover.
- Maintain minimum separation.
- Coordinate takeoff and landing order.
- Detect allocation conflicts and deadlocks.
- Optionally test flocking and formation transitions in simulation, then in a globally localized flight area.

### Exit gate

The three-drone system maintains safe separation and continues a mission after one drone or leader becomes unavailable.

## Stage 7 — Single docking prototype

### Additional hardware

- One simple docking platform
- Charging contacts or Qi charging interface
- Visual marker, beacon, or other alignment aid
- Dock-side sensor or camera if required
- Mechanical guides that tolerate landing error

Build one forgiving dock for one drone. Mechanical capture and alignment are preferable to demanding perfect localization.

### Goal

Autonomously land, confirm charging, and later return the drone to the available pool.

### Docking state sequence

```text
RETURN_TO_DOCK_AREA
→ LOCATE_DOCK
→ ALIGN
→ DESCEND
→ CONFIRM_CONTACT
→ CONFIRM_CHARGING
→ CHARGING
→ READY
```

### Work items

- Detect dock occupancy.
- Separate coarse return from precise final alignment.
- Confirm physical landing independently from charging current.
- Retry or divert after a failed approach.
- Set a maximum number of attempts.
- Mark a landed but uncharged drone as a fault.

### Acceptance test

First prove reliable landing inside the physical capture area. Then target a confirmed charging connection in at least 9 of 10 attempts.

### Exit gate

The drone lands autonomously, confirms that it is charging, and later becomes available for another mission.

## Stage 8 — Automated replacement and rotation

### Additional hardware

- At least three drones
- At least one functioning dock
- Preferably two docking or charging positions
- Enough batteries and charging capacity for repeated cycles

### Goal

Maintain a defined mission coverage level while individual drones leave, recharge, and rejoin.

### Reference cycle

```text
Drone A → active
Drone B → active
Drone C → charged reserve

A reaches return threshold
→ C launches early
→ C confirms takeover
→ A returns and docks
→ A charges
→ A becomes the next reserve
```

### Work items

- Predict the safe return point from measured energy use.
- Add a conservative reserve margin.
- Select and launch a replacement early enough.
- Confirm takeover before releasing the outgoing drone.
- Track charging progress and estimated ready time.
- Queue drones when docks are occupied.
- Recover from failed replacement or docking attempts.
- Measure coverage gaps and total mission availability.

### Exit gate

The fleet completes multiple flight-and-charge cycles while maintaining the defined coverage level. This is the first complete persistent-autonomy demonstrator.

## Stage 9 — Vision and onboard AI

### Additional hardware

- AI Deck or another camera-plus-compute platform on one drone

### Goal

Improve one clearly defined perception function without making AI responsible for basic flight safety.

### Development order

1. Capture and store images reliably.
2. Detect a simple visual marker.
3. Use marker detection to assist docking.
4. Detect a known object.
5. Track a moving object.
6. Feed detections, confidence, and position estimates into deterministic mission logic.
7. Only then evaluate visual navigation or SLAM.

### Interface rule

`camera → perception result + confidence → deterministic mission logic → validated flight action`

### Exit gate

Vision measurably improves one mission function, while invalid or low-confidence detections fail safely.

## Stage 10 — Outdoor transition

### Additional hardware

- One PX4- or ArduPilot-compatible development drone
- GNSS, with RTK GNSS if the use case requires it
- Telemetry link
- Camera or depth sensor as needed
- Larger battery and appropriate safety equipment

Start with one outdoor drone, not a fleet.

### Goal

Run the same high-level mission architecture on a realistic outdoor platform.

### Components that should transfer

- Mission and task model
- Vehicle-state model
- Fleet manager and task allocator
- Battery scheduler and replacement logic
- Dock manager
- Operator interface
- Logging, fault handling, and mission results

### Components that must be adapted

- Crazyflie-specific communication
- Indoor localization and Flow Deck assumptions
- Deck-specific sensor interfaces
- Indoor obstacle model
- Docking sensors and approach logic

### New constraints

- Wind and weather
- GNSS error and outages
- Magnetic interference
- Longer-range communication
- Regulation and airspace restrictions
- Higher energy, crash cost, and injury risk

### Exit gate

One outdoor drone executes the same high-level mission model used by the indoor prototype.

## Purchase gates

The pre-hardware simulator program is the first purchase gate. An RTX host may be
selected for NVIDIA-ISAAC-WP-01, but physical drone procurement follows successful
software simulation qualification unless availability or lead time is explicitly
accepted as a separate procurement risk.

| Purchase point | Hardware to add |
|---|---|
| Start | One Crazyflie, Crazyradio, charger, and 3–5 batteries |
| After connection and manual-flight tests | Flow Deck |
| After stable autonomous flight | Multi-ranger Deck |
| After single-drone mission supervision works | Second equipped drone |
| Before close formation or precise multi-drone paths | Lighthouse, Loco/UWB, or available motion-capture positioning plus required per-drone hardware |
| After two-drone management and separation work | Third equipped drone |
| After reliable three-drone task reassignment | One docking prototype |
| After docking works | Additional dock or charging position |
| After automated rotation works | AI Deck for one drone |
| After the indoor architecture is proven | One outdoor PX4-compatible drone |

## Milestone checklist

Reality/NVIDIA dependency path:

```text
REALITY-WP-00 ──┬──> REALITY-WP-01 ──┐
                └──> REALITY-WP-02 ──┴──> REALITY-WP-03
REALITY-WP-02 ───────────────────────────> REALITY-WP-04 (hardware bench)
REALITY-WP-01..04 ───────────────────────> REALITY-WP-05 (contained flight)
REALITY-WP-03..05 ───────────────────────> REALITY-WP-06 (cross-source/model gate)
```

NVIDIA architecture and host work may proceed after WP-00; the mock gateway is
closed by WP-02. Isaac physical-model qualification remains dependent on WP-04/06
measured evidence, and a digital-twin claim remains disabled until the independent
reference gate passes.

- [x] Current simulator passes the Fast Simulator work-packet gate with a clean test, type, lint, UI, and real-time verification baseline; this is software evidence only.
- [x] Reality WP-00 establishes baseline commit `4bd185d` and classifies software, configured, physical, deferred, and unsupported claims.
- [x] Reality WP-01 through WP-03 pass the same-source, backend-neutral, estimator-in-loop, continuous-health, gateway-failure, and accelerated-load software gate.
- [ ] Reality WP-04 bench-qualifies the pinned Crazyflie 2.1+ Flow Deck V2/Multi-ranger adapter before physical model tuning.
- [ ] Reality WP-05/06 qualify contained hardware missions and cross-source residuals before any digital-twin claim.
- [x] One immutable mission artifact executes through both the current and mocked Isaac adapters under the same contract and produces an equal normalized intent trace.
- [ ] A pinned Isaac Sim environment starts, steps, streams telemetry, and shuts down reproducibly on an RTX host.
- [ ] One virtual Crazyflie completes hover, movement, abort, emergency, and failure scenarios in Isaac Sim.
- [ ] Isaac Sim is qualified as the default operator-facing simulation backend while the current simulator remains the fast-test backend.
- [ ] Multi-drone Isaac Sim scenes pass namespace, identity, timing, separation, evidence, and performance tests without hardware.
- [ ] One drone connects and flies reliably.
- [ ] One drone completes a short autonomous mission.
- [ ] Project software supervises and evaluates the mission.
- [ ] One drone detects and avoids large static obstacles.
- [ ] The mission layer accepts zone-level tasks.
- [ ] Simulation passes latency, packet-loss, low-battery, collision, and failure scenarios.
- [ ] Shared global positioning is validated for close multi-drone work.
- [ ] Two drones complete independent missions without command mix-ups.
- [ ] Two drones demonstrate leader–follower motion and enforced separation.
- [ ] Three drones hold a wide formation, allocate work, and recover from one unavailable drone.
- [ ] One drone docks and confirms charging.
- [ ] The fleet rotates drones while maintaining coverage.
- [ ] Vision improves one bounded mission function.
- [ ] The architecture executes on one outdoor platform.

## Suggested project structure

As implementation begins, keep hardware-specific code separate from mission logic:

```text
src/
  adapters/          # Fast simulator, Isaac gateway, Crazyflie and future PX4 integrations
  simulation/        # shared model contracts and deterministic fast simulation
  isaac/             # out-of-process gateway protocol and Isaac integration code
  vehicles/          # vehicle state machine and telemetry model
  missions/          # tasks, zones, plans and completion rules
  fleet/             # allocation, reserve and handover logic
  docking/           # dock state, approach and charging confirmation
  safety/            # limits, aborts, watchdogs and fault policy
  operator/          # dashboard and operator commands
  logging/           # events, telemetry and mission reports
tests/
  simulation/
  hardware/
  scenarios/
config/
  simulation/        # shared vehicle, sensor, frame and fidelity configuration
  isaac/             # pinned runtime, scene and gateway configuration
docs/
assets/
  usd/               # source-controlled project-owned USD layers, not runtime caches
```

## Test record template

Use the same record for every acceptance trial:

```markdown
### Test: <name>

- Date/time:
- Operator:
- Drone IDs:
- Hardware configuration:
- Software/configuration version:
- Environment and floor/lighting conditions:
- Starting battery:
- Expected behavior:
- Actual behavior:
- Result: PASS / FAIL / ABORTED
- Lowest battery:
- Faults or anomalies:
- Logs/video:
- Follow-up action:
```

## Immediate next actions

1. Reconcile the separately completed WP-09/WP-10 task when its changes become visible;
   do not duplicate or overwrite that implementation in the mission-planner queue.
2. Close WP-11: deterministic mission-plan compilation, safety findings,
   pre-provision admission, exact receipt binding, focused tests, API/client parity,
   and same-tree repository verification.
3. Execute WP-12 through WP-17 in order: plugin contracts/manifests/registries;
   route-planner library; fleet-policy/recovery extraction plus the non-bypassable
   Safety Kernel; mission intent and controlled phases; operator hash approval; then
   Fast Sim replay, restart, load, and release qualification.
4. Preserve Fast Sim physical model v2 as
   `SOFTWARE_QUALIFIED_CONFIGURED_UNQUALIFIED`. Keep exact-aircraft calibration,
   endurance, controller transfer, and external residuals open until Reality WP-04
   through WP-06 produce reviewed measurements.
5. Keep NVIDIA/Isaac host work and every physical-drone stage outside the active queue
   until the operator has access to the required computer or real aircraft and grants
   explicit authorization. Do not install, qualify, purchase, connect, or fly as part
   of WP-11 through WP-17.
