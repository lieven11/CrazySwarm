# Simulator adapter contract 1.0.0

> Navigation: [documentation index](../README.md)

Version `1.0.0` is the frozen backend-neutral boundary implemented by
`crazyswarm_app.vehicles.base.Vehicle`. Its machine-readable release artifact is
`config/contracts/simulator-adapter-v1.json`. Mission code, the safety supervisor,
evidence, API, replay, and browser logic depend on this boundary—not on Fast Sim or
an Isaac implementation.

## Required interface

An adapter supplies immutable `identity` and `capabilities`, an
`AdapterContractManifest`, stable `execution_metadata`, and asynchronous
`connect`, `disconnect`, `execute`, `snapshot`, and `telemetry_stream` operations.
Adapter discovery alone has no authority to change operating mode, arm, or execute.

`execute` accepts a versioned `CommandEnvelope` and returns a
`CommandAcknowledgement`. Target identity, command identity, source, issue time,
completion or rejection status, completion time, and reason codes retain their
shared meaning. Abort-and-land is a controlled recovery command. Emergency stop is
an immediate, separately guarded and evidenced motor-cutoff command.

## Commands, frames, units, and time

Version 1 covers arm, disarm, takeoff, relative movement, hover, stop-and-hold,
land, abort, and emergency stop. Allowed states, required capabilities, duration,
and completion semantics are defined in `COMMAND_SEMANTICS`.

All numeric values use SI units. WORLD/HOME is right-handed with +Z up; BODY and
sensor/rotor transforms are explicit. Quaternions use Hamilton `(w, x, y, z)`
order. An adapter must not silently reinterpret a frame or use browser coordinates.

Every telemetry envelope carries source and receive timestamps, a source-clock ID,
an epoch, monotonically scoped sequence identity, and explicit vehicle identity.
Simulation time, source time, receive time, wall time, and replay time remain
separate. Reset increments the source-clock epoch rather than making time appear to
run backward in one epoch.

## Telemetry and provenance

Signals declare unit, frame, source class, model/source identity, validity, and
presence. An unsupported or never-received field is absent; it is not zero. Invalid,
unavailable, stale, measured-real, simulated-model, configured, derived, planned,
and replayed are distinct states. Fast Sim may expose model truth; an adapter must
not relabel onboard estimation, synthetic data, or Isaac state as external measured
ground truth.

The adapter manifest negotiates capabilities, signals, and model IDs before a run.
Missing capabilities fail closed. An additive signal does not become visible until
both its contract and source provenance are understood by the consumer.

## Run identity and evidence

Simulation receipts bind mission source SHA-256, model ID/version/configuration
SHA-256, scenario ID/configuration SHA-256, initial-state SHA-256, seed, and fixed
step. Adapter-specific process IDs and wall-clock timestamps are not identity
inputs. Commands, acknowledgements, telemetry, faults, safety state, and results
remain separately attributable during replay.

## Lifecycle and safety guarantees

The safety supervisor—not an adapter or renderer—owns leases, preflight, allowed
state transitions, timeouts, abort recovery, and live-mode authorization. Adapter,
renderer, WebSocket, or evidence-consumer failure cannot grant command authority.
Each adapter must isolate its failures and return explicit rejection/fault evidence.

## Conformance

`tests/vehicles/conformance.py` is the minimum shared lifecycle suite. Both Fast Sim
and the Isaac-shaped mock pass it. A future Isaac adapter must additionally prove
command/state semantics, frames, clocks, missing-field suppression, run identity,
failure isolation, and safety behavior without changing mission files or adding a
browser control loop.

Changes follow `docs/reference/SIMULATOR_COMPATIBILITY.md`. Incompatible meaning, frame,
command, clock, or required-field changes require adapter contract 2.0.0.
