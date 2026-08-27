# Learnings from the first altitude-transition iteration

> Navigation: [requirements index](../requirements/README.md)

Historical tuning evidence; not a normative requirement source.

## Learnings from the first altitude-transition iteration

| Observation | Durable learning for future feature tests |
|---|---|
| A duration-derived audit initially made requested and achieved speed appear equal while the sampled spline still contained large waves. | Never infer conformance from metadata alone; sample the generated command and compare it with both the request and recorded response. |
| The tracker largely followed the oscillating commanded velocity. | Locate the earliest causal owner. Fixing the time-parameterization layer was more justified than tuning downstream gains. |
| Whole-route ripple was meaningful for constant-speed profiles but misleading for intentionally ramped or vertical-rate profiles. | Declare profile-specific metrics and evaluate steady windows or segments; do not reuse an aggregate gate merely because the plotted field is the same. |
| Terminal deceleration could visually resemble flutter. | Separate intended stopping from instability with a terminal window, reversal count, secondary-peak metric, landing error, and contact/state evidence. |
| The wide case needed safety retiming and therefore did not exactly retain the requested target speed. | A bounded target may yield to declared dynamics limits; report requested, achieved, and limiting constraint rather than hiding the retiming. |
| Isolated repeats reduced constant-speed ripple and showed no saturation or terminal reversals, but used the software simulator. | Retain the quantitative improvement as software qualification only, then use realtime and later digital-twin/physical reruns to test transfer. |
