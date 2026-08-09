"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.2d.perpendicular_crossing"
CLUSTER = "GEOMETRIC_CONFLICT_RESOLUTION"
PURPOSE = (
    "Deterministic perpendicular crossing planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The joint planner selects a fully validated separation strategy, or blocks with an exact reason; an admitted run stays outside warning and critical separation limits."
)
NAMED_VARIATIONS = (
    "compact_equal_priority",
    "nominal_equal_priority",
    "wide_equal_priority",
    "wide_alpha_priority",
    "compact_no_hover",
    "constrained_height",
    "vertical_allowed",
    "vertical_forbidden",
    "latency_and_noise",
)
EXECUTES_ON_IMPORT = False
