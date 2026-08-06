import { createEmptyDashboard } from "./empty";
import type {
  DashboardModel,
  DeckView,
  EvidenceClass,
  FidelityManifest,
  Freshness,
  MissionOption,
  MissionRunView,
  ParameterView,
  PreflightReportView,
  RangeRay,
  ReplayView,
  RoomView,
  RunHistoryView,
  TelemetryView,
  TransportView,
  Vec3,
  VehicleView,
} from "./models";

export interface ApiCredentials {
  endpoint: string;
  token?: string;
  clientId: string;
}

export interface MissionStartResult {
  mission_run_id: string;
  status: string;
}

const DIRECTIONS: RangeRay["direction"][] = ["front", "back", "left", "right", "up", "down"];

export class ControlApi {
  constructor(private readonly credentials: ApiCredentials) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.credentials.endpoint}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Client-ID": this.credentials.clientId,
        ...(this.credentials.token ? { "X-Local-Token": this.credentials.token } : {}),
        ...(init?.method && init.method !== "GET"
          ? { "Idempotency-Key": crypto.randomUUID() }
          : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null) as Record<string, unknown> | null;
      const error = asRecord(body?.error);
      throw new Error(stringValue(error?.message, `Control API returned ${response.status}`));
    }
    return await response.json() as T;
  }

  async loadDashboard(): Promise<DashboardModel> {
    const [state, missions, world, fidelity, twins] = await Promise.all([
      this.request<Record<string, unknown>>("/api/v1/state"),
      this.request<unknown[]>("/api/v1/mission-files"),
      this.request<Record<string, unknown>>("/api/v1/simulation/world"),
      this.request<Record<string, unknown>>("/api/v1/simulation/fidelity"),
      this.request<unknown[]>("/api/v1/twins"),
    ]);
    return adaptDashboard(state, missions, world, fidelity, this.credentials.clientId, twins);
  }

  async connectVehicle(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/connect`, {});
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/control/claim`, {});
  }

  async selectVehicle(vehicleId: string): Promise<void> {
    await this.post("/api/v1/vehicles/select", { vehicle_id: vehicleId });
  }

  async claimControl(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/control/claim`, {});
  }

  async renewControl(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/control/renew`, {});
  }

  async releaseControl(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/control/release`, {});
  }

  async disconnectVehicle(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/disconnect`, {});
  }

  async resetSimulation(vehicleId: string): Promise<number | undefined> {
    const response = await this.post<Record<string, unknown>>(
      `/api/v1/simulation/vehicles/${encodeURIComponent(vehicleId)}/clock`,
      { action: "reset" },
    );
    return finiteNumber(response.battery_percent);
  }

  async preflight(vehicleId: string, missionId?: string): Promise<PreflightReportView> {
    const value = await this.post<Record<string, unknown>>(
      `/api/v1/vehicles/${encodeURIComponent(vehicleId)}/preflight`,
      { mission_id: missionId ?? null },
    );
    return {
      reportId: stringValue(value.report_id, ""),
      approved: value.approved === true,
      expiresAtMonotonicS: finiteNumber(value.expires_at_monotonic_s) ?? 0,
      checks: (Array.isArray(value.checks) ? value.checks : []).flatMap((item) => {
        const check = asRecord(item);
        return check && typeof check.code === "string"
          ? [{ code: check.code, passed: check.passed === true, message: stringValue(check.message, "") }]
          : [];
      }),
    };
  }

  async arm(vehicleId: string, reportId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/arm`, { report_id: reportId });
  }

  async disarm(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/disarm`, {});
  }

  async takeoff(vehicleId: string, heightM = 0.3, durationS = 2): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/takeoff`, { height_m: heightM, duration_s: durationS });
  }

  async hold(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/stop-and-hold`, {});
  }

  async moveRelative(vehicleId: string, movement: { x_m?: number; y_m?: number; z_m?: number; yaw_rad?: number; duration_s?: number }): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/move-relative`, movement);
  }

  async land(vehicleId: string, durationS = 2): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/land`, { duration_s: durationS });
  }

  async abort(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/abort`, { reason: "operator requested abort" });
  }

  async emergencyStop(vehicleId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/emergency-stop`, { reason: "operator confirmed emergency motor cutoff" });
  }

  async parameters(vehicleId: string): Promise<ParameterView[]> {
    const response = await this.request<Record<string, unknown>>(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/parameters`);
    return (Array.isArray(response.values) ? response.values : []).flatMap(mapParameter);
  }

  async writeParameter(vehicleId: string, name: string, value: number | string | boolean): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/parameters/write`, { name, value });
  }

  async snapshotParameters(vehicleId: string): Promise<string> {
    const response = await this.post<Record<string, unknown>>(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/parameters/snapshot`, {});
    return stringValue(response.snapshot_id, "");
  }

  async uploadMission(name: string, filename: string, source: string): Promise<MissionOption> {
    const response = await this.post<Record<string, unknown>>("/api/v1/mission-files", {
      name,
      filename,
      source,
    });
    const mission = mapMission(response);
    if (!mission) throw new Error("Uploaded mission response is invalid");
    return mission;
  }

  async startMissionFile(
    missionId: string,
    vehicleId: string,
    executionMode: "SIMULATION" | "TWIN",
  ): Promise<MissionStartResult> {
    return this.request(`/api/v1/mission-files/${encodeURIComponent(missionId)}/start`, {
      method: "POST",
      body: JSON.stringify({ vehicle_id: vehicleId, execution_mode: executionMode }),
    });
  }

  async archiveMission(missionId: string): Promise<void> {
    await this.request(`/api/v1/mission-files/${encodeURIComponent(missionId)}`, {
      method: "DELETE",
    });
  }

  async parameterDiffCount(vehicleId: string, snapshotId: string): Promise<number> {
    const response = await this.request<Record<string, unknown>>(
      `/api/v1/vehicles/${encodeURIComponent(vehicleId)}/parameters/snapshots/${encodeURIComponent(snapshotId)}/diff`,
    );
    return Object.keys(asRecord(response.changes) ?? {}).length;
  }

  async restoreParameters(vehicleId: string, snapshotId: string): Promise<void> {
    await this.post(`/api/v1/vehicles/${encodeURIComponent(vehicleId)}/parameters/restore`, { snapshot_id: snapshotId });
  }

  private async post<T = Record<string, unknown>>(path: string, body: Record<string, unknown>): Promise<T> {
    return this.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  }

  async cancelMission(runId: string): Promise<Record<string, unknown>> {
    return this.request(`/api/v1/mission-runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
      body: "{}",
    });
  }

  async missionRun(runId: string): Promise<Record<string, unknown>> {
    return this.request(`/api/v1/mission-runs/${encodeURIComponent(runId)}`);
  }

  async runHistory(): Promise<RunHistoryView[]> {
    const response = await this.request<unknown[]>("/api/v1/runs?limit=100");
    return response.flatMap((item) => {
      const value = asRecord(item);
      if (!value || typeof value.run_id !== "string" || typeof value.mission_id !== "string" || typeof value.vehicle_id !== "string") return [];
      const status = value.status === "SUCCEEDED" || value.status === "ABORTED" || value.status === "FAILED"
        ? value.status
        : "INCOMPLETE";
      return [{
        runId: value.run_id,
        missionId: value.mission_id,
        vehicleId: value.vehicle_id,
        status,
        configurationHash: stringValue(value.configuration_hash, ""),
        startedAtUtc: stringValue(value.started_at_utc, ""),
      }];
    });
  }

  async openReplay(runId: string): Promise<ReplayView> {
    const response = await this.post<Record<string, unknown>>(
      `/api/v1/replay/${encodeURIComponent(runId)}/open`,
      {},
    );
    return mapReplay(runId, response);
  }

  async stepReplay(runId: string): Promise<ReplayView> {
    const response = await this.post<Record<string, unknown>>(
      `/api/v1/replay/${encodeURIComponent(runId)}/control`,
      { action: "step" },
    );
    return mapReplay(runId, response);
  }
}

function mapReplay(runId: string, value: Record<string, unknown>): ReplayView {
  const event = asRecord(value.event);
  return {
    runId,
    index: finiteNumber(value.index) ?? 0,
    eventCount: finiteNumber(value.event_count) ?? 0,
    nowS: finiteNumber(value.now_s) ?? 0,
    paused: value.paused === true,
    speed: finiteNumber(value.speed) ?? 1,
    eventKind: typeof event?.kind === "string" ? event.kind : undefined,
  };
}

export function adaptDashboard(
  state: Record<string, unknown>,
  missionsValue: unknown[],
  worldValue: Record<string, unknown>,
  fidelityValue: Record<string, unknown>,
  clientId: string,
  twinsValue: unknown[] = [],
): DashboardModel {
  const model = createEmptyDashboard();
  model.apiConnected = true;
  model.serviceLabel = "Local control service";
  if (isMode(state.mode)) model.mode = state.mode;
  if (typeof state.selected_vehicle_id === "string") model.selectedVehicleId = state.selected_vehicle_id;
  model.missions = missionsValue.flatMap((value) => {
    const mission = mapMission(value);
    return mission ? [mission] : [];
  });
  model.vehicles = (Array.isArray(state.vehicles) ? state.vehicles : []).flatMap((value) => {
    const vehicle = mapVehicle(value, model.selectedVehicleId, clientId);
    return vehicle ? [vehicle] : [];
  });
  model.room = mapRoom(worldValue, model.selectedVehicleId, state.configured_flight_volume);
  model.fidelity = mapFidelity(fidelityValue);
  model.latestRun = mapLatestRun(state.mission_runs);
  model.twins = twinsValue.flatMap((value) => {
    const twin = asRecord(value);
    if (!twin || typeof twin.session_id !== "string" || typeof twin.observed_vehicle_id !== "string" || typeof twin.simulated_vehicle_id !== "string") return [];
    const deviation = asRecord(twin.latest_deviation);
    const sourceTimestampS = finiteNumber(deviation?.source_timestamp_s);
    const observedLatencyMs = finiteNumber(deviation?.observed_latency_ms);
    const simulatedLatencyMs = finiteNumber(deviation?.simulated_latency_ms);
    const alignmentDeltaMs = finiteNumber(deviation?.alignment_delta_ms);
    const latestDeviation = deviation
      && sourceTimestampS !== undefined
      && observedLatencyMs !== undefined
      && simulatedLatencyMs !== undefined
      && alignmentDeltaMs !== undefined
      ? {
          sourceTimestampS,
          observedLatencyMs,
          simulatedLatencyMs,
          alignmentDeltaMs,
          positionM: finiteNumber(deviation.position_m),
          altitudeM: finiteNumber(deviation.altitude_m),
          velocityMS: finiteNumber(deviation.velocity_m_s),
          yawRad: finiteNumber(deviation.yaw_rad),
          batteryPercent: finiteNumber(deviation.battery_percent),
          frame: stringValue(deviation.frame, "unknown"),
          validity: deviation.validity === "VALID"
            ? "VALID" as const
            : deviation.validity === "INCOMPATIBLE"
              ? "INCOMPATIBLE" as const
              : "UNAVAILABLE" as const,
        }
      : undefined;
    return [{
      id: twin.session_id,
      status: stringValue(twin.status, "UNKNOWN"),
      observedVehicleId: twin.observed_vehicle_id,
      simulatedVehicleId: twin.simulated_vehicle_id,
      groundTruthAvailable: twin.ground_truth_available === true,
      latestDeviation,
    }];
  });
  return model;
}

function mapMission(value: unknown): MissionOption | null {
  const source = asRecord(value);
  if (!source || typeof source.mission_id !== "string" || typeof source.name !== "string") return null;
  if (source.source_kind !== "UPLOADED_PYTHON" || typeof source.source_filename !== "string" || typeof source.source_sha256 !== "string") return null;
  return {
    id: source.mission_id,
    version: stringValue(source.mission_version, "unknown"),
    name: source.name,
    description: stringValue(source.description, ""),
    sourceKind: "UPLOADED_PYTHON",
    sourceFilename: source.source_filename,
    sourceSha256: source.source_sha256,
    plannedCommands: (Array.isArray(source.planned_commands) ? source.planned_commands : []).flatMap((item) => {
      const command = asRecord(item);
      const action = command?.action;
      const argumentsValue = asRecord(command?.arguments);
      if (!argumentsValue || (action !== "takeoff" && action !== "hover" && action !== "move_relative" && action !== "land")) return [];
      return [{ action, arguments: Object.fromEntries(Object.entries(argumentsValue).filter((entry): entry is [string, number | string] => typeof entry[1] === "number" || typeof entry[1] === "string")) }];
    }),
  };
}

function mapVehicle(
  value: unknown,
  selectedVehicleId: string | undefined,
  clientId: string,
): VehicleView | null {
  const source = asRecord(value);
  const identity = asRecord(source?.identity);
  if (!source || !identity || typeof identity.vehicle_id !== "string") return null;
  const observation = asRecord(source.observation);
  const telemetryEnvelope = asRecord(source.telemetry);
  const telemetry = mapTelemetry(telemetryEnvelope, observation);
  const capabilities = asRecord(source.capabilities);
  const lease = asRecord(source.control_lease);
  const controlState = asRecord(source.control_state);
  const adapter = identity.adapter === "cflib" || identity.adapter === "replay" ? identity.adapter : "sim";
  const status = stringValue(observation?.status, "UNAVAILABLE");
  return {
    id: identity.vehicle_id,
    name: stringValue(identity.display_name, identity.vehicle_id),
    adapter,
    selected: source.selected === true || identity.vehicle_id === selectedVehicleId,
    state: stringValue(source.state, "UNKNOWN"),
    commandAuthority: typeof lease?.owner_id === "string" && lease.owner_id === clientId,
    observationStatus: isObservationStatus(status) ? status : "UNAVAILABLE",
    observationClass: evidenceClass(observation?.source_class),
    observationRunId: typeof observation?.run_id === "string" ? observation.run_id : undefined,
    telemetry: telemetry ?? undefined,
    decks: mapDecks(capabilities?.decks),
    capabilities: stringArray(capabilities?.features),
    radioUri: typeof identity.radio_uri === "string" ? identity.radio_uri : undefined,
    firmwareVersion: typeof identity.firmware_version === "string" ? identity.firmware_version : undefined,
    armed: typeof controlState?.armed === "boolean" ? controlState.armed : undefined,
    flying: typeof controlState?.flying === "boolean" ? controlState.flying : undefined,
  };
}

function mapParameter(value: unknown): ParameterView[] {
  const source = asRecord(value);
  if (!source || typeof source.name !== "string" || !["number", "string", "boolean"].includes(typeof source.value)) return [];
  const current = source.value as number | string | boolean;
  return [{
    name: source.name,
    value: current,
    default: ["number", "string", "boolean"].includes(typeof source.default) ? source.default as number | string | boolean : undefined,
    valueType: stringValue(source.value_type, typeof current),
    access: source.access === "READ_WRITE" ? "READ_WRITE" : "READ_ONLY",
    persistence: source.persistence === "STORED" ? "STORED" : "SESSION",
    minimum: finiteNumber(source.minimum),
    maximum: finiteNumber(source.maximum),
    unit: typeof source.unit === "string" ? source.unit : undefined,
    sourceClass: source.source_class === "MEASURED_REAL" ? "MEASURED_REAL" : "CONFIGURED",
  }];
}

function mapTelemetry(
  envelope: Record<string, unknown> | null,
  observation: Record<string, unknown> | null,
): TelemetryView | null {
  const source = asRecord(envelope?.telemetry);
  if (!source) return null;
  const freshness = telemetryFreshness(envelope);
  const attitude = asRecord(source.attitude);
  const imu = asRecord(source.imu);
  const flow = asRecord(source.flow);
  const acceleration = vec3(imu?.acceleration_body_m_s2);
  const angularVelocity = vec3(imu?.angular_velocity_body_rad_s);
  const flowVelocity = vec3(flow?.velocity_body_m_s);
  const transport = mapTransport(source.transport);
  const rollRad = finiteNumber(attitude?.roll_rad);
  const pitchRad = finiteNumber(attitude?.pitch_rad);
  const yawRad = finiteNumber(attitude?.yaw_rad);
  const motors = asRecord(source.motors);
  const motorReadings: NonNullable<TelemetryView["motors"]>["readings"] = (Array.isArray(motors?.readings) ? motors.readings : []).flatMap((value) => {
    const reading = asRecord(value);
    const id = reading?.motor_id;
    const commandPercent = finiteNumber(reading?.command_percent);
    const thrustN = finiteNumber(reading?.thrust_n);
    const currentA = finiteNumber(reading?.current_a);
    const motorId = id === "M1" || id === "M2" || id === "M3" || id === "M4" ? id : undefined;
    return motorId
      && commandPercent !== undefined && thrustN !== undefined && currentA !== undefined
      ? [{ id: motorId, commandPercent, thrustN, currentA }]
      : [];
  });
  const localizationSource = stringValue(source.localization_source, "");
  return {
    armed: source.armed === true,
    flying: source.flying === true,
    estimate: vec3(source.position_m) ?? undefined,
    simulatedTruth: vec3(source.ground_truth_position_m) ?? undefined,
    velocity: vec3(source.velocity_m_s) ?? undefined,
    attitude: rollRad !== undefined && pitchRad !== undefined && yawRad !== undefined
      ? { rollRad, pitchRad, yawRad }
      : undefined,
    yawRad,
    batteryPercent: finiteNumber(source.battery_percent),
    batteryVoltage: finiteNumber(source.battery_voltage_v),
    batteryCurrent: finiteNumber(source.battery_current_a),
    localizationPercent: finiteNumber(source.localization_quality_percent),
    localizationLabel: localizationSource || undefined,
    imu: imu && acceleration && angularVelocity ? {
      acceleration,
      angularVelocity,
      provenance: fieldProvenance(observation, "imu", "m/s² · rad/s", "body", freshness, envelope),
    } : undefined,
    flow: flow && flowVelocity ? {
      velocity: flowVelocity,
      groundDistanceM: finiteNumber(flow.ground_distance_m),
      qualityPercent: finiteNumber(flow.quality_percent),
      provenance: fieldProvenance(observation, "flow", "m · m/s", "body", freshness, envelope),
    } : undefined,
    ranges: mapRanges(source.ranges, freshness),
    motors: motors && motorReadings.length === 4 ? {
      modelId: stringValue(motors.model_id, "unknown"),
      modelVersion: stringValue(motors.model_version, "unknown"),
      readings: motorReadings,
    } : undefined,
    transport: transport ?? undefined,
    radio: source.link_quality_percent !== undefined ? {
      qualityPercent: finiteNumber(source.link_quality_percent),
      latencyMs: finiteNumber(source.link_latency_ms),
      packetLossPercent: finiteNumber(source.packet_loss_percent),
      evidenceClass: evidenceClass(observation?.source_class),
    } : undefined,
    faults: Array.isArray(source.faults) ? source.faults.filter((item): item is string => typeof item === "string") : [],
    provenance: fieldProvenance(
      observation,
      "position_m",
      "SI",
      source.frame === "body" ? "body" : source.frame === "world" ? "world" : "home",
      freshness,
      envelope,
    ),
  };
}

function mapRanges(value: unknown, freshness: Freshness): RangeRay[] {
  const source = asRecord(value);
  if (!source) return [];
  const maximumM = finiteNumber(source.max_range_m);
  if (maximumM === undefined) return [];
  return DIRECTIONS.flatMap((direction) => {
    const distanceM = finiteNumber(source[`${direction}_m`]);
    return distanceM === undefined ? [] : [{ direction, distanceM, maximumM, freshness }];
  });
}

function mapTransport(value: unknown): TransportView | null {
  const source = asRecord(value);
  if (!source || (source.kind !== "physical_radio" && source.kind !== "modeled_transport" && source.kind !== "replay")) return null;
  return {
    kind: source.kind,
    evidenceClass: evidenceClass(source.source_class),
    deliveryQualityPercent: finiteNumber(source.delivery_quality_percent),
    latencyMs: finiteNumber(source.latency_ms),
    packetLossPercent: finiteNumber(source.packet_loss_percent),
  };
}

function mapDecks(value: unknown): DeckView[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    const source = asRecord(item);
    const type = source?.deck_type;
    if (!source || source.present !== true || !isDeckType(type)) return [];
    return [{
      id: `${type}-${index + 1}`,
      name: stringValue(source.name, `${type} model`),
      type,
      health: source.health === "HEALTHY" || source.health === "DEGRADED" || source.health === "FAILED" ? source.health : "UNKNOWN",
    }];
  });
}

function mapRoom(worldValue: Record<string, unknown>, selectedVehicleId: string | undefined, flightVolumeValue: unknown): RoomView | undefined {
  const source = asRecord(worldValue.world);
  const widthM = finiteNumber(source?.width_m);
  const depthM = finiteNumber(source?.depth_m);
  const heightM = finiteNumber(source?.height_m);
  if (!source || widthM === undefined || depthM === undefined || heightM === undefined) return undefined;
  const spawn = Array.isArray(worldValue.vehicles)
    ? worldValue.vehicles.map(asRecord).find((item) => item?.vehicle_id === selectedVehicleId)
    : undefined;
  const flightVolume = asRecord(flightVolumeValue);
  const geofenceMinimum = vec3(flightVolume?.minimum_m);
  const geofenceMaximum = vec3(flightVolume?.maximum_m);
  return {
    id: stringValue(source.world_id, "configured-room"),
    widthM,
    depthM,
    heightM,
    home: vec3(spawn?.position_m) ?? undefined,
    geofence: geofenceMinimum && geofenceMaximum ? { minimum: geofenceMinimum, maximum: geofenceMaximum } : undefined,
    obstacles: Array.isArray(source.obstacles) ? source.obstacles.flatMap((value) => {
      const obstacle = asRecord(value);
      const minimum = vec3(obstacle?.minimum_m);
      const maximum = vec3(obstacle?.maximum_m);
      return obstacle && minimum && maximum
        ? [{ id: stringValue(obstacle.obstacle_id, "obstacle"), minimum, maximum }]
        : [];
    }) : [],
    source: "configured",
    frame: "world",
    version: finiteNumber(worldValue.schema_version) ?? 1,
  };
}

function mapFidelity(source: Record<string, unknown>): FidelityManifest | undefined {
  if (source.source_class !== "SIMULATED_MODEL") return undefined;
  return {
    id: stringValue(source.manifest_id, "unknown"),
    sourceClass: "SIMULATED_MODEL",
    model: stringValue(source.model, "unspecified model"),
    modeledOutputs: stringArray(source.modeled_outputs),
    omittedOutputs: stringArray(source.omitted_outputs),
    limitations: stringArray(source.limitations),
  };
}

function mapLatestRun(value: unknown): MissionRunView | undefined {
  if (!Array.isArray(value)) return undefined;
  const runs = value.map(asRecord).filter((item): item is Record<string, unknown> => item !== null);
  const source = runs.reduce<Record<string, unknown> | undefined>((latest, item) => {
    const started = finiteNumber(item.started_at_monotonic_s) ?? -1;
    const latestStarted = finiteNumber(latest?.started_at_monotonic_s) ?? -1;
    return started >= latestStarted ? item : latest;
  }, undefined);
  if (!source || typeof source.mission_run_id !== "string" || typeof source.mission_id !== "string" || typeof source.vehicle_id !== "string") return undefined;
  const result = asRecord(source.result);
  const rawStatus = result?.status;
  const status = rawStatus === "SUCCEEDED" || rawStatus === "ABORTED" || rawStatus === "FAILED" ? rawStatus : "RUNNING";
  return {
    id: source.mission_run_id,
    missionId: source.mission_id,
    vehicleId: source.vehicle_id,
    phase: stringValue(source.phase, "SCHEDULED"),
    status,
    parameters: primitiveRecord(source.parameters),
    resultMessage: typeof result?.message === "string" ? result.message : undefined,
  };
}

function provenance(
  sourceClass: EvidenceClass,
  source: string,
  unit: string,
  frame: "world" | "home" | "body" | "sensor",
  freshness: Freshness,
  envelope: Record<string, unknown> | null,
) {
  return {
    evidenceClass: sourceClass,
    source,
    unit,
    frame,
    freshness,
    timestamp: typeof envelope?.recorded_at_utc === "string" ? envelope.recorded_at_utc : undefined,
    sourceTimeS: finiteNumber(envelope?.source_timestamp_s),
    receiveTimeS: finiteNumber(envelope?.received_timestamp_s),
    simulationTimeS: finiteNumber(envelope?.simulation_timestamp_s),
    replayTimeS: finiteNumber(envelope?.replay_timestamp_s),
    sourceClockId: typeof envelope?.source_clock_id === "string" ? envelope.source_clock_id : undefined,
    sourceClockEpoch: finiteNumber(envelope?.source_clock_epoch),
    ageMs: telemetryAgeMs(envelope),
  };
}

function fieldProvenance(
  observation: Record<string, unknown> | null,
  field: string,
  fallbackUnit: string,
  fallbackFrame: "world" | "home" | "body" | "sensor",
  freshness: Freshness,
  envelope: Record<string, unknown> | null,
) {
  const fields = asRecord(observation?.fields);
  const metadata = asRecord(fields?.[field]);
  const frame = metadata?.frame === "world" || metadata?.frame === "home" || metadata?.frame === "body" || metadata?.frame === "sensor"
    ? metadata.frame
    : fallbackFrame;
  return provenance(
    evidenceClass(metadata?.source_class ?? observation?.source_class),
    stringValue(metadata?.source, "vehicle adapter"),
    stringValue(metadata?.unit, fallbackUnit),
    frame,
    freshness,
    envelope,
  );
}

function telemetryAgeMs(envelope: Record<string, unknown> | null): number | undefined {
  if (!envelope || typeof envelope.recorded_at_utc !== "string") return undefined;
  const recorded = Date.parse(envelope.recorded_at_utc);
  return Number.isFinite(recorded) ? Math.max(0, Math.round(Date.now() - recorded)) : undefined;
}

function telemetryFreshness(envelope: Record<string, unknown> | null): Freshness {
  const age = telemetryAgeMs(envelope);
  return age === undefined ? "absent" : age > 1000 ? "stale" : "current";
}

function evidenceClass(value: unknown): EvidenceClass {
  return value === "MEASURED_REAL" || value === "SIMULATED_MODEL" || value === "DERIVED" || value === "PLANNED" || value === "CONFIGURED" || value === "REPLAYED" ? value : "UNAVAILABLE";
}

function isMode(value: unknown): value is DashboardModel["mode"] {
  return value === "SIM" || value === "LIVE" || value === "SHADOW" || value === "REPLAY";
}

function isObservationStatus(value: string): value is VehicleView["observationStatus"] {
  return value === "NOT_STARTED" || value === "ACTIVE" || value === "COMPLETED_SNAPSHOT" || value === "UNAVAILABLE";
}

function isDeckType(value: unknown): value is DeckView["type"] {
  return value === "flow" || value === "multiranger" || value === "lighthouse" || value === "loco" || value === "ai";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function vec3(value: unknown): Vec3 | null {
  const source = asRecord(value);
  const x = finiteNumber(source?.x);
  const y = finiteNumber(source?.y);
  const z = finiteNumber(source?.z);
  return x === undefined || y === undefined || z === undefined ? null : { x, y, z };
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function primitiveRecord(value: unknown): Record<string, number | string | boolean> {
  const source = asRecord(value);
  if (!source) return {};
  return Object.fromEntries(Object.entries(source).filter((entry): entry is [string, number | string | boolean] => ["number", "string", "boolean"].includes(typeof entry[1])));
}
