# Time-parameterized trajectory contract v1

| Field | Value |
|---|---|
| Contract | `time-parameterized-trajectory-v1` |
| Execution program | `accepted-execution-program-v1` |
| Status | `FROZEN` |
| Ordinary authority | Fast Sim, accepted static single-role mission programs |
| Physical or live-Isaac claim | None |

## Purpose

The accepted mission plan now contains the motion authority used for eligible static
single-role execution. A mission preview is no longer converted back into a series of
independent relative moves at runtime. Consecutive moves compile into one absolute,
world-frame trajectory and one backend command.

Every trajectory declares:

- immutable role, vehicle, route, trajectory, execution-program, and accepted-plan
  identities;
- strictly increasing source-clock timestamps and absolute positions;
- velocity and acceleration at every knot;
- `QUINTIC_HERMITE_C2` interpolation;
- explicit stop-point sequences, including start and terminal points;
- terminal position and velocity tolerances; and
- one canonical SHA-256 identity.

Non-stop internal knots retain a shared non-zero derivative. For the canonical 2.4 m
route, 24 historical 0.1 m commands compile into one 25-point trajectory whose 23
internal points retain 0.125 m/s velocity. Fast Sim samples the same quintic contract
used by admission and evaluation.

## Accepted execution program

An execution program contains ordered takeoff, declared hold, trajectory, and landing
operations. Its schedule is continuous from source time zero. Nominal duration,
contingency reserve, recovery reserve, and the resulting timeout must agree exactly.
The program is included in the mission-plan hash, and each trajectory command repeats
the accepted plan, program, route, and trajectory hashes. A mismatch fails closed.

Eligible uploaded missions execute this accepted program directly; the restricted
Python worker is not rerun as a parallel motion authority. Observation-dependent
missions remain on their established command path. Predictively resolved two-role
crossings execute the deconflicted static programs admitted by WP-22; other adaptive
coordination requires its own equivalent authority.

## Backend and safety boundary

`time_parameterized_trajectory` is an explicit vehicle capability. Fast Sim and the
software-only mock gateway declare it. A backend that does not declare it is rejected
before connect, arm, or takeoff; there is no semantic fallback.

The Safety Supervisor validates current-position capture, flight volume, altitude,
sampled spline velocity, acceleration, yaw rate, duration, and identities before
dispatch. It retains independent authority to interrupt the active backend command,
stop and hold, replace it with another accepted trajectory, land, abort-and-land, or
emergency-stop. Those interventions do not depend on artificial micro-waypoints.

## Clock and completion semantics

The execution program declares source-clock scheduling and monotonic-wall-clock
watchdogs. Fast Sim supports explicit `ACCELERATED` and `REALTIME` source-clock modes.
Blocking command timeout is trajectory-duration aware; mission execution timeout is
the accepted schedule plus declared contingency and recovery reserves.

Fast Sim follows the complete trajectory and then performs bounded terminal tracking
settling. Completion requires both position and velocity tolerance. Failing that
tracking gate is a command timeout, not success.

## Evidence

Mission results retain accepted plan/program/trajectory identities and clock policy.
The execution evaluator separately records:

- accepted trajectory command count and identities;
- plan/program/trajectory identity agreement;
- unintended stops generated in the trajectory itself; and
- desired-trajectory versus estimate/truth tracking RMS and maximum error.

This separates a trajectory-generation discontinuity from controller/plant tracking
error. The original estimate-versus-truth localization metrics remain independent.
