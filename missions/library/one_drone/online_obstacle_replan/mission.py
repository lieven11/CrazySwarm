"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.1d.online_obstacle_replan"
CLUSTER = "DYNAMIC_REPLANNING"
PURPOSE = (
    "Deterministic online obstacle replan planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The update or fault is accepted only with current authority and complete acknowledgements; otherwise it is rejected deterministically and the declared hold, abort, or landing fallback runs."
)
NAMED_VARIATIONS = (
    "dynamic_nominal",
)
EXECUTES_ON_IMPORT = False
