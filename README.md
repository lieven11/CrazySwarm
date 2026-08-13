# CrazySwarm Control Center

Simulation-first mission, fleet, safety, telemetry, evidence, and operator-control
software for Crazyflie-class vehicles.

## Project status

Planning is intentionally limited to two current documents:

- [Completed work](docs/work-packages/COMPLETED.md) — finished, evidence-backed scope.
- [Active and next work](docs/work-packages/ACTIVE.md) — WP-35 through WP-39 repair the
  generated catalog into a truth-gated executable one-, two-, and three-drone learning
  curriculum; externally gated work remains listed there.

WP-01 through WP-34 are implemented and reconciled in the completed-work ledger.
NVIDIA/Isaac and physical-drone work are explicitly deferred; the WP-25 handoff does
not enable or authorize either path.

## Documentation

- [Documentation index](docs/README.md)
- [Project guide and local setup](docs/project/README.md)
- [Mission, planner, Control Center, and simulator responsibilities](docs/system/README.md)
- [Planning and recovery plugin architecture](docs/system/PLANNING_AND_RECOVERY_PLUGINS.md)
- [Mission plan receipt v1](docs/reference/MISSION_PLAN_V1.md)
- [Mission safety guide](docs/guides/MISSION_SAFETY_GUIDE.md)
- [Long-range development guide](docs/project/DEVELOPMENT_GUIDE.md)
- [UI design implementation guide](design.md)
- [Detailed interface design](docs/project/DESIGN.md)
- [Fast Simulator guide](docs/guides/FAST_SIMULATOR.md)

## Quick start

```bash
cd /Users/lievenmuller/Projects/CrazySwarm
nvm use
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd ui && npm ci && cd ..
scripts/qualify_fast_sim.sh
```

Start the dashboard with one terminal command:

```bash
.venv/bin/crazyswarm-control dashboard
```

Leave that terminal open. Frontend edits update the browser automatically, backend
edits restart the API automatically, and either process is restarted if it exits. You
do not need to run a separate Vite or Uvicorn command.

The application always starts in `SIM`. Hardware discovery never arms or launches a
vehicle. `DIGITAL_TWIN` remains disabled until a real adapter, synchronized measured
telemetry, and an independent reference pass their qualification gates.
