"""Data-only campaign behavior template; catalog discovery never imports this file."""

TEMPLATE_ID = "template.1d.boundary_constrained_route"
CLUSTER = "CONSTRAINTS_AND_OPTIMIZATION"
PURPOSE = (
    "Deterministic boundary constrained route planning and execution with "
    "terminal-state and evidence classification."
)
EXPECTED_OUTCOME = (
    "Forbidden strategies are rejected, hard limits are never weakened, and the selected candidate is optimal in the declared bounded objective order."
)
NAMED_VARIATIONS = (
    "canonical_nominal",
    "compact",
    "wide",
)
EXECUTES_ON_IMPORT = False
