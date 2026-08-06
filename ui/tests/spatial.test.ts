import { describe, expect, it } from "vitest";
import type { RoomView } from "../app/lib/models";
import { missionPlan, rangeDirectionVector, rangeEndpoint, worldToScene } from "../app/lib/spatial";

describe("3D coordinate contracts", () => {
  it("maps altitude to the Three.js up axis", () => {
    expect(worldToScene({ x: 1, y: -2, z: 0.3 })).toEqual([1, 0.3, -2]);
  });

  it("rotates body range directions into the world frame", () => {
    const front = rangeDirectionVector("front", Math.PI / 2);
    expect(front.x).toBeCloseTo(0, 8);
    expect(front.y).toBeCloseTo(1, 8);
    expect(front.z).toBe(0);
  });

  it("caps rendered rays at the declared maximum range", () => {
    expect(rangeEndpoint(
      { x: 0, y: 0, z: 0.3 },
      { direction: "up", distanceM: 8, maximumM: 4, freshness: "current" },
      0,
    )).toEqual({ x: 0, y: 0, z: 4.3 });
  });

  it("creates planned geometry only from an explicit mission and configured home", () => {
    const room: RoomView = { id: "lab", widthM: 4, depthM: 4, heightM: 2.5, home: { x: 0, y: 0, z: 0 }, obstacles: [], source: "configured", frame: "world", version: 1 };
    expect(missionPlan(undefined, room)).toEqual([]);
    expect(missionPlan({
      id: "py-123",
      version: "123",
      name: "Hover",
      description: "hover.py",
      sourceKind: "UPLOADED_PYTHON",
      sourceFilename: "hover.py",
      sourceSha256: "123",
      plannedCommands: [
        { action: "takeoff", arguments: { height_m: 0.3, duration_s: 2 } },
        { action: "hover", arguments: { duration_s: 3 } },
        { action: "land", arguments: { duration_s: 2 } },
      ],
    }, room)).toEqual([
      { x: 0, y: 0, z: 0 },
      { x: 0, y: 0, z: 0.3 },
      { x: 0, y: 0, z: 0 },
    ]);
  });
});
