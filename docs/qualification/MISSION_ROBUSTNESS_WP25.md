# Mission robustness and handoff WP-25 qualification

| Field | Value |
|---|---|
| Package | `WP-25` |
| Status | `COMPLETE` |
| Date | 2026-08-09 |
| Contract | [`../reference/MISSION_ROBUSTNESS_MATRIX_V1.md`](../reference/MISSION_ROBUSTNESS_MATRIX_V1.md) |
| Backend claim | Fast Sim |
| Live Isaac / physical status | `NOT_RUN` / `NOT_RUN` |

## Matrix result

The default manifest contains 16 immutable cells across seven profiles and has SHA-256
`d4ca4264d3b1b23adaf69cd29b88878039651fc05c2cb4d0b1f4de5c91124598`.
All 16 cells executed through normal Play, produced complete persisted evaluation
files, matched their live evaluator response, and passed in 108.80 seconds.

The evidence-bound qualification from that run passed at 100% for every profile, had
no missing cell, and reproduced every repeated safe-failure outcome. Its report hash
was `2f4ed1d7bcfb1e029695f8114c8fa2c8d6c2c3d3d87a687364c38be5206e4659`.
The accelerated/real-time pair preserved all declared invariants while retaining
elapsed/tracking fields as model-sensitive.

Across the retained evaluator files:

- all 16 reports are `COMPLETE` with complete evidence;
- warning and critical sample totals are both zero;
- the worst successful goal-capture margin is approximately 0.0616 m;
- boundary margin is never negative (ground contact reaches the declared z=0 border);
- the recovery crossing's minimum truth separation is approximately 1.4622 m, or
  0.7122 m above its warning threshold; and
- the four observation-loss, two timeout, and two fleet-recovery cells all terminate
  safely with their declared reproducible failure/recovery class.

## Timeout and evidence defects found during qualification

An initial whole-clock slowdown caused command timeout but also slowed recovery, so it
was rejected as unsafe. The accepted profile uses a trajectory-only stall that keeps
telemetry fresh; duration-aware timeout then selects the normal supervised recovery.

The first matrix run also exposed a single-role durability race: a terminal child
result could become visible after the final context update but just before refreshed
materialization. The API now awaits the owning top-level execution task at the terminal
read boundary. The rerun verifies downloaded and live evaluations are identical for
all 16 cells.

## Handoff result

The passing qualification produced a three-case backend-neutral handoff for endpoint
accuracy, staged crossing/recovery, and observation-loss handling. The evidence-bound
bundle hash for the qualification run was
`e763f87dc4bac99ab5f8d5ecc3139089f47626198bb2a54110ac8e82705121ad`.
It includes required signals, hard thresholds, model-sensitive expectations, and stop
conditions. It does not select, install, launch, or authorize another backend.

## Regression evidence

- Four contract tests cover deterministic generation, complete promotion/handoff,
  hard-failure non-averaging, and repeated-outcome rejection.
- One 16-cell API qualification test executes every declared profile and validates
  both live and persisted evaluator artifacts.
- The simulator fault-family repetition gate and evaluator/unified-execution checks
  pass with the new trajectory-timeout profile.
- The WP-25 focused set passes 13 tests, including 100-seed fault-family repetition.
- Final whole-repository coverage passes 529 tests with one intentional live-Isaac
  host skip: 496 passing tests plus the skip in the broad shard, 19 coordination
  tests, and 14 persistent-handover tests. The telemetry-heavy coordination harness
  explicitly collects closed runtime cycles between cases, outside active mission
  windows, preventing deferred GC from creating a false realtime freshness gap.
- Repository Ruff and strict MyPy pass over 193 source/test files. Generated API/client
  parity, UI lint/typecheck, 80 unit tests, the production build, three rendered-HTML
  checks, and a zero-vulnerability npm audit also pass.

## Claim boundary

The profiles are bounded Fast Sim experiments, not measured real-world probability
distributions. WP-25 does not qualify physical noise, RF, contact, endurance, Isaac,
digital-twin equivalence, or physical flight. Higher-fidelity execution remains a
separate explicitly authorized future work package.
