# Fleet foundation: WP-01–04 implementation record

> Navigation: [documentation index](../README.md)

This software-only foundation separates mission behavior, logical deployment,
backend binding, preparation, task ownership, and fleet coordination. It is
qualified locally with Fast Sim and the mock Isaac process boundary. It does not
claim live Isaac, NVIDIA-host, radio, or physical-flight qualification.

## Artifact and identity boundary

The immutable v1 contracts live in `crazyswarm_app.fleet.artifacts`:

- `MissionArtifact` identifies behavior and source without selecting a backend.
- `DeploymentManifest` declares logical vehicle IDs, homes, roles, zones, tasks,
  safety constraints, docks, and completion policy.
- `BackendBindingProfile` is the only fleet artifact containing simulator
  instance/namespace or future physical-radio identifiers.
- `FleetSessionIdentity` binds mission, deployment, binding, model, scenario,
  initial state, execution backend, session, and fleet run.

Canonical JSON and SHA-256 make the identities independent of mapping order.
Only schema version 1 is currently accepted; older, absent, and newer versions
fail closed until an explicit migration is implemented.

The example deployment and its two interchangeable software bindings are in
`config/fleet/`.

## Operator preparation and observation

`FleetPreparation` starts with configured placeholders that have no telemetry.
It records these orthogonal state axes:

```text
registration: DECLARED -> DISCOVERED -> IDENTITY_BOUND -> VERIFIED
connection:   DISCONNECTED -> CONNECTING -> READY | FAULT
mission role: UNASSIGNED | ACTIVE | RESERVE | HANDOVER | RETURNING | DOCKED | CHARGING
observation:  NOT_OBSERVED -> CURRENT -> STALE | COMPLETED_SNAPSHOT
```

Backend initialization/discovery, connection, observation, and fleet preflight
are explicit methods and evidence events. `FleetCoordinator.run()` refuses to
start unless every required identity is verified, connected, currently observed,
and approved by fleet preflight. A convenience orchestrator may call these
methods in sequence, but it cannot omit or disguise a lifecycle step.

Preparation evidence carries the execution session plus deployment and binding
hashes. The committed `fleet-preparation-golden-v1.json` trace is asserted for
Fast Sim, mock Isaac, and the fake-real adapter so their semantic order stays
identical while their backend evidence remains distinct.

## Tasks and coordination

`TaskLedger` keeps logical task progress separate from child mission runs. It
validates capabilities and observed battery against the task estimate plus
margin, and supports pause, resume, retry, reassignment, completion, and abort.
Generation-numbered ownership leases prevent a stale owner from updating a task
after reassignment. Versioned task events reconstruct ownership and progress.

`FleetCoordinator` sits above `MissionRunner`; it does not bypass
`SafetySupervisor`. Each child run is routed by immutable logical vehicle ID.
Coordinated command envelopes include fleet session, deployment hash, fleet run,
task, lease generation, mission run, and vehicle identity, which Fast Sim and the
mock Isaac gateway verify at their command boundary.

Launch checkpoints are sequential. Once children are active, each vehicle is
monitored independently. A member abort does not implicitly command its peer;
the configured child-failure policy explicitly selects continue, hold, or land.
Stale member observations abort only that member under the default continue
policy.

Pairwise separation is centralized. A warning or critical condition before
launch blocks launch. During execution, the coordinator aborts one deterministic
member before allowing both members to continue inside the threshold. Every
sample and intervention is retained in the fleet result with minimum-separation
metrics.

## Qualification

Run:

```bash
.venv/bin/python scripts/qualify_fleet_foundation.py
```

The command runs two logical drones and two independent tasks first with Fast
Sim and then with two mock-Isaac gateway processes. It compares normalized
preparation and fleet traces and emits a deterministic normalized outcome hash.
The focused tests also cover identity rejection, lifecycle truthfulness,
energy/capability assignment, pause/retry/reassignment, stale-lease rejection,
evidence replay, command identity, individual child results, and proactive
warning-separation launch blocking.
