# Aerium Control: simulation-first interface proposal

Status: proposed design direction  
Date: 2026-08-06  
Scope: the main CrazySwarm operator route (`ui/app/page.tsx`) at desktop and tablet sizes

## 1. Design outcome

The simulation environment becomes the application itself, not one panel inside the application. The Three.js room fills the viewport and remains visually continuous behind a restrained layer of controls. Mission controls sit at the edges of the scene, while all live data is collected in one compact telemetry dock on the right.

The interface remains predominantly black, charcoal, and white. Color is reserved for live data, data provenance, selected actions, and safety state. This produces a modern visual language without turning the operator screen into a generic business dashboard or a neon cockpit.

The intended first impression is:

> I am looking into the simulated room, I can immediately see what the drone is doing, and the information around it explains that scene.

At a 1440 × 1000 desktop viewport, at least 70% of the screen should remain visually attributable to the simulation, and no persistent card should cover the drone or the center of its planned path.

## 2. Evaluation of the current UI

The current implementation has a solid safety and data foundation. It already separates simulation, replay, and live modes; labels provenance; exposes stale data; gives safety actions explicit wording; and has a capable Three.js observer with camera and layer controls. Those behaviors should be preserved.

The weakness is primarily composition and hierarchy, not missing information.

| Area | Current UI | Effect | Proposed change |
| --- | --- | --- | --- |
| Primary focus | The room is a 16:9 block beside a 310 px mission panel and above a separate observation area. | The simulation reads as one module among several. | Make the room canvas full-viewport and layer edge controls over it. |
| Information layout | Observation data expands into a wide auto-fit wall of nearly identical cards below the scene. | The eye has no obvious starting point and related data is scattered horizontally. | Consolidate telemetry into one right-hand dock with Overview, Systems, and Evidence views. |
| Data hierarchy | Room, observation, motors, IMU, flow, ranges, and transport use similar card weight and dense key/value rows. | Critical flight information and engineering detail look equally important. | Show four to six essential flight values first; place detailed sensors and provenance behind clear tabs or expansion. |
| Visualization | Most values are rendered as text, even when they are bounded, directional, or changing over time. | Trends, imbalance, proximity, and degradation require reading many numbers. | Add truthful sparklines, segmented bars, motor bars, and a six-direction proximity visualization. |
| Typography | Many labels and sources are 7–10 px, uppercase, and monospaced. | The interface feels compressed and technical rather than calm and modern. | Use 12 px as the dense-label floor, 14 px body text, 24–32 px key values, and monospace only for identifiers or precise values. |
| Color | Almost all non-emergency information is grayscale. | Graphs and data relationships are hard to scan. | Keep surfaces monochrome, but consistently color observed, modeled, healthy, warning, critical, and replay data. |
| Mission setup | Mission selection, upload, target, simulator reset, and launch permanently occupy the left column. | Setup controls compete with the scene even after a run begins. | Collapse setup into a mission dock; open an anchored sheet only when choosing or editing a mission. |
| Controls | Camera/layer controls live in a full-width strip below the canvas; advanced controls open a large drawer. | The room feels framed and separated from its controls. | Float camera and layer controls directly over the lower scene edge; retain the drawer for advanced engineering work. |
| Data state | Provenance is present but repeated as low-emphasis footer text. | Truthfulness exists, but it is hard to scan. | Use compact source chips and consistent color/line styles while retaining explicit text labels. |
| Responsive behavior | At narrow widths, large sections stack vertically. | The scene stops being the anchor and the page becomes a long dashboard. | Keep the scene full-bleed; move telemetry and mission setup into bottom sheets on tablet. |

### What should remain unchanged

- Simulation must remain the default mode; detecting hardware must never arm or launch it.
- The distinction between simulated model, measured data, configured data, planned data, and replay must remain explicit.
- A completed run must appear as a frozen snapshot, not as live telemetry.
- Abort-and-land and emergency motor cutoff must remain distinct actions with the existing confirmation safeguards.
- The browser remains an operator client; safety validation stays in the backend.
- Scene layers must keep meaningful visual differences in addition to color.

## 3. What to take from the references

The screenshots point to two complementary families: spatial interfaces where a model or image is the main surface, and modern bento dashboards where a few data cards carry clear visual hierarchy.

| Reference | Useful direction | What not to copy |
| --- | --- | --- |
| 1 — dark building simulation with right analytics panel | Best overall composition: a dominant 3D world, restrained top chrome, and one consolidated analytics surface. | The analytics panel is a little too tall and opaque for a small indoor flight scene. |
| 2 — hotel image with frosted bottom cards | Controls and data feel attached to the visual background; rounded tonal cards are quiet and modern. | The low-contrast glass and oversized decorative whitespace would reduce operator legibility. |
| 3 — building model with spatial callouts | Contextual labels can connect a measurement to an object or position in the world. | Many floating cards around the model create occlusion and an unclear reading order. |
| 4 — current Aerium observation area | Contains the correct data and explicit source truthfulness. | This is the main layout problem: a large, flat card wall with tiny text, no trend visualization, and substantial unused space. |
| 5 — dark satellite telemetry cards | Strong bento rhythm, compact bars, localized chart color, and clear metric scale. | Avoid decorative glow, ornamental equipment drawings, and arbitrary aggregate scores. |
| 6 — dark orange dashboard | Good surface separation, restrained accent use, rounded cards, and clear grouping. | Do not let the bento dashboard replace or shrink the simulation. |
| 7 — light security dashboard | Excellent hierarchy, large values, segmented severity visualization, and generous spacing. | The light palette is outside the requested direction, and its persistent navigation is too large. |
| 8 — task dashboard with colorful graphs | Useful chart density, clear legends, compact KPI tiles, and readable tooltips. | Avoid business-dashboard patterns such as a long KPI strip and table-first composition. |

The resulting design uses the spatial composition of references 1–3, the tile and chart craft of references 5, 6, and 8, the readability of reference 7, and the safety/provenance rigor already present in reference 4.

## 4. Design principles

1. **World first.** The scene is the only full-size surface. Everything else is edge chrome, a dock, a popover, or a temporary sheet.
2. **One telemetry home.** Live values should never be distributed across unrelated areas. The right dock is the single place to inspect them.
3. **Overview before engineering.** The default view answers state, position, motion, energy, proximity, and mission progress. Raw sensors remain one click away.
4. **Color carries meaning.** A color represents the same source or state everywhere; it is never added merely for decoration.
5. **Truth before polish.** No synthetic health scores, fake trend lines, or implied measurements. Every graph has a real source, unit, time window, and unavailable state.
6. **Calm during normal operation.** Normal data uses restrained contrast. Warning and emergency states become prominent only when they occur.
7. **Progressive disclosure.** Setup and engineering controls expand when requested and recede during observation.

## 5. Desktop spatial model

The room canvas is positioned behind the full shell (`position: fixed; inset: 0`). UI surfaces are layered above it with an unobtrusive edge scrim where needed for contrast.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│  AERIUM   SIMULATION   mission / phase / clock          Engineering  ABORT  │
├─────┬───────────────────────────────────────────────────────┬────────────────┤
│     │                                                       │ Drone 01   ●  │
│  M  │                                                       │ OVERVIEW SYS… │
│  R  │              FULL-BLEED 3D ROOM                       │                │
│  E  │                                                       │ Battery  Alt  │
│     │        path, trace, drone, range rays                  │ Speed     Loc  │
│     │                                                       │                │
│     │                                                       │ 60 s trend     │
│     │                                                       │ ────────────   │
│     │                                                       │                │
│     │ [camera] [layers]                    [fit / fullscreen]│ proximity /    │
├─────┴───────────────┬───────────────────────────────────────┤ motor balance  │
│  Mission name  SIM  │  phase · elapsed       Run / Stop     │ source + age   │
└─────────────────────┴───────────────────────────────────────┴────────────────┘
```

### Persistent regions

- **Top status bar:** 56–60 px tall, translucent charcoal, spanning the viewport.
- **Left rail:** 52–56 px wide with Mission, Room, and Engineering destinations. Labels appear in tooltips and for keyboard focus, not as a wide permanent sidebar.
- **Telemetry dock:** 360–384 px wide, 12 px from the top/bottom/right shell edges, with a maximum height that leaves the mission dock visible.
- **Mission dock:** 52–60 px tall and centered along the lower scene edge. It expands into a setup sheet before a run and becomes a progress/control bar during a run.
- **Scene tools:** compact floating button groups in the bottom-left and bottom-right safe areas of the canvas.

The left rail, top bar, and bottom dock may overlap the canvas, but the telemetry dock should reserve a right-side safe area in the scene camera framing. Camera fitting must account for the dock so the drone and planned path remain in the visible scene area.

### Overlay restraint

- No permanent tile may sit in the central 50% of the scene.
- Persistent UI should cover no more than 30% of the desktop viewport.
- Scene callouts are limited to the selected drone, target, active fault, and operator-selected sensor ray.
- Translucency is used only where the scene remains readable. Text surfaces need an effective opacity of at least 88% plus a subtle blur or local scrim.
- The telemetry dock can collapse to a 48 px handle, leaving a nearly unobstructed simulation view.

## 6. Main components

### 6.1 Top status bar

The bar communicates global state, not detailed controls.

Left to right:

- compact Aerium wordmark;
- explicit mode badge: Simulation, Live, Shadow, or Replay;
- active mission and current phase;
- simulation/source clock with stale indicator;
- connection state;
- Engineering button;
- persistent **Abort and land** action during flight.

Emergency motor cutoff remains in the engineering/safety surface and keeps the typed confirmation. It must not become an easy-to-hit decorative red icon.

### 6.2 Simulation stage

The room uses the full available viewport and retains the existing geometry, geofence, obstacle, home, vehicle, planned path, historical trace, simulated truth, velocity heading, and range-ray layers.

Visual refinements:

- Use a near-black floor with a low-contrast grid rather than a black rectangle surrounded by borders.
- Increase the selected drone's silhouette and selection halo slightly so it remains visible when zoomed out.
- Use a soft cyan received-estimate trace and a white dashed planned path.
- Use orange wireframe or dotted treatment for simulator truth/model overlays, not color alone.
- Fade non-selected vehicles to 55–65% opacity.
- Use a subtle vignette/scrim only beneath UI edges, never across the whole room.
- Place the room ID and frame in a small scene label instead of a full telemetry card.

Scene interaction:

- drag to orbit, wheel/pinch to zoom;
- double-click or keyboard shortcut `F` to fit the active path;
- camera presets live in one three-icon segmented control;
- layer control opens a checklist popover rather than a row of text buttons;
- selecting a drone or sensor ray highlights the related tile in the telemetry dock;
- all scene controls remain keyboard reachable.

### 6.3 Mission dock

The permanent left mission panel is replaced by a compact dock.

**Before a run**

- selected mission name and source file;
- Simulation / Digital twin mode chip;
- selected vehicle;
- primary **Run simulation** action;
- chevron or Mission button that opens setup.

**Expanded setup sheet**

- mission library and upload;
- execution mode;
- vehicle target;
- simulator recharge/reset;
- latest-run summary.

This sheet is anchored to the mission dock and is approximately 340 px wide. It closes after selection and never permanently consumes scene width.

**During a run**

- mission name and current backend phase;
- elapsed simulation time, not an invented percent if total progress is unknown;
- run state icon and text;
- **Abort and land** action.

**After a run**

- explicit Completed, Aborted, or Failed state;
- “Frozen snapshot” label;
- Replay and Export evidence actions.

### 6.4 Telemetry dock

This is the single home for operational data. It uses three tabs: **Overview**, **Systems**, and **Evidence**. The dock header always shows selected vehicle, state, observation class, freshness, and data age.

#### Overview

The default arrangement is a compact two-column tile grid:

1. **Battery** — large percent, voltage/current subtitle, segmented horizontal bar, short rolling sparkline.
2. **Altitude** — world-frame Z as the primary value; Flow ground distance appears separately when available so the two are never falsely merged.
3. **Speed** — magnitude derived from the received velocity vector, with the X/Y/Z vector available on expand.
4. **Localization** — bounded quality bar with its model/source label.
5. **Flight trend** — full-width 60-second chart. A small selector switches between Altitude, Speed, Battery, and Current rather than mixing incompatible units on one axis.
6. **Proximity** — full-width six-direction glyph with the minimum range called out and exact values accessible in a compact list.

The top four tiles should be visible without scrolling at a 1000 px-high viewport. Secondary visualizations may scroll within the dock, while its header remains sticky.

#### Systems

- four motor command bars, aligned for immediate imbalance detection;
- thrust and current available per motor on selection/focus;
- IMU acceleration and angular-velocity mini-plots;
- Flow quality and drift-prone label;
- range sensor list;
- physical radio or modeled transport tile;
- detected decks/sensor models.

Systems content uses collapsible groups, but the currently abnormal group automatically moves to the top and opens.

#### Evidence

- observation class, frame, freshness, source clock, source time, receive time, and age;
- run ID with copy action;
- configured room version and fidelity manifest;
- replay state and event position;
- digital-twin residuals when a qualified twin session exists;
- explicit “No external ground truth” when appropriate.

Long identifiers remain available here instead of wrapping inside primary tiles.

### 6.5 Engineering drawer

The existing drawer remains an on-demand surface for connection, authority, preflight, arming, manual movement, parameters, run history, replay, export, and safety actions.

Its visual treatment should match the new tile system, but it should not become another dashboard. Use one focused workflow at a time:

- Target and authority;
- Flight controls;
- Parameters;
- Run history and replay;
- Evidence export.

On desktop it may open as a 420–480 px right sheet over the telemetry dock. On tablet it opens as a bottom sheet. Opening it must pause conflicting scene keyboard shortcuts.

## 7. Visual language

### 7.1 Neutral foundation

| Token | Value | Use |
| --- | --- | --- |
| Canvas | `#07090B` | Room background and deepest surface |
| Shell | `#0B0E12` | Top and edge chrome |
| Tile | `rgba(20, 24, 29, 0.90)` | Default tile over the scene |
| Tile elevated | `#191E24` | Selected/expanded tile and popovers |
| Border | `rgba(255, 255, 255, 0.10)` | Quiet separation |
| Border strong | `rgba(255, 255, 255, 0.20)` | Selected and focus-adjacent separation |
| Text primary | `#F4F6F8` | Main labels and values |
| Text secondary | `#A9B0B8` | Descriptions and units |
| Text muted | `#747D87` | Inactive or tertiary metadata |

The visual tone is soft black and clean white, with cool neutral grays. Avoid pure-white large backgrounds, glossy gradients, heavy bloom, and borders around every row.

### 7.2 Semantic color

| Meaning | Color | Application |
| --- | --- | --- |
| Received/observed telemetry | Cyan `#4CC9E8` | Current trace, observed chart series, selected sensor |
| Simulated/model data | Orange `#FF7A45` | Model overlays, modeled chart marks, Simulation selection |
| Replay/digital-twin comparison | Violet `#A78BFA` | Replay trace, twin residual series |
| Healthy/within limits | Green `#7DDF8A` | Status only, never generic decoration |
| Warning/degraded | Amber `#F2C45E` | Threshold crossing and stale-near-limit state |
| Critical/emergency | Red `#FF5D68` | Fault, danger, abort/emergency state |
| Planned/configured | White `#E9ECF0` | Dashed planned path and configured boundary |

Color is concentrated in charts, small progress fills, selected controls, and state dots. Approximately 85–90% of the screen remains neutral.

Every color meaning also has a label, icon, pattern, or line style. For example, planned is white and dashed, replay is violet and double/dotted, and stale data is both dimmed and labeled **Stale**.

### 7.3 Typography

- Keep Geist Sans for the interface and Geist Mono for IDs, clocks, and exact vector values.
- Page/status title: 18–20 px, semibold.
- Tile value: 24–32 px, medium, tabular numerals.
- Tile title/body: 13–14 px.
- Dense label/source chip: 11–12 px; never 7–9 px.
- Use sentence case for visible labels. Reserve uppercase for short source/state chips.
- Units sit on the same baseline as values at approximately 55–65% of the value size.

### 7.4 Shape and depth

- Tiles: 14–16 px radius.
- Buttons and fields: 9–11 px radius and at least 40 px hit height.
- Status chips: pill radius.
- Use one-pixel borders, a subtle `0 12px 40px rgba(0,0,0,.28)` dock shadow, and restrained backdrop blur.
- Use an 8 px spacing grid. Tile interiors generally use 14–16 px padding.
- Hover changes border and surface tone; it does not move or scale cards.

## 8. Data visualization specification

### General chart rules

- Each chart names its metric, source, unit, and visible time window.
- Current value is visually primary; charts explain change rather than replacing the number.
- Use a 2 px series stroke, quiet grid lines at 6–8% white, and no decorative fill unless it communicates a threshold.
- Tooltips use exact values and simulation/source time.
- Charts update at 5–10 Hz at most, even if telemetry polling is faster.
- Disable sweeping entrance animations. New points may interpolate over 100–180 ms.
- Break the line across absent or invalid samples; freeze and label stale samples.
- A chart has a text summary for assistive technology and keyboard-accessible latest/min/max values.

### Recommended visualizations

| Data | Visualization | Rationale |
| --- | --- | --- |
| Battery percent | segmented bar + 60 s sparkline | Bounded value and trend are both important. |
| World Z / speed / current | selectable line chart | Change over time matters; incompatible units stay separated. |
| Localization or Flow quality | horizontal bounded bar | Clear 0–100 scale with threshold bands. |
| M1–M4 command | four aligned vertical or horizontal bars | Makes imbalance visible while retaining exact values on focus. |
| Six range rays | six-axis proximity glyph + exact list | Preserves direction and nearest-obstacle context. |
| Twin deviation | paired/residual line chart | Shows divergence without pretending the simulator is ground truth. |
| Attitude | compact roll/pitch horizon plus numeric yaw | Spatial orientation is easier to scan than a three-number string. |

Do not add a donut, gauge, or “health score” simply because a reference contains one. Gauges are appropriate only for a genuinely bounded quantity with meaningful thresholds.

## 9. Truthful data mapping

The first implementation can be built from the existing `DashboardModel` without inventing backend data.

| Display | Existing source | Treatment |
| --- | --- | --- |
| Battery | `telemetry.batteryPercent`, `batteryVoltage`, `batteryCurrent` | Label as Battery model in simulation. |
| Altitude | `telemetry.estimate.z` | Label World Z; do not call it ground clearance. |
| Ground distance | `telemetry.flow.groundDistanceM` | Separate Flow tile/value with modeled and drift-prone source. |
| Speed | magnitude of `telemetry.velocity` | Mark as Derived; preserve vector details. |
| Position | `telemetry.estimate` | Show X/Y/Z and frame. |
| Attitude | `telemetry.attitude` | Convert radians to degrees for display; retain explicit unit. |
| Localization | `telemetry.localizationPercent` and label | Use bounded bar only when present. |
| Motors | `telemetry.motors.readings` | Show command first, then thrust/current details and model version. |
| IMU | `telemetry.imu` | Preserve simulated-model/body provenance. |
| Proximity | `telemetry.ranges` | Show each freshness state and maximum; no ray means unavailable, not zero. |
| Link/transport | `telemetry.radio` or `telemetry.transport` | Never present modeled transport as physical radio quality. |
| Mission state | `latestRun.status` and `latestRun.phase` | Use explicit phase and elapsed clock; only show percent if later supplied truthfully. |
| Twin residual | `twin.latestDeviation` | Always include validity and ground-truth availability. |

The current client stores recent position points only. Trend tiles for battery, altitude, speed, current, IMU, and quality require a bounded in-memory rolling telemetry buffer or a backend time-series query. Until that exists, those tiles show the current value and an explicit **Trend unavailable** state rather than generated history.

## 10. State behavior

| State | Scene | Telemetry dock | Controls |
| --- | --- | --- | --- |
| Starting/offline | Dim room placeholder or last non-live room with Offline banner | Skeletons stop after timeout and become explicit unavailable tiles | Retry service is primary; flight actions absent. |
| Disconnected | Configured room remains visible; drone appears only if a truthful snapshot exists | Target and configured values remain; live values say No data | Connect/recharge available where valid. |
| Idle/ready | Normal room and current drone pose | Overview values visible; charts begin accumulating | Mission dock offers Run simulation. |
| Running | Active trace and plan; selected vehicle emphasized | Live tiles and trend charts update; abnormal tile rises to top | Dock shows phase, elapsed time, Abort and land. |
| Stale | Last pose remains but is ghosted and timestamped | Affected values freeze, line breaks, amber Stale chip appears | New commands requiring fresh data are disabled by existing policy. |
| Fault | Fault location/object is highlighted when known | Fault tile replaces the first overview slot and explains the failing source | Recovery actions are explicit; no celebratory animation. |
| Aborted | Trace freezes and endpoint is marked | Aborted reason and final values are retained | Replay/export are offered. |
| Emergency | Scene and chrome receive a restrained red edge treatment | Emergency state is textually dominant | Further flight controls disappear; evidence actions remain. |
| Completed snapshot | Frozen scene with Snapshot badge | Last values remain with completed timestamp | Replay/export and next mission are available. |
| Replay | Violet/dotted replay trace and fixed replay clock | Evidence tab becomes prominent; values are labeled Replayed | Only replay controls are enabled; command controls remain disabled. |

## 11. Responsive behavior

### Desktop: 1280 px and wider

- Full edge-chrome layout as specified.
- Telemetry dock 360–384 px wide.
- Overview tiles use two columns.
- Engineering opens as a right sheet.

### Compact desktop/tablet landscape: 900–1279 px

- Telemetry dock becomes 320–340 px and uses one primary column where necessary.
- Left rail remains icons only.
- Mission dock shortens labels but retains explicit action text.
- Engineering opens over the telemetry dock.

### Tablet portrait: 720–899 px

- The full-bleed room remains the background.
- Telemetry becomes a draggable bottom sheet with collapsed, half, and full heights.
- Mission setup opens as a separate bottom sheet; it is never shown simultaneously with expanded telemetry.
- Camera tools remain floating above the current sheet height.

### Below 720 px

Phone-sized manual flight control remains out of scope. Provide a deliberate observation-only layout or an explanatory minimum-size state instead of squeezing safety controls into a long stacked page.

## 12. Accessibility and operator safety

- Maintain at least WCAG AA contrast on every text-bearing overlay regardless of the scene behind it.
- Keep native buttons, visible focus rings, skip navigation, reduced-motion behavior, and explicit dialog semantics.
- Provide non-color state cues and chart summaries.
- Use at least 40 × 40 px targets; destructive actions should be separated spatially from routine controls.
- Never require hover for values, units, source, or safety information.
- Announce connection, stale, fault, mission completion, and replay transitions through appropriate live regions without announcing every telemetry sample.
- Preserve the typed `STOP` confirmation for emergency motor cutoff.
- Camera keyboard shortcuts must be disabled while a form field or modal is active.

## 13. Performance constraints

- Keep the Three.js renderer isolated from chart component updates; telemetry tiles should not rebuild the scene.
- Maintain the existing bounded path history and add bounded, metric-specific rolling buffers.
- Render detailed charts only while their tab is visible; use lightweight SVG or canvas primitives rather than multiple heavy chart runtimes.
- Cap visualization updates independently of the API polling frequency.
- Restrict backdrop blur to the top bar, telemetry dock, and open sheets; provide an opaque fallback.
- Preserve reduced-motion and render-FPS instrumentation.

## 14. Proposed component structure

```text
ControlCenter
├── SimulationStage
│   ├── RoomScene
│   ├── SceneStatusLabel
│   ├── CameraControls
│   └── LayerPopover
├── TopStatusBar
├── EdgeNavigation
├── MissionDock
│   └── MissionSetupSheet
├── TelemetryDock
│   ├── TelemetryHeader
│   ├── OverviewGrid
│   │   ├── MetricTile
│   │   ├── TrendTile
│   │   └── ProximityTile
│   ├── SystemsView
│   └── EvidenceView
├── EngineeringSheet
├── SafetyDialog
└── ToastRegion
```

Reusable primitives should include `MetricTile`, `SourceChip`, `StatusDot`, `SegmentBar`, `Sparkline`, `TrendChart`, `MotorBars`, `ProximityGlyph`, `EmptyData`, and `StaleOverlay`.

## 15. Implementation sequence

1. **Recompose the shell.** Make `RoomScene` full-bleed; replace fixed mission and scene-control strips with edge overlays; move existing observation content into a right dock without changing data behavior.
2. **Establish the visual system.** Apply the neutral and semantic tokens, updated type scale, consistent tile primitive, and accessible source/status chips.
3. **Build the Overview.** Add current-value tiles first, then a bounded client-side time-series buffer and truthful trend visualizations.
4. **Add Systems and Evidence.** Rehouse motors, IMU, Flow, ranges, radio/transport, decks, provenance, run, and twin details.
5. **Refine scene coupling.** Add safe-area-aware camera fitting, selected-object highlighting, and limited contextual callouts.
6. **Qualify states and viewports.** Update visual fixtures for idle, running, stale/fault, aborted, emergency, completed snapshot, and replay at desktop and tablet sizes.

## 16. Acceptance criteria

- The simulation visibly occupies the entire application background and at least 70% of the desktop viewport remains scene-readable.
- Mission setup no longer consumes a permanent 285–310 px column.
- Operational data has one clear home in a collapsible right dock.
- Battery, altitude, speed, localization, trend, motor balance, and proximity use appropriate visual treatments when their data exists.
- All charts identify source, unit, time context, unavailable state, and stale state.
- No display invents a combined health score, ground truth, radio measurement, or mission progress percentage.
- Simulation, received observation, planned path, replay, safety, warning, and unavailable states are visually and textually distinct.
- The completed state is visibly a frozen snapshot; replay never enables commands.
- The interface is usable at 1440 × 1000 and 1024 × 768 without turning into a long stacked dashboard.
- Existing safety confirmations, keyboard access, focus visibility, reduced motion, provenance, and evidence workflows remain intact.

