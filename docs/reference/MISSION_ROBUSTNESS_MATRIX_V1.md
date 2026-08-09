# Mission robustness matrix contract v1

| Field | Value |
|---|---|
| Contract | `mission-robustness-matrix-v1` |
| Version | `1.0.0` |
| Nominal backend | Fast Sim |
| Default matrix size | 16 immutable cells |
| Higher-fidelity execution authority | None |

## Purpose

The matrix turns retained mission execution into a repeatable development loop. A cell
binds one accepted lower-level case to a profile, seed, clock mode, repetition, Fast
Sim model version, simulation configuration hash, safety configuration hash, and cell
hash. Results are accepted only from the existing deterministic mission-execution
evaluator plus a terminal outcome record.

The default selected cases are endpoint/landing accuracy, staged two-drone crossing,
and required-position observation loss. The matrix can grow by adding bounded cells;
it does not require a separate handwritten mission for every parameter combination.

## Declared profiles

| Profile | Cells | Variation or fault | Expected result |
|---|---:|---|---|
| `nominal-multi-seed` | 2 | Seeds 109 and 811 | Success |
| `bounded-sensor-noise` | 2 | 0.006 m position/range noise; 0.004 m/√s flow drift | Success |
| `bounded-transport-latency` | 2 | 0.05 s command, 0.02 s acknowledgement, 0.01 s estimator latency | Success |
| `bounded-clock-rate` | 2 | 1.02 clock-rate scale in accelerated and real-time modes | Success with invariant equivalence |
| `required-observation-loss` | 4 | Localization loss, two seeds, two repetitions | Reproducible safe failure |
| `bounded-execution-timeout` | 2 | Trajectory-only stall with a tightened 0.5 s base command timeout | Reproducible timeout and recovery |
| `bounded-abort-and-land-recovery` | 2 | One crossing role loses localization | Reproducible bounded fleet degradation/recovery |

`TRAJECTORY_TIMEOUT` is a simulation fault, not a production behavior. It stalls only
the trajectory completion while continuing fresh telemetry; the Safety Supervisor
therefore exercises its duration-aware command timeout and retains an independent
abort-and-land path. A whole-clock slowdown that also disables recovery does not count
as a safe timeout qualification.

## Per-run assessment

Every cell requires complete persisted evidence, matching execution identity,
preserved accepted-plan identity, zero critical samples, its declared warning and
margin thresholds, and a safe terminal state. Expected-success cells additionally
require success and goal capture where declared. Expected-failure cells require an
allowed reason and observed bounded recovery.

Profile summaries record expected/observed/passed counts, pass rate, worst boundary,
goal and separation margins, safe-failure count, and hard-failure count. Missing
evidence, identity loss, unsafe terminal state, critical separation, or boundary/goal
failure is a hard failure and cannot be hidden by an average pass rate.

Repeated profile cells must have the same normalized outcome hash. Accelerated and
real-time cells reconcile safety, plan identity, terminal, and evidence invariants.
Elapsed time, wall-clock duration, and tracking error remain explicitly
model-sensitive and need not be bit-identical.

## Persistence boundary

Once the mission-status API exposes a terminal single-role result, it waits for the
top-level execution task to finish the final context update and materialization. The
downloaded evaluation JSON must equal the live evaluation response. An older
incomplete file followed by a complete live recomputation is not acceptable evidence.

## Operator/developer loop

Generate the immutable matrix:

```bash
.venv/bin/python scripts/qualify_mission_robustness.py --output matrix.json
```

After executing cells, provide an evidence-map JSON object keyed by cell SHA-256. Each
value contains `evaluation` and `outcome` paths. Then qualify and emit a handoff:

```bash
.venv/bin/python scripts/qualify_mission_robustness.py \
  --evidence-map evidence-map.json \
  --output qualification.json \
  --handoff-output higher-fidelity-handoff.json
```

The handoff is emitted only for a complete passing matrix.

## Backend-neutral handoff

The handoff binds selected case/cell hashes, Fast Sim evaluator-report hashes,
required command/acknowledgement/timestamp/estimate/truth/setpoint/fault/separation/
goal/terminal signals, thresholds, model-sensitive expectations, and stop conditions.
It records Isaac and physical status as `NOT_RUN` and explicitly grants no execution
authority.
