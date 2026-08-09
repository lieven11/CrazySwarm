"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.2d.formation_spacing"
CLUSTER = "COORDINATION_AND_ALLOCATION"
PURPOSE = (
    "Deterministic formation spacing planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "Every task has one authoritative owner, assignments and leases remain unique, and all roles finish or enter their declared safe recovery state."
)
NAMED_VARIATIONS = (
    "canonical_nominal",
    "compact",
    "wide",
)
EXECUTES_ON_IMPORT = False
