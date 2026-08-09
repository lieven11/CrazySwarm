# Run-history CSV and control-layout WP-18 qualification

| Field | Value |
|---|---|
| Package | `WP-18` |
| Status | `COMPLETE` |
| Contract | [`../reference/RUN_TELEMETRY_CSV_V1.md`](../reference/RUN_TELEMETRY_CSV_V1.md) |
| Qualification date | 2026-08-08 |
| Default backend | `FAST_SIM` |
| Physical flight | `NOT_RUN` |
| Live Isaac | `NOT_RUN` |
| Digital twin | `NOT_RUN` |

## Qualified boundary

The observability layer now persists one deterministic RFC 4180 CSV for every terminal
mission from all checksum-verified telemetry events. A mission execution owns one
atomic folder, one manifest, and exactly one combined CSV regardless of vehicle count.
Each row retains its child run and vehicle identity. Successful, failed, and aborted
results are retained. The fixed v1 schema
contains 128 identity, clock, state, motion, power, transport, IMU, estimator, flow,
range, motor, and fault columns. Optional unavailable values remain blank, including
powertrain fields absent from legacy telemetry. Booleans are lower-case, physical
fields are SI-labeled, and the same committed mission exports byte-identically.

`GET /api/v1/run-files` returns one artifact per mission.
`GET /api/v1/run-files/{mission_execution_id}/telemetry.csv` accepts an ID, never a
filesystem path, and serves the already-persisted file with attachment, schema,
row-count, ETag, and content-SHA metadata. Older run-addressed endpoints remain
compatible and resolve to the same combined bytes. Unknown IDs return `404`; an active
recording is listed without a download URL, and the compatibility run-ID endpoint
returns `409`. Failed and aborted terminal missions remain downloadable. A terminal
zero-sample mission contains the exact header without invented data. Existing
diagnostic ZIP and command-free replay behavior remains intact.

The **Run files** disclosure is now a separate bottom-left control directly after the
mission/Play capsule. It loads missions newest-first and shows each as one compact,
non-expandable row: aggregate status, mission name, an icon-only download control, and
total sample count. Ready filenames remain available to accessibility APIs and the
browser download attribute. Downloading does not open replay, select a vehicle, or
request command authority. Reposition and Recharge remain in the right-side
quick-action cluster next to Flight information. Narrow layouts stack controls without
horizontal overflow and hide them while the full-height telemetry panel is open.

The archive defaults to `run-files/` and retains the latest 100 completed mission
executions, not 100 individual vehicle files. Incomplete missions are never deleted.
The same mission-group policy prunes completed SQLite runs and their events. Startup
backfill materializes retained legacy runs in a background thread. Every CSV and
manifest is written to a temporary sibling, flushed, and atomically renamed.

## Evidence

| Gate | Result |
|---|---|
| Full Python suite | `500 passed, 1 skipped` |
| Intentional skip | Compatible live-Isaac host variables unavailable |
| Ruff | Passed |
| Strict MyPy | Passed over 178 source/test files |
| Focused storage/API contract | `26 passed` |
| UI TypeScript | Passed |
| UI ESLint | Passed |
| UI unit tests | `80 passed` |
| UI production build | Passed |
| Rendered HTML | `3 passed` |
| OpenAPI and generated TypeScript client | Regenerated and passed parity checks |
| Repository whitespace gate | Passed |
| Current-database `/runs?limit=20` through UI proxy | HTTP 200 in `0.050935 s` after index creation |
| Current-database `/run-files?limit=100` through UI proxy | HTTP 200 in `0.025597 s` |
| 80-request concurrent proxy stress | 20 requests each to run files, run list, state, and health returned 200; maximum latency `0.7068 s`; API PID remained stable |
| Multi-drone persistence contract | Focused storage/API gate proves one mission folder, one manifest, one CSV containing both child run IDs and both vehicle IDs |
| Current clean archive | Zero missions and zero CSVs after the operator-authorized reset; the next completed mission starts the new one-file sequence |
| Historical backfill checkpoint | Before the operator reset and one-file consolidation: 154 runs in 100 completed groups plus one protected incomplete group |
| Recovery audit | 191,066 unique checksum-valid carved events accepted, 74,151 missing events restored with zero ID/sequence conflicts, and the pre-restoration SQLite backup retained under `.cache/crazyswarm/recovery/` |

The historical counts above describe the pre-consolidation qualification checkpoint,
not the current archive shape. After that gate, the operator explicitly authorized
clearing all non-valuable mission-run data. The current run list, run-file API, SQLite
run table, and `run-files/` archive therefore start at zero; non-run system evidence
and the recovery snapshot were not deleted.

The header-only canonical fixture is the UTF-8 v1 header plus CRLF. It has 128 columns
and SHA-256:

```text
3ab3700c0b8a159b8d7cc1f3393027806ff7ce634d41a90d25767f935de9dfa1
```

A real Fast Sim export was additionally opened through the bundled spreadsheet
runtime: 425 telemetry rows imported into the fixed columns, representative identity
and clock cells matched the source CSV, and the spreadsheet error scan found no
formula/error cells.

## Preserved boundaries and limitations

- The CSV is a plotting/spreadsheet convenience view, not the complete evidence
  backup. Commands, acknowledgements, safety transitions, operator actions, mission
  events, and typed results remain in ZIP/NDJSON and replay.
- Persistence is local filesystem storage. WP-18 does not add cloud replication,
  streaming pagination, bulk archive download, or user-triggered deletion.
- Reposition and Recharge retain the existing simulation-only, stopped, disarmed,
  disconnected, selected-target, and busy-state gates.
- No simulation value is relabeled as measured reality, and no unavailable field is
  replaced with a plausible default.
- This qualification makes no live-Isaac, physical-aircraft, docking, endurance, RF,
  sensor-accuracy, or flightworthiness claim.
