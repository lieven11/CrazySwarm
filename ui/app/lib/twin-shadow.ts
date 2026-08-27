import type {
  PhysicalTwinLiveFrameView,
  PhysicalTwinSourceStatusView,
  Provenance,
  Vec3,
  VehicleView,
} from "./models";

const SHADOW_TRACE_LIMIT = 3_600;
const MINIMUM_TRACE_STEP_M = 0.001;

export interface TwinShadowState {
  sourceKey: string;
  origin: Vec3;
  lastRawSourceTimestampS?: number;
  vehicle: VehicleView;
  path: Vec3[];
}

export function twinLiveFrameFromStatus(
  status: {
    state: PhysicalTwinLiveFrameView["state"];
    vehicleLabel?: string;
    pairedCycleCount?: number;
    sampleCount: number;
    observed?: PhysicalTwinSourceStatusView;
    telemetryOwner?: "OBSERVER" | "PHYSICAL_OPERATION";
    operationSampleCount?: number;
  },
): PhysicalTwinLiveFrameView {
  return {
    state: status.state,
    vehicleLabel: status.vehicleLabel,
    liveSequence: status.observed?.pairSequence ?? status.pairedCycleCount ?? 0,
    pairedCycleCount: status.pairedCycleCount ?? 0,
    channelRecordCount: status.sampleCount,
    observed: status.observed,
    telemetryOwner: status.telemetryOwner,
    operationSampleCount: status.operationSampleCount,
  };
}

export function updateTwinShadow(
  current: TwinShadowState | undefined,
  frame: PhysicalTwinLiveFrameView,
): TwinShadowState | undefined {
  const source = frame.observed;
  if (!source?.position || source.freshness === "MISSING") return current;

  // The parent owns the physical-flight boundary and clears this state when that
  // flight ends. A reconnect may advance the source epoch or reset its raw clock
  // while the same onboard HOME-frame estimator continues flying. Keep the
  // presentation origin across that transport break so current altitude is not
  // incorrectly subtracted away and rendered on the floor.
  const sourceKey = source.vehicleId;
  const reset = !current || current.sourceKey !== sourceKey;
  const origin = reset ? source.position : current.origin;
  const position = relativePosition(source.position, origin);
  const path = appendShadowPoint(reset ? [] : current.path, position);

  return {
    sourceKey,
    origin,
    lastRawSourceTimestampS: source.rawSourceTimestampS,
    vehicle: shadowVehicle(frame, source, position),
    path,
  };
}

export function relativePosition(position: Vec3, origin: Vec3): Vec3 {
  return {
    x: position.x - origin.x,
    y: position.y - origin.y,
    z: Math.max(0, position.z - origin.z),
  };
}

function appendShadowPoint(points: Vec3[], point: Vec3): Vec3[] {
  const previous = points.at(-1);
  if (previous && Math.hypot(
    point.x - previous.x,
    point.y - previous.y,
    point.z - previous.z,
  ) < MINIMUM_TRACE_STEP_M) return points;
  return [...points, point].slice(-SHADOW_TRACE_LIMIT);
}

function shadowVehicle(
  frame: PhysicalTwinLiveFrameView,
  source: PhysicalTwinSourceStatusView,
  position: Vec3,
): VehicleView {
  const freshness = source.freshness === "CURRENT" ? "current" : "stale";
  const evidenceClass = source.sourceClass === "MEASURED_REAL"
    ? "MEASURED_REAL"
    : source.sourceClass === "SIMULATED_MODEL"
      ? "SIMULATED_MODEL"
      : "CONFIGURED";
  const ranges = source.ranges;
  const provenance: Provenance = {
    evidenceClass,
    source: source.sourceClass,
    sourceTimeS: source.rawSourceTimestampS ?? source.sourceTimestampS,
    sourceClockId: source.sourceClockId,
    sourceClockEpoch: source.sourceEpoch,
    sequence: frame.liveSequence,
    unit: "m",
    frame: "home" as const,
    freshness,
  };
  return {
    id: source.vehicleId,
    name: frame.vehicleLabel ?? "Crazyflie",
    adapter: "physical-twin-observer",
    backendRole: "TWIN_OBSERVER",
    authorityClass: "OBSERVATION_ONLY",
    selected: true,
    state: source.flying ? "FLYING" : "READY",
    commandAuthority: false,
    observationStatus: source.freshness === "CURRENT" ? "CURRENT" : "STALE",
    observationClass: evidenceClass,
    telemetry: {
      armed: source.armed ?? false,
      flying: source.flying ?? false,
      estimate: position,
      attitude: source.attitude,
      yawRad: source.attitude?.yawRad,
      batteryVoltage: source.batteryVoltage,
      imu: source.imu ? {
        ...source.imu,
        provenance: { ...provenance, unit: "m/s² · rad/s", frame: "body" },
      } : undefined,
      flow: source.flow?.velocity ? {
        velocity: source.flow.velocity,
        groundDistanceM: source.flow.groundDistanceM,
        qualityPercent: source.flow.qualityPercent,
        provenance: { ...provenance, unit: "m · m/s", frame: "body" },
      } : undefined,
      ranges: ranges ? ([
        ["front", ranges.frontM],
        ["back", ranges.backM],
        ["left", ranges.leftM],
        ["right", ranges.rightM],
        ["up", ranges.upM],
        ["down", ranges.downM],
      ] as const).map(([direction, distanceM]) => ({
        direction,
        distanceM: distanceM ?? null,
        maximumM: 4,
        freshness,
      })) : [],
      faults: source.faults ?? [],
      provenance,
    },
    decks: [],
    capabilities: [],
  };
}
