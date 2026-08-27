# Cushioned acrobatics control profile

Status: `IMPLEMENTED_UNVERIFIED` · physical execution: `OPERATOR_GATED`

The third Digital Twin mission cluster, `Cushioned acrobatics`, contains one visible
learning motion: a finite positive-roll 360-degree profile entered from hover. The
Campaign Laboratory implements it as two distinct operator actions. Play establishes a
0.50 m hover and keeps backend ownership of the flight. Only after measured hover
capture does a mission-specific `Flip` button appear beside `Abort and land`. Flip is
accepted once, runs the fixed profile, observes recovery, and lands automatically.

This implementation has fake-link evidence but no physical qualification result. It was
not deployed to or exercised on the shared Crazyflie runtime as part of this change.

## Control ownership

The host does not calculate or send four independent motor PWM values during flight.
It sends body-rate targets and collective thrust through cflib's manual commander with
`rate=True`. Crazyflie firmware compares those targets with gyro measurements in its
rate PID and applies its X-frame mixer to produce motor M1–M4 commands. This preserves
closed-loop stabilization and makes the firmware, not host scheduling jitter, the
time-critical motor-control owner.

```text
immutable sampled roll profile
        -> cflib manual commander (rate mode)
        -> Crazyflie rate PID + measured gyro
        -> Crazyflie X mixer
        -> M1 / M2 / M3 / M4
```

The transport ends with a zero-rate sample and
`send_notify_setpoint_stop()`. That meta command lowers the manual setpoint priority so
the previous high-level hover controller can regain control. It deliberately does not
use `send_stop_setpoint()`, which would cut motor output rather than perform a hover
handoff.

## Immutable reference profile

| Phase | Samples | Period | Command |
|---|---:|---:|---|
| Collective boost | 25 | 10 ms | 0 deg/s body rate, 100% collective thrust |
| Cubic roll | 52 | 10 ms | positive roll rate, 0 pitch/yaw rate, 100% collective thrust |
| Handoff | 1 | 10 ms | 0 deg/s body rate, then commander-priority release |

The continuous cubic reference ramps from 0 to at most 1,400 deg/s and back to 0.
Because its 0.514285… s duration is not an integer multiple of 10 ms, the 52 sampled
rates are normalized once so their zero-order-held integral is exactly 360 degrees.
The complete manual-command interval is 0.78 s, including the 0.25 s boost and 0.01 s
handoff sample.

The source is
[`hardware/acrobatics_lab.py`](../../src/crazyswarm_app/hardware/acrobatics_lab.py).
The physical transport is
[`vehicles/_cflib_link.py`](../../src/crazyswarm_app/vehicles/_cflib_link.py), and the
permit-owning adapter is
[`vehicles/crazyflie.py`](../../src/crazyswarm_app/vehicles/crazyflie.py).

## Staged workflow and containment

1. Select `Cushioned acrobatics` → `Single flip` and press Play. The backend connects,
   resets the estimator, arms when required, takes off to 0.50 m, and waits for three
   consecutive captured hover samples.
2. The operation enters `HOVERING_READY`. The captured position is retained as HOME,
   and `Flip` becomes available next to the always-available `Abort and land` action.
3. Pressing `Flip` changes the operation to `FLIPPING` and consumes the trigger. The
   button disappears, so browser retries cannot schedule a second roll.
4. After the 0.78 s body-rate/thrust stream, the high-level hover regains commander
   priority, recovery is observed, and landing starts automatically.

While waiting, flipping, and recovering, measured X and Y must each remain within
±0.50 m of the captured HOME point. The vehicle adapter polls the same bound during the
rate stream and interrupts that stream before the failure path commands landing if the
box is crossed. A 60-second untriggered hover also enters the automatic failure-landing
path. Exact landing position is recorded but is not the maneuver success criterion.

The operator-facing workflow intentionally exposes no roll-rate, thrust, or individual
motor controls. A cushion reduces impact consequences; it does not turn this unverified
profile into a qualified or low-risk flight.

## Reference material

- [Bitcraze cflib Commander API](https://www.bitcraze.io/documentation/repository/crazyflie-lib-python/master/api/cflib/crazyflie/commander/)
- [Bitcraze generic commander firmware decoder](https://github.com/bitcraze/crazyflie-firmware/blob/master/src/modules/src/crtp_commander_generic.c)
- [Community Crazyflie cubic flip experiment](https://github.com/shravankumargulvadi/Drone_Acrobatics/blob/master/drone_flip.py)

The community experiment supplies the cubic one-roll reference parameters. This
implementation makes rate mode explicit and adds a deterministic high-level-controller
handoff; it does not treat the community flight result as qualification for this airframe
or room.
