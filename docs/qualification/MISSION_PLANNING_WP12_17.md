# Mission planning WP-12 through WP-17 qualification

| Field | Value |
|---|---|
| Scope | Backend-neutral planner/policy/recovery contracts, intent, approval, Fast Sim release |
| Date | 2026-08-08 |
| Qualification ID | `planning-release-fast-sim-v1` |
| Qualification report SHA-256 | `8352fa8d0cc7e886ae10424f6521a20abbaf0f3cf1e14310a96e01a670d524fe` |
| Route planners | 4 registered implementations / 7 advertised capabilities |
| Fleet policies | 4 |
| Recovery strategies | 8 |
| Physical flight | `NOT_RUN` |
| Live Isaac | `NOT_RUN` |
| Digital twin | `NOT_RUN` |

## Qualified boundary

- Frozen manifests, selections, proposal contracts, explicit registries, duplicate and
  version/capability rejection, implementation hash binding, and a shared deterministic
  bounded qualification harness.
- Direct, zone/obstacle-aware, coverage, and temporal planners; explicit dock and
  leader/follower capabilities; route timing, length, energy, corridor, completion,
  limitation, finding, replan, and canonical hash contracts.
- Persistent, crossing-route, leader/follower, and independent fleet policies plus
  eight typed recovery strategies with standardized actions, preconditions, deadlines,
  fallbacks, and evidence.
- Mission safety declaration, tighten-only policy enforcement, Safety Kernel recovery
  admission, and a hash-bound safety-case receipt. Existing `SafetySupervisor` remains
  the final command authority.
- Objective/phase intent, bounded transitions, immutable execution graph, explicit-
  action Python compatibility, graph/assignment admission, and complete receipt
  preservation.
- Control Center plan review, exact client-bound approval, finding acknowledgement,
  one-time consumption, and stale change rejection before provisioning.

## Canonical software cases

The machine-readable release report passes nominal route, boundary rejection, obstacle
rejection, energy accounting, observation and command loss, cancellation, temporal
separation, bounded planning conflict, recovery selection, contingency bounds, and
stateless cleanup. Every registered component passes two-invocation
canonical determinism and the one-second component budget. The report is stable across
fresh Python processes, survives JSON round-trip reconstruction, and remains unchanged
over 100 repeated in-process qualification runs.

Normal API evidence additionally covers Preview/approve/Play, missing approval, current
observation changes invalidating approval, low-battery acknowledgement, multi-role and
reserve execution, cancellation/restart cleanup, Fast Sim and mock-backend portability,
and execution receipt preservation.

## Commands

```text
.venv/bin/python scripts/qualify_mission_planning.py
.venv/bin/python scripts/verify_canonical_scenarios.py
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src tests
UI lint + TypeScript + Vitest + production build + rendered HTML tests
```

The exact final same-tree repository and UI counts are recorded in the authoritative
completed ledger after the last broad gate. A failed or interrupted gate is never
represented as a passing count here.

## Limitations and deferred systems

- This is a software-only qualification. It makes no flightworthiness, physical
  separation, endurance, docking, charging, RF, or real-aircraft claim.
- Route corridors use conservative axis-aligned reservation bounds; general 3D optimal
  motion planning is not claimed.
- Restricted Python remains a supported explicit-action input, not an unrestricted
  autonomous goal interpreter.
- `LIVE_ISAAC`, `PHYSICAL_CRAZYFLIE`, and `DIGITAL_TWIN` are explicitly `NOT_RUN` and
  remain outside WP-12 through WP-17.
