# Mission package v2

> Navigation: [documentation index](../README.md)

Status: `FROZEN_SOFTWARE_CONTRACT`
Backends: `FAST_SIM`, `MOCK_ISAAC`, explicitly bound future `ISAAC`/`CRAZYFLIE`
Physical authorization: none

Mission package v2 extends the existing bounded uploaded-Python format with one
literal `MISSION` declaration. The source remains the immutable mission artifact;
its SHA-256 and mission ID are calculated from the exact uploaded bytes.

Existing files containing only `async def mission(drone)` are schema v1. They
remain valid, keep the same source hash and normalized intent, and are planned as
one implicit role using the configured backend vehicle. No migration is required.

## Frozen declaration

```python
MISSION = {
    "schema_version": 2,
    "roles": {
        "left": {
            "logical_vehicle_id": "drone-left",
            "display_name": "Left drone",       # optional
            "home_m": [-0.8, 0.0, 0.0],
            "initial_role": "ACTIVE",           # ACTIVE or RESERVE
            "required": True,
            "required_capabilities": [],
            "zone": {                            # optional; world volume otherwise
                "minimum_m": [-2.0, -2.0, 0.0],
                "maximum_m": [0.0, 2.0, 1.0],
            },
            "task": {                            # optional
                "task_type": "MISSION_ROLE",
                "priority": 100,
                "estimated_energy_percent": 5.0,
                "energy_margin_percent": 10.0,
            },
        },
    },
    "warning_separation_m": 0.75,
    "critical_separation_m": 0.5,
    "observation_freshness_s": 1.0,
    "child_failure_policy": "CONTINUE_HEALTHY",
}


async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    if drone.role == "left":
        await drone.move_relative(x_m=-0.1, duration_s=1.0, frame="home")
    await drone.land(duration_s=2.0)
```

The role mapping is sorted by role ID before validation and planning. A package
must contain one to three unique roles and logical vehicle IDs, with at least one
`ACTIVE` role. `RESERVE` roles are connected, observed, preflight-approved, and
kept disarmed until production fleet policy assigns work.

`drone.role` is immutable role context. The restricted worker executes the same
source once per active task owner. All existing source, syntax, command,
observation, duration, subprocess, filesystem, network, import, reflection, and
bounded-control-flow restrictions remain in force.

## Backend boundary

The declaration cannot contain a simulator type, model parameter, seed, fault
schedule, Isaac namespace, radio URI, USB serial, or physical address. The
planner derives a backend-neutral `DeploymentManifest`; a separate binding maps
each logical vehicle to a backend identity.

- Fast Sim creates session vehicles in the already configured world/model.
- Mock Isaac creates one gateway namespace per logical vehicle.
- Physical planning fails unless the caller supplies an exact operator-approved
  `CRAZYFLIE` binding profile. It never selects the first discovered aircraft.

Backend choice changes the binding hash, not the mission source SHA, logical
vehicle IDs, assignments, or deployment SHA.

## Operator and lifecycle behavior

The normal start request contains the mission ID and execution backend mode; it
does not contain fleet size or assignments. The server records placeholders and
then performs identity verification, explicit connection, source-aware telemetry
readiness, preflight, deterministic assignment, sequential launch, separation
monitoring, terminal snapshots, safe disconnect, and bounded session cleanup.

See [`two_role_move.py`](../../missions/qualification/two_role_move.py) for an
uploadable two-role qualification artifact. The ACTIVE-WP-09 portable artifact is
[`persistent_coverage_rotation.py`](../../missions/qualification/persistent_coverage_rotation.py):
it declares two active coverage zones and one reserve without backend identifiers or
simulation fault configuration. Production fleet policy, not the mission file, owns
battery-triggered handover, lease transfer, separation, return, and dock scheduling.
