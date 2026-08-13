"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.1d.curved_route"
CLUSTER = "BASIC_FLIGHT_AND_ROUTE_FOLLOWING"
PURPOSE = (
    "Deterministic curved route planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The curved route route completes for the canonical nominal variation with smooth motion, bounded tracking error, accepted goal capture, and a landed/disarmed terminal state."
)
NAMED_VARIATIONS = (
    "canonical_nominal",
)
EXECUTES_ON_IMPORT = False
