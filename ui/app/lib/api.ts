import { createEmptyDashboard } from "./empty";
import type {
  AuthorityClass,
  BackendRole,
  CampaignCatalogView,
  CampaignWorkspaceView,
  DashboardModel,
  DeckView,
  EvidenceClass,
  FidelityManifest,
  FleetSessionView,
  Freshness,
  MissionOption,
  MissionPreview,
  MissionRunView,
  ParameterView,
  PreflightReportView,
  RangeRay,
  ReplayView,
  RoomView,
  RunFileMissionView,
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
  execution_session_id: string;
  member_count: number;
  status: string;
}

export interface MissionPlanApprovalResult {
  approvalId: string;
  planSha256: string;
}

export interface LiveDashboardSnapshot {
  dashboard: DashboardModel;
  activeRun?: MissionRunView;
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
      const message = stringValue(error?.message, `Control API returned ${response.status}`);
      throw new Error(formatControlError(message, asRecord(error?.details)));
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

  async loadLiveDashboard(current: DashboardModel, activeRunId?: string): Promise<LiveDashboardSnapshot> {
    const state = await this.request<Record<string, unknown>>("/api/v1/state");
    return {
      dashboard: adaptDashboardState(current, state, this.credentials.clientId),
      activeRun: activeRunId ? mapMissionRunById(state.mission_runs, activeRunId) : undefined,
    };
  }

  async createTwoDroneFleet(backend: "FAST_SIM" | "MOCK_ISAAC"): Promise<FleetSessionView> {
    const template = await this.request<Record<string, unknown>>("/api/v1/fleet/templates/two-drone");
    const bindings = Array.isArray(template.bindings) ? template.bindings : [];
    const binding = bindings.find((value) => asRecord(value)?.backend === backend);
    if (!binding || !asRecord(template.deployment)) throw new Error(`No ${backend} two-drone template is available`);
    const suffix = crypto.randomUUID().replaceAll("-", "").slice(0, 12);
    const value = await this.post<Record<string, unknown>>("/api/v1/fleet/sessions", {
      execution_session_id: `fleet-session-${suffix}`,
      fleet_run_id: `fleet-run-${suffix}`,
      mission_id: "hover",
      deployment: template.deployment,
      binding,
    });
    return requireFleetSession(value);
  }

  async connectFleet(sessionId: string): Promise<FleetSessionView> {
    return requireFleetSession(await this.post(`/api/v1/fleet/sessions/${encodeURIComponent(sessionId)}/connect`, {}));
  }

  async observeFleet(sessionId: string): Promise<FleetSessionView> {
    return requireFleetSession(await this.post(`/api/v1/fleet/sessions/${encodeURIComponent(sessionId)}/observe`, {}));
  }

  async preflightFleet(sessionId: string): Promise<FleetSessionView> {
    return requireFleetSession(await this.post(`/api/v1/fleet/sessions/${encodeURIComponent(sessionId)}/preflight`, {}));
  }

  async startFleet(session: FleetSessionView): Promise<FleetSessionView> {
    if (!session.runId) throw new Error("Fleet run identity is unavailable");
    const assignments = Object.fromEntries(
      session.tasks.map((task, index) => [task.id, session.vehicles[index]?.id]),
    );
    if (Object.values(assignments).some((vehicleId) => !vehicleId)) throw new Error("Fleet assignment is incomplete");
    return requireFleetSession(await this.post(`/api/v1/fleet/runs/${encodeURIComponent(session.runId)}/start`, { assignments }));
  }

  async abortFleetVehicle(runId: string, vehicleId: string): Promise<FleetSessionView> {
    return requireFleetSession(await this.post(`/api/v1/fleet/runs/${encodeURIComponent(runId)}/vehicles/${encodeURIComponent(vehicleId)}/abort`, { reason: "operator requested individual abort" }));
  }

  async disconnectFleet(sessionId: string): Promise<FleetSessionView> {
    return requireFleetSession(await this.post(`/api/v1/fleet/sessions/${encodeURIComponent(sessionId)}/disconnect`, {}));
  }

  async fleetQualification(): Promise<Record<string, unknown>> {
    return this.request("/api/v1/fleet/qualification");
  }

  async fleetReplay(runId: string): Promise<Record<string, unknown>> {
    return this.request(`/api/v1/fleet/runs/${encodeURIComponent(runId)}/replay`);
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

  async resetSimulationPose(vehicleId: string): Promise<void> {
    await this.post<Record<string, unknown>>(
      `/api/v1/simulation/vehicles/${encodeURIComponent(vehicleId)}/clock`,
      { action: "reset_pose" },
    );
  }

  async rechargeSimulation(vehicleId: string): Promise<number | undefined> {
    return this.setSimulationBattery(vehicleId, 100);
  }

  async setSimulationBattery(vehicleId: string, batteryPercent: number): Promise<number | undefined> {
    const response = await this.post<Record<string, unknown>>(
      `/api/v1/simulation/vehicles/${encodeURIComponent(vehicleId)}/clock`,
      { action: "recharge", battery_percent: batteryPercent },
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

  async previewMission(missionId: string): Promise<MissionPreview> {
    const response = await this.request<Record<string, unknown>>(
      `/api/v1/mission-files/${encodeURIComponent(missionId)}/preview`,
    );
    if (typeof response.mission_id !== "string" || typeof response.source_sha256 !== "string") {
      throw new Error("Mission preview response is invalid");
    }
    const vehicles = (Array.isArray(response.vehicles) ? response.vehicles : []).flatMap((value) => {
      const vehicle = asRecord(value);
      const home = vec3(vehicle?.home_m);
      const start = vec3(vehicle?.start_m);
      if (
        !vehicle
        || typeof vehicle.role_id !== "string"
        || typeof vehicle.vehicle_id !== "string"
        || !home
        || !start
      ) return [];
      return [{
        roleId: vehicle.role_id,
        vehicleId: vehicle.vehicle_id,
        displayName: stringValue(vehicle.display_name, vehicle.vehicle_id),
        initialRole: vehicle.initial_role === "RESERVE" ? "RESERVE" as const : "ACTIVE" as const,
        home,
        start,
        batteryPercent: finiteNumber(vehicle.battery_percent),
        minimumBatteryPercent: finiteNumber(vehicle.minimum_battery_percent),
        existingVehicle: vehicle.existing_vehicle === true,
        backendRole: isBackendRole(stringValue(vehicle.backend_role, ""))
          ? stringValue(vehicle.backend_role, "") as BackendRole
          : undefined,
        vehicleState: typeof vehicle.vehicle_state === "string" ? vehicle.vehicle_state : undefined,
        previewFidelity: vehicle.preview_fidelity === "EXACT_ROLE" ? "EXACT_ROLE" as const : "STATIC_BOUNDS" as const,
        plannedCommands: mapPlannedCommands(vehicle.planned_commands),
      }];
    });
    if (!vehicles.length) throw new Error("Mission preview has no declared vehicles");
    const plan = mapMissionPlan(response.plan, response.plan_sha256);
    if (!plan) throw new Error("Mission preview has no valid operational plan");
    return {
      missionId: response.mission_id,
      sourceSha256: response.source_sha256,
      plan,
      vehicles,
    };
  }

  async approveMissionPlan(
    missionId: string,
    planSha256: string,
    acknowledgedFindingCodes: string[],
  ): Promise<MissionPlanApprovalResult> {
    const response = await this.post<Record<string, unknown>>(
      `/api/v1/mission-files/${encodeURIComponent(missionId)}/approve`,
      {
        expected_plan_sha256: planSha256,
        acknowledged_finding_codes: acknowledgedFindingCodes,
      },
    );
    if (typeof response.approval_id !== "string" || typeof response.plan_sha256 !== "string") {
      throw new Error("Mission approval response is invalid");
    }
    return { approvalId: response.approval_id, planSha256: response.plan_sha256 };
  }

  async startMissionFile(
    missionId: string,
    executionMode: "SIMULATION" | "TWIN",
    confirmLowBatteryRisk = false,
    approval?: MissionPlanApprovalResult,
  ): Promise<MissionStartResult> {
    const body: Record<string, unknown> = { execution_mode: executionMode };
    if (confirmLowBatteryRisk) body.confirm_low_battery_risk = true;
    if (approval) {
      body.approval_id = approval.approvalId;
      body.expected_plan_sha256 = approval.planSha256;
    }
    return this.request(`/api/v1/mission-files/${encodeURIComponent(missionId)}/start`, {
      method: "POST",
      body: JSON.stringify(body),
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

  async campaignCatalog(): Promise<CampaignCatalogView> {
    return this.request<CampaignCatalogView>("/api/v1/campaign/cases");
  }

  async campaignState(): Promise<CampaignWorkspaceView> {
    return this.request<CampaignWorkspaceView>("/api/v1/campaign/state");
  }

  async staticValidateCampaignCase(caseId: string): Promise<Record<string, unknown>> {
    return this.post("/api/v1/campaign/cases/static-validate", { case_id: caseId });
  }

  async setActiveCampaignCase(caseId: string, reason: string): Promise<Record<string, unknown>> {
    return this.post("/api/v1/campaign/active", { case_id: caseId, reason });
  }

  async previewActiveCampaign(): Promise<Record<string, unknown>> {
    return this.request("/api/v1/campaign/active/preview");
  }

  async runActiveCampaign(mode: "AUTOMATED_ACCELERATED" | "OPERATOR_OBSERVED_REALTIME"): Promise<Record<string, unknown>> {
    return this.post("/api/v1/campaign/runs", { mode });
  }

  async createCampaignChild(childCaseId: string, updates: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post("/api/v1/campaign/active/child", { child_case_id: childCaseId, updates });
  }

  async addCampaignObservation(reviewId: string, note: string): Promise<Record<string, unknown>> {
    return this.post(`/api/v1/campaign/reviews/${encodeURIComponent(reviewId)}/observations`, { note });
  }

  async decideCampaignReview(
    reviewId: string,
    decision: "APPROVE" | "REJECT" | "NEEDS_RERUN",
    reason: string,
  ): Promise<Record<string, unknown>> {
    return this.post(`/api/v1/campaign/reviews/${encodeURIComponent(reviewId)}/decision`, { decision, reason });
  }

  async recordBrowserTiming(event: {
    correlationId: string;
    stage: "BROWSER_RECEIPT" | "RENDER_FRAME" | "PLAYBACK_BUFFER";
    sourceTimestampS: number;
    sourceClockId: string;
    sourceClockEpoch: number;
    observedMonotonicS: number;
    playbackBufferAgeS?: number;
    droppedSamples?: number;
    coalescedSamples?: number;
  }): Promise<void> {
    await this.post("/api/v1/campaign/timing/browser", {
      correlation_id: event.correlationId,
      stage: event.stage,
      source_timestamp_s: event.sourceTimestampS,
      source_clock_id: event.sourceClockId,
      source_clock_epoch: event.sourceClockEpoch,
      observed_monotonic_s: event.observedMonotonicS,
      playback_buffer_age_s: event.playbackBufferAgeS,
      dropped_samples: event.droppedSamples ?? 0,
      coalesced_samples: event.coalescedSamples ?? 0,
    });
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
      const telemetryCsv = (Array.isArray(value.artifacts) ? value.artifacts : [])
        .flatMap((item) => {
          const artifact = asRecord(item);
          const downloadPath = typeof artifact?.download_url === "string" ? artifact.download_url : "";
          if (
            artifact?.kind !== "TELEMETRY_CSV"
            || typeof artifact.filename !== "string"
            || artifact.media_type !== "text/csv"
            || artifact.schema_version !== "run-telemetry-v1"
            || !(
              downloadPath.startsWith("/api/v1/run-files/")
              || downloadPath.startsWith("/api/v1/runs/")
            )
            || !downloadPath.endsWith("/telemetry.csv")
          ) return [];
          return [{
            kind: "TELEMETRY_CSV" as const,
            filename: artifact.filename,
            mediaType: "text/csv" as const,
            schemaVersion: "run-telemetry-v1" as const,
            downloadUrl: `${this.credentials.endpoint.replace(/\/$/, "")}${downloadPath}`,
            available: artifact.available === true,
            unavailableReason: typeof artifact.unavailable_reason === "string" ? artifact.unavailable_reason : undefined,
            rowCount: Math.max(0, Math.trunc(finiteNumber(artifact.row_count) ?? 0)),
          }];
        })[0];
      return [{
        runId: value.run_id,
        missionId: value.mission_id,
        vehicleId: value.vehicle_id,
        status,
        configurationHash: stringValue(value.configuration_hash, ""),
        startedAtUtc: stringValue(value.started_at_utc, ""),
        telemetryCsv,
      }];
    });
  }

  async runFiles(): Promise<RunFileMissionView[]> {
    const response = await this.request<unknown[]>("/api/v1/run-files?limit=100");
    return response.flatMap((item) => {
      const value = asRecord(item);
      if (
        !value
        || typeof value.mission_execution_id !== "string"
        || typeof value.mission_id !== "string"
      ) return [];
      const status = runFileStatus(value.status);
      const artifact = asRecord(value.artifact);
      const downloadPath = typeof artifact?.download_url === "string"
        ? artifact.download_url
        : undefined;
      const safeDownloadPath = downloadPath
        && downloadPath.startsWith("/api/v1/run-files/")
        && downloadPath.endsWith("/telemetry.csv")
        ? downloadPath
        : undefined;
      return [{
        missionExecutionId: value.mission_execution_id,
        missionId: value.mission_id,
        missionName: stringValue(value.mission_name, value.mission_id),
        status,
        startedAtUtc: stringValue(value.started_at_utc, ""),
        completedAtUtc: typeof value.completed_at_utc === "string" ? value.completed_at_utc : undefined,
        telemetryRowCount: Math.max(0, Math.trunc(finiteNumber(value.telemetry_row_count) ?? 0)),
        filename: typeof artifact?.filename === "string" ? artifact.filename : undefined,
        downloadUrl: safeDownloadPath
          ? `${this.credentials.endpoint.replace(/\/$/, "")}${safeDownloadPath}`
          : undefined,
        available: artifact?.available === true && Boolean(safeDownloadPath),
        sizeBytes: finiteNumber(artifact?.size_bytes),
        sha256: typeof artifact?.sha256 === "string" ? artifact.sha256 : undefined,
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
  const model = adaptDashboardState(createEmptyDashboard(), state, clientId);
  model.missions = missionsValue.flatMap((value) => {
    const mission = mapMission(value);
    return mission ? [mission] : [];
  });
  model.room = mapRoom(worldValue, model.selectedVehicleId, state.configured_flight_volume);
  model.fidelity = mapFidelity(fidelityValue);
  model.twins = mapTwins(twinsValue);
  return model;
}

export function adaptDashboardState(
  current: DashboardModel,
  state: Record<string, unknown>,
  clientId: string,
): DashboardModel {
  const model = { ...current };
  model.apiConnected = true;
  model.serviceLabel = "Local control service";
  if (isMode(state.mode)) model.mode = state.mode;
  if (typeof state.selected_vehicle_id === "string") model.selectedVehicleId = state.selected_vehicle_id;
  const safetyPolicy = asRecord(state.safety_policy);
  const minimumTakeoffBatteryPercent = finiteNumber(
    safetyPolicy?.minimum_takeoff_battery_percent,
  );
  const criticalBatteryPercent = finiteNumber(safetyPolicy?.critical_battery_percent);
  if (
    minimumTakeoffBatteryPercent !== undefined
    && criticalBatteryPercent !== undefined
  ) {
    model.safetyPolicy = { minimumTakeoffBatteryPercent, criticalBatteryPercent };
  }
  model.vehicles = (Array.isArray(state.vehicles) ? state.vehicles : []).flatMap((value) => {
    const vehicle = mapVehicle(value, model.selectedVehicleId, clientId);
    return vehicle ? [vehicle] : [];
  });
  model.latestRun = mapLatestRun(state.mission_runs);
  model.fleetSessions = (Array.isArray(state.fleet_sessions) ? state.fleet_sessions : []).flatMap((value) => {
    const session = mapFleetSession(value);
    return session ? [session] : [];
  });
  return model;
}

function requireFleetSession(value: unknown): FleetSessionView {
  const session = mapFleetSession(value);
  if (!session) throw new Error("Fleet session response is invalid");
  return session;
}

function mapFleetSession(value: unknown): FleetSessionView | null {
  const source = asRecord(value);
  const session = asRecord(source?.session);
  const deployment = asRecord(source?.deployment);
  const binding = asRecord(source?.binding);
  const execution = asRecord(source?.execution);
  const result = asRecord(source?.result);
  const coordination = asRecord(source?.coordination);
  const constraints = asRecord(deployment?.constraints);
  if (!source || !session || !deployment || !binding || typeof session.execution_session_id !== "string" || typeof deployment.deployment_id !== "string") return null;
  const backend = stringValue(binding.backend, "FAST_SIM");
  if (!["FAST_SIM", "MOCK_ISAAC", "ISAAC", "CRAZYFLIE"].includes(backend)) return null;
  const status = stringValue(session.status, "FAULT");
  if (!["DECLARED", "PREPARING", "OBSERVING", "READY", "FAULT", "CLOSED"].includes(status)) return null;
  const fleetDefinitions = new Map(
    (Array.isArray(deployment.fleet) ? deployment.fleet : []).flatMap((item) => {
      const member = asRecord(item);
      return member && typeof member.vehicle_id === "string"
        ? [[member.vehicle_id, member] as const]
        : [];
    }),
  );
  const vehicles = (Array.isArray(session.vehicles) ? session.vehicles : []).flatMap((item) => {
    const vehicle = asRecord(item);
    if (!vehicle || typeof vehicle.vehicle_id !== "string") return [];
    const definition = fleetDefinitions.get(vehicle.vehicle_id);
    return [{
      id: vehicle.vehicle_id,
      home: vec3(definition?.home) ?? undefined,
      registration: stringValue(vehicle.registration, "DECLARED") as FleetSessionView["vehicles"][number]["registration"],
      connection: stringValue(vehicle.connection, "FAULT") as FleetSessionView["vehicles"][number]["connection"],
      missionRole: stringValue(vehicle.mission_role, "UNASSIGNED") as FleetSessionView["vehicles"][number]["missionRole"],
      observation: stringValue(vehicle.observation, "NOT_OBSERVED") as FleetSessionView["vehicles"][number]["observation"],
      preflightApproved: vehicle.preflight_approved === true,
      readinessSamples: finiteNumber(vehicle.readiness_samples) ?? 0,
      readinessReason: stringValue(vehicle.readiness_reason, "WAITING"),
      faultReason: typeof vehicle.fault_reason === "string" ? vehicle.fault_reason : undefined,
    }];
  });
  const definitions = new Map(
    (Array.isArray(deployment.tasks) ? deployment.tasks : []).flatMap((item) => {
      const task = asRecord(item);
      return task && typeof task.task_id === "string" ? [[task.task_id, task] as const] : [];
    }),
  );
  const records = Array.isArray(source.tasks) ? source.tasks : [];
  const tasks = (records.length ? records : Array.from(definitions.values())).flatMap((item) => {
    const record = asRecord(item);
    const definition = asRecord(record?.definition) ?? record;
    if (!record || !definition || typeof definition.task_id !== "string") return [];
    return [{
      id: definition.task_id,
      zoneId: stringValue(definition.zone_id, "unknown"),
      priority: finiteNumber(definition.priority) ?? 0,
      state: stringValue(record.state, "DECLARED") as FleetSessionView["tasks"][number]["state"],
      ownerVehicleId: typeof record.owner_vehicle_id === "string" ? record.owner_vehicle_id : undefined,
      progressPercent: finiteNumber(record.progress_percent) ?? 0,
      leaseGeneration: finiteNumber(record.lease_generation) ?? 0,
    }];
  });
  const vehicleStatesSource = asRecord(coordination?.vehicle_states);
  const vehicleStates = Object.fromEntries(
    Object.entries(vehicleStatesSource ?? {}).flatMap(([vehicleId, state]) => (
      typeof state === "string" ? [[vehicleId, state] as const] : []
    )),
  );
  const handovers = (Array.isArray(coordination?.handovers) ? coordination.handovers : []).flatMap((item) => {
    const handover = asRecord(item);
    if (
      !handover
      || typeof handover.handover_id !== "string"
      || typeof handover.task_id !== "string"
      || typeof handover.outgoing_vehicle_id !== "string"
    ) return [];
    return [{
      id: handover.handover_id,
      taskId: handover.task_id,
      outgoingVehicleId: handover.outgoing_vehicle_id,
      incomingVehicleId: typeof handover.incoming_vehicle_id === "string"
        ? handover.incoming_vehicle_id
        : undefined,
      phase: stringValue(handover.phase, "REQUESTED"),
      incomingLeaseGeneration: finiteNumber(handover.incoming_lease_generation),
      takeoverConfirmed: handover.takeover_confirmed === true,
      reason: stringValue(handover.reason, "handover requested"),
      releaseReason: typeof handover.release_reason === "string"
        ? handover.release_reason
        : undefined,
    }];
  });
  const docks = (Array.isArray(coordination?.dock_snapshots)
    ? coordination.dock_snapshots
    : []).flatMap((item) => {
    const dock = asRecord(item);
    if (!dock || typeof dock.dock_id !== "string") return [];
    const reservations = (Array.isArray(dock.reservations) ? dock.reservations : []).flatMap((value) => {
      const reservation = asRecord(value);
      if (!reservation || typeof reservation.vehicle_id !== "string") return [];
      return [{
        vehicleId: reservation.vehicle_id,
        state: stringValue(reservation.state, "AVAILABLE"),
        modeledChargingConfirmed: reservation.modeled_charging_confirmed === true,
        terminalReason: typeof reservation.terminal_reason === "string"
          ? reservation.terminal_reason
          : undefined,
      }];
    });
    return [{
      id: dock.dock_id,
      health: stringValue(dock.health, "AVAILABLE"),
      reservations,
    }];
  });
  return {
    id: session.execution_session_id,
    deploymentId: deployment.deployment_id,
    missionId: typeof execution?.mission_id === "string" ? execution.mission_id : undefined,
    backend: backend as FleetSessionView["backend"],
    status: status as FleetSessionView["status"],
    runId: typeof source.fleet_run_id === "string" ? source.fleet_run_id : undefined,
    runStatus: stringValue(source.fleet_run_status, "READY"),
    resultReasonCode: typeof execution?.reason_code === "string"
      ? execution.reason_code
      : typeof result?.reason_code === "string"
        ? result.reason_code
        : undefined,
    resultMessage: typeof execution?.message === "string"
      ? execution.message
      : typeof result?.message === "string"
        ? result.message
        : undefined,
    vehicles,
    tasks,
    vehicleStates,
    handovers,
    docks,
    minimumSeparationM: finiteNumber(coordination?.minimum_separation_m),
    warningViolations: finiteNumber(coordination?.warning_violations) ?? 0,
    criticalViolations: finiteNumber(coordination?.critical_violations) ?? 0,
    authorityTransitionCount: finiteNumber(coordination?.authority_transition_count) ?? 0,
    warningSeparationM: finiteNumber(constraints?.warning_separation_m) ?? 0,
    criticalSeparationM: finiteNumber(constraints?.critical_separation_m) ?? 0,
    missionDerived: execution !== null,
    createdAtMonotonicS: finiteNumber(execution?.created_at_monotonic_s) ?? 0,
  };
}

function mapTwins(twinsValue: unknown[]): DashboardModel["twins"] {
  return twinsValue.flatMap((value) => {
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
    packageSchemaVersion: source.package_schema_version === 2 ? 2 : 1,
    logicalRoles: (Array.isArray(source.logical_roles) ? source.logical_roles : []).flatMap((item) => {
      const role = asRecord(item);
      if (!role || typeof role.role_id !== "string" || typeof role.logical_vehicle_id !== "string") return [];
      return [{
        roleId: role.role_id,
        logicalVehicleId: role.logical_vehicle_id,
        initialRole: role.initial_role === "RESERVE" ? "RESERVE" as const : "ACTIVE" as const,
      }];
    }),
    plannedCommands: mapPlannedCommands(source.planned_commands),
  };
}

function mapMissionPlan(value: unknown, sha256Value: unknown): MissionPreview["plan"] | null {
  const plan = asRecord(value);
  const planning = asRecord(plan?.planning);
  const safetyCase = asRecord(planning?.safety_case);
  const intent = asRecord(planning?.mission_intent);
  if (
    !plan
    || typeof plan.plan_id !== "string"
    || typeof sha256Value !== "string"
    || typeof safetyCase?.safety_case_sha256 !== "string"
  ) return null;
  const status = plan.status === "BLOCKED"
    ? "BLOCKED" as const
    : plan.status === "REQUIRES_CONFIRMATION"
      ? "REQUIRES_CONFIRMATION" as const
      : "APPROVED" as const;
  const plugins: MissionPreview["plan"]["plugins"] = (
    Array.isArray(planning?.plugin_selections) ? planning.plugin_selections : []
  ).flatMap((value) => {
    const plugin = asRecord(value);
    const kind = plugin?.kind;
    if (
      !plugin
      || typeof plugin.plugin_id !== "string"
      || typeof plugin.implementation_version !== "string"
      || typeof plugin.manifest_sha256 !== "string"
      || (kind !== "ROUTE_PLANNER" && kind !== "FLEET_POLICY" && kind !== "RECOVERY_STRATEGY")
    ) return [];
    return [{
      id: plugin.plugin_id,
      kind,
      version: plugin.implementation_version,
      capabilities: stringArray(plugin.capabilities_used),
      manifestSha256: plugin.manifest_sha256,
    }];
  });
  const phases: MissionPreview["plan"]["phases"] = (
    Array.isArray(intent?.phases) ? intent.phases : []
  ).flatMap((value) => {
    const phase = asRecord(value);
    const maximumDurationS = finiteNumber(phase?.maximum_duration_s);
    if (!phase || typeof phase.phase_id !== "string" || maximumDurationS === undefined) return [];
    return [{
      id: phase.phase_id,
      objective: stringValue(phase.objective, phase.phase_id),
      roleIds: stringArray(phase.role_ids),
      maximumDurationS,
    }];
  });
  const routes: MissionPreview["plan"]["routes"] = (
    Array.isArray(planning?.route_plans) ? planning.route_plans : []
  ).flatMap((value) => {
    const route = asRecord(value);
    const durationS = finiteNumber(route?.expected_duration_s);
    const energyPercent = finiteNumber(route?.expected_energy_percent);
    const lengthM = finiteNumber(route?.route_length_m);
    if (
      !route
      || typeof route.role_id !== "string"
      || durationS === undefined
      || energyPercent === undefined
      || lengthM === undefined
    ) return [];
    return [{
      roleId: route.role_id,
      status: route.status === "BLOCKED" ? "BLOCKED" as const : "READY" as const,
      durationS,
      energyPercent,
      lengthM,
      waypointCount: Array.isArray(route.waypoints) ? route.waypoints.length : 0,
      findings: stringArray(route.findings),
    }];
  });
  const findings: MissionPreview["plan"]["findings"] = (
    Array.isArray(plan.findings) ? plan.findings : []
  ).flatMap((value) => {
    const finding = asRecord(value);
    if (!finding || typeof finding.code !== "string" || typeof finding.message !== "string") return [];
    return [{
      code: finding.code,
      severity: finding.severity === "BLOCKER"
        ? "BLOCKER" as const
        : finding.severity === "WARNING"
          ? "WARNING" as const
          : "INFO" as const,
      message: finding.message,
      roleId: typeof finding.role_id === "string" ? finding.role_id : undefined,
      requiresConfirmation: finding.requires_confirmation === true,
    }];
  });
  return {
    id: plan.plan_id,
    sha256: sha256Value,
    safetyCaseSha256: safetyCase.safety_case_sha256,
    status,
    objective: stringValue(intent?.objective, "Execute declared mission actions"),
    plugins,
    phases,
    routes,
    findings,
  };
}

function mapPlannedCommands(value: unknown): MissionOption["plannedCommands"] {
  return (Array.isArray(value) ? value : []).flatMap((item) => {
    const command = asRecord(item);
    const action = command?.action;
    const argumentsValue = asRecord(command?.arguments);
    if (!argumentsValue || (action !== "takeoff" && action !== "hover" && action !== "move_relative" && action !== "land")) return [];
    return [{
      action,
      arguments: Object.fromEntries(
        Object.entries(argumentsValue).filter(
          (entry): entry is [string, number | string] => typeof entry[1] === "number" || typeof entry[1] === "string",
        ),
      ),
    }];
  });
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
  const backend = asRecord(source.backend);
  const role = stringValue(backend?.role, "TWIN_OBSERVER");
  const authority = stringValue(backend?.authority, "OBSERVATION_ONLY");
  const backendRole: BackendRole = isBackendRole(role) ? role : "TWIN_OBSERVER";
  const authorityClass: AuthorityClass = isAuthorityClass(authority)
    ? authority
    : "OBSERVATION_ONLY";
  const status = stringValue(observation?.status, "UNAVAILABLE");
  return {
    id: identity.vehicle_id,
    name: stringValue(identity.display_name, identity.vehicle_id),
    adapter: stringValue(identity.adapter, "unknown-adapter"),
    backendRole,
    authorityClass,
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
  return mapMissionRun(source);
}

function mapMissionRunById(value: unknown, runId: string): MissionRunView | undefined {
  if (!Array.isArray(value)) return undefined;
  const source = value.map(asRecord).find((item) => item?.mission_run_id === runId);
  return mapMissionRun(source);
}

function mapMissionRun(source: Record<string, unknown> | null | undefined): MissionRunView | undefined {
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
    resultReasonCode: typeof result?.reason_code === "string" ? result.reason_code : undefined,
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
    sequence: finiteNumber(envelope?.sequence),
    correlationId: typeof envelope?.timing_correlation_id === "string"
      ? envelope.timing_correlation_id
      : undefined,
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
  return value === "NOT_STARTED" || value === "ACTIVE" || value === "CURRENT" || value === "STALE" || value === "COMPLETED_SNAPSHOT" || value === "UNAVAILABLE";
}

function isBackendRole(value: string): value is BackendRole {
  return ["FAST_SIM", "ISAAC_SIM", "REAL_CRAZYFLIE", "REPLAY", "TWIN_OBSERVER"].includes(value);
}

function isAuthorityClass(value: string): value is AuthorityClass {
  return ["SIMULATION", "PHYSICAL", "OBSERVATION_ONLY"].includes(value);
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

function runFileStatus(value: unknown): RunFileMissionView["status"] {
  return value === "SUCCEEDED" || value === "ABORTED" || value === "FAILED"
    ? value
    : "INCOMPLETE";
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function formatControlError(message: string, details: Record<string, unknown> | null): string {
  if (!details) return message;
  const identityParts = ["missing", "unexpected", "duplicate", "vehicle_ids"].flatMap((key) => {
    const values = stringArray(details[key]);
    return values.length ? [`${key.replaceAll("_", " ")}: ${values.join(", ")}`] : [];
  });
  return identityParts.length ? `${message} · ${identityParts.join(" · ")}` : message;
}

function primitiveRecord(value: unknown): Record<string, number | string | boolean> {
  const source = asRecord(value);
  if (!source) return {};
  return Object.fromEntries(Object.entries(source).filter((entry): entry is [string, number | string | boolean] => ["number", "string", "boolean"].includes(typeof entry[1])));
}
