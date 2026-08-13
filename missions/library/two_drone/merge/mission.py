"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.2d.merge"
CLUSTER = "GEOMETRIC_CONFLICT_RESOLUTION"
PURPOSE = (
    "Deterministic merge planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The joint planner selects a fully validated separation strategy, or blocks with an exact reason; an admitted run stays outside warning and critical separation limits."
)
NAMED_VARIATIONS = (
    "canonical_nominal",
)
EXECUTES_ON_IMPORT = False
