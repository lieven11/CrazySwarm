import { describe, expect, it } from "vitest";
import type { PhysicalTwinLiveFrameView } from "../app/lib/models";
import { updateTwinShadow } from "../app/lib/twin-shadow";

function frame(
  position: { x: number; y: number; z: number },
  liveSequence: number,
  attitude = { rollRad: 0, pitchRad: 0, yawRad: 0 },
): PhysicalTwinLiveFrameView {
  return {
    state: "PAIRED",
    vehicleLabel: "Drone one",
    liveSequence,
    pairedCycleCount: liveSequence,
    channelRecordCount: liveSequence * 28,
    observed: {
      role: "OBSERVED",
      vehicleId: "physical:one",
      sourceClass: "MEASURED_REAL",
      freshness: "CURRENT",
      frame: "home",
      sourceClockId: "crazyflie-firmware",
      sourceEpoch: 1,
      rawSourceTimestampS: liveSequence / 10,
      positionAvailability: "INCOMPATIBLE",
      position,
      batteryAvailability: "AVAILABLE",
      batteryVoltage: 4.02,
      attitude,
      imu: {
        acceleration: { x: 0.1, y: 0.2, z: 9.81 },
        angularVelocity: { x: 0.01, y: 0.02, z: 0.03 },
      },
      familyAvailability: { attitude: "AVAILABLE", imu: "AVAILABLE" },
    },
  };
}

describe("digital twin shadow projection", () => {
  it("starts at the scene center and follows estimated displacement and attitude", () => {
    const initial = updateTwinShadow(undefined, frame({ x: 1.4, y: -0.7, z: 0.12 }, 1));
    const moved = updateTwinShadow(
      initial,
      frame(
        { x: 1.75, y: -0.9, z: 0.48 },
        2,
        { rollRad: 0.2, pitchRad: -0.1, yawRad: 0.4 },
      ),
    );

    expect(initial?.vehicle.telemetry?.estimate).toEqual({ x: 0, y: 0, z: 0 });
    expect(moved?.vehicle.telemetry?.estimate).toEqual({
      x: 0.3500000000000001,
      y: -0.20000000000000007,
      z: 0.36,
    });
    expect(moved?.vehicle.telemetry?.attitude).toEqual({
      rollRad: 0.2,
      pitchRad: -0.1,
      yawRad: 0.4,
    });
    expect(moved?.vehicle.telemetry?.imu?.angularVelocity).toEqual({ x: 0.01, y: 0.02, z: 0.03 });
    expect(moved?.path).toHaveLength(2);
  });

  it("does not grow the trace when cached presentation frames repeat a position", () => {
    const initial = updateTwinShadow(undefined, frame({ x: 0.2, y: 0.3, z: 0.1 }, 1));
    const repeated = updateTwinShadow(initial, frame({ x: 0.2, y: 0.3, z: 0.1 }, 2));

    expect(repeated?.path).toEqual([{ x: 0, y: 0, z: 0 }]);
  });

  it("preserves the flight anchor when a reconnect advances the source epoch", () => {
    const initial = updateTwinShadow(undefined, frame({ x: 0, y: 0, z: 0 }, 1));
    const changedEpoch = frame({ x: 0.05, y: -0.02, z: 0.31 }, 2);
    changedEpoch.observed!.sourceEpoch = 2;
    changedEpoch.observed!.rawSourceTimestampS = 0.1;

    const reconnected = updateTwinShadow(initial, changedEpoch);

    expect(reconnected?.vehicle.telemetry?.estimate).toEqual({
      x: 0.05,
      y: -0.02,
      z: 0.31,
    });
    expect(reconnected?.path).toEqual([
      { x: 0, y: 0, z: 0 },
      { x: 0.05, y: -0.02, z: 0.31 },
    ]);
  });

  it("retains the last airborne projection while reconnecting has no sample", () => {
    const airborne = updateTwinShadow(undefined, frame({ x: 0, y: 0, z: 0 }, 1));
    const reconnecting: PhysicalTwinLiveFrameView = {
      state: "CONNECTING",
      liveSequence: 2,
      pairedCycleCount: 1,
      channelRecordCount: 28,
    };

    expect(updateTwinShadow(airborne, reconnecting)).toBe(airborne);
  });

  it("starts a new anchor when the physical-flight boundary clears prior state", () => {
    const priorFlight = updateTwinShadow(undefined, frame({ x: 0, y: 0, z: 0 }, 1));
    const nextFlight = updateTwinShadow(
      undefined,
      frame({ x: 1.2, y: -0.4, z: 0.08 }, 2),
    );

    expect(priorFlight?.vehicle.telemetry?.estimate).toEqual({ x: 0, y: 0, z: 0 });
    expect(nextFlight?.vehicle.telemetry?.estimate).toEqual({ x: 0, y: 0, z: 0 });
    expect(nextFlight?.path).toEqual([{ x: 0, y: 0, z: 0 }]);
  });
});
