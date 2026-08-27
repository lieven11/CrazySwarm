// @vitest-environment node
import { readFile } from "node:fs/promises";
import { LineBasicMaterial, LineDashedMaterial, LineSegments, PerspectiveCamera, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { buildScene, disposeScene, encodeSceneSnapshotBlob, frameSmoothingAlpha, neutralSnapshotCamera, snapshotCaptureDimensions, sourceBufferedVehicles, syncDynamicScene, vehicleAtPointer, zoomOrbitRadius } from "../app/components/RoomScene";
import { deterministicDashboard } from "../app/lib/fixtures";
import type { RangeRay, Vec3, VehicleView } from "../app/lib/models";
import { SourceTimePlaybackBuffer } from "../app/lib/playback";
import { worldToScene } from "../app/lib/spatial";

describe("3D renderer boundary", () => {
  it("bounds operator-triggered scene snapshots without changing aspect ratio", () => {
    expect(snapshotCaptureDimensions(2560, 1440)).toEqual({ width: 1920, height: 1080 });
    expect(snapshotCaptureDimensions(640, 360)).toEqual({ width: 640, height: 360 });
    expect(snapshotCaptureDimensions(0, 0)).toEqual({ width: 0, height: 0 });
  });

  it("re-encodes as JPEG when a browser substitutes PNG for requested WebP", async () => {
    const requestedTypes: string[] = [];
    const requestedQualities: number[] = [];
    const blob = await encodeSceneSnapshotBlob(async (type, quality) => {
      requestedTypes.push(type);
      requestedQualities.push(quality);
      return type === "image/webp"
        ? new Blob(["browser png fallback"], { type: "image/png" })
        : new Blob(["jpeg"], { type: "image/jpeg" });
    });

    expect(requestedTypes).toEqual(["image/webp", "image/jpeg"]);
    expect(requestedQualities).toEqual([0.92, 0.94]);
    expect(blob.type).toBe("image/jpeg");
  });

  it("keeps full-resolution captures below the upload limit with adaptive quality", async () => {
    const requestedQualities: number[] = [];
    const blob = await encodeSceneSnapshotBlob(async (type, quality) => {
      requestedQualities.push(quality);
      return new Blob(
        [new Uint8Array(quality > 0.86 ? 960_000 : 700_000)],
        { type },
      );
    });

    expect(requestedQualities).toEqual([0.92, 0.86]);
    expect(blob.size).toBe(700_000);
    expect(blob.type).toBe("image/webp");
  });

  it("uses a fixed ceiling-corner camera that keeps the complete room in frame", () => {
    const room = deterministicDashboard.room!;
    const camera = neutralSnapshotCamera(room, 16 / 9);
    const corners = [-1, 1].flatMap((xSign) => [-1, 1].flatMap((ySign) => [0, 1].map((zSign) => (
      new Vector3(
        xSign * room.widthM / 2,
        zSign * room.heightM,
        ySign * room.depthM / 2,
      ).project(camera)
    ))));

    expect(camera.position.x).toBeGreaterThan(0);
    expect(camera.position.y).toBeGreaterThan(room.heightM);
    expect(camera.position.z).toBeGreaterThan(0);
    for (const corner of corners) {
      expect(Math.abs(corner.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(corner.y)).toBeLessThanOrEqual(1);
      expect(corner.z).toBeGreaterThanOrEqual(-1);
      expect(corner.z).toBeLessThanOrEqual(1);
    }

    const missionPoints = [
      { x: -1.5, y: 0, z: 0.3 },
      { x: 0.2, y: 0, z: 0.3 },
      { x: 1.5, y: 0, z: 0.3 },
    ];
    const missionCamera = neutralSnapshotCamera(room, 16 / 9, missionPoints);
    const missionDirection = missionCamera.getWorldDirection(new Vector3());
    expect(missionDirection.x).toBeCloseTo(missionDirection.y);
    expect(missionDirection.y).toBeCloseTo(missionDirection.z);
    const projectedMission = missionPoints.map((value) => (
      new Vector3(...worldToScene(value)).project(missionCamera)
    ));
    for (const point of projectedMission) {
      expect(Math.abs(point.x)).toBeLessThan(0.9);
      expect(Math.abs(point.y)).toBeLessThan(0.9);
    }
    const horizontalMissionSpan = Math.max(...projectedMission.map((point) => point.x))
      - Math.min(...projectedMission.map((point) => point.x));
    const roomFramedMission = missionPoints.map((value) => (
      new Vector3(...worldToScene(value)).project(camera)
    ));
    const roomFramedSpan = Math.max(...roomFramedMission.map((point) => point.x))
      - Math.min(...roomFramedMission.map((point) => point.x));
    expect(horizontalMissionSpan).toBeGreaterThan(0.8);
    expect(horizontalMissionSpan).toBeGreaterThan(roomFramedSpan * 1.5);
  });

  it("shows a disconnected simulator reset immediately instead of freezing its old estimate", () => {
    const vehicle = structuredClone(deterministicDashboard.vehicles[0]!);
    vehicle.state = "DISCONNECTED";
    vehicle.telemetry!.estimate = { x: 0, y: 0, z: 0 };
    vehicle.telemetry!.simulatedTruth = { x: 0, y: 0, z: 0 };
    vehicle.telemetry!.provenance = {
      ...vehicle.telemetry!.provenance,
      simulationTimeS: 12,
      sourceClockId: "fast-sim-reset",
      sourceClockEpoch: 1,
      sequence: 42,
    };
    const buffers = new Map([[vehicle.id, new SourceTimePlaybackBuffer()]]);

    const display = sourceBufferedVehicles([vehicle], buffers);

    expect(display.vehicles[0]!.telemetry!.estimate).toEqual({ x: 0, y: 0, z: 0 });
    expect(display.vehicles[0]!.telemetry!.simulatedTruth).toEqual({ x: 0, y: 0, z: 0 });
    expect(buffers.has(vehicle.id)).toBe(false);
  });

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
    const longTrace: Vec3[] = Array.from({ length: 3_600 }, (_, index) => ({
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

  it("keeps static and vehicle GPU objects mounted while telemetry overlays update", () => {
    const scene = buildScene(
      deterministicDashboard.room!,
      deterministicDashboard.vehicles,
      [],
      [],
      { sensors: true, trace: true, plan: true, truth: true },
    );
    const homeBase = scene.children.find((object) => object.userData.visualRole === "vehicle-home-base");
    const oldVehicle = scene.children.find((object) => object.userData.visualRole === "received-estimate");
    expect(homeBase).toBeDefined();
    expect(oldVehicle).toBeDefined();

    const vehicles = structuredClone(deterministicDashboard.vehicles);
    vehicles[0]!.telemetry!.estimate = { x: 0.7, y: -0.4, z: 0.3 };
    syncDynamicScene(
      scene,
      vehicles,
      [{ x: 0, y: 0, z: 0.2 }, { x: 0.7, y: -0.4, z: 0.3 }],
      { sensors: true, trace: true, plan: true, truth: true },
    );

    expect(scene.children).toContain(homeBase);
    expect(scene.children).toContain(oldVehicle);
    const updatedVehicle = scene.children.find(
      (object) => object.userData.visualRole === "received-estimate" && object.userData.sceneLayer === "dynamic",
    );
    expect(updatedVehicle).toBeDefined();
    expect(updatedVehicle).toBe(oldVehicle);
    expect(updatedVehicle!.position.toArray()).toEqual([0.7, 0.3, -0.4]);
    disposeScene(scene);
  });

  it("keeps hidden evidence layers mounted for a snapshot render", () => {
    const paths = [{ x: 0, y: 0, z: 0 }, { x: 0.2, y: 0, z: 0.3 }];
    const scene = buildScene(
      deterministicDashboard.room!,
      deterministicDashboard.vehicles,
      paths,
      paths,
      { sensors: false, trace: false, plan: false, truth: false },
    );
    const plan = scene.children.find((object) => object.userData.sceneLayer === "plan");
    const trace = scene.children.find((object) => object.userData.sceneLayer === "trace");
    const truth = scene.children.find((object) => object.userData.visualRole === "simulator-truth");
    expect(plan).toMatchObject({ visible: false });
    expect(trace).toMatchObject({ visible: false });
    expect(truth).toMatchObject({ visible: false });
    disposeScene(scene);
  });

  it("hit-tests drones independently from empty scene space", () => {
    const scene = buildScene(
      deterministicDashboard.room!,
      deterministicDashboard.vehicles,
      [],
      [],
      { sensors: false, trace: false, plan: false, truth: false },
    );
    const camera = new PerspectiveCamera(42, 1, 0.05, 100);
    camera.position.set(.02, .3, 3);
    camera.lookAt(.02, .3, .01);
    camera.updateProjectionMatrix();
    const canvas = {
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }),
    } as HTMLCanvasElement;

    expect(vehicleAtPointer(scene, camera, canvas, 50, 50))
      .toBe(deterministicDashboard.vehicles[0]!.id);
    expect(vehicleAtPointer(scene, camera, canvas, 0, 0)).toBeUndefined();
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
      "planned-target",
      "replay",
      "simulator-truth",
      "received-estimate",
    ]));
    disposeScene(scene);
  });

  it("renders room and flight boundaries as solid blue lines distinct from the plan", () => {
    const paths = [{ x: 0, y: 0, z: 0 }, { x: 0.2, y: 0, z: 0.3 }];
    const room = {
      ...deterministicDashboard.room!,
      geofence: {
        minimum: { x: -1.5, y: -1.5, z: 0 },
        maximum: { x: 1.5, y: 1.5, z: 2 },
      },
    };
    const scene = buildScene(
      room,
      deterministicDashboard.vehicles,
      paths,
      [],
      { sensors: false, trace: false, plan: true, truth: false },
    );
    const roomBoundary = scene.children.find(
      (object) => object.userData.visualRole === "room-boundary",
    );
    const flightBoundary = scene.children.find(
      (object) => object.userData.visualRole === "flight-boundary",
    );
    const plan = scene.children.find((object) => object.userData.visualRole === "planned");

    expect(roomBoundary).toBeDefined();
    expect(flightBoundary).toBeDefined();
    expect((roomBoundary as LineSegments).material).toBeInstanceOf(LineBasicMaterial);
    expect((flightBoundary as LineSegments).material).toBeInstanceOf(LineBasicMaterial);
    expect(((roomBoundary as LineSegments).material as LineBasicMaterial).color.getHex()).toBe(0x89cff0);
    expect(((flightBoundary as LineSegments).material as LineBasicMaterial).color.getHex()).toBe(0x89cff0);
    expect((plan as LineSegments).material).toBeInstanceOf(LineDashedMaterial);
    disposeScene(scene);
  });

  it("centers the ground target dome above the home pad surface", () => {
    const home = deterministicDashboard.room!.home!;
    const scene = buildScene(
      deterministicDashboard.room!,
      [],
      [home, { ...home, z: 0.3 }, home],
      [],
      { sensors: false, trace: false, plan: true, truth: false },
    );
    const marker = scene.children.find(
      (object) => object.userData.visualRole === "planned-target",
    );
    expect(marker).toBeDefined();
    expect(marker!.position.x).toBe(home.x);
    expect(marker!.position.z).toBe(home.y);
    expect(marker!.position.y).toBeCloseTo(0.018, 8);
    disposeScene(scene);
  });

  it("renders one numbered home base at each mission vehicle start", () => {
    const bases = [
      { vehicleId: "drone-left", number: 1, position: { x: -1, y: -0.4, z: 0 } },
      { vehicleId: "drone-right", number: 2, position: { x: 1, y: 0.4, z: 0 } },
    ];
    const scene = buildScene(
      deterministicDashboard.room!,
      deterministicDashboard.vehicles,
      [],
      [],
      { sensors: false, trace: false, plan: false, truth: false },
      false,
      bases,
    );
    const pads = scene.children.filter(
      (object) => object.userData.visualRole === "vehicle-home-base",
    );
    expect(pads).toHaveLength(2);
    expect(pads.map((pad) => ({
      vehicleId: pad.userData.vehicleId,
      number: pad.userData.baseNumber,
      x: pad.position.x,
      z: pad.position.z,
    }))).toEqual([
      { vehicleId: "drone-left", number: 1, x: -1, z: -0.4 },
      { vehicleId: "drone-right", number: 2, x: 1, z: 0.4 },
    ]);
    const labels: string[] = [];
    scene.traverse((object) => {
      if (object.userData.visualRole === "home-base-number") labels.push(object.userData.label);
    });
    expect(labels).toEqual(["1", "2"]);
    disposeScene(scene);
  });

  it("renders staged mission roles without leaking the current runtime vehicle", () => {
    const preview = {
      missionId: "py-fleet",
      sourceSha256: "hash",
      plan: {
        id: "plan-fleet", sha256: "plan-hash", safetyCaseSha256: "safety-hash",
        status: "APPROVED" as const, objective: "Fleet", plugins: [], phases: [], routes: [], findings: [],
      },
      vehicles: [{
        roleId: "left",
        vehicleId: "drone-left",
        displayName: "Left",
        initialRole: "ACTIVE" as const,
        home: { x: -0.8, y: 0, z: 0 },
        start: { x: -1.0, y: 0.2, z: 0 },
        existingVehicle: true,
        previewFidelity: "EXACT_ROLE" as const,
        plannedCommands: [],
      }, {
        roleId: "right",
        vehicleId: "drone-right",
        displayName: "Right",
        initialRole: "ACTIVE" as const,
        home: { x: 0.8, y: 0, z: 0 },
        start: { x: 1.0, y: -0.2, z: 0 },
        existingVehicle: true,
        previewFidelity: "EXACT_ROLE" as const,
        plannedCommands: [],
      }],
    };
    const scene = buildScene(
      deterministicDashboard.room!,
      deterministicDashboard.vehicles,
      {
        "drone-left": [preview.vehicles[0]!.start, { ...preview.vehicles[0]!.start, z: 0.3 }],
        "drone-right": [preview.vehicles[1]!.start, { ...preview.vehicles[1]!.start, z: 0.3 }],
      },
      {},
      { sensors: false, trace: false, plan: true, truth: false },
      false,
      preview.vehicles.map((vehicle, index) => ({ vehicleId: vehicle.vehicleId, number: index + 1, position: vehicle.home })),
      preview,
    );
    const previewVehicleIds: string[] = [];
    const roles = new Set<string>();
    scene.traverse((object) => {
      if (object.userData.visualRole === "received-estimate") {
        previewVehicleIds.push(object.userData.vehicleId);
      }
      if (typeof object.userData.visualRole === "string") roles.add(object.userData.visualRole);
    });
    expect(previewVehicleIds).toEqual(["drone-left", "drone-right"]);
    expect(previewVehicleIds).not.toContain(deterministicDashboard.vehicles[0]!.id);
    const previewGroups = scene.children.filter(
      (object) => object.userData.visualRole === "received-estimate",
    );
    expect(previewGroups.map((group) => [group.position.x, group.position.y, group.position.z])).toEqual([
      [-1, 0.07, 0.2],
      [1, 0.07, -0.2],
    ]);
    expect([...roles]).toEqual(expect.arrayContaining(["planned-drone-left", "planned-drone-right"]));
    disposeScene(scene);
  });

  it("smooths only between received dashboard telemetry positions", async () => {
    const control = await readFile(new URL("../app/components/ControlCenter.tsx", import.meta.url), "utf8");
    const renderer = await readFile(new URL("../app/components/RoomScene.tsx", import.meta.url), "utf8");
    expect(control).not.toMatch(/requestAnimationFrame|interpolat/i);
    expect(renderer).toContain("requestAnimationFrame");
    expect(renderer).toContain("targetPosition");
    expect(renderer).toContain("data.estimate");
    expect(renderer).toContain("model.vehicles");
    expect(frameSmoothingAlpha(0)).toBe(0);
    expect(frameSmoothingAlpha(16)).toBeGreaterThan(0);
    expect(frameSmoothingAlpha(16)).toBeLessThan(1);
  });

  it("limits browser timing traffic to active campaigns and keeps uploaded missions visible", async () => {
    const control = await readFile(new URL("../app/components/ControlCenter.tsx", import.meta.url), "utf8");
    expect(control).toContain("onDisplayTiming={campaignRunActive ?");
    expect(control).toContain("!campaignRunActive && !runningRunId");
  });

  it("keeps the camera and pointer lifecycle stable while telemetry scenes update", async () => {
    const renderer = await readFile(new URL("../app/components/RoomScene.tsx", import.meta.url), "utf8");
    expect(renderer).toContain("const rendererRef = useRef");
    expect(renderer).toContain("const sceneRef = useRef");
    expect(renderer).toContain("const draggingRef = useRef");
    expect(renderer).not.toContain("let dragging = false");
    expect(renderer).toContain("}, [roomAvailable]);");
  });

  it("allows a detailed perspective close-up that follows the selected drone", async () => {
    const renderer = await readFile(new URL("../app/components/RoomScene.tsx", import.meta.url), "utf8");
    expect(zoomOrbitRadius(6.4, -10_000)).toBe(0.65);
    expect(zoomOrbitRadius(0.65, 100)).toBeGreaterThan(0.65);
    expect(zoomOrbitRadius(6.4, 10_000)).toBe(10);
    expect(renderer).toContain("selectedMotionKeyRef");
    expect(renderer).toContain("orbitTargetRef.current.copy(selectedMotion.position)");
    expect(renderer).toContain('aria-label="Zoom in on selected drone"');
    expect(renderer).toContain('aria-label="Zoom out from selected drone"');
  });

  it("keeps the flight surface focused on current telemetry instead of evidence metadata", async () => {
    const control = await readFile(new URL("../app/components/ControlCenter.tsx", import.meta.url), "utf8");
    const renderer = await readFile(new URL("../app/components/RoomScene.tsx", import.meta.url), "utf8");
    const telemetry = await readFile(new URL("../app/components/TelemetryDock.tsx", import.meta.url), "utf8");
    expect(control).not.toContain("truth-strip");
    expect(control).not.toContain("workspace-header");
    expect(renderer).not.toContain("room-title-overlay");
    expect(renderer).not.toContain("room-readout");
    expect(renderer).not.toContain('className="scene-legend"');
    expect(renderer).not.toContain("canvas-help");
    expect(renderer).not.toContain('className="room-scene-label"');
    expect(telemetry).not.toContain("World volume");
    expect(telemetry).not.toContain('<summary>Evidence');
    expect(telemetry).not.toContain("formatClockContext(data.provenance)");
    expect(telemetry).toContain('aria-label="Telemetry category"');
  });

  it("uses a full-bleed scene with independent liquid surfaces instead of dashboard chrome", async () => {
    const control = await readFile(new URL("../app/components/ControlCenter.tsx", import.meta.url), "utf8");
    const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
    expect(control).toContain('className="workspace"');
    expect(control).toContain('className="mission-dock"');
    expect(control).not.toContain("<RunFilesControl");
    expect(control).toContain("<FlightReadout");
    expect(control).not.toContain('className="control-row"');
    expect(control).not.toContain('className="topbar"');
    expect(control).not.toContain('className="nav-rail"');
    expect(control).not.toContain("twin-world-unavailable");
    expect(styles).toMatch(/\.workspace \{ position: absolute; inset: 0;/);
    expect(styles).toMatch(/\.room-stage \{ position: absolute; inset: 0;/);
    expect(styles).toContain(".flight-readout {");
    expect(styles).toContain(".mission-dock {");
    expect(styles).toMatch(/\.campaign-actions \.campaign-action-active \{[^\n]*background: var\(--warning\);/);
    expect(styles).toMatch(/\.scene-controls \{ z-index: 55;[^\n]*left: 50%;[^\n]*transform: translateX\(-50%\);/);
    expect(styles).toMatch(/\.mission-dock \{[\s\S]*?left: 16px;[\s\S]*?width: min\(320px,[\s\S]*?transform: none;/);
    expect(styles).toMatch(/\.mission-panel \{[\s\S]*?left: 16px;[\s\S]*?width: min\(320px,/);
    expect(control.indexOf('className="flight-quick-actions"')).toBeLessThan(control.indexOf("<FlightReadout"));
    expect(styles).toMatch(/\.flight-quick-actions \{[\s\S]*?right: 414px;[\s\S]*?bottom: 16px;/);
    expect(styles).toContain(".control-center.flight-expanded .flight-quick-actions");
  });

  it("keeps fleet selection on the left while telemetry can expand on the right", async () => {
    const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
    const fleetPanel = styles.match(/\.fleet-panel \{[\s\S]*?\n\}/)?.[0] ?? "";
    expect(fleetPanel).toContain("right: auto;");
    expect(fleetPanel).toContain("left: 16px;");
    expect(styles).toContain(".flight-readout.is-expanded { top: 80px;");
    expect(styles).toContain(".twin-vector-grid { display: grid; grid-template-columns: 1fr; gap: 24px;");
    expect(styles).toContain(".twin-vector-bars { padding: 0; border-radius: 0; background: transparent; }");
    expect(styles).toContain(".twin-vector-bars .axis-meter { grid-template-columns: 24px minmax(0,1fr) minmax(96px,120px); gap: 12px; min-height: 28px; }");
  });
});
