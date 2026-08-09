# Mission execution bundle and evaluation v1

| Field | Value |
|---|---|
| Bundle contract | `mission-execution-bundle-v1` |
| Evaluation contract | `mission-execution-evaluation-v1` |
| Evaluator | `deterministic-mission-execution-evaluator@1.0.0` |
| Group identity | One immutable `mission_execution_id` |
| Fleet time basis | `recorded_at_utc` |
| Runtime authority | None; evaluation is read-only |
| Physical-flight qualification | None |

## Persisted execution boundary

Every materialized mission folder contains the existing combined telemetry CSV plus:

```text
<mission>_<execution>_execution-bundle-v1.json
<mission>_<execution>_evaluation-v1.json
```

The bundle contains the accepted mission plan, deployment, backend binding, role-to-
vehicle assignments, terminal execution/fleet result, fleet events, child run
snapshots/results, every checksum-verified evidence event, optional operator
annotations, and the derived evaluation. Estimated state and simulator truth remain
separate fields. Neither channel is rewritten or substituted for the other.

Uploaded mission execution records the accepted context before launch and refreshes it
with the terminal execution result after the evidence recorder is flushed. A terminal
status exposed through the mission API therefore waits for the grouped evidence
refresh. Admission failures before a child run exists remain execution failures but do
not invent a mission-run bundle.

## Determinism and identity

Runs are ordered by vehicle and run identity. Events are ordered by recorded UTC,
vehicle, child run, sequence, and event identity. JSON keys are sorted, no export time
is inserted, and the report and bundle each carry a canonical payload SHA-256.
Repeating evaluation or materialization over unchanged committed evidence produces the
same report identity and byte-identical JSON artifacts.

`recorded_at_utc` is the fleet alignment basis because child simulation clocks may
advance independently. Pairwise separation only compares samples within the declared
0.25 s alignment tolerance. Source, simulation, and replay timestamps remain present
as evidence and are never relabeled as the shared fleet clock.

## Evidence completeness

The report names every present and missing evidence class. A complete report requires:

- accepted plan, deployment, binding, and terminal execution result;
- terminal child results with run provenance;
- telemetry, commands, and acknowledgements for every participating vehicle; and
- fleet events for a multi-vehicle execution.

An incomplete report is still deterministic and downloadable. `INCOMPLETE` describes
the evidence boundary, not mission success or failure. Operator annotations are
optional and cannot turn incomplete evidence into complete evidence.

## Metrics

Per-vehicle metrics include telemetry/command/acknowledgement counts, execution time,
estimate and truth path length, planned-target error, estimate-versus-truth RMS and
maximum error, final/peak speed, peak acceleration and jerk, unintended stop count,
declared holds, battery use, flight-volume margin, planned-versus-observed duration,
terminal state, inherited faults, and newly raised faults.

Fleet metrics include aligned estimate/truth minimum separation and pair identity,
warning/critical sample counts, configured warning/critical thresholds, planned
minimum separation, and plan-versus-execution duration delta. The concise summary is a
derived view of these typed fields; it is not a separate source of truth.

A telemetry fault present in the first run sample is `inherited_faults`. A fault first
seen later, or raised by a fault evidence event, is `new_faults` unless it was already
present at run start. This prevents stale simulator state from being reported as a new
fault caused by the current mission.

## Operator API

| Method and path | Result |
|---|---|
| `GET /api/v1/run-files/{mission_execution_id}/evaluation` | Current typed evaluation |
| `GET /api/v1/run-files/{mission_execution_id}/evaluation.json` | Persisted evaluation bytes with content/report hashes |
| `GET /api/v1/run-files/{mission_execution_id}/execution-bundle.json` | Persisted complete grouped evidence bundle |
| `POST /api/v1/run-files/{mission_execution_id}/annotations` | Append one authenticated note and regenerate evaluation/bundle |

Notes are limited to 2,000 characters, retain author and UTC identity, and are
append-only. They supplement measured evidence and cannot waive a hard gate, change a
safety limit, or grant command authority.

## Claim boundary

This contract measures recorded behavior. It does not change trajectories,
coordination, controller gains, mission success semantics, or safety thresholds. It
does not qualify Isaac, a digital twin, physical flight, landing contact, or model
accuracy.
