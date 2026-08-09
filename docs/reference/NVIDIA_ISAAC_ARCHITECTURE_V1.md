# NVIDIA Isaac architecture decision v1

> Navigation: [documentation index](../README.md)

Status: `SOFTWARE_VERIFIED_ARCHITECTURE_AND_MOCK`. This decision implements the
currently approved `GO_ARCHITECTURE_AND_MOCK` path. It does not assert that Isaac
is installed, that an NVIDIA host is compatible, or that the configured model is
physically accurate. `FAST_SIM` remains the deterministic default.

## Decision and process placement

The Control Center, `MissionRunner`, `SafetySupervisor`, evidence recorder, replay,
and command authority stay in the normal CrazySwarm Python environment. An
`IsaacSimVehicle` speaks gateway protocol 1.2 to a separate process. No Isaac, ROS,
OmniGraph, USD, or PhysX Python type enters the application domain.

The worker may be a directly managed local child process or a remote local/cloud
worker reached through certificate-validated TLS 1.3. Plain TCP is unsupported.
Remote support is a deployment boundary, not approval to create paid cloud
resources. The candidate Victus and every cloud host remain unqualified until a
host record explicitly reaches `GO_MINIMAL_EXPERIMENT`.

ROS 2, OmniGraph, simulation lifecycle, PhysX, and the USD stage are colocated with
Isaac. The Mac remains authoritative in the current split-host design. A future
qualified Linux/Windows host may colocate the Control Center, but that does not
change the authority or protocol contract.

## Frozen contracts

- Domain adapter contract: `docs/reference/SIMULATOR_ADAPTER_CONTRACT_V1.md` and
  `ADAPTER_CONTRACT_VERSION=1.0.0`.
- Gateway wire contract: `GATEWAY_PROTOCOL_VERSION=1.3.0` and
  `config/isaac/gateway-contract-v1.json`.
- Canonical frame contract: `crazyswarm-frames-v1`.
- Minimal scene: `config/isaac/minimal-one-vehicle-scene-v1.json`.
- Shared vehicle inputs: `SimulationConfig.vehicle_parameters()`. The scene pins
  their canonical SHA-256 and refuses drift.

Capability negotiation is mandatory on connect. The application rejects physical
authority, `DIGITAL_TWIN`, an incomplete command set, the wrong model, a wrong
vehicle or session, a wrong frame, and a protocol mismatch before command use.

## Identity, security, and command mapping

Connect creates a gateway instance and session identity. Before a mission command,
`MissionRunner` binds mission run ID, exact source SHA-256, simulation run identity,
model/version/configuration hash, and scenario/configuration hash. Each canonical
command carries the bound run identity. The gateway never accepts `LIVE` or
`REPLAY` mode. Supervisor recovery commands remain valid for the bound run; this
does not give the worker independent recovery authority.

Local process authentication uses a random per-process secret passed through the
child environment. Remote authentication uses a separately supplied secret after
TLS peer verification. Secrets are excluded from receipts and repository config.
Commands are serialized with one request in flight. An acknowledgement lost after
write has `UNKNOWN_OUTCOME`; automatic retry is false. Reconnect creates a new
session and cannot reinterpret the earlier command as success.

The child is started without a shell, with an explicit absolute executable, bounded
messages, request/shutdown deadlines, a bounded stderr tail, and an explicit
start/ready/stop/failed state. Process exit, EOF, timeout, malformed output, or
network loss fails the simulation mission. It cannot affect later physical command
authority.

## Clock, stepping, and lifecycle

Isaac owns simulation time and the fixed physics step. Protocol samples contain
simulation/source timestamps, a clock ID, and an epoch. Time and sequence must be
strictly monotonic inside an epoch; reset increments the epoch. The Control Center
adds receive-monotonic time. UTC is evidence/display time only.

The state path is `NEW -> STARTING -> READY -> RUN_BOUND -> STOPPING -> STOPPED`.
Any crash or protocol failure enters `FAILED`. A new launch is a new gateway
instance/session. Pause, single/multiple fixed-step, reset, real-time factor, and
clean shutdown are worker-owned operations exposed through the declared gateway
and ROS service boundary; no manual OmniGraph edit may be required.

Telemetry queues are bounded at 100 samples in the minimal profile. Overflow drops
the oldest telemetry, increments an observable counter, and never blocks command
acknowledgement. Commands are never dropped to relieve backpressure.

## Frames, ROS namespaces, and signals

Canonical world/home is right-handed Z-up, +X room-forward/east, +Y room-left/north.
Body is +X forward, +Y left, +Z up. Angles use radians and right-hand signs;
quaternions use Hamilton `wxyz`. USD must be metres and Z-up. The ROS edge is ENU.
Any conversion occurs inside the worker and is covered by golden fixtures.

Vehicle `cf01` owns `/cf01`; future vehicles use `/cf02`, etc. Topic/service names,
message types, QoS, rates, and failure behavior are frozen in the machine-readable
gateway contract. ROS messages are translated to protocol messages on the worker;
they are never forwarded directly to the application.

Required minimal outputs are state, separately labeled estimate and simulated
truth, IMU, Flow-like observation, six range directions, clock, and gateway health.
Battery/motor models and rendering are optional. Camera, depth, RTX lidar,
Replicator, and physical-radio metrics are unsupported in the minimal profile.
Missing, no-hit, invalid, and stale remain explicit states and never become zero.

## Minimal scene and qualification boundary

The one-vehicle headless scene specifies a 4 m by 4 m by 2.5 m primitive room,
`cf01`, primitive visual/collision geometry, no renderer, no cameras, and no RTX
lidar. It is a scene specification and hash-addressed launch input, not a qualified
USD/PhysX result. Every unmeasured geometry, mass/model, environment, sensor, and
controller input remains `CONFIGURED_UNQUALIFIED`. `physical_model_authorized` and
`digital_twin_enabled` are hard false.

The initial controller selection is the same `ESTIMATOR_IN_LOOP_REFERENCE` profile
used by Fast Sim. A live worker may translate canonical high-level intent into an
Isaac-side controller only after host/runtime qualification; it may not bypass the
supervisor. The exact Python QF files remain unchanged.

## Evidence and output identity

Mission receipts retain repository commit/dirty state, source/runtime identity,
adapter/backend/authority, model/version/configuration, scene/version/configuration,
seed, fixed step, initial state, and aggregate run SHA-256. Live evidence must add
gateway instance/session, exact Isaac/PhysX/ROS/driver versions, host profile,
launch profile, process exit, queue/drop health, and measured RAM/VRAM/startup/rate/
thermal data. Absence of live evidence stays `NOT_RUN`.

## Candidate resource and failure budgets

The Victus is `SELECTED_UNQUALIFIED` and reportedly below the documented baseline
recorded in the work packet. The only planned local workload is one headless
primitive vehicle without RTX sensors. Until measured, the following are
`CONFIGURED_UNQUALIFIED_BUDGET`, not performance claims: no swap thrash, no thermal
throttling, stable 100 Hz physics/source clock, bounded 100-sample telemetry queue,
and clean startup/shutdown within the manual job deadline. RAM, VRAM, temperature,
startup, real-time factor, and sustained-duration limits must be supplied by WP-01
host evidence before launch acceptance. Three live vehicles are
`UNSUPPORTED_LOCAL_UNTIL_MEASURED`; three-identity behavior remains mock-testable.

## Threat and failure review

Golden and fault tests cover wrong request/session/vehicle/run/model/frame identity,
stale epoch/sequence/time, malformed and oversized messages, duplicate/reordered
responses, delayed response, process/network loss, gateway restart, missing data,
queue overflow, and lost acknowledgement. The required result is explicit rejection
or mission failure; never success, implicit retry, cross-vehicle delivery, or a
fabricated healthy numeric value.

Live closeout is intentionally still waiting. `scripts/launch_isaac_headless.py`
only produces an executable no-shell plan after exact runtime, gateway entrypoint,
secret, compatible host evidence, and launch authorization exist. Without those it
reports `WAITING_FOR_COMPATIBLE_LOCAL_OR_CLOUD_HOST` and starts nothing.
