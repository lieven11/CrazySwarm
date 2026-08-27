# CrazySwarm requirements index

This directory is the canonical source for durable CrazySwarm requirements. Start
here, select only the documents required by the task, and do not read the complete
catalog by default. A requirement definition is authoritative only in the one file
assigned below; guides, decisions, retrospectives, qualification records, and work
packages may cite but never redefine it.

## Authority and precedence

Read [`FOUNDATION.md`](FOUNDATION.md) when authority, precedence, experiment identity,
or a cross-domain interpretation is material. In summary, precedence remains:

1. safety, authorization, and frozen interface contracts;
2. the development guide and system responsibility boundaries;
3. the active work-package ledger;
4. these durable operator requirements; and
5. an individual mission description.

Open work belongs in `docs/work-packages/ACTIVE.md`; completed evidence belongs in
`docs/work-packages/COMPLETED.md`. Requirements are not status records or independent
implementation authority.

## Task routing

| Task | Required reading | Add only when applicable |
|---|---|---|
| Mission authoring, identity, variants, or curriculum | [`MISSION_AND_CURRICULUM.md`](MISSION_AND_CURRICULUM.md) | Foundation; motion; evidence |
| Motion, trajectory, controller, or parameter tuning | [`MOTION_AND_CONTROL.md`](MOTION_AND_CONTROL.md), [`workflow/ITERATION_AND_TUNING.md`](workflow/ITERATION_AND_TUNING.md) | Evidence; fidelity; run-analysis guide |
| CSV, evaluation, run review, plots, or evidence claims | [`EVIDENCE_AND_REVIEW.md`](EVIDENCE_AND_REVIEW.md), [`../../guides/RUN_ANALYSIS_PROTOCOL.md`](../../guides/RUN_ANALYSIS_PROTOCOL.md) | Motion, planning, replanning, or fidelity according to the question |
| Planning submissions, optimization, obstacles, geometry, contact, or landing targets | [`PLANNING_AND_GEOMETRY.md`](PLANNING_AND_GEOMETRY.md) | Motion; replanning; evidence |
| Runtime events, reaction horizons, or replanning | [`REPLANNING_AND_RUNTIME.md`](REPLANNING_AND_RUNTIME.md) | Planning/geometry; evidence; fidelity |
| Simulator, Isaac, hardware, calibration, or digital-twin transfer | [`FIDELITY_AND_TRANSFER.md`](FIDELITY_AND_TRANSFER.md) | Motion; evidence; replanning |
| Catalog navigation or ordinary operator controls | [`UI_AND_CATALOG.md`](UI_AND_CATALOG.md), [`../../../design.md`](../../../design.md) | The domain document for the behavior displayed |
| Ordinary focused implementation or diagnosis | The owning domain document only | Workflow documents only when their trigger applies |
| Evidence-driven iteration without a work packet | [`workflow/ITERATION_AND_TUNING.md`](workflow/ITERATION_AND_TUNING.md) | Owning domain and evidence documents |
| Explicit work-packet request | [`workflow/WORK_PACKET_GATES.md`](workflow/WORK_PACKET_GATES.md), [`workflow/COST_SCOPE_AND_HANDOFF.md`](workflow/COST_SCOPE_AND_HANDOFF.md) | Pre-freeze/oracles under the triggers below |
| Historical rationale or investigation | Relevant file under [`../decisions/`](../decisions/) or [`../retrospectives/`](../retrospectives/) | Never required for routine implementation |

## Specialized work-packet routing

Read [`workflow/PREFREEZE_AND_ORACLES.md`](workflow/PREFREEZE_AND_ORACLES.md)
when a packet contains any of the following:

- a matrix, registry, proposal family, lifecycle inventory, or comparator map;
- a numerical oracle, tolerance, tie-break, or feasibility certificate;
- geometry- or sampling-derived behavior;
- generated or hash-bound artifacts;
- a production/runtime claim; or
- served UI/release qualification.

Do not load that specialized document for an ordinary packet that has none of those
properties.

## Requirement ownership

| Prefix/range | Canonical file | Definitions |
|---|---|---:|
| `REQ-MIS-*`, `REQ-REU-*` | [`MISSION_AND_CURRICULUM.md`](MISSION_AND_CURRICULUM.md) | 16 |
| `REQ-MOT-*` | [`MOTION_AND_CONTROL.md`](MOTION_AND_CONTROL.md) | 17 |
| `REQ-PLN-*`, `REQ-GEO-*` | [`PLANNING_AND_GEOMETRY.md`](PLANNING_AND_GEOMETRY.md) | 24 |
| `REQ-RPL-*` | [`REPLANNING_AND_RUNTIME.md`](REPLANNING_AND_RUNTIME.md) | 13 |
| `REQ-XFR-*` | [`FIDELITY_AND_TRANSFER.md`](FIDELITY_AND_TRANSFER.md) | 10 |
| `REQ-EVI-*` | [`EVIDENCE_AND_REVIEW.md`](EVIDENCE_AND_REVIEW.md) | 14 |
| `REQ-UI-*` | [`UI_AND_CATALOG.md`](UI_AND_CATALOG.md) | 2 |
| `REQ-WFL-001..012` | [`workflow/ITERATION_AND_TUNING.md`](workflow/ITERATION_AND_TUNING.md) | 12 |
| `REQ-WFL-013..027` | [`workflow/WORK_PACKET_GATES.md`](workflow/WORK_PACKET_GATES.md) | 15 |
| `REQ-WFL-028..041` | [`workflow/PREFREEZE_AND_ORACLES.md`](workflow/PREFREEZE_AND_ORACLES.md) | 14 |
| `REQ-WFL-042..054` | [`workflow/COST_SCOPE_AND_HANDOFF.md`](workflow/COST_SCOPE_AND_HANDOFF.md) | 13 |
| **Total** |  | **150** |

## Supporting records

- [`../decisions/VARIATION_ADMISSION.md`](../decisions/VARIATION_ADMISSION.md)
- [`../decisions/MULTIDRONE_PLANNING.md`](../decisions/MULTIDRONE_PLANNING.md)
- [`../decisions/ALTITUDE_TRANSITION.md`](../decisions/ALTITUDE_TRANSITION.md)
- [`../retrospectives/WP52_56_COST_AND_VALUE.md`](../retrospectives/WP52_56_COST_AND_VALUE.md)
- [`../retrospectives/REPEATED_PACKET_REVIEWS.md`](../retrospectives/REPEATED_PACKET_REVIEWS.md)
- [`../retrospectives/ALTITUDE_TRANSITION_LEARNINGS.md`](../retrospectives/ALTITUDE_TRANSITION_LEARNINGS.md)
- [`../REQUIREMENTS_CHANGELOG.md`](../REQUIREMENTS_CHANGELOG.md)

Run `python scripts/check_requirement_catalog.py` after moving, adding, or changing a
requirement or routing link.
