# Parameterized mission curriculum WP-23 qualification

| Field | Value |
|---|---|
| Package | `WP-23` |
| Status | `COMPLETE` |
| Date | 2026-08-09 |
| Contract | [`../reference/MISSION_CURRICULUM_V1.md`](../reference/MISSION_CURRICULUM_V1.md) |

## Exit evidence

The default generator produces 30 deterministic cases covering levels 1–5, all three
declared borders, and both seeds. Repeated generation has identical case and manifest
hashes. Every generated mission source parses, its source hash matches, and its plan
compiles under the case's own non-relaxing flight volume with the declared role count.

Level 4 selects `STAGING_HOLD`. Level 5 explicitly forbids staging and admits only
`SPEED_RETIMING` and `HORIZONTAL_DETOUR`; normal Play executes the selected retimed
program with no hover action, warning sample, critical sample, or goal failure. Its
persisted report is consumed through the same deterministic evaluator contract and
becomes a passing hashed curriculum baseline.

The promotion test retains one baseline per generated case, promotes all five levels,
then injects a level-2 critical regression. The result preserves level 1, blocks level
2, and does not promote levels 3–5. Thresholds are unchanged.

## Verification

- The curriculum/package/planning/no-hover/release focused gate passes 17 tests.
- Generation, parsing, and planning of all 30 variants pass in one deterministic test.
- Repository Ruff and strict MyPy pass over 188 source/test/script files.
- The manifest/promotion CLI emits a valid 30-case contract and accepts retained
  evaluator JSON paths without commanding a vehicle.

## Claim boundary

The full variant grid proves deterministic generation, admission, evaluator baseline,
and promotion mechanics. Representative mission families execute through normal Play;
this packet does not claim that every future Cartesian expansion has been simulated.
Three-or-more-drone planning and robustness/failure matrices remain WP-24 and WP-25.
