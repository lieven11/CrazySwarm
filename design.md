# CrazySwarm UI design guide

Status: authoritative implementation guide  
Applies to: every user-facing interface in this repository  
Detailed product specification: [`docs/project/DESIGN.md`](docs/project/DESIGN.md)

This file defines the durable design decisions that every new UI implementation and
UI change must follow. The detailed product document describes specific CrazySwarm
surfaces; this guide describes how to make design decisions consistently.

## How to use this guide

Before implementing a user-facing change:

1. Identify the decision tags that apply.
2. Design the smallest interface that completes the operator's task.
3. Reuse an existing pattern before introducing a new one.
4. Verify the result in the real rendered interface at its intended viewport.
5. Record any deliberate exception and why it is safer or clearer.

Decision priority is always:

1. truth and safety;
2. task completion;
3. clarity;
4. simplicity and consistency;
5. visual polish.

Minimalism must never conceal risk, uncertainty, authority, mode, or failure.

## Decision register

| Tag | Decision | Acceptance test |
| --- | --- | --- |
| `[SIM-01]` | Every visible element must earn its space. | Removing it would make the current task unsafe, ambiguous, or meaningfully slower. |
| `[SIM-02]` | The simulation and current task are the interface. | Supporting chrome does not compete with the main scene or decision. |
| `[SIM-03]` | Use progressive disclosure. | Primary facts are visible; technical, historical, and diagnostic detail is collapsed or opened on demand. |
| `[TXT-01]` | Copy is short, plain, and decision-oriented. | The user can understand the state or action on the first read. |
| `[TXT-02]` | Show each fact once. | Names, statuses, explanations, and actions are not repeated across adjacent surfaces. |
| `[LAY-01]` | Alignment communicates structure. | Peer controls share edges, widths, spacing, and baselines; indentation exists only for real hierarchy. |
| `[LAY-02]` | One visual hierarchy leads each surface. | There is one primary subject or action, followed by supporting state, then optional detail. |
| `[CMP-01]` | Components represent concepts, not decoration. | A container groups a meaningful workflow or data relationship, not one isolated value. |
| `[CMP-02]` | Controls use familiar, consistent behavior. | Similar actions use the same component, location, labels, states, and keyboard behavior. |
| `[STA-01]` | Normal state is quiet; exceptional state is explicit. | Warnings, failures, stale data, and blocked actions are visible without persistent success noise. |
| `[VIS-01]` | Use the established black liquid-glass language. | Surfaces, typography, radii, and contrast match the existing product rather than creating a second theme. |
| `[VIS-02]` | Color has stable semantic meaning. | Color supports text or symbols and is never the only state indicator. |
| `[RSP-01]` | Responsive layouts reflow instead of compressing. | Content remains legible and controls remain operable at supported widths without overlap. |
| `[A11Y-01]` | Accessibility is part of the component contract. | Keyboard, focus, names, semantics, contrast, reduced motion, and touch targets are verified. |
| `[TRU-01]` | The interface shows authoritative state only. | Values, units, modes, freshness, and unavailable states are truthful and never inferred for decoration. |
| `[MOT-01]` | Motion explains change. | Animation is brief, purposeful, interruptible, and removed for reduced-motion users. |
| `[VAL-01]` | Rendered behavior is the design oracle. | Tests pass and the actual UI is checked for hierarchy, wrapping, clipping, overlap, and interaction. |

## Simplicity and information density

Apply `[SIM-01]`, `[SIM-02]`, and `[SIM-03]` to every surface.

- Start with the user's immediate question: what is happening, what matters, and what
  can I do next?
- Keep only the information required to answer that question in the default view.
- Put hashes, IDs, route internals, raw evidence, diagnostics, history, and advanced
  controls behind a named disclosure unless they are required for the current
  decision.
- Prefer one composed summary over several metric cards.
- Prefer spacing and typography over borders around every item.
- Do not add headings, helper text, badges, or icons solely to make a surface feel
  complete.
- Do not create UI for unavailable data when hiding the surface is more truthful.
- Empty space is useful. Do not fill it with secondary statistics or explanatory copy.

Use this three-level information hierarchy:

1. **Primary:** the current subject, critical state, and next action.
2. **Supporting:** the few facts needed to choose or understand that action.
3. **Technical:** evidence, provenance, identifiers, configuration, and history shown
   on demand.

## Writing and labels

Apply `[TXT-01]` and `[TXT-02]` before changing layout to fit more words.

- Use sentence case for headings, labels, and buttons.
- Prefer concrete nouns and verbs: `Preview plan`, `Move to review`, `Battery 75%`.
- Avoid internal enum names, underscores, implementation terminology, and unexplained
  abbreviations in operator-facing copy.
- Target 1–3 words for labels and buttons. Use more only when shortening would make the
  action ambiguous.
- Keep helper copy to one short sentence. If several sentences are necessary, the
  content probably belongs in a disclosure, detail view, or documentation.
- Do not repeat a title in its subtitle, a status in body copy, or a selected value in
  a nearby heading.
- Do not narrate normal state with phrases such as `Ready to run`, `Current status`,
  `Everything looks good`, or `Active vehicle`.
- State failures directly and preserve the authoritative reason. Never invent a cause.
- Tooltips supplement a visible label; they do not carry essential information.
- Units stay attached to values. Use consistent precision and terminology.

Good:

> **Expected outcome**  
> Lands inside the accepted region with bounded tracking error.

Avoid:

> **Expected outcome for this mission case**  
> This section displays the expected outcome that should occur when the selected
> mission case has completed successfully.

## Layout and hierarchy

Apply `[LAY-01]` and `[LAY-02]`.

- Use an 8 px spacing rhythm. Prefer 8, 16, 24, and 32 px for structural gaps, with
  smaller optical adjustments only when necessary.
- Align peer controls to the same left and right edges. Decorative left borders,
  offsets, or indentation must not make a peer look like a child.
- Use indentation only to express a real parent-child relationship.
- Keep one clear reading direction. Desktop may use two panes; narrow screens must
  become one ordered vertical flow.
- Reserve the strongest contrast for the primary action or current selection.
- Keep supporting actions visually quieter and destructive actions distinctly red.
- Do not resolve collisions with z-index. Give each item real layout space and verify
  long labels at the narrowest supported width.
- Overlays must have bounded height, internal scrolling where needed, a visible close
  control, Escape behavior, focus containment, and focus return.
- The central simulation area should remain visually uninterrupted; detached surfaces
  stay near viewport edges.

## Component rules

Apply `[CMP-01]` and `[CMP-02]`.

### Surfaces and cards

- One surface represents one concept or workflow.
- Do not wrap every row or value in a separate card.
- Use outer grouping, spacing, and subtle tone changes before adding dividers.
- A summary card should normally contain a title, one concise outcome, and at most a
  few decision-relevant facts.

### Buttons and actions

- Place the primary action where the user finishes the workflow.
- Use one primary action per decision point.
- Button labels describe the result, not the implementation.
- Disabled controls remain understandable through visible context or a concise title;
  never rely on opacity alone to explain why an action is unavailable.
- Icon-only controls require an accessible name and should be used only when the icon
  is familiar in context.

### Selection controls

- Use segmented controls for small, mutually exclusive sets.
- Use a dropdown for longer or searchable sets.
- Campaign preparation uses the same numbered hierarchy for every mission cluster:
  `1 Mission cluster`, `2 Major mission`, `3 Variant`, then `4 Motion`. Selecting any
  discovered simulation item immediately binds its first descendant mission; there is
  no separate `Use mission` confirmation. In ordinary 1D flight preparation, the
  second layer retains exactly `Flight`, `Target`, `Level path`, `3D path`, and
  `Shape`. Layer 2 shows only the mission name, without a redundant variant count.
  Selected values and their menu choices use the same type size. At layer 3, show the
  lifecycle as a small semantic-color dot beside the selected variant and every
  available menu choice, while retaining its plain-language status for assistive
  technology. Keep immutable case IDs and planner package names in technical detail.
- Directly adjustable motion controls use one-word labels: `Balance`, `Speed`,
  `Accuracy`, and `Smoothness`. All four remain visible as the flat fourth hierarchy
  layer without a surrounding card or disclosure. Show units and the safety-resolved
  value beside a focused slider, not inside its label. For checkpoint motion,
  Accuracy ends at the selected mission's authored goal tolerance. For an all
  single-drone fly-through route, it ends at the authored flight-volume route span so
  the control can progress from exact tracking through corner cutting to a direct safe
  shortcut.
  If neither contract is present, bind it to goal-region dimensions and then the
  flight-volume span. Never expose the transport schema's generic accuracy ceiling as
  an operator choice. World, obstacle, dynamics, and terminal guards remain hard at
  every Accuracy value.
- Selection chrome is neutral black and white. Semantic colors remain reserved for
  lifecycle, source, and safety meaning.
- Dropdowns and repeated controls use identical widths and alignment.
- Long menus are bounded and scroll internally.

### Status and badges

- Show status when it changes what the user should understand or do.
- Use plain-language labels plus color or a symbol.
- Keep lifecycle status independent from selection. The Campaign footer is a status
  picker only; its `Not started`, `In progress`, `In review`, and `Completed` controls
  never select or deselect the mission bound by the catalog hierarchy.
- Keep lifecycle meaning stable everywhere:
  `Not started`, `Ready`, `In progress`, `In review`, `Completed`, `Blocked`.
- Success is usually communicated by the completed result or a temporary notice, not
  a permanent green badge on every surface.
- Do not attach a routine `Eligible` badge to a mission or preparation choice. Every
  discovered simulation mission remains enabled regardless of implementation or
  qualification metadata. Planner, backend, and hard safety checks run after
  selection and preserve their exact failure reason. Unavailable optional technical
  submissions stay disabled in the closed technical disclosure.
- Superseded run evidence uses a plain `Old` label and one full-width historical
  divider. Keep those rows inspectable and quieter than current runs; violet may
  reinforce their historical meaning but never replaces the text label.

### Details and evidence

- Use a native disclosure for optional technical detail.
- Summaries should describe what is inside and may include a small count.
- Keep the disclosure closed by default unless the contained information is required
  for the current workflow.
- Do not expose hashes or raw IDs in the default view. Provide a copy action when an
  identifier is genuinely useful.
- In review surfaces, lead with the outcome and large evidence graphs. Keep provenance,
  planning authority, hashes, and coordinate reconciliation in a closed evidence
  disclosure.
- Review graphs are direct inspection controls: each graph has a visible expand affordance,
  a text alternative, keyboard operation, and expands in place without losing review
  context.

### Digital-twin evidence

- Selecting Digital twin places the connected-drone summary in the existing upper
  deployment position, not inside the Mission panel. Use the same compact drone-card
  hierarchy as Simulation, with the configured drone label in place of a simulated
  role. Its disclosure owns the exact binding, first-seen identity capture,
  connection failure, and process-local Pause action. Measured freshness, provenance, and
  channel data belong in the expandable readout. Simulation missions and mission
  upload stay absent from Digital twin. When real missions exist, expose them through
  the same bounded Campaign Laboratory shell, tabs, two-pane layout, dense selectors,
  focus behavior, and responsive reflow as Simulation. Only the mission catalog and
  execution authority differ; modeled rehearsals and measured physical runs remain
  labeled separately.
  The selector changes the presentation context, not observer connectivity: an
  already paired observer keeps recording across Simulation/Digital twin switches.
  Saving a complete URI requires one explicit exact-match confirmation; that save is
  the pairing action. It connects, captures, and persists the first measured identity
  without a second confirmation panel, then keeps automatic observation enabled across
  application restarts. A later different measured identity fails closed and requires
  editing and saving the exact connection before it can replace the binding. Physical
  actions show `Suspended` while they
  hold the radio, name the authoritative owning operation, and resume observation
  automatically afterward. While suspended,
  the expandable sensor readout switches to clearly labeled mission telemetry from
  the physical command link that owns the radio; it must not hide live IMU, range,
  attitude, power, or other measured families merely because the observer link yielded
  authority. Unrelated build,
  simulation, and chat activity never suspends the observer. `Pause observer` releases
  the link for the current service process only; a service restart resumes bounded automatic
  reconnection for the trusted binding. While reconnect supervision is between
  attempts, present `RECONNECTING` and `Waiting for radio`, never the misleading
  manual-intent label `Enable observer`. A dashboard refresh restores the last Simulation/Digital twin
  environment, Mission panel visibility, and Campaign Laboratory workspace, tab, and
  selection. This browser-local navigation state never restores command authority or
  an active physical command. Block switching while a Simulation operation is active.
- The Digital twin room remains one observation-only subject projection. Show `SHADOW`, the exact
  configured drone label, and `1 observed`; it never carries a simulation mission,
  plan, fleet, target, quick-action, Engineering, or flight-control state into the
  observed-drone projection. Idle observation leaves the room without a drone marker or
  trace. Once a physical flight starts, its first received HOME-frame estimator position
  anchors the drone at the scene center. Later mission samples move it by measured metric
  displacement, rotate it from measured attitude, and extend its observed trace. A temporary
  observer reconnect or source-clock epoch change preserves that flight anchor and trace;
  only the physical-flight boundary or a measured vehicle identity change starts a new
  anchor. The projection disappears when the physical flight ends. This presentation transform never
  changes the retained HOME-frame source or creates WORLD evidence.
- Campaign Laboratory owns physical-mission selection, preparation, and retained
  review; it does not own arming, disarming, takeoff, or live motor-output controls.
  The selected physical mission projects into the ordinary bottom mission capsule,
  whose Play/Stop position is the sole execution entry point shared with Simulation.
  Pairing, a selected mission, and fresh supervisor truth with a known arm state and
  `flying=false` are required before Play is enabled. Missing or stale supervisor
  truth keeps Play disabled. When the grounded drone reports `armed=true`, the Play
  operation sends and confirms a preflight disarm on the exact paired URI before
  estimator reset, arm, and takeoff. The commissioning baseline remains the first-flight
  action: estimator reset/convergence, 0.30 m takeoff, 30-second hover, landing, and
  disarm. The same gated surface then offers a progressive contained-flight curriculum:
  a 12-second hover; 0.10 m forward, left, and right return moves; a later 0.20 m return;
  immutable, non-physical 0.10 m checkpoint L, square, and triangle catalog entries
  plus centered 0.40 m physical successor variants; a straight 0.20 m out-and-back path;
  and 0.10 m or 0.20 m offset landings. Each flight resets and verifies the estimator,
  captures 0.30 m altitude and bounded vertical rate before task translation, and uses the
  fixed takeoff frame. Non-shape routes remain within 0.20 m of home; the centered
  checkpoint shape successors keep their authored center within 0.29 m and within
  0.32 m including
  the retained 0.03 m estimator allowance, below the 0.34 m hard center boundary. Every
  route commands horizontal motion at no more than 0.10 m/s and excludes yaw and altitude maneuvers.
  Checkpoint missions hold for two seconds at authored stops; the continuous straight
  mission adds no checkpoint dwell. Ground readiness may physically arm for three
  seconds while recording telemetry, then disarm without takeoff. Do not
  place manual confirmation checklists in this surface; automatic link, estimator, and
  fault preflight owns admission. Battery and range observations are learning data and
  do not gate these actions. Digital Twin exposes physical actions only—Simulation
  rehearsals belong in the Simulation environment. A contained physical flight start
  returns immediately to backend-owned operation
  state. From `STARTING` through landing/disarm, the bottom Play position becomes a
  global `Abort and land` action; a loading spinner never occupies the only stop
  control. That state and action survive mission-panel closure and browser refresh.
  Abort interrupts the remaining plan, commands a controlled landing followed by
  disarm on the live link, and records the operation as aborted rather than completed.
  The click acknowledges immediately as `ABORTING`; backend ownership completes the
  radio sequence so a local HTTP timeout can never be presented as an abort failure.
  If command acknowledgement is lost or the backend restarts with a nonterminal
  operation marker, replace Play with `Abort and land` and retain `Stop unconfirmed`
  until an exact-URI recovery or current observer explicitly reports both disarmed and
  not flying.
  Grounded arm-state normalization remains a backend detail of Play; do not replace
  the mission capsule with a separate arming or disarming action. A retained or
  unconfirmed nonterminal physical-flight marker still replaces Play with
  `Abort and land`, preserving exact-URI recovery after connection loss or restart.
  Direct-PWM Motor bench controls are not exposed as a selectable Digital twin mission.
  Retain only the global recovery presentation needed for stale actuation state from an
  earlier process or version: the bottom mission dock keeps `Stop motors` visible while
  output is active, stopping, failed to stop, or unconfirmed after process loss. It must
  never expose a control that can raise output. A lost link is `Motor output ·
  Unconfirmed`, never zero by inference. Global stop is idempotent without the original
  session ID, and a replacement API process clears a retained override before reporting
  idle.
- Digital Twin exposes controller work as a second physical mission cluster named
  `Controller characterization & tuning`. It reuses the same four-level selector and
  bottom Play/Stop location as Basic flight. Major missions A–E remain individually
  selectable; floor markers A–E are the placement variants inside every implemented
  major mission, while heading and height are compact run inputs below the hierarchy.
  Heading defaults to `0 deg`, uses `0 = front toward +Y`, and initially admits only
  `0..90 deg` toward `+X`. A Play action freezes the selected placement, heading,
  height, fixture identity,
  and repetition into exactly one observation or flight, never the whole campaign. A
  motors-off fixture observation uses `Stop observation`, does not create a room flight
  projection, and retains raw ranger evidence. After a flight, Campaign Review may
  collect three or more marker distances from the landed drone-center projection and
  bind the raw measurements plus trilaterated result to that run. Do not repeat a
  generic `Setup required` label on every placement or motion. Show incomplete fixture
  characterization once as a non-blocking supporting warning, keep exact missing fields
  in technical detail, and leave every implemented B–E command selectable. Use
  `Unavailable` only when the selected motion lacks command inputs or an implementation,
  never for survey completion, baseline acceptance, coverage, or recommended progression.
  Missions F–H remain selectable `Raw`
  stages with no steps or executable action until their workflows are intentionally
  implemented. Raw is not presented as ready, failed, or qualified.
- Digital Twin exposes `Cushioned acrobatics` as the third mission cluster. Its first
  visible motion is `Hover → boost → fast roll → recover → land`, with one immutable
  positive-roll 360-degree body-rate profile. It uses a two-stage operator workflow:
  Play starts and captures a 0.50 m hover, then the backend exposes one mission-only
  `Flip` action beside `Abort and land`. Flip is absent before capture, accepted once,
  and followed by a measured recovery interval and automatic landing. The takeoff hover
  position is the HOME reference; measured X and Y must each stay within ±0.50 m while
  waiting, flipping, and recovering. Landing position remains observational rather than
  a success target. Do not add a browser-only cushion checkbox or expose roll-rate,
  thrust, or direct motor PWM as operator sliders. Technical detail names the 100 Hz
  rate-mode stream, onboard PID/X mixer ownership, measured four-motor outputs, and
  zero-rate commander-priority handoff. Present the workflow as implemented but
  unverified until physical evidence exists.
- Keep twin evidence inside the existing room/Campaign review hierarchy. The room
  remains the spatial overview and Campaign `Review` owns retained run/session
  inspection and comparison. The compact flight readout contains current operational
  telemetry only; it does not host provenance or evidence disclosures. Do not
  introduce a competing dashboard shell.
- In the expanded flight readout, keep the mission overview visible above the focused
  telemetry category. Height, scalar drone speed, battery, and nearest-range history
  remain individually scaled; every category then shows its combined history first
  and one independently scaled plot per channel underneath.
- The compact Digital twin summary prioritizes current drone measurements: battery
  voltage, Roll/Pitch with Yaw, and nearest valid range with direction. Keep the drone
  name, source ownership, pairing counters, channel counts, and reconnect state in
  their existing connection or Link surfaces. A stale current value must say that it
  is stale.
- The expanded Digital twin readout keeps one mission overview above the focused
  diagnostic category, without a second Overview tab, simulated task summary, or model
  comparison. Match Simulation's temporal usefulness with compact 60-second measured
  histories in Mission overview and a large combined history beneath each available
  sensor family. Mission overview prioritizes battery voltage, derived tilt, and the
  nearest valid range, adding height only when trusted position samples exist. The
  selected tab is the category heading; the content panel does not repeat that heading
  or add a redundant source/freshness caption. Histories accept only current received
  measurements, reset at telemetry owner/session/vehicle boundaries, and never fill a
  missing physical channel with predicted, modeled, or scene-derived data. Use a
  cockpit-style attitude horizon for measured Roll, Pitch, and Yaw; represent ranges in clearly
  labeled Top and Front orthographic views; use a 1 m close-range scale; and mark
  exact readings beyond 2 m violet as beyond close range, with visible text that
  distinguishes this local range-scale exception from replay/comparison. Use factual
  link counters/clocks rather than an inferred stability score. In `Link`, lead with a
  visual radio-state row, factual packet-success gauge, and last-ACK age. Group packet
  success/loss and retry quality as separate delivery meters; align uplink/downlink
  rates with their own congestion bars; add measured quality/rate histories; and move
  raw clocks, exact counters, queue/USB/reconnect diagnostics, and alignment into one
  Technical details disclosure. Never merge loss and retry into a composite score or
  label a reported failure boundary as a hardware root cause.
- Keep measured orientation and inertial motion together: the Digital twin `Attitude`
  category shows its cockpit horizon, Roll/Pitch/Yaw, acceleration, and gyro readings.
  The adjacent category is `Motors`, with four separately labeled M1–M4 measured PWM
  percentage bars. Missing motor output remains explicit and is never replaced with
  inferred thrust, current, or modeled values.
- Keep World Z, scalar speed, and battery as three evenly spaced peer values in the
  compact flight summary. Preserve the battery warning and critical tones.
- Motor plots may omit the first three powered seconds once that interval has elapsed,
  so the steady-state oscillations determine the visible scale. Keep the underlying
  telemetry unchanged and label the active startup trim beside the plots.
- In the room, observed/received paths are cyan, model predictions are orange, and
  replay or historical comparison is violet. Planned authority remains grey/dashed.
  Every color has a visible text legend and source label.
- A twin timeline is a review graph set, not live command authority. It uses one shared
  source-time cursor across actual/predicted path, sensor, motor, residual, obstacle,
  and replan channels. Missing, stale, incompatible, and unqualified channels remain
  explicit and are never bridged with invented values.
- Activating a plotted point moves that shared cursor and the room/replay marker to the
  same retained source sequence. The focused readout names the drone position,
  accepted plan/reference, commanded and observed motion, obstacle/replan state, IMU,
  and individual motor values available at that sequence. Interpolated and unavailable
  values are labeled explicitly.
- Start with outcome, actual-versus-predicted path, and the primary residual. Put
  channel provenance, hashes, frames, calibration identity, and raw timing inside a
  closed evidence disclosure. Individual motors remain separately inspectable.
- Desktop and narrow layouts preserve graph units, source labels, cursor time, and
  quality state. Wide graph grids become one vertical sequence rather than shrinking
  text or clipping controls.
- The served surface requires loading, empty, unavailable, stale, error,
  expanded/collapsed, keyboard/focus, and reduced-motion states. Canvas/SVG plots have
  equivalent text summaries and never use color alone to communicate a result.

### Empty, loading, and error states

- Loading copy says what is loading, without a paragraph of explanation.
- Empty states use one sentence and, when useful, one next action.
- Errors name the failed operation and preserve the backend reason.
- Never present missing, stale, modeled, replayed, or unqualified data as live truth.

## Visual language

Apply `[VIS-01]` and `[VIS-02]`. The implemented CSS tokens in
[`ui/app/globals.css`](ui/app/globals.css) are the source of truth.

- Backgrounds are true black or translucent black, never blue-gray dashboard panels.
- Floating surfaces use restrained blur, a subtle light edge, generous radius, and a
  diffuse dark shadow.
- Primary controls are brighter than informational surfaces.
- Use the sans font for readable interface copy and the mono font for compact labels,
  units, identifiers, and technical metadata.
- Use large type sparingly. Most hierarchy should come from weight, contrast, spacing,
  and placement.
- Avoid decorative gradients, ornamental illustrations, excessive glow, and borders
  around every internal group.

Semantic colors are stable:

| Meaning | Color |
| --- | --- |
| Observed or received information | Cyan |
| Modeled or simulated information | Orange |
| Replay or comparison information | Violet |
| Healthy completion | Green |
| Warning, degraded, or stale | Amber |
| Failure, danger, or destructive action | Red |

Never use a semantic color for generic decoration or selection emphasis.

## Responsive behavior

Apply `[RSP-01]`.

- Design desktop and narrow layouts together; do not treat mobile as a later shrink
  pass.
- Reflow multi-column content to one column before text or controls become cramped.
- Allow labels to wrap when the full meaning matters. Truncate only secondary,
  recoverable context.
- Keep primary controls reachable and at least 40 px high where space permits.
- Do not allow header actions, badges, or downloads to overlap. Group related actions
  in a flex or grid container that owns their layout.
- Sheets and dialogs must fit within the dynamic viewport and scroll internally.
- Hide secondary scene controls while a narrow-screen sheet needs that space.

Required visual checks for a substantial surface:

- its intended desktop viewport;
- its narrowest supported desktop or tablet width;
- long realistic labels and values;
- expanded and collapsed states;
- loading, empty, disabled, error, and overflow states when applicable.

## Accessibility and interaction

Apply `[A11Y-01]`.

- Use semantic HTML before adding ARIA.
- Every interactive element is keyboard reachable and has a visible focus treatment.
- Dialogs trap focus, close with Escape, and return focus to the trigger.
- Menus support Enter/Space, arrows, Home/End, Escape, and focus restoration.
- State is not communicated by color alone.
- Icon-only actions have programmatic labels.
- Touch targets should be approximately 40–44 px even when the visible glyph is
  smaller.
- Respect `prefers-reduced-motion` and `prefers-reduced-transparency`.
- Live notices use the correct `status` or `alert` semantics and do not persist after
  their usefulness ends.
- Canvas and visual instruments retain a text or keyboard-accessible equivalent.

## Truth, safety, and state

Apply `[TRU-01]` and `[STA-01]`.

- `SIM`, `LIVE`, `SHADOW`, and `REPLAY` remain explicit.
- Modeled data is never presented as observed hardware data.
- Unavailable is not zero. Unknown is not healthy. Stale is not live.
- Completed telemetry is a snapshot, not a continuing live stream.
- Command scope and selected targets must be unambiguous.
- Destructive, physical, or authority-changing actions require stronger confirmation
  than reversible inspection actions.
- Normal state is quiet. Warnings and failures become prominent only when they are
  relevant and actionable.
- Do not add generic scores, progress percentages, or success claims without an
  authoritative source and defined meaning.

## Motion

Apply `[MOT-01]`.

- Use motion to show entry, exit, expansion, selection, or continuity.
- Keep transitions short and calm, generally around 120–220 ms.
- Avoid looping motion except for a genuine in-progress indicator.
- Do not animate layout in a way that moves the user's target unexpectedly.
- Reduced-motion mode removes nonessential transitions and animation.

## Implementation and validation

Apply `[VAL-01]`.

- Reuse existing components and tokens before adding variants.
- Keep presentational decisions in components and styles; do not duplicate design
  constants across business logic.
- Preserve real content during visual testing. Placeholder text often hides wrapping
  and density failures.
- Test interaction behavior, not class names alone.
- Run type checking, linting, relevant unit tests, and the production build.
- Inspect the rendered interface at the viewport where the change will be used.
- Check for overlap, clipping, unintended scroll, inconsistent alignment, focus loss,
  unreadable contrast, and console errors.
- A technically passing build is not sufficient if the rendered hierarchy is noisy or
  ambiguous.

## Design review checklist

Before considering a UI change complete, answer yes to each applicable item:

- [ ] Can anything be removed without harming safety, clarity, or task speed?
- [ ] Is the primary task or decision obvious within a few seconds?
- [ ] Is technical detail disclosed progressively?
- [ ] Is every visible sentence necessary and concise?
- [ ] Is each fact shown only once?
- [ ] Do peer controls align without decorative offsets?
- [ ] Is there one primary action per decision point?
- [ ] Are normal, loading, empty, disabled, warning, and failure states truthful?
- [ ] Are semantic colors used consistently and reinforced with text or symbols?
- [ ] Does the layout reflow without overlap at supported widths?
- [ ] Can the complete workflow be used with a keyboard?
- [ ] Are focus, accessible names, reduced motion, and touch targets correct?
- [ ] Was the real rendered UI inspected with realistic content?
- [ ] Do relevant tests, type checks, linting, and the production build pass?

## Exceptions and evolution

New durable patterns must be added to this guide with a new or updated decision tag.
One-off exceptions must be documented next to the implementation with the applicable
tag and a concise reason. Safety, truth, or platform requirements may override a
visual rule; aesthetic preference alone may not.
