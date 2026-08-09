# Persistent fleet software foundation — WP-05 through WP-08

> Navigation: [documentation index](../README.md)

## Delivered scope

The software now has a backend-neutral three-vehicle persistent-coverage model:
`cf01` and `cf02` own two coverage tasks, while `cf03` is the connected, disarmed
reserve. Allocation considers task priority, capability, availability, observed
battery/energy margin, and distance with a stable vehicle-ID tie break.

Handover is fail closed. The outgoing lease remains current through replacement
selection and preparation. `confirm_takeover` changes owner and lease generation in
one ledger update; the previous owner immediately fails current-lease checks.
`release_outgoing` is rejected until takeover has been confirmed. If no reserve is
serviceable, the result is explicitly degraded and the old owner is not silently
released.

Dock scheduling is a software model. It owns capacity, reservations, queues,
health, bounded attempts, modeled landing, modeled contact, modeled charging
confirmation, charge progress, and estimated-ready time. It does not claim a
physical landing, electrical contact, or battery charge.

Fleet metrics are derived from semantic events and cover availability, coverage
gaps, separation, assignment/lease latency, handover phases, energy margin, docks,
fault recovery, and drops. The operator API exports the full software-only report,
and the dashboard’s Fleet panel exposes staged WP-02/WP-04 controls plus a software
evidence download.

The Isaac gateway protocol is frozen at `1.3.0` for this slice. A coordinated run
binding is all-or-none and includes fleet/session/deployment/task/lease identity,
the per-vehicle backend namespace, and `READY` preparation state. The mock worker
rejects a namespace different from the one selected at connection.

## Canonical artifacts

- `config/fleet/three-drone-persistent-coverage-v1.yaml`
- `config/fleet/fast-sim-three-drone-binding-v1.yaml`
- `config/fleet/mock-isaac-three-drone-binding-v1.yaml`
- `config/worlds/three_drone_fleet.yaml`
- `config/qualification/persistent-fleet-scenarios-v1.json`
- `config/qualification/fleet-load-budgets-v1.json`
- `config/isaac/gateway-contract-v1.json`
- `scripts/qualify_persistent_fleet.py`
- `scripts/qualify_fleet_load.py`

The qualification manifest declares 27 injected scenarios and three deterministic seeds,
giving 81 outcomes per backend. The canonical nominal handover executes
the allocator, atomic transfer, pairwise separation, dock integration, metrics, and
normalized hashing. The local load runner measures 100 state API, replay API, and
bounded storage queries with three vehicles, verifies the reserve is observed and
disarmed, and checks task, lease, subscription, and telemetry-worker cleanup.
The final local run completed in 4.40 seconds; state, replay, and storage-query
p95 latencies were 5.81 ms, 6.28 ms, and 31.96 ms respectively, with every
post-shutdown cleanup counter at zero.

## Run the qualification

From the repository root:

```bash
PYTHONPATH=src .venv/bin/python scripts/qualify_persistent_fleet.py
```

Expected headline fields:

```text
decision: PASS_SOFTWARE_ONLY
equivalent_normalized_intent: true
equivalent_normalized_outcome: true
normalized_report_sha256: 3f044174fdbaadb3c318ad4ac4fa3f85ac7fb065e9c723617c3f4e82e09feee2
live_isaac: NOT_RUN
physical_flight: NOT_RUN
```

Write a diagnostic artifact explicitly when desired:

```bash
PYTHONPATH=src .venv/bin/python scripts/qualify_persistent_fleet.py \
  --output artifacts/persistent-fleet-software-qualification-v1.json
```

Run the three-vehicle performance and cleanup gate:

```bash
PYTHONPATH=src .venv/bin/python scripts/qualify_fleet_load.py
```

Run focused verification:

```bash
.venv/bin/pytest -q tests/fleet tests/api/test_fleet_operator.py tests/isaac
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src
cd ui
PATH=/Users/lievenmuller/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
  ./node_modules/typescript/bin/tsc --noEmit
PATH=/Users/lievenmuller/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
  ./node_modules/vitest/vitest.mjs run
```

## Operator test

Start the application with `config/worlds/two_drone_fleet.yaml`. In the Fleet panel,
use the single staged action repeatedly: declare, connect, observe, preflight, then
start the coordinated two-drone run. Each drone has its own lifecycle row and abort
control. Reloading the browser reads the same server-owned session. Use “Software
evidence · Fast Sim / mock Isaac” to download the WP-05–08 report.

The three-drone reserve/handover is currently qualified through the canonical
software runner and domain/API evidence export; it is not represented as physical
or live-Isaac behavior.
