"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.3d.simultaneous_center_conflict"
CLUSTER = "GEOMETRIC_CONFLICT_RESOLUTION"
PURPOSE = (
    "Deterministic simultaneous center conflict planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The joint planner selects a fully validated separation strategy, or blocks with an exact reason; an admitted run stays outside warning and critical separation limits."
)
NAMED_VARIATIONS = (
    "wide_priority_200_150_100",
    "compact_equal_priority",
    "nominal_equal_priority",
    "wide_unequal_priority",
    "compact_no_hover",
    "constrained_height",
    "vertical_allowed",
    "vertical_forbidden",
    "latency_and_noise",
)
EXECUTES_ON_IMPORT = False
