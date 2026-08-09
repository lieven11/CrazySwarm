# CrazySwarm Control Center

CrazySwarm is a simulation-first mission, fleet, safety, telemetry, evidence, and
operator-control application for Crazyflie-class vehicles. It is designed to run
one immutable mission through different backends while centralizing preparation,
multi-vehicle coordination, safety, and audit evidence.

The application always starts in `SIM`. Hardware discovery never arms a vehicle,
starts a mission, or enables `DIGITAL_TWIN`.

## Current product position

- Uploaded restricted Python mission packages can declare one to three logical roles.
- The normal Play workflow derives the deployment, provisions Fast Sim vehicles,
  prepares every member, and runs one or multiple child missions.
- Fast Sim provides deterministic 6-DOF dynamics, modeled sensors and energy,
  failures, real-time or accelerated clocks, telemetry, evidence, and replay.
- Two active coverage roles and a ready, disarmed reserve can execute a telemetry-
  triggered handover with generation-numbered authority, return/landing, and an
  abstract modeled dock/charge lifecycle.
- WP-09 and WP-10 are implemented and reconciled with normal-Play Fast Sim evidence.
  The active queue now starts with the operational mission planner, plugin, recovery,
  and mission safety work in WP-11 through WP-17.
- Preview now exposes a deterministic plan receipt; Play rebuilds and admits that plan
  before provisioning, and execution evidence identifies the accepted receipt.
- Live Isaac, physical Crazyflie qualification, and a calibrated digital twin are not
  complete and are not implied by simulation results.

See the two status ledgers for the precise boundary:

- [`../work-packages/COMPLETED.md`](../work-packages/COMPLETED.md)
- [`../work-packages/ACTIVE.md`](../work-packages/ACTIVE.md)

## Local setup

```bash
cd /Users/lievenmuller/Projects/CrazySwarm
nvm use
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd ui && npm ci && cd ..
```

Run the complete Fast Sim qualification gate with:

```bash
scripts/qualify_fast_sim.sh
```

Use `scripts/qualify_fast_sim.sh --install` in a fresh environment. The detailed
operator and automated workflows are in the
[`Fast Simulator guide`](../guides/FAST_SIMULATOR.md).

## Dashboard

Install the dashboard as a persistent macOS user service:

```bash
.venv/bin/crazyswarm-control dashboard-service install
```

Open `http://localhost:3001`. Service commands are:

```bash
.venv/bin/crazyswarm-control dashboard-service status
.venv/bin/crazyswarm-control dashboard-service restart
.venv/bin/crazyswarm-control dashboard-service uninstall
```

For foreground development, use `.venv/bin/crazyswarm-control dashboard` and leave
that one terminal open. The browser updates after UI edits, the API restarts after
Python/configuration edits, and the launcher recovers either child process if it exits.
There is no need to start Vite or Uvicorn separately. The API can still be started on
its own with `.venv/bin/crazyswarm-control serve --reload --port 8001`.

## Mission boundary

A v1 mission contains one restricted `async def mission(drone)` function. A v2
package also contains a literal `MISSION` declaration for logical roles, capabilities,
homes, zones, tasks, energy requirements, separation thresholds, freshness, and child
failure policy. It never selects Fast Sim, Isaac, a radio URI, a concrete aircraft,
physics coefficients, or a fault schedule.

```python
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=3.0)
    await drone.move_relative(x_m=0.2, duration_s=1.5, frame="home")
    await drone.land(duration_s=2.0)
```

The exact division of responsibility is documented in
[`../system/README.md`](../system/README.md), and the frozen v2 format is documented
in [`../reference/MISSION_PACKAGE_V2.md`](../reference/MISSION_PACKAGE_V2.md).
The compiled operational plan is defined in
[`../reference/MISSION_PLAN_V1.md`](../reference/MISSION_PLAN_V1.md); author, reviewer,
and operator safety checks are in
[`../guides/MISSION_SAFETY_GUIDE.md`](../guides/MISSION_SAFETY_GUIDE.md).
The planned `RoutePlanner`, `FleetPolicy`, `RecoveryStrategy`, registry, and Safety
Kernel boundaries are in
[`../system/PLANNING_AND_RECOVERY_PLUGINS.md`](../system/PLANNING_AND_RECOVERY_PLUGINS.md).

## Safety and fidelity boundary

- Every mission command goes through backend-neutral identity and safety authority.
- Discovery, connection, observation, preflight, arming, execution, recovery, and
  cleanup are distinct states.
- Collision in Fast Sim means deterministic termination at configured geometry; it
  is not resolved crash or contact physics.
- Physical coefficients remain `CONFIGURED_UNQUALIFIED` until measured hardware
  evidence passes the Reality gates.
- `DIGITAL_TWIN` remains disabled until a real adapter, synchronized measured
  telemetry, and an independent reference are qualified.

Read the current model and claim limits before interpreting simulated output:

- [`../reference/FAST_SIM_PHYSICS_V2.md`](../reference/FAST_SIM_PHYSICS_V2.md)
- [`../qualification/FAST_SIMULATOR_LIMITATIONS.md`](../qualification/FAST_SIMULATOR_LIMITATIONS.md)
- [`../reference/SIMULATOR_COMPATIBILITY.md`](../reference/SIMULATOR_COMPATIBILITY.md)
