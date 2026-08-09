"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.2d.leader_loss"
CLUSTER = "FAILURE_RECOVERY_AND_REPLANNING"
PURPOSE = (
    "Deterministic leader loss planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "The update or fault is accepted only with current authority and complete acknowledgements; otherwise it is rejected deterministically and the declared hold, abort, or landing fallback runs."
)
NAMED_VARIATIONS = (
    "canonical_nominal",
    "compact",
    "wide",
)
EXECUTES_ON_IMPORT = False
