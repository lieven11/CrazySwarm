# Aerium Control: essential liquid-glass interface

> Project design reference. Planning status is maintained separately in
> [`../work-packages/ACTIVE.md`](../work-packages/ACTIVE.md).

Status: implementation baseline
Date: 2026-08-06
Scope: the main CrazySwarm operator route

## 1. Core decision

The simulation is the interface. Everything else is temporary support.

The previous proposal still contained too much dashboard thinking: a permanent telemetry dock, repeated status chips, four metric tiles, tabs, borders, headings, and text such as “Ready to run.” That information is technically valid but not continuously necessary. It competes with the room and makes the interface feel like instrumentation surrounding a simulation rather than a simulation with precise controls.

The revised interface uses a true-black environment with a few detached liquid-glass surfaces. Controls are brighter than information surfaces. Normal state is quiet. Text appears only when it helps the operator make a decision.

The target feeling is:

> The room is visually uninterrupted. Controls float above it like dark glass. I see only what I need now, and detail appears when I request it or when something is wrong.

## 2. Necessity audit

An element earns permanent screen space only if its absence would make the current operation unsafe, ambiguous, or meaningfully slower.

### Keep visible

| Element | Why it is necessary | Minimal form |
| --- | --- | --- |
| Simulation room | It is the main object of observation and control. | Full viewport. |
| Operating mode | Simulation, Live, Shadow, and Replay must never be confused. | One short mode capsule. |
| Command targets | Commands must have an unambiguous scope: selected drones, or the whole scene when none are selected. | Selected count or `All drones` plus one state dot. |
| Mission control | The operator must be able to choose and start a mission. | One bottom capsule with mission name and play button. |
| Fast Sim scenario controls | Resetting pose and setting battery state are frequent simulation setup actions. | Two independent icon pills immediately right of the mission capsule. |
| Mission deployment | The selected mission's drones, plan, energy, geometry, and coordination constraints must remain inspectable without reopening file setup. | One collapsed-by-default left glass surface with persistent drone tiles. |
| Controlled abort | It must remain immediately available during an active run. | One bright red action visible only while running. |
| Essential flight values | Battery, height, speed, and nearest range materially affect immediate understanding. | One shared glass readout, not four cards. |

### Show only when requested

| Element | Revised location |
| --- | --- |
| Mission library and upload | Mission popover. |
| Trend chart | Expanded flight readout. One chart at a time. |
| Motors, IMU, Flow, ranges, transport, decks | Expanded details sheet. |
| Source clocks, run ID, fidelity, room version, twin residuals | Evidence section inside the details sheet. |
| Connection, authority, preflight, manual control, parameters, replay history | Engineering sheet. |
| Camera presets and layer toggles | Two compact scene-control capsules. |

### Remove from the normal view

- continuous top bar background;
- permanent left rail background;
- permanent telemetry dock;
- Overview / Systems / Evidence tabs;
- separate battery, altitude, speed, and localization tiles;
- “Active vehicle,” “Ready to run,” “Current status,” and other normal-state copy;
- repeated modeled/source chips on every value;
- permanent room/frame label;
- persistent simulation clock;
- card borders around every data group;
- decorative status scores, generic health scores, and progress percentages;
- duplicated mission and abort actions;
- persistent success, cancellation, abort, and failure messages in panels or normal app chrome;
- labels beside familiar camera and navigation icons;
- placeholders for absent telemetry when hiding the surface is clearer.

## 3. Reference evaluation

The new references are useful for their composition, not their light color palette.

### Reference 1

Useful:

- the central model remains unobstructed;
- detached rounded surfaces sit around the edges;
- large surfaces group related information without internal card grids;
- controls appear as small circular points or capsules;
- generous empty space makes each visible number feel intentional.

Avoid:

- large permanent left and right panels;
- pale glass that would fail against a dark moving scene;
- financial widgets that do not map to an operator decision.

### Reference 2

Useful:

- strong black-and-white contrast;
- bright white control capsules over quiet content;
- large liquid radii and soft specular edges;
- independent floating groups instead of one boxed dashboard;
- black content areas used as visual anchors.

Avoid:

- a full management dashboard grid;
- repeated navigation labels;
- ornamental imagery or metrics without operational meaning.

## 4. Spatial model

```text
┌────────────────────────────────────────────────────────────────────────────┐
│  [ AERIUM · SIM ]                         [ vehicle ● ] [ engineering icon ]│
│                                                                            │
│                                                                            │
│                         FULL-BLEED 3D ROOM                                 │
│                                                                            │
│                                                                            │
│                                                                            │
│ [ mission name  ▶ ] [ home ] [ battery ⌃ ] [ camera ] [ layers ] [ flight]│
└────────────────────────────────────────────────────────────────────────────┘
```

There is no continuous chrome around the viewport.

- Top-left: one dark-glass brand/mode capsule.
- Top-right: selected vehicle capsule and one bright engineering icon button.
- Bottom-left: mission capsule followed by separate Fast Sim home-reset and battery-level pills.
- Bottom-center: camera capsule and layer button.
- Bottom-right: essential flight readout, visible only when telemetry exists.
- During a run: controlled abort appears beside the mission capsule.

The center 65% of the viewport contains no interface surfaces.

## 5. Liquid-glass language

### Foundation

| Token | Value | Use |
| --- | --- | --- |
| Scene black | `#000000` | Canvas and page background |
| Raised black | `rgba(8, 8, 8, .72)` | Main floating glass |
| Dense black | `rgba(4, 4, 4, .90)` | Open popovers and sheets |
| Bright control | `rgba(248, 248, 246, .94)` | Primary icon and run buttons |
| Primary text | `#F7F7F4` | Essential values and names |
| Secondary text | `rgba(247, 247, 244, .58)` | Units and short labels |
| Glass edge | `rgba(255, 255, 255, .14)` | Outer edge only |
| Modeled orange | `#FF7A45` | Simulation/model information |
| Observed cyan | `#58D5EE` | Measured/received information |
| Replay violet | `#B49BFF` | Replay/twin information |
| Warning | `#FFD166` | Degraded or stale information |
| Danger | `#FF6673` | Fault and abort |

There are no blue-gray surfaces. Neutral surfaces are black or translucent black.

### Glass construction

Floating surfaces use:

- 22–28 px outer radius;
- black fill with 68–82% opacity;
- 22–32 px background blur and mild saturation;
- one subtle white outer edge;
- a soft white inset highlight along the top edge;
- deep, diffuse black shadow;
- no internal divider lines unless a destructive action must be separated;
- no glow around entire panels.

Controls use brighter fills than data surfaces. The primary run button is near-white with a black icon. Selected camera controls may also become white. Destructive controls remain red rather than white.

## 6. Persistent surfaces

### Brand and mode capsule

Contents:

- Aerium mark;
- `SIM`, `LIVE`, `SHADOW`, or `REPLAY`.

Remove the separate wordmark subtitle and explanatory mode icon. In Simulation mode, the short orange `SIM` label is sufficient source context for normal telemetry.

### Vehicle capsule

Contents:

- selected vehicle name;
- one state dot.

No “Active vehicle” label. No normal state word. Text appears beside the name only for exceptional states: `Offline`, `Stale`, `Fault`, `Emergency`, or `Snapshot`.

### Mission capsule

Idle contents:

- selected mission name, or `Mission` when none is selected;
- one expand chevron;
- one bright run button when the mission can run.

Running contents:

- mission name;
- current phase only if the phase helps explain the scene;
- controlled abort button.

Remove `READY TO RUN`, target labels, execution chips, duplicate running labels, and the always-visible simulation clock. Execution mode remains inside the mission popover; vehicle targeting belongs to the scene and deployment-member controls.

### Fast Sim quick-action pills

This is a reusable simulation-scenario control pattern for this application and later Aerium interfaces.

- Show the controls only for a selected `FAST_SIM` vehicle.
- Place them immediately right of the mission capsule without merging their glass surfaces into the mission chooser.
- Relocation is one 58 × 58 px circular glass control containing only a reset/home symbol. One click returns pose, velocity, attitude, and estimator state to the configured home without changing battery charge.
- Battery is a separate rounded glass pill. Its 46 px primary battery symbol always sets the simulated battery to 100% in one click and must not change pose.
- A narrow up-chevron segment on the battery pill opens a dense-black popover above the control. The upward direction communicates that the menu opens above the bottom edge.
- The battery popover offers one-click presets for `5%`, `10%`, `20%`, `50%`, `75%`, and `100%`, plus a numeric custom field accepting any value from 0 through 100, including decimals.
- Applying a preset or custom value updates visible telemetry immediately; the operator must never need to start another mission to make maintenance state visible.
- A battery level below the configured takeoff minimum or the selected role's mission-specific energy-plus-margin requirement remains selectable for scenario testing. Starting a mission at that level opens a compact orange confirmation banner at the top center, matching ordinary operation notices and never dimming or covering the simulation. It shows the current charge, applicable start minimum, critical threshold when applicable, likely early termination, and compact cancel/run-anyway actions.
- Confirming the warning creates a Fast Sim-only, auditable battery-policy override. It bypasses only takeoff battery admission, mission task-energy admission, and the in-run critical-battery gate; identity, command authority, transport, localization, sensors, geofence, and every other safety check remain enforced.
- Confirmed low-battery runs retain simulated drain and voltage cutoff, so the mission can still fail or terminate immediately. An airborne cutoff advances the zero-thrust rigid body through ground impact and publishes the settled terminal sample; it must never leave an aircraft frozen at its last powered pose. The override must never be accepted for physical or observation-only authority.
- Both controls are disabled while a mission is active. Home relocation additionally requires `DISCONNECTED`. Battery recharge remains available after a terminal low-battery event when live Fast Sim telemetry confirms the selected drone is disarmed and no longer flying; recovery may reconcile `LANDING`, `ABORTING`, `FAULT`, or `EMERGENCY` back to `DISCONNECTED`. This exception is simulation-only and never enables maintenance while airborne.
- Each action has a distinct accessible name, keyboard focus treatment, busy state, and concise completion notice. Icons are never the sole programmatic label.
- On narrow screens, the pair moves above the mission capsule while remaining two visually independent surfaces.

### Mission selection preview

- Selecting a mission stages a read-only scene preview immediately; the Play button remains the only action that connects, arms, or executes vehicles.
- The preview renders every declared mission role at its current parked pose when it already exists, or at its configured home when it has not been provisioned yet. Multi-drone and reserve roles retain one numbered configured-home pad per role.
- Planned paths are calculated per active role so role-dependent branches do not collapse into one misleading combined path. Observation-dependent missions may show bounded static geometry and must label it as preview rather than live evidence.
- Switching missions replaces the preview atomically and never creates runtime vehicles, consumes battery, records mission evidence, or changes command authority.
- The persistent Mission deployment surface identifies the selected plan, so the 3D room does not repeat a `MISSION PREVIEW · not running` label. Starting the mission replaces staged preview drones with observed runtime drones while retaining the mission's grey dashed reference paths and endpoint domes for comparison.
- Existing simulated vehicles are previewed from their current observed parked pose; the mission-declared home remains visible as the numbered relocation anchor. A declared home is used as the start only when the role has not been provisioned yet.
- Starting another mission never reinitializes pose, battery, estimator state, or simulation time. Those scenario variables persist across runs and change only through flight behavior or an explicit operator control such as **Reset drone to home** or **Set battery**.

### Mission deployment and plan overview

- A selected mission always owns one persistent **Mission deployment** surface below the brand capsule. It is independent of the mission-file upload popover and remains present before, during, and after execution.
- Do not repeat the selected mission or uploaded filename beneath the **Mission deployment** heading; the mission chooser already provides that identity.
- The surface is collapsed by default and may be expanded. The mission drone tiles and deployment heading remain visible when collapsed; plan metrics, route detail, positions, minimum separation, handovers, and dock evidence reveal together.
- Drone tiles are the direct command-selection controls. Their blue selection state follows the same multi-selection model as the 3D scene, and a planned drone that has not yet been provisioned is visible but not presented as commandable.
- The expanded plan uses compact visual instruments rather than an audit-data dump: fleet distance, concurrent duration, total planned energy, per-role energy bars, projected battery when charge is known, waypoint counts, and color-keyed X/Y/Z start and home positions.
- Each drone's route uses a visibly brighter grouped surface than the surrounding plan. Show its display name once and omit the duplicate internal role ID.
- Start and Home positions each occupy a full-width row with three unconstrained X/Y/Z value groups; coordinate text must never ellipsize at the normal panel width.
- Begin the expanded content directly with those metrics. Omit the redundant **Plan overview** heading, approval label, and generic mission-objective sentence.
- Minimum separation is visualized directly below the deployment heading and above all drone tiles and route information, with its critical and warning thresholds. It hides with the other expanded details and has no divider line above it; spacing and the instrument background provide grouping.
- Keep plan blockers, confirmation-required findings, and operational limitations because they affect whether Play is safe. Remove plan hashes, safety-case hashes, plugin/version inventories, raw plan IDs, and duplicated role-owner rows from the normal interface.
- Changing the selected mission replaces the overview and reference geometry atomically. Starting execution must not remove the plan overview, grey dashed reference paths, or endpoint domes; colored observed traces accumulate alongside them.
- During active execution, reference geometry is keyed only by the authoritative execution mission ID from the fleet session, matching live run, or locally bound start response. Never fall back to the selected or first library mission; if execution identity is unavailable, show no planned path rather than a wrong one.

### Essential flight readout

This is one continuous glass surface containing four values with spacing rather than boxes or divider lines:

- battery `%`;
- world Z `m`;
- speed `m/s`;
- nearest valid range `m`.

Use 18–22 px tabular values and 9–10 px labels. Normal values are white. Only a threshold crossing receives semantic color. The surface is absent when there is no truthful telemetry.

The readout is collapsed by default whenever truthful telemetry is available; selecting its summary expands or closes it. The expanded panel contains:

1. the same four values;
2. a shared visual instrument strip with battery and clearance half-gauges plus height and speed bars;
3. a single selectable 60-second trend;
4. an open-by-default `Systems` disclosure and a collapsed `Evidence` disclosure.

It does not reproduce a grid of tiles.

The visual instruments are graphical translations of existing values, never additional scores. Battery uses a 0–100% half-gauge. Clearance uses the nearest valid range normalized to that sensor's declared maximum. Height uses the configured room height. Speed uses a clearly labeled operational display range and may saturate without implying a safety limit.

Inside `Systems`, visual density is preferred over repeated coordinate strings:

- motor command uses four aligned progress bars;
- attitude uses three centered Roll / Pitch / Yaw axis meters with degree values;
- IMU acceleration and angular velocity use X / Y / Z bipolar bars;
- Flow quality uses a percentage bar;
- each range uses a bar normalized to the sensor's declared maximum.

Axis colors remain consistent: X cyan, Y orange, Z violet. Every visualization retains a numeric value and unit, so color or bar position is never the only carrier of meaning.

## 7. Popovers and sheets

### Operation notice banner

Operation notices are temporary top-center banners rather than bottom-corner toasts or modal windows.

- The banner is fixed 16 px below the viewport top, centered horizontally, at most 460 px wide, and never dims or blocks the 3D room.
- It uses an opaque near-white surface, black primary text, a subtle neutral edge, a 16 px radius, and a diffuse black shadow so it remains readable against every camera angle.
- A close button with a 34 px target remains at the right edge. The banner also dismisses automatically: ordinary confirmations after 4.5 seconds and mission failures after 7 seconds so the reason can be read.
- Entry is a short downward slide and fade. Reduced-motion environments receive no animation.
- Ordinary notices use one concise line and `role="status"`. A mission failure uses `role="alert"`, a restrained danger-colored heading, and a second neutral detail line.
- Failure content is sourced from the terminal mission or fleet execution result. The first line is always `Mission failed`; the second begins `Reason:` and combines the normalized reason code with the backend message when both exist. The interface never invents a cause; if neither is present it explicitly says that no failure reason was reported.
- Examples: `Mission succeeded`; `Battery set to 100.0%`; and `Mission failed` followed by `Reason: Critical battery — Modeled battery reached authoritative cutoff`.
- A newer notice replaces the existing banner and starts a fresh dismissal timer. Browser reload does not manufacture a notice from an old terminal result.
- Every terminal operation outcome—including success, cancellation, controlled abort, and failure—is emitted once as an operation notice when the state transition is observed. It must never remain rendered inside the mission, fleet, deployment, telemetry, or scene panels after the notice dismisses. Historical outcomes belong only in an explicitly requested history or evidence view.
- When a non-failure terminal result supplies a backend reason code and message, the normalized reason becomes the notice title and the backend message becomes its temporary detail line. For example, `EXECUTION_CANCELLED` is shown as `Execution cancelled`, with the cleanup message below it, and then auto-dismisses like any other ordinary notice.

### Mission popover

A single dense-black liquid panel opens above the mission capsule. It contains only:

- Simulation / Digital twin selector;
- mission list;
- Add Python;

Vehicle targeting remains in the scene-level and deployment-member controls. Terminal results use the temporary operation notice banner and are never repeated persistently in this popover.

### Drone command selection

- A drone can be toggled into or out of the command selection from either its 3D scene object or its deployment-member tile. Both surfaces render the same selection state; observation focus must never create a blue command-selection highlight by itself.
- Clicking an unselected drone adds it without clearing other selected drones. Clicking a selected drone removes it. This supports one, several, or zero selected drones without a modifier key.
- Zero selected drones is a deliberate `All drones` scope. No drone or deployment tile is highlighted blue, and Fast Sim quick actions such as Recharge and Reset target every eligible drone in the scene exactly once.
- With one or more selected drones, quick actions target only those selected IDs. The visible selection and the API target list must always be derived from the same state.

### Flight details

The expanded flight surface opens upward from the bottom-right and remains smaller than 380 × 620 px. `Systems` is expanded by default so live vehicle internals are immediately visible; `Evidence` remains a native disclosure closed by default. The operator can collapse either section independently.

### Engineering

Engineering remains a separate sheet because connection, authority, manual flight, parameters, and history are deliberate workflows. Frequent Fast Sim pose and battery setup lives in the dedicated quick-action pills beside the mission capsule, not in Engineering or mission-file setup. The sheet uses large black glass groups with spacing instead of bordered cards. It must not be visible during normal observation.

### Overlay geometry

An expanded flight panel starts below the top-right vehicle and Engineering controls. These surfaces must never intersect or rely on z-index to cover one another. The flight panel scrolls internally between the top and bottom safe areas. On narrow screens, opening flight details hides scene controls until the panel closes.

### Dense selection menus

Catalog selectors use the same dense-black language as Run files rather than the
operating system's native select window.

- The closed control is a quiet 50 px black-glass row with a readable title, one line
  of secondary context, and a restrained chevron.
- The open menu is bounded to the width of its control and at most 45% of the viewport
  height. Long catalogs scroll inside the menu and never create a screen-sized native
  window.
- Mission-case menus begin with search and a visible result count. Names are converted
  from identifiers to title case; underscores and internal lifecycle codes are not
  operator-facing copy.
- Options are separated near-black rounded rows. The status sits in a stable left
  column, the mission name and context occupy the center, and the current selection
  receives a white check at the right. Hover/focus changes the edge and surface only;
  it never replaces the status color.
- Menu structure is black, white, and neutral gray. Open controls, search focus,
  highlighted rows, and selected rows must not use cyan/blue outlines, blue surface
  fills, or blue glow. Cyan is reserved for semantic source/status meaning, never for
  generic selection chrome.
- Primary option names are at least 12 px, secondary context at least 8.5 px, and
  lifecycle labels at least 8.5 px at the Campaign Lab control scale.
- Fleet scope is always explicit. The selector contains exactly `1D`, `2D`, and `3D`;
  there is no `All` state. `1D` is the default, unavailable sizes are disabled, and a
  cluster change moves to its first available fleet size when necessary.
- Keyboard behavior is mandatory: Enter/Space opens, arrows and Home/End move through
  results, Enter selects, Escape closes, and focus returns to the trigger.

Campaign lifecycle states use both plain language and color, so color is never the
only carrier of meaning:

| Internal lifecycle | Operator label | Color | Meaning |
| --- | --- | --- | --- |
| `DEFINED_NOT_RUN` | `Not started` | Neutral gray | Registered but never run |
| `READY` | `Ready` | Observed cyan | Static checks passed and available to begin |
| `ACTIVE_DEVELOPMENT` | `In progress` | Warning amber | Explicitly selected development work |
| `BASELINED` | `Reviewed` | Replay violet | Accepted evidence is bound as a baseline |
| `PROMOTED` | `Completed` | Healthy green | Qualification and promotion are complete |
| `BLOCKED` | `Blocked` | Danger red | A recorded reason prevents progress |

These meanings and colors remain consistent in selectors, summaries, review queues,
and future campaign-history surfaces.

## 8. Scene treatment

- Use a true-black renderer background.
- Keep the default operator room obstacle-free. Dedicated obstacle scenarios may render configured geometry in neutral black/graphite, never blue-gray; obstacle support remains a scenario capability rather than decorative room furniture.
- Reduce room grid and boundary contrast.
- Keep the selected drone cyan in received observation and simulator truth orange/wireframe.
- Keep planned path grey/dashed and replay violet/dotted. The planned path and endpoint domes remain visible during execution so the operator can compare the colored flown trace against the approved route.
- Remove the permanent room/frame overlay.
- Show camera controls only as icons in a dark capsule; the selected preset becomes bright white.
- Place layers behind one icon button and checklist popover rather than persistent text buttons.
- Keep `No data` only when it prevents the scene from being misread as live; render it as one quiet capsule.

## 9. Truth and state rules

Minimalism must not hide an important distinction.

- `SIM`, `LIVE`, `SHADOW`, and `REPLAY` are always explicit.
- Modeled transport is never labeled as physical radio.
- World Z and Flow ground distance remain separate in details.
- No valid range is unavailable, never zero.
- Stale values freeze and the vehicle capsule says `Stale` with age.
- Completed telemetry says `Snapshot`; it never looks live.
- Replay disables command controls and uses the violet replay identity.
- No generic health score or invented mission percentage is shown.
- Normal state is communicated by absence of warning, not by optimistic phrases.

## 10. Responsive behavior

- Desktop: all five floating regions are independent.
- Compact desktop: flight readout becomes a shorter four-value row; labels may hide but units remain.
- Tablet: mission and flight readouts sit above the bottom edge; expanded surfaces become bottom sheets.
- Phone: observation-only or minimum-size state; manual flight control remains out of scope.

## 11. Acceptance criteria

- The page and renderer use true black rather than dark blue.
- There is no continuous top bar, sidebar, or telemetry dock background.
- The normal viewport contains no metric-card grid and no tab bar.
- At most seven small floating surface groups are visible while idle; the two additional groups are the independent Fast Sim setup pills.
- The center 65% of the simulation is unobstructed.
- `Ready to run`, `Active vehicle`, normal-state status copy, repeated source chips, and persistent clock copy are absent.
- Essential telemetry occupies one shared glass readout.
- Expanded telemetry includes truthful half-gauges and normalized bars without adding persistent tiles.
- Vehicle identity never overlaps the expanded flight panel.
- Fast Sim home reset and battery setup exist as independent pills right of the mission capsule and not in Engineering or mission-file setup.
- Battery setup provides 5/10/20/50/75/100% presets and a validated custom 0–100% value.
- Pose and battery maintenance update visible telemetry immediately and never alter one another.
- Detailed systems and evidence are closed and on demand.
- Primary controls are visibly brighter than informational surfaces.
- Fault, stale, emergency, snapshot, and replay remain explicit without relying on color alone.
- Mission-failure banners show the authoritative reason code/message, remain readable for 7 seconds, and are announced as alerts.
- Existing mission, replay, evidence, and safety behavior remains truthful and functional.
