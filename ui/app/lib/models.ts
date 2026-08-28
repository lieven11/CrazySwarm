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
    readings: {
      id: "M1" | "M2" | "M3" | "M4";
      commandPercent: number;
      appliedPwmPercent?: number;
      requestedThrustN?: number;
      thrustN: number;
      availableThrustN?: number;
      currentA: number;
      saturated: boolean;
    }[];
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
  observedSourceClass: "MEASURED_REAL" | "SIMULATED_MODEL" | "CONFIGURED" | "TEST";
  simulatedSourceClass: "MEASURED_REAL" | "SIMULATED_MODEL" | "CONFIGURED" | "TEST";
  observedSourceId?: string;
  simulatedSourceId?: string;
  calibrationId?: string;
  campaignRunId?: string;
  campaignReviewId?: string;
  groundTruthAvailable: boolean;
  latestDeviation?: TwinDeviationView;
}

export interface TwinTimelineSampleView {
  sampleSha256: string;
  side: "OBSERVED" | "PREDICTED";
  channelId: string;
  sourceTimestampS: number;
  receivedTimestampS: number;
  availability: "AVAILABLE" | "MISSING" | "STALE" | "REJECTED";
  quality: "GOOD" | "DEGRADED" | "INVALID" | "UNQUALIFIED";
  calibrationId?: string;
  unit: string;
  frame: string;
  value?: number | boolean | string | Vec3;
}

export interface TwinResidualSampleView {
  residualSha256: string;
  channelId: string;
  sourceTimestampS: number;
  availability: "AVAILABLE" | "MISSING" | "STALE" | "REJECTED";
  quality: "GOOD" | "DEGRADED" | "INVALID" | "UNQUALIFIED";
  unit: string;
  frame: string;
  value?: number | Vec3;
}

export interface TwinTimelineView {
  sessionId: string;
  timelineSha256: string;
  samples: TwinTimelineSampleView[];
  residuals: TwinResidualSampleView[];
  nextAfterSourceS?: number;
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

export interface CampaignSubmissionView {
  submission_id: string;
  submission_sha256: string;
  semantic_fingerprint_sha256: string;
  submission_version: string;
  display_name: string;
  case_id: string;
  case_sha256: string;
  baseline_submission_id?: string;
  baseline_submission_sha256?: string;
  kind: "PLANNER_RETIMED_BASELINE" | "CONSTANT_PATH_SPEED" | "RAMPED_SEGMENT_SPEED" | "BOUNDED_VERTICAL_RATE" | "DURATION_SCALE" | "CORNER_TRANSITION" | "CONSTANT_ROTOR_SPEED";
  owner: "PLANNER" | "TIME_PARAMETERIZER" | "TRAJECTORY_TRACKER" | "LOW_LEVEL_ACTUATOR";
  status: "EXECUTABLE" | "PLANNED_NOT_EXECUTABLE";
  run_eligible: boolean;
  missing_prerequisites: string[];
  comparison_case_ids: string[];
  rationale: string;
  parameters: {
    target_path_speed_m_s?: number | null;
    segment_target_speeds_m_s: number[];
    target_vertical_rate_m_s?: number | null;
    duration_scale?: number | null;
    lookahead_time_s?: number | null;
    entry_exit_ramp_s: number;
    steady_window_tolerance_fraction: number;
  };
  feasibility?: {
    minimum_path_speed_m_s: number;
    maximum_path_speed_m_s: number;
    limiting_segment_index: number;
    maximum_horizontal_tangent_fraction: number;
    maximum_vertical_tangent_fraction: number;
    maximum_steady_window_curvature_m_inverse: number;
    route_segment_lengths_m: number[];
    climb_descent_segment_indices: number[];
    excluded_phases: string[];
    residual_gates: string[];
  };
  prerequisite_submission_ids: string[];
  metric_ids: string[];
  admission: {
    causal_question: string;
    baseline_limitation: string;
    distinguishing_oracle: string;
    reused_evidence: string[];
    new_integration_gate: string;
    learning_value: string;
  };
}

export interface CampaignPlanningSubmissionView {
  planning_submission_id: string;
  planning_submission_sha256: string;
  semantic_fingerprint_sha256: string;
  submission_version: string;
  display_name: string;
  case_id: string;
  case_sha256: string;
  status: "EXECUTABLE" | "PLANNED_NOT_EXECUTABLE";
  rationale: string;
  experiment_id: string;
  experiment_axis: "OBJECTIVE_ORDER" | "MANEUVER_DIMENSION" | "FALLBACK_POLICY" | "SCALAR_PARAMETER" | "CAPABILITY_BINDING";
  axis_value: string;
  layer: "P" | "R";
  fallback_policy?: "SAFE_PREFIX" | "BOUNDED_HOLD" | "CONTROLLED_LAND" | "SAFE_OLD_EPOCH" | "COORDINATED_LAND" | "PROMOTE_SUCCESSOR" | null;
  capability_id?: string | null;
  support_reason: string;
  strategy_authority: string[];
  maneuver_dimensions: string[];
  path_adherence: {
    mode: "EXACT_ROUTE" | "HARD_TUBE" | "REQUIRED_REGIONS" | "SOFT_REFERENCE" | "GOAL_SEQUENCE_ONLY" | "ROUTE_CORRIDOR" | "AUTHORED_CENTERLINE";
    maximum_centerline_deviation_m?: number;
  };
  clearance: {
    nominal_vehicle_radius_m: number;
    nominal_vehicle_half_height_m: number;
    required_pairwise_center_separation_m: number;
    required_solid_clearance_m: number;
    uncertainty_allowance_m: number;
  };
  coordination: {
    synchronized_launch_required: boolean;
    synchronized_route_start_required: boolean;
    minimum_simultaneous_flight_s: number;
    maximum_release_delay_s: number;
  };
  objective: {
    composition: "LEXICOGRAPHIC" | "WEIGHTED_SUM";
    terms: Array<{ metric: string; weight?: number }>;
    deterministic_tie_breaker: "CANDIDATE_SHA256";
  };
  feasibility_oracle_ids: string[];
  admission: {
    causal_question: string;
    baseline_limitation: string;
    principal_variable: string;
    fixed_inputs: string[];
    behavior_difference: string;
    distinguishing_oracle: string;
    reused_evidence: string[];
    new_integration_gate: string;
    backend_semantics: string;
    safety_bounds: string;
    operator_comparison: string;
    learning_value: string;
  };
}

export interface CampaignCaseView {
  case_id: string;
  case_sha256: string;
  execution_semantics_sha256: string;
  cluster: "BASIC_FLIGHT_AND_ROUTE_FOLLOWING" | "DYNAMIC_REPLANNING" | "GEOMETRIC_CONFLICT_RESOLUTION" | "CONSTRAINTS_AND_OPTIMIZATION" | "COORDINATION_AND_ALLOCATION" | "FAILURE_RECOVERY_AND_REPLANNING";
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
  semantics?: {
    curriculum_level: number;
    learning_objective: string;
    difficulty_rationale: string;
    route_intent_by_role: Record<string, Array<{
      region_id: string;
      mode: "FLY_THROUGH" | "CAPTURE" | "CAPTURE_AND_HOLD" | "REVERSAL";
      dwell_s: number;
      capture_tolerance_m: number;
    }>>;
    scenario_events: Array<{
      event_id: string;
      kind: string;
      trigger_time_s: number;
      role_id?: string;
      expected_disposition: string;
    }>;
    behavior_oracles: Array<{
      oracle_id: string;
      kind: string;
      evidence_source: string;
      threshold?: number;
      unit?: string;
    }>;
  };
  drones: Array<{
    role_id: string;
    start_region: { minimum_m: { x: number; y: number; z: number }; maximum_m: { x: number; y: number; z: number } };
    goal_sequence: Array<{ region_id: string; minimum_m: { x: number; y: number; z: number }; maximum_m: { x: number; y: number; z: number } }>;
    landing_region: { minimum_m: { x: number; y: number; z: number }; maximum_m: { x: number; y: number; z: number } };
  }>;
  semantic_audit: {
    classification: "SEMANTICALLY_EXECUTABLE" | "INTENTIONAL_SHARED_BASELINE" | "PLACEHOLDER_QUARANTINED";
    reason: string;
  };
  execution: {
    seed: number;
    repetitions: number;
    backend_profile_id: string;
    configuration_sha256: string;
  };
  submissions?: CampaignSubmissionView[];
  planning_submissions?: CampaignPlanningSubmissionView[];
  submission_registry?: {
    case_id: string;
    expected_case_sha256: string;
    baseline_only: boolean;
    retain_existing_only: boolean;
    baseline_only_rationale?: string | null;
  };
  variation_relationship?: {
    family: string;
    case_id: string;
    variation_name: string;
    relationship: "IMMUTABLE_CASE_VARIATION";
    legacy_named_variations: string[];
  };
  motion_preparation_limits?: {
    accuracy_min_m: number;
    accuracy_max_m: number;
    accuracy_binding: string;
  };
}

export interface CampaignCatalogView {
  major_missions: {
    schema_version: 1;
    curriculum_id: "1d-major-missions-v1" | "1d-major-missions-v2";
    groups: Array<{
      label: "Flight" | "Target" | "Level path" | "3D path" | "Shape";
      variants: Array<{
        label: string;
        case_id: string;
        status: "EXECUTABLE" | "PLANNED_NOT_EXECUTABLE";
        disabled_reason?: string | null;
        future_fixture_source?: string | null;
      }>;
    }>;
  };
  two_drone_missions: {
    schema_version: 1;
    curriculum_id: "2d-conflict-missions-v1";
    groups: Array<{
      label: "Crossing" | "Traffic" | "Merge" | "Coordination" | "Recovery";
      variants: Array<{
        label: string;
        case_id: string;
        status: "EXECUTABLE" | "PLANNED_NOT_EXECUTABLE";
        disabled_reason?: string | null;
      }>;
    }>;
  };
  cases: CampaignCaseView[];
  hierarchy: Record<string, Record<string, Record<string, Record<string, string[]>>>>;
}

export interface CampaignMotionPreparationRequest {
  balance: number;
  speed_m_s?: number;
  accuracy_m?: number;
  smoothness?: number;
}

export interface CampaignCoordinationPreparationRequest {
  launch_gap_s: number;
}

export interface CampaignReviewCursorView {
  vehicleId: string;
  sourceTimestampS: number;
  receivedTimestampS?: number;
  sourceSequence: number;
  sourceClockId?: string;
  sourceClockEpoch?: number;
  correlationId?: string;
  positionM?: Vec3;
  groundTruthPositionM?: Vec3;
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
    submission_id?: string;
    submission_sha256?: string;
    planning_submission_id?: string;
    planning_submission_sha256?: string;
    resolved_planning_package_sha256?: string;
  };
  requested_at_utc: string;
  started_at_utc?: string;
  finished_at_utc?: string;
  mission_execution_id?: string;
  artifact_set_sha256?: string;
  analysis_sha256?: string;
  superseded_at_utc?: string;
  superseded_by_revision?: string;
  superseded_by_actor?: string;
  superseded_reason?: string;
}

export interface CampaignRunStartView extends CampaignRunSummary {
  accepted: true;
}

export interface CampaignSnapshotView {
  snapshot_id: string;
  run_id: string;
  captured_at_utc: string;
  content_type: "image/webp" | "image/jpeg";
  filename: string;
  size_bytes: number;
  sha256: string;
  width_px: number;
  height_px: number;
  case_id?: string;
  case_sha256?: string;
  plan_sha256?: string;
  trajectory_set_sha256?: string;
  review_frame?: {
    source_timestamp_s: number;
    source_clock_id: string;
    source_clock_epoch: number;
    source_sequence: number;
    correlation_id: string;
    estimate_source_timestamp_s: number;
    truth_source_timestamp_s?: number;
    desired_source_timestamp_s?: number;
    playback_buffer_age_s: number;
    interpolation_state: "EXACT" | "INTERPOLATED" | "FROZEN" | "UNAVAILABLE";
    captured_at_wall_utc?: string;
    source_rows?: Array<{
      correlation_id: string;
      source_sequence: number;
      source_timestamp_s: number;
      source_clock_id: string;
      source_clock_epoch: number;
    }>;
    same_time_truth_estimate_error_m?: number;
    buffer_induced_estimate_displacement_m?: number;
  };
  operator_comment?: string;
  commented_at_utc?: string;
  neutral_assessment?: string;
  assessment_disposition?: "VALID" | "PARTLY_VALID" | "DISPLAY_EFFECT" | "NOT_SUPPORTED" | "NEEDS_MORE_EVIDENCE";
  assessment_confidence?: number;
  assessment_evidence_refs?: string[];
  assessed_at_utc?: string;
  image_available: boolean;
  purged_at_utc?: string;
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
    submission_id?: string;
    submission_sha256?: string;
    planning_submission_id?: string;
    planning_submission_sha256?: string;
    resolved_planning_package_sha256?: string;
  };
  runs: CampaignRunView[];
  snapshots?: CampaignSnapshotView[];
  reviews: Array<{
    review_id: string;
    run_id: string;
    case_id: string;
    status: string;
    operator_questions: string[];
    operator_observations: string[];
    twin_session_ids?: string[];
    baseline_comparison?: Record<string, string | number | boolean | null>;
    cross_case_profile_comparison?: Record<string, string | number | boolean | null>;
    approval?: { decision: "APPROVE" | "REJECT" | "NEEDS_RERUN" };
    analysis: {
      mission_execution_id: string;
      mission_outcome: string;
      telemetry_row_count: number;
      minimum_truth_separation_m?: number;
      planning_submission_id?: string;
      planning_submission_sha256?: string;
      resolved_planning_package_sha256?: string;
      primary_cause: { stage: string; confidence: number; reason: string };
      landing?: Array<{
        vehicle_id: string;
        accepted_landing_center_m: { x: number; y: number; z: number };
        planned_arrival_m?: { x: number; y: number; z: number };
        planned_descent_m?: { x: number; y: number; z: number };
        estimated_touchdown_m?: { x: number; y: number; z: number };
        truth_touchdown_m?: { x: number; y: number; z: number };
        displayed_goal_marker_m?: { x: number; y: number; z: number };
        landing_goal_id?: string;
        terminal_contact?: string;
        pre_contact_vertical_speed_m_s?: number;
        motors_cut_after_contact?: boolean;
        coordinate_conversion_chain: string[];
      }>;
      vehicles?: Array<{
        vehicle_id: string;
        kinematics_gate_reconciliation?: {
          raw_horizontal_speed_peak_m_s?: number;
          raw_vertical_speed_peak_m_s?: number;
          processed_horizontal_speed_peak_m_s?: number;
          processed_vertical_speed_peak_m_s?: number;
          maximum_horizontal_speed_m_s?: number;
          maximum_vertical_speed_m_s?: number;
          raw_gate_passed?: boolean;
          processed_gate_passed?: boolean;
          gate_disagreement: boolean;
        };
      }>;
      motion_quality?: Array<{
        vehicle_id: string;
        contract_sha256: string;
        csv_sha256: string;
        sample_count: number;
        vector: Record<string, number | boolean | null>;
        failed_guards: string[];
        missing_guards: string[];
        analysis_sha256: string;
      }>;
      physical_truth?: Array<{
        vehicle_id: string;
        paired_sample_count: number;
        maneuver_sample_count: number;
        sign_agreement_fraction?: number;
        normalized_error_p95?: number;
        maximum_source_pairing_error_s?: number;
        all_equal_moving_sample_count: number;
        saturated_maneuver_sample_count: number;
        failures: string[];
        passed: boolean;
        analysis_sha256: string;
      }>;
      replan_timeline?: Array<{
        stage?: string;
        event_id?: string;
        observation_id?: string;
        source_timestamp_s?: number;
        received_timestamp_s?: number;
        disposition?: string;
        execution_disposition?: string;
        fallback_command?: string;
        observation_sha256?: string;
        decision_sha256?: string;
        reason?: string;
        change_kind?: string;
        solid_id?: string;
        region?: { minimum_m: Vec3; maximum_m: Vec3 } | null;
      }>;
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
  missionExecutionId: string;
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

export interface PhysicalTwinStatusView {
  state: "UNCONFIGURED" | "DISCONNECTED" | "CONNECTING" | "PENDING_CONFIRMATION" | "PAIRED" | "SUSPENDED" | "ERROR" | "CONFIGURATION_INVALID";
  configured: boolean;
  autoConnectEnabled?: boolean;
  vehicleLabel?: string;
  redactedUri?: string;
  uriSha256?: string;
  connectionNonce?: string;
  observedIdentitySha256?: string;
  commandReadiness: "NOT_ASSESSED" | "UNQUALIFIED";
  commandReadinessIssues: string[];
  sessionId?: string;
  observedSourceClass?: "MEASURED_REAL" | "TEST";
  predictedSourceClass?: "SIMULATED_MODEL" | "TEST";
  provenance?: "MEASURED_REAL" | "TEST";
  testOnly: boolean;
  sampleCount: number;
  pairedCycleCount: number;
  observed?: PhysicalTwinSourceStatusView;
  predicted?: PhysicalTwinSourceStatusView;
  lastErrorCode?: string;
  lastErrorMessage?: string;
  lastFailureKind?: RadioFailureKindView;
  lastFailureAtUtc?: string;
  reconnectAttempt?: number;
  reconnectMode?: "IDLE" | "FAST" | "LOW_DUTY";
  nextReconnectAtUtc?: string;
  suspensionReason?: string;
  suspensionOwner?: string;
  suspendedAtUtc?: string;
  telemetryOwner?: "OBSERVER" | "PHYSICAL_OPERATION";
  operationSampleCount?: number;
}

export interface PhysicalTwinLiveFrameView {
  state: PhysicalTwinStatusView["state"];
  vehicleLabel?: string;
  liveSequence: number;
  pairedCycleCount: number;
  channelRecordCount: number;
  observed?: PhysicalTwinSourceStatusView;
  telemetryOwner?: "OBSERVER" | "PHYSICAL_OPERATION";
  operationSampleCount?: number;
}

export interface PhysicalTwinSourceStatusView {
  role: "OBSERVED" | "PREDICTED";
  vehicleId: string;
  sourceClass: "MEASURED_REAL" | "SIMULATED_MODEL" | "TEST";
  freshness: "CURRENT" | "STALE" | "MISSING";
  frame?: "world" | "home" | "body" | "sensor";
  sourceClockId?: string;
  sourceEpoch?: number;
  rawSourceTimestampS?: number;
  sourceTimestampS?: number;
  pairSequence?: number;
  alignmentEpoch?: number;
  positionAvailability: "AVAILABLE" | "MISSING" | "INCOMPATIBLE";
  position?: Vec3;
  batteryAvailability: "AVAILABLE" | "MISSING";
  batteryVoltage?: number;
  armed?: boolean;
  flying?: boolean;
  faults?: string[];
  attitude?: { rollRad: number; pitchRad: number; yawRad: number };
  imu?: { acceleration: Vec3; angularVelocity: Vec3 };
  flow?: {
    velocity?: Vec3;
    groundDistanceM?: number;
    qualityPercent: number;
    status: string;
  };
  ranges?: {
    frontM?: number;
    backM?: number;
    leftM?: number;
    rightM?: number;
    upM?: number;
    downM?: number;
    statuses: Record<string, string>;
  };
  estimator?: {
    converged?: boolean;
    positionVariance?: Vec3;
    qualityMetricId?: string;
  };
  motorPwmPercent?: [number, number, number, number];
  transport?: {
    kind: "physical_radio" | "modeled_transport" | "replay";
    deliveryQualityPercent?: number;
    latencyMs?: number;
    packetLossPercent?: number;
    radio?: RadioTransportDiagnosticsView;
  };
  familyAvailability: Record<string, "AVAILABLE" | "MISSING" | "STALE" | "REJECTED" | "INCOMPATIBLE">;
}

export type RadioFailureKindView = "NONE" | "USB_UNAVAILABLE" | "TARGET_OFFLINE" | "RF_ACK_LOSS" | "OUTBOUND_QUEUE_SATURATED" | "TELEMETRY_STALE" | "PROTOCOL_SETUP_FAILED" | "UNKNOWN";

export interface RadioTransportDiagnosticsView {
  connectionEpoch: number;
  state: "HEALTHY" | "DEGRADED" | "STALE" | "DISCONNECTED";
  failureKind: RadioFailureKindView;
  ackedPacketCount: number;
  lostPacketCount: number;
  packetLossPercent?: number;
  consecutiveLostPacketCount: number;
  maximumConsecutiveLostPacketCount: number;
  retryQualityPercent?: number;
  uplinkRssiRaw?: number;
  uplinkRateHz?: number;
  downlinkRateHz?: number;
  uplinkCongestionPercent?: number;
  downlinkCongestionPercent?: number;
  outboundQueueDepth: number;
  outboundQueueCapacity: number;
  queueSaturationCount: number;
  usbErrorCount: number;
  lastAckAgeMs?: number;
  lastEventAtUtc?: string;
  lastEventMessage?: string;
}

export interface TwinBasicFlightStepView {
  stepId: string;
  title: string;
  behavior: string;
  containment: string;
}

export interface TwinBasicFlightMotionView {
  motionId: string;
  clusterId: string;
  majorMission: string;
  variant: string;
  placementMarker?: "A" | "B" | "C" | "D" | "E";
  motion: string;
  summary: string;
  physicalScope: "PROPS_OFF_BENCH" | "FIXTURE_OBSERVATION" | "CONTAINED_FLIGHT";
  physicalExecution: "NOT_ENABLED" | "OPERATOR_GATED";
  catalogVisibility: boolean;
  implementationState: "READY" | "SETUP_REQUIRED" | "RAW";
  blockReason?: string;
  steps: TwinBasicFlightStepView[];
  learningSignals: string[];
}

export interface TwinMissionClusterView {
  clusterId: string;
  clusterName: string;
  purpose: string;
  state: "READY" | "SETUP_REQUIRED";
  detail?: string;
}

export interface ControllerTuningFixtureStatusView {
  fixtureId: string;
  fixtureVersion: string;
  artifactPath: string;
  state: "AWAITING_MEASUREMENTS" | "READY" | "INVALID";
  implementedFlightsAvailable: boolean;
  missingFields: string[];
  detail: string;
}

export interface TwinBasicFlightCatalogView {
  clusterId: string;
  clusterName: string;
  purpose: string;
  qualificationClaim: "NONE";
  clusters: TwinMissionClusterView[];
  controllerTuningFixture?: ControllerTuningFixtureStatusView;
  motions: TwinBasicFlightMotionView[];
}

export interface TwinBasicFlightRunView {
  runId: string;
  motionId: string;
  status: "COMPLETED" | "FAILED";
  executionBackend: "FAST_SIM" | "REAL_CRAZYFLIE";
  evidenceClass: "SIMULATED_MODEL" | "MEASURED_REAL";
  learningDisposition: "SIMULATOR_INPUT_CANDIDATE";
  qualificationClaim: "NONE";
  steps: { stepId: string; status: "COMPLETED" | "MODELED_ONLY"; detail: string }[];
  learningSample: {
    batteryStartPercent: number;
    batteryMinimumPercent: number;
    batteryEndPercent: number;
    batteryDeltaPercent: number;
    minimumVoltageV?: number;
    maximumCurrentA?: number;
    peakMotorCommandPercent?: number;
    hoverRmsDriftM?: number;
    maximumAltitudeM: number;
    landingContactObserved: boolean;
    finalState: string;
  };
  artifactPath: string;
  telemetryRowCount?: number;
  telemetryCsvSha256?: string;
  controllerTuningPreparation?: ControllerTuningRunPreparationView;
  controllerTuningRangeSummary?: {
    fixtureId: string;
    fixtureVersion: string;
    modelStatus: "EVALUATED" | "RAW_ONLY";
    predictionSource: "CONFIGURED_PLACEMENT" | "ESTIMATOR_POSE" | "UNAVAILABLE";
    validRangeValueCount: number;
    posePredictionResidualRmsM?: number;
    opposingRangeSumResidualRmsM?: number;
    fittedPoseSampleCount: number;
    estimatorToRangeXyRmsM?: number;
    continuityConstrained: true;
    qualificationClaim: "NONE";
    detail: string;
  };
}

export interface ControllerTuningRunPreparationView {
  fixtureId: string;
  fixtureVersion: string;
  fixtureSha256: string;
  stationId: "A" | "B" | "C" | "D" | "E";
  headingDeg: number;
  targetHeightM?: number;
}

export interface ControllerTuningPreparationInput {
  stationId: "A" | "B" | "C" | "D" | "E";
  headingDeg: number;
  targetHeightM?: number;
}

export type ObstacleAvoidanceMode = "MONITOR_ONLY" | "ENFORCED";

export interface ObstacleAvoidanceStatusView {
  mode: ObstacleAvoidanceMode;
  decision?: "CLEAR" | "LIMIT" | "BLOCK_BEFORE_DISPATCH" | "RECOVER_ABORT_LAND" | "RECORD_ONLY";
  evaluationCount: number;
  minimumMarginM?: number;
  bindingRay?: "front" | "back" | "left" | "right";
  interventionReason?: string;
}

export type PhysicalBasicFlightMotionId =
  | "commissioning-baseline"
  | "arm-disarm"
  | "hover-12s"
  | "forward-10cm-return"
  | "left-10cm-return"
  | "right-10cm-return"
  | "forward-20cm-return"
  | "land-forward-10cm"
  | "land-forward-20cm"
  | "land-diagonal-20cm"
  | "l-shape-stops"
  | "square-stops"
  | "triangle-stops"
  | "l-shape-stops-40cm"
  | "square-stops-40cm"
  | "triangle-stops-40cm"
  | "straight-out-back-continuous"
  | "tuning-a-floor-start"
  | "tuning-a-raised-center"
  | "tuning-a-station-a"
  | "tuning-a-station-b"
  | "tuning-a-station-c"
  | "tuning-a-station-d"
  | "tuning-a-station-e"
  | "tuning-a-yaw-minus-45"
  | "tuning-a-yaw-minus-30"
  | "tuning-a-yaw-minus-15"
  | "tuning-a-yaw-zero"
  | "tuning-a-yaw-plus-15"
  | "tuning-a-yaw-plus-30"
  | "tuning-a-yaw-plus-45"
  | "tuning-a-height-low"
  | "tuning-a-height-nominal"
  | "tuning-a-height-high"
  | "tuning-a-holdout-one"
  | "tuning-a-holdout-two"
  | "tuning-b-center-hover"
  | "tuning-c-x-plus-05"
  | "tuning-c-x-minus-05"
  | "tuning-c-y-plus-05"
  | "tuning-c-y-minus-05"
  | "tuning-c-x-plus-15"
  | "tuning-c-x-minus-15"
  | "tuning-c-y-plus-15"
  | "tuning-c-y-minus-15"
  | "tuning-c-x-plus-30"
  | "tuning-c-x-minus-30"
  | "tuning-c-y-plus-30"
  | "tuning-c-y-minus-30"
  | "tuning-d-yaw-zero"
  | "tuning-d-yaw-plus-15"
  | "tuning-d-yaw-minus-15"
  | "tuning-d-yaw-plus-30"
  | "tuning-d-yaw-minus-30"
  | "tuning-d-slow-sweep"
  | "tuning-d-off-center"
  | "tuning-e-slow-x"
  | "tuning-e-stress-x"
  | "tuning-e-hold-x-positive"
  | "tuning-e-hold-x-negative"
  | "tuning-e-hold-y-positive"
  | "tuning-e-hold-y-negative"
  | "acro-single-roll";

export interface PhysicalFlightOperationStatusView {
  state: "IDLE" | "STARTING" | "RUNNING" | "HOVERING_READY" | "FLIPPING" | "ABORTING" | "STOP_UNCONFIRMED" | "COMPLETED" | "ABORTED" | "FAILED";
  stopRequired: boolean;
  operationId?: string;
  motionId?: PhysicalBasicFlightMotionId;
  startedAtUtc?: string;
  detail?: string;
  result?: TwinBasicFlightRunView;
  controllerTuningPreparation?: ControllerTuningRunPreparationView;
  availableAction?: "FLIP";
  avoidance: ObstacleAvoidanceStatusView;
}

export type MotorBenchSelection = "all" | "m1" | "m2" | "m3" | "m4";

export interface MotorBenchSessionView {
  sessionId: string;
  status: "ACTIVE" | "STOPPED" | "FAILED";
  motorSelection: MotorBenchSelection;
  outputPercent: number;
  measuredPwmPercent?: [number, number, number, number];
  maximumOutputPercent: 70;
  watchdogTimeoutMs: 750;
  firmwareWatchdogArmed: boolean;
  rebootRequired: boolean;
  telemetryRowCount: number;
  telemetryArtifactPath?: string;
  motorCsvPath?: string;
  motorCsvSha256?: string;
  error?: string;
}

export interface MotorActuationStatusView {
  state: "IDLE" | "ACTIVE" | "POSSIBLY_ACTIVE" | "STOPPING" | "STOP_FAILED";
  stopRequired: boolean;
  sessionId?: string;
  motorSelection?: MotorBenchSelection;
  commandedOutputPercent?: number;
  measuredPwmPercent?: [number, number, number, number];
  measuredOutputActive?: boolean;
  firmwareWatchdogArmed?: boolean;
  rebootRequired?: boolean;
  detail?: string;
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
