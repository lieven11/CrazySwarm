"use client";

import {
  AlertOctagon,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BatteryMedium,
  Check,
  ChevronDown,
  ChevronUp,
  CircleDot,
  Clock3,
  Command,
  FileCode2,
  Gauge,
  Hexagon,
  LoaderCircle,
  Map,
  PanelRightOpen,
  Pause,
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
  useState,
  type ReactNode,
} from "react";
import { ControlApi } from "../lib/api";
import { createEmptyDashboard } from "../lib/empty";
import type {
  DashboardModel,
  Health,
  OperatingMode,
  ParameterView,
  PreflightReportView,
  ReplayView,
  RunHistoryView,
  Vec3,
  VehicleView,
} from "../lib/models";
import { missionPlan } from "../lib/spatial";
import { RoomScene } from "./RoomScene";
import { TelemetryDock, type TelemetrySample } from "./TelemetryDock";

type ServiceState = "ATTACHING" | "ONLINE" | "OFFLINE";
type SafetyAction = "abort" | "emergency" | null;
type ExecutionMode = "SIMULATION" | "TWIN";

const LOCAL_API = { endpoint: "/control-api", clientId: "control-center-ui" };

export function ControlCenter() {
  const [model, setModel] = useState<DashboardModel>(() => createEmptyDashboard());
  const [serviceState, setServiceState] = useState<ServiceState>("ATTACHING");
  const [selectedMissionId, setSelectedMissionId] = useState("");
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("SIMULATION");
  const [uploadFile, setUploadFile] = useState<File>();
  const [uploadName, setUploadName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string>();
  const [history, setHistory] = useState<{ runId?: string; points: Vec3[] }>({ points: [] });
  const [telemetryHistory, setTelemetryHistory] = useState<{ key?: string; points: TelemetrySample[] }>({ points: [] });
  const [missionOpen, setMissionOpen] = useState(false);
  const [telemetryOpen, setTelemetryOpen] = useState(true);
  const [notice, setNotice] = useState<string>();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<string>();
  const [preflight, setPreflight] = useState<PreflightReportView>();
  const [safetyAction, setSafetyAction] = useState<SafetyAction>(null);
  const [parametersOpen, setParametersOpen] = useState(false);
  const [engineeringParameters, setEngineeringParameters] = useState<ParameterView[]>([]);
  const [parameterSnapshotId, setParameterSnapshotId] = useState<string>();
  const [parameterDiffCount, setParameterDiffCount] = useState<number>();
  const [runHistory, setRunHistory] = useState<RunHistoryView[]>([]);
  const [replay, setReplay] = useState<ReplayView>();

  const api = useMemo(() => new ControlApi(LOCAL_API), []);
  const effectiveMissionId = selectedMissionId || model.missions[0]?.id || "";
  const selectedVehicle = model.vehicles.find((vehicle) => vehicle.id === model.selectedVehicleId);
  const selectedMission = model.missions.find((mission) => mission.id === effectiveMissionId);
  const runningRunId = activeRunId
    ?? (model.latestRun?.status === "RUNNING" ? model.latestRun.id : undefined);
  const plannedPath = useMemo(
    () => missionPlan(selectedMission, model.room),
    [selectedMission, model.room],
  );
  const rendererModel = replay ? { ...model, mode: "REPLAY" as const } : model;
  const twinAvailable = model.vehicles.some((vehicle) => vehicle.adapter === "cflib")
    && model.vehicles.some((vehicle) => vehicle.adapter === "sim");

  const applyDashboard = useCallback((dashboard: DashboardModel) => {
    setModel(dashboard);
    const observed = dashboard.vehicles.find((vehicle) => vehicle.id === dashboard.selectedVehicleId);
    const sample = telemetrySample(observed);
    if (observed && sample) {
      const key = observed.observationRunId
        ?? `${observed.id}:${observed.telemetry?.provenance.sourceClockEpoch ?? 0}`;
      setTelemetryHistory((current) => {
        if (current.key !== key) return { key, points: [sample] };
        const previous = current.points.at(-1);
        if (previous?.t === sample.t) return current;
        return {
          key,
          points: [...current.points, sample]
            .filter((point) => sample.t - point.t <= 65)
            .slice(-600),
        };
      });
    }
    const runId = observed?.observationRunId;
    const point = observed?.telemetry?.estimate;
    if (!runId || !point) return;
    setHistory((current) => {
      if (current.runId !== runId) return { runId, points: [point] };
      const previous = current.points.at(-1);
      if (previous && previous.x === point.x && previous.y === point.y && previous.z === point.z) return current;
      return { runId, points: [...current.points, point].slice(-500) };
    });
  }, []);

  useEffect(() => {
    if (model.apiConnected && model.missions.length === 0) setMissionOpen(true);
  }, [model.apiConnected, model.missions.length]);

  const attachLocalService = useCallback(async () => {
    setServiceState("ATTACHING");
    const dashboard = await api.loadDashboard();
    applyDashboard(dashboard);
    setActiveRunId(
      dashboard.latestRun?.status === "RUNNING" ? dashboard.latestRun.id : undefined,
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
    if (!activeRunId) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const [run, dashboard] = await Promise.all([
          api.missionRun(activeRunId),
          api.loadDashboard(),
        ]);
        if (cancelled) return;
        applyDashboard(dashboard);
        if (run.result) {
          setActiveRunId(undefined);
          const result = run.result as Record<string, unknown>;
          setNotice(`Mission ${typeof result.status === "string" ? result.status.toLowerCase() : "complete"}`);
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
      timer = window.setTimeout(poll, 160);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, activeRunId, applyDashboard]);

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

  const startMission = async () => {
    if (!api || !selectedMission || !selectedVehicle) return;
    setStarting(true);
    try {
      const result = await api.startMissionFile(selectedMission.id, selectedVehicle.id, executionMode);
      setHistory({ runId: result.mission_run_id, points: [] });
      setTelemetryHistory({ key: result.mission_run_id, points: [] });
      setActiveRunId(result.mission_run_id);
      setMissionOpen(false);
      setNotice("Mission started");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Mission could not start");
    } finally {
      setStarting(false);
    }
  };

  const cancelMission = async () => {
    const runId = runningRunId;
    if (!api || !runId) return;
    try {
      await api.cancelMission(runId);
      setNotice("Controlled abort and landing requested");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Cancel request failed");
    }
  };

  const refreshDashboard = useCallback(async () => {
    applyDashboard(await api.loadDashboard());
  }, [api, applyDashboard]);

  const saveMissionFile = async () => {
    if (!uploadFile) return;
    setUploading(true);
    try {
      const name = uploadName.trim() || uploadFile.name.replace(/\.py$/i, "");
      const mission = await api.uploadMission(name, uploadFile.name, await uploadFile.text());
      await refreshDashboard();
      setSelectedMissionId(mission.id);
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
      if (selectedMissionId === missionId) setSelectedMissionId("");
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

  const resetSimulation = async () => {
    if (
      !selectedVehicle
      || selectedVehicle.adapter !== "sim"
      || selectedVehicle.state !== "DISCONNECTED"
      || runningRunId
    ) return;
    setBusyAction("Reset simulation");
    try {
      const batteryPercent = await api.resetSimulation(selectedVehicle.id);
      setPreflight(undefined);
      setHistory({ points: [] });
      setTelemetryHistory({ points: [] });
      await refreshDashboard();
      setNotice(batteryPercent === undefined
        ? "Simulator reset · battery restored to configured start level"
        : `Simulator reset · battery ${batteryPercent.toFixed(1)}%`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Simulation reset failed");
    } finally {
      setBusyAction(undefined);
    }
  };

  const connectVehicle = async () => {
    if (!selectedVehicle) return;
    await runOperatorAction("Vehicle connected", async () => {
      await api.connectVehicle(selectedVehicle.id);
    });
  };

  const selectVehicle = async (vehicleId: string) => {
    await runOperatorAction("Target selected", async () => {
      await api.selectVehicle(vehicleId);
      setPreflight(undefined);
      setEngineeringParameters([]);
      setParametersOpen(false);
      setParameterSnapshotId(undefined);
      setParameterDiffCount(undefined);
    });
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
    setBusyAction("Load run history");
    try {
      setRunHistory(await api.runHistory());
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Run history unavailable");
    } finally {
      setBusyAction(undefined);
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

  return (
    <main className="control-center">
      <a className="skip-link" href="#mission-workspace">Skip to mission workspace</a>
      <header className="topbar">
        <div className="brand" aria-label="Aerium Control">
          <span className="brand-mark"><Hexagon size={20} strokeWidth={1.8} /></span>
          <span><strong>AERIUM</strong><small>CONTROL</small></span>
        </div>
        <div className="topbar-rule" />
        {model.mode ? <ModeBadge mode={model.mode} label={model.mode === "SIM" ? "SIMULATION" : model.mode} /> : <span className="offline-label">{serviceState === "ATTACHING" ? "STARTING" : "SIM OFFLINE"}</span>}
        <div className="topbar-mission" aria-label="Mission context">
          <small>{runningRunId ? sentenceCase(model.latestRun?.phase ?? "Running") : selectedMission ? "READY TO RUN" : "NO MISSION"}</small>
          <strong>{selectedMission?.name ?? "Select a mission"}</strong>
        </div>
        {selectedVehicle?.telemetry ? (
          <div className="clock-chip"><Clock3 size={14} /><span>{compactClock(selectedVehicle)}</span></div>
        ) : null}
        <div className="topbar-actions">
          {runningRunId ? (
            <button className="stop-button" type="button" onClick={cancelMission}>
              <Square size={13} fill="currentColor" /> Abort and land
            </button>
          ) : null}
          {model.apiConnected ? <button className="connection-button" type="button" onClick={() => setAdvancedOpen((open) => !open)}><Settings size={15} />Engineering</button> : null}
        </div>
      </header>

      <div className={`app-shell ${telemetryOpen ? "has-telemetry" : "telemetry-collapsed"}`}>
        <section className="workspace" id="mission-workspace" tabIndex={-1}>
          <RoomScene model={rendererModel} plannedPath={plannedPath} historicalPath={history.points} />
        </section>

        <nav className="nav-rail" aria-label="Workspace sections">
          <button type="button" className={missionOpen ? "is-active" : ""} aria-label="Mission" aria-pressed={missionOpen} onClick={() => setMissionOpen((open) => !open)}><Command size={19} /></button>
          <button type="button" aria-label="Room" onClick={() => document.getElementById("room-scene")?.focus()}><Map size={19} /></button>
          <button type="button" aria-label="Controls" disabled={!model.apiConnected} onClick={() => setAdvancedOpen(true)}><Gauge size={19} /></button>
        </nav>

        {missionOpen ? (
          <aside className="mission-panel" aria-label="Mission setup">
            <div className="panel-heading">
              <span><small>MISSION SETUP</small><h1 id="mission-title" tabIndex={-1}>Mission</h1></span>
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
                        className={mission.id === effectiveMissionId ? "mission-card is-selected" : "mission-card"}
                        onClick={() => setSelectedMissionId(mission.id)}
                      >
                        <FileCode2 size={15} />
                        <span><strong>{mission.name}</strong><small>{mission.sourceFilename}</small></span>
                        {mission.id === effectiveMissionId ? <Check size={13} /> : null}
                      </button>
                      <button className="mission-archive" type="button" aria-label={`Archive ${mission.name}`} disabled={Boolean(runningRunId || busyAction)} onClick={() => void archiveMission(mission.id)}><Trash2 size={13} /></button>
                    </div>
                  ))}
                  {!model.missions.length ? <span className="mission-empty">NO MISSIONS YET</span> : null}
                </div>

                {model.vehicles.length > 1 ? (
                  <>
                    <label className="field-label" htmlFor="vehicle-select">Vehicle</label>
                    <select id="vehicle-select" value={selectedVehicle?.id ?? ""} disabled={Boolean(runningRunId || busyAction)} onChange={(event) => void selectVehicle(event.target.value)}>
                      {model.vehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id}>{vehicle.name} · {vehicle.id}</option>)}
                    </select>
                  </>
                ) : null}

                <div className="configured-target">
                  <span>Target</span>
                  <strong>{selectedVehicle?.name ?? "No vehicle"}</strong>
                  <small>{selectedVehicle?.id ?? "—"} · {selectedVehicle?.state ?? "unavailable"}</small>
                </div>

                {selectedVehicle?.adapter === "sim" ? (
                  <div className="sim-maintenance">
                    <button
                      type="button"
                      disabled={selectedVehicle.state !== "DISCONNECTED" || Boolean(runningRunId || busyAction)}
                      title={selectedVehicle.state !== "DISCONNECTED" ? "Land, disarm, and disconnect the simulator first" : undefined}
                      onClick={() => void resetSimulation()}
                    >
                      <BatteryMedium size={15} />Recharge simulation
                    </button>
                    <small>Disconnected only · resets battery, pose, clock, and model state</small>
                  </div>
                ) : null}

                {model.latestRun ? <RunSummary run={model.latestRun} /> : null}
              </>
            )}
          </aside>
        ) : null}

        <section className="mission-dock" aria-label="Mission controls">
          <button className="mission-dock-summary" type="button" aria-expanded={missionOpen} onClick={() => setMissionOpen((open) => !open)}>
            <span className="dock-mission-icon"><FileCode2 size={17} /></span>
            <span><small>{runningRunId ? sentenceCase(model.latestRun?.phase ?? "Running") : "MISSION"}</small><strong>{selectedMission?.name ?? "Choose a mission"}</strong></span>
            {missionOpen ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
          </button>
          <span className={`execution-chip execution-${executionMode.toLowerCase()}`}>{executionMode === "SIMULATION" ? "SIM" : "TWIN"}</span>
          <span className="mission-target"><small>VEHICLE</small><strong>{selectedVehicle?.name ?? "Unavailable"}</strong></span>
          {runningRunId ? (
            <span className="mission-running"><LoaderCircle className="spin" size={15} /><strong>Running</strong><small>{compactClock(selectedVehicle)}</small></span>
          ) : (
            <button
              className="dock-run-button"
              type="button"
              disabled={!selectedMission || !selectedVehicle || starting || (executionMode === "TWIN" && !twinAvailable)}
              onClick={() => void startMission()}
            >
              {starting ? <LoaderCircle className="spin" size={16} /> : <Play size={15} fill="currentColor" />}
              {executionMode === "TWIN" ? "Run twin" : "Run simulation"}
            </button>
          )}
        </section>

        {telemetryOpen ? (
          <TelemetryDock
            model={model}
            vehicle={selectedVehicle}
            twin={model.twins.find((item) => item.observedVehicleId === selectedVehicle?.id)}
            samples={telemetryHistory.points}
            onCollapse={() => setTelemetryOpen(false)}
          />
        ) : (
          <button className="telemetry-reopen" type="button" onClick={() => setTelemetryOpen(true)}><PanelRightOpen size={17} /><span>Telemetry</span></button>
        )}
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
        onWriteParameter={writeParameter}
        onSnapshotParameters={snapshotParameters}
        onRestoreParameters={restoreParameters}
        onLoadRunHistory={loadRunHistory}
        onOpenReplay={openReplay}
        onStepReplay={stepReplay}
        onCloseReplay={() => setReplay(undefined)}
      />
      <SafetyDialog kind={safetyAction} vehicle={selectedVehicle} onClose={() => setSafetyAction(null)} onConfirm={confirmSafetyAction} />
      {notice ? <Toast message={notice} onClose={() => setNotice(undefined)} /> : null}
    </main>
  );
}

function EmptyMission({ state, onRetry }: { state: ServiceState; onRetry: () => void }) {
  return (
    <div className="empty-mission">
      <button type="button" disabled={state === "ATTACHING"} onClick={onRetry}>{state === "ATTACHING" ? <LoaderCircle className="spin" size={14} /> : <RotateCcw size={14} />} {state === "ATTACHING" ? "Starting" : "Retry"}</button>
    </div>
  );
}

function RunSummary({ run }: { run: NonNullable<DashboardModel["latestRun"]> }) {
  return (
    <div className="run-summary">
      <span className={`run-symbol status-${run.status.toLowerCase()}`}>{run.status === "RUNNING" ? <LoaderCircle size={15} /> : run.status === "SUCCEEDED" ? <Check size={15} /> : <X size={15} />}</span>
      <div><small>LATEST RUN</small><strong>{run.status}</strong><p>{sentenceCase(run.phase)}</p></div>
    </div>
  );
}

function ObservationPanel({ room, vehicle, twin }: { room: DashboardModel["room"]; vehicle: VehicleView; twin?: TwinSessionView }) {
  const data = vehicle.telemetry;
  if (!data) return null;
  return (
    <aside className="observation-panel" aria-label="Mission observation">
      <div className="observation-heading">
        <div><span className="eyebrow">OBSERVATION</span><h2>{vehicle.name}</h2></div>
        <span className="source-chip">{vehicle.observationClass}</span>
      </div>
      {room ? (
        <section className="observation-card">
          <h3>Room / world frame</h3>
          <Fact label="Room" value={room.id} />
          <Fact label="Volume" value={`${room.widthM} × ${room.depthM} × ${room.heightM} m`} />
          <small className="card-source">CONFIGURED</small>
        </section>
      ) : null}
      <section className="observation-card">
        <h3>Observation</h3>
        {data.estimate ? <VectorFact label="Position" vector={data.estimate} unit={`m · ${data.provenance.frame}`} /> : null}
        <Fact label="Status" value={sentenceCase(vehicle.observationStatus)} />
        <Fact label="Freshness" value={sentenceCase(data.provenance.freshness)} />
        <Fact label="Clock" value={formatClockContext(data.provenance)} />
        {vehicle.observationRunId ? <Fact label="Run" value={vehicle.observationRunId} /> : null}
        <small className="card-source">{vehicle.observationClass} · {data.provenance.frame.toUpperCase()}</small>
      </section>
      <section className="observation-card">
        <h3>Vehicle</h3>
        <Fact label="State" value={vehicle.state} />
        {data.batteryPercent !== undefined ? <Fact label="Battery model" value={`${data.batteryPercent.toFixed(1)}%`} icon={<BatteryMedium size={14} />} /> : null}
        {data.batteryCurrent !== undefined ? <Fact label="Current" value={`${data.batteryCurrent.toFixed(2)} A`} /> : null}
        {data.attitude ? <Fact label="Attitude" value={`${toDegrees(data.attitude.rollRad)}° · ${toDegrees(data.attitude.pitchRad)}° · ${toDegrees(data.attitude.yawRad)}°`} /> : null}
        {data.localizationPercent !== undefined ? <Fact label="Localization model" value={`${data.localizationPercent.toFixed(0)}%`} /> : null}
      </section>
      {data.motors ? (
        <section className="observation-card">
          <h3>Motors</h3>
          {data.motors.readings.map((motor) => <Fact key={motor.id} label={motor.id} value={`${motor.commandPercent.toFixed(0)}% · ${motor.thrustN.toFixed(3)} N · ${motor.currentA.toFixed(2)} A`} />)}
          <small className="card-source">{data.motors.modelId} · {data.motors.modelVersion}</small>
        </section>
      ) : null}
      {data.imu ? (
        <section className="observation-card">
          <h3>Modeled IMU</h3>
          <VectorFact label="Acceleration" vector={data.imu.acceleration} unit="m/s²" />
          <VectorFact label="Angular velocity" vector={data.imu.angularVelocity} unit="rad/s" />
          <small className="card-source">SIMULATED_MODEL · BODY</small>
        </section>
      ) : null}
      {data.flow ? (
        <section className="observation-card">
          <h3>Modeled flow</h3>
          {data.flow.groundDistanceM !== undefined ? <Fact label="Height" value={`${data.flow.groundDistanceM.toFixed(2)} m`} /> : null}
          {data.flow.qualityPercent !== undefined ? <Fact label="Quality" value={`${data.flow.qualityPercent.toFixed(0)}%`} /> : null}
          <VectorFact label="Velocity" vector={data.flow.velocity} unit="m/s" />
          <small className="card-source">SIMULATED_MODEL · RELATIVE / DRIFT-PRONE</small>
        </section>
      ) : null}
      {data.ranges.length ? (
        <section className="observation-card">
          <h3>Modeled ranges</h3>
          <div className="range-list">
            {data.ranges.map((ray) => <Fact key={ray.direction} label={ray.direction} value={ray.distanceM === null ? "—" : `${ray.distanceM.toFixed(2)} m`} />)}
          </div>
          <small className="card-source">SIMULATED_MODEL · SENSOR FRAME</small>
        </section>
      ) : null}
      {data.transport ? (
        <section className="observation-card muted-card">
          <h3>Modeled transport</h3>
          {data.transport.latencyMs !== undefined ? <Fact label="Configured latency" value={`${data.transport.latencyMs.toFixed(0)} ms`} /> : null}
          <small className="card-source">NOT PHYSICAL RADIO DATA</small>
        </section>
      ) : null}
      {data.radio ? (
        <section className="observation-card">
          <h3>Radio</h3>
          {data.radio.qualityPercent !== undefined ? <Fact label="Quality" value={`${data.radio.qualityPercent.toFixed(0)}%`} /> : null}
          {data.radio.latencyMs !== undefined ? <Fact label="Latency" value={`${data.radio.latencyMs.toFixed(0)} ms`} /> : null}
          <small className="card-source">{data.radio.evidenceClass}</small>
        </section>
      ) : null}
      {vehicle.decks.length ? (
        <section className="observation-card">
          <h3>{vehicle.adapter === "sim" ? "Sensor models" : "Decks"}</h3>
          {vehicle.decks.map((deck) => <Fact key={deck.id} label={deck.type} value={vehicle.adapter === "sim" ? "MODELED" : deck.health} />)}
          <small className="card-source">{vehicle.adapter === "sim" ? "CONFIGURED" : "MEASURED_REAL"}</small>
        </section>
      ) : null}
      {twin?.latestDeviation ? (
        <section className="observation-card">
          <h3>Digital twin</h3>
          {twin.latestDeviation.positionM !== undefined ? <Fact label="Position delta" value={`${twin.latestDeviation.positionM.toFixed(3)} m`} /> : null}
          {twin.latestDeviation.altitudeM !== undefined ? <Fact label="Altitude delta" value={`${twin.latestDeviation.altitudeM.toFixed(3)} m`} /> : null}
          {twin.latestDeviation.batteryPercent !== undefined ? <Fact label="Battery delta" value={`${twin.latestDeviation.batteryPercent.toFixed(2)}%`} /> : null}
          <Fact label="Observed latency" value={`${twin.latestDeviation.observedLatencyMs.toFixed(1)} ms`} />
          <Fact label="Twin latency" value={`${twin.latestDeviation.simulatedLatencyMs.toFixed(1)} ms`} />
          <Fact label="Clock alignment" value={`${twin.latestDeviation.alignmentDeltaMs.toFixed(1)} ms`} />
          <small className="card-source">{twin.groundTruthAvailable ? "EXTERNAL GROUND TRUTH" : "NO EXTERNAL GROUND TRUTH"}</small>
        </section>
      ) : null}
    </aside>
  );
}

function Fact({ label, value, icon }: { label: string; value: string; icon?: ReactNode }) {
  return <div className="fact"><span>{icon}{label}</span><strong>{value}</strong></div>;
}

function VectorFact({ label, vector, unit }: { label: string; vector: Vec3; unit: string }) {
  return <div className="vector-fact"><span>{label}</span><code>{vector.x.toFixed(2)} / {vector.y.toFixed(2)} / {vector.z.toFixed(2)} {unit}</code></div>;
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

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  return <div className="toast" role="status"><span>{message}</span><button type="button" aria-label="Dismiss" onClick={onClose}><X size={14} /></button></div>;
}

export function ModeBadge({ mode, label }: { mode: OperatingMode; label?: string }) {
  const icon = mode === "SIM" ? <Command size={13} /> : mode === "LIVE" ? <Radio size={13} /> : mode === "SHADOW" ? <Pause size={13} /> : <RotateCcw size={13} />;
  return <span className={`mode-badge mode-${mode.toLowerCase()}`} aria-label={`Mode: ${label ?? mode}`}>{icon}{label ?? mode}</span>;
}

export function controlActionsEnabled(model: DashboardModel, vehicle?: VehicleView) {
  return Boolean(model.apiConnected && vehicle?.commandAuthority && (vehicle.armed ?? vehicle.telemetry?.armed));
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

function sentenceCase(value: string) {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function toDegrees(value: number) {
  return (value * 180 / Math.PI).toFixed(1);
}
