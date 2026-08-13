"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.1d.planar_shape_loop"
CLUSTER = "BASIC_FLIGHT_AND_ROUTE_FOLLOWING"
PURPOSE = (
    "Deterministic planar shape loop planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The planar shape loop route completes for the circle variation with smooth motion, bounded tracking error, accepted goal capture, and a landed/disarmed terminal state."
)
NAMED_VARIATIONS = (
    "circle",
    "rounded_square",
    "figure_eight",
)
EXECUTES_ON_IMPORT = False
