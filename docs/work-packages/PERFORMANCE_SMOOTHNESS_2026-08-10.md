# Performance and motion smoothness investigation

Date: 2026-08-10  
Status: implemented presentation-path fixes and incremental startup backfill; remaining backend and scale packages proposed  
Scope: Fast Sim, live dashboard, uploaded Python missions, campaign snapshots, and three-vehicle software load

This document is a focused supplement to `ACTIVE.md`. It does not reorder that active
ledger because the ledger already contains unrelated in-progress campaign work.

## Outcome

The rendered motion problem was primarily a presentation-path problem, not a stop in
the authoritative trajectory. The UI received a new state approximately every 100 ms,
rebuilt and disposed every dynamic Three.js object on each update, and only advanced
the playback target when a poll arrived. The snapshot button repeated the same work by
building and disposing a second complete scene on the live renderer. Campaign timing
diagnostics could additionally send three HTTP requests per vehicle per dashboard
update.

The implemented changes now:

- retain drone meshes, trace lines, velocity/heading lines, truth models, and range
  lines and update their transforms or dynamic buffers in place;
- advance buffered source time on every animation frame, bounded by the existing
  maximum-extrapolation setting;
- animate direct object and follower references instead of traversing the complete
  scene twice per frame;
- keep plan, trace, and truth layers mounted and use visibility for operator layers
  and evidence snapshots;
- render a snapshot with the existing scene and a neutral evidence camera instead of
  constructing and disposing a second scene;
- report browser timing only for an active campaign and at most once per second;
- expose frame, draw-call, geometry, heap, and snapshot-duration diagnostics on the
  scene canvas; and
- keep an independently started uploaded-Python run visible even when a campaign case
  remains docked.

Three.js documents that geometry and material creation allocates renderer resources
and that disposal/recreation can cause a performance drop in the current frame. Its
buffer APIs support updating attributes in place with `needsUpdate`, which is the model
used here:

- https://threejs.org/manual/en/how-to-dispose-of-objects.html
- https://threejs.org/docs/pages/BufferGeometry.html
- https://threejs.org/docs/pages/BufferAttribute.html

The animation loop uses the `requestAnimationFrame` timestamp for frame-rate-independent
progress, consistent with the browser contract:

- https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame

## Reproducible experiments

### Uploaded-Python continuous-motion probe

The probe is a real Python mission file at
`missions/performance/smooth_motion_probe.py`. It performs a bounded takeoff, two
five-second traverses, a hover, and a landing. The profiler at
`scripts/profile_dashboard_performance.py` uploads that file through the mission-file
API, previews and approves the resulting plan, starts it in Fast Sim, and observes the
run until its terminal result. It does not execute an inline or temporary mission.

```bash
.venv/bin/python scripts/profile_dashboard_performance.py \
  --base-url http://127.0.0.1:3001/control-api \
  --pid <api-pid> --pid <ui-pid> \
  --output .cache/performance/smooth-motion.json
```

The profiler records state latency and bytes, poll cadence, source cadence, visible
pose steps, repeated source observations, and the summed CPU/RSS of explicitly named
processes.

### Three-vehicle software qualification

```bash
PYTHONPATH=src .venv/bin/python scripts/qualify_fleet_load.py
```

This uses an isolated temporary evidence store and the canonical three-drone Fast Sim
deployment. It exercises 100 state requests, 100 replay requests, 100 storage queries,
and verifies complete task and telemetry cleanup.

### Rendered snapshot experiment

The production dashboard was opened in the in-app browser. A two-drone realtime
campaign was started, the evidence snapshot button was used during flight, and the
canvas diagnostics were sampled before and after capture. The campaign completed
normally.

## Measurements

### Application data path

The comparable before/after rows use the same uploaded Python file, a 100 ms target
poll period, one Fast Sim drone, and state payloads of approximately 18.1 kB.

| Metric | Before | After | Interpretation |
|---|---:|---:|---|
| Mission result | Succeeded | Succeeded | Same bounded mission |
| Wall duration | 16.503 s | 16.414 s | Equivalent realtime duration |
| State latency mean | 23.258 ms | 22.307 ms | 4.1% lower |
| State latency p95 | 43.951 ms | 42.169 ms | 4.1% lower |
| State latency maximum | 182.315 ms | 139.169 ms | 23.7% lower in this sample |
| Poll interval p95 | 131.060 ms | 133.109 ms | No material change |
| Poll interval maximum | 263.030 ms | 240.485 ms | 8.6% lower in this sample |
| Mean state payload | 18,086 B | 18,084 B | Unchanged full snapshot |
| Response-body bandwidth | 164.816 KiB/s | 164.617 KiB/s | Unchanged full snapshot |
| CPU mean, API + UI | 42.55% | 42.93% | Unchanged backend-dominated cost |
| CPU p95, API + UI | 48.0% | 48.8% | Unchanged backend-dominated cost |
| Source interval p50 | 110 ms | 110 ms | State still exposes about 10 Hz |
| Visible pose-step p95 | 0.0228 m | 0.0234 m | Raw poll-step size unchanged |

RSS is not compared: the service restart concurrently materialized retained evidence
archives and left the process cache materially warmer than the baseline.

The lack of a CPU reduction is expected. The completed fixes remove browser/GPU churn
and distribute movement across animation frames; they do not change the simulator's
100 Hz evidence production or the API's full-state response construction.

### Rendered one-drone mission after the fix

Two consecutive one-second windows during the uploaded mission reported:

| Metric | Window 1 | Window 2 |
|---|---:|---:|
| Render FPS | 120.0 | 120.5 |
| Maximum frame | 10.4 ms | 10.1 ms |
| Frames over 50 ms | 0 | 0 |
| Three.js geometries | 46 | 46 |
| JS heap | 16.3 MiB | 13.8 MiB |
| Display health | CURRENT | CURRENT |

The scene remained visible while the uploaded mission ran even though a campaign case
was still docked.

### Two-drone snapshot after the fix

| Metric | Before capture | After capture |
|---|---:|---:|
| Render FPS | 122.0 | 121.5 |
| Maximum frame | 10.4 ms | 10.2 ms |
| Frames over 50 ms | 0 | 0 |
| Three.js geometries | 65 | 65 |
| JS heap | 24.9 MiB | 21.0 MiB |

Snapshot-specific timings were 10.0 ms until the live view was restored, 93.0 ms
until image encoding completed, and 103.0 ms including upload. Encoding remains
asynchronous through `HTMLCanvasElement.toBlob`:

- https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/toBlob

There is no trustworthy pre-fix snapshot number because instrumentation was added with
the fix. The structural regression test verifies object reuse, and the post-fix browser
gate verifies no geometry growth or long frame during capture.

### Three-vehicle isolated load gate

Decision: `PASS_SOFTWARE_ONLY`.

| Metric | Result |
|---|---:|
| State API p95 | 1.847 ms |
| State payload | 30,595 B |
| Replay API p95 | 3.640 ms |
| Replay payload | 383,580 B |
| Storage query p95 | 13.047 ms |
| Total runtime | 11.861 s |
| Remaining fleet/mission/telemetry tasks | 0 / 0 / 0 |

This gate is strong for isolated API and cleanup behavior, but it does not render ten
or more drones in a real browser and therefore is not a fleet-scale smoothness gate.

### Startup evidence backfill observation

Publishing the production UI restarted the service against the existing 1.07 GB
evidence database. Its automatic background backfill used approximately 96-98% of one
CPU core, reached a sampled physical footprint of about 1.5 GB, and took roughly one
minute to settle. It materialized 24 retained archive folders totaling about 1.4 GB.
Although the server remained responsive, this work directly competes with simulation,
state serialization, and browser requests and is a credible source of startup stutter.

After the incremental backfill fix, the same database and archive set reported zero
executions requiring materialization in 0.22 seconds with 49.6 MB maximum RSS. A real
production service restart became healthy after approximately one second; the newest
manifest modification time did not change, and twelve post-start samples placed the API
at 0.1-0.2% CPU and about 88 MB RSS. This removes normal-restart contention. The
first migration of a genuinely missing legacy archive still needs the remaining worker
isolation and maintenance-budget tasks in PERF-WP-05.

The uploaded-Python probe after that restart also succeeded in 16.276 seconds. Its
state request p95 was 36.514 ms, maximum latency was 85.467 ms, and response-body
traffic was 122.007 KiB/s. API plus UI CPU p95 was 53.1%; this remains dominated by
the intentionally unchanged simulator/evidence path described in PERF-WP-03.

## Prioritized causes

| Priority | Cause | Evidence | State |
|---|---|---|---|
| P0 | Dynamic Three.js scene rebuilt and disposed at 10 Hz | Source inspection; object-reuse regression | Fixed |
| P0 | Buffered target advanced only on poll arrival | Source inspection; continuous source-clock test | Fixed |
| P0 | Snapshot built/disposed a second scene on the live renderer | Source inspection; stable geometry and 10 ms blocking gate | Fixed |
| P0 | Docked campaign could hide an uploaded run as `NO DATA` | Reproduced in browser; corrected condition | Fixed |
| P1 | Three browser timing POSTs per vehicle per state update | About 30 POST/s/drone at 10 Hz | Fixed to campaign-only, sampled 1 Hz |
| P1 | Simulator creates rich telemetry/evidence at 100 Hz while UI observes about 10 Hz | Process profile and source cadence | Open |
| P1 | Full `/state` snapshot polling | About 18.1 kB/request and 164.6 KiB/s/client for one drone | Open |
| P1 | Startup backfill loads and rewrites large retained evidence | 96-98% CPU, 1.5 GB footprint, about one minute | Fixed for complete archives; worker isolation remains open |
| P2 | Trace payload and draw calls scale per vehicle | 65 geometries for the two-drone snapshot case | Open for 10+ drones |
| P2 | Multiple UI polling owners can overlap across runtime modes | Source inspection | Open |

## Work packages

### PERF-WP-01 — Presentation hot path

Status: implemented in this change.

Tasks:

1. Replace destructive dynamic-scene synchronization with keyed upsert/removal.
2. Grow line-position buffers geometrically and update them with dynamic usage.
3. Retain direct motion-object and follower references for the animation loop.
4. Advance buffered source time per animation frame with a bounded stale freeze.
5. Remove campaign-only diagnostic traffic from normal missions and throttle it.
6. Correct the campaign-dock visibility condition.

Exit criteria:

- stable geometry count during a continuous mission;
- zero frames above 50 ms in two consecutive one-second windows;
- current display health during normal realtime motion;
- regression tests prove vehicle object identity is retained; and
- uploaded Python missions remain visible with a campaign selected.

### PERF-WP-02 — Snapshot critical path

Status: implemented first phase.

Tasks:

1. Keep plan, trace, and truth layers mounted.
2. Temporarily change only evidence-layer visibility and camera for capture.
3. Restore the live view immediately after the synchronous canvas copy.
4. Record blocking, encoding, total, long-frame, and geometry metrics.
5. If future 10+ drone snapshots exceed the frame budget, evaluate an
   `OffscreenCanvas`/worker encoder; do not add that complexity before the gate fails.

Exit criteria:

- no second scene construction in the capture path;
- no geometry-count increase across capture;
- live-view restoration within one 60 Hz frame (16.7 ms target); and
- no frame above 50 ms in the surrounding measurement window.

`OffscreenCanvas` is the standards-based follow-up option for moving canvas work away
from the main thread:

- https://developer.mozilla.org/en-US/docs/Web/API/OffscreenCanvas

### PERF-WP-03 — Simulator/evidence rate separation

Status: proposed; highest backend priority.

Tasks:

1. Measure cost separately for physics integration, telemetry model construction,
   evidence recording, safety supervision, and presentation coalescing.
2. Preserve qualified physics and raw-evidence cadence, but construct the operator
   presentation envelope only at its configured rate.
3. Avoid validating/serializing sensor structures that no active evidence or operator
   consumer needs on that cycle.
4. Evaluate a worker process for evidence export/evaluation so Python GC and Pydantic
   construction cannot pause the API event loop.
5. Add one-, three-, and ten-drone CPU/RSS profiles.

Exit criteria:

- raw evidence and qualification hashes remain unchanged;
- one-drone realtime API + UI CPU p95 is materially below the current 48% baseline;
- no source-clock gap or watchdog regression; and
- state request p95 remains below the configured operator budget while evidence is
  being written.

### PERF-WP-04 — Compact streaming presentation channel

Status: proposed.

Tasks:

1. Keep the full state endpoint for initial attach, recovery, and explicit refresh.
2. Add one server-owned SSE or WebSocket stream for compact vehicle deltas at the
   presentation rate.
3. Collapse the separate run/campaign/execution poll owners behind one subscription.
4. Batch browser timing records into at most one request per second.
5. Add reconnect sequence/epoch handling and bounded backpressure.

Exit criteria:

- one long-lived presentation connection per dashboard;
- no routine 10 Hz full-state polling;
- reconnect reconstructs the same authoritative state without a visual jump;
- bounded client queue with explicit delayed health; and
- measured one-drone presentation traffic materially below 164.6 KiB/s.

### PERF-WP-05 — Evidence backfill and archive isolation

Status: first phase implemented; worker isolation and maintenance budgets remain open.

Tasks:

1. Build a manifest/index query that identifies only missing or stale archives before
   decoding event JSON. **Implemented:** schema, completion timestamp, filenames, and
   recorded file sizes are checked without reading or hashing large payloads.
2. Move backfill/evaluation/export into a separately budgeted worker process.
3. Start only after API readiness and an idle grace period; pause while a mission or
   campaign is active.
4. Bound work per batch and expose progress, CPU time, bytes read/written, and failure.
5. Add an archive disk quota and an operator-visible estimate before expansion.
6. Do not make runtime shutdown wait indefinitely for a large maintenance batch.

Exit criteria:

- dashboard/API ready within 3 seconds on the retained qualification database;
- idle maintenance cannot consume a full API core;
- peak API memory increase stays within a defined maintenance budget;
- active-mission request/frame p95 is unchanged with maintenance enabled; and
- rerunning against a complete archive performs no event decode or file rewrite.

The final criterion now has regression coverage. Startup also schedules the maintenance
task only after the evidence recorder and live telemetry consumers have started. A
missing or size-mismatched artifact is still rebuilt automatically; a complete archive
takes the manifest-only fast path. Process isolation, idle pausing, resource budgets,
and bounded shutdown remain separate follow-up work because they affect the first-ever
migration of legacy database-only executions rather than normal restarts.

### PERF-WP-06 — Fleet-scale rendered qualification

Status: proposed.

Tasks:

1. Add committed uploaded-Python probes for 1, 3, 10, and 25 continuously moving
   drones with deterministic routes and bounded duration.
2. Record API/UI CPU, RSS, traffic, source cadence, FPS, p95/max frame time, long
   frames, draw calls, geometries, and snapshot blocking time.
3. Run with trace/truth/ranges independently and together to attribute cost.
4. Add trace decimation/level-of-detail with a bounded spatial error contract.
5. Use instanced drone/rotor geometry if draw calls become the limiting factor.
6. Store result JSON as a qualification artifact and compare it in CI.

Exit criteria:

- explicit pass/fail budgets for each fleet size;
- no unbounded heap, geometry, trace, or queued-sample growth;
- 30 FPS minimum and no frame above the configured 100 ms hard limit at the supported
  fleet size; and
- snapshots and recovery attach remain within their own budgets during the load run.

## Verification completed

- TypeScript typecheck: passed.
- ESLint for the changed UI files: passed.
- Focused playback and renderer tests: 27 passed.
- UI production build: passed.
- Uploaded Python mission: succeeded repeatedly.
- Two-drone campaign with snapshot: succeeded.
- Three-vehicle software load: `PASS_SOFTWARE_ONLY`.
- Ruff and Python bytecode compilation for the new probe/profiler: passed.
- Incremental archive regression: complete archive skipped; missing bundle rebuilt.
- Complete 1.0 GB database backfill fast path: 0.22 seconds, zero rewrites.
- Production restart: healthy, unchanged manifest timestamp, API settled at 0.1-0.2%
  CPU and about 88 MB RSS.
- Post-restart uploaded-Python motion probe: succeeded.

The full UI unit suite currently has one unrelated expectation failure in the existing
dirty API-adapter work: the adapter returns `missionExecutionId`, while that older test
expectation omits it. The performance-specific tests are green, and that unrelated
change was not modified here.

A broad Python run was stopped after 2 minutes 52 seconds with 19 passes and five
failures, all in the existing campaign work: campaign validation calls
`Region3D.contains`, but that method is currently absent. The focused observability and
API mission/replay/uploaded-execution set completed with 55 passes; the campaign model
failure is independent of the performance and archive-backfill paths.
