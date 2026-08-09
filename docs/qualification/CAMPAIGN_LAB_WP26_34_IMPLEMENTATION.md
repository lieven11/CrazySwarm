# Campaign Lab WP-26 through WP-34 implementation

| Field | Value |
|---|---|
| Status | `IMPLEMENTED_AND_QUALIFIED` |
| Qualification date | 2026-08-09 |
| Default backend | Fast Sim |
| Executed development case | `SIM / three_drone_multi_conflict` |
| Physical flight authorized | No |
| Live Isaac executed | No |

## Delivered boundary

WP-26 through WP-34 are implemented as one bounded campaign pipeline:

- WP-26 adds source-clock mission analysis, timing traces, primary-cause localization,
  and explicit accelerated/realtime comparison tolerances.
- WP-27 defines immutable, hash-addressed campaign cases and keeps mutable lifecycle
  state in the persistent workspace.
- WP-28 creates ground-first joint schedules and retains their exact identity.
- WP-29 enumerates and validates timing, speed, horizontal, vertical, and combined
  conflict-resolution strategies against hard constraints before optimization.
- WP-30 generates smooth C2 trajectory sets and executes the retained source-time
  authority through the normal runtime and Safety Supervisor.
- WP-31 provides persistent selection, static validation, preview, execution,
  artifact import, review, approval, promotion, recommendation, and idempotency.
- WP-32 exposes that loop through the API and Control Center.
- WP-33 generates the progressive one-, two-, and three-drone catalog.
- WP-34 implements bounded goal replacement and atomic fleet replanning with authority,
  generation, acknowledgement, timeout, stale-update, and rollback checks.

Catalog discovery, filtering, recommendations, and static validation do not invoke the
executor. An existing definition-only workspace may safely absorb a regenerated case
identity by resetting that lifecycle entry. A changed identity with a run, review,
baseline, active selection, or promoted authority fails closed and preserves evidence.

## Clustered catalog

The filesystem and Campaign Lab use the same five clusters. The UI hierarchy is
`Simulation | Real -> cluster -> one | two | three drones -> family -> immutable case`.

| Cluster | Simulation | Real mirrors | Total | Qualification intent |
|---|---:|---:|---:|---|
| Basic flight and route following | 18 | 6 | 24 | Execution, tracking, smoothness, goals, boundaries, landing |
| Geometric conflict resolution | 39 | 10 | 49 | Separation through timing, speed, detours, or altitude |
| Constraints and optimization | 21 | 7 | 28 | Hard limits and lexicographic objective ordering |
| Coordination and allocation | 24 | 8 | 32 | Roles, ownership, priority, reserve selection, handover |
| Failure recovery and replanning | 25 | 4 | 29 | Rejection, atomic replacement, recovery, abort behavior |
| **Total** | **127** | **35** | **162** | |

Every case carries a plain-language purpose, behavior-under-test explanation, and
expected outcome. The panel no longer exposes the internal case hash or a raw expected
decision list. Fleet-size changes select a compatible case immediately, so displayed
drone count and difficulty cannot remain stale. Simulation and Real mirrors are
separate scopes; Real remains visibly `NOT_AUTHORIZED` and cannot be activated.

All 127 simulation definitions were discovered and bounded-planned: 127 `READY`, zero
blocked. This catalog-wide check was static and launched no missions.

## Selected-case execution evidence

The canonical three-drone case executed once in each declared mode through
`FastSimCampaignExecutor` and the retained application runtime.

| Metric | Accelerated | Operator realtime |
|---|---:|---:|
| Status | `SUCCEEDED` | `SUCCEEDED` |
| Telemetry rows | 6,276 | 6,057 |
| Minimum truth separation | 1.090391 m | 1.090391 m |
| Alpha / Beta / Gamma battery used | 3.783% / 3.936% / 4.090% | 3.783% / 3.936% / 4.090% |
| Alpha / Beta / Gamma airborne wait | 1.28 s / 1.31 s / 1.30 s | 1.28 s / 1.31 s / 1.30 s |
| Unintended stops | 0 / 0 / 0 | 0 / 0 / 0 |
| Maximum per-vehicle tracking RMS | 0.017444 m | 0.017397 m |

Each run retained `manifest.json`, `telemetry.csv`, `execution-bundle.json`,
`evaluation.json`, and `analysis.json`. Cross-mode comparison passed every gate:
minimum-separation difference 0 m, maximum source-clock target-error difference 0 s,
maximum truth-path difference 0.00000125 m, and maximum tracking-RMS difference
0.0000465 m.

## Verification record

- Ruff: all source, test, and script checks passed.
- Mypy strict: 210 source and test files passed.
- Campaign/API/release contracts: 29 passed.
- Mission, planner, fleet, and retained-evidence regression suite: 94 passed.
- Realtime predictive crossing, active-link isolation, and range-loss handover: 3
  passed after restoring supervised hover execution.
- UI: ESLint and TypeScript passed; 87 unit tests, production build, and 3 rendered
  HTML tests passed.
- Browser verification on the running local application confirmed the hierarchy,
  explanations, removed tagline/hash/raw decision output, immediate 1D-to-2D case and
  difficulty update, and Real `NOT_AUTHORIZED` presentation.

## Claim boundary

This closes the software and Fast Sim gates only. It does not authorize physical
flight, props-on testing, live Isaac execution, or digital-twin claims. The 35 Real
mirrors are catalog definitions for future separately authorized qualification and
remain non-executable.
