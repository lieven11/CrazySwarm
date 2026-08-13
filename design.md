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
- Selection chrome is neutral black and white. Semantic colors remain reserved for
  lifecycle, source, and safety meaning.
- Dropdowns and repeated controls use identical widths and alignment.
- Long menus are bounded and scroll internally.

### Status and badges

- Show status when it changes what the user should understand or do.
- Use plain-language labels plus color or a symbol.
- Keep lifecycle meaning stable everywhere:
  `Not started`, `Ready`, `In progress`, `In review`, `Completed`, `Blocked`.
- Success is usually communicated by the completed result or a temporary notice, not
  a permanent green badge on every surface.

### Details and evidence

- Use a native disclosure for optional technical detail.
- Summaries should describe what is inside and may include a small count.
- Keep the disclosure closed by default unless the contained information is required
  for the current workflow.
- Do not expose hashes or raw IDs in the default view. Provide a copy action when an
  identifier is genuinely useful.

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

