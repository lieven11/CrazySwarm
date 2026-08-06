# Accessibility verification

Scope: UI-WP-07 application shell and UI-WP-08 spatial observer at desktop and
tablet sizes. Phone-sized manual control remains explicitly out of scope.

## Automated checks

- `vitest` and `axe-core` audit the deterministic operator-state gallery.
- Semantic names cover modes, navigation, the map canvas, dialogs, toast status,
  and safety actions.
- The emergency dialog test proves that motor cutoff remains disabled until the
  operator types `STOP`.
- Rendered-HTML tests prove the finished shell and state fixtures are present and
  starter-preview metadata is absent.
- ESLint includes React hooks and JSX accessibility rules.

`axe-core` color contrast is disabled under jsdom because jsdom does not provide
the canvas color parser it requires. The redesigned interface uses the following
monochrome tokens on `#090909`:

| Token | Ratio |
| --- | ---: |
| Primary text `#f4f4f1` | 17.9:1 |
| Secondary text `#b9b9b2` | 9.8:1 |
| Muted text `#777772` | 4.3:1 |
| Emergency text `#ff4d4d` | 5.7:1 |

## Interaction and non-color cues

- A skip link moves focus to the workspace.
- All navigation and scene controls are native buttons with visible focus rings.
- SIM, LIVE, SHADOW, and REPLAY combine text and icon; LIVE also uses a distinct border.
- Health states combine text and symbols; stale and invalid values add explicit
  wording and line treatment.
- Abort is described as controlled recovery. Emergency is described as
  last-resort motor cutoff and requires an explicit phrase.
- Reduced-motion preference collapses animation and transition duration.

## Manual viewport checklist

- Desktop target: 1440 × 1000.
- Tablet target: 1024 × 768, with the contextual inspector hidden when space is tight.
- Below 800 px the setup and room stack vertically; phone-sized manual control
  remains out of scope.

The final browser screenshot pass could not be automated in this run because
local-page inspection was denied by the browser security reviewer. The source,
responsive contracts, rendered HTML, coordinate fixtures, and accessibility
checks are complete; desktop/tablet screenshot baselines remain the only open
verification item.
