# Hardware runtime ownership

CrazySwarm has one physical hardware lane. The Crazyradio, configured Crazyflie,
persistent dashboard service, live API/UI ports, and retained hardware state are one
operator-owned runtime. Parallel coding remains supported, but only that runtime may
touch the radio.

## Normal operating model

| Lane | Checkout | Ports | Physical hardware | May restart live service |
|---|---|---:|---|---|
| Operator hardware | Local | UI `3001`, API `8011` | Yes, exclusive | Only by explicit operator deployment |
| Background coding | Codex worktree | Deterministic `18xxx`/`22xxx` | No | No |
| Unit/integration tests | Local or worktree | Test allocated | Injected/fake link only | No |

The installed macOS service starts with owner `operator-dashboard-service` and holds
an OS-backed exclusive lease for its entire API lifetime. The kernel releases the
lease if that process crashes. A second hardware runtime fails before it can initialize
cflib or open the USB radio. Every direct cflib discovery or connection also requires
the owning process, so a helper script cannot silently become a second radio client.

Check current ownership without touching hardware:

```bash
.venv/bin/crazyswarm-control hardware-owner status
```

## Parallel Codex work

Start background tasks in a Codex **Worktree**. Worktrees isolate source and commands,
and CrazySwarm additionally assigns them deterministic alternate dashboard ports. A
worktree dashboard is simulation-only even if a saved physical binding exists.

Initialize shared read-only dependency links once per new worktree:

```bash
scripts/setup_worktree.sh
```

Background tasks may build the UI, run type checking, run backend/UI tests, and use
fake link factories. They do not install or restart the dashboard service, invoke
`Restart CrazySwarm.command`, kill ports `3001`/`8011`, call physical API endpoints,
or pass `--hardware-owner`.

## Explicit deployment to the hardware lane

Deployment is an operator decision because it interrupts observation. Run:

```bash
scripts/deploy_hardware_dashboard.sh
```

The command refuses to deploy from a worktree, refuses while backend actuation may be
active, and refuses to erase an active or unconfirmed contained-flight stop. If the
command link cannot confirm landing/disarm, physically disconnect the Crazyflie
battery first; only then may the operator set `CRAZYSWARM_PHYSICAL_POWER_REMOVED=1`
for the one deployment that archives the retained unconfirmed-flight marker and
replaces that stale in-memory flight state. The archive remains in the canonical
cache for recovery inspection. The command builds the immutable UI release from
current source, records its source digest,
and pins that exact release in the installed service before restarting once. Installation
also rejects a noncanonical working directory or cache path. It does not retry by
repeatedly replacing the runtime, and it fails unless the restarted API actually holds
the `operator-dashboard-service` hardware lease.
Deployment takes an exclusive physical-operation admission gate before its final state
check and retains it through build and replacement. Play, readiness, abort, and Motor
bench mutations that have not yet entered are rejected while that gate is held; an
operation that entered first becomes durable before deployment rechecks state and causes
deployment to refuse safely.

After deployment, verify:

```bash
.venv/bin/crazyswarm-control dashboard-service status
.venv/bin/crazyswarm-control hardware-owner status
```

Service status is successful only when the process is healthy, owns the hardware lane,
uses the Local checkout, and its pinned release digest still matches current UI source.

Then inspect `Drone connection`. `PAIRED` means observation is active. `RETRYING` or
`ERROR` preserves the radio failure reason. Do not restart merely to clear a truthful
radio error; power-cycle the Crazyflie/Crazyradio when the backend explicitly requires
it.

## Meaning of `SUSPENDED`

`SUSPENDED` means one named physical operation temporarily owns all access to the
observer's radio session. A contained Play operation pauses observer sampling and
borrows a command-capable view of the already-connected, identity-confirmed link. It
does not disconnect after observation, reconnect before takeoff, disconnect after
landing, and reconnect again for observation. The observer remains the transport owner,
the operation publishes its measured telemetry, and `finally` returns the same link to
observer sampling after grounded telemetry is captured.

Before the first command permit exists, one stale-link check may close and reconnect
the observer-owned link exactly once. A failure there is a start failure with no command
outcome and must not retain `Abort and land`. Once command dispatch begins, commands are
never retried automatically. An Abort request during startup or flight joins the
existing suspension and link; it must not create a second connection or replace the
authoritative suspension reason.

Readiness, Motor bench, global motor-stop recovery, and explicit observer pause remain
separate bounded operations that may release observation and create their own command
connection. In every case the backend reports `SUSPENDED` with the exact owner and
reason, for example `Motor bench owns the radio`. Every API path resumes in `finally`;
unrelated simulation, build, test, or chat activity must never produce this state.

## Failure handling

- `Local service request timed out`: first check whether the operator service was
  deliberately deployed. A background task must not respond by restarting it.
- `Crazyradio hardware runtime is already owned`: leave the owner running and use a
  simulation-only worktree. Never remove the lease file to bypass ownership.
- `CONNECTING` longer than the bounded handshake: the adapter transitions to an error;
  correct power, URI, USB ownership, or radio loss, then allow automatic retry.
- The Link disclosure and `radio-transport-events.jsonl` distinguish
  `USB_UNAVAILABLE`, `TARGET_OFFLINE`, `RF_ACK_LOSS`,
  `OUTBOUND_QUEUE_SATURATED`, `TELEMETRY_STALE`, and
  `PROTOCOL_SETUP_FAILED`. These are measured failure boundaries, not proof that a
  particular dongle or aircraft component is defective. Use controlled substitution
  before making a hardware claim.
- A failed Play that never dispatched a command returns to a terminal failed result
  without retaining `Abort and land`, even when the radio handshake had already opened.
  Abort requested during that connection phase cancels the start without opening a
  second recovery link. Default Crazyflie 2.1 firmware automatic arming is distinguished
  from manual arming: current `flying=false` is a safe grounded state in that mode, and
  the backend does not wait for a Disarm state that firmware immediately reverses.
- `Motor output unconfirmed` or `stop_required=true`: do not deploy or power-cycle the
  host. Use the live global Stop action and confirm `IDLE`; follow the physical safety
  procedure if radio contact is unavailable.
