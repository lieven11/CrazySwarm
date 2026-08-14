"use client";

import {
  AlertOctagon,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BatteryCharging,
  Check,
  ChevronDown,
  ChevronUp,
  CircleDot,
  Command,
  FileCode2,
  Hexagon,
  LoaderCircle,
  Play,
  Radio,
  RotateCcw,
  Settings,
  ShieldCheck,
  Square,
  Unplug,
  Upload,
  Trash2,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { ControlApi } from "../lib/api";
import { campaignMissionPreview } from "../lib/campaign-preview";
import { createEmptyDashboard } from "../lib/empty";
import type {
  CampaignCaseView,
  CampaignRunMode,
  CampaignRunSummary,
  DashboardModel,
  FleetSessionView,
  Health,
  MissionOption,
  MissionPreview,
  MissionRunView,
  OperatingMode,
  ParameterView,
  PreflightReportView,
  ReplayView,
  RunFileMissionView,
  RunHistoryView,
  Vec3,
  VehicleView,
} from "../lib/models";
import { missionPlan, missionPreviewPaths } from "../lib/spatial";
import { RoomScene, type HomeBaseView, type SceneSnapshotCapture, type TwinSceneOverlay } from "./RoomScene";
import { FlightReadout, RunFilesControl, telemetrySample, type TelemetrySample } from "./TelemetryDock";
import { CampaignLab, humanizeCampaignValue } from "./CampaignLab";

type ServiceState = "ATTACHING" | "ONLINE" | "OFFLINE";
type SafetyAction = "abort" | "emergency" | null;
type ExecutionMode = "SIMULATION" | "TWIN";
type MaintenanceVehicle = Pick<
  VehicleView,
  "id" | "name" | "backendRole" | "state" | "armed" | "flying"
>;

const LOCAL_API = { endpoint: "/control-api", clientId: "control-center-ui" };
const LIVE_UPDATE_PERIOD_MS = 100;
export const OBSERVED_TRACE_HISTORY_LIMIT = 3_600;
const BATTERY_LEVEL_PRESETS = [5, 10, 20, 50, 75, 100] as const;
export const TOAST_DURATION_MS = 4_500;
export const TOAST_FAILURE_DURATION_MS = 7_000;

export function appendObservedTracePoint(points: Vec3[], point: Vec3): Vec3[] {
  return [...points, point].slice(-OBSERVED_TRACE_HISTORY_LIMIT);
}

export function campaignDockModePresentation(mode: CampaignRunMode): {
  label: "Accelerated" | "Realtime";
  actionLabel: "accelerated" | "realtime";
  buttonClassName: "campaign-mode-accelerated" | "";
} {
  return mode === "AUTOMATED_ACCELERATED"
    ? { label: "Accelerated", actionLabel: "accelerated", buttonClassName: "campaign-mode-accelerated" }
    : { label: "Realtime", actionLabel: "realtime", buttonClassName: "" };
}

export function campaignMissionFilename(campaignCase: CampaignCaseView): string {
  return `campaign_${campaignCase.case_id}.py`;
}

export interface SimulationBatteryStartRisk {
  batteryPercent: number;
  minimumPercent: number;
  minimumKind: "mission" | "takeoff";
  vehicleId?: string;
  affectedVehicleCount: number;
}

type SimulationBatteryStartCandidate = Omit<SimulationBatteryStartRisk, "affectedVehicleCount"> & {
  vehicleId: string;
};

export function simulationBatteryStartRisk(
  preview: MissionPreview | undefined,
  vehicles: VehicleView[],
  fallbackVehicle: VehicleView | undefined,
  takeoffMinimumPercent: number | undefined,
): SimulationBatteryStartRisk | undefined {
  if (takeoffMinimumPercent === undefined) return undefined;
  const candidates = preview
    ? preview.vehicles
        .filter((vehicle) => vehicle.initialRole === "ACTIVE")
        .flatMap((vehicle): SimulationBatteryStartCandidate[] => {
          const liveBattery = vehicles.find((item) => item.id === vehicle.vehicleId)?.telemetry?.batteryPercent;
          const batteryPercent = liveBattery ?? vehicle.batteryPercent;
          const missionMinimum = vehicle.minimumBatteryPercent;
          const minimumPercent = Math.max(takeoffMinimumPercent, missionMinimum ?? 0);
          return batteryPercent === undefined || batteryPercent >= minimumPercent
            ? []
            : [{
                batteryPercent,
                minimumPercent,
                minimumKind: missionMinimum !== undefined && missionMinimum > takeoffMinimumPercent
                  ? "mission" as const
                  : "takeoff" as const,
                vehicleId: vehicle.vehicleId,
              }];
        })
    : fallbackVehicle?.telemetry?.batteryPercent !== undefined
      && fallbackVehicle.telemetry.batteryPercent < takeoffMinimumPercent
      ? [{
          batteryPercent: fallbackVehicle.telemetry.batteryPercent,
          minimumPercent: takeoffMinimumPercent,
          minimumKind: "takeoff" as const,
          vehicleId: fallbackVehicle.id,
        }]
      : [];
  if (!candidates.length) return undefined;
  const mostConstrained = candidates.reduce((current, candidate) =>
    candidate.batteryPercent - candidate.minimumPercent
      < current.batteryPercent - current.minimumPercent
      ? candidate
      : current,
  );
  return { ...mostConstrained, affectedVehicleCount: candidates.length };
}

export function missionPreviewHomeBases(preview: MissionPreview): HomeBaseView[] {
  const singleVehicle = preview.vehicles.length === 1;
  return preview.vehicles.map((vehicle, index) => ({
    vehicleId: vehicle.vehicleId,
    number: index + 1,
    position: singleVehicle ? vehicle.start : vehicle.home,
  }));
}

export function missionSceneHomeBases(
  activeMissionPreview: MissionPreview | undefined,
  retainedMissionStart: HomeBaseView[] | undefined,
  campaignCase: CampaignCaseView | undefined,
  fleet: FleetSessionView | undefined,
): HomeBaseView[] | undefined {
  if (retainedMissionStart) return retainedMissionStart;
  if (activeMissionPreview) return missionPreviewHomeBases(activeMissionPreview);
  return !campaignCase && fleet?.missionDerived
    ? fleet.vehicles.flatMap((vehicle, index) => vehicle.home
        ? [{ vehicleId: vehicle.id, number: index + 1, position: vehicle.home }]
        : [])
    : undefined;
}

export function missionPreviewControlVehicles(
  preview: MissionPreview | undefined,
  liveVehicles: VehicleView[],
): MaintenanceVehicle[] | undefined {
  if (!preview) return undefined;
  const liveById = new Map(liveVehicles.map((vehicle) => [vehicle.id, vehicle]));
  return preview.vehicles.flatMap((vehicle) => {
    const live = liveById.get(vehicle.vehicleId);
    if (live) {
      return [{
        id: live.id,
        name: live.name,
        backendRole: live.backendRole,
        state: live.state,
        armed: live.armed,
        flying: live.flying,
      }];
    }
    return vehicle.existingVehicle && vehicle.backendRole && vehicle.vehicleState
      ? [{
          id: vehicle.vehicleId,
          name: vehicle.displayName,
          backendRole: vehicle.backendRole,
          state: vehicle.vehicleState,
          armed: undefined,
          flying: undefined,
        }]
      : [];
  });
}

export function missionIdForRunningReference(
  runningRunId: string | undefined,
  fleet: FleetSessionView | undefined,
  executionActive: boolean,
  latestRun: MissionRunView | undefined,
  missionStart: { missionId: string; runId?: string } | undefined,
): string | undefined {
  if (!runningRunId) return undefined;
  return (fleet && (executionActive || fleet.runId === runningRunId) ? fleet.missionId : undefined)
    ?? (latestRun?.status === "RUNNING" && latestRun.id === runningRunId
      ? latestRun.missionId
      : undefined)
    ?? (missionStart?.runId === runningRunId ? missionStart.missionId : undefined);
}

export function campaignReferencePlan(
  campaignCase: CampaignCaseView | undefined,
  preview: MissionPreview | undefined,
): MissionPreview | undefined {
  return campaignCase && preview?.sourceSha256 === campaignCase.case_sha256
    ? preview
    : undefined;
}

export function shouldDisplayHistoricalPath(
  activeMissionPreview: MissionPreview | undefined,
  campaignCase: CampaignCaseView | undefined,
  campaignRun: CampaignRunSummary | undefined,
  retainedMissionScene = false,
): boolean {
  return retainedMissionScene || (!activeMissionPreview && (!campaignCase || Boolean(campaignRun)));
}

export function campaignScenePreview(
  preview: MissionPreview | undefined,
  run: CampaignRunSummary | undefined,
): MissionPreview | undefined {
  return run && run.status !== "QUEUED" && run.status !== "RUNNING"
    ? undefined
    : preview;
}

export function ControlCenter() {
  const initialModel = useMemo(() => createEmptyDashboard(), []);
  const [model, setModel] = useState<DashboardModel>(initialModel);
  const modelRef = useRef(initialModel);
  const [serviceState, setServiceState] = useState<ServiceState>("ATTACHING");
  const [selectedMissionId, setSelectedMissionId] = useState("");
  const [activeCampaignCase, setActiveCampaignCase] = useState<CampaignCaseView>();
  const [campaignDockCase, setCampaignDockCase] = useState<CampaignCaseView>();
  const [campaignRun, setCampaignRun] = useState<CampaignRunSummary>();
  const [campaignExecutionMode, setCampaignExecutionMode] = useState<CampaignRunMode>("OPERATOR_OBSERVED_REALTIME");
  const [campaignSubmissionId, setCampaignSubmissionId] = useState<string>();
  const [campaignPlanningSubmissionId, setCampaignPlanningSubmissionId] = useState<string>();
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("SIMULATION");
  const [uploadFile, setUploadFile] = useState<File>();
  const [uploadName, setUploadName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string>();
  const [activeExecutionId, setActiveExecutionId] = useState<string>();
  const [observedVehicleId, setObservedVehicleId] = useState<string>();
  const [targetVehicleIds, setTargetVehicleIds] = useState<string[]>([]);
  const targetSelectionInitializedRef = useRef(false);
  const [historyByVehicle, setHistoryByVehicle] = useState<Record<string, { runId?: string; points: Vec3[] }>>({});
  const [telemetryHistoryByVehicle, setTelemetryHistoryByVehicle] = useState<Record<string, { key?: string; points: TelemetrySample[] }>>({});
  const [missionOpen, setMissionOpen] = useState(false);
  const [telemetryOpen, setTelemetryOpen] = useState(false);
  const [notice, setNotice] = useState<string>();
  const dismissNotice = useCallback(() => setNotice(undefined), []);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<string>();
  const [preflight, setPreflight] = useState<PreflightReportView>();
  const [safetyAction, setSafetyAction] = useState<SafetyAction>(null);
  const [parametersOpen, setParametersOpen] = useState(false);
  const [engineeringParameters, setEngineeringParameters] = useState<ParameterView[]>([]);
  const [parameterSnapshotId, setParameterSnapshotId] = useState<string>();
  const [parameterDiffCount, setParameterDiffCount] = useState<number>();
  const [runHistory, setRunHistory] = useState<RunHistoryView[]>([]);
  const [runHistoryLoading, setRunHistoryLoading] = useState(false);
  const [runFileMissions, setRunFileMissions] = useState<RunFileMissionView[]>([]);
  const [runFilesLoaded, setRunFilesLoaded] = useState(false);
  const [runFilesLoading, setRunFilesLoading] = useState(false);
  const [runFilesError, setRunFilesError] = useState<string>();
  const [deletingRunFileMissionId, setDeletingRunFileMissionId] = useState<string>();
  const [replay, setReplay] = useState<ReplayView>();
  const [batteryMenuOpen, setBatteryMenuOpen] = useState(false);
  const [customBatteryPercent, setCustomBatteryPercent] = useState("50");
  const [lowBatteryConfirmation, setLowBatteryConfirmation] = useState<SimulationBatteryStartRisk>();
  const [missionPreview, setMissionPreview] = useState<MissionPreview>();
  const [campaignPreview, setCampaignPreview] = useState<MissionPreview>();
  const [planOverview, setPlanOverview] = useState<MissionPreview>();
  const [twinSceneOverlay, setTwinSceneOverlay] = useState<TwinSceneOverlay>();
  const [missionStart, setMissionStart] = useState<{ missionId: string; runId?: string; homeBases: HomeBaseView[] }>();
  const [previewingMissionId, setPreviewingMissionId] = useState<string>();
  const previewRequestRef = useRef(0);
  const campaignPreviewRequestRef = useRef(0);
  const autoPreviewMissionIdRef = useRef<string | undefined>(undefined);
  const activeCampaignCaseIdRef = useRef<string | undefined>(undefined);
  const batteryControlRef = useRef<HTMLDivElement>(null);

  const api = useMemo(() => new ControlApi(LOCAL_API), []);
  const loadTwinTimeline = useCallback(
    (sessionId: string) => api.twinTimeline(sessionId),
    [api],
  );
  const handleActiveCampaignCaseChange = useCallback((campaignCase: CampaignCaseView | undefined) => {
    const activeCaseChanged = activeCampaignCaseIdRef.current !== campaignCase?.case_id;
    activeCampaignCaseIdRef.current = campaignCase?.case_id;
    setActiveCampaignCase(campaignCase);
    if (!activeCaseChanged) {
      setCampaignDockCase((current) => current?.case_id === campaignCase?.case_id
        ? campaignCase
        : current);
      return;
    }
    setCampaignDockCase(campaignCase);
    setCampaignPreview(undefined);
    setCampaignRun(undefined);
    if (!campaignCase) return;
    previewRequestRef.current += 1;
    autoPreviewMissionIdRef.current = undefined;
    setMissionPreview(undefined);
    setPlanOverview(undefined);
    setObservedVehicleId(undefined);
    setTargetVehicleIds([]);
    setExecutionMode("SIMULATION");
  }, []);
  const handleCampaignRunChange = useCallback((run: CampaignRunSummary | undefined) => {
    setCampaignRun(run);
  }, []);
  const handleCampaignExecutionModeChange = useCallback((mode: CampaignRunMode) => {
    setCampaignExecutionMode(mode);
  }, []);
  const handleCampaignSubmissionChange = useCallback((submissionId: string | undefined) => {
    setCampaignSubmissionId(submissionId);
    setCampaignPreview(undefined);
  }, []);
  const handleCampaignPlanningSubmissionChange = useCallback((planningSubmissionId: string | undefined) => {
    setCampaignPlanningSubmissionId(planningSubmissionId);
    setCampaignPreview(undefined);
  }, []);
  const captureCampaignScene = useCallback(async (capture: SceneSnapshotCapture) => {
    if (!campaignRun || campaignRun.status !== "RUNNING") {
      throw new Error("Campaign snapshots are available only while a run is running");
    }
    await api.uploadCampaignSnapshot(campaignRun.run_id, capture);
    setNotice("Campaign scene snapshot captured");
  }, [api, campaignRun]);
  const observationVehicleId = observedVehicleId && model.vehicles.some((vehicle) => vehicle.id === observedVehicleId)
    ? observedVehicleId
    : model.selectedVehicleId;
  const selectedVehicle = model.vehicles.find((vehicle) => vehicle.id === observationVehicleId);
  const fleet = latestMissionDeployment(model.fleetSessions);
  const executionActive = fleet && activeExecutionId === fleet.id
    && ["SCHEDULED", "PREPARING", "READY", "RUNNING"].includes(fleet.runStatus);
  const runningRunId = activeRunId
    ?? (executionActive ? fleet.runId : undefined)
    ?? (model.latestRun?.status === "RUNNING" ? model.latestRun.id : undefined);
  const activeMissionId = missionIdForRunningReference(
    runningRunId,
    fleet,
    Boolean(executionActive),
    model.latestRun,
    missionStart,
  );
  const effectiveMissionId = activeMissionId || selectedMissionId || model.missions[0]?.id || "";
  const selectedMission = model.missions.find((mission) => mission.id === effectiveMissionId);
  const campaignRunId = campaignRun?.run_id;
  const campaignRunActive = campaignRun?.status === "QUEUED" || campaignRun?.status === "RUNNING";
  const campaignModePresentation = campaignDockModePresentation(campaignExecutionMode);
  // Keep the admitted campaign geometry available after launch. The live vehicle
  // positions replace the preview vehicle, but the route remains the operator's
  // reference for comparing intended and observed motion.
  const campaignPlanOverview = campaignReferencePlan(campaignDockCase, campaignPreview);
  const activePythonMissionPreview = !runningRunId && missionPreview?.missionId === effectiveMissionId
    ? missionPreview
    : undefined;
  const activeCampaignPreview = !runningRunId
    && !campaignRunActive
    && campaignPlanOverview
    ? campaignPlanOverview
    : undefined;
  const activeMissionPreview = campaignDockCase
    ? activeCampaignPreview
    : activePythonMissionPreview;

  useEffect(() => {
    if (!campaignDockCase || runningRunId || campaignRunActive) return;
    const requestId = campaignPreviewRequestRef.current + 1;
    campaignPreviewRequestRef.current = requestId;
    let cancelled = false;
    void api.previewActiveCampaign(campaignSubmissionId, campaignPlanningSubmissionId).then((payload) => {
      if (cancelled || campaignPreviewRequestRef.current !== requestId) return;
      const preview = campaignMissionPreview(campaignDockCase, payload);
      if (!preview) throw new Error("Campaign preview has no selected route");
      setCampaignPreview(preview);
    }).catch((error: unknown) => {
      if (!cancelled && campaignPreviewRequestRef.current === requestId) {
        setNotice(error instanceof Error ? error.message : "Campaign preview unavailable");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [api, campaignDockCase, campaignPlanningSubmissionId, campaignRunActive, campaignSubmissionId, runningRunId]);

  const previewControlVehicles = missionPreviewControlVehicles(activeMissionPreview, model.vehicles);
  const controlScopeVehicles: MaintenanceVehicle[] = campaignDockCase
    ? previewControlVehicles?.length ? previewControlVehicles : model.vehicles
    : activeMissionPreview
    ? previewControlVehicles ?? []
    : model.vehicles;
  const controlScopeVehicleIds = new Set(controlScopeVehicles.map((vehicle) => vehicle.id));
  const effectiveTargetVehicleIds = targetVehicleIds.filter((vehicleId) =>
    controlScopeVehicleIds.has(vehicleId),
  );
  const commandTargetVehicles = vehiclesForTargetSelection(
    controlScopeVehicles,
    effectiveTargetVehicleIds,
  );
  const simulationTargetVehicles = commandTargetVehicles.filter(
    (vehicle) => vehicle.backendRole === "FAST_SIM",
  );
  const allCommandTargetsAreFastSim = commandTargetVehicles.length > 0
    && simulationTargetVehicles.length === commandTargetVehicles.length;
  const singleTargetVehicle = effectiveTargetVehicleIds.length === 1
    ? model.vehicles.find((vehicle) => vehicle.id === effectiveTargetVehicleIds[0])
    : undefined;
  const singleTargetName = effectiveTargetVehicleIds.length === 1
    ? singleTargetVehicle?.name
      ?? activeMissionPreview?.vehicles.find(
        (vehicle) => vehicle.vehicleId === effectiveTargetVehicleIds[0],
      )?.displayName
    : undefined;
  const sceneVehicleCount = activeMissionPreview?.vehicles.length
    ?? campaignDockCase?.drone_count
    ?? model.vehicles.length;
  const selectedPlanOverview = planOverview?.missionId === effectiveMissionId
    ? planOverview
    : undefined;
  const referencePlanOverview = campaignDockCase
    ? campaignPlanOverview
    : runningRunId
      ? activeMissionId && planOverview?.missionId === activeMissionId ? planOverview : undefined
      : selectedPlanOverview;
  const selectedMissionPlanId = runningRunId && !activeMissionId ? undefined : selectedMission?.id;
  const selectedPlanOverviewMissionId = selectedPlanOverview?.missionId;
  const retainedMissionStart = !campaignDockCase && missionStart?.missionId === effectiveMissionId
    ? missionStart.homeBases
    : undefined;
  const retainedCampaignHomeBases = campaignDockCase && campaignPlanOverview
    ? missionPreviewHomeBases(campaignPlanOverview)
    : undefined;
  const retainedSceneHomeBases = retainedCampaignHomeBases ?? retainedMissionStart;
  const detectedLowBatteryRisk = simulationBatteryStartRisk(
    activeMissionPreview,
    model.vehicles,
    selectedVehicle,
    model.safetyPolicy?.minimumTakeoffBatteryPercent,
  );
  const homeBases = missionSceneHomeBases(
    activeMissionPreview,
    retainedSceneHomeBases,
    campaignDockCase,
    fleet,
  );
  const plannedPath = referencePlanOverview
    ? missionPreviewPaths(referencePlanOverview)
    : runningRunId || campaignDockCase
      ? {}
      : missionPlan(selectedMission, model.room);
  const displayHistoricalPath = shouldDisplayHistoricalPath(
    activeMissionPreview,
    campaignDockCase,
    campaignRun,
    Boolean(retainedMissionStart || (campaignDockCase && campaignRun)),
  );
  const historicalPath = useMemo(
    () => displayHistoricalPath
      ? Object.fromEntries(
          Object.entries(historyByVehicle).map(([vehicleId, value]) => [vehicleId, value.points]),
        )
      : {},
    [displayHistoricalPath, historyByVehicle],
  );
  const observationModel = withObservationFocus(model, observationVehicleId);
  const targetSelectionModel = withVehicleTargetSelection(
    observationModel,
    effectiveTargetVehicleIds,
  );
  const rendererModel = replay
    ? { ...targetSelectionModel, mode: "REPLAY" as const }
    : campaignDockCase && !activeMissionPreview && !campaignRunActive && !runningRunId
      ? { ...targetSelectionModel, vehicles: [] }
      : targetSelectionModel;
  const twinAvailable = model.vehicles.some((vehicle) => vehicle.authorityClass === "PHYSICAL")
    && model.vehicles.some((vehicle) => vehicle.authorityClass === "SIMULATION");
  const selectedVehicleException = singleTargetVehicle ? vehicleException(singleTargetVehicle) : undefined;
  const simulationQuickActionsDisabled = !allCommandTargetsAreFastSim
    || Boolean(runningRunId || campaignRunActive)
    || Boolean(busyAction);
  const simulationBatteryDisabled = !allCommandTargetsAreFastSim
    || simulationTargetVehicles.some((vehicle) => !simulationBatteryControlEnabled(
      vehicle,
      Boolean(runningRunId || campaignRunActive),
      Boolean(busyAction),
    ));
  const simulationQuickActionHint = runningRunId || campaignRunActive
    ? "Stop the mission first"
    : campaignDockCase
      ? "Reset simulator motion before staging this campaign"
      : "Reset simulator motion and return the drone to its configured home";
  const simulationBatteryHint = runningRunId || campaignRunActive
    ? "Stop the mission first"
    : simulationBatteryDisabled
      ? "Recharge is available once the simulated drone is disarmed and no longer flying"
      : undefined;

  useEffect(() => {
    if (!batteryMenuOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!batteryControlRef.current?.contains(event.target as Node)) setBatteryMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setBatteryMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [batteryMenuOpen]);

  const applyDashboard = useCallback((dashboard: DashboardModel) => {
    modelRef.current = dashboard;
    setModel(dashboard);
    const availableVehicleIds = new Set(dashboard.vehicles.map((vehicle) => vehicle.id));
    if (!targetSelectionInitializedRef.current) {
      targetSelectionInitializedRef.current = true;
      setTargetVehicleIds(
        dashboard.selectedVehicleId && availableVehicleIds.has(dashboard.selectedVehicleId)
          ? [dashboard.selectedVehicleId]
          : [],
      );
    } else {
      setTargetVehicleIds((current) => {
        const next = current.filter((vehicleId) => availableVehicleIds.has(vehicleId));
        return next.length === current.length ? current : next;
      });
    }
    setTelemetryHistoryByVehicle((current) => {
      let changed = false;
      const next = { ...current };
      for (const vehicle of dashboard.vehicles) {
        const sample = telemetrySample(vehicle);
        if (!sample) continue;
        const key = vehicle.observationRunId
          ?? `${vehicle.id}:${vehicle.telemetry?.provenance.sourceClockEpoch ?? 0}`;
        const existing = current[vehicle.id];
        if (existing?.key !== key) {
          next[vehicle.id] = { key, points: [sample] };
          changed = true;
          continue;
        }
        const previous = existing.points.at(-1);
        if (previous?.t === sample.t) continue;
        next[vehicle.id] = {
          key,
          points: [...existing.points, sample]
            .filter((point) => sample.t - point.t <= 65)
            .slice(-600),
        };
        changed = true;
      }
      return changed ? next : current;
    });
    setHistoryByVehicle((current) => {
      let changed = false;
      const next = { ...current };
      for (const vehicle of dashboard.vehicles) {
        const runId = vehicle.observationRunId;
        const point = vehicle.telemetry?.estimate;
        if (!runId || !point) continue;
        const existing = current[vehicle.id];
        if (existing?.runId !== runId) {
          next[vehicle.id] = { runId, points: [point] };
          changed = true;
          continue;
        }
        const previous = existing.points.at(-1);
        if (previous && previous.x === point.x && previous.y === point.y && previous.z === point.z) continue;
        next[vehicle.id] = { runId, points: appendObservedTracePoint(existing.points, point) };
        changed = true;
      }
      return changed ? next : current;
    });
  }, []);

  const attachLocalService = useCallback(async () => {
    setServiceState("ATTACHING");
    const dashboard = await api.loadDashboard();
    applyDashboard(dashboard);
    const activeDeployment = latestMissionDeployment(
      dashboard.fleetSessions.filter(
        (session) => ["SCHEDULED", "PREPARING", "READY", "RUNNING"].includes(session.runStatus),
      ),
    );
    setActiveExecutionId(activeDeployment?.id);
    setActiveRunId(
      !activeDeployment && dashboard.latestRun?.status === "RUNNING"
        ? dashboard.latestRun.id
        : undefined,
    );
    setServiceState("ONLINE");
  }, [api, applyDashboard]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const attach = async () => {
      try {
        await attachLocalService();
        if (cancelled) return;
      } catch {
        if (cancelled) return;
        setServiceState("OFFLINE");
        setModel(createEmptyDashboard());
        timer = window.setTimeout(attach, 2_000);
      }
    };
    void attach();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [attachLocalService]);

  useEffect(() => {
    if (!campaignRunActive || !campaignRunId) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const workspace = await api.campaignState();
        if (cancelled) return;
        const tracked = workspace.runs.find((run) => run.run_id === campaignRunId);
        if (!tracked) {
          setCampaignRun(undefined);
          setNotice("Campaign run is no longer tracked");
          return;
        }
        setCampaignRun(tracked);
        if (tracked.status === "QUEUED" || tracked.status === "RUNNING") {
          timer = window.setTimeout(poll, 500);
          return;
        }
        void api.loadDashboard().then(applyDashboard).catch(() => undefined);
        if (tracked.status === "SUCCEEDED") {
          setNotice("Campaign run succeeded · review evidence is ready");
        } else if (tracked.status === "ABORTED" || tracked.status === "CANCELLED_BEFORE_LAUNCH") {
          setNotice("Campaign run aborted · vehicles returned to a safe state");
        } else {
          setNotice(`Campaign run failed${tracked.failure_reason ? ` · ${tracked.failure_reason}` : ""}`);
        }
      } catch (error) {
        if (!cancelled) {
          setNotice(error instanceof Error ? error.message : "Campaign status unavailable");
          timer = window.setTimeout(poll, 2_000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, applyDashboard, campaignRunActive, campaignRunId]);

  // Campaign state only reports lifecycle progress. Poll the shared live state
  // independently so realtime campaign flights render their current position and
  // build an observed trace while the route remains visible.
  useEffect(() => {
    if (!campaignRunActive) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      const startedAtMs = performance.now();
      try {
        const { dashboard } = await api.loadLiveDashboard(modelRef.current);
        if (cancelled) return;
        applyDashboard(dashboard);
        setServiceState("ONLINE");
      } catch (error) {
        if (!cancelled) {
          setServiceState("OFFLINE");
          setNotice(error instanceof Error ? error.message : "Campaign telemetry unavailable");
          timer = window.setTimeout(poll, 2_000);
        }
        return;
      }
      if (cancelled) return;
      const elapsedMs = performance.now() - startedAtMs;
      timer = window.setTimeout(poll, Math.max(0, LIVE_UPDATE_PERIOD_MS - elapsedMs));
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, applyDashboard, campaignRunActive]);

  useEffect(() => {
    if (!activeRunId) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      const startedAtMs = performance.now();
      try {
        const snapshot = await api.loadLiveDashboard(modelRef.current, activeRunId);
        if (cancelled) return;
        const { dashboard, activeRun } = snapshot;
        applyDashboard(dashboard);
        if (!activeRun) {
          setActiveRunId(undefined);
          setNotice("Mission is no longer active · controls unlocked");
          return;
        }
        if (activeRun.status !== "RUNNING") {
          setActiveRunId(undefined);
          setNotice(missionCompletionNotice(
            activeRun.status,
            activeRun.resultMessage,
            activeRun.resultReasonCode,
          ));
          return;
        }
      } catch (error) {
        if (!cancelled) {
          setServiceState("OFFLINE");
          setNotice(error instanceof Error ? error.message : "Mission polling failed");
          timer = window.setTimeout(poll, 2_000);
        }
        return;
      }
      setServiceState("ONLINE");
      const elapsedMs = performance.now() - startedAtMs;
      timer = window.setTimeout(poll, Math.max(0, LIVE_UPDATE_PERIOD_MS - elapsedMs));
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, activeRunId, applyDashboard]);

  useEffect(() => {
    if (!activeExecutionId) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      const startedAtMs = performance.now();
      try {
        const { dashboard } = await api.loadLiveDashboard(modelRef.current);
        if (cancelled) return;
        applyDashboard(dashboard);
        const execution = dashboard.fleetSessions.find((session) => session.id === activeExecutionId);
        if (!execution) {
          setActiveExecutionId(undefined);
          setNotice("Deployment session is no longer available");
          return;
        }
        if (!["SCHEDULED", "PREPARING", "READY", "RUNNING"].includes(execution.runStatus)) {
          setActiveExecutionId(undefined);
          setActiveRunId(undefined);
          setRunFilesLoaded(false);
          void api.runFiles().then((missions) => {
            setRunFileMissions(missions);
            setRunFilesLoaded(true);
            setRunFilesError(undefined);
          }).catch(() => undefined);
          setNotice(missionCompletionNotice(
            execution.runStatus,
            execution.resultMessage,
            execution.resultReasonCode,
          ));
          return;
        }
      } catch (error) {
        if (!cancelled) setNotice(error instanceof Error ? error.message : "Mission polling failed");
      }
      const elapsedMs = performance.now() - startedAtMs;
      timer = window.setTimeout(poll, Math.max(0, LIVE_UPDATE_PERIOD_MS - elapsedMs));
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeExecutionId, api, applyDashboard]);

  useEffect(() => {
    if (
      !selectedVehicle?.commandAuthority
      || activeRunId
      || selectedVehicle.state === "DISCONNECTED"
      || selectedVehicle.state === "FAULT"
      || selectedVehicle.state === "EMERGENCY"
    ) return;
    const timer = window.setInterval(() => {
      void api.renewControl(selectedVehicle.id).catch(() => undefined);
    }, 600);
    return () => window.clearInterval(timer);
  }, [api, activeRunId, selectedVehicle?.commandAuthority, selectedVehicle?.id, selectedVehicle?.state]);

  const executeMissionStart = async (
    preview: MissionPreview,
    confirmLowBatteryRisk = false,
  ) => {
    if (!api || !selectedMission) return;
    setStarting(true);
    try {
      const acknowledgedFindingCodes = confirmLowBatteryRisk
        ? preview.plan.findings
            .filter((finding) => finding.requiresConfirmation)
            .map((finding) => finding.code)
        : [];
      const approval = await api.approveMissionPlan(
        selectedMission.id,
        preview.plan.sha256,
        acknowledgedFindingCodes,
      );
      const result = await api.startMissionFile(
        selectedMission.id,
        executionMode,
        confirmLowBatteryRisk,
        approval,
      );
      setHistoryByVehicle({});
      setTelemetryHistoryByVehicle({});
      setObservedVehicleId(undefined);
      setActiveExecutionId(result.execution_session_id);
      setMissionStart({
        missionId: preview.missionId,
        runId: result.mission_run_id,
        homeBases: missionPreviewHomeBases(preview),
      });
      setMissionPreview(undefined);
      setMissionOpen(false);
      setNotice(`Preparing ${result.member_count} mission ${result.member_count === 1 ? "vehicle" : "vehicles"}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Mission could not start");
    } finally {
      setStarting(false);
    }
  };

  const startMission = async () => {
    let preview = activeMissionPreview;
    if (executionMode === "SIMULATION" && selectedMission && !preview) {
      setStarting(true);
      try {
        preview = await api.previewMission(selectedMission.id);
        setMissionPreview(preview);
        setPlanOverview(preview);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "Mission preview unavailable");
        setStarting(false);
        return;
      }
      setStarting(false);
    }
    if (preview) {
      setMissionStart({
        missionId: preview.missionId,
        homeBases: missionPreviewHomeBases(preview),
      });
    }
    const risk = preview === activeMissionPreview
      ? detectedLowBatteryRisk
      : simulationBatteryStartRisk(
          preview,
          modelRef.current.vehicles,
          selectedVehicle,
          modelRef.current.safetyPolicy?.minimumTakeoffBatteryPercent,
        );
    if (executionMode === "SIMULATION" && risk) {
      setNotice(undefined);
      setLowBatteryConfirmation(risk);
      return;
    }
    if (!preview) {
      setNotice("Mission plan preview is required before approval");
      return;
    }
    void executeMissionStart(preview);
  };

  const startCampaignFromDock = async () => {
    if (!campaignDockCase || campaignRunActive) return;
    setStarting(true);
    try {
      const run = await api.runActiveCampaign(
        campaignExecutionMode,
        campaignSubmissionId,
        campaignPlanningSubmissionId,
      );
      setCampaignRun(run);
      setMissionOpen(false);
      setNotice(`Starting ${humanizeCampaignValue(campaignDockCase.family)} · ${campaignModePresentation.actionLabel} · ${campaignDockCase.drone_count} ${campaignDockCase.drone_count === 1 ? "drone" : "drones"}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Campaign run could not start");
    } finally {
      setStarting(false);
    }
  };

  const cancelCampaign = async () => {
    if (!campaignRunActive || !campaignRun) return;
    try {
      await api.cancelCampaignRun(campaignRun.run_id);
      setNotice("Campaign abort and landing requested");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Campaign cancel request failed");
    }
  };

  const cancelMission = async () => {
    const runId = runningRunId;
    if (!api || !runId) return;
    try {
      await api.cancelMission(runId);
      setNotice("Controlled abort and landing requested");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Cancel request failed";
      if (message.startsWith("unknown mission run:")) {
        setActiveRunId(undefined);
        try {
          applyDashboard(await api.loadDashboard());
        } catch {
          // The stale local run is still cleared even if the follow-up refresh fails.
        }
        setNotice("Mission is no longer active · controls unlocked");
        return;
      }
      setNotice(message);
    }
  };

  const refreshDashboard = useCallback(async () => {
    applyDashboard(await api.loadDashboard());
  }, [api, applyDashboard]);

  const stageMissionPreview = async (mission: MissionOption) => {
    if (runningRunId || campaignRunActive) return;
    const requestId = previewRequestRef.current + 1;
    previewRequestRef.current = requestId;
    autoPreviewMissionIdRef.current = mission.id;
    setObservedVehicleId(undefined);
    setTargetVehicleIds([]);
    setCampaignDockCase(undefined);
    setCampaignPreview(undefined);
    setCampaignRun(undefined);
    setSelectedMissionId(mission.id);
    setMissionPreview(undefined);
    setPlanOverview(undefined);
    setPreviewingMissionId(mission.id);
    try {
      const preview = await api.previewMission(mission.id);
      if (previewRequestRef.current !== requestId) return;
      setMissionPreview(preview);
      setPlanOverview(preview);
      const activeCount = preview.vehicles.filter(
        (vehicle) => vehicle.initialRole === "ACTIVE",
      ).length;
      setNotice(`Previewing ${mission.name} · ${activeCount} ${activeCount === 1 ? "drone" : "drones"}`);
    } catch (error) {
      if (previewRequestRef.current !== requestId) return;
      setNotice(error instanceof Error ? error.message : "Mission preview unavailable");
    } finally {
      if (previewRequestRef.current === requestId) setPreviewingMissionId(undefined);
    }
  };

  const selectActiveCampaignMission = () => {
    if (!activeCampaignCase || runningRunId || campaignRunActive) return;
    previewRequestRef.current += 1;
    autoPreviewMissionIdRef.current = undefined;
    setMissionPreview(undefined);
    setPlanOverview(undefined);
    setObservedVehicleId(undefined);
    setTargetVehicleIds([]);
    setCampaignPreview(undefined);
    setCampaignRun(undefined);
    setCampaignDockCase(activeCampaignCase);
    setExecutionMode("SIMULATION");
    setNotice(`Selected ${humanizeCampaignValue(activeCampaignCase.case_id)}`);
  };

  useEffect(() => {
    if (
      !model.apiConnected
      || !selectedMissionPlanId
      || selectedPlanOverviewMissionId
      || autoPreviewMissionIdRef.current === selectedMissionPlanId
    ) return;
    const missionId = selectedMissionPlanId;
    autoPreviewMissionIdRef.current = missionId;
    let cancelled = false;
    void api.previewMission(missionId).then((preview) => {
      if (cancelled) return;
      setPlanOverview(preview);
      if (!runningRunId) setMissionPreview(preview);
    }).catch((error) => {
      if (!cancelled) setNotice(error instanceof Error ? error.message : "Mission plan unavailable");
    });
    return () => {
      cancelled = true;
    };
  }, [api, model.apiConnected, runningRunId, selectedMissionPlanId, selectedPlanOverviewMissionId]);

  const saveMissionFile = async () => {
    if (!uploadFile) return;
    setUploading(true);
    try {
      const name = uploadName.trim() || uploadFile.name.replace(/\.py$/i, "");
      const mission = await api.uploadMission(name, uploadFile.name, await uploadFile.text());
      await refreshDashboard();
      await stageMissionPreview(mission);
      setUploadFile(undefined);
      setUploadName("");
      setNotice("Mission added");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Mission upload failed");
    } finally {
      setUploading(false);
    }
  };

  const archiveMission = async (missionId: string) => {
    if (activeRunId) return;
    setBusyAction("Archive mission");
    try {
      await api.archiveMission(missionId);
      if (selectedMissionId === missionId) {
        previewRequestRef.current += 1;
        autoPreviewMissionIdRef.current = undefined;
        setSelectedMissionId("");
        setMissionPreview(undefined);
        setPlanOverview(undefined);
      }
      await refreshDashboard();
      setNotice("Mission archived");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Archive failed");
    } finally {
      setBusyAction(undefined);
    }
  };

  const runOperatorAction = async (name: string, action: () => Promise<void>) => {
    setBusyAction(name);
    try {
      await action();
      await refreshDashboard();
      setNotice(name);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `${name} failed`);
    } finally {
      setBusyAction(undefined);
    }
  };

  const resetSimulationPose = async () => {
    if (
      !allCommandTargetsAreFastSim
      || runningRunId
      || campaignRunActive
    ) return;
    const targets = simulationTargetVehicles;
    const actionName = campaignDockCase ? "Redo campaign setup" : "Reposition to home";
    setBusyAction(actionName);
    try {
      await api.resetSimulationFleet(targets.map((vehicle) => vehicle.id));
      setPreflight(undefined);
      setHistoryByVehicle({});
      setTelemetryHistoryByVehicle({});
      setMissionStart(undefined);
      await refreshDashboard();
      if (selectedPlanOverview) {
        const refreshedPreview = await api.previewMission(selectedPlanOverview.missionId);
        setPlanOverview(refreshedPreview);
        if (activeMissionPreview) setMissionPreview(refreshedPreview);
      }
      if (campaignDockCase) setCampaignRun(undefined);
      setNotice(campaignDockCase
        ? "Campaign setup reset to its starting state"
        : targets.length === 1
          ? "Drone repositioned to configured home"
          : `${targets.length} drones repositioned to configured home`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Drone reset failed");
    } finally {
      setBusyAction(undefined);
    }
  };

  const setSimulationBattery = async (requestedPercent: number) => {
    if (
      !allCommandTargetsAreFastSim
      || simulationTargetVehicles.some((vehicle) => !simulationBatteryControlEnabled(
        vehicle,
        Boolean(runningRunId),
        Boolean(busyAction),
      ))
    ) return;
    const targets = simulationTargetVehicles;
    const batteryPercent = Math.max(0, Math.min(100, requestedPercent));
    const actionName = batteryPercent === 100 ? "Recharge battery" : `Set battery to ${batteryPercent}%`;
    setBusyAction(actionName);
    try {
      const results = await Promise.allSettled(
        targets.map((vehicle) => api.setSimulationBattery(vehicle.id, batteryPercent)),
      );
      await refreshDashboard();
      if (selectedPlanOverview) {
        const refreshedPreview = await api.previewMission(selectedPlanOverview.missionId);
        setPlanOverview(refreshedPreview);
        if (activeMissionPreview) setMissionPreview(refreshedPreview);
      }
      setBatteryMenuOpen(false);
      const failedCount = results.filter((result) => result.status === "rejected").length;
      if (failedCount) {
        throw new Error(`Battery update failed for ${failedCount} of ${targets.length} targeted drones`);
      }
      const appliedPercent = results[0]?.status === "fulfilled" ? results[0].value : undefined;
      setNotice(targets.length === 1
        ? appliedPercent === undefined
          ? `Battery set to ${batteryPercent}%`
          : `Battery set to ${appliedPercent.toFixed(1)}%`
        : `${targets.length} drone batteries set to ${batteryPercent.toFixed(1)}%`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Battery update failed");
    } finally {
      setBusyAction(undefined);
    }
  };

  const applyCustomBatteryPercent = () => {
    const value = Number(customBatteryPercent);
    if (!customBatteryPercent.trim() || !Number.isFinite(value) || value < 0 || value > 100) {
      setNotice("Battery percentage must be between 0 and 100");
      return;
    }
    void setSimulationBattery(value);
  };

  const connectVehicle = async () => {
    if (!selectedVehicle) return;
    await runOperatorAction("Vehicle connected", async () => {
      await api.connectVehicle(selectedVehicle.id);
    });
  };

  const changeVehicleTargetSelection = (vehicleId?: string) => {
    if (!vehicleId) {
      setTargetVehicleIds([]);
      setBatteryMenuOpen(false);
      return;
    }
    const selectable = activeMissionPreview
      ? activeMissionPreview.vehicles.some(
        (vehicle) => vehicle.vehicleId === vehicleId && vehicle.existingVehicle,
      )
      : modelRef.current.vehicles.some((vehicle) => vehicle.id === vehicleId);
    if (!selectable) return;
    const next = toggleVehicleSelection(effectiveTargetVehicleIds, vehicleId);
    setTargetVehicleIds(next);
    if (next.includes(vehicleId)) setObservedVehicleId(vehicleId);
    else if (observedVehicleId === vehicleId) setObservedVehicleId(next.at(-1));
    setBatteryMenuOpen(false);
  };

  const claimVehicle = async () => {
    if (!selectedVehicle) return;
    await runOperatorAction("Control claimed", async () => {
      await api.claimControl(selectedVehicle.id);
    });
  };

  const disconnectVehicle = async () => {
    if (!selectedVehicle) return;
    await runOperatorAction("Vehicle disconnected", async () => {
      if (selectedVehicle.commandAuthority) await api.releaseControl(selectedVehicle.id);
      await api.disconnectVehicle(selectedVehicle.id);
      setPreflight(undefined);
    });
  };

  const runPreflight = async () => {
    if (!selectedVehicle) return;
    setBusyAction("Preflight");
    try {
      const report = await api.preflight(selectedVehicle.id, selectedMission?.id);
      setPreflight(report);
      setNotice(report.approved ? "Preflight passed" : "Preflight failed");
      await refreshDashboard();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Preflight failed");
    } finally {
      setBusyAction(undefined);
    }
  };

  const armVehicle = async () => {
    if (!selectedVehicle || !preflight?.approved) return;
    await runOperatorAction("Vehicle armed", () => api.arm(selectedVehicle.id, preflight.reportId));
  };

  const openParameters = async () => {
    if (!selectedVehicle) return;
    setParametersOpen(true);
    try {
      setEngineeringParameters(await api.parameters(selectedVehicle.id));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Parameters unavailable");
    }
  };

  const writeParameter = async (parameter: ParameterView, value: number) => {
    if (!selectedVehicle) return;
    await runOperatorAction("Parameter updated", async () => {
      await api.writeParameter(selectedVehicle.id, parameter.name, value);
      setEngineeringParameters(await api.parameters(selectedVehicle.id));
      if (parameterSnapshotId) {
        setParameterDiffCount(await api.parameterDiffCount(selectedVehicle.id, parameterSnapshotId));
      }
    });
  };

  const snapshotParameters = async () => {
    if (!selectedVehicle) return;
    await runOperatorAction("Baseline saved", async () => {
      const snapshotId = await api.snapshotParameters(selectedVehicle.id);
      setParameterSnapshotId(snapshotId);
      setParameterDiffCount(0);
    });
  };

  const restoreParameters = async () => {
    if (!selectedVehicle || !parameterSnapshotId) return;
    await runOperatorAction("Baseline restored", async () => {
      await api.restoreParameters(selectedVehicle.id, parameterSnapshotId);
      setEngineeringParameters(await api.parameters(selectedVehicle.id));
      setParameterDiffCount(0);
    });
  };

  const confirmSafetyAction = async () => {
    if (!selectedVehicle || !safetyAction) return;
    const action = safetyAction;
    setSafetyAction(null);
    await runOperatorAction(
      action === "emergency" ? "Emergency motor cutoff" : "Abort and land",
      () => action === "emergency" ? api.emergencyStop(selectedVehicle.id) : api.abort(selectedVehicle.id),
    );
  };

  const loadRunHistory = async () => {
    if (runHistoryLoading) return;
    setRunHistoryLoading(true);
    try {
      setRunHistory(await api.runHistory());
    } catch (error) {
      const message = error instanceof Error ? error.message : "Run history unavailable";
      setNotice(message);
    } finally {
      setRunHistoryLoading(false);
    }
  };

  const loadRunFiles = async () => {
    if (runFilesLoading) return;
    setRunFilesLoading(true);
    setRunFilesError(undefined);
    try {
      setRunFileMissions(await api.runFiles());
      setRunFilesLoaded(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Run files unavailable";
      setRunFilesError(message);
      setNotice(message);
    } finally {
      setRunFilesLoading(false);
    }
  };

  const deleteRunFileMission = async (missionExecutionId: string) => {
    setDeletingRunFileMissionId(missionExecutionId);
    try {
      await api.deleteRunFileMission(missionExecutionId);
      setRunFileMissions((missions) => missions.filter(
        (item) => item.missionExecutionId !== missionExecutionId,
      ));
      setRunHistory((history) => history.filter((run) => run.missionExecutionId !== missionExecutionId));
      setNotice("Run files and archive folder deleted");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to delete run files";
      setRunFilesError(message);
      setNotice(message);
    } finally {
      setDeletingRunFileMissionId(undefined);
    }
  };

  const openReplay = async (runId: string) => {
    setBusyAction("Open replay");
    try {
      setReplay(await api.openReplay(runId));
      setNotice("Command-free replay opened");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Replay unavailable");
    } finally {
      setBusyAction(undefined);
    }
  };

  const stepReplay = async () => {
    if (!replay) return;
    setBusyAction("Step replay");
    try {
      setReplay(await api.stepReplay(replay.runId));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Replay step failed");
    } finally {
      setBusyAction(undefined);
    }
  };

  const toggleMission = () => {
    const next = !missionOpen;
    setMissionOpen(next);
    if (next) setTelemetryOpen(false);
  };

  return (
    <main className={`control-center ${telemetryOpen && selectedVehicle?.telemetry ? "flight-expanded" : ""}`}>
      <a className="skip-link" href="#room-scene">Skip to simulation</a>
      <div className="identity-capsule" aria-label="Aerium Control">
        <div className="brand">
          <span className="brand-mark"><Hexagon size={20} strokeWidth={1.8} /></span>
          <strong>AERIUM</strong>
        </div>
        {model.mode ? <ModeBadge mode={model.mode} label={model.mode === "SIM" ? "SIM" : model.mode} /> : null}
      </div>

      <div className="vehicle-controls">
        {sceneVehicleCount ? (
          <div className="vehicle-capsule" aria-label="Command targets">
            <span className={`vehicle-state-dot ${singleTargetVehicle ? vehicleTone(singleTargetVehicle) : ""}`} />
            <strong>{effectiveTargetVehicleIds.length === 0
              ? "All drones"
              : effectiveTargetVehicleIds.length === 1
                ? singleTargetName ?? "1 drone selected"
                : `${effectiveTargetVehicleIds.length} drones selected`}</strong>
            {effectiveTargetVehicleIds.length === 0 ? (
              <small className="target-scope">{sceneVehicleCount} in scene</small>
            ) : effectiveTargetVehicleIds.length > 1 ? (
              <small className="target-scope">Selection</small>
            ) : selectedVehicleException ? <small>{selectedVehicleException}</small> : null}
          </div>
        ) : serviceState === "OFFLINE" ? <span className="service-exception">Offline</span> : null}
        {model.apiConnected ? (
          <button className="engineering-fab" type="button" aria-label="Engineering" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((open) => !open)}>
            <Settings size={17} />
          </button>
        ) : null}
      </div>

      <div className="app-shell">
        <section className="workspace" id="mission-workspace" tabIndex={-1}>
          <RoomScene
            model={rendererModel}
            plannedPath={plannedPath}
            homeBases={homeBases}
            missionPreview={campaignScenePreview(activeMissionPreview, campaignRun)}
            historicalPath={historicalPath}
            selectedVehicleIds={effectiveTargetVehicleIds}
            onVehicleSelectionChange={changeVehicleTargetSelection}
            onDisplayTiming={campaignRunActive ? (event) => {
              void api.recordBrowserTiming(event).catch(() => undefined);
            } : undefined}
            onSceneCapture={campaignRun?.status === "RUNNING" ? captureCampaignScene : undefined}
            onSceneCaptureError={setNotice}
            twinOverlay={twinSceneOverlay}
          />
        </section>

        {referencePlanOverview || (!campaignDockCase && fleet?.missionDerived && fleet.vehicles.length > 0) ? (
          <DeploymentSummary
            key={referencePlanOverview?.missionId ?? fleet?.id}
            fleet={!campaignDockCase && fleet?.missionDerived ? fleet : undefined}
            preview={referencePlanOverview}
            vehicles={model.vehicles}
            selectedVehicleIds={effectiveTargetVehicleIds}
            onSelect={changeVehicleTargetSelection}
          />
        ) : null}

        <aside className={missionOpen ? "mission-panel" : "mission-panel is-closed"} aria-label="Mission setup" aria-hidden={!missionOpen}>
            <div className="panel-heading">
              <h1 id="mission-title" tabIndex={-1}>Mission</h1>
              <button className="panel-close" type="button" aria-label="Close mission setup" onClick={() => setMissionOpen(false)}><ChevronDown size={17} /></button>
            </div>
            {!model.apiConnected ? (
              <EmptyMission state={serviceState} onRetry={() => void attachLocalService()} />
            ) : (
              <>
                <div className="execution-switch" role="group" aria-label="Execution mode">
                  <button type="button" className={executionMode === "SIMULATION" ? "is-selected" : ""} onClick={() => setExecutionMode("SIMULATION")}>Simulation</button>
                  <button type="button" className={executionMode === "TWIN" ? "is-selected" : ""} disabled={!twinAvailable} title={!twinAvailable ? "Real vehicle adapter required" : undefined} onClick={() => setExecutionMode("TWIN")}>Digital twin</button>
                </div>

                <CampaignLab
                  api={api}
                  onNotice={setNotice}
                  onActiveCaseChange={handleActiveCampaignCaseChange}
                  onCampaignRunChange={handleCampaignRunChange}
                  onExecutionModeChange={handleCampaignExecutionModeChange}
                  onSubmissionChange={handleCampaignSubmissionChange}
                  onPlanningSubmissionChange={handleCampaignPlanningSubmissionChange}
                />
                {activeCampaignCase ? (
                  <div className="campaign-active-mission">
                    <button
                      type="button"
                      className={campaignDockCase ? "mission-card is-selected" : "mission-card"}
                      disabled={Boolean(runningRunId || campaignRunActive)}
                      onClick={selectActiveCampaignMission}
                    >
                      <FileCode2 size={15} />
                      <span>
                        <strong>{humanizeCampaignValue(activeCampaignCase.case_id)}</strong>
                        <small>{campaignMissionFilename(activeCampaignCase)}</small>
                      </span>
                      {campaignDockCase ? <Check size={13} /> : null}
                    </button>
                  </div>
                ) : null}

                <div className="mission-source-divider" role="separator" />

                <div className="mission-upload">
                  <input
                    id="mission-file"
                    className="file-input"
                    type="file"
                    accept=".py,text/x-python"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      setUploadFile(file);
                      setUploadName(file?.name.replace(/\.py$/i, "") ?? "");
                      event.target.value = "";
                    }}
                  />
                  <label className="upload-button" htmlFor="mission-file"><Upload size={14} />Add Python</label>
                  {uploadFile ? (
                    <div className="upload-editor">
                      <input aria-label="Mission name" value={uploadName} onChange={(event) => setUploadName(event.target.value)} />
                      <button type="button" disabled={uploading} onClick={() => void saveMissionFile()}>{uploading ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}</button>
                    </div>
                  ) : null}
                </div>

                <div className="mission-library" aria-label="Python missions">
                  {model.missions.map((mission) => (
                    <div className="mission-card-row" key={mission.id}>
                      <button
                        type="button"
                        className={!campaignDockCase && mission.id === effectiveMissionId ? "mission-card is-selected" : "mission-card"}
                        disabled={Boolean(runningRunId || campaignRunActive)}
                        onClick={() => void stageMissionPreview(mission)}
                      >
                        {previewingMissionId === mission.id ? <LoaderCircle className="spin" size={15} /> : <FileCode2 size={15} />}
                        <span><strong>{mission.name}</strong><small>{mission.sourceFilename}</small></span>
                        {!campaignDockCase && mission.id === effectiveMissionId ? <Check size={13} /> : null}
                      </button>
                      <button className="mission-archive" type="button" aria-label={`Archive ${mission.name}`} disabled={Boolean(runningRunId || campaignRunActive || busyAction)} onClick={() => void archiveMission(mission.id)}><Trash2 size={13} /></button>
                    </div>
                  ))}
                  {!model.missions.length ? <span className="mission-empty">NO MISSIONS YET</span> : null}
                </div>

              </>
            )}
        </aside>

        <section className="mission-dock" aria-label="Mission controls">
          <button className="mission-dock-summary" type="button" aria-expanded={missionOpen} onClick={toggleMission}>
            <Command size={17} />
            <span>
              <strong>{campaignDockCase ? humanizeCampaignValue(campaignDockCase.family) : selectedMission?.name ?? "Mission"}</strong>
              {campaignDockCase ? (
                <small>{campaignRunActive ? sentenceCase(campaignRun?.status ?? "Running") : `Campaign · ${campaignDockCase.drone_count}D · ${campaignModePresentation.label}`}</small>
              ) : runningRunId ? <small>{sentenceCase(model.latestRun?.phase ?? "Running")}</small> : null}
            </span>
            {missionOpen ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
          </button>
          {runningRunId || campaignRunActive ? (
            <button className="dock-abort-button" type="button" onClick={campaignRunActive ? cancelCampaign : cancelMission}><Square size={13} fill="currentColor" />Abort and land</button>
          ) : (
            <button
              className={`dock-run-button ${campaignDockCase ? campaignModePresentation.buttonClassName : ""}`}
              type="button"
              aria-label={campaignDockCase ? `Run active campaign ${campaignModePresentation.actionLabel}` : executionMode === "TWIN" ? "Run digital twin" : "Run simulation"}
              disabled={
                (!campaignDockCase && !selectedMission)
                || starting
                || Boolean(runningRunId)
                || Boolean(campaignRunActive)
                || (!campaignDockCase && activeMissionPreview?.plan.status === "BLOCKED")
                || (!campaignDockCase && executionMode === "TWIN" && !twinAvailable)
              }
              onClick={() => void (campaignDockCase ? startCampaignFromDock() : startMission())}
            >
              {starting ? <LoaderCircle className="spin" size={16} /> : <Play size={15} fill="currentColor" />}
            </button>
          )}
        </section>

        <RunFilesControl
          missions={runFileMissions}
          loaded={runFilesLoaded}
          loading={runFilesLoading}
          error={runFilesError}
          onLoad={() => void loadRunFiles()}
          onDelete={(mission) => void deleteRunFileMission(mission.missionExecutionId)}
          deletingMissionId={deletingRunFileMissionId}
        />

        {allCommandTargetsAreFastSim ? (
          <div className="flight-quick-actions" aria-label="Simulation quick actions">
            <div className="mission-quick-pill home-quick-pill">
              <button
                type="button"
                aria-label={campaignDockCase
                  ? "Redo campaign setup"
                  : effectiveTargetVehicleIds.length === 0
                    ? `Reposition all ${simulationTargetVehicles.length} ${simulationTargetVehicles.length === 1 ? "drone" : "drones"} to home`
                    : simulationTargetVehicles.length === 1
                      ? "Reposition drone to home"
                      : `Reposition ${simulationTargetVehicles.length} selected drones to home`}
                disabled={simulationQuickActionsDisabled}
                title={simulationQuickActionHint}
                onClick={() => void resetSimulationPose()}
              >
                {busyAction === (campaignDockCase ? "Redo campaign setup" : "Reposition to home") ? <LoaderCircle className="spin" size={17} /> : <RotateCcw size={17} />}
              </button>
            </div>
            <div className="battery-quick-control" ref={batteryControlRef}>
              <div className="mission-quick-pill battery-quick-pill">
                <button
                  className="battery-recharge-button"
                  type="button"
                  aria-label={effectiveTargetVehicleIds.length === 0
                    ? `Recharge all ${simulationTargetVehicles.length} ${simulationTargetVehicles.length === 1 ? "drone" : "drones"} to 100%`
                    : simulationTargetVehicles.length === 1
                      ? "Recharge battery to 100%"
                      : `Recharge ${simulationTargetVehicles.length} selected drones to 100%`}
                  disabled={simulationBatteryDisabled}
                  title={simulationBatteryHint}
                  onClick={() => void setSimulationBattery(100)}
                >
                  {busyAction === "Recharge battery" ? <LoaderCircle className="spin" size={17} /> : <BatteryCharging size={17} />}
                </button>
                <button
                  className="battery-menu-toggle"
                  type="button"
                  aria-label="Choose battery level"
                  aria-expanded={batteryMenuOpen}
                  disabled={simulationBatteryDisabled}
                  title={simulationBatteryHint}
                  onClick={() => setBatteryMenuOpen((open) => !open)}
                >
                  <ChevronUp size={14} />
                </button>
              </div>
              {batteryMenuOpen ? (
                <div className="battery-level-popover" role="dialog" aria-label="Battery level">
                  <span>BATTERY LEVEL</span>
                  <div className="battery-level-presets">
                    {BATTERY_LEVEL_PRESETS.map((percent) => (
                      <button
                        key={percent}
                        type="button"
                        disabled={Boolean(busyAction)}
                        onClick={() => void setSimulationBattery(percent)}
                      >
                        {percent}%
                      </button>
                    ))}
                  </div>
                  <form onSubmit={(event) => { event.preventDefault(); applyCustomBatteryPercent(); }}>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      inputMode="decimal"
                      aria-label="Custom battery percentage"
                      value={customBatteryPercent}
                      onChange={(event) => setCustomBatteryPercent(event.target.value)}
                    />
                    <button type="submit" disabled={Boolean(busyAction)}>Set</button>
                  </form>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        <FlightReadout
          model={model}
          vehicle={selectedVehicle}
          twin={model.twins.find((item) => item.observedVehicleId === selectedVehicle?.id)}
          samples={selectedVehicle ? telemetryHistoryByVehicle[selectedVehicle.id]?.points ?? [] : []}
          expanded={telemetryOpen}
          onToggle={() => {
            const next = !telemetryOpen;
            setTelemetryOpen(next);
            if (next) setMissionOpen(false);
          }}
          onLoadTwinTimeline={loadTwinTimeline}
          onTwinSceneOverlay={setTwinSceneOverlay}
        />
      </div>

      <EngineeringDrawer
        open={advancedOpen}
        model={model}
        vehicle={selectedVehicle}
        busyAction={busyAction}
        preflight={preflight}
        parameters={engineeringParameters}
        parametersOpen={parametersOpen}
        parameterSnapshotId={parameterSnapshotId}
        parameterDiffCount={parameterDiffCount}
        runHistory={runHistory}
        replay={replay}
        missionRunning={Boolean(runningRunId)}
        onClose={() => setAdvancedOpen(false)}
        onConnect={connectVehicle}
        onClaim={claimVehicle}
        onDisconnect={disconnectVehicle}
        onPreflight={runPreflight}
        onArm={armVehicle}
        onDisarm={() => selectedVehicle && runOperatorAction("Vehicle disarmed", () => api.disarm(selectedVehicle.id))}
        onTakeoff={() => selectedVehicle && runOperatorAction("Takeoff complete", () => api.takeoff(selectedVehicle.id))}
        onHold={() => selectedVehicle && runOperatorAction("Position held", () => api.hold(selectedVehicle.id))}
        onMove={(movement) => selectedVehicle && runOperatorAction("Move complete", () => api.moveRelative(selectedVehicle.id, movement))}
        onLand={() => selectedVehicle && runOperatorAction("Landing complete", () => api.land(selectedVehicle.id))}
        onAbort={() => setSafetyAction("abort")}
        onEmergency={() => setSafetyAction("emergency")}
        onOpenParameters={openParameters}
        onDeleteRunHistory={(run) => void deleteRunFileMission(run.missionExecutionId)}
        onWriteParameter={writeParameter}
        onSnapshotParameters={snapshotParameters}
        onRestoreParameters={restoreParameters}
        onLoadRunHistory={loadRunHistory}
        onOpenReplay={openReplay}
        onStepReplay={stepReplay}
        onCloseReplay={() => setReplay(undefined)}
      />
      {lowBatteryConfirmation ? (
        <LowBatterySimulationDialog
          batteryPercent={lowBatteryConfirmation.batteryPercent}
          minimumPercent={lowBatteryConfirmation.minimumPercent}
          minimumKind={lowBatteryConfirmation.minimumKind}
          vehicleId={lowBatteryConfirmation.vehicleId}
          affectedVehicleCount={lowBatteryConfirmation.affectedVehicleCount}
          criticalPercent={model.safetyPolicy?.criticalBatteryPercent ?? 10}
          starting={starting}
          onClose={() => setLowBatteryConfirmation(undefined)}
          onConfirm={() => {
            setLowBatteryConfirmation(undefined);
            if (activeMissionPreview) void executeMissionStart(activeMissionPreview, true);
          }}
        />
      ) : null}
      <SafetyDialog kind={safetyAction} vehicle={selectedVehicle} onClose={() => setSafetyAction(null)} onConfirm={confirmSafetyAction} />
      {notice ? <Toast message={notice} onClose={dismissNotice} /> : null}
    </main>
  );
}

export function MissionPlanReview({
  preview,
  vehicles = [],
}: {
  preview: MissionPreview;
  vehicles?: VehicleView[];
}) {
  const activeVehicles = preview.vehicles.filter((vehicle) => vehicle.initialRole === "ACTIVE");
  const totalDistanceM = preview.plan.routes.reduce((total, route) => total + route.lengthM, 0);
  const totalEnergyPercent = preview.plan.routes.reduce((total, route) => total + route.energyPercent, 0);
  const totalDurationS = preview.plan.routes.reduce((duration, route) => Math.max(duration, route.durationS), 0);
  const blocking = preview.plan.findings.filter((finding) => finding.severity === "BLOCKER");
  const confirmable = preview.plan.findings.filter(
    (finding) => finding.requiresConfirmation && finding.severity !== "BLOCKER",
  );
  const informational = preview.plan.findings.filter(
    (finding) => finding.severity !== "BLOCKER" && !finding.requiresConfirmation,
  );
  return (
    <section className={`mission-plan-review is-${preview.plan.status.toLowerCase()}`} aria-label="Operational mission plan" aria-live="polite">
      <div className="plan-overview-totals" aria-label="Plan totals">
        <PlanMetric label="Drones" value={String(activeVehicles.length)} />
        <PlanMetric label="Distance" value={`${totalDistanceM.toFixed(2)} m`} />
        <PlanMetric label="Duration" value={`${totalDurationS.toFixed(1)} s`} />
        <PlanMetric label="Fleet energy" value={`${totalEnergyPercent.toFixed(1)}%`} tone="energy" />
      </div>
      <div className="plan-routes" aria-label="Planned drone routes">
        {preview.vehicles.map((plannedVehicle) => {
          const route = preview.plan.routes.find((item) => item.roleId === plannedVehicle.roleId);
          const liveVehicle = vehicles.find((item) => item.id === plannedVehicle.vehicleId);
          const batteryPercent = liveVehicle?.telemetry?.batteryPercent ?? plannedVehicle.batteryPercent;
          const energyPercent = route?.energyPercent ?? 0;
          const projectedBattery = batteryPercent === undefined
            ? undefined
            : Math.max(0, batteryPercent - energyPercent);
          return (
            <article className="plan-route" key={plannedVehicle.roleId}>
              <div className="plan-route-heading">
                <strong>{plannedVehicle.displayName}</strong>
                <b>{route ? sentenceCase(route.status) : sentenceCase(plannedVehicle.initialRole)}</b>
              </div>
              <div className="plan-route-stats">
                <span><small>Distance</small><strong>{route ? `${route.lengthM.toFixed(2)} m` : "—"}</strong></span>
                <span><small>Duration</small><strong>{route ? `${route.durationS.toFixed(1)} s` : "—"}</strong></span>
                <span><small>Waypoints</small><strong>{route?.waypointCount ?? "—"}</strong></span>
              </div>
              <div className="plan-energy">
                <span>
                  <small>Planned energy</small>
                  <strong>{route ? `${energyPercent.toFixed(1)}%` : "Not estimated"}</strong>
                </span>
                <i className="plan-energy-track" role="img" aria-label={route ? `${energyPercent.toFixed(1)} percent planned energy` : "Planned energy unavailable"}>
                  <b style={{ width: `${Math.max(0, Math.min(100, energyPercent))}%` }} />
                </i>
                {projectedBattery !== undefined ? (
                  <em>Projected battery · {projectedBattery.toFixed(0)}%</em>
                ) : null}
              </div>
              <div className="plan-positions">
                <PlanPosition label="Start" position={plannedVehicle.start} />
                <PlanPosition label="Home" position={plannedVehicle.home} />
              </div>
            </article>
          );
        })}
      </div>
      <PlanFindingGroup title="Blockers" findings={blocking} />
      <PlanFindingGroup title="Confirm before Play" findings={confirmable} />
      <PlanFindingGroup title="Information and limitations" findings={informational} />
    </section>
  );
}

function PlanMetric({ label, value, tone }: { label: string; value: string; tone?: "energy" }) {
  return (
    <span className={tone ? `plan-metric is-${tone}` : "plan-metric"}>
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function PlanPosition({ label, position }: { label: string; position: Vec3 }) {
  return (
    <span className="plan-position">
      <small><span>{label}</span><em>m</em></small>
      <span className="plan-position-values">
        <span><i className="axis-x">X</i><b>{position.x.toFixed(2)}</b></span>
        <span><i className="axis-y">Y</i><b>{position.y.toFixed(2)}</b></span>
        <span><i className="axis-z">Z</i><b>{position.z.toFixed(2)}</b></span>
      </span>
    </span>
  );
}

function PlanFindingGroup({
  title,
  findings,
}: {
  title: string;
  findings: MissionPreview["plan"]["findings"];
}) {
  if (!findings.length) return null;
  return (
    <div className="mission-plan-findings">
      <strong>{title}</strong>
      <ul>
        {findings.map((finding) => (
          <li key={`${title}-${finding.code}-${finding.roleId ?? "mission"}`}>
            <span>{finding.code}{finding.roleId ? ` · ${finding.roleId}` : ""}</span>
            <p>{finding.message}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DeploymentSummary({
  fleet,
  preview,
  vehicles,
  selectedVehicleIds,
  onSelect,
}: {
  fleet?: FleetSessionView;
  preview?: MissionPreview;
  vehicles: VehicleView[];
  selectedVehicleIds: string[];
  onSelect: (vehicleId: string) => void;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const memberRows = preview?.vehicles.length
    ? preview.vehicles.map((plannedVehicle) => ({
        id: plannedVehicle.vehicleId,
        displayName: plannedVehicle.displayName,
        roleId: plannedVehicle.roleId,
        initialRole: plannedVehicle.initialRole,
        plannedBatteryPercent: plannedVehicle.batteryPercent,
        existingVehicle: plannedVehicle.existingVehicle,
        fleetMember: fleet?.vehicles.find((member) => member.id === plannedVehicle.vehicleId),
      }))
    : (fleet?.vehicles ?? []).map((fleetMember) => ({
        id: fleetMember.id,
        displayName: fleetMember.id,
        roleId: fleetMember.missionRole,
        initialRole: fleetMember.missionRole,
        plannedBatteryPercent: undefined,
        existingVehicle: true,
        fleetMember,
      }));
  const status = fleet?.runStatus ?? preview?.plan.status ?? "PLANNED";
  return (
    <section className="fleet-panel deployment-summary" aria-label="Mission deployment status">
      <header className="deployment-heading">
        <button
          type="button"
          aria-expanded={detailsOpen}
          aria-label={detailsOpen ? "Collapse mission deployment details" : "Expand mission deployment details"}
          onClick={() => setDetailsOpen((open) => !open)}
        >
          <span>
            <strong>Mission deployment</strong>
          </span>
          <span className={`deployment-run-state state-${status.toLowerCase()}`}>
            {sentenceCase(status)}
          </span>
          <ChevronDown className={detailsOpen ? "is-open" : ""} size={15} />
        </button>
      </header>
      {detailsOpen && fleet?.minimumSeparationM !== undefined ? (
        <DeploymentSeparation fleet={fleet} />
      ) : null}
      <div className="fleet-vehicles">
        {memberRows.map((member) => {
          const vehicle = vehicles.find((item) => item.id === member.id);
          const ready = member.fleetMember
            ? member.fleetMember.preflightApproved || member.fleetMember.readinessReason === "TERMINAL_SNAPSHOT"
            : true;
          const selected = selectedVehicleIds.includes(member.id);
          const batteryPercent = vehicle?.telemetry?.batteryPercent ?? member.plannedBatteryPercent;
          const battery = batteryPercent === undefined
            ? "—"
            : `${batteryPercent.toFixed(0)}%`;
          const coordinationState = fleet?.vehicleStates[member.id]
            ?? member.fleetMember?.missionRole
            ?? member.initialRole;
          const selectable = Boolean(vehicle || member.existingVehicle);
          return (
            <button
              className={`deployment-member ${selected ? "is-selected" : ""}`}
              type="button"
              key={member.id}
              aria-pressed={selected}
              aria-label={`Toggle ${member.id} command selection · battery ${battery}`}
              disabled={!selectable}
              title={!selectable ? "This planned drone is not yet provisioned in the scene" : undefined}
              onClick={() => onSelect(member.id)}
            >
              <span className={`vehicle-state-dot ${member.fleetMember?.faultReason ? "is-critical" : ready ? "is-normal" : "is-warning"}`} />
              <span className="deployment-member-copy">
                <strong>{member.displayName}</strong>
                <small>{member.roleId} · {sentenceCase(coordinationState)}</small>
              </span>
              <b>{battery}</b>
            </button>
          );
        })}
      </div>
      {detailsOpen ? (
        <div className="deployment-expanded">
          {preview ? <MissionPlanReview preview={preview} vehicles={vehicles} /> : null}
          {fleet ? <DeploymentCoordination fleet={fleet} /> : null}
        </div>
      ) : null}
    </section>
  );
}

function DeploymentCoordination({ fleet }: { fleet: FleetSessionView }) {
  const reservations = fleet.docks.flatMap((dock) => dock.reservations.map((reservation) => ({
    dockId: dock.id,
    reservation,
  })));
  if (!fleet.handovers.length && !reservations.length) return null;
  return (
    <div className="deployment-coordination" aria-label="Fleet coordination evidence">
      {fleet.handovers.map((handover) => (
        <div className="deployment-handover" key={handover.id}>
          <span>Handover · {sentenceCase(handover.phase)}</span>
          <strong>
            {handover.outgoingVehicleId} → {handover.incomingVehicleId ?? "no reserve"}
          </strong>
          <small>
            {handover.taskId}
            {handover.incomingLeaseGeneration !== undefined
              ? ` · generation ${handover.incomingLeaseGeneration}`
              : ""}
            {handover.takeoverConfirmed ? " · takeover confirmed" : ""}
          </small>
        </div>
      ))}
      {reservations.map(({ dockId, reservation }) => (
        <div className="deployment-evidence-row" key={`${dockId}-${reservation.vehicleId}`}>
          <span>{dockId} · {reservation.vehicleId}</span>
          <strong>{sentenceCase(reservation.state)}</strong>
        </div>
      ))}
    </div>
  );
}

function DeploymentSeparation({ fleet }: { fleet: FleetSessionView }) {
  const minimumSeparationM = fleet.minimumSeparationM;
  if (minimumSeparationM === undefined) return null;
  const separationMaximum = Math.max(fleet.warningSeparationM * 1.5, minimumSeparationM, 0.01);
  const separationPercent = Math.max(0, Math.min(100, minimumSeparationM / separationMaximum * 100));
  const separationTone = minimumSeparationM <= fleet.criticalSeparationM
    ? "critical"
    : minimumSeparationM <= fleet.warningSeparationM
      ? "warning"
      : "normal";
  return (
    <div className={`deployment-separation is-${separationTone}`}>
      <span>
        <small>Minimum separation</small>
        <strong>{minimumSeparationM.toFixed(2)} m</strong>
      </span>
      <i role="img" aria-label={`${minimumSeparationM.toFixed(2)} meters minimum separation`}>
        <b style={{ width: `${separationPercent}%` }} />
      </i>
      <em>Critical {fleet.criticalSeparationM.toFixed(2)} m · warning {fleet.warningSeparationM.toFixed(2)} m</em>
    </div>
  );
}

export function withObservationFocus(model: DashboardModel, vehicleId?: string): DashboardModel {
  if (!vehicleId || !model.vehicles.some((vehicle) => vehicle.id === vehicleId)) return model;
  return {
    ...model,
    selectedVehicleId: vehicleId,
    vehicles: model.vehicles.map((vehicle) => ({
      ...vehicle,
      selected: vehicle.id === vehicleId,
    })),
  };
}

export function toggleVehicleSelection(selectedVehicleIds: string[], vehicleId: string): string[] {
  return selectedVehicleIds.includes(vehicleId)
    ? selectedVehicleIds.filter((selectedId) => selectedId !== vehicleId)
    : [...selectedVehicleIds, vehicleId];
}

export function vehiclesForTargetSelection<T extends { id: string }>(
  vehicles: T[],
  selectedVehicleIds: string[],
): T[] {
  if (!selectedVehicleIds.length) return vehicles;
  const selectedIds = new Set(selectedVehicleIds);
  return vehicles.filter((vehicle) => selectedIds.has(vehicle.id));
}

export function withVehicleTargetSelection(
  model: DashboardModel,
  selectedVehicleIds: string[],
): DashboardModel {
  const availableIds = new Set(model.vehicles.map((vehicle) => vehicle.id));
  const selectedIds = new Set(selectedVehicleIds.filter((vehicleId) => availableIds.has(vehicleId)));
  const soleSelectedVehicleId = selectedIds.size === 1 ? [...selectedIds][0] : undefined;
  return {
    ...model,
    selectedVehicleId: soleSelectedVehicleId,
    vehicles: model.vehicles.map((vehicle) => ({
      ...vehicle,
      selected: selectedIds.has(vehicle.id),
    })),
  };
}

function latestMissionDeployment(sessions: FleetSessionView[]) {
  return sessions
    .filter((session) => session.missionDerived)
    .reduce<FleetSessionView | undefined>(
      (latest, session) => !latest || session.createdAtMonotonicS > latest.createdAtMonotonicS
        ? session
        : latest,
      undefined,
    );
}

function EmptyMission({ state, onRetry }: { state: ServiceState; onRetry: () => void }) {
  return (
    <div className="empty-mission">
      <button type="button" disabled={state === "ATTACHING"} onClick={onRetry}>{state === "ATTACHING" ? <LoaderCircle className="spin" size={14} /> : <RotateCcw size={14} />} {state === "ATTACHING" ? "Starting" : "Retry"}</button>
    </div>
  );
}

function Fact({ label, value, icon }: { label: string; value: string; icon?: ReactNode }) {
  return <div className="fact"><span>{icon}{label}</span><strong>{value}</strong></div>;
}

function EngineeringDrawer({
  open,
  model,
  vehicle,
  busyAction,
  preflight,
  parameters,
  parametersOpen,
  parameterSnapshotId,
  parameterDiffCount,
  runHistory,
  replay,
  missionRunning,
  onClose,
  onConnect,
  onClaim,
  onDisconnect,
  onPreflight,
  onArm,
  onDisarm,
  onTakeoff,
  onHold,
  onMove,
  onLand,
  onAbort,
  onEmergency,
  onOpenParameters,
  onDeleteRunHistory,
  onWriteParameter,
  onSnapshotParameters,
  onRestoreParameters,
  onLoadRunHistory,
  onOpenReplay,
  onStepReplay,
  onCloseReplay,
}: {
  open: boolean;
  model: DashboardModel;
  vehicle?: VehicleView;
  busyAction?: string;
  preflight?: PreflightReportView;
  parameters: ParameterView[];
  parametersOpen: boolean;
  parameterSnapshotId?: string;
  parameterDiffCount?: number;
  runHistory: RunHistoryView[];
  replay?: ReplayView;
  missionRunning: boolean;
  onClose: () => void;
  onConnect: () => void;
  onClaim: () => void;
  onDisconnect: () => void;
  onPreflight: () => void;
  onArm: () => void;
  onDisarm: () => void;
  onTakeoff: () => void;
  onHold: () => void;
  onMove: (movement: { x_m?: number; y_m?: number; z_m?: number; duration_s?: number }) => void;
  onLand: () => void;
  onAbort: () => void;
  onEmergency: () => void;
  onOpenParameters: () => void;
  onDeleteRunHistory: (run: RunHistoryView) => void;
  onWriteParameter: (parameter: ParameterView, value: number) => void;
  onSnapshotParameters: () => void;
  onRestoreParameters: () => void;
  onLoadRunHistory: () => void;
  onOpenReplay: (runId: string) => void;
  onStepReplay: () => void;
  onCloseReplay: () => void;
}) {
  if (!open) return null;
  const connected = vehicle && vehicle.state !== "DISCONNECTED";
  const ready = vehicle?.state === "READY";
  const armed = vehicle?.armed === true;
  const flying = vehicle?.flying === true || vehicle?.state === "FLYING";
  return (
    <div className="engineering-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="engineering-drawer" role="dialog" aria-modal="true" aria-labelledby="engineering-title">
        <header><div><span className="eyebrow">ADVANCED</span><h2 id="engineering-title">Engineering</h2></div><button type="button" aria-label="Close engineering" onClick={onClose}><X size={17} /></button></header>
        {!vehicle ? <div className="engineering-empty">No vehicle</div> : (
          <>
            <section className="engineering-section">
              <h3>Target</h3>
              <Fact label="Vehicle" value={`${vehicle.name} · ${vehicle.id}`} />
              <Fact label="Mode" value={model.mode ?? "UNAVAILABLE"} />
              <Fact label="State" value={vehicle.state} />
              {vehicle.firmwareVersion ? <Fact label="Firmware" value={vehicle.firmwareVersion} /> : null}
              {vehicle.radioUri ? <Fact label="Radio URI" value={vehicle.radioUri} /> : null}
            </section>

            <section className="engineering-section action-stack">
              <h3>Authority</h3>
              {!connected ? <button className="button-primary" type="button" disabled={Boolean(busyAction)} onClick={onConnect}><Radio size={14} />Connect vehicle</button> : null}
              {connected && !vehicle.commandAuthority ? <button className="button-primary" type="button" disabled={Boolean(busyAction)} onClick={onClaim}>Claim control</button> : null}
              {connected && vehicle.commandAuthority ? <button className="button-secondary" type="button" disabled={!ready || armed || Boolean(busyAction)} title={!ready || armed ? "Land and disarm first" : undefined} onClick={onDisconnect}><Unplug size={14} />Disconnect vehicle</button> : null}
            </section>

            {vehicle.commandAuthority ? (
              <section className="engineering-section action-stack">
                <h3>Flight</h3>
                {!armed ? <button type="button" className="button-secondary" disabled={!ready || Boolean(busyAction)} title={!ready ? "Vehicle must be ready" : undefined} onClick={onPreflight}><ShieldCheck size={14} />Preflight</button> : null}
                {preflight ? <div className="preflight-list">{preflight.checks.map((check) => <span key={check.code} className={check.passed ? "is-pass" : "is-fail"}>{check.passed ? <Check size={11} /> : <X size={11} />}{check.code}</span>)}</div> : null}
                {!armed ? <button type="button" className="button-primary" disabled={!armActionEnabled(vehicle, preflight, busyAction)} title={!ready ? "Vehicle must be ready" : !preflight?.approved ? "Passing preflight required" : undefined} onClick={onArm}>Arm</button> : null}
                {armed && !flying ? <div className="action-row"><button type="button" className="button-primary" disabled={Boolean(busyAction)} onClick={onTakeoff}>Take off 0.3 m</button><button type="button" className="button-secondary" disabled={Boolean(busyAction)} onClick={onDisarm}>Disarm</button></div> : null}
                {flying ? (
                  <>
                    <div className="direction-pad" aria-label="Relative position controls">
                      <button type="button" aria-label="Move forward" onClick={() => onMove({ y_m: 0.1, duration_s: 1 })}><ArrowUp size={15} /></button>
                      <button type="button" aria-label="Move left" onClick={() => onMove({ x_m: -0.1, duration_s: 1 })}><ArrowLeft size={15} /></button>
                      <button type="button" aria-label="Hold position" onClick={onHold}><Square size={12} /></button>
                      <button type="button" aria-label="Move right" onClick={() => onMove({ x_m: 0.1, duration_s: 1 })}><ArrowRight size={15} /></button>
                      <button type="button" aria-label="Move backward" onClick={() => onMove({ y_m: -0.1, duration_s: 1 })}><ArrowDown size={15} /></button>
                    </div>
                    <div className="action-row"><button type="button" className="button-secondary" onClick={() => onMove({ z_m: 0.1, duration_s: 1 })}>Up</button><button type="button" className="button-secondary" onClick={() => onMove({ z_m: -0.1, duration_s: 1 })}>Down</button><button type="button" className="button-primary" onClick={onLand}>Land</button></div>
                    <button type="button" className="button-secondary abort-button" onClick={onAbort}>Abort and land</button>
                  </>
                ) : null}
                <button type="button" className="emergency-button" disabled={!connected || !vehicle.commandAuthority || vehicle.state === "EMERGENCY"} onClick={onEmergency}>Emergency motor cutoff</button>
              </section>
            ) : null}

            {missionRunning && connected && !vehicle.commandAuthority ? (
              <section className="engineering-section action-stack">
                <h3>Mission safety override</h3>
                <p className="engineering-warning">The mission owns normal commands. Emergency cutoff remains locally available and terminates the mission.</p>
                <button type="button" className="emergency-button" disabled={vehicle.state === "EMERGENCY"} onClick={onEmergency}>Emergency motor cutoff</button>
              </section>
            ) : null}

            {vehicle.capabilities.length ? (
              <section className="engineering-section"><h3>Capabilities</h3><div className="capability-list">{vehicle.capabilities.map((capability) => <span key={capability}>{sentenceCase(capability)}</span>)}</div></section>
            ) : null}

            {vehicle.observationRunId ? (
              <section className="engineering-section action-stack">
                <h3>Evidence</h3>
                <a className="button-secondary" href={`/control-api/api/v1/runs/${encodeURIComponent(vehicle.observationRunId)}/diagnostic`}>Export run</a>
              </section>
            ) : null}

            <section className="engineering-section action-stack">
              <h3>Run history &amp; replay</h3>
              <button className="button-secondary" type="button" disabled={Boolean(busyAction)} onClick={onLoadRunHistory}>Load run history</button>
              {runHistory.map((run) => (
                <div className="run-history-row" key={run.runId}>
                  <span><strong>{run.status}</strong><small>{run.missionId} · {run.runId.slice(0, 12)}…</small></span>
                  <button type="button" disabled={run.status === "INCOMPLETE" || Boolean(busyAction)} onClick={() => onOpenReplay(run.runId)}>Replay</button>
                  <button
                    type="button"
                    className="run-history-delete"
                    disabled={run.status === "INCOMPLETE" || Boolean(busyAction)}
                    onClick={() => onDeleteRunHistory(run)}
                    aria-label={`Delete ${run.missionId} files`}
                    title={run.status === "INCOMPLETE" ? "A recording cannot be deleted" : "Delete run files and folder"}
                  ><Trash2 size={13} /></button>
                </div>
              ))}
              {replay ? (
                <div className="replay-controls" aria-label="Command-free evidence replay">
                  <span><strong>REPLAY · {replay.paused ? "PAUSED" : "READY"}</strong><small>{replay.index} / {replay.eventCount} · {replay.eventKind ?? "open"} · {replay.nowS.toFixed(2)} s</small></span>
                  <div><button type="button" disabled={replay.index >= replay.eventCount || Boolean(busyAction)} onClick={onStepReplay}>Step event</button><button type="button" onClick={onCloseReplay}>Close replay</button></div>
                </div>
              ) : null}
            </section>

            {vehicle.capabilities.includes("parameter_access") ? (
              <section className="engineering-section action-stack">
                <button type="button" className="section-toggle" onClick={onOpenParameters}><Settings size={13} />Parameters</button>
                {parametersOpen ? (
                  <>
                    <div className="parameter-actions">
                      <button type="button" className="button-secondary" disabled={!ready || armed || Boolean(busyAction)} onClick={onSnapshotParameters}>Save baseline</button>
                      {parameterSnapshotId ? <button type="button" className="button-secondary" disabled={!ready || armed || parameterDiffCount === 0 || Boolean(busyAction)} onClick={onRestoreParameters}>Restore{parameterDiffCount ? ` · ${parameterDiffCount}` : ""}</button> : null}
                    </div>
                    <div className="parameter-table">{parameters.map((parameter) => <EngineeringParameter key={parameter.name} parameter={parameter} disabled={!ready || armed} onWrite={onWriteParameter} />)}</div>
                  </>
                ) : null}
              </section>
            ) : null}
          </>
        )}
      </aside>
    </div>
  );
}

function EngineeringParameter({ parameter, disabled, onWrite }: { parameter: ParameterView; disabled: boolean; onWrite: (parameter: ParameterView, value: number) => void }) {
  const inputId = `parameter-${parameter.name.replaceAll(".", "-")}`;
  return (
    <div className="parameter-row"><span><label htmlFor={inputId}>{parameter.name.replace("sim.", "")}</label><small>{parameter.valueType} · {parameter.access} · {parameter.persistence}{parameter.default !== undefined ? ` · default ${String(parameter.default)}` : ""}{parameter.unit ? ` · ${parameter.unit}` : ""}</small></span><input id={inputId} type="number" defaultValue={String(parameter.value)} min={parameter.minimum} max={parameter.maximum} step="any" disabled={disabled || parameter.access !== "READ_WRITE"} onBlur={(event) => { const parsed = Number(event.target.value); if (Number.isFinite(parsed) && parsed !== parameter.value) onWrite(parameter, parsed); }} /></div>
  );
}

export function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  const [title, ...detailLines] = message.split("\n");
  const detail = detailLines.join(" ").trim();
  const failure = title.trim().toLowerCase() === "mission failed";
  useEffect(() => {
    const timeout = window.setTimeout(
      onClose,
      failure ? TOAST_FAILURE_DURATION_MS : TOAST_DURATION_MS,
    );
    return () => window.clearTimeout(timeout);
  }, [failure, message, onClose]);

  return createPortal(
    <div className={`toast ${failure ? "is-failure" : ""} ${detail ? "has-detail" : ""}`} role={failure ? "alert" : "status"} aria-atomic="true">
      <span><strong>{title}</strong>{detail ? <small>{detail}</small> : null}</span>
      <button type="button" aria-label="Dismiss" onClick={onClose}><X size={16} /></button>
    </div>,
    document.body,
  );
}

export function ModeBadge({ mode, label }: { mode: OperatingMode; label?: string }) {
  return <span className={`mode-badge mode-${mode.toLowerCase()}`} aria-label={`Mode: ${label ?? mode}`}>{label ?? mode}</span>;
}

export function controlActionsEnabled(model: DashboardModel, vehicle?: VehicleView) {
  return Boolean(model.apiConnected && vehicle?.commandAuthority && (vehicle.armed ?? vehicle.telemetry?.armed));
}

export function simulationBatteryControlEnabled(
  vehicle?: Pick<VehicleView, "backendRole" | "state" | "armed" | "flying">,
  missionRunning = false,
  busy = false,
) {
  if (!vehicle || vehicle.backendRole !== "FAST_SIM" || missionRunning || busy) return false;
  if (vehicle.state === "DISCONNECTED") return true;
  return ["READY", "LANDING", "ABORTING", "FAULT", "EMERGENCY"].includes(vehicle.state)
    && vehicle.armed === false
    && vehicle.flying === false;
}

export function missionCompletionNotice(
  status: string,
  resultMessage?: string,
  resultReasonCode?: string,
) {
  const normalizedStatus = status.trim().toUpperCase();
  const title = `Mission ${normalizedStatus.toLowerCase()}`;
  const reasonCode = resultReasonCode?.trim()
    ? sentenceCase(resultReasonCode.trim().toLowerCase())
    : undefined;
  const message = resultMessage?.trim() ? sentenceCase(resultMessage.trim()) : undefined;
  if (normalizedStatus !== "FAILED") {
    const noticeTitle = reasonCode ?? title;
    return message && message.toLowerCase() !== noticeTitle.toLowerCase()
      ? `${noticeTitle}\n${message}`
      : noticeTitle;
  }
  const reason = reasonCode && message && reasonCode.toLowerCase() !== message.toLowerCase()
    ? `${reasonCode} — ${message}`
    : reasonCode ?? message ?? "No failure reason was reported";
  return `${title}\nReason: ${reason}`;
}

export function armActionEnabled(
  vehicle?: VehicleView,
  preflight?: PreflightReportView,
  busyAction?: string,
) {
  return vehicle?.state === "READY" && preflight?.approved === true && !busyAction;
}

export function HealthGlyph({ health }: { health: Health }) {
  return <span role="img" className={`health-glyph health-${health.toLowerCase()}`} aria-label={health}>{health === "HEALTHY" ? <Check size={12} /> : health === "FAILED" ? <X size={12} /> : <CircleDot size={12} />}</span>;
}

export function SafetyDialog({ kind, vehicle, onClose, onConfirm }: { kind: "abort" | "emergency" | null; vehicle?: VehicleView; onClose: () => void; onConfirm: () => void }) {
  const [phrase, setPhrase] = useState("");
  if (!kind) return null;
  const emergency = kind === "emergency";
  return (
    <div className="dialog-backdrop"><section className={`dialog safety-dialog is-${kind}`} role="dialog" aria-modal="true"><AlertOctagon size={25} /><h2>{emergency ? "Emergency motor cutoff" : "Abort and land"}</h2><p>{vehicle?.name ?? "Selected vehicle"}</p>{emergency ? <label>Type STOP to confirm<input aria-label="Type STOP to confirm" value={phrase} onChange={(event) => setPhrase(event.target.value)} /></label> : null}<div className="dialog-actions"><button type="button" onClick={onClose}>Cancel</button><button type="button" className="button-danger" disabled={emergency && phrase !== "STOP"} onClick={onConfirm}>{emergency ? "Cut motors now" : "Abort and land"}</button></div></section></div>
  );
}

export function LowBatterySimulationDialog({
  batteryPercent,
  minimumPercent,
  minimumKind = "takeoff",
  vehicleId,
  affectedVehicleCount = 1,
  criticalPercent,
  starting,
  onClose,
  onConfirm,
}: {
  batteryPercent: number;
  minimumPercent: number;
  minimumKind?: "mission" | "takeoff";
  vehicleId?: string;
  affectedVehicleCount?: number;
  criticalPercent: number;
  starting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const isCritical = batteryPercent <= criticalPercent;
  return (
    <section
      className="low-battery-warning"
      role="alertdialog"
      aria-labelledby="low-battery-title"
      aria-describedby="low-battery-description"
    >
      <AlertOctagon size={19} />
      <span className="low-battery-warning-copy">
        <strong id="low-battery-title">{batteryPercent.toFixed(0)}% battery · run anyway?</strong>
        <small id="low-battery-description">
          {vehicleId ? `${vehicleId} is below` : "Below"} the {minimumPercent.toFixed(0)}% {minimumKind === "mission" ? "mission start" : "takeoff"} minimum{isCritical ? ` and ${criticalPercent.toFixed(0)}% critical threshold` : ""}.
          {affectedVehicleCount > 1 ? ` ${affectedVehicleCount} mission vehicles are below their required start level.` : ""}
          Mission may stop immediately; modeled battery limits and all other safety checks stay active.
        </small>
      </span>
      <span className="low-battery-warning-actions">
        <button type="button" aria-label="Cancel low-battery run" disabled={starting} onClick={onClose}><X size={15} /></button>
        <button type="button" className="low-battery-run-button" disabled={starting} onClick={onConfirm}>
          {starting ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />}
          Run anyway
        </button>
      </span>
    </section>
  );
}

function sentenceCase(value: string) {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function vehicleException(vehicle: VehicleView) {
  if (vehicle.state === "DISCONNECTED") return "Offline";
  if (vehicle.state === "EMERGENCY") return "Emergency";
  if (vehicle.state === "FAULT") return "Fault";
  if (vehicle.telemetry?.provenance.freshness === "invalid") return "Invalid data";
  if (vehicle.telemetry?.provenance.freshness === "stale") {
    const age = vehicle.telemetry.provenance.ageMs;
    return age === undefined ? "Stale" : `Stale ${(age / 1_000).toFixed(1)}s`;
  }
  if (vehicle.observationStatus === "COMPLETED_SNAPSHOT") return "Snapshot";
  return undefined;
}

function vehicleTone(vehicle: VehicleView) {
  if (vehicle.state === "DISCONNECTED") return "is-offline";
  if (vehicle.state === "EMERGENCY" || vehicle.state === "FAULT" || vehicle.telemetry?.provenance.freshness === "invalid") return "is-critical";
  if (vehicle.telemetry?.provenance.freshness === "stale" || vehicle.observationStatus === "COMPLETED_SNAPSHOT") return "is-warning";
  return "is-normal";
}
