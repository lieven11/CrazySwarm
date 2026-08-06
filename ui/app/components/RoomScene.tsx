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
  GridHelper,
  Group,
  Line,
  LineBasicMaterial,
  LineDashedMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PerspectiveCamera,
  PlaneGeometry,
  Scene,
  SphereGeometry,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { useEffect, useRef, useState } from "react";
import { Crosshair, Eye, Layers3, ScanLine } from "lucide-react";
import type { DashboardModel, Provenance, RoomView, Vec3, VehicleView } from "../lib/models";
import { rangeEndpoint, worldToScene } from "../lib/spatial";

type CameraPreset = "perspective" | "top" | "side";

export function RoomScene({ model, plannedPath, historicalPath }: { model: DashboardModel; plannedPath: Vec3[]; historicalPath: Vec3[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cameraRef = useRef<PerspectiveCamera | null>(null);
  const rendererRef = useRef<WebGLRenderer | null>(null);
  const sceneRef = useRef<Scene | null>(null);
  const orbitRef = useRef({ theta: 0.76, phi: 0.9, radius: 6.4 });
  const cameraPresetRef = useRef<CameraPreset>("perspective");
  const pointerRef = useRef(new Vector2());
  const draggingRef = useRef(false);
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>("perspective");
  const [layers, setLayers] = useState({ sensors: true, trace: true, plan: true, truth: true });
  const selected = model.vehicles.find((vehicle) => vehicle.id === model.selectedVehicleId);
  const roomAvailable = Boolean(model.room);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !roomAvailable) return;
    const container = canvas.parentElement;
    if (!container) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ canvas, antialias: true });
    } catch {
      canvas.dataset.webgl = "unavailable";
      return;
    }
    rendererRef.current = renderer;
    renderer.setClearColor(new Color("#0b0b0b"), 1);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.6));
    const camera = new PerspectiveCamera(42, 1, 0.05, 100);
    cameraRef.current = camera;
    applyPreset(camera, cameraPresetRef.current, orbitRef.current);

    const pointerDown = (event: PointerEvent) => {
      draggingRef.current = true;
      pointerRef.current.set(event.clientX, event.clientY);
      canvas.setPointerCapture(event.pointerId);
    };
    const pointerMove = (event: PointerEvent) => {
      if (!draggingRef.current || cameraPresetRef.current === "top") return;
      orbitRef.current.theta += (event.clientX - pointerRef.current.x) * 0.007;
      orbitRef.current.phi = Math.max(0.25, Math.min(1.42, orbitRef.current.phi + (event.clientY - pointerRef.current.y) * 0.006));
      pointerRef.current.set(event.clientX, event.clientY);
      applyOrbit(camera, orbitRef.current);
    };
    const pointerUp = (event: PointerEvent) => {
      draggingRef.current = false;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      orbitRef.current.radius = Math.max(3.2, Math.min(10, orbitRef.current.radius + event.deltaY * 0.006));
      if (cameraPresetRef.current === "perspective") applyOrbit(camera, orbitRef.current);
    };
    canvas.addEventListener("pointerdown", pointerDown);
    canvas.addEventListener("pointermove", pointerMove);
    canvas.addEventListener("pointerup", pointerUp);
    canvas.addEventListener("pointercancel", pointerUp);
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
    let frame = requestAnimationFrame(function render(timestampMs) {
      if (sceneRef.current) renderer.render(sceneRef.current, camera);
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
      canvas.removeEventListener("pointercancel", pointerUp);
      canvas.removeEventListener("wheel", wheel);
      renderer.dispose();
      rendererRef.current = null;
      cameraRef.current = null;
      draggingRef.current = false;
    };
  }, [roomAvailable]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !model.room) return;
    const nextScene = buildScene(
      model.room,
      model.vehicles,
      plannedPath,
      historicalPath,
      layers,
      model.mode === "REPLAY",
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
  }, [model.mode, model.room, model.vehicles, plannedPath, historicalPath, layers]);

  if (!model.room) {
    return <div className="room-empty"><Layers3 size={24} /><strong>No room</strong></div>;
  }

  const estimate = selected?.telemetry?.estimate;
  const hasSensors = Boolean(selected?.telemetry?.ranges.length);
  const hasTruth = Boolean(selected?.telemetry?.simulatedTruth);
  const changePreset = (preset: CameraPreset) => {
    cameraPresetRef.current = preset;
    setCameraPreset(preset);
    if (cameraRef.current) applyPreset(cameraRef.current, preset, orbitRef.current);
  };

  return (
    <section className="room-stage" aria-label={`3D room ${model.room.id}`}>
      <div className="room-canvas-wrap">
        <canvas id="room-scene" ref={canvasRef} className="room-canvas" role="img" tabIndex={-1} aria-label={`Configured 3D room ${model.room.id}${estimate ? ` with an observed vehicle at ${formatVec(estimate)}` : " with no vehicle observation"}`} />
        {!estimate ? (
          <div className="room-no-observation"><CircleDotIcon /><strong>NO DATA</strong></div>
        ) : null}
      </div>
      <div className="scene-controls" aria-label="3D room controls">
        <div className="segmented">
          <button className={cameraPreset === "perspective" ? "is-active" : ""} type="button" onClick={() => changePreset("perspective")}><Eye size={14} />Perspective</button>
          <button className={cameraPreset === "top" ? "is-active" : ""} type="button" onClick={() => changePreset("top")}><ScanLine size={14} />Top</button>
          <button className={cameraPreset === "side" ? "is-active" : ""} type="button" onClick={() => changePreset("side")}><Crosshair size={14} />Side</button>
        </div>
        <div className="layer-buttons">
          {plannedPath.length > 1 ? <LayerButton label="Plan" active={layers.plan} onClick={() => setLayers((value) => ({ ...value, plan: !value.plan }))} /> : null}
          {historicalPath.length > 1 ? <LayerButton label="Trace" active={layers.trace} onClick={() => setLayers((value) => ({ ...value, trace: !value.trace }))} /> : null}
          {hasTruth ? <LayerButton label="Truth" active={layers.truth} onClick={() => setLayers((value) => ({ ...value, truth: !value.truth }))} /> : null}
          {hasSensors ? <LayerButton label="Ranges" active={layers.sensors} onClick={() => setLayers((value) => ({ ...value, sensors: !value.sensors }))} /> : null}
        </div>
      </div>
    </section>
  );
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
  plannedPath: Vec3[],
  historicalPath: Vec3[],
  layers: { sensors: boolean; trace: boolean; plan: boolean; truth: boolean },
  replay = false,
) {
  const scene = new Scene();
  scene.add(new AmbientLight(0xffffff, 1.35));
  const key = new DirectionalLight(0xffffff, 2.4);
  key.position.set(-3, 6, 4);
  scene.add(key);
  const floor = new Mesh(new PlaneGeometry(room.widthM, room.depthM), new MeshStandardMaterial({ color: 0x151515, roughness: 0.92, metalness: 0.02 }));
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);
  const grid = new GridHelper(Math.max(room.widthM, room.depthM), 16, 0x555555, 0x292929);
  grid.position.y = 0.006;
  scene.add(grid);
  const bounds = new BoxGeometry(room.widthM, room.heightM, room.depthM);
  const edges = new LineSegments(new EdgesGeometry(bounds), new LineBasicMaterial({ color: 0x5a5a5a, transparent: true, opacity: 0.7 }));
  edges.position.y = room.heightM / 2;
  scene.add(edges);
  if (room.geofence) {
    const minimum = room.geofence.minimum;
    const maximum = room.geofence.maximum;
    const geometry = new BoxGeometry(maximum.x - minimum.x, maximum.z - minimum.z, maximum.y - minimum.y);
    const fence = new LineSegments(new EdgesGeometry(geometry), new LineDashedMaterial({ color: 0x8a8a8a, dashSize: 0.07, gapSize: 0.06, transparent: true, opacity: 0.6 }));
    fence.position.set((minimum.x + maximum.x) / 2, (minimum.z + maximum.z) / 2, (minimum.y + maximum.y) / 2);
    fence.computeLineDistances();
    scene.add(fence);
  }
  if (room.home) addHome(scene, room.home);
  for (const obstacle of room.obstacles) addObstacle(scene, obstacle.minimum, obstacle.maximum);
  if (layers.plan) addPath(scene, plannedPath, 0xbdbdbd, true, "planned");
  if (layers.trace) {
    addPath(
      scene,
      historicalPath,
      replay ? 0x8fb7d8 : 0xffffff,
      replay,
      replay ? "replay" : "received-estimate",
    );
  }
  if (layers.plan && plannedPath.length) addTarget(scene, plannedPath.at(-1)!);
  for (const vehicle of vehicles) {
    const data = vehicle.telemetry;
    if (!data?.estimate) continue;
    addVehicle(scene, data.estimate, data.attitude, vehicle.selected, false);
    if (data.velocity && Math.hypot(data.velocity.x, data.velocity.y, data.velocity.z) > 0.005) {
      addPath(scene, [data.estimate, {
        x: data.estimate.x + data.velocity.x,
        y: data.estimate.y + data.velocity.y,
        z: data.estimate.z + data.velocity.z,
      }], 0x8a8a8a, false, "received-velocity");
    }
    if (layers.truth && data.simulatedTruth) addVehicle(scene, data.simulatedTruth, data.attitude, false, true);
    if (layers.sensors && vehicle.selected) addRanges(scene, vehicle);
  }
  return scene;
}

function addHome(scene: Scene, home: Vec3) {
  const ring = new Mesh(new CircleGeometry(0.16, 40), new MeshBasicMaterial({ color: 0xffffff, side: DoubleSide }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.copy(toThree({ ...home, z: 0.012 }));
  scene.add(ring);
  const center = new Mesh(new CircleGeometry(0.105, 40), new MeshBasicMaterial({ color: 0x151515, side: DoubleSide }));
  center.rotation.x = -Math.PI / 2;
  center.position.copy(toThree({ ...home, z: 0.016 }));
  scene.add(center);
}

function addObstacle(scene: Scene, minimum: Vec3, maximum: Vec3) {
  const geometry = new BoxGeometry(maximum.x - minimum.x, maximum.z - minimum.z, maximum.y - minimum.y);
  const mesh = new Mesh(geometry, new MeshStandardMaterial({ color: 0x242424, roughness: 0.72 }));
  mesh.position.set((minimum.x + maximum.x) / 2, (minimum.z + maximum.z) / 2, (minimum.y + maximum.y) / 2);
  scene.add(mesh);
  const edges = new LineSegments(new EdgesGeometry(geometry), new LineBasicMaterial({ color: 0x707070 }));
  edges.position.copy(mesh.position);
  scene.add(edges);
}

function addVehicle(scene: Scene, position: Vec3, attitude: { rollRad: number; pitchRad: number; yawRad: number } | undefined, selected: boolean, truth: boolean) {
  const group = new Group();
  group.userData.visualRole = truth ? "simulator-truth" : "received-estimate";
  const color = truth ? 0x777777 : selected ? 0xffffff : 0xa3a3a3;
  const material = new MeshStandardMaterial({ color, roughness: 0.32, metalness: 0.5, transparent: truth, opacity: truth ? 0.45 : 1, wireframe: truth });
  group.add(new Mesh(new SphereGeometry(0.07, 16, 10), material));
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
  group.position.copy(toThree(position));
  const rollRad = attitude?.rollRad ?? 0;
  const pitchRad = attitude?.pitchRad ?? 0;
  const yawRad = attitude?.yawRad ?? 0;
  group.rotation.order = "YXZ";
  group.rotation.set(-rollRad, -yawRad, pitchRad);
  scene.add(group);
  if (!truth) {
    addPath(scene, [
      position,
      {
        x: position.x + Math.cos(yawRad) * 0.25,
        y: position.y + Math.sin(yawRad) * 0.25,
        z: position.z,
      },
    ], 0xffffff, false, "received-heading");
  }
}

function addRanges(scene: Scene, vehicle: VehicleView) {
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
      ? new LineBasicMaterial({ color: 0xd0d0d0, transparent: true, opacity: 0.68 })
      : new LineDashedMaterial({ color: 0x777777, dashSize: 0.05, gapSize: 0.05, transparent: true, opacity: 0.5 });
    const line = new Line(geometry, material);
    line.userData.visualRole = "modeled-range";
    if (material instanceof LineDashedMaterial) line.computeLineDistances();
    scene.add(line);
  }
}

function addPath(scene: Scene, points: Vec3[], color: number, dashed: boolean, role: string) {
  if (points.length < 2) return;
  const geometry = new BufferGeometry().setFromPoints(points.map(toThree));
  const material = dashed ? new LineDashedMaterial({ color, dashSize: 0.08, gapSize: 0.07, transparent: true, opacity: 0.7 }) : new LineBasicMaterial({ color, transparent: true, opacity: 0.9 });
  const line = new Line(geometry, material);
  line.userData.visualRole = role;
  if (dashed) line.computeLineDistances();
  scene.add(line);
}

function addTarget(scene: Scene, target: Vec3) {
  const marker = new Mesh(new SphereGeometry(0.045, 14, 8), new MeshBasicMaterial({ color: 0xffffff, wireframe: true }));
  marker.position.copy(toThree(target));
  scene.add(marker);
}

function toThree(point: Vec3) { return new Vector3(...worldToScene(point)); }

function applyPreset(camera: PerspectiveCamera, preset: CameraPreset, orbit: { theta: number; phi: number; radius: number }) {
  if (preset === "top") camera.position.set(0, 7.2, 0.001);
  else if (preset === "side") camera.position.set(5.8, 1.35, 0);
  else applyOrbit(camera, orbit);
  camera.lookAt(0, 0.45, 0);
}

function applyOrbit(camera: PerspectiveCamera, orbit: { theta: number; phi: number; radius: number }) {
  camera.position.set(orbit.radius * Math.sin(orbit.phi) * Math.cos(orbit.theta), 0.45 + orbit.radius * Math.cos(orbit.phi), orbit.radius * Math.sin(orbit.phi) * Math.sin(orbit.theta));
  camera.lookAt(0, 0.45, 0);
}

export function disposeScene(scene: Scene) {
  scene.traverse((object) => {
    if (object instanceof Mesh || object instanceof Line || object instanceof LineSegments) {
      object.geometry.dispose();
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose();
    }
  });
}

function formatVec(point: Vec3) { return `X ${signed(point.x)}  Y ${signed(point.y)}  Z ${signed(point.z)} m`; }
function signed(value: number) { return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`; }
