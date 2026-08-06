# CrazySwarm Control Center

Simulation-first mission, safety, telemetry, and operator-control software for
Crazyflie vehicles. The application always starts in `SIM`; detecting hardware
never arms or launches a vehicle.

## Local setup

```bash
cd /Users/lievenmuller/Projects/CrazySwarm
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd ui && npm ci && cd ..
```

Run the complete Fast Simulator qualification gate with one command:

```bash
scripts/qualify_fast_sim.sh
```

Use `scripts/qualify_fast_sim.sh --install` after creating a fresh virtual
environment to install both stacks before running the same gate. See the
[Fast Simulator guide](docs/FAST_SIMULATOR.md) for canonical scenarios,
real-time/accelerated operation, evidence, fidelity, and troubleshooting.

The official Bitcraze client remains available as `cfclient` for firmware,
manual engineering, and hardware diagnostics.

## Python missions and dashboard

Start the complete dashboard and local API with one command:

```bash
.venv/bin/crazyswarm-control dashboard
```

Open `http://localhost:3001`. The UI attaches to the local API automatically
through a same-origin proxy; internal ports and the temporary local token remain
server-side. Upload a `.py` mission, name it, select **Simulation**, and press
**Run simulation**. There are no built-in operator missions and the dashboard
does not edit mission parameters. Operator world configurations use a real-time
clock, and the dashboard receives intermediate physics and sensor samples while
each command is in progress. A 30-second hover therefore takes approximately 30
seconds on screen. Failure-injection scenarios may remain accelerated for fast,
repeatable automated checks.

The current safe mission subset is:

```python
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=3.0)
    await drone.move_relative(x_m=0.2, duration_s=1.5, frame="home")
    await drone.land(duration_s=2.0)
```

Imports and arbitrary Python statements are rejected. The source file is stored
unchanged and identified by SHA-256. The current simulator is a deterministic,
fixed-step rigid-body 6-DOF quadrotor model. It models quaternion attitude, motor
thrust and body torque, gravity, linear drag, battery load and voltage sag, IMU,
Flow-like odometry, and six-direction range rays. Its configured physical
coefficients are not hardware-qualified, and it does not model propeller RPM,
ground effect, aerodynamic wash, camera imagery, or real radio performance. The
machine-readable fidelity statement is available from
`GET /api/v1/simulation/fidelity`; the versioned frame, vehicle-parameter,
signal, command, time, run-identity, and adapter contracts are available from
`GET /api/v1/simulation/contracts`. Collision means deterministic termination
at configured geometry, not resolved contact or crash dynamics. Supported
timestep tolerances, analytic comparisons, failure repetitions, and other
software-only qualification limits are recorded in
`config/qualification/fast-sim-v1.json`.

**Digital twin** stays disabled until a real adapter and measured reference are
qualified. Merely detecting hardware never changes the mode, arms, or starts
flight.

Fast Sim remains the default operator backend while an Isaac host is absent,
resource-limited, experimental, or not fully qualified. It is permanently retained
for CI and as the supported fallback after an Isaac adapter is introduced. Closing
the Fast Simulator pre-hardware gate does not require an Isaac-capable host.

The shared adapter boundary is frozen at version 1.0.0 in
[`config/contracts/simulator-adapter-v1.json`](config/contracts/simulator-adapter-v1.json).
Compatibility rules and physical-model limitations are documented in
[`docs/SIMULATOR_COMPATIBILITY.md`](docs/SIMULATOR_COMPATIBILITY.md) and
[`docs/FAST_SIMULATOR_LIMITATIONS.md`](docs/FAST_SIMULATOR_LIMITATIONS.md).

The API can still be started independently for development with
`.venv/bin/crazyswarm-control serve --port 8001`.

## Package boundaries

- `domain`: versioned commands, telemetry, identity, capabilities, and results
- `vehicles`: backend-neutral vehicle interface and adapters
- `missions`: registered missions and the shared safety lifecycle runner
- `simulation`: deterministic indoor vehicle and sensor backend
- `safety`: command authority, preflight policy, and recovery supervisor
- `observability`: bounded telemetry, durable evidence, queries, and replay
- `api`: authenticated local HTTP and WebSocket gateway for the operator UI

All internal values use SI units: metres, seconds, radians, metres per second,
volts, amperes, and percentages explicitly named with a `_percent` suffix.
