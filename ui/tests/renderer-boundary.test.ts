// @vitest-environment node
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { buildScene, disposeScene } from "../app/components/RoomScene";
import { deterministicDashboard } from "../app/lib/fixtures";
import type { RangeRay, Vec3, VehicleView } from "../app/lib/models";

describe("3D renderer boundary", () => {
  it("has no command or API side effects", async () => {
    const source = await readFile(new URL("../app/components/RoomScene.tsx", import.meta.url), "utf8");
    expect(source).not.toMatch(/ControlApi|fetch\(|\/api\/v1|emergency-stop|takeoff|land\(/);
  });

  it("keeps development fixtures out of the operator data path", async () => {
    const control = await readFile(new URL("../app/components/ControlCenter.tsx", import.meta.url), "utf8");
    const api = await readFile(new URL("../app/lib/api.ts", import.meta.url), "utf8");
    expect(control).not.toMatch(/fixtures|deterministicDashboard|fixtureForState/);
    expect(api).not.toMatch(/fixtures|deterministicDashboard|fixtureForState/);
  });

  it("renders long traces, six sensor rays, and three vehicles within the scene budget", () => {
    const base = deterministicDashboard.vehicles[0];
    const directions = ["front", "back", "left", "right", "up", "down"] as const;
    const ranges: RangeRay[] = directions.map((direction) => ({
      direction,
      distanceM: 1.25,
      maximumM: 4,
      freshness: "current",
    }));
    const vehicles: VehicleView[] = [0, 1, 2].map((index) => ({
      ...structuredClone(base),
      id: `sim0${index + 1}`,
      selected: index === 0,
      telemetry: base.telemetry ? {
        ...structuredClone(base.telemetry),
        estimate: { x: index - 1, y: index * 0.15, z: 0.3 },
        ranges,
      } : undefined,
    }));
    const longTrace: Vec3[] = Array.from({ length: 2_000 }, (_, index) => ({
      x: -1.5 + index * 0.0015,
      y: Math.sin(index / 30) * 0.5,
      z: 0.3,
    }));
    const started = performance.now();
    const scene = buildScene(
      deterministicDashboard.room!,
      vehicles,
      longTrace.slice(0, 800),
      longTrace,
      { sensors: true, trace: true, plan: true, truth: true },
    );
    const elapsedMs = performance.now() - started;
    const roles: string[] = [];
    scene.traverse((object) => {
      if (typeof object.userData.visualRole === "string") roles.push(object.userData.visualRole);
    });
    expect(elapsedMs).toBeLessThan(250);
    expect(scene.children.length).toBeLessThan(80);
    expect(roles).toEqual(expect.arrayContaining([
      "planned",
      "received-estimate",
      "simulator-truth",
      "modeled-range",
    ]));
    disposeScene(scene);
  });

  it("keeps planned, received-estimate, truth, and replay structures distinct", () => {
    const paths = [{ x: 0, y: 0, z: 0 }, { x: 0.2, y: 0, z: 0.3 }];
    const scene = buildScene(
      deterministicDashboard.room!,
      deterministicDashboard.vehicles,
      paths,
      paths,
      { sensors: true, trace: true, plan: true, truth: true },
      true,
    );
    const roles = new Set<string>();
    scene.traverse((object) => {
      if (typeof object.userData.visualRole === "string") roles.add(object.userData.visualRole);
    });
    expect([...roles]).toEqual(expect.arrayContaining([
      "planned",
      "replay",
      "simulator-truth",
      "received-estimate",
    ]));
    disposeScene(scene);
  });

  it("uses only received dashboard telemetry for animation positions", async () => {
    const control = await readFile(new URL("../app/components/ControlCenter.tsx", import.meta.url), "utf8");
    const renderer = await readFile(new URL("../app/components/RoomScene.tsx", import.meta.url), "utf8");
    expect(control).not.toMatch(/requestAnimationFrame|lerp|interpolat/i);
    expect(renderer).not.toMatch(/\.lerp\(|interpolat/i);
    expect(renderer).toContain("data.estimate");
    expect(renderer).toContain("model.vehicles");
  });

  it("keeps the camera and pointer lifecycle stable while telemetry scenes update", async () => {
    const renderer = await readFile(new URL("../app/components/RoomScene.tsx", import.meta.url), "utf8");
    expect(renderer).toContain("const rendererRef = useRef");
    expect(renderer).toContain("const sceneRef = useRef");
    expect(renderer).toContain("const draggingRef = useRef");
    expect(renderer).not.toContain("let dragging = false");
    expect(renderer).toContain("}, [roomAvailable]);");
  });

  it("keeps room and provenance metadata in Observation instead of over the scene", async () => {
    const control = await readFile(new URL("../app/components/ControlCenter.tsx", import.meta.url), "utf8");
    const renderer = await readFile(new URL("../app/components/RoomScene.tsx", import.meta.url), "utf8");
    expect(control).not.toContain("truth-strip");
    expect(control).not.toContain("workspace-header");
    expect(renderer).not.toContain("room-title-overlay");
    expect(renderer).not.toContain("room-readout");
    expect(renderer).not.toContain("scene-legend");
    expect(renderer).not.toContain("canvas-help");
    expect(control).toContain("<h3>Room / world frame</h3>");
    expect(control).toContain("<h3>Observation</h3>");
    expect(control).toContain("formatClockContext(data.provenance)");
  });

  it("places Observation below a scene-height upper control row", async () => {
    const control = await readFile(new URL("../app/components/ControlCenter.tsx", import.meta.url), "utf8");
    const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
    expect(control).toContain('className="control-row"');
    expect(control).toContain('className="control-surface"');
    expect(control).toContain('className="mission-slot"');
    expect(styles).toMatch(/\.mission-panel \{ position: absolute; inset: 0;/);
    expect(styles).toContain(".control-surface { min-width: 0; display: grid;");
    expect(styles).not.toContain(".workspace-stack");
  });
});
