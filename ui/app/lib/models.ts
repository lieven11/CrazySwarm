export type OperatingMode = "SIM" | "LIVE" | "SHADOW" | "REPLAY";
export type EvidenceClass =
  | "MEASURED_REAL"
  | "SIMULATED_MODEL"
  | "DERIVED"
  | "PLANNED"
  | "CONFIGURED"
  | "REPLAYED"
  | "UNAVAILABLE";
export type Freshness = "current" | "stale" | "invalid" | "absent";
export type Health = "HEALTHY" | "DEGRADED" | "FAILED" | "UNKNOWN";

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Provenance {
  evidenceClass: EvidenceClass;
  source: string;
  timestamp?: string;
  sourceTimeS?: number;
  receiveTimeS?: number;
  simulationTimeS?: number;
  replayTimeS?: number;
  sourceClockId?: string;
  sourceClockEpoch?: number;
  ageMs?: number;
  unit: string;
  frame: "world" | "home" | "body" | "sensor";
  freshness: Freshness;
}

export interface RangeRay {
  direction: "front" | "back" | "left" | "right" | "up" | "down";
  distanceM: number | null;
  maximumM: number;
  freshness: Freshness;
}

export interface DeckView {
  id: string;
  name: string;
  type: "flow" | "multiranger" | "lighthouse" | "loco" | "ai";
  health: Health;
}

export interface ImuView {
  acceleration: Vec3;
  angularVelocity: Vec3;
  provenance: Provenance;
}

export interface FlowView {
  velocity: Vec3;
  groundDistanceM?: number;
  qualityPercent?: number;
  provenance: Provenance;
}

export interface TransportView {
  kind: "physical_radio" | "modeled_transport" | "replay";
  evidenceClass: EvidenceClass;
  deliveryQualityPercent?: number;
  latencyMs?: number;
  packetLossPercent?: number;
}

export interface RadioView {
  qualityPercent?: number;
  latencyMs?: number;
  packetLossPercent?: number;
  evidenceClass: EvidenceClass;
}

export interface TelemetryView {
  armed: boolean;
  flying: boolean;
  estimate?: Vec3;
  simulatedTruth?: Vec3;
  velocity?: Vec3;
  attitude?: { rollRad: number; pitchRad: number; yawRad: number };
  yawRad?: number;
  batteryPercent?: number;
  batteryVoltage?: number;
  batteryCurrent?: number;
  localizationPercent?: number;
  localizationLabel?: string;
  imu?: ImuView;
  flow?: FlowView;
  ranges: RangeRay[];
  motors?: {
    modelId: string;
    modelVersion: string;
    readings: { id: "M1" | "M2" | "M3" | "M4"; commandPercent: number; thrustN: number; currentA: number }[];
  };
  transport?: TransportView;
  radio?: RadioView;
  faults: string[];
  provenance: Provenance;
}

export interface VehicleView {
  id: string;
  name: string;
  adapter: "sim" | "cflib" | "replay";
  selected: boolean;
  state: string;
  commandAuthority: boolean;
  observationStatus: "NOT_STARTED" | "ACTIVE" | "COMPLETED_SNAPSHOT" | "UNAVAILABLE";
  observationClass: EvidenceClass;
  observationRunId?: string;
  telemetry?: TelemetryView;
  decks: DeckView[];
  capabilities: string[];
  radioUri?: string;
  firmwareVersion?: string;
  armed?: boolean;
  flying?: boolean;
}

export interface PreflightCheckView {
  code: string;
  passed: boolean;
  message: string;
}

export interface PreflightReportView {
  reportId: string;
  approved: boolean;
  expiresAtMonotonicS: number;
  checks: PreflightCheckView[];
}

export interface ParameterView {
  name: string;
  value: number | string | boolean;
  default?: number | string | boolean;
  valueType: string;
  access: "READ_ONLY" | "READ_WRITE";
  persistence: "SESSION" | "STORED";
  minimum?: number;
  maximum?: number;
  unit?: string;
  sourceClass: "CONFIGURED" | "MEASURED_REAL";
}

export interface TwinDeviationView {
  sourceTimestampS: number;
  observedLatencyMs: number;
  simulatedLatencyMs: number;
  alignmentDeltaMs: number;
  positionM?: number;
  altitudeM?: number;
  velocityMS?: number;
  yawRad?: number;
  batteryPercent?: number;
  frame: string;
  validity: "VALID" | "UNAVAILABLE" | "INCOMPATIBLE";
}

export interface TwinSessionView {
  id: string;
  status: string;
  observedVehicleId: string;
  simulatedVehicleId: string;
  groundTruthAvailable: boolean;
  latestDeviation?: TwinDeviationView;
}

export interface ObstacleView {
  id: string;
  minimum: Vec3;
  maximum: Vec3;
}

export interface RoomView {
  id: string;
  widthM: number;
  depthM: number;
  heightM: number;
  home?: Vec3;
  geofence?: { minimum: Vec3; maximum: Vec3 };
  obstacles: ObstacleView[];
  source: "configured";
  frame: "world";
  version: number;
}

export interface MissionOption {
  id: string;
  version: string;
  name: string;
  description: string;
  sourceKind: "UPLOADED_PYTHON";
  sourceFilename: string;
  sourceSha256: string;
  plannedCommands: Array<{
    action: "takeoff" | "hover" | "move_relative" | "land";
    arguments: Record<string, number | string>;
  }>;
}

export interface MissionRunView {
  id: string;
  missionId: string;
  vehicleId: string;
  phase: string;
  status: "RUNNING" | "SUCCEEDED" | "ABORTED" | "FAILED";
  parameters: Record<string, number | string | boolean>;
  resultMessage?: string;
}

export interface RunHistoryView {
  runId: string;
  missionId: string;
  vehicleId: string;
  status: "SUCCEEDED" | "ABORTED" | "FAILED" | "INCOMPLETE";
  configurationHash: string;
  startedAtUtc: string;
}

export interface ReplayView {
  runId: string;
  index: number;
  eventCount: number;
  nowS: number;
  paused: boolean;
  speed: number;
  eventKind?: string;
}

export interface FidelityManifest {
  id: string;
  sourceClass: "SIMULATED_MODEL";
  model: string;
  modeledOutputs: string[];
  omittedOutputs: string[];
  limitations: string[];
}

export interface DashboardModel {
  mode?: OperatingMode;
  apiConnected: boolean;
  serviceLabel: string;
  selectedVehicleId?: string;
  vehicles: VehicleView[];
  room?: RoomView;
  missions: MissionOption[];
  latestRun?: MissionRunView;
  fidelity?: FidelityManifest;
  twins: TwinSessionView[];
  fault?: { code: string; message: string };
}
