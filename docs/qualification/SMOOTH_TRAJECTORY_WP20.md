# Authoritative smooth trajectory WP-20 qualification

| Field | Value |
|---|---|
| Package | `WP-20` |
| Status | `COMPLETE` |
| Date | 2026-08-09 |
| Contract | [`../reference/TIME_PARAMETERIZED_TRAJECTORY_V1.md`](../reference/TIME_PARAMETERIZED_TRAJECTORY_V1.md) |
| Backend claim | Fast Sim plus software-only mock capability boundary |

## Exit evidence

The canonical single vehicle starts at x = -1.2 m, takes off to 0.3 m, travels 2.4 m,
and lands. Its 24 source moves compile into one 19.2 s trajectory command. The same
test runs with Fast Sim `ACCELERATED` and `REALTIME` clocks.

Both modes pass with:

- one accepted plan, execution-program, route, and trajectory identity from planning
  through mission result;
- 23 non-stop internal knots at 0.125 m/s and declared stops only at sequence 1 and 25;
- observed in-route speed above 0.04 m/s at every selected interior sample (the
  accelerated reference trial ranged from 0.092 to 0.130 m/s);
- landed x within 0.08 m of the 1.2 m goal and z within 0.001 m of ground;
- terminal `READY`, `MISSION_COMPLETED`, and no nominal timeout; and
- equivalent invariant outcomes in both clock modes.

The unsupported-backend test removes the explicit capability and proves rejection
while the vehicle is still disconnected and before any command is sent.

## Regression and performance evidence

- The full repository run reached 504 passing tests plus one expected live-Isaac skip;
  the only reported mismatch was the newly advertised Fast Sim capability missing
  from its frozen reference artifact. After updating that artifact, the release,
  trajectory, and fleet-load gates pass together (9 tests).
- Repository Ruff and strict MyPy pass over 182 source/test files.
- Existing WP-10 crossing/leader-follower coverage remains on its prior multi-command
  authority pending WP-22 and passes all 11 normal Play coordination tests.
- The fleet storage-load race discovered during the full gate was repaired by making
  recorder flush/materialization a terminal result-visibility boundary. Three
  consecutive software-only load qualifications pass with storage query p95 between
  10.3 and 11.6 ms against the unchanged 50 ms budget.
- OpenAPI and the TypeScript client were regenerated. UI lint, typecheck, 80 unit
  tests, production builds, 3 rendered checks, and a zero-vulnerability audit pass.

## Claim boundary

WP-20 does not claim landing-region capture, predictive multi-drone deconfliction,
case curriculum generation, three-or-more-drone planning, robustness qualification,
live Isaac, digital twin, or physical flight. Those remain WP-21 through WP-25 or
explicitly external work.
