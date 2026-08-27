# Mission and curriculum requirements

> Navigation: [requirements index](README.md)

Read when changing mission identity, variations, curriculum progression, capability reuse, or catalog grouping.

## Mission and variation design

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-MIS-001` | Behavior must precede labels. No case or submission may exist only to satisfy a count, naming pattern, compact/wide quota, seed grid, or requested variety. | Semantic fingerprint and retained execution must demonstrate a distinct causal question. |
| `REQ-MIS-002` | Mission problem truth, planning policy, and execution profile must be modeled separately. | The same world can be solved under different admitted maneuver/deviation policies and time laws without duplicating or mutating the case. |
| `REQ-MIS-003` | A variation must change a behavior-driving input, feasible set, accepted trajectory, event, decision, or evidence question. | A description, ID, seed, or display-only change is not a semantic variation. |
| `REQ-MIS-004` | Each proposed case, sub-problem, or submission must pass the variation-admission gate below before implementation. | Prevents unreasoned variety and combinatorial growth. |
| `REQ-MIS-005` | A comparison should change one principal causal variable at a time; secondary changes must be declared and justified. | Makes differences attributable rather than merely observable. |
| `REQ-MIS-006` | Every admitted planning submission and selected execution profile must have stable identifiers and canonical hashes included in plan, runtime command authority, evidence, evaluation, analysis, replay, and download. | Prevents a catalog choice from becoming an unrecorded runtime setting. |
| `REQ-MIS-007` | Experimental planning submissions and evidence profiles are mission-specific and are not copied into every catalog case. The qualified implementation beneath them must live once in its owning core capability layer and be bound at planning time when a mission requirement requests it. | A synchronized vertical-layer experiment may be case-specific, while a learned constant-speed time law must remain reusable without adding a new submission or copying code into each mission. |
| `REQ-MIS-008` | Catalog implementation and qualification metadata never gates selection of a discovered simulation mission or its retained baseline playback. Optional unsupported or scientifically premature planning submissions and profiles remain `PLANNED_NOT_EXECUTABLE` and fail closed before provisioning. The selected baseline still passes the real planner, backend, and hard safety checks before command authority. | Separates operator mission choice from qualification progress without implying that unsupported optional behavior is executable or weakening runtime safety. |
| `REQ-MIS-009` | Existing cases and retained runs remain immutable. Successor cases, planning submissions, and profiles reference their baselines instead of rewriting historical evidence. | Preserves traceability across design iterations. |
| `REQ-MIS-010` | The operator-facing current 1D curriculum is organized into exactly five major missions—`Flight`, `Target`, `Level path`, `3D path`, and `Shape`—with behaviorally distinct cases presented as subordinate variants. This is a versioned catalog grouping over immutable case/run identities, not a rewrite or deletion of historical evidence. | Makes the ordinary curriculum understandable without replacing stable evidence identities or turning execution settings into extra missions. |
## Primitive reuse and curriculum progression

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-REU-001` | Validate a motion, controller, landing, event, or protocol primitive at the lowest meaningful mission level. | A one-drone constant-path-speed primitive should not be re-tuned from scratch inside every fleet mission. |
| `REQ-REU-002` | Higher-level cases must cite prerequisite evidence and define only the new coupling they test. | A three-drone crossing should test joint wait/layer/detour reasoning, separation, fairness, and atomic authority—not requalify ordinary straight motion. |
| `REQ-REU-003` | Reuse does not waive integration gates. Revalidate when payload, battery, altitude envelope, simultaneous maneuvering, downwash/contact model, disturbances, or controller saturation can materially alter feasibility. | “Previously validated” means evidence-backed reuse within a declared applicability boundary. |
| `REQ-REU-004` | Catalog recommendations should select the lowest unmet prerequisite, a causal follow-on, or an explicit regression. | Progression is based on learning state rather than case count or recency. |
| `REQ-REU-005` | Every accepted learning from mission testing or iteration must be classified as either a reusable core primitive, policy, model, or bounded parameter improvement implemented once in its owning production layer, or an explicit case/backend-specific limitation with retained rationale. It must not survive only as mission-local copied behavior. | Missions are learning and qualification environments; accepted behavior becomes drone/fleet capability rather than a growing collection of special-case mission implementations. |
| `REQ-REU-006` | A planner that requires a qualified core capability must request it by stable capability identity and parameters. Resolution binds it automatically to the selected case, geometry, vehicles, backend, hashes, and safety bounds; no per-mission catalog submission is required. Resolution fails closed outside the retained applicability boundary. | Future flexible planners can consume constant path speed directly while preserving traceability and integration gates. |
