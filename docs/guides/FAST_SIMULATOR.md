# Fast Simulator reference guide

> Navigation: [documentation index](../README.md)

## Release position

Fast Sim (`fast-sim`, model `crazyflie-6dof@1.0.0`) is the pre-hardware software
reference, the CI simulator, and the fallback simulator. It is also the default
operator backend while the available Isaac host is absent, resource-limited,
experimental, or not fully qualified. An Isaac adapter may become the preferred
high-fidelity backend only after its separate qualification passes. Fast Sim is not
removed or demoted as a test/fallback backend when that happens.

The Fast Simulator release gate is software-only and does not require an
Isaac-capable host, NVIDIA runtime, paid cloud GPU, physical aircraft, radio, deck,
or motion-capture system. It does not authorize real flight.

## Supported local setup

Requirements are Python 3.11 or newer, Node.js 22.13 or newer, npm, and a POSIX
shell. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
scripts/qualify_fast_sim.sh --install
```

`--install` performs the locked npm install and Python requirements install before
running the complete gate. Once dependencies are installed, the release gate is:

```bash
scripts/qualify_fast_sim.sh
```

Set `PYTHON=/absolute/path/to/python` or `NPM=/absolute/path/to/npm` to select
explicit runtimes. The command checks health/configuration, reproduces every
canonical scenario twice in clean child processes, runs backend tests, Ruff,
strict mypy, regenerates the OpenAPI client, and runs UI lint, typing, unit tests,
rendered-HTML tests, visual hashes, the production build, and a complete npm
dependency audit.

## Operator and automated modes

Start the real-time operator application with:

```bash
.venv/bin/crazyswarm-control dashboard
```

Open `http://localhost:3001`. Configurations under `config/worlds/` use the
`realtime` clock so displayed mission duration follows wall time and every rendered
state comes from received simulator telemetry. The browser does not interpolate a
new flight state or run a control loop.

Canonical and injected-failure scenarios use the `accelerated` clock. They retain
the same fixed-step physics and command semantics but advance simulation time as
quickly as the process allows. Use accelerated mode for tests and reproducibility;
use real-time mode for operator observation and intervention exercises.

Pause, reset, and single-step are developer API operations, not normal flight
controls. They require a disconnected vehicle; single-step also requires a paused
clock. Every mutation is authenticated and recorded as operator evidence.

## Canonical release scenarios

The frozen manifest is `config/qualification/canonical-scenarios-v1.json`.
`scripts/verify_canonical_scenarios.py` launches a clean process twice per scenario,
requires byte-identical stable outcome records, and checks both the configuration
and outcome hashes below.

| Scenario | Configuration SHA-256 | Outcome SHA-256 | Expected result |
| --- | --- | --- | --- |
| Hover | `8a0137811959dedb31d23f9dd4f113af6227aa953e70daf68f2a315aaae39767` | `59620fae250c2ac49805297ffd2d415937de00df469a3d836bd4a2448d21619f` | `SUCCEEDED / MISSION_COMPLETED` |
| Move/return | `726645d94995dc49a87e4969f5efdd9ef0598d9f7b37804a42f735257bf834ec` | `fb311148a9e09a71898eaee1ff47869c14e3c6a83a79ceb0e519291f95641cc6` | `SUCCEEDED / MISSION_COMPLETED` |
| Link-loss failure | `514dbada809e7f64a21a053f81577e2aabae35f67598928714231384264e15a1` | `78c7fd4b743a7d2e673440c2033954b87368f46cdb176303122ba98dfcaeb7d0` | `FAILED / LINK_LOST` |
| Three vehicle | `f8bbc8658bfc19f518db26c2fe5ad51a33d399fd28641e53d60f84a4d0013914` | `6863c3cbf932ba2248995cc44148c6cd831c1078006d0da4aac679bb98c9fc96` | all three `SUCCEEDED / MISSION_COMPLETED` |

The failure case deliberately verifies a failed receipt and link-loss state rather
than pretending that commands can still land a disconnected vehicle. The
three-vehicle case models independent vehicles and scoped command ownership; it
does not model rotor wash or inter-vehicle aerodynamics.

WP-20/WP-21 deliberately advanced the outcome record to
`execution-authority-and-goal-landing-v2`: every result now binds explicit execution
authority and landing uses the admitted goal-region contract. The underlying physics
model remains `1.0.0`. Both the original hashes and the immediately preceding
pre-WP-20 hashes remain immutable history under `config/qualification/`.

## Fidelity and model identity

The model integrates fixed-step 6DOF rigid-body state, quaternion attitude, four
actuator responses, thrust/body torque, gravity, configured drag, battery load and
voltage sag, IMU, Flow-like odometry, and six range rays. Collision with configured
geometry terminates deterministically; it is not a resolved contact/crash model.

Every run receipt binds the mission artifact/configuration, adapter contract,
physics model and parameter hash, scenario hash, initial-state hash, seed, and
fixed timestep. Supported software tolerances and qualification results are in
`config/qualification/fast-sim-v1.json`. The API exposes the same fidelity and
contract information at `/api/v1/simulation/fidelity` and
`/api/v1/simulation/contracts`.

All physical coefficients are `CONFIGURED_UNQUALIFIED`. They are model inputs, not
measurements and not hardware-qualified evidence. See
`docs/qualification/FAST_SIMULATOR_LIMITATIONS.md` before interpreting any modeled quantity.

## Evidence and replay

Mission starts, phase transitions, commands, acknowledgements, safety transitions,
telemetry, operator actions, faults, and final results are stored against one run
identity. Completed and failed runs are immutable history. Replay is command-free:
it reads the recorded event sequence and cannot send vehicle commands. A stopped or
completed UI shows a labeled frozen snapshot or replay, never live-looking synthetic
updates.

## Compatibility and versions

The simulator adapter contract is frozen at `1.0.0`; its machine-readable artifact
is `config/contracts/simulator-adapter-v1.json` and its normative explanation is
`docs/reference/SIMULATOR_ADAPTER_CONTRACT_V1.md`. Model, config, and migration rules are in
`docs/reference/SIMULATOR_COMPATIBILITY.md`. Hash changes to a canonical scenario or outcome
are release changes and must never be accepted as an incidental baseline update.

## Open-work review at release

| UI packet | Software review | Remaining work |
| --- | --- | --- |
| UI-WP-02 | Verified; shared identity, command, telemetry, frame, time, and adapter contracts are complete | none in Fast Sim scope |
| UI-WP-08 | Verified; visual baselines, supported viewport coverage, renderer load, and source distinctions pass | none |
| UI-WP-09 | Software scope verified; browser journey, reconnect, replay, archive, and isolated worker penetration pass | measured hardware engineering views only |
| UI-WP-10 | 6DOF/software foundation verified, including independent analytic references and current model replay identity | bench calibration, measured initial state, real/sim execution, physical residuals, and bounded hardware calibration |

No unresolved software-only P0/P1 item blocks adapter version 1.0.0. The remaining
items require physical evidence or a separately qualified real adapter and do not
block Fast Sim release or the start of the NVIDIA adapter work.

## Troubleshooting

- `Python runtime not found`: create `.venv` or set `PYTHON` to an executable Python.
- `npm was not found`: install Node.js/npm or set `NPM` to its absolute executable.
- Canonical hash mismatch: inspect the scenario/model/config change. Do not replace
  a frozen hash until the change has an intentional compatibility/release decision.
- UI client mismatch: rerun the full qualification command; it regenerates OpenAPI
  types before UI checks.
- Real-time mission appears slow: this is expected; source time tracks wall time.
  Use an accelerated scenario for automated testing.
- DIGITAL_TWIN remains disabled: this is expected until a real adapter and measured
  reference are qualified. Continue using the default Fast Sim backend.
