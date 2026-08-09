# Reality coupling and claim inventory

> Navigation: [documentation index](../README.md)

Audit scope: code outside `crazyswarm_app.simulation`, operator/API authority,
mission execution, safety, evidence, UI contracts, and project claims.

## Concrete coupling inventory

| Baseline coupling | Baseline location | Resolution |
|---|---|---|
| Runtime stored `SimulatedVehicle` | `api/runtime.py` | Runtime and telemetry consumers now store `Vehicle` |
| Mode/preflight/arming inferred authority from adapter string `sim` | `safety/supervisor.py` | Replaced with `VehicleBackendProfile.authority` |
| Mission-file route inferred simulation from adapter string | `api/app.py` | Replaced with declared authority |
| Twin sides inferred real/sim from adapter strings | `api/app.py` | Replaced with declared authority |
| Duration timeout special-cased adapter `sim` | `safety/supervisor.py` | Replaced with declared duration-aware completion capability |
| Parameter service imported `SimulatedVehicle` | `engineering.py` | Generic capability facade plus simulator-owned provider |
| Clock/fault routes assumed every `Vehicle` had Fast Sim internals | `api/app.py` | Capability-routed `simulation_controls`; unsupported backends fail closed |
| UI collapsed unknown adapters to `sim` and used adapter strings for reset/twin availability | `ui/app/lib/api.ts`, `ControlCenter.tsx` | UI preserves opaque adapter identity and uses declared backend role/authority; missing declarations fail closed |

Static gate: adapter-neutral mission, safety, runtime, evidence, and API authority
layers may refer to backend roles and capabilities, but may not import concrete
simulator classes or grant authority based on adapter identifiers.

## Claim-to-test inventory

| Claim | Classification | Test/evidence |
|---|---|---|
| Continuous health enforcement | `SOFTWARE_VERIFIED` for qualified software profiles | Faults in takeoff/hover/move/land: `tests/reality/test_estimator_and_health.py` |
| Same immutable source on Fast/mock Isaac | `SOFTWARE_VERIFIED` | Full QF corpus and normalized intent traces: `tests/reality/test_mission_portability.py` |
| Observation-dependent Python is online and bounded | `SOFTWARE_VERIFIED` | Tier-B worker/negative corpus tests |
| Gateway process loss cannot become success | `SOFTWARE_VERIFIED` | `tests/vehicles/test_adapter_conformance.py` |
| Delayed/duplicate/reordered/malformed/wrong-source gateway traffic fails closed | `SOFTWARE_VERIFIED` | out-of-process gateway fault matrix and unknown-outcome test |
| Estimator affects control without truth access | `SOFTWARE_VERIFIED` for the reference model | Pure controller-boundary and accumulated-drift tests |
| Snapshot polling cannot change dynamics | `SOFTWARE_VERIFIED` | polling-invariance test in `tests/reality/test_estimator_and_health.py` |
| 1,000+ mixed accelerated mission runs clean up resources | `SOFTWARE_VERIFIED` | `scripts/verify_reality_load.py`; 1,500-run record |
| Three configured vehicles preserve identity | `SOFTWARE_VERIFIED` | Existing canonical three-vehicle scenario |
| Formation or separation enforcement | `DEFERRED` | No qualifying mission-level test exists |
| Real Flow/Multi-ranger response | `DEFERRED` | Reality WP-04/05 |
| Digital twin trajectory fidelity | `UNSUPPORTED` | No real adapter/synchronized independent reference |

The three-vehicle scenario must not be described as formation, collision avoidance,
allocation, or persistent coverage evidence.
