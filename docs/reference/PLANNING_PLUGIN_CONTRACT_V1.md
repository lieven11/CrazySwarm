# Planning plugin contract v1

| Field | Value |
|---|---|
| Contracts | `RoutePlanner`, `FleetPolicy`, `RecoveryStrategy` |
| Manifest schema | `PluginManifest` v1 |
| Registry | Explicit process-local allow list |
| Execution authority | None; plugins return immutable proposals only |
| Final authority | Non-replaceable `SafetyKernel` and `SafetySupervisor` |
| Qualification | Fast Sim/software only |

## Manifest and registry

Every built-in component declares a stable plugin ID, semantic implementation version,
input/output schema version, Control Center compatibility range, capabilities, required
observations, deterministic/bounded flags, qualification state, and implementation
SHA-256. A `PluginSelection` copies the exact manifest and implementation hashes into
the mission-plan receipt.

`PluginRegistry` accepts application-created objects only. Resolution requires an exact
ID/version and all requested capabilities. Duplicate, wrong-kind, unregistered,
unqualified, and capability-mismatched components fail closed. There is no path that
imports, installs, downloads, or evaluates a plugin supplied by a mission or browser.

## Proposal-only interfaces

- `RoutePlanner.plan` receives bounded world-frame geometry, targets, observations,
  limits, reservations, and replan identity. It returns waypoints, timing, energy,
  length, corridors, completion, limitations, findings, and a canonical route hash.
- `FleetPolicy.decide` receives roles, routes, reserves, and separation policy. It
  returns launch/hold/active/reserve decisions and rationale with a canonical hash.
- `RecoveryStrategy.propose` receives a typed trigger, current identity/authority,
  available actions, lease, and deadline. It returns a reasoned, hash-bound proposal
  with preconditions, evidence, and fallback.

None of these interfaces exposes a `Vehicle`, adapter, command sender, radio, gateway,
browser callback, or mutable fleet lease.

## Registered built-ins

Route capabilities are `DIRECT`, `ZONE`, `COVERAGE`, `OBSTACLE_AWARE`,
`TEMPORAL_SEPARATION`, `DOCK_APPROACH`, and `LEADER_FOLLOWER`. The zone adapter retains
the existing deterministic `ZoneTaskPlanner`. Temporal planning gives an existing
reservation precedence, applies a bounded hold, and returns `BLOCKED` when no bounded
slot exists.

Fleet policies are persistent coverage, crossing route, leader/follower, and independent
tasks. Recovery strategies cover low battery, leader loss, link loss, localization
loss, reserve loss, dock unavailability, command timeout, and acknowledgement loss.

## Safety boundary

A mission safety declaration may only call `SafetyPolicy.tighten`. It cannot expand the
flight volume, increase altitude/dynamics/timeouts, lower battery/link/localization
minimums, or disable supervisor authority. The Safety Kernel rejects stale request,
role, vehicle, authority, observation, action, or declaration identity. Runtime command
validation, watchdogs, abort, landing, and emergency-stop remain owned by the existing
supervisor after strategic admission.

The common qualification harness invokes every registered component twice on canonical
input, compares canonical output hashes, enforces a time budget, and records its exact
manifest/input/output identities. WP-17 currently covers 4 route planners, 4 fleet
policies, and 8 recovery strategies through that one harness.
