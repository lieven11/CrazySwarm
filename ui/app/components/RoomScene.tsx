"use client";

import {
  AmbientLight,
  BoxGeometry,
  BufferGeometry,
  CircleGeometry,
  Color,
  CylinderGeometry,
  DirectionalLight,
  DoubleSide,
  EdgesGeometry,
  Euler,
  GridHelper,
  Group,
  Line,
  LineBasicMaterial,
  LineDashedMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  PerspectiveCamera,
  PlaneGeometry,
  Quaternion,
  Raycaster,
  Scene,
  SphereGeometry,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { useEffect, useRef, useState } from "react";
import { Crosshair, Eye, Layers3, ScanLine, ZoomIn, ZoomOut } from "lucide-react";
import type { DashboardModel, MissionPreview, Provenance, RoomView, Vec3, VehicleView } from "../lib/models";
import { SourceTimePlaybackBuffer } from "../lib/playback";
import { rangeEndpoint, worldToScene } from "../lib/spatial";

type CameraPreset = "perspective" | "top" | "side";
type SceneMotion = {
  position: Vector3;
  targetPosition: Vector3;
  orientation: Quaternion;
  targetOrientation: Quaternion;
};

const VISUAL_SMOOTHING_TIME_MS = 60;
const MAX_FRAME_DELTA_MS = 50;
const MIN_ORBIT_RADIUS_M = 0.65;
const MAX_ORBIT_RADIUS_M = 10;
const ZOOM_RATE = 0.002;
const TARGET_DOME_RADIUS_M = 0.045;
const HOME_PAD_SURFACE_M = 0.018;
const LANDED_DRONE_VISUAL_HEIGHT_M = 0.07;

export interface HomeBaseView {
  vehicleId: string;
  number: number;
  position: Vec3;
}

export type ScenePathSet = Vec3[] | Record<string, Vec3[]>;
type SceneLayers = { sensors: boolean; trace: boolean; plan: boolean; truth: boolean };
export interface BrowserDisplayTiming {
  correlationId: string;
  stage: "BROWSER_RECEIPT" | "RENDER_FRAME" | "PLAYBACK_BUFFER";
  sourceTimestampS: number;
  sourceClockId: string;
  sourceClockEpoch: number;
  observedMonotonicS: number;
  playbackBufferAgeS: number;
  droppedSamples: number;
  coalescedSamples: number;
}

export function RoomScene({
  model,
  plannedPath,
  historicalPath,
  homeBases,
  missionPreview,
  selectedVehicleIds,
  onVehicleSelectionChange,
  onDisplayTiming,
}: {
  model: DashboardModel;
  plannedPath: ScenePathSet;
  historicalPath: ScenePathSet;
  homeBases?: HomeBaseView[];
  missionPreview?: MissionPreview;
  selectedVehicleIds?: string[];
  onVehicleSelectionChange?: (vehicleId?: string) => void;
  onDisplayTiming?: (event: BrowserDisplayTiming) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cameraRef = useRef<PerspectiveCamera | null>(null);
  const rendererRef = useRef<WebGLRenderer | null>(null);
  const sceneRef = useRef<Scene | null>(null);
  const orbitRef = useRef({ theta: 0.76, phi: 0.9, radius: 6.4 });
  const orbitTargetRef = useRef(new Vector3(0, 0.45, 0));
  const selectedMotionKeyRef = useRef<string | undefined>(undefined);
  const cameraPresetRef = useRef<CameraPreset>("perspective");
  const pointerRef = useRef(new Vector2());
  const pointerStartRef = useRef(new Vector2());
  const draggingRef = useRef(false);
  const pointerDraggedRef = useRef(false);
  const onVehicleSelectionChangeRef = useRef(onVehicleSelectionChange);
  const onDisplayTimingRef = useRef(onDisplayTiming);
  const motionRef = useRef(new Map<string, SceneMotion>());
  const playbackRef = useRef(new Map<string, SourceTimePlaybackBuffer>());
  const displayHealthRef = useRef<HTMLDivElement>(null);
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>("perspective");
  const [layers, setLayers] = useState({ sensors: true, trace: true, plan: true, truth: true });
  const [layersOpen, setLayersOpen] = useState(false);
  onVehicleSelectionChangeRef.current = onVehicleSelectionChange;
  onDisplayTimingRef.current = onDisplayTiming;
  const selectedVehicles = model.vehicles.filter((vehicle) => vehicle.selected);
  const selected = selectedVehicles[0];
  const roomAvailable = Boolean(model.room);
  const sensorsVisible = layers.sensors;
  const traceVisible = layers.trace;
  const truthVisible = layers.truth;
  const fallbackHomeVehicleId = model.vehicles[0]?.id ?? "home";
  const staticSceneInputRef = useRef({
    room: model.room,
    plannedPath,
    planVisible: layers.plan,
    homeBases,
    fallbackHomeVehicleId,
  });
  staticSceneInputRef.current = {
    room: model.room,
    plannedPath,
    planVisible: layers.plan,
    homeBases,
    fallbackHomeVehicleId,
  };
  const staticSceneSignature = JSON.stringify(staticSceneInputRef.current);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !roomAvailable) return;
    const container = canvas.parentElement;
    if (!container) return;
    const motions = motionRef.current;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ canvas, antialias: true });
    } catch {
      canvas.dataset.webgl = "unavailable";
      return;
    }
    rendererRef.current = renderer;
    renderer.setClearColor(new Color("#000000"), 1);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.6));
    const camera = new PerspectiveCamera(42, 1, 0.05, 100);
    cameraRef.current = camera;
    applyPreset(camera, cameraPresetRef.current, orbitRef.current, orbitTargetRef.current);

    const pointerDown = (event: PointerEvent) => {
      draggingRef.current = true;
      pointerDraggedRef.current = false;
      pointerRef.current.set(event.clientX, event.clientY);
      pointerStartRef.current.copy(pointerRef.current);
      canvas.setPointerCapture(event.pointerId);
    };
    const pointerMove = (event: PointerEvent) => {
      if (!draggingRef.current) return;
      const distanceX = event.clientX - pointerStartRef.current.x;
      const distanceY = event.clientY - pointerStartRef.current.y;
      if (distanceX * distanceX + distanceY * distanceY > 25) {
        pointerDraggedRef.current = true;
      }
      if (cameraPresetRef.current === "top") return;
      orbitRef.current.theta += (event.clientX - pointerRef.current.x) * 0.007;
      orbitRef.current.phi = Math.max(0.25, Math.min(1.42, orbitRef.current.phi + (event.clientY - pointerRef.current.y) * 0.006));
      pointerRef.current.set(event.clientX, event.clientY);
      applyOrbit(camera, orbitRef.current, orbitTargetRef.current);
    };
    const pointerUp = (event: PointerEvent) => {
      const wasClick = draggingRef.current && !pointerDraggedRef.current;
      draggingRef.current = false;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      if (wasClick && sceneRef.current) {
        onVehicleSelectionChangeRef.current?.(
          vehicleAtPointer(sceneRef.current, camera, canvas, event.clientX, event.clientY),
        );
      }
    };
    const pointerCancel = (event: PointerEvent) => {
      draggingRef.current = false;
      pointerDraggedRef.current = false;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      orbitRef.current.radius = zoomOrbitRadius(orbitRef.current.radius, normalizedWheelDelta(event, container.clientHeight));
      if (cameraPresetRef.current === "perspective") applyOrbit(camera, orbitRef.current, orbitTargetRef.current);
    };
    canvas.addEventListener("pointerdown", pointerDown);
    canvas.addEventListener("pointermove", pointerMove);
    canvas.addEventListener("pointerup", pointerUp);
    canvas.addEventListener("pointercancel", pointerCancel);
    canvas.addEventListener("wheel", wheel, { passive: false });

    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      if (sceneRef.current) renderer.render(sceneRef.current, camera);
    };
    window.addEventListener("resize", resize);
    let frameCount = 0;
    let frameWindowStartedMs: number | undefined;
    let previousFrameTimestampMs: number | undefined;
    let frame = requestAnimationFrame(function render(timestampMs) {
      if (sceneRef.current) {
        const deltaMs = previousFrameTimestampMs === undefined
          ? 0
          : Math.min(timestampMs - previousFrameTimestampMs, MAX_FRAME_DELTA_MS);
        animateSceneMotion(sceneRef.current, motions, deltaMs);
        const selectedMotionKey = selectedMotionKeyRef.current;
        const selectedMotion = selectedMotionKey ? motions.get(selectedMotionKey) : undefined;
        if (selectedMotion && cameraPresetRef.current === "perspective") {
          orbitTargetRef.current.copy(selectedMotion.position);
          applyOrbit(camera, orbitRef.current, orbitTargetRef.current);
        }
        renderer.render(sceneRef.current, camera);
      }
      previousFrameTimestampMs = timestampMs;
      frameCount += 1;
      frameWindowStartedMs ??= timestampMs;
      const elapsedMs = timestampMs - frameWindowStartedMs;
      if (elapsedMs >= 1_000) {
        canvas.dataset.renderFps = (frameCount * 1_000 / elapsedMs).toFixed(1);
        const memory = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory;
        if (memory) canvas.dataset.heapMib = (memory.usedJSHeapSize / 1_048_576).toFixed(1);
        frameCount = 0;
        frameWindowStartedMs = timestampMs;
      }
      frame = requestAnimationFrame(render);
    });
    resize();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("pointerdown", pointerDown);
      canvas.removeEventListener("pointermove", pointerMove);
      canvas.removeEventListener("pointerup", pointerUp);
      canvas.removeEventListener("pointercancel", pointerCancel);
      canvas.removeEventListener("wheel", wheel);
      renderer.dispose();
      rendererRef.current = null;
      cameraRef.current = null;
      draggingRef.current = false;
      motions.clear();
    };
  }, [roomAvailable]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const staticInput = staticSceneInputRef.current;
    if (!canvas || !staticInput.room) return;
    const nextScene = buildStaticScene(
      staticInput.room,
      staticInput.plannedPath,
      staticInput.planVisible,
      staticInput.homeBases,
      staticInput.fallbackHomeVehicleId,
    );
    sceneRef.current = nextScene;
    canvas.dataset.sceneObjects = String(nextScene.children.length);
    const renderer = rendererRef.current;
    const camera = cameraRef.current;
    if (renderer && camera) renderer.render(nextScene, camera);
    return () => {
      if (sceneRef.current === nextScene) sceneRef.current = null;
      disposeScene(nextScene);
    };
  }, [roomAvailable, staticSceneSignature]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const scene = sceneRef.current;
    if (!canvas || !scene) return;
    const display = sourceBufferedVehicles(model.vehicles, playbackRef.current);
    for (const timing of display.timings) {
      const common = {
        correlationId: timing.sample.correlationId,
        sourceTimestampS: timing.sample.sourceTimestampS,
        sourceClockId: timing.sample.sourceClockId,
        sourceClockEpoch: timing.sample.sourceClockEpoch,
        playbackBufferAgeS: timing.diagnostics.playbackBufferAgeS,
        droppedSamples: timing.diagnostics.droppedSamples,
        coalescedSamples: timing.diagnostics.coalescedSamples,
      };
      onDisplayTimingRef.current?.({
        ...common,
        stage: "BROWSER_RECEIPT",
        observedMonotonicS: timing.sample.receivedMonotonicS,
      });
      onDisplayTimingRef.current?.({
        ...common,
        stage: "PLAYBACK_BUFFER",
        observedMonotonicS: performance.now() / 1_000,
      });
    }
    syncDynamicScene(
      scene,
      display.vehicles,
      historicalPath,
      { sensors: sensorsVisible, trace: traceVisible, plan: false, truth: truthVisible },
      model.mode === "REPLAY",
      missionPreview,
      selectedVehicleIds,
    );
    if (displayHealthRef.current) {
      displayHealthRef.current.textContent = display.health;
      displayHealthRef.current.dataset.health = display.health;
      displayHealthRef.current.hidden = display.health === "CURRENT";
    }
    canvas.dataset.displayHealth = display.health;
    canvas.dataset.presentationOnly = "true";
    canvas.dataset.rawEvidence = "false";
    bindSceneMotion(scene, motionRef.current);
    const selectedVehicle = model.vehicles.filter((vehicle) => vehicle.selected);
    const previewVehicles = missionPreview?.vehicles ?? [];
    selectedMotionKeyRef.current = previewVehicles.length === 1
      ? previewMotionKey(missionPreview!.missionId, previewVehicles[0]!.vehicleId)
      : selectedVehicle.length === 1 ? vehicleMotionKey(selectedVehicle[0]!, false) : undefined;
    if (previewVehicles.length) {
      const center = previewVehicles.reduce(
        (sum, vehicle) => sum.add(toThree(vehicle.start)),
        new Vector3(),
      ).multiplyScalar(1 / previewVehicles.length);
      orbitTargetRef.current.copy(center);
      const spread = Math.max(
        ...previewVehicles.map((vehicle) => toThree(vehicle.start).distanceTo(center)),
      );
      orbitRef.current.radius = Math.max(
        MIN_ORBIT_RADIUS_M,
        Math.min(MAX_ORBIT_RADIUS_M, 2.2 + spread * 2.2),
      );
    }
    const selectedMotion = selectedMotionKeyRef.current
      ? motionRef.current.get(selectedMotionKeyRef.current)
      : undefined;
    if (selectedMotion) orbitTargetRef.current.copy(selectedMotion.position);
    canvas.dataset.sceneObjects = String(scene.children.length);
    const renderer = rendererRef.current;
    const camera = cameraRef.current;
    if (renderer && camera) {
      applyPreset(camera, cameraPresetRef.current, orbitRef.current, orbitTargetRef.current);
      renderer.render(scene, camera);
      for (const timing of display.timings) {
        onDisplayTimingRef.current?.({
          correlationId: timing.sample.correlationId,
          stage: "RENDER_FRAME",
          sourceTimestampS: timing.sample.sourceTimestampS,
          sourceClockId: timing.sample.sourceClockId,
          sourceClockEpoch: timing.sample.sourceClockEpoch,
          observedMonotonicS: performance.now() / 1_000,
          playbackBufferAgeS: timing.diagnostics.playbackBufferAgeS,
          droppedSamples: timing.diagnostics.droppedSamples,
          coalescedSamples: timing.diagnostics.coalescedSamples,
        });
      }
    }
  }, [model.mode, model.selectedVehicleId, model.vehicles, historicalPath, sensorsVisible, traceVisible, truthVisible, missionPreview, selectedVehicleIds, staticSceneSignature]);

  if (!model.room) {
    return <div className="room-empty"><Layers3 size={24} /><strong>No room</strong></div>;
  }

  const estimate = selected?.telemetry?.estimate;
  const hasVehicleObservation = model.vehicles.some((vehicle) => vehicle.telemetry?.estimate);
  const hasSensors = selectedVehicles.some((vehicle) => vehicle.telemetry?.ranges.length);
  const hasTruth = selectedVehicles.some((vehicle) => vehicle.telemetry?.simulatedTruth);
  const changePreset = (preset: CameraPreset) => {
    cameraPresetRef.current = preset;
    setCameraPreset(preset);
    if (cameraRef.current) applyPreset(cameraRef.current, preset, orbitRef.current, orbitTargetRef.current);
  };
  const changeZoom = (wheelDelta: number) => {
    orbitRef.current.radius = zoomOrbitRadius(orbitRef.current.radius, wheelDelta);
    cameraPresetRef.current = "perspective";
    setCameraPreset("perspective");
    if (cameraRef.current) applyOrbit(cameraRef.current, orbitRef.current, orbitTargetRef.current);
  };

  return (
    <section className="room-stage" aria-label={`3D room ${model.room.id}`}>
      <div className="room-canvas-wrap">
        <canvas id="room-scene" ref={canvasRef} className="room-canvas" role="img" tabIndex={-1} aria-label={`Configured 3D room ${model.room.id}${missionPreview ? ` previewing ${missionPreview.vehicles.length} mission ${missionPreview.vehicles.length === 1 ? "vehicle" : "vehicles"}` : estimate ? ` with a selected vehicle at ${formatVec(estimate)}` : hasVehicleObservation ? " with no selected vehicles; commands target all drones" : " with no vehicle observation"}`} />
        {onVehicleSelectionChange ? (
          <div className="scene-selection-accessibility" role="group" aria-label="Drone selection">
            {(missionPreview
              ? missionPreview.vehicles
                  .filter((vehicle) => vehicle.existingVehicle)
                  .map((vehicle) => ({ id: vehicle.vehicleId, name: vehicle.displayName }))
              : model.vehicles
            ).map((vehicle) => (
              <button
                type="button"
                key={vehicle.id}
                aria-pressed={selectedVehicleIds?.includes(vehicle.id)
                  ?? model.vehicles.find((item) => item.id === vehicle.id)?.selected
                  ?? false}
                onClick={() => onVehicleSelectionChange(vehicle.id)}
              >
                Toggle {vehicle.name} selection
              </button>
            ))}
            <button type="button" onClick={() => onVehicleSelectionChange(undefined)}>Clear drone selection</button>
          </div>
        ) : null}
        {!missionPreview && !hasVehicleObservation ? (
          <div className="room-no-observation"><CircleDotIcon /><strong>NO DATA</strong></div>
        ) : null}
        <div ref={displayHealthRef} className="room-display-health" hidden aria-live="polite" />
      </div>
      <div className="scene-controls" aria-label="3D room controls">
        <div className="segmented">
          <button className={cameraPreset === "perspective" ? "is-active" : ""} type="button" aria-label="Perspective view" onClick={() => changePreset("perspective")}><Eye size={15} /><span>Perspective</span></button>
          <button className={cameraPreset === "top" ? "is-active" : ""} type="button" aria-label="Top view" onClick={() => changePreset("top")}><ScanLine size={15} /><span>Top</span></button>
          <button className={cameraPreset === "side" ? "is-active" : ""} type="button" aria-label="Side view" onClick={() => changePreset("side")}><Crosshair size={15} /><span>Side</span></button>
          <button type="button" aria-label="Zoom in on selected drone" onClick={() => changeZoom(-1_000)}><ZoomIn size={15} /><span>Zoom in</span></button>
          <button type="button" aria-label="Zoom out from selected drone" onClick={() => changeZoom(500)}><ZoomOut size={15} /><span>Zoom out</span></button>
        </div>
        <div className="layer-menu">
          <button className="layer-toggle" type="button" aria-label="Scene layers" aria-expanded={layersOpen} onClick={() => setLayersOpen((open) => !open)}><Layers3 size={15} /></button>
          {layersOpen ? (
            <div className="layer-popover">
              {pathPointCount(plannedPath) > 1 ? <LayerButton label="Plan" active={layers.plan} onClick={() => setLayers((value) => ({ ...value, plan: !value.plan }))} /> : null}
              {pathPointCount(historicalPath) > 1 ? <LayerButton label="Trace" active={layers.trace} onClick={() => setLayers((value) => ({ ...value, trace: !value.trace }))} /> : null}
              {hasTruth ? <LayerButton label="Truth" active={layers.truth} onClick={() => setLayers((value) => ({ ...value, truth: !value.truth }))} /> : null}
              {hasSensors ? <LayerButton label="Ranges" active={layers.sensors} onClick={() => setLayers((value) => ({ ...value, sensors: !value.sensors }))} /> : null}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function sourceBufferedVehicles(
  vehicles: VehicleView[],
  buffers: Map<string, SourceTimePlaybackBuffer>,
): {
  vehicles: VehicleView[];
  health: "BUFFERING" | "CURRENT" | "DISPLAY_DELAYED";
  timings: {
    sample: Parameters<SourceTimePlaybackBuffer["push"]>[0];
    diagnostics: ReturnType<SourceTimePlaybackBuffer["diagnostics"]>;
  }[];
} {
  const health: ("BUFFERING" | "CURRENT" | "DISPLAY_DELAYED")[] = [];
  const timings: {
    sample: Parameters<SourceTimePlaybackBuffer["push"]>[0];
    diagnostics: ReturnType<SourceTimePlaybackBuffer["diagnostics"]>;
  }[] = [];
  const displayVehicles = vehicles.map((vehicle) => {
    const telemetry = vehicle.telemetry;
    const position = telemetry?.estimate;
    const provenance = telemetry?.provenance;
    const sourceTimestampS = provenance?.simulationTimeS ?? provenance?.sourceTimeS;
    if (!telemetry || !position || !provenance || sourceTimestampS === undefined) return vehicle;
    const buffer = buffers.get(vehicle.id) ?? new SourceTimePlaybackBuffer();
    buffers.set(vehicle.id, buffer);
    const attitude = telemetry.attitude ?? { rollRad: 0, pitchRad: 0, yawRad: telemetry.yawRad ?? 0 };
    const orientation = new Quaternion().setFromEuler(
      new Euler(attitude.rollRad, attitude.pitchRad, attitude.yawRad, "XYZ"),
    );
    const sample = {
      correlationId: provenance.correlationId
        ?? `${provenance.sourceClockId ?? vehicle.id}:${provenance.sourceClockEpoch ?? 0}:${provenance.sequence ?? sourceTimestampS}`,
      sequence: provenance.sequence ?? Math.round(sourceTimestampS * 1_000_000),
      sourceTimestampS,
      sourceClockId: provenance.sourceClockId ?? vehicle.id,
      sourceClockEpoch: provenance.sourceClockEpoch ?? 0,
      receivedMonotonicS: performance.now() / 1_000,
      position,
      orientation: { w: orientation.w, x: orientation.x, y: orientation.y, z: orientation.z },
    };
    buffer.push(sample);
    const rendered = buffer.render();
    const diagnostics = buffer.diagnostics();
    timings.push({ sample, diagnostics });
    health.push(diagnostics.health);
    if (!rendered) return { ...vehicle, telemetry: { ...telemetry, estimate: undefined } };
    const renderedEuler = new Euler().setFromQuaternion(
      new Quaternion(
        rendered.orientation.x,
        rendered.orientation.y,
        rendered.orientation.z,
        rendered.orientation.w,
      ),
      "XYZ",
    );
    return {
      ...vehicle,
      telemetry: {
        ...telemetry,
        estimate: rendered.position,
        attitude: {
          rollRad: renderedEuler.x,
          pitchRad: renderedEuler.y,
          yawRad: renderedEuler.z,
        },
        yawRad: renderedEuler.z,
      },
    };
  });
  const aggregate = health.includes("DISPLAY_DELAYED")
    ? "DISPLAY_DELAYED"
    : health.includes("BUFFERING")
      ? "BUFFERING"
      : "CURRENT";
  return { vehicles: displayVehicles, health: aggregate, timings };
}

export function formatClockContext(provenance: Provenance): string {
  const source = provenance.sourceTimeS;
  const received = provenance.receiveTimeS;
  const simulation = provenance.simulationTimeS;
  const replay = provenance.replayTimeS;
  if (replay !== undefined) return `replay ${replay.toFixed(2)} s · source ${source?.toFixed(2) ?? "—"} s`;
  if (simulation !== undefined) return `sim ${simulation.toFixed(2)} s · received ${received?.toFixed(2) ?? "—"} s`;
  return `source ${source?.toFixed(2) ?? "—"} s · received ${received?.toFixed(2) ?? "—"} s`;
}

function LayerButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return <button type="button" className={active ? "is-active" : ""} aria-pressed={active} onClick={onClick}>{label}</button>;
}

function CircleDotIcon() { return <span className="empty-dot" aria-hidden="true" />; }

export function buildScene(
  room: RoomView,
  vehicles: VehicleView[],
  plannedPath: ScenePathSet,
  historicalPath: ScenePathSet,
  layers: SceneLayers,
  replay = false,
  homeBases?: HomeBaseView[],
  missionPreview?: MissionPreview,
) {
  const scene = buildStaticScene(room, plannedPath, layers.plan, homeBases, vehicles[0]?.id ?? "home");
  syncDynamicScene(scene, vehicles, historicalPath, layers, replay, missionPreview);
  return scene;
}

export function buildStaticScene(
  room: RoomView,
  plannedPath: ScenePathSet,
  planVisible: boolean,
  homeBases?: HomeBaseView[],
  fallbackHomeVehicleId = "home",
) {
  const scene = new Scene();
  scene.add(new AmbientLight(0xffffff, 1.35));
  const key = new DirectionalLight(0xffffff, 2.4);
  key.position.set(-3, 6, 4);
  scene.add(key);
  const floor = new Mesh(new PlaneGeometry(room.widthM, room.depthM), new MeshStandardMaterial({ color: 0x050505, roughness: 0.92, metalness: 0.02 }));
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);
  const grid = new GridHelper(Math.max(room.widthM, room.depthM), 16, 0x242424, 0x111111);
  grid.position.y = 0.006;
  scene.add(grid);
  const bounds = new BoxGeometry(room.widthM, room.heightM, room.depthM);
  const edges = new LineSegments(new EdgesGeometry(bounds), new LineBasicMaterial({ color: 0x444444, transparent: true, opacity: 0.66 }));
  edges.position.y = room.heightM / 2;
  scene.add(edges);
  if (room.geofence) {
    const minimum = room.geofence.minimum;
    const maximum = room.geofence.maximum;
    const geometry = new BoxGeometry(maximum.x - minimum.x, maximum.z - minimum.z, maximum.y - minimum.y);
    const fence = new LineSegments(new EdgesGeometry(geometry), new LineDashedMaterial({ color: 0xe9ecf0, dashSize: 0.07, gapSize: 0.06, transparent: true, opacity: 0.42 }));
    fence.position.set((minimum.x + maximum.x) / 2, (minimum.z + maximum.z) / 2, (minimum.y + maximum.y) / 2);
    fence.computeLineDistances();
    scene.add(fence);
  }
  const bases = homeBases?.length
    ? homeBases
    : room.home
      ? [{ vehicleId: fallbackHomeVehicleId, number: 1, position: room.home }]
      : [];
  for (const base of bases) addHome(scene, base.position, base.number, base.vehicleId);
  for (const obstacle of room.obstacles) addObstacle(scene, obstacle.minimum, obstacle.maximum);
  const legacyPlan = Array.isArray(plannedPath);
  const plans = legacyPlan
    ? [["selected", plannedPath] as const]
    : Object.entries(plannedPath);
  if (planVisible) {
    plans.forEach(([vehicleId, points]) => {
      addPath(scene, points, 0xe9ecf0, true, legacyPlan ? "planned" : `planned-${vehicleId}`);
      if (points.length) addTarget(scene, points.at(-1)!);
    });
  }
  return scene;
}

export function syncDynamicScene(
  scene: Scene,
  vehicles: VehicleView[],
  historicalPath: ScenePathSet,
  layers: SceneLayers,
  replay = false,
  missionPreview?: MissionPreview,
  selectedVehicleIds?: string[],
) {
  clearSceneLayers(scene, "dynamic", "trace");
  const selectedIds = new Set(
    selectedVehicleIds
      ?? vehicles.filter((vehicle) => vehicle.selected).map((vehicle) => vehicle.id),
  );
  if (layers.trace) {
    const legacyHistory = Array.isArray(historicalPath);
    const histories = legacyHistory
      ? [["selected", historicalPath] as const]
      : Object.entries(historicalPath);
    const colors = [0x4cc9e8, 0xa78bfa, 0xf2c45e, 0x7ddf8a];
    histories.forEach(([vehicleId, points], index) => {
      const path = addPath(
        scene,
        points,
        replay ? 0xa78bfa : colors[index % colors.length]!,
        replay,
        replay
          ? legacyHistory ? "replay" : `replay-${vehicleId}`
          : legacyHistory ? "received-estimate" : `received-estimate-${vehicleId}`,
      );
      if (path) path.userData.sceneLayer = "trace";
    });
  }
  if (missionPreview) {
    missionPreview.vehicles.forEach((vehicle) => {
      addVehicle(
        scene,
        vehicle.vehicleId,
        previewMotionKey(missionPreview.missionId, vehicle.vehicleId),
        vehicle.start,
        undefined,
        selectedIds.has(vehicle.vehicleId),
        false,
      );
    });
    return;
  }
  for (const vehicle of vehicles) {
    const data = vehicle.telemetry;
    if (!data?.estimate) continue;
    const observedMotionKey = vehicleMotionKey(vehicle, false);
    addVehicle(scene, vehicle.id, observedMotionKey, data.estimate, data.attitude, vehicle.selected, false);
    if (data.velocity && Math.hypot(data.velocity.x, data.velocity.y, data.velocity.z) > 0.005) {
      const velocityPath = addPath(scene, [data.estimate, {
        x: data.estimate.x + data.velocity.x,
        y: data.estimate.y + data.velocity.y,
        z: data.estimate.z + data.velocity.z,
      }], 0x4cc9e8, false, "received-velocity", observedMotionKey);
      if (velocityPath) velocityPath.userData.sceneLayer = "dynamic";
    }
    if (layers.truth && data.simulatedTruth) {
      addVehicle(scene, vehicle.id, vehicleMotionKey(vehicle, true), data.simulatedTruth, data.attitude, false, true);
    }
    if (layers.sensors && vehicle.selected) addRanges(scene, vehicle, observedMotionKey);
  }
}

function pathPointCount(value: ScenePathSet) {
  return Array.isArray(value)
    ? value.length
    : Object.values(value).reduce((total, points) => total + points.length, 0);
}

function addHome(scene: Scene, home: Vec3, number: number, vehicleId: string) {
  const group = new Group();
  group.userData.visualRole = "vehicle-home-base";
  group.userData.vehicleId = vehicleId;
  group.userData.baseNumber = number;
  group.position.copy(toThree({ ...home, z: 0 }));
  const ring = new Mesh(new CircleGeometry(0.16, 40), new MeshBasicMaterial({ color: 0xffffff, side: DoubleSide }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.012;
  group.add(ring);
  const center = new Mesh(new CircleGeometry(0.105, 40), new MeshBasicMaterial({ color: 0x050505, side: DoubleSide }));
  center.rotation.x = -Math.PI / 2;
  center.position.y = 0.016;
  group.add(center);
  addBaseNumber(group, number);
  scene.add(group);
}

const PAD_DIGITS: Record<string, string[]> = {
  "0": ["111", "101", "101", "101", "111"],
  "1": ["010", "110", "010", "010", "111"],
  "2": ["111", "001", "111", "100", "111"],
  "3": ["111", "001", "111", "001", "111"],
  "4": ["101", "101", "111", "001", "001"],
  "5": ["111", "100", "111", "001", "111"],
  "6": ["111", "100", "111", "101", "111"],
  "7": ["111", "001", "010", "010", "010"],
  "8": ["111", "101", "111", "101", "111"],
  "9": ["111", "101", "111", "001", "111"],
};

function addBaseNumber(base: Group, number: number) {
  const label = String(number);
  const digitSize = label.length > 1 ? 0.014 : 0.021;
  const digitGap = digitSize * 0.65;
  const digitWidth = digitSize * 3;
  const totalWidth = label.length * digitWidth + Math.max(0, label.length - 1) * digitGap;
  const numberGroup = new Group();
  numberGroup.userData.visualRole = "home-base-number";
  numberGroup.userData.label = label;
  label.split("").forEach((digit, digitIndex) => {
    const pattern = PAD_DIGITS[digit] ?? PAD_DIGITS["0"]!;
    pattern.forEach((row, rowIndex) => {
      row.split("").forEach((pixel, columnIndex) => {
        if (pixel !== "1") return;
        const mark = new Mesh(
          new PlaneGeometry(digitSize * 0.72, digitSize * 0.72),
          new MeshBasicMaterial({ color: 0xffffff, side: DoubleSide }),
        );
        mark.rotation.x = -Math.PI / 2;
        mark.position.set(
          -totalWidth / 2 + digitWidth / 2 + digitIndex * (digitWidth + digitGap) + (columnIndex - 1) * digitSize,
          0.019,
          (rowIndex - 2) * digitSize,
        );
        numberGroup.add(mark);
      });
    });
  });
  base.add(numberGroup);
}

function addObstacle(scene: Scene, minimum: Vec3, maximum: Vec3) {
  const geometry = new BoxGeometry(maximum.x - minimum.x, maximum.z - minimum.z, maximum.y - minimum.y);
  const mesh = new Mesh(geometry, new MeshStandardMaterial({ color: 0x121212, roughness: 0.72 }));
  mesh.position.set((minimum.x + maximum.x) / 2, (minimum.z + maximum.z) / 2, (minimum.y + maximum.y) / 2);
  scene.add(mesh);
  const edges = new LineSegments(new EdgesGeometry(geometry), new LineBasicMaterial({ color: 0x3d3d3d }));
  edges.position.copy(mesh.position);
  scene.add(edges);
}

function addVehicle(
  scene: Scene,
  vehicleId: string,
  motionKey: string,
  position: Vec3,
  attitude: { rollRad: number; pitchRad: number; yawRad: number } | undefined,
  selected: boolean,
  truth: boolean,
) {
  const group = new Group();
  group.userData.sceneLayer = "dynamic";
  group.userData.visualRole = truth ? "simulator-truth" : "received-estimate";
  group.userData.vehicleId = vehicleId;
  group.userData.motionKey = motionKey;
  const color = truth ? 0xff7a45 : selected ? 0x4cc9e8 : 0xa3adb5;
  const material = new MeshStandardMaterial({ color, roughness: 0.32, metalness: 0.5, transparent: truth, opacity: truth ? 0.45 : 1, wireframe: truth });
  group.add(new Mesh(new SphereGeometry(0.07, 16, 10), material));
  if (selected && !truth) {
    group.add(new Mesh(new SphereGeometry(0.115, 18, 12), new MeshBasicMaterial({ color: 0x4cc9e8, wireframe: true, transparent: true, opacity: 0.28 })));
  }
  for (const rotation of [Math.PI / 4, -Math.PI / 4]) {
    const arm = new Mesh(new BoxGeometry(0.34, 0.018, 0.025), material);
    arm.rotation.y = rotation;
    group.add(arm);
  }
  for (const [x, z] of [[0.125, 0.125], [-0.125, 0.125], [0.125, -0.125], [-0.125, -0.125]]) {
    const rotor = new Mesh(new CylinderGeometry(0.055, 0.055, 0.008, 20), material);
    rotor.position.set(x, 0.035, z);
    group.add(rotor);
  }
  group.position.copy(toThree({
    ...position,
    z: Math.max(position.z, LANDED_DRONE_VISUAL_HEIGHT_M),
  }));
  const rollRad = attitude?.rollRad ?? 0;
  const pitchRad = attitude?.pitchRad ?? 0;
  const yawRad = attitude?.yawRad ?? 0;
  group.rotation.order = "YXZ";
  group.rotation.set(-rollRad, -yawRad, pitchRad);
  scene.add(group);
  if (!truth) {
    const headingPath = addPath(scene, [
      position,
      {
        x: position.x + Math.cos(yawRad) * 0.25,
        y: position.y + Math.sin(yawRad) * 0.25,
        z: position.z,
      },
    ], 0x4cc9e8, false, "received-heading", motionKey);
    if (headingPath) headingPath.userData.sceneLayer = "dynamic";
  }
}

function addRanges(scene: Scene, vehicle: VehicleView, motionKey: string) {
  const data = vehicle.telemetry;
  if (!data?.estimate) return;
  const origin = toThree(data.estimate);
  for (const ray of data.ranges) {
    const endpoint = rangeEndpoint(
      data.estimate,
      ray,
      data.yawRad ?? 0,
      data.attitude?.rollRad ?? 0,
      data.attitude?.pitchRad ?? 0,
    );
    if (!endpoint) continue;
    const geometry = new BufferGeometry().setFromPoints([origin, toThree(endpoint)]);
    const material = ray.freshness === "current"
      ? new LineBasicMaterial({ color: 0x4cc9e8, transparent: true, opacity: 0.62 })
      : new LineDashedMaterial({ color: 0xf2c45e, dashSize: 0.05, gapSize: 0.05, transparent: true, opacity: 0.5 });
    const line = new Line(geometry, material);
    line.userData.sceneLayer = "dynamic";
    line.userData.visualRole = "modeled-range";
    line.userData.followMotionKey = motionKey;
    if (material instanceof LineDashedMaterial) line.computeLineDistances();
    scene.add(line);
  }
}

function addPath(scene: Scene, points: Vec3[], color: number, dashed: boolean, role: string, followMotionKey?: string) {
  if (points.length < 2) return;
  const geometry = new BufferGeometry().setFromPoints(points.map(toThree));
  const material = dashed ? new LineDashedMaterial({ color, dashSize: 0.08, gapSize: 0.07, transparent: true, opacity: 0.7 }) : new LineBasicMaterial({ color, transparent: true, opacity: 0.9 });
  const line = new Line(geometry, material);
  line.userData.visualRole = role;
  if (followMotionKey) line.userData.followMotionKey = followMotionKey;
  if (dashed) line.computeLineDistances();
  scene.add(line);
  return line;
}

function addTarget(scene: Scene, target: Vec3) {
  const marker = new Mesh(
    new SphereGeometry(
      TARGET_DOME_RADIUS_M,
      14,
      8,
      0,
      Math.PI * 2,
      0,
      Math.PI / 2,
    ),
    new MeshBasicMaterial({ color: 0xffffff, wireframe: true }),
  );
  marker.userData.visualRole = "planned-target";
  marker.position.copy(toThree({
    ...target,
    z: target.z <= HOME_PAD_SURFACE_M ? HOME_PAD_SURFACE_M : target.z,
  }));
  scene.add(marker);
}

function toThree(point: Vec3) { return new Vector3(...worldToScene(point)); }

function vehicleMotionKey(vehicle: VehicleView, truth: boolean) {
  const epoch = vehicle.telemetry?.provenance.sourceClockEpoch ?? 0;
  return `${vehicle.id}:${truth ? "truth" : "observed"}:${epoch}`;
}

function previewMotionKey(missionId: string, vehicleId: string) {
  return `preview:${missionId}:${vehicleId}`;
}

export function frameSmoothingAlpha(deltaMs: number) {
  if (!Number.isFinite(deltaMs) || deltaMs <= 0) return 0;
  return 1 - Math.exp(-Math.min(deltaMs, MAX_FRAME_DELTA_MS) / VISUAL_SMOOTHING_TIME_MS);
}

function bindSceneMotion(scene: Scene, motions: Map<string, SceneMotion>) {
  const activeKeys = new Set<string>();
  scene.traverse((object) => {
    const motionKey = object.userData.motionKey;
    if (!(object instanceof Group) || typeof motionKey !== "string") return;
    activeKeys.add(motionKey);
    const targetPosition = object.position.clone();
    const targetOrientation = object.quaternion.clone();
    const existing = motions.get(motionKey);
    const motion = existing ?? {
      position: targetPosition.clone(),
      targetPosition: targetPosition.clone(),
      orientation: targetOrientation.clone(),
      targetOrientation: targetOrientation.clone(),
    };
    motion.targetPosition.copy(targetPosition);
    motion.targetOrientation.copy(targetOrientation);
    object.position.copy(motion.position);
    object.quaternion.copy(motion.orientation);
    motions.set(motionKey, motion);
  });
  for (const key of motions.keys()) {
    if (!activeKeys.has(key)) motions.delete(key);
  }
  positionMotionFollowers(scene, motions);
}

function animateSceneMotion(scene: Scene, motions: Map<string, SceneMotion>, deltaMs: number) {
  const alpha = frameSmoothingAlpha(deltaMs);
  if (alpha <= 0) return;
  scene.traverse((object) => {
    const motionKey = object.userData.motionKey;
    if (!(object instanceof Group) || typeof motionKey !== "string") return;
    const motion = motions.get(motionKey);
    if (!motion) return;
    motion.position.x += (motion.targetPosition.x - motion.position.x) * alpha;
    motion.position.y += (motion.targetPosition.y - motion.position.y) * alpha;
    motion.position.z += (motion.targetPosition.z - motion.position.z) * alpha;
    motion.orientation.slerp(motion.targetOrientation, alpha);
    object.position.copy(motion.position);
    object.quaternion.copy(motion.orientation);
  });
  positionMotionFollowers(scene, motions);
}

function positionMotionFollowers(scene: Scene, motions: Map<string, SceneMotion>) {
  scene.traverse((object) => {
    const motionKey = object.userData.followMotionKey;
    if (typeof motionKey !== "string") return;
    const motion = motions.get(motionKey);
    if (!motion) return;
    object.position.copy(motion.position).sub(motion.targetPosition);
  });
}

export function vehicleAtPointer(
  scene: Scene,
  camera: PerspectiveCamera,
  canvas: HTMLCanvasElement,
  clientX: number,
  clientY: number,
): string | undefined {
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return undefined;
  const pointer = new Vector2(
    ((clientX - bounds.left) / bounds.width) * 2 - 1,
    -((clientY - bounds.top) / bounds.height) * 2 + 1,
  );
  scene.updateMatrixWorld(true);
  camera.updateMatrixWorld(true);
  const raycaster = new Raycaster();
  raycaster.setFromCamera(pointer, camera);
  for (const intersection of raycaster.intersectObjects(scene.children, true)) {
    let object: Object3D | null = intersection.object;
    while (object) {
      if (
        object.userData.visualRole === "received-estimate"
        && typeof object.userData.vehicleId === "string"
      ) {
        return object.userData.vehicleId;
      }
      object = object.parent;
    }
  }
  return undefined;
}

function applyPreset(camera: PerspectiveCamera, preset: CameraPreset, orbit: { theta: number; phi: number; radius: number }, orbitTarget: Vector3) {
  if (preset === "top") camera.position.set(0, 7.2, 0.001);
  else if (preset === "side") camera.position.set(5.8, 1.35, 0);
  else {
    applyOrbit(camera, orbit, orbitTarget);
    return;
  }
  camera.lookAt(0, 0.45, 0);
}

function applyOrbit(camera: PerspectiveCamera, orbit: { theta: number; phi: number; radius: number }, target: Vector3) {
  camera.position.set(
    target.x + orbit.radius * Math.sin(orbit.phi) * Math.cos(orbit.theta),
    target.y + orbit.radius * Math.cos(orbit.phi),
    target.z + orbit.radius * Math.sin(orbit.phi) * Math.sin(orbit.theta),
  );
  camera.lookAt(target);
}

export function zoomOrbitRadius(radius: number, wheelDelta: number) {
  const nextRadius = radius * Math.exp(wheelDelta * ZOOM_RATE);
  return Math.max(MIN_ORBIT_RADIUS_M, Math.min(MAX_ORBIT_RADIUS_M, nextRadius));
}

function normalizedWheelDelta(event: WheelEvent, pageHeight: number) {
  if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) return event.deltaY * 16;
  if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) return event.deltaY * pageHeight;
  return event.deltaY;
}

export function disposeScene(scene: Scene) {
  disposeObjectTree(scene);
}

function clearSceneLayers(scene: Scene, ...layers: string[]) {
  const layerSet = new Set(layers);
  for (const child of [...scene.children]) {
    if (!layerSet.has(String(child.userData.sceneLayer ?? ""))) continue;
    scene.remove(child);
    disposeObjectTree(child);
  }
}

function disposeObjectTree(root: Object3D) {
  root.traverse((object) => {
    if (object instanceof Mesh || object instanceof Line || object instanceof LineSegments) {
      object.geometry.dispose();
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose();
    }
  });
}

function formatVec(point: Vec3) { return `X ${signed(point.x)}  Y ${signed(point.y)}  Z ${signed(point.z)} m`; }
function signed(value: number) { return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`; }
