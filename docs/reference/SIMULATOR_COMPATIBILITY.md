# Simulator compatibility and migration policy

> Navigation: [documentation index](../README.md)

## Version axes

Adapter contract, physics model, scenario schema, vehicle-parameter schema, mission
runtime, and API schema are separate versions. A run records each applicable axis
and its canonical configuration hash. A version string is never a substitute for
the content hash.

The adapter contract uses semantic versioning:

- Major: incompatible command meaning, required method/field, state transition,
  frame, unit, clock, identity, safety, or acknowledgement change.
- Minor: backward-compatible optional capability, signal, command, metadata field,
  or behavior that old consumers can safely omit.
- Patch: clarification or defect fix that preserves serialized meaning and the
  published tolerances of the versioned contract.

Physics model versions use the same categories, but any dynamics change that can
alter canonical outcomes also requires a new model version or a documented patch
qualification, new outcome hashes, and retained prior evidence identity.

## Config and schema migration

Readers validate strictly and reject unknown or invalid fields. A schema migration
must be an explicit, testable transformation from a named source version to a named
target version. It must preserve the original artifact/hash in run history, emit a
new canonical hash, document defaults and unit/frame changes, and be idempotent.

There are no silent migrations, implicit unit conversions, best-effort unknown
field drops, or in-place mutations of artifacts referenced by a run. If an old
schema cannot be interpreted without ambiguity, loading fails with a useful error.

## Canonical baselines

Canonical scenario/configuration and outcome hashes are release assertions. When a
deliberate model or scenario change alters a hash, the change review must explain
why, compare old/new outcomes within declared tolerances, update the correct version,
and keep previous receipts replayable. A developer must not approve a changed hash
only because the new run is internally deterministic.

## Adapter negotiation and fallback

Consumers negotiate declared capabilities, signals, model IDs, and adapter contract
version. Unsupported required capability or incompatible major version fails before
mission start. Optional absent data remains absent.

Fast Sim stays compatible with contract 1.0.0 and remains the CI/fallback backend.
It remains the default operator backend whenever the Isaac host/runtime is absent,
resource-constrained, experimental, incompatible, unhealthy, or not fully qualified.
Selecting or detecting an Isaac installation never silently changes backend, mode,
or command authority.

## Deprecation

Deprecation must be documented before removal and include the replacement, first
deprecated version, earliest removal major version, migration tool or procedure,
and tests covering the overlap. Immutable evidence and replay readers retain the
ability to identify prior versions even after active execution support is removed.
