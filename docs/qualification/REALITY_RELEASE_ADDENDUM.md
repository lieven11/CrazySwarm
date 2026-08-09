# Pre-NVIDIA mission-reality release addendum

> Navigation: [documentation index](../README.md)

Baseline commit: `4bd185d967eefcccbfc9a41324b1ef685f976e41`

The Fast Sim v1 release remains `SOFTWARE_VERIFIED` for deterministic dynamics,
canonical scenarios, API/UI integration, replay, and software fault injection. It
is not physical-aircraft evidence and does not by itself qualify adapter parity,
sensor-in-loop control, an Isaac model, a real Crazyflie, or a digital twin.

## Claim classification

| Claim | Classification | Evidence or open gate |
|---|---|---|
| Deterministic Fast Sim reference | `SOFTWARE_VERIFIED` | Fast Sim release gate and baseline commit |
| Exact Tier-A hover source in Fast Sim | `SOFTWARE_VERIFIED` | SHA-256 `fd00838…dc`; baseline hover diagnostic |
| Same source through Fast and mock Isaac | `SOFTWARE_VERIFIED` | all 11 QF artifacts and normalized traces in `tests/reality/test_mission_portability.py` |
| Estimator-in-loop controller boundary | `SOFTWARE_VERIFIED` | controller/truth separation, disturbance, sensor and polling-invariance tests in `tests/reality/test_estimator_and_health.py` |
| Mock gateway transport/failure contract | `SOFTWARE_VERIFIED` | process-boundary matrix in `tests/vehicles/test_adapter_conformance.py` |
| Fast Sim accelerated mission/fault load | `SOFTWARE_VERIFIED` | 1,500 runs, 100 per 11 fault classes, 400 nominal, zero tracked leaks |
| Configured mass, thrust, battery, sensor, environment values | `CONFIGURED_UNQUALIFIED` | Requires Reality WP-04/05 measurements |
| Physical Flow/Multi-ranger behavior | `DEFERRED` | Reality WP-04/05 |
| Physical trajectory accuracy | `UNSUPPORTED` without an independent external reference | Reality WP-05/06 |
| Isaac physical fidelity | `DEFERRED` | NVIDIA model packets plus Reality WP-04/06 evidence |
| Digital twin | `UNSUPPORTED` in the current release | Real adapter, synchronized telemetry, independent truth, Reality WP-06 |
| Formation, enforced separation, allocation, handover, docking | `DEFERRED` | Later fleet work packets and global-reference gate |

No simulator value may be relabeled `PHYSICALLY_MEASURED`. `PHYSICALLY_MEASURED`
is reserved for traceable hardware evidence. Missing fields remain unavailable;
they are never replaced by zero.

## Command lifecycle vocabulary

- `ACCEPTED`: the backend accepted responsibility, but completion is not proven.
- `COMPLETED`: the declared command completion condition was acknowledged.
- `REJECTED`: the backend refused the command before accepting responsibility.
- `TIMED_OUT`: the configured completion deadline expired.
- `UNKNOWN_OUTCOME`: transport/process loss prevents proving whether a command ran.
- Cancel request: a request to stop mission execution; it is not proof of vehicle recovery.
- Abort: supervised recovery intent, normally abort-and-land.
- Emergency: distinct immediate motor-stop intent; it is not a normal abort.

Non-idempotent flight commands are never automatically replayed after reconnect or
an unknown outcome. A new operator/supervisor decision is required.

The consolidated software record is
`config/qualification/reality-wp00-03-software-gate.json`. It contains no hardware,
live Isaac, physical-fidelity, or digital-twin evidence.
