# CrazySwarm agent instructions

## UI design guide

Before creating, changing, or reviewing any user-facing interface, read and follow
`design.md`. Treat its decision tags as implementation and review criteria. Reuse the
existing detailed surface specification in `docs/project/DESIGN.md` where applicable.
If a change introduces a durable new visual or interaction pattern, update
`design.md`; document a one-off exception instead of silently creating a competing
pattern.

## Independent verification for work packets

Apply this protocol only when the user explicitly asks to create, structure, refine,
implement, execute, complete, verify, qualify, or transition one or more work
packets/work packages. It applies whether packet numbers already exist or the user asks
to create them. A mere mention, explanation, status question, ordinary numbered plan,
or unrelated small task does not activate it. An explicit work-packet request takes
precedence over the small-task exemption.

Use the detailed requirements in
`docs/project/WORKFLOW_AND_REQUIREMENTS.md` (`REQ-WFL-013` through `REQ-WFL-027`).
One related packet batch is one review unit unless the user asks for a different split.

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
