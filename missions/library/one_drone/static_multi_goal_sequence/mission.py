"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.1d.static_multi_goal_sequence"
CLUSTER = "BASIC_FLIGHT_AND_ROUTE_FOLLOWING"
PURPOSE = (
    "Deterministic static multi goal sequence planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The static multi goal sequence route completes for the canonical nominal variation with smooth motion, bounded tracking error, accepted goal capture, and a landed/disarmed terminal state."
)
NAMED_VARIATIONS = (
    "canonical_nominal",
)
EXECUTES_ON_IMPORT = False
