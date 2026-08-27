# CrazySwarm agent instructions

## Context routing

Start repository orientation with `docs/README.md` and
`docs/project/requirements/README.md`. Read only the domain and workflow documents
selected by their routing tables; do not load the complete requirements catalog,
historical decisions, retrospectives, run evidence, or CSV files by default. For run
analysis, read `docs/guides/RUN_ANALYSIS_PROTOCOL.md` and summarize artifacts before
inspecting row-level CSV windows.

When a change moves an entry point, responsibility owner, public transit boundary,
contract location, or primary test boundary, update `docs/system/README.md`. Ordinary
internal edits do not require map churn.

## Shared hardware and live-runtime ownership

The Crazyradio, physical drone, macOS dashboard service, ports `3001`/`8011`, and the
Local checkout's `.cache/crazyswarm` state form one operator-owned hardware runtime.
They are shared external state, not per-chat test fixtures.

- Ordinary coding, review, diagnosis, and test tasks must not start, stop, restart,
  install, uninstall, rebuild, or replace the persistent dashboard service; kill its
  processes or ports; call physical-flight, readiness, observer-connect, motor-bench,
  or global-motor-stop endpoints; or set/pass `CRAZYSWARM_PHYSICAL_HARDWARE_ENABLED`,
  `CRAZYSWARM_HARDWARE_OWNER`, or `--hardware-owner`.
- A task may touch the live runtime only when the user explicitly asks that same task
  to deploy to hardware, operate the drone, or perform a physical test. Code changes
  and a generic request to test do not imply hardware authority.
- Background/parallel Codex work belongs in a Git worktree. Worktree dashboards are
  simulation-only and receive isolated default ports. They must use injected/fake
  Crazyflie links for tests. Run `scripts/setup_worktree.sh` once when dependencies
  are absent. Never hand a background task physical-radio authority.
- The persistent macOS service is the sole normal hardware owner. Inspect it with
  `.venv/bin/crazyswarm-control hardware-owner status`. If another owner is recorded,
  fail closed; do not bypass, delete, or replace the lease.
- For an explicitly authorized deployment, first confirm backend motor actuation is
  `IDLE` with `stop_required=false`, tell the user that the live runtime will restart,
  deploy exactly once through `scripts/deploy_hardware_dashboard.sh`, then wait for
  service health and report observer state. Never loop on restarts.
- `SUSPENDED` means a named physical operation temporarily owns the radio. Preserve
  and display the authoritative suspension reason, release in `finally`, and resume
  observation automatically. Unrelated work must never suspend the observer.

The operator procedure and failure recovery are in
`docs/guides/HARDWARE_RUNTIME_OWNERSHIP.md`.

## UI design guide

Before creating, changing, or reviewing any user-facing interface, read and follow
`design.md`. Treat its decision tags as implementation and review criteria. Reuse the
existing detailed surface specification in `docs/project/DESIGN.md` where applicable.
If a change introduces a durable new visual or interaction pattern, update
`design.md`; document a one-off exception instead of silently creating a competing
pattern.

## Independent verification for work packets

Apply this full protocol only when the user explicitly asks for independent
verification, a formal gate, qualification, or the strict work-packet workflow. Merely
asking to create, structure, refine, implement, execute, or change a work packet does
not activate independent review. The default for a user-present iteration is the fast
loop: make the bounded change, run proportionate author checks once, deploy when
applicable, and hand it to the user for feedback. Fast-loop work remains
`IMPLEMENTED_UNVERIFIED` and must not be described as independently verified,
qualified, or complete.

Read `docs/project/requirements/workflow/WORK_PACKET_GATES.md` and
`docs/project/requirements/workflow/COST_SCOPE_AND_HANDOFF.md`. Also read
`docs/project/requirements/workflow/PREFREEZE_AND_ORACLES.md` only under the triggers
listed in the requirements index. One related packet batch is one review unit unless
the user asks for a different split.

### Design gate

1. Draft the packet in `docs/work-packages/ACTIVE.md` before implementation. Keep the
   repository's canonical `Status` field and add a separate
   `Independent verification: DRAFT_UNVERIFIED` field.
2. Delimit and hash the exact design payload. Freeze the originating user request,
   durable requirements, affected boundaries, base commit, and relevant preimage
   hashes.
3. Spawn a fresh project-scoped `work_packet_verifier` agent thread. The verifier owns
   finding severity and the gate verdict. The author may fix findings or provide
   contrary evidence, but may not dismiss P0/P1 findings unilaterally.
4. Permit one revision and one focused recheck by that same verifier. Do not start a
   third automatic pass. Unresolved P0/P1 findings leave the design blocked.
5. If the request is design-only, stop after `DESIGN_VERIFIED`; do not implement it.

### Implementation gate

1. Do not implement a packet without a recorded `DESIGN_VERIFIED` result. During work,
   use the canonical status vocabulary and set the separate verification field to
   `IMPLEMENTED_UNVERIFIED` when the author believes implementation is finished.
2. Run the packet's declared checks, then freeze an exact implementation payload
   manifest: base commit, pre/post hashes, and changed/new/deleted files or delimited
   sections. A dirty working tree is never identified only as "the diff."
3. Spawn a different fresh `work_packet_verifier` agent. Give it the original user
   request, accepted design hash, exact implementation manifest, evidence, and every
   documentation claim. It must trace core claims through the real production path and
   require an independent oracle plus a meaningful failure, perturbation, child-case,
   rename/reordering, or boundary counterexample as applicable.
4. Permit one fix pass and one focused recheck by the same implementation verifier.
   Do not start a third automatic pass. P2 limitations may be retained; unresolved
   P0/P1 findings keep the packet unverified/blocked.
5. Reconcile `ACTIVE.md`, `COMPLETED.md`, qualification reports, and operator docs.
   Reviewer acceptance is necessary but does not replace the declared evidence needed
   for `QUALIFIED` or `COMPLETE`.

If the independent agent, configuration, or concurrency slot is unavailable, fail
closed as `REVIEW_BLOCKED` or `IMPLEMENTED_UNVERIFIED`; never substitute same-author
review or create a recursive review loop. The `work_packet_verifier` itself is exempt
from triggering this protocol while reviewing and must not delegate another verifier.
Only mechanical verification-record/status updates and an unchanged ledger move may
follow a passing verdict; any substantive edit invalidates the verdict.
