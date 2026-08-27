# Iteration and tuning workflow

> Navigation: [requirements index](../README.md)

Read for evidence-driven refinement, parameter searches, candidate comparison, finite stop conditions, and operator handoff.

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-WFL-001` | Treat the operator's stated general behavior and outcome as the design intent. Use comments, images, CSV, evaluation, analysis, and earlier evidence to establish the current gap and measurable baseline, not to narrow the requirement to the workflow or behavior already present in those artifacts. | Evidence explains what exists; it does not redefine the requested future capability. |
| `REQ-WFL-002` | Translate durable operator intent into dependencies, tasks, non-goals, and measurable exit gates in `ACTIVE.md` before changing implementation. | Separates analysis and planning from implementation authority while retaining the general goal. |
| `REQ-WFL-003` | Update this file when operator feedback creates or changes a durable preference. Append a change-log entry and retain stable requirement IDs; do not silently erase earlier intent. | Makes the review loop cumulative. |
| `REQ-WFL-004` | Close work only from retained evidence and record remaining limits. Requirements remain durable even after their first implementation package completes. | A completed implementation does not remove the design rule from future missions. |
| `REQ-WFL-005` | Do not encode “read comments/CSV and copy the observed workflow” as the product goal. Reconcile evidence repeatedly, but implement the generalized planning, constraint, collision, and replanning capability requested by the operator. | Prevents one reviewed run or current planner workaround from becoming the permanent design. |
| `REQ-WFL-006` | Use an assisted evidence-driven iteration loop for motion refinement: (1) freeze exact current evidence identities; (2) compute phase- and segment-specific baselines; (3) identify the causal owner layer; (4) change one bounded hypothesis; (5) run static/dynamics gates; (6) execute isolated accelerated repeats; (7) compare the full pre/post gate set; and (8) accept, revise, or revert before requesting realtime/operator reruns. Stop when declared improvement and non-regression gates pass, not when a plot merely looks smoother. | Allows the system to help iterate parameters while keeping the reasoning, stop condition, and trade-offs explicit. |
| `REQ-WFL-007` | Assisted iterations use temporary or qualification evidence stores and must not select, flag, baseline, promote, delete, or otherwise transition the operator's campaign cases or review runs. The operator-owned current iteration changes only through explicit actions; accepted implementation hashes then start a new Run-history iteration as required by `REQ-EVI-007`. | Automation may improve and qualify code, but it may not rewrite the meaning or lifecycle of retained review evidence. |
| `REQ-WFL-008` | Before an assisted search starts, record a tuning contract containing the causal hypothesis, exact baseline identities, primary metric, safety and quality guardrails, bounded parameter family, repeat policy, cross-case checks, acceptance threshold, plateau condition, and revert rule. Thresholds may not be invented after seeing candidate results. | Makes automated improvement reproducible and prevents the search from optimizing a visually attractive but incomplete result. |
| `REQ-WFL-009` | Retain a candidate ledger for every evaluated parameter set, including code/configuration and artifact hashes, derived plan/trajectory identities, run IDs, metric vector, pass/fail result, and rejection reason. Preserve failed candidates as learning evidence and do not report only the selected winner. | Prevents cherry-picking and makes future iterations reuse knowledge instead of repeating rejected experiments. |
| `REQ-WFL-010` | Qualify candidates in stages: exact-artifact and analytic sampling first, static/dynamics and semantic gates second, isolated deterministic execution repeats third, and a distinct stress/coupling case last. A candidate that fails an earlier gate is not provisioned for later execution. | Reduces unnecessary runs and separates a bad commanded artifact from tracker, controller, backend, or plant behavior. |
| `REQ-WFL-011` | Accept a candidate only when its predeclared primary objective and every non-regression gate pass. Stop and retain the existing behavior when improvement plateaus, bounds are exhausted, or a gain requires an undeclared trade-off. Record remaining limitations and the evidence that would justify reopening the search. | Gives assisted iteration a finite, auditable stop condition and a safe revert path. |
| `REQ-WFL-012` | Treat isolated software qualification as a candidate handoff, not final operational or physical validation. After acceptance, request the minimum meaningful realtime/operator reruns; later high-fidelity simulator, digital-twin, and physical-drone checks remain separate evidence layers with their own tolerances. | Keeps fast iteration useful without overstating what software-simulation evidence proves. |

## Reusable assisted feature-iteration method

The altitude-transition refinement established the following reusable method for
future motion, planning, control, evaluation, and review features:

1. **Define.** Convert the operator-observed behavior into a measurable tuning
   contract before testing. Name one primary objective and retain safety, tracking,
   actuator, energy, terminal, fault, and semantic non-regression gates as applicable.
2. **Freeze the baseline.** Bind the exact case, submission/profile, backend, seed,
   configuration, accepted plan, trajectory, implementation, and evidence hashes.
   Split measurements into meaningful phases and segments rather than relying on a
   whole-run average or visual impression.
3. **Diagnose ownership.** Compare authored intent, generated command, accepted
   artifact, actual response, and evaluator result. Correct the earliest causal layer
   that violates intent before changing downstream controller gains.
4. **Bound the search.** Vary one causally related parameter family at a time inside
   declared safe bounds. Include a margin-rich anchor and a meaningful stress anchor;
   avoid dense arbitrary sweeps and unrelated simultaneous changes.
5. **Screen cheaply.** Sample the exact generated artifact at adequate resolution and
   reject failures of coverage, continuity, conformance, dynamics, authority, or
   semantics before executing a run.
6. **Execute reproducibly.** Run deterministic isolated repeats, preserve every
   candidate in the ledger, and distinguish repeat jitter from a systematic defect.
   Automated runs must not change operator-owned review or campaign lifecycle state.
7. **Compare completely.** Evaluate the predeclared primary metric and all guardrails
   against the frozen baseline. Use profile-aware metrics and verify at least one
   distinct geometry, stress, or coupling case so a reusable primitive is not tuned
   only to one route.
8. **Decide and hand off.** Accept, revise, or revert according to the declared rules.
   An accepted software candidate then receives the smallest meaningful realtime
   operator rerun; digital-twin and physical validation remain subsequent layers.
9. **Retain the learning.** Record the chosen and rejected parameters, comparison
   table, decision, remaining limitation, and reopening trigger in this document or
   the linked qualification artifact before closing the work package.

The method is “half automatic”: the system may diagnose, propose bounded candidates,
run isolated checks, compare metrics, and recommend a candidate. It may not silently
change mission truth, broaden authority, transition review state, choose an undeclared
trade-off, or claim physical validity. Those boundaries remain explicit operator and
evidence decisions.

## Change log

- `2026-08-25`: Controller-characterization Mission A baseline review established that
  survey completeness, baseline acceptance, coverage, and recommended A→B→C→D→E
  progression are analysis milestones rather than flight unlocks. Implemented B–E
  commands remain operator-selectable under `REQ-XFR-010`; missing measurements limit
  interpretation and qualification, not command availability.
- `2026-08-23`: Operator hover review established three durable iteration preferences:
  keep a Digital Twin flight's presentation anchor across temporary reconnect/source
  epochs; require measured takeoff altitude/rate capture before horizontal task motion;
  and add larger HOME-centered checkpoint successors when estimator scatter makes a
  0.10 m shape visually ambiguous, without rewriting retained 0.10 m mission identities.
  Controller gains remain unchanged until retained
  target, actuator, repeat, and independent-position evidence can isolate the causal
  control layer.
