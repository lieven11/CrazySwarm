# WP-52 through WP-56 cost/value retrospective

> Navigation: [requirements index](../requirements/README.md)

Historical process evidence; not a normative requirement source.

## WP-52 through WP-56 cost/value retrospective

Exact per-turn token telemetry was not available in the retained packet evidence, so
no exact percentage is asserted. Review generations, correction passes, runtime runs,
artifact rewrites, and the portion of usable behavior affected are the available
proxies. On those proxies, the batch delivered substantial real value, but roughly one
third to one half of the later review effort appears avoidable or safely deferrable.
That range is a qualitative process estimate, not measured token accounting.

| Work area | Value judgment | Future treatment |
|---|---|---|
| Case-specific submission registry, selector/API integration, reusable constant-speed and corner-transition capability | Central to the operator's request and worth the implementation cost. | Keep as the minimum useful outcome and deliver in small vertical tranches. |
| Point-density-dependent steering, permissive child/backend binding, unsafe rejection labels, priority/context errors, and component-only work reported as runtime/production | Critical behavior, authority, safety, or claim-truth defects. These could materially change commands or mislead an operator. | `MUST_FIX_NOW`, preferably caught once by pre-freeze perturbation and production-path audits. |
| Comparator identity, metric membership, lifecycle separation, literal row oracles, and non-vacuous symmetric contexts | Necessary for any proposal advertised as a valid causal experiment, but many failures were predictable set/contract errors. | Run one machine audit before review; disable only affected proposals if the shared application remains safe. |
| Mutable historical hashes, preimage reconstruction, and phase-separated audit identities | Useful traceability, but much of R6/R7 was process-created overhead rather than new user behavior. | Fix the workflow pattern once; do not repeatedly reopen product design for bookkeeping that can be safely reconciled separately. |
| R8 relation discriminability and complete per-clause evidence for two surviving alternatives | Scientifically valid qualification concerns, but they did not prevent most of the application from running and the alternatives had a safe disabled state. | After the allowed correction, defer/disable the two alternatives instead of opening R9 unless the operator explicitly prioritizes them. |
| Further polishing of a function whose operator value is uncertain | Worst-case waste even if technically excellent. | `SCOPE_CHALLENGE`: stop and ask before any more design or implementation. |

The main failure was therefore not that the reviews invented meaningless defects.
Most findings were valid. The inefficient decision was repeatedly coupling isolated
qualification completeness to the whole five-packet batch. Future work keeps strict
oracles, but uses a smaller blast radius and a safe disabled/deferred outcome.
