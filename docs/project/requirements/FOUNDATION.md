# Requirements foundation

> Navigation: [requirements index](README.md)

Read this for requirement authority, precedence, the core design position, and the experiment taxonomy.

## Purpose and authority

This file records the durable workflow and requirements learned during operator
review so that the same design preferences and testing method do not have to be
restated for every mission family or feature. It is consulted before a mission
definition, planner behavior, review surface, feature, or work packet is changed.

This document is not a status ledger, frozen interface, or permission to implement.
Open implementation work belongs only in `docs/work-packages/ACTIVE.md`; completed
evidence belongs only in `docs/work-packages/COMPLETED.md`. A requirement added here
must still be translated into a gated work packet before code, mission data, or
campaign state changes.

Precedence is:

1. safety, authorization, and frozen interface contracts;
2. the development guide and system responsibility boundaries;
3. the active work-package ledger;
4. these durable operator requirements; and
5. an individual mission description.

A lower item may specialize a higher item but may not silently weaken it. A conflict
is recorded and resolved explicitly.

## Core design position

- Develop and qualify in simulation first, but define mission intent so that a later
  high-fidelity simulator or physical adapter can execute the same experiment without
  changing what the experiment means.
- Fast Sim evidence establishes deterministic software behavior only. It does not
  establish physical accuracy, motor calibration, contact fidelity, or a digital-twin
  claim.
- Test one main causal variable at a time. Preserve exact configuration, versions,
  backend/model identity, case identity, profile identity, seed, result, and faults.
- Prefer the smallest mission that can validate a primitive. Higher-order missions
  reuse that evidence and test only newly introduced coupling or coordination.
- Treat an authored route as a reference, tolerance tube, required corridor, or exact
  path according to an explicit path-adherence contract. Do not assume every authored
  polyline is either immutable or freely replaceable.
- Let the planner use timing, speed, lateral motion, altitude, or a bounded combination
  only when the selected submission and environment explicitly permit those degrees of
  freedom. Obstacles and occupied volumes remove options; they do not silently force a
  globally preferred strategy.
- Let an operator author, review, and download one resolved submission package that
  contains or references the complete case/world conditions and the requested planning
  authority. A single-file workflow must not collapse immutable obstacle truth and
  mutable planning permission into the same canonical identity.
- A visually plausible run is not enough. The accepted plan, runtime behavior,
  telemetry, evaluation, analysis, replay, and operator-facing explanation must agree.

## Experiment taxonomy

The catalog and evidence model must distinguish the following layers.

| Layer | Meaning | Example | Identity rule |
|---|---|---|---|
| Mission family | Reusable causal learning objective | `altitude_transition` | Groups related cases; does not command flight. |
| Mission case | Immutable problem truth: starts/goals, reference routes, environment and obstacle state, vehicle set, safety bounds, events, and behavior oracles | A head-on encounter in an open room, or the same encounter under a bridge with only an underpass available | A world, event, vehicle, or hard-success-condition change produces a new immutable case/hash. |
| Mission sub-problem | One causal coordination question within a case family | Same-time head-on resolution, merge-corridor capacity, or reaction to a newly observed obstacle | It becomes a case when problem truth changes; it may be exercised by a submission when only admitted planner authority or objective changes. |
| Planning submission | A case-bound request describing the admissible solution space and optimization intent | Earliest safe release, synchronized altitude-layer resolution, bounded lateral detour, or path-fidelity-first planning | Binds the case hash, maneuver authority, path-adherence/deviation limits, coordination policy, objective, optional execution profile, backend support, and submission-specific oracles. |
| Execution profile | A time law or control objective used by a planning submission | Planner baseline, constant path speed, or a bounded segment-speed schedule | Retains its own profile hash and owner layer; it does not grant geometric maneuver or replanning authority. |
| Run | One execution of an exact case/planning-submission/profile/backend/configuration/seed/clock tuple | Realtime repeat 2 of a simultaneous altitude-layer submission | Repetition alone is not a new case, submission, or profile. |

“Submission” is the operator-facing term for a planning submission. The currently
implemented execution-profile submission remains a narrower, hash-bound component for
time/control-law experiments and must remain readable as historical evidence. A
successor planning-submission contract composes, rather than silently reinterprets, an
eligible execution profile. The catalog should first select a mission case and then
show only the planning submissions and profiles admitted for that case. It must not
flatten every combination into a global Cartesian catalog.

The operator-facing submitted request may be transported as one file. That file must
resolve the immutable case/world snapshot, vehicle/model references, planning
submission, and optional execution profile, while retaining a separate canonical hash
for every component and for the resolved package. This preserves the requested
declarative workflow without making an obstacle, tunnel, or hard corridor a mutable
planner preference.
