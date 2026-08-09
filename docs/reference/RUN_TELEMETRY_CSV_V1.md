# Run telemetry CSV v1

| Field | Value |
|---|---|
| Contract ID | `run-telemetry-v1` |
| File role | Persisted, downloadable tabular view of one mission execution's committed telemetry evidence |
| Row identity | One `EvidenceKind.TELEMETRY` event |
| Canonical source | Checksum-verified `EvidenceStore`; CSV is derived, not authoritative |
| Media type | `text/csv; charset=utf-8` |
| Encoding | UTF-8 without BOM |
| Record format | RFC 4180 comma-separated records with CRLF line endings |
| Physical-flight qualification | None |

## Persistent mission archive

Terminal runs are stored by mission execution, not as a flat file list:

```text
run-files/
└── 20260808T130818Z_crossing_route_separation_<mission-execution-id>/
    ├── manifest.json
    └── crossing-route-separation_<mission-execution-id>_telemetry-v1.csv
```

The folder token combines the earliest member start time, mission name, and opaque
mission execution ID. Every mission has exactly one CSV, independent of how many
vehicles participated. Each row retains its child `run_id` and `vehicle_id`, so the
combined file does not erase per-vehicle identity. The API accepts only the mission
execution ID; it never accepts a client-supplied path. CSV and manifest writes use a
temporary sibling, `fsync`, and atomic rename, so partial artifacts are not listed.

`manifest.json` records `mission_execution_id`, mission ID/name, start/completion UTC,
aggregate status, vehicle IDs, aggregate telemetry-row count, and one `artifact`.
That artifact records every child run ID and vehicle ID plus the filename, media type,
schema version, byte size, total telemetry-row count, and SHA-256. If any member is
still being recorded, the mission artifact remains unavailable until all members are
terminal and the complete mission manifest is rewritten.

Retention keeps the latest 100 completed mission folders by default. Incomplete
missions are never selected for deletion. SQLite completed-run retention uses the same
mission execution grouping. Operators can configure both values with:

```yaml
run_files:
  directory: run-files
  keep_latest_missions: 100
```

## Filename

The canonical persisted filename inside a mission folder is:

```text
<mission-name>_<mission-execution-id>_telemetry-v1.csv
```

Segments are lower-case and replace characters outside `[a-z0-9._-]` with `-`.
Every complete child run and vehicle identity remains in the data rows and manifest.
For example:
`crossing-route-separation_execution-01j4run8a2cf_telemetry-v1.csv`.

## Serialization rules

1. The header is always present and its order is fixed by this document.
2. Event sequences must be unique and ascending within each child run. Combined rows
   are ordered by recorded UTC time, vehicle ID, run ID, event sequence, and event ID,
   making interleaved multi-drone telemetry deterministic.
3. All numeric values are finite base-10 decimals using `.` and no thousands separator.
   NaN and infinity are never emitted.
4. Boolean values are exactly `true` or `false`.
5. Unavailable optional values are empty fields. Zero is never used as a replacement
   for unavailable data.
6. UTC timestamps use ISO 8601 with a trailing `Z`. Monotonic, simulation, and replay
   times remain numeric seconds and are not relabeled as wall time.
7. All physical values use the SI unit encoded in the column name. Percent values are
   in the inclusive range `0..100`; angles are radians.
8. Text is escaped with the standard CSV quoting rules. `faults_json` is a compact JSON
   array inside one quoted cell; its order is preserved.
9. Ground-truth columns remain blank when ground truth was not recorded. A model value
   must never be presented as measured reality.
10. Exporting the same committed terminal mission twice with the same contract version
    produces byte-identical content and the same content SHA-256/ETag.

## Fixed column order

The groups below are concatenated in this exact order. Pattern expansions use the
listed direction or motor order, never alphabetical or implementation-defined order.

### Identity and clocks

| # | Column | Meaning |
|---:|---|---|
| 1 | `csv_schema_version` | Constant integer `1` |
| 2 | `run_id` | Full immutable run identifier |
| 3 | `mission_id` | Mission identifier recorded for the run |
| 4 | `mission_version` | Mission version recorded for the run |
| 5 | `configuration_sha256` | Run configuration hash |
| 6 | `event_id` | Full evidence-event identifier |
| 7 | `event_sequence` | Evidence sequence within the run |
| 8 | `vehicle_id` | Vehicle identity carried by the event |
| 9 | `operating_mode` | Recorded `SIM`, `LIVE`, `SHADOW`, or `REPLAY` mode |
| 10 | `source` | Recorded evidence source identifier |
| 11 | `recorded_at_utc` | Evidence record time in UTC |
| 12 | `source_timestamp_s` | Evidence source time |
| 13 | `received_timestamp_s` | Evidence receive time |
| 14 | `telemetry_sequence` | Sequence from the telemetry envelope |
| 15 | `simulation_timestamp_s` | Simulation time, blank if unavailable |
| 16 | `replay_timestamp_s` | Replay time, blank if unavailable |
| 17 | `source_clock_id` | Source clock identity |
| 18 | `source_clock_epoch` | Source clock epoch |
| 19 | `frame` | Recorded spatial frame |

### State, localization, and motion

| Columns, in order | Meaning |
|---|---|
| `state`, `armed`, `flying` | Recorded vehicle lifecycle state |
| `position_is_estimate`, `localization_source`, `localization_quality_percent` | Localization classification and quality |
| `position_x_m`, `position_y_m`, `position_z_m` | Estimated/observed position in `frame` |
| `ground_truth_x_m`, `ground_truth_y_m`, `ground_truth_z_m` | Optional explicitly modeled/measured ground truth |
| `velocity_x_m_s`, `velocity_y_m_s`, `velocity_z_m_s` | Velocity in `frame` |
| `roll_rad`, `pitch_rad`, `yaw_rad` | Euler attitude |
| `quaternion_w`, `quaternion_x`, `quaternion_y`, `quaternion_z` | Hamilton quaternion in explicit `w,x,y,z` order |

### Power and transport

| Columns, in order | Meaning |
|---|---|
| `battery_percent` | Remaining charge estimate |
| `battery_open_circuit_voltage_v`, `battery_voltage_v`, `battery_current_a` | Battery electrical values |
| `battery_cutoff_active`, `battery_cutoff_reason`, `powertrain_current_limited` | Powertrain protection state |
| `transport_kind`, `transport_source_class` | Physical, modeled, or replay transport attribution |
| `transport_delivery_quality_percent`, `transport_latency_ms`, `transport_packet_loss_percent` | Optional transport metrics |

### IMU, estimator, and flow

| Columns, in order | Meaning |
|---|---|
| `imu_acceleration_x_m_s2`, `imu_acceleration_y_m_s2`, `imu_acceleration_z_m_s2` | Body-frame acceleration |
| `imu_angular_velocity_x_rad_s`, `imu_angular_velocity_y_rad_s`, `imu_angular_velocity_z_rad_s` | Body-frame angular velocity |
| `estimator_variance_x_m2`, `estimator_variance_y_m2`, `estimator_variance_z_m2` | Position variance |
| `estimator_converged`, `estimator_quality_metric_id` | Estimator status |
| `flow_velocity_x_m_s`, `flow_velocity_y_m_s`, `flow_velocity_z_m_s` | Body-frame flow velocity |
| `flow_ground_distance_m`, `flow_quality_percent`, `flow_status`, `flow_source_timestamp_s` | Flow range, quality, state, and source time |

### Range sensors

The next columns are `range_max_m`, `range_source_timestamp_s`, followed by
`range_<direction>_m`, `range_<direction>_status` for each direction in this fixed
order:

```text
front, back, left, right, up, down
```

### Motors and faults

The next columns are `motor_model_id` and `motor_model_version`, followed by these
fields for each motor in the fixed order `m1`, `m2`, `m3`, `m4`:

```text
motor_<id>_command_percent
motor_<id>_requested_thrust_n
motor_<id>_applied_pwm_percent
motor_<id>_voltage_v
motor_<id>_thrust_n
motor_<id>_available_thrust_n
motor_<id>_current_a
motor_<id>_saturated
motor_<id>_health_percent
motor_<id>_faulted
```

The final column is `faults_json`.

## Download API metadata

`GET /api/v1/run-files` lists the newest persisted missions. Each mission advertises
one ID-only download URL:

```text
GET /api/v1/run-files/{mission_execution_id}/telemetry.csv
```

`GET /api/v1/runs/{run_id}/telemetry.csv` and the former mission/run-ID route remain as
compatibility routes. Both resolve the child run to its mission and serve the same
combined persisted bytes; neither creates another CSV.

The download routes return a terminal mission file with:

| Header | Required value |
|---|---|
| `Content-Type` | `text/csv; charset=utf-8` |
| `Content-Disposition` | `attachment; filename="<backend filename>"` |
| `ETag` | Quoted SHA-256 identity of the CSV bytes |
| `X-CrazySwarm-CSV-Schema` | `run-telemetry-v1` |
| `X-CrazySwarm-Row-Count` | Number of telemetry rows excluding the header |
| `X-CrazySwarm-Content-SHA256` | Lower-case hexadecimal SHA-256 of the response bytes |

The authenticated mission-list response advertises the same filename and URL. A
mission with a failed or aborted child is still evidence and remains downloadable. A
terminal mission with no telemetry produces the exact header and zero data rows. A
mission still being recorded is listed without a persisted download URL; the
compatibility run-ID endpoint returns `409` for a non-final child.

## Relationship to grouped execution evidence

The CSV is optimized for plotting and spreadsheet analysis. It intentionally contains
telemetry rows only. The same mission folder now also contains the complete deterministic
[`mission-execution-bundle-v1`](MISSION_EXECUTION_EVALUATION_V1.md), including commands,
acknowledgements, safety transitions, plan/deployment context, fleet/child results, and
operator annotations, plus its derived evaluation. Existing diagnostic ZIP/NDJSON and
command-free replay remain compatible. The UI must not describe CSV download alone as a
complete evidence backup.
