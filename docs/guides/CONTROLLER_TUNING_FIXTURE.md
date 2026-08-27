# Controller-tuning fixture setup

The Digital Twin Campaign Laboratory contains a separate **Controller
characterization & tuning** cluster. Its fixture definition is
[`config/fixtures/controller-tuning-box-v1.json`](../../config/fixtures/controller-tuning-box-v1.json).
The committed draft intentionally remains partial. Do not mark it `SURVEYED` or accept
its baseline until every required value describes the built box.

## Coordinate and geometry fields

- The survey origin is the closest inner floor corner. `+X` follows the short side,
  `+Y` follows the long side, and `+Z` is up. All configured fixture poses use this
  corner-origin frame; the geometric center is therefore
  `(inside_x_m / 2, inside_y_m / 2)` rather than `(0, 0)`.
- For every baseline placement, center the drone over the selected red floor X and
  point its front toward `+Y`. Fixture heading is clockwise from `+Y`: `0 deg` points
  front toward `+Y`, `+45 deg` lies between `+Y` and `+X`, and `+90 deg` points front
  toward `+X`.
- `positive_x_wall_label` and `positive_y_wall_label` may bind optional operator wall
  names to the walls reached by the positive axes; they are not flight-geometry gates.
- `inside_x_m`, `inside_y_m`, and `wall_height_m` are internal measured dimensions.
- `floor_markers` records the measured A–E floor X marks in the corner-origin frame.
  Keep directly measured marker distances in `marker_distances`; do not replace those
  observations with only a derived coordinate.
- `nominal_hover_height_m` is an optional default capped at 0.50 m. The Campaign
  Laboratory requires an explicit height for each flight, so this default is not an
  unlock. `safety_clearance_m`, when known, supports analysis and operator warnings;
  it does not disable an implemented controller-characterization command.
- A-E are the authoritative placement stations. Legacy named stations such as
  `CENTER` and `X_POSITIVE` are not global fixture-readiness gates; a motion that
  explicitly targets one must require its coordinates locally. Coordinates name the
  Crazyflie reference point, not a ranger face.
- Each `front`, `back`, `left`, and `right` sensor mount needs its optical-center
  `origin_x_m/y_m/z_m` and a normalized body-frame direction vector. Record placement
  and angular uncertainty when known.
- The current horizontal optical-center offsets are `0.012 m` from the drone center in
  their respective directions. The body frame is `+X` front, `+Y` left, and `+Z` up.
  Only front/back/left/right participate in the wall-based PID fixture model. Up is
  excluded because the box is open; down remains height telemetry and is not part of
  the horizontal wall geometry.

Wall material is part of the characterization record. Wall finish, floor texture
identity, and lighting remain useful baseline metadata but are not geometry gates.
Changing them requires a new fixture version and another Mission A baseline; an
earlier retained run is never rewritten.

The current `1.1-draft` artifact contains preliminary scan-derived A–D marker centers,
base dimensions, the placement/heading baseline, and the four horizontal ranger
offsets. Marker E is provisionally trilaterated at `(0.603, 0.665) m` from the retained
direct measurements `EC = 0.268 m`, `EB = 0.441 m`, and `EA = 0.502 m`. Its three range
residuals fit within 6 mm, but the coordinate remains subject to the scan-derived
anchor uncertainty. The fixture stays `AWAITING_MEASUREMENTS`.

## Survey source and derived runtime geometry

Do not rely on chat context or repeatedly reinterpret the mesh during a run. The
current source scan is `Scaniverse 2026-08-25 185658.glb`, `11,967,612` bytes, with
SHA-256 `0546087236cc762792d0b464de8655679952e738f1138cec7503b61825d214e5`.
It is not yet imported into an immutable project artifact store; the current copy in
Downloads is only the operator's source copy.

The planned import retains the unchanged GLB and records its hash, then generates a
small versioned fixture-geometry artifact containing the GLB-to-fixture transform,
A–E coordinates and uncertainties, inner floor boundary, height-indexed wall
profiles and their uncertainty, and the source hash. Normal prediction and route
analysis use that derived artifact. The source GLB remains available for audit and
reprocessing, but it is not a runtime dependency. A single width/length rectangle is
not sufficient because the cardboard walls bow with height.

## Planned operator workflow

The placement/heading preparation slice is implemented in the catalog and physical-run
contract. Landing-survey entry, compressed bowed-wall geometry, coverage matrices, and
later analysis milestones remain planned.

- The four-level hierarchy is `Controller characterization & tuning` → major mission
  `A` through `H` → placement variant `A` through `E` → the mission-specific motion.
  A–E are reusable placement variants for every implemented major mission, not five
  hard-coded headings or five separate flight programs.
- Each Play action binds `station_id`, fixture heading, height/preset, motion, fixture
  version and geometry hash, controller/estimator snapshot, and an automatically
  assigned repetition number before the action starts. The request remains immutable
  after start.
- Heading is a typed degree input with default `0` and an initial admitted range of
  `0..90`. The convention is `0 = front toward +Y`, `45 = between +Y and +X`, and
  `90 = front toward +X`. Heading is not inferred later from a chat message.
- Mission A runs one motors-off observation at the selected marker and heading. The
  initial height is the surveyed grounded ranger height; raised observations are
  available only with a measured jig/preset. Retain raw ranges, validity, source and
  receive times, attitude, predicted wall intersections, residuals, and opposing-range
  consistency. Marker E remains selectable but is the default holdout: do not refit
  geometry to E while using it to report validation error.
- Mission B uses the same placement and heading inputs, then performs one
  default-PID takeoff, hover, landing, and disarm. Repeats are separate operator
  actions. The run becomes operationally terminal after landing but its external
  position evaluation remains `AWAITING_LANDING_SURVEY` until the operator submits
  the measurements below.
- Missions C–E also reuse the placement variant and heading/height inputs. Motion
  labels must name their command frame, such as `Body forward 5 cm`; the system must
  never present an ambiguous bare `X` when fixture, HOME, and body axes could differ.

After a flight, measure planar distances from the vertical floor projection of the
drone center to at least three non-collinear A–E markers. Four or five measurements
are preferred because they expose a bad reading. Store every raw marker/distance pair,
the stated measurement uncertainty, the derived `(x, y)` coordinate, residuals, and
the solver version on that exact run. A corrected submission creates a new revision;
it does not overwrite the original. Contradictory circles are flagged rather than
silently averaged.

The landing survey establishes only final position. Path, overshoot, settling, speed,
and in-flight disturbance claims must come from retained telemetry and ranger
evidence; they cannot be reconstructed from the touchdown coordinate.

For B–E, geometry resolution converts the selected marker, heading, height, and
body/HOME command into the fixture frame when the required measurements exist. It may
report the swept vehicle envelope, stopping reach, wall profile, clearance, geometry
uncertainty, placement uncertainty, and estimator allowance as analysis and operator
guidance. These values do not form curriculum unlocks or a run-anyway override flow:
an implemented command is directly selectable, and missing characterization data is
reported without pretending that clearance or safety was measured.

Do not tune after A and B alone. First validate the fixture/ranger model in A, collect
repeatable B hover baselines, then run the margin-rich C 5 cm probes plus a small
bounded D yaw and E slow-profile guard set. Diagnose estimator error, ranger/model
error, command tracking, coupling, and final-position error separately. Gain changes
occur only between disarmed runs, change one bounded parameter family, verify readback,
and create a new run identity. A–E collect and diagnose evidence; F–H remain raw until
their controller comparison, refinement, and confirmation workflows are separately
implemented.

## Non-blocking characterization milestones

1. **A — Fixture & sensor baseline:** each A–E marker, typed heading, and admitted
   height is one motors-off observation. Raw ranges can be retained before the survey
   is complete; modeled residuals remain unavailable.
2. Set `survey_status` to `SURVEYED` only after every required field is measured. This
   changes characterization state and model credibility, not flight availability.
3. **B — Default-PID vertical baseline:** retain readable
   `stabilizer.controller=1` and `stabilizer.estimator=2` with each run so the mission
   identity remains truthful. Run repetitions as separate Play actions and review them.
4. **C — XY transitions:** 5 cm before 15 cm and 30 cm remains the recommended learning
   order. It is not an amplitude unlock.
5. **D — Yaw geometry:** small yaw cases remain the recommended first evidence; no
   Mission A/B result enables or disables them.
6. **E — Speed & position:** slow, margin-rich cases remain the recommended starting
   point; no mission-enable flag exists.

The fixture schema intentionally has no baseline-acceptance, enabled-amplitude,
yaw-enable, or speed/position-enable fields. Do not reintroduce them as software flight
gates. Missions F–H remain different: they are raw because no command workflow exists,
not because an earlier mission has not passed.

Missions F–H are intentionally raw catalog stages. They have no commands, controller
switch, gain write, parameter persistence, or automatic promotion behind them.

Every Play action owns exactly one physical run. A motors-off observation offers
**Stop observation**; an airborne run offers **Abort and land**. The fixture does not
grant radio authority, bypass the ordinary supervisor checks, or automatically persist
controller parameters.
