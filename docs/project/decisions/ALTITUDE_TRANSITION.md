# Altitude-transition design decision

> Navigation: [requirements index](../requirements/README.md)

Historical design decision supporting motion, tuning, and evidence requirements.

## Altitude-transition design decision from current review

The current canonical and wide cases remain geometry variations of the same family.
The wide case changes the altitude envelope from approximately `0.25..0.65 m` to
`0.20..0.82 m`. The current evidence shows a longer route and duration, more energy
use, and modestly larger tracking error, but no qualitatively new control policy.
Therefore:

- `canonical_nominal` is the profile-development and bounded speed-sweep anchor;
- `wide` remains a vertical-envelope stress case;
- wide does not repeat every canonical profile automatically;
- after a canonical profile is qualified, wide repeats it only when the larger
  climb/descent amplitude can plausibly expose vertical-rate, thrust-headroom,
  tracking, energy, or landing differences; and
- constant-rotor-speed flight is not admitted as an altitude-transition submission.

The implemented initial submission set is intentionally small:

| Submission | Canonical | Wide | Reason |
|---|---:|---:|---|
| Current planner-retimed baseline | Retain reviewed runs | Retain reviewed runs | Establishes existing behavior and geometric delta. |
| Constant path speed, slow anchor | Qualify | Do not duplicate initially | Establishes the primitive with generous control margin. |
| Constant path speed, higher-stress anchor | Qualify after feasibility gate | Repeat after canonical qualification | The wider vertical envelope can expose vertical authority and tracking coupling. |
| One ramped slope/segment-speed schedule | Qualify | Run only if wide adds a declared headroom question | Tests intentional speed transitions rather than arbitrary variation. |
| Bounded vertical-rate / actuator-headroom profile | Derive evidence prerequisite | Preferred stress follow-on | More specific to wide altitude motion than a generic speed copy. |
| Constant motor/rotor speed | Not executable | Not executable | Low-level calibrated diagnostic, not compatible with guaranteed path tracking. |

Exact speed targets are derived from each route's segment lengths and horizontal/
vertical tangent bounds. Bounded allocation then applies acceleration/jerk gates,
while retained execution measures controller/actuator headroom, energy, and terminal
behavior. The initial ratios intentionally produce only a margin-rich anchor and one
higher-stress anchor; they are not a dense parameter grid.

The 2026-08-11 assisted refinement established that the excessive constant-speed
wave was primarily commanded by the old quintic time law rather than created by the
tracker: the repeated 0.18 m/s evidence had an approximately `0.133 m/s` recorded
90% route-speed band, with segment deviations reaching about 55%. The corrected
profile uses explicit entry/exit and knot-transition windows with flat-speed
interiors, samples the generated spline for conformance, and retains safety retiming
when the wide altitude envelope reaches a dynamics margin. Isolated accelerated
post-change runs reduced the constant-speed 90% steady ripple to approximately
`0.019..0.024 m/s`, completed without motor saturation, and showed no component-
velocity reversals in the last two landing seconds. These are software-simulation
results, not physical-controller qualification. The ramped-speed and bounded-
vertical-rate profiles remain segment-specific comparisons and do not use the
constant-speed aggregate-ripple gate.
