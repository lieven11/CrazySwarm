"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.3d.duplicate_assignment_rejection"
CLUSTER = "COORDINATION_AND_ALLOCATION"
PURPOSE = (
    "Deterministic duplicate assignment rejection planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "Every task has one authoritative owner, assignments and leases remain unique, and all roles finish or enter their declared safe recovery state."
)
NAMED_VARIATIONS = (
    "dynamic_nominal",
)
EXECUTES_ON_IMPORT = False
