# Mission intent, execution graph, and exact approval v1

| Field | Value |
|---|---|
| Intent | `MissionIntent` v1 |
| Execution | `ExecutionGraph` v1 |
| Approval | `MissionPlanApproval` v1 |
| Compatibility | Restricted Python explicit actions remain supported |
| Browser authority | Review, approve, Play, cancel, abort, emergency-stop |

## Intent and graph

Mission intent freezes the objective, success criteria, roles, phases, completion
conditions, maximum phase durations, planner capability, transitions, and safety
declaration. Compilation rejects missing roles/routes, unknown transition endpoints,
cycles, unreachable phases, phases without a bounded terminal transition, unbounded
retry, and recovery outside the safety declaration.

The compiler emits immutable nodes and edges. Each node binds role IDs and exact route
hashes; each edge names `COMPLETE`, `HOLD`, `RESUME`, `REPLAN`, `RETRY`, `HANDOVER`,
`RETURN_HOME`, `LAND`, or `ABORT`. `ExecutionCoordinator` rejects assignments absent
from the accepted graph or route set. The complete graph remains inside execution
evidence, so reconstruction does not rerun mission source to infer accepted behavior.

Existing restricted Python missions compile as
`RESTRICTED_PYTHON_EXPLICIT_ACTIONS`: their role branches and meaning are retained,
while the generated operational routes, selected policy, recovery capabilities,
execution graph, and safety case are hash-bound around those explicit actions.

## Exact operator approval

The operator flow is:

```text
Preview current source/deployment/world/observations/policy/plugins
        -> review blockers, confirmations, routes, phases, and hashes
        -> POST exact plan hash and finding acknowledgements
        -> receive client-bound, expiring approval
        -> Play recompiles from current inputs
        -> reject any mismatch before provisioning
        -> consume approval once the execution is scheduled
```

An approval binds mission source, deployment, plan, safety case, every selected plugin
manifest, operator client, acknowledgements, and expiry. Mission, policy, world,
obstacle, start observation, battery, route, graph, safety, or plugin changes produce a
different plan and invalidate approval. Unknown, consumed, expired, or other-client
approvals also fail closed.

The Control Center displays the objective, plan and safety hashes, component versions,
phases, route timing/length/energy, and separate blocker, confirmable-risk, and
informational sections. The browser does not rewrite the receipt or run planning,
allocation, recovery, safety, or vehicle-control algorithms.
