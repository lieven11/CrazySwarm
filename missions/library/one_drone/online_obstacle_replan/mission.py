"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.1d.online_obstacle_replan"
CLUSTER = "BASIC_FLIGHT_AND_ROUTE_FOLLOWING"
PURPOSE = (
    "Deterministic online obstacle replan planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The online obstacle replan route completes for the dynamic nominal variation with smooth motion, bounded tracking error, accepted goal capture, and a landed/disarmed terminal state."
)
NAMED_VARIATIONS = (
    "dynamic_nominal",
)
EXECUTES_ON_IMPORT = False
