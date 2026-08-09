# Mission plan receipt v1

| Field | Value |
|---|---|
| Contract | `MissionPlanReceipt` |
| Schema | `1` |
| Implementation | `src/crazyswarm_app/missions/planning.py` |
| Execution record schema | `2` |
| Authority | Backend service; never the browser or simulator |
| Physical-flight qualification | None |

## Purpose

A mission source preview is not sufficient evidence for execution. The mission
planner compiles mission intent and the current planning inputs into an immutable,
machine-readable admission receipt. The receipt answers:

1. Which logical roles and vehicles are involved?
2. Which commands and route segments are currently expected for each active role?
3. Which safety policy and environmental facts were checked?
4. Is the plan approved, operator-confirmable, or blocked?
5. Which exact receipt did the execution accept?

The receipt is backend-neutral. It contains logical deployment identity and no radio
address, simulator namespace, renderer setting, physics tuning, or fault schedule.

## Compilation inputs

`build_mission_plan` receives:

- the immutable `MissionFileRecord`, including source hash and declared roles;
- the backend-neutral `DeploymentManifest` and role assignments;
- the effective global `SafetyPolicy`;
- current known start positions and observed battery values when available;
- the identities of already-existing vehicles; and
- configured axis-aligned obstacle geometry.

These inputs are normalized and sorted before hashing. Identical canonical inputs
produce the same `plan_id` and receipt SHA-256. A material change requires a new plan.
Unavailable observations remain unavailable; the planner does not invent telemetry.

## Receipt structure

| Field | Meaning |
|---|---|
| `plan_id` | Stable `mission-plan-…` identifier derived from canonical plan content |
| `mission_id` / `mission_source_sha256` | Exact immutable mission artifact |
| `package_schema_version` | Mission package language version used to compile the plan |
| `deployment_sha256` | Exact logical fleet, tasks, zones, and constraints |
| `status` | `APPROVED`, `REQUIRES_CONFIRMATION`, or `BLOCKED` |
| `roles` | Per-role start, home, commands, waypoints, timing, distance, altitude, energy, and fidelity |
| `safety` | Frozen safety-policy limits and fleet separation/freshness constraints |
| `findings` | Ordered machine-readable blockers, warnings, confirmations, and details |
| `planning` | Selected plugin hashes, route plans, fleet decision, intent, execution graph, and safety case |

Every `MissionRolePlan` identifies whether the vehicle already exists and whether its
preview is:

- `EXACT_ROLE`: the selected restricted role branch executed in the bounded preview
  worker and produced exact planned commands;
- `STATIC_BOUNDS`: reserved for a future explicitly limited static-only plan; current
  start admission fails closed when exact role preview cannot be compiled; or
- `PREPARED_RESERVE`: the role is provisioned/prepared but has no active mission
  command sequence at initial execution.

## Admission checks

The v1 compiler evaluates:

- start and target containment in the global flight volume;
- maximum altitude;
- maximum mission duration;
- modeled command horizontal and vertical speed;
- modeled command acceleration and yaw rate;
- declared starting warning and critical separation;
- line-segment intersection with configured axis-aligned obstacles;
- task energy estimate plus margin against observed battery; and
- safety-policy takeoff battery against observed battery.

An unavailable current position or battery is recorded as an explicit limitation and
deferred to mandatory preparation observation/preflight; the declared home is labeled
only as a proposed start. It is never substituted as measured telemetry, and no vehicle
may arm until runtime preflight obtains the required healthy observations. WP-12 will
allow mission safety declarations to require selected inputs already at planning time.

The dynamic formulas match the supervisor's smooth command profile bounds. Runtime
preflight, command validation, observation freshness, health watchdogs, fleet
separation intervention, abort, and emergency authority remain active after a plan is
accepted. Planning never bypasses runtime safety.

## Status rules

| Status | Rule | Start behavior |
|---|---|---|
| `APPROVED` | No blocker and no unresolved confirmation finding | May continue to preparation and runtime preflight |
| `REQUIRES_CONFIRMATION` | No blocker; at least one finding explicitly requires confirmation | Rejected until the allowed execution mode receives explicit operator confirmation |
| `BLOCKED` | At least one blocker | Always rejected before provisioning |

Warnings that do not require confirmation remain visible but do not alone block
start. A blocker cannot be overridden by the low-battery simulation confirmation.

## API and execution binding

`GET /api/v1/mission-files/{mission_id}/preview` returns both the legacy `vehicles`
view and the complete `plan` plus `plan_sha256`.

`POST /api/v1/mission-files/{mission_id}/approve` binds the exact current plan and
safety-case hashes, selected manifests, acknowledgements, and operator client into an
expiring approval. `POST /api/v1/mission-files/{mission_id}/start` recompiles from
current inputs before provisioning and requires that exact approval. A blocked,
unapproved, stale, or unresolved confirmable plan returns `PREFLIGHT_FAILED` with the
plan identity and findings. An accepted execution stores:

- `mission_plan_id`;
- `mission_plan_sha256`;
- the complete `mission_plan` receipt; and
- the execution graph and safety case inside that receipt.

The execution coordinator rejects a receipt whose mission source or deployment hash
does not match the execution request.

## Known v1 limitations

- Obstacle admission uses straight command segments against configured axis-aligned
  boxes; it is not a general motion planner or resolved contact model.
- V1 records current starting separation but does not predict all simultaneous
  inter-vehicle trajectories. Fleet coordination and runtime separation policy remain
  authoritative for dynamic peer conflicts.
- An observation-dependent preview uses the bounded worker's planning observations.
  Runtime observations can select a different validated branch, so the receipt is not
  proof that every future runtime branch is known; every emitted command remains
  subject to runtime policy.
- Starting yaw is currently treated as zero because the planning input does not yet
  contain a source-qualified yaw observation.
- The receipt proves software checks against declared/configured inputs. It does not
  prove physical accuracy, obstacle completeness, localization accuracy, airworthiness,
  or real-flight safety.

These remain explicit limitations for any future planner expansion and do not widen the
WP-12 through WP-17 software-only claim.
