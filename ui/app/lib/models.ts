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
export type BackendRole = "FAST_SIM" | "ISAAC_SIM" | "REAL_CRAZYFLIE" | "REPLAY" | "TWIN_OBSERVER";
export type AuthorityClass = "SIMULATION" | "PHYSICAL" | "OBSERVATION_ONLY";

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
  sequence?: number;
  correlationId?: string;
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
  adapter: string;
  backendRole: BackendRole;
  authorityClass: AuthorityClass;
  selected: boolean;
  state: string;
  commandAuthority: boolean;
  observationStatus: "NOT_STARTED" | "ACTIVE" | "CURRENT" | "STALE" | "COMPLETED_SNAPSHOT" | "UNAVAILABLE";
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
  packageSchemaVersion: 1 | 2;
  logicalRoles: Array<{
    roleId: string;
    logicalVehicleId: string;
    initialRole: "ACTIVE" | "RESERVE";
  }>;
  plannedCommands: Array<{
    action: "takeoff" | "hover" | "move_relative" | "land";
    arguments: Record<string, number | string>;
  }>;
}

export type CampaignLifecycle = "DEFINED_NOT_RUN" | "READY" | "ACTIVE_DEVELOPMENT" | "BASELINED" | "PROMOTED" | "BLOCKED";

export interface CampaignCaseView {
  case_id: string;
  case_sha256: string;
  cluster: "BASIC_FLIGHT_AND_ROUTE_FOLLOWING" | "GEOMETRIC_CONFLICT_RESOLUTION" | "CONSTRAINTS_AND_OPTIMIZATION" | "COORDINATION_AND_ALLOCATION" | "FAILURE_RECOVERY_AND_REPLANNING";
  family: string;
  variation_name: string;
  purpose: string;
  behavior_under_test: string;
  expected_outcome: string;
  drone_count: 1 | 2 | 3;
  environment: "SIMULATION" | "REAL";
  authorization: "SOFTWARE_SIMULATION_ONLY" | "NOT_AUTHORIZED";
  implementation_status: "EXECUTABLE" | "PLANNED_NOT_EXECUTABLE";
  lifecycle: CampaignLifecycle;
  allowed_strategies: string[];
  objective_order: string[];
  expected_decisions: string[];
  execution_eligibility: "STATIC_VALIDATE_ONLY" | "AUTOMATED_ACCELERATED" | "OPERATOR_OBSERVED_REALTIME" | "BOTH";
  operator_observation_questions: string[];
  difficulty: number;
  prerequisites: string[];
  execution: {
    seed: number;
    repetitions: number;
    backend_profile_id: string;
    configuration_sha256: string;
  };
}

export interface CampaignCatalogView {
  cases: CampaignCaseView[];
  hierarchy: Record<string, Record<string, Record<string, Record<string, string[]>>>>;
}

export type CampaignRunStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "ABORTED" | "FAILED" | "CANCELLED_BEFORE_LAUNCH";
export type CampaignRunMode = "AUTOMATED_ACCELERATED" | "OPERATOR_OBSERVED_REALTIME";

export interface CampaignRunSummary {
  run_id: string;
  mode: CampaignRunMode;
  status: CampaignRunStatus;
  failure_reason?: string;
}

export interface CampaignRunView extends CampaignRunSummary {
  locked_inputs: {
    case_id: string;
    case_sha256: string;
    seed: number;
    backend_profile_id: string;
    configuration_sha256: string;
    planner_implementation_id: string;
    planner_implementation_version: string;
    planner_settings_sha256: string;
    comparison_baseline_sha256?: string;
  };
  requested_at_utc: string;
  started_at_utc?: string;
  finished_at_utc?: string;
}

export interface CampaignRunStartView extends CampaignRunSummary {
  accepted: true;
}

export interface CampaignWorkspaceView {
  active_case_id?: string;
  locked_inputs?: {
    case_sha256: string;
    seed: number;
    backend_profile_id: string;
    configuration_sha256: string;
    planner_implementation_id: string;
    planner_implementation_version: string;
    planner_settings_sha256: string;
    comparison_baseline_sha256?: string;
  };
  runs: CampaignRunView[];
  reviews: Array<{
    review_id: string;
    run_id: string;
    case_id: string;
    status: string;
    operator_questions: string[];
    operator_observations: string[];
    approval?: { decision: "APPROVE" | "REJECT" | "NEEDS_RERUN" };
    analysis: {
      mission_outcome: string;
      minimum_truth_separation_m?: number;
      primary_cause: { stage: string; confidence: number; reason: string };
    };
  }>;
}

export interface MissionPreview {
  missionId: string;
  sourceSha256: string;
  plan: {
    id: string;
    sha256: string;
    safetyCaseSha256: string;
    status: "APPROVED" | "REQUIRES_CONFIRMATION" | "BLOCKED";
    objective: string;
    plugins: Array<{
      id: string;
      kind: "ROUTE_PLANNER" | "FLEET_POLICY" | "RECOVERY_STRATEGY";
      version: string;
      capabilities: string[];
      manifestSha256: string;
    }>;
    phases: Array<{
      id: string;
      objective: string;
      roleIds: string[];
      maximumDurationS: number;
    }>;
    routes: Array<{
      roleId: string;
      status: "READY" | "BLOCKED";
      durationS: number;
      energyPercent: number;
      lengthM: number;
      waypointCount: number;
      findings: string[];
    }>;
    findings: Array<{
      code: string;
      severity: "INFO" | "WARNING" | "BLOCKER";
      message: string;
      roleId?: string;
      requiresConfirmation: boolean;
    }>;
  };
  vehicles: Array<{
    roleId: string;
    vehicleId: string;
    displayName: string;
    initialRole: "ACTIVE" | "RESERVE";
    home: Vec3;
    start: Vec3;
    batteryPercent?: number;
    minimumBatteryPercent?: number;
    existingVehicle: boolean;
    backendRole?: BackendRole;
    vehicleState?: string;
    previewFidelity: "EXACT_ROLE" | "STATIC_BOUNDS";
    plannedCommands: MissionOption["plannedCommands"];
  }>;
}

export interface MissionRunView {
  id: string;
  missionId: string;
  vehicleId: string;
  phase: string;
  status: "RUNNING" | "SUCCEEDED" | "ABORTED" | "FAILED";
  parameters: Record<string, number | string | boolean>;
  resultReasonCode?: string;
  resultMessage?: string;
}

export interface RunHistoryView {
  runId: string;
  missionId: string;
  vehicleId: string;
  status: "SUCCEEDED" | "ABORTED" | "FAILED" | "INCOMPLETE";
  configurationHash: string;
  startedAtUtc: string;
  telemetryCsv?: RunArtifactView;
}

export interface RunArtifactView {
  kind: "TELEMETRY_CSV";
  filename: string;
  mediaType: "text/csv";
  schemaVersion: "run-telemetry-v1";
  downloadUrl: string;
  available: boolean;
  unavailableReason?: string;
  rowCount: number;
}

export interface RunFileMissionView {
  missionExecutionId: string;
  missionId: string;
  missionName: string;
  status: "SUCCEEDED" | "ABORTED" | "FAILED" | "INCOMPLETE";
  startedAtUtc: string;
  completedAtUtc?: string;
  telemetryRowCount: number;
  filename?: string;
  downloadUrl?: string;
  available: boolean;
  sizeBytes?: number;
  sha256?: string;
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

export interface FleetVehicleLifecycleView {
  id: string;
  home?: Vec3;
  registration: "DECLARED" | "DISCOVERED" | "IDENTITY_BOUND" | "VERIFIED";
  connection: "DISCONNECTED" | "CONNECTING" | "READY" | "FAULT";
  missionRole: "UNASSIGNED" | "ACTIVE" | "RESERVE" | "HANDOVER" | "RETURNING" | "DOCKED" | "CHARGING";
  observation: "NOT_OBSERVED" | "CURRENT" | "STALE" | "COMPLETED_SNAPSHOT";
  preflightApproved: boolean;
  readinessSamples: number;
  readinessReason: string;
  faultReason?: string;
}

export interface FleetTaskView {
  id: string;
  zoneId: string;
  priority: number;
  state: "DECLARED" | "ASSIGNED" | "IN_PROGRESS" | "PAUSED" | "RETRY_PENDING" | "COMPLETED" | "ABORTED";
  ownerVehicleId?: string;
  progressPercent: number;
  leaseGeneration: number;
}

export interface FleetHandoverView {
  id: string;
  taskId: string;
  outgoingVehicleId: string;
  incomingVehicleId?: string;
  phase: string;
  incomingLeaseGeneration?: number;
  takeoverConfirmed: boolean;
  reason: string;
  releaseReason?: string;
}

export interface FleetDockView {
  id: string;
  health: string;
  reservations: Array<{
    vehicleId: string;
    state: string;
    modeledChargingConfirmed: boolean;
    terminalReason?: string;
  }>;
}

export interface FleetSessionView {
  id: string;
  deploymentId: string;
  missionId?: string;
  backend: "FAST_SIM" | "MOCK_ISAAC" | "ISAAC" | "CRAZYFLIE";
  status: "DECLARED" | "PREPARING" | "OBSERVING" | "READY" | "FAULT" | "CLOSED";
  runId?: string;
  runStatus: string;
  resultReasonCode?: string;
  resultMessage?: string;
  vehicles: FleetVehicleLifecycleView[];
  tasks: FleetTaskView[];
  vehicleStates: Record<string, string>;
  handovers: FleetHandoverView[];
  docks: FleetDockView[];
  minimumSeparationM?: number;
  warningViolations: number;
  criticalViolations: number;
  authorityTransitionCount: number;
  warningSeparationM: number;
  criticalSeparationM: number;
  missionDerived: boolean;
  createdAtMonotonicS: number;
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
  fleetSessions: FleetSessionView[];
  safetyPolicy?: {
    minimumTakeoffBatteryPercent: number;
    criticalBatteryPercent: number;
  };
  fault?: { code: string; message: string };
}
