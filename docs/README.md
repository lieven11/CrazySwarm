# CrazySwarm documentation

This directory is the single documentation entry point. Project status has exactly
two authoritative ledgers: one for finished work and one for everything still open.

## Start here

| Question | Document |
|---|---|
| What is finished and frozen? | [`work-packages/COMPLETED.md`](work-packages/COMPLETED.md) |
| What is active, next, or externally blocked? | [`work-packages/ACTIVE.md`](work-packages/ACTIVE.md) |
| Which requirements apply to this task? | [`project/requirements/README.md`](project/requirements/README.md) |
| How should a retained run and its CSV be analyzed efficiently? | [`guides/RUN_ANALYSIS_PROTOCOL.md`](guides/RUN_ANALYSIS_PROTOCOL.md) |
| How will the placeholder campaign catalog become a real learning curriculum? | [`work-packages/ACTIVE.md`](work-packages/ACTIVE.md#wp-35--semantic-truth-gate-and-executable-case-contract) |
| What belongs in a mission, planner, control center, or simulator? | [`system/README.md`](system/README.md) |
| How do planner, fleet-policy, recovery, and Safety Kernel modules connect? | [`system/PLANNING_AND_RECOVERY_PLUGINS.md`](system/PLANNING_AND_RECOVERY_PLUGINS.md) |
| What exactly is compiled and admitted before Play? | [`reference/MISSION_PLAN_V1.md`](reference/MISSION_PLAN_V1.md) |
| What must a downloadable previous-run CSV contain? | [`reference/RUN_TELEMETRY_CSV_V1.md`](reference/RUN_TELEMETRY_CSV_V1.md) |
| What belongs in a grouped execution bundle and evaluator report? | [`reference/MISSION_EXECUTION_EVALUATION_V1.md`](reference/MISSION_EXECUTION_EVALUATION_V1.md) |
| What is the accepted smooth-motion authority? | [`reference/TIME_PARAMETERIZED_TRAJECTORY_V1.md`](reference/TIME_PARAMETERIZED_TRAJECTORY_V1.md) |
| What makes an arrival and landing successful? | [`reference/LANDING_GOAL_REGION_V1.md`](reference/LANDING_GOAL_REGION_V1.md) |
| How are two-drone trajectory conflicts predicted and resolved? | [`reference/PREDICTIVE_DECONFLICTION_V1.md`](reference/PREDICTIVE_DECONFLICTION_V1.md) |
| How are parameterized cases generated and promoted? | [`reference/MISSION_CURRICULUM_V1.md`](reference/MISSION_CURRICULUM_V1.md) |
| What are the frozen planning plugin contracts? | [`reference/PLANNING_PLUGIN_CONTRACT_V1.md`](reference/PLANNING_PLUGIN_CONTRACT_V1.md) |
| How do intent graphs and exact approvals work? | [`reference/MISSION_INTENT_AND_APPROVAL_V1.md`](reference/MISSION_INTENT_AND_APPROVAL_V1.md) |
| What qualifies WP-12 through WP-17? | [`qualification/MISSION_PLANNING_WP12_17.md`](qualification/MISSION_PLANNING_WP12_17.md) |
| What qualifies previous-run CSV downloads and their control layout? | [`qualification/RUN_HISTORY_CSV_WP18.md`](qualification/RUN_HISTORY_CSV_WP18.md) |
| What qualifies the deterministic execution evaluator? | [`qualification/MISSION_EVALUATION_WP19.md`](qualification/MISSION_EVALUATION_WP19.md) |
| What qualifies authoritative smooth trajectory execution? | [`qualification/SMOOTH_TRAJECTORY_WP20.md`](qualification/SMOOTH_TRAJECTORY_WP20.md) |
| What qualifies goal-region arrival and landing? | [`qualification/GOAL_LANDING_WP21.md`](qualification/GOAL_LANDING_WP21.md) |
| What qualifies predictive two-drone deconfliction? | [`qualification/PREDICTIVE_DECONFLICTION_WP22.md`](qualification/PREDICTIVE_DECONFLICTION_WP22.md) |
| What qualifies the progressive mission curriculum? | [`qualification/MISSION_CURRICULUM_WP23.md`](qualification/MISSION_CURRICULUM_WP23.md) |
| How should a mission be authored, reviewed, and operated safely? | [`guides/MISSION_SAFETY_GUIDE.md`](guides/MISSION_SAFETY_GUIDE.md) |
| How do parallel tasks avoid restarting or stealing the physical runtime? | [`guides/HARDWARE_RUNTIME_OWNERSHIP.md`](guides/HARDWARE_RUNTIME_OWNERSHIP.md) |
| How do I enter the measured controller-tuning box geometry and unlock missions A–E? | [`guides/CONTROLLER_TUNING_FIXTURE.md`](guides/CONTROLLER_TUNING_FIXTURE.md) |
| How does the staged cushioned-acrobatics hover and Flip workflow work? | [`guides/CUSHIONED_ACROBATICS.md`](guides/CUSHIONED_ACROBATICS.md) |
| What is the product and how do I run it? | [`project/README.md`](project/README.md) |
| What is the long-range development roadmap? | [`project/DEVELOPMENT_GUIDE.md`](project/DEVELOPMENT_GUIDE.md) |
| Which durable workflow and operator requirements must future feature iterations reuse? | [`project/requirements/README.md`](project/requirements/README.md) |
| Which design decisions must every UI implementation follow? | [`../design.md`](../design.md) |
| What should the operator interface look like? | [`project/DESIGN.md`](project/DESIGN.md) |

## Directory structure

```text
docs/
├── project/          product overview, routed requirements, decisions, and development guide
├── work-packages/    the only two current planning ledgers
├── system/           responsibility boundaries and codebase map
├── guides/           runnable simulator, Isaac, and physical procedures
├── reference/        frozen contracts, schemas, architecture, and compatibility
├── qualification/    evidence-oriented records, limitations, and claim boundaries
└── archive/           non-authoritative historical planning sources
```

Documents inside `archive/` are retained for traceability only. Their checkboxes,
counts, paths, and status labels are historical and must not be used to decide what
to implement next.

## Documentation rules

1. Update `COMPLETED.md` only after an implementation has evidence and no package
   acceptance item remains open.
2. Put active work, its immediate next action, dependencies, and exit gate in
   `ACTIVE.md`; do not create another planning file.
3. Keep product intent and durable architecture out of status ledgers. Put them in
   `project/` or `system/`.
4. Keep executable procedures in `guides/`, frozen interfaces in `reference/`, and
   evidence or limitation statements in `qualification/`.
5. Use one of `PLANNED`, `IN_PROGRESS`, `IMPLEMENTED`, `QUALIFIED`, `COMPLETE`, or
   `EXTERNALLY_BLOCKED`. `IMPLEMENTED` never implies that the full closeout gate passed.
6. Define each durable requirement exactly once under `project/requirements/`. Keep
   historical rationale in `project/decisions/` or `project/retrospectives/` and use
   the requirements index to select only task-relevant context.

Validate routed documentation with:

```bash
python scripts/check_requirement_catalog.py
python scripts/check_project_map.py
```

Current planning contracts include the
[multi-drone conflict-planning contract](reference/MULTI_DRONE_CONFLICT_PLANNING_V1.md),
with its [WP-24 Fast Sim qualification](qualification/MULTI_DRONE_CONFLICT_WP24.md).
The final iterative software packet is recorded in the
[mission robustness matrix contract](reference/MISSION_ROBUSTNESS_MATRIX_V1.md) and
[WP-25 qualification](qualification/MISSION_ROBUSTNESS_WP25.md).
