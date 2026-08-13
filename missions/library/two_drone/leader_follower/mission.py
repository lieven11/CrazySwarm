"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.2d.leader_follower"
CLUSTER = "COORDINATION_AND_ALLOCATION"
PURPOSE = (
    "Deterministic leader follower planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "Every task has one authoritative owner, assignments and leases remain unique, and all roles finish or enter their declared safe recovery state."
)
NAMED_VARIATIONS = (
    "canonical_nominal",
)
EXECUTES_ON_IMPORT = False
