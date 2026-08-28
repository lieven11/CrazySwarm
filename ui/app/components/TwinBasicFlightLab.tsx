"use client";

import {
  Beaker,
  CircleAlert,
  ChevronDown,
  ChevronUp,
  Database,
  LoaderCircle,
  Maximize2,
  Play,
  ShieldCheck,
  Square,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { ControlApi } from "../lib/api";
import type {
  PhysicalBasicFlightMotionId,
  PhysicalTwinStatusView,
  MotorActuationStatusView,
  TwinBasicFlightCatalogView,
  TwinBasicFlightMotionView,
  TwinBasicFlightRunView,
  TwinMissionClusterView,
  PhysicalFlightOperationStatusView,
} from "../lib/models";
import { CampaignDropdown } from "./CampaignLab";

type TwinWorkspaceTab = "catalog" | "run" | "review";

export const TWIN_WORKSPACE_PREFERENCES_KEY = "crazyswarm.twin-workspace.v1";

const TWIN_WORKSPACE_TABS: ReadonlyArray<{ id: TwinWorkspaceTab; label: string }> = [
  { id: "catalog", label: "Catalog" },
  { id: "run", label: "Active run" },
  { id: "review", label: "Review" },
];

interface TwinBasicFlightLabProps {
  api: ControlApi;
  actuationStatus?: MotorActuationStatusView;
  missionOpen?: boolean;
  onNotice: (message: string) => void;
  onMissionClose?: () => void;
  onMissionToggle?: () => void;
  onOperationActiveChange?: (active: boolean) => void;
  onPhysicalFlightActiveChange?: (active: boolean) => void;
  onStopAllMotorOutput?: () => Promise<MotorActuationStatusView | undefined>;
  onSelectSimulation?: () => void;
  onPhysicalStatusChange?: (status: PhysicalTwinStatusView) => void;
  physicalStatus?: PhysicalTwinStatusView;
}

export function TwinBasicFlightLab({
  api,
  actuationStatus,
  missionOpen = false,
  onNotice,
  onMissionClose,
  onMissionToggle,
  onOperationActiveChange,
  onPhysicalFlightActiveChange,
  onStopAllMotorOutput,
  onSelectSimulation,
  onPhysicalStatusChange,
  physicalStatus,
}: TwinBasicFlightLabProps) {
  const [open, setOpen] = useState(false);
  const [workspaceTab, setWorkspaceTab] = useState<TwinWorkspaceTab>("catalog");
  const [preferencesReady, setPreferencesReady] = useState(false);
  const [catalog, setCatalog] = useState<TwinBasicFlightCatalogView>();
  const [selectedMotionId, setSelectedMotionId] = useState("arm-disarm");
  const [headingInput, setHeadingInput] = useState("0");
  const [heightInput, setHeightInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string>();
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [running, setRunning] = useState(false);
  const [triggeringFlip, setTriggeringFlip] = useState(false);
  const [run, setRun] = useState<TwinBasicFlightRunView>();
  const [runError, setRunError] = useState<string>();
  const [avoidanceEnabled, setAvoidanceEnabled] = useState(true);
  const [flightOperation, setFlightOperation] = useState<PhysicalFlightOperationStatusView>();
  const launcherRef = useRef<HTMLButtonElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const handledFlightTerminalRef = useRef<string | undefined>(undefined);

  const acceptFlightOperation = useCallback((next: PhysicalFlightOperationStatusView) => {
    setFlightOperation(next);
    if (next.state === "FAILED" && next.stopRequired) {
      setRunError(next.detail ?? "Physical flight stop could not be confirmed");
      return;
    }
    if (!next.operationId || next.stopRequired || handledFlightTerminalRef.current === next.operationId) {
      return;
    }
    handledFlightTerminalRef.current = next.operationId;
    if (next.state === "COMPLETED" && next.result) {
      setRun(next.result);
      setRunError(undefined);
      setWorkspaceTab("review");
      const completedMotion = catalog?.motions.find(
        (motion) => motion.motionId === next.motionId
          && (
            !next.controllerTuningPreparation
            || motion.placementMarker === next.controllerTuningPreparation.stationId
          ),
      );
      onNotice(next.motionId === "arm-disarm"
        ? "Physical arm and disarm completed"
        : completedMotion?.physicalScope === "FIXTURE_OBSERVATION"
          ? "Fixture observation completed with no flight command"
        : next.motionId === "commissioning-baseline"
          ? "Physical 30 cm commissioning flight completed and landed"
          : `Physical ${completedMotion?.motion ?? "mission"} completed and landed`);
    } else if (next.state === "ABORTED") {
      setRunError(undefined);
      onNotice(next.detail ?? "Physical flight aborted and landed safely");
    } else if (next.state === "FAILED") {
      setRunError(next.detail ?? "Physical drone action failed");
      onNotice(next.detail ?? "Physical drone action failed");
    }
  }, [catalog?.motions, onNotice]);

  /* Local storage restores workspace navigation, never physical command state. */
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(TWIN_WORKSPACE_PREFERENCES_KEY);
      if (stored) {
        const preferences = JSON.parse(stored) as Record<string, unknown>;
        if (typeof preferences.open === "boolean") setOpen(preferences.open);
        if (TWIN_WORKSPACE_TABS.some((tab) => tab.id === preferences.tab)) {
          setWorkspaceTab(preferences.tab as TwinWorkspaceTab);
        }
        if (typeof preferences.selectedMotionId === "string") {
          setSelectedMotionId(preferences.selectedMotionId);
        }
      }
    } catch {
      window.localStorage.removeItem(TWIN_WORKSPACE_PREFERENCES_KEY);
    } finally {
      setPreferencesReady(true);
    }
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (!preferencesReady) return;
    window.localStorage.setItem(TWIN_WORKSPACE_PREFERENCES_KEY, JSON.stringify({
      open,
      tab: workspaceTab,
      selectedMotionId,
    }));
  }, [open, preferencesReady, selectedMotionId, workspaceTab]);

  useEffect(() => {
    let active = true;
    void api.twinBasicFlightCatalog()
      .then((next) => {
        if (!active) return;
        setCatalog(next);
        const visibleMotions = next.motions.filter(
          (motion) => motion.catalogVisibility,
        );
        setSelectedMotionId((current) => (
          visibleMotions.some((motion) => motionSelectionKey(motion) === current)
            ? current
            : motionSelectionKey(
                visibleMotions.find((motion) => motion.motionId === current)
                  ?? visibleMotions[0],
              )
        ));
      })
      .catch((error) => {
        if (!active) return;
        const message = error instanceof Error ? error.message : "Basic flight laboratory unavailable";
        setLoadError(message);
        onNotice(message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, loadAttempt, onNotice]);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await api.physicalFlightStatus();
        if (active) acceptFlightOperation(next);
      } catch {
        // Preserve the last backend-owned active state until status recovers.
      }
      if (active) timer = window.setTimeout(poll, 500);
    };
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [acceptFlightOperation, api]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : undefined;
    const launcher = launcherRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const handleWorkspaceKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        return;
      }
      if (event.key !== "Tab" || !workspaceRef.current) return;
      const focusable = [...workspaceRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => !element.hidden);
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleWorkspaceKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleWorkspaceKeyDown);
      document.body.style.overflow = previousOverflow;
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
      else launcher?.focus();
    };
  }, [open]);

  const visibleMotions = catalog?.motions.filter(
    (motion) => motion.catalogVisibility,
  ) ?? [];
  const availableClusters = unique(visibleMotions.map((motion) => motion.clusterId)).map(
    (clusterId): TwinMissionClusterView => catalog?.clusters.find(
      (cluster) => cluster.clusterId === clusterId,
    ) ?? {
      clusterId,
      clusterName: missionClusterLabel(clusterId),
      purpose: "",
      state: "READY",
    },
  );
  const selected = visibleMotions.find(
    (motion) => motionSelectionKey(motion) === selectedMotionId,
  );
  const selectedClusterId = selected?.clusterId ?? availableClusters[0]?.clusterId ?? "basic-flight";
  const clusterMotions = visibleMotions.filter(
    (motion) => motion.clusterId === selectedClusterId,
  );
  const majorMissions = unique(clusterMotions.map((motion) => motion.majorMission));
  const variants = unique(
    clusterMotions
      .filter((motion) => motion.majorMission === selected?.majorMission)
      .map((motion) => motion.variant),
  );
  const motions = clusterMotions.filter(
    (motion) => motion.majorMission === selected?.majorMission && motion.variant === selected?.variant,
  );
  const motorStopRequired = Boolean(actuationStatus?.stopRequired);
  const physicalFlightActive = Boolean(flightOperation?.stopRequired);
  const observedSupervisor = physicalStatus?.observed;
  const controllerPreparationSelected = selected?.clusterId === "controller-characterization-tuning"
    && selected.placementMarker !== undefined;
  const avoidanceAvailable = selected?.physicalScope === "CONTAINED_FLIGHT"
    && selected.motionId !== "acro-single-roll";
  const avoidanceMode = avoidanceAvailable && avoidanceEnabled
    ? "ENFORCED" as const
    : "MONITOR_ONLY" as const;
  const parsedHeadingDeg = headingInput.trim() === "" ? 0 : Number(headingInput);
  const parsedHeightM = heightInput.trim() === "" ? undefined : Number(heightInput);
  const controllerFlightHeightRequired = controllerPreparationSelected
    && selected?.physicalScope === "CONTAINED_FLIGHT";
  const controllerPreparationValid = !controllerPreparationSelected || (
    Number.isFinite(parsedHeadingDeg)
    && parsedHeadingDeg >= 0
    && parsedHeadingDeg <= 90
    && (
      (!controllerFlightHeightRequired && parsedHeightM === undefined)
      || (
        parsedHeightM !== undefined
        && Number.isFinite(parsedHeightM)
        && parsedHeightM >= (controllerFlightHeightRequired ? 0.01 : 0)
        && parsedHeightM <= 0.5
      )
    )
  );
  const physicalFlightStartReady = Boolean(
    physicalStatus?.state === "PAIRED"
    && observedSupervisor?.freshness === "CURRENT"
    && typeof observedSupervisor.armed === "boolean"
    && observedSupervisor.flying === false
    && actuationStatus?.rebootRequired !== true
    && selected?.physicalExecution === "OPERATOR_GATED"
    && selected.implementationState === "READY"
    && controllerPreparationValid
  );
  const physicalFlightBlockReason = controllerFlightHeightRequired && parsedHeightM === undefined
    ? "Enter the flight height for this run (0.01 m to 0.50 m)"
    : !controllerPreparationValid
    ? "Heading must be between 0° and 90° and height must be within the displayed range"
    : selected?.blockReason
    ?? (selected?.physicalExecution !== "OPERATOR_GATED"
      ? "This raw stage has no executable workflow yet"
      : actuationStatus?.rebootRequired
    ? "Power cycle the Crazyflie before starting another physical action"
    : physicalStatus?.state !== "PAIRED"
    ? "Connect and pair the observer first"
    : observedSupervisor?.freshness !== "CURRENT"
      ? "Waiting for current supervisor telemetry"
      : observedSupervisor.flying === true
        ? "The drone reports flying; flight recovery is required"
        : typeof observedSupervisor.armed !== "boolean"
          ? "Waiting for current supervisor arm state"
          : "Waiting for supervisor confirmation that the drone is not flying");
  const operationActive = running || triggeringFlip || physicalFlightActive || motorStopRequired;
  const operationMotion = visibleMotions.find(
    (motion) => motion.motionId === flightOperation?.motionId
      && (
        !flightOperation?.controllerTuningPreparation
        || motion.placementMarker === flightOperation.controllerTuningPreparation.stationId
      ),
  ) ?? selected;
  const flightVisualizationActive = (running || physicalFlightActive)
    && operationMotion?.physicalScope !== "FIXTURE_OBSERVATION";

  useEffect(() => {
    onOperationActiveChange?.(operationActive);
  }, [onOperationActiveChange, operationActive]);

  useEffect(() => () => onOperationActiveChange?.(false), [onOperationActiveChange]);

  useEffect(() => {
    onPhysicalFlightActiveChange?.(flightVisualizationActive);
  }, [flightVisualizationActive, onPhysicalFlightActiveChange]);

  useEffect(
    () => () => onPhysicalFlightActiveChange?.(false),
    [onPhysicalFlightActiveChange],
  );

  const chooseFirst = (predicate: (motion: TwinBasicFlightMotionView) => boolean) => {
    if (operationActive) return;
    const next = visibleMotions.find(predicate);
    if (next) {
      setSelectedMotionId(motionSelectionKey(next));
      setRun(undefined);
      setRunError(undefined);
    }
  };

  const startPhysical = async () => {
    if (!selected || selected.physicalExecution !== "OPERATOR_GATED") return;
    if (!physicalFlightStartReady) {
      onNotice(physicalFlightBlockReason);
      return;
    }
    onMissionClose?.();
    setRunning(true);
    setRun(undefined);
    setRunError(undefined);
    setWorkspaceTab("run");
    try {
      const preparation = controllerPreparationSelected ? {
        stationId: selected.placementMarker!,
        headingDeg: parsedHeadingDeg,
        targetHeightM: parsedHeightM,
      } : undefined;
      const operation = avoidanceAvailable
        ? await api.startPhysicalFlight(
          selected.motionId as PhysicalBasicFlightMotionId,
          preparation,
          avoidanceMode,
        )
        : preparation
          ? await api.startPhysicalFlight(
            selected.motionId as PhysicalBasicFlightMotionId,
            preparation,
          )
          : await api.startPhysicalFlight(
            selected.motionId as PhysicalBasicFlightMotionId,
          );
      handledFlightTerminalRef.current = undefined;
      acceptFlightOperation(operation);
      onNotice(selected.physicalScope === "FIXTURE_OBSERVATION"
        ? "Fixture observation started · Stop observation is available below"
        : selected.motionId === "acro-single-roll"
          ? "50 cm hover starting · Flip appears when hover capture is confirmed"
        : "Physical drone action started · Abort and land is available below");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Physical drone action failed";
      setRunError(message);
      onNotice(message);
    } finally {
      try {
        onPhysicalStatusChange?.(await api.physicalTwinStatus());
      } catch {
        // The parent keeps polling configured observer state, so a transient
        // refresh failure cannot leave this workflow as the state authority.
      }
      setRunning(false);
    }
  };

  const triggerAcrobaticsFlip = async () => {
    if (flightOperation?.availableAction !== "FLIP" || triggeringFlip) return;
    setTriggeringFlip(true);
    try {
      acceptFlightOperation(await api.triggerAcrobaticsFlip());
      onNotice("Flip triggered · recovery hover and automatic landing follow");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Flip trigger failed";
      setRunError(message);
      onNotice(message);
    } finally {
      setTriggeringFlip(false);
    }
  };

  const abortPhysicalFlight = async () => {
    if (!physicalFlightActive) return;
    try {
      acceptFlightOperation(await api.abortPhysicalFlight());
    } catch (error) {
      const message = error instanceof Error ? error.message : "Abort and land failed";
      setRunError(message);
      onNotice(message);
    }
  };

  const stopMotorOutput = async () => {
    if (!motorStopRequired || !onStopAllMotorOutput) return;
    setRunning(true);
    try {
      const stopped = await onStopAllMotorOutput();
      if (stopped?.state === "IDLE") {
        setRunError(undefined);
      } else if (stopped) {
        setRunError(stopped.detail ?? "Motor stop could not be confirmed");
      }
    } finally {
      setRunning(false);
    }
  };
  const status = run?.status === "COMPLETED"
    ? { label: "Completed", className: "state-promoted" }
    : run?.status === "FAILED"
      ? { label: "Blocked", className: "state-blocked" }
      : selected?.implementationState === "RAW"
        ? { label: "Raw", className: "state-defined" }
        : selected?.implementationState === "SETUP_REQUIRED"
          ? { label: "Unavailable", className: "state-blocked" }
      : { label: "Ready", className: "state-ready" };
  const headerSummary = selected
    ? `${selected.majorMission} · Physical drone · ${status.label}`
    : "Digital twin missions · Physical drone";
  const launcherSummary = selected
    ? `${selected.majorMission} · ${status.label}`
    : loading ? "Loading Digital Twin missions" : "Open mission development workspace";

  const workspaceOverlay = open && typeof document !== "undefined" ? createPortal(
    <div className="campaign-workspace-backdrop">
      <section
        ref={workspaceRef}
        className="campaign-workspace twin-campaign-workspace"
        role="dialog"
        aria-modal="true"
        aria-labelledby="twin-campaign-workspace-title"
      >
        <header className="campaign-workspace-header">
          <div className="campaign-workspace-title">
            <span><Beaker size={17} /></span>
            <div>
              <h2 id="twin-campaign-workspace-title">Campaign Laboratory</h2>
              <small>{headerSummary}</small>
            </div>
          </div>
          <div className="campaign-filter campaign-workspace-environment" role="group" aria-label="Environment">
            <button
              type="button"
              onClick={() => {
                if (!operationActive) setOpen(false);
                onSelectSimulation?.();
              }}
            >Simulation</button>
            <button type="button" className="is-selected" aria-pressed="true">Digital twin</button>
          </div>
          <button
            ref={closeButtonRef}
            className="campaign-workspace-close"
            type="button"
            aria-label="Close Campaign Laboratory"
            onClick={() => setOpen(false)}
          ><X size={18} /></button>
        </header>

        <div className="campaign-workspace-tabs" role="tablist" aria-label="Campaign Laboratory sections">
          {TWIN_WORKSPACE_TABS.map((tab) => (
            <button
              key={tab.id}
              id={`twin-campaign-workspace-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={workspaceTab === tab.id}
              aria-controls={`twin-campaign-workspace-panel-${tab.id}`}
              className={workspaceTab === tab.id ? "is-selected" : ""}
              onClick={() => setWorkspaceTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="campaign-workspace-body">
          {loading ? (
            <div className="campaign-loading"><LoaderCircle className="spin" size={16} />Loading campaign workspace</div>
          ) : null}
          {loadError ? (
            <div className="campaign-loading" role="alert">
              <CircleAlert size={16} />
              <span>Campaign workspace unavailable: {loadError}</span>
              <button type="button" onClick={() => {
                setLoading(true);
                setLoadError(undefined);
                setLoadAttempt((value) => value + 1);
              }}>Retry</button>
            </div>
          ) : null}

          {catalog && selected && workspaceTab === "catalog" ? (
            <TwinCatalog
              catalog={catalog}
              clusters={availableClusters}
              selected={selected}
              selectedClusterId={selectedClusterId}
              majorMissions={majorMissions}
              variants={variants}
              motions={motions}
              status={status}
              disabled={operationActive}
              headingInput={headingInput}
              heightInput={heightInput}
              onHeadingInputChange={setHeadingInput}
              onHeightInputChange={setHeightInput}
              onClusterChange={(clusterId) => chooseFirst(
                (motion) => motion.clusterId === clusterId,
              )}
              onMajorMissionChange={(majorMission) => chooseFirst(
                (motion) => motion.clusterId === selectedClusterId
                  && motion.majorMission === majorMission,
              )}
              onVariantChange={(variant) => chooseFirst(
                (motion) => motion.clusterId === selectedClusterId
                  && motion.majorMission === selected.majorMission
                  && motion.variant === variant,
              )}
              onMotionChange={(motionId) => {
                if (operationActive) return;
                setSelectedMotionId(motionId);
                setRun(undefined);
                setRunError(undefined);
              }}
            />
          ) : null}

          {catalog && selected && workspaceTab === "run" ? (
            <section
              id="twin-campaign-workspace-panel-run"
              className="campaign-run-workspace"
              role="tabpanel"
              aria-labelledby="twin-campaign-workspace-tab-run"
            >
              <header className="campaign-case-detail-header">
                <div><small>Active mission</small><h3>{selected.motion}</h3></div>
                <span className={`campaign-status ${status.className}`}>{running ? "Connecting" : status.label}</span>
              </header>
              {physicalFlightActive || running ? (
                <div className="campaign-running"><LoaderCircle className="spin" size={14} />{
                  running
                    ? "Connecting to physical drone"
                    : flightOperation?.state === "HOVERING_READY"
                      ? "Hovering at 50 cm · Flip is ready"
                    : flightOperation?.state === "FLIPPING"
                      ? "Flip running · Automatic landing follows"
                    : selected.physicalScope === "FIXTURE_OBSERVATION"
                      ? "Fixture observation running"
                      : "Physical drone action running"
                }</div>
              ) : null}
              {runError ? (
                <div className="campaign-loading" role="alert"><CircleAlert size={16} />{runError}</div>
              ) : null}
              <MotionSequence motion={selected} />
              <SafetyScope motion={selected} />
            </section>
          ) : null}

          {catalog && workspaceTab === "review" ? (
            <TwinReview run={run} selected={selected} />
          ) : null}
        </div>

        <footer className="campaign-workspace-footer twin-campaign-workspace-footer">
          <span><ShieldCheck size={14} />Selected mission appears in the bottom mission control</span>
        </footer>
      </section>
    </div>,
    document.body,
  ) : null;

  const dockHost = typeof document !== "undefined"
    ? document.querySelector(".app-shell") ?? document.body
    : null;
  const dockTitle = selected?.majorMission ?? "Basic flight";
  const measuredMaximum = actuationStatus?.measuredPwmPercent
    ? Math.max(...actuationStatus.measuredPwmPercent)
    : undefined;
  const dockDetail = motorStopRequired
    ? measuredMaximum !== undefined
      ? `Measured PWM · ${measuredMaximum.toFixed(0)}%`
      : actuationStatus?.state === "ACTIVE" && actuationStatus.commandedOutputPercent !== undefined
        ? `Motor command · ${actuationStatus.commandedOutputPercent.toFixed(0)}%`
        : "Motor output · Unconfirmed"
    : running
      ? "Physical drone · Connecting"
    : observedSupervisor?.freshness === "CURRENT" && observedSupervisor.flying === true
      ? "Drone reports flying · Recovery required"
    : actuationStatus?.rebootRequired
      ? "Motors off · Power cycle required"
      : physicalFlightActive
      ? flightOperation?.state === "ABORTING"
        ? "Physical drone · Landing"
        : flightOperation?.state === "HOVERING_READY"
          ? "Hovering at 50 cm · Flip ready"
        : flightOperation?.state === "FLIPPING"
          ? "Flip running · Landing next"
        : flightOperation?.state === "FAILED" || flightOperation?.state === "STOP_UNCONFIRMED"
          ? "Physical flight · Stop unconfirmed"
          : flightOperation?.state === "STARTING"
            ? "Physical drone · Starting"
            : "Physical drone · Running"
      : selected
        ? selected.implementationState === "RAW"
          ? `${selected.motion} · Raw stage`
          : selected.implementationState === "SETUP_REQUIRED"
            ? `${selected.motion} · Unavailable`
            : selected.physicalScope === "FIXTURE_OBSERVATION"
              ? `${selected.motion} · Motors off`
              : `${selected.motion} · Physical drone`
        : loading ? "Loading missions" : "Select a mission";
  const startLabel = selected?.physicalScope === "FIXTURE_OBSERVATION"
      ? `Record ${selected.motion}`
      : selected?.motionId === "arm-disarm"
      ? "Run arm and disarm"
      : selected?.motionId === "commissioning-baseline"
        ? "Run 30 cm commissioning flight"
      : selected?.motionId === "acro-single-roll"
        ? "Start 50 cm hover"
        : `Run ${selected?.motion ?? "physical mission"}`;
  const missionDock = dockHost ? createPortal(
    <section className={`mission-dock twin-mission-dock ${motorStopRequired ? "has-motor-control" : ""} ${flightOperation?.availableAction === "FLIP" ? "has-flip-control" : ""} ${avoidanceAvailable && !physicalFlightActive && !motorStopRequired ? "has-avoidance-control" : ""}`} aria-label="Digital Twin mission controls">
      <button
        className="mission-dock-summary"
        type="button"
        aria-expanded={missionOpen}
        disabled={operationActive}
        title={operationActive ? "Stop the active physical mission before changing selection" : undefined}
        onClick={onMissionToggle}
      >
        <Beaker size={17} />
        <span><strong>{dockTitle}</strong><small aria-live="polite">{dockDetail}</small></span>
        {missionOpen ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
      </button>
      {motorStopRequired ? (
        <button
          className="dock-abort-button"
          type="button"
          disabled={actuationStatus?.state === "STOPPING" || !onStopAllMotorOutput}
          onClick={() => void stopMotorOutput()}
        >
          {actuationStatus?.state === "STOPPING"
            ? <LoaderCircle className="spin" size={14} />
            : <Square size={13} fill="currentColor" />}Stop motors
        </button>
      ) : physicalFlightActive ? (
        <>
          {flightOperation?.availableAction === "FLIP" ? (
            <button
              className="dock-run-button twin-physical-run-button twin-flip-button"
              type="button"
              disabled={triggeringFlip}
              onClick={() => void triggerAcrobaticsFlip()}
            >
              {triggeringFlip
                ? <LoaderCircle className="spin" size={14} />
                : <Play size={14} fill="currentColor" />}
              Flip
            </button>
          ) : null}
          <button
            className="dock-abort-button"
            type="button"
            disabled={flightOperation?.state === "ABORTING"}
            onClick={() => void abortPhysicalFlight()}
          >
            {flightOperation?.state === "ABORTING"
              ? <LoaderCircle className="spin" size={14} />
              : <Square size={13} fill="currentColor" />}
            {operationMotion?.physicalScope === "FIXTURE_OBSERVATION"
              ? "Stop observation"
              : "Abort and land"}
          </button>
        </>
      ) : (
        <>
          {avoidanceAvailable ? (
            <button
              className="twin-avoidance-toggle"
              type="button"
              role="switch"
              aria-checked={avoidanceEnabled}
              disabled={running}
              title="Enforced by default; turn off only to record ranges without intervention"
              onClick={() => setAvoidanceEnabled((enabled) => !enabled)}
            >
              <ShieldCheck size={13} />
              <span>Avoidance</span>
              <small>{avoidanceEnabled ? "On" : "Monitor"}</small>
            </button>
          ) : null}
          <button
            className="dock-run-button twin-physical-run-button"
            type="button"
            aria-label={running ? "Connecting to physical drone" : startLabel}
            disabled={
              !selected
              || running
              || !physicalFlightStartReady
            }
            title={
              !physicalFlightStartReady
                ? physicalFlightBlockReason
                : undefined
            }
            onClick={() => void startPhysical()}
          >
            {running ? <LoaderCircle className="spin" size={16} /> : <Play size={15} fill="currentColor" />}
          </button>
        </>
      )}
    </section>,
    dockHost,
  ) : null;

  return (
    <>
      <section className="campaign-lab" aria-label="Digital Twin mission development laboratory">
        <button
          ref={launcherRef}
          className="campaign-lab-toggle"
          type="button"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen(true)}
        >
          <Beaker size={15} />
          <span><strong>Campaign Laboratory</strong><small>{launcherSummary}</small></span>
          <em>Open <Maximize2 size={13} /></em>
        </button>
      </section>
      {workspaceOverlay}
      {missionDock}
    </>
  );
}

function TwinCatalog({
  catalog,
  clusters,
  selected,
  selectedClusterId,
  majorMissions,
  variants,
  motions,
  status,
  disabled,
  headingInput,
  heightInput,
  onHeadingInputChange,
  onHeightInputChange,
  onClusterChange,
  onMajorMissionChange,
  onVariantChange,
  onMotionChange,
}: {
  catalog: TwinBasicFlightCatalogView;
  clusters: TwinMissionClusterView[];
  selected: TwinBasicFlightMotionView;
  selectedClusterId: string;
  majorMissions: string[];
  variants: string[];
  motions: TwinBasicFlightMotionView[];
  status: { label: string; className: string };
  disabled: boolean;
  headingInput: string;
  heightInput: string;
  onHeadingInputChange: (value: string) => void;
  onHeightInputChange: (value: string) => void;
  onClusterChange: (value: string) => void;
  onMajorMissionChange: (value: string) => void;
  onVariantChange: (value: string) => void;
  onMotionChange: (value: string) => void;
}) {
  return (
    <section
      id="twin-campaign-workspace-panel-catalog"
      className="campaign-catalog-workspace"
      role="tabpanel"
      aria-labelledby="twin-campaign-workspace-tab-catalog"
    >
      <div className="campaign-catalog-controls">
        <div className="campaign-filter" role="group" aria-label="Fleet size">
          <button type="button" className="is-selected">1D</button>
          <button type="button" disabled>2D</button>
          <button type="button" disabled>3D</button>
        </div>
        <CampaignDropdown
          label="Mission cluster"
          level={1}
          value={selectedClusterId}
          options={clusters.map((cluster) => ({
            value: cluster.clusterId,
            label: cluster.clusterName,
            meta: cluster.detail,
          }))}
          onChange={onClusterChange}
          disabled={disabled}
        />
        <CampaignDropdown
          label="Major mission"
          level={2}
          value={selected.majorMission}
          options={majorMissions.map((value) => ({ value, label: value }))}
          onChange={onMajorMissionChange}
          disabled={disabled}
        />
        <CampaignDropdown
          label="Variant"
          level={3}
          value={selected.variant}
          options={variants.map((value) => {
            const state = catalog.motions.find(
              (motion) => motion.clusterId === selectedClusterId
                && motion.majorMission === selected.majorMission
                && motion.variant === value,
            )?.implementationState ?? "READY";
            return {
              value,
              label: value,
              badge: state === "RAW" ? "Raw" : state === "SETUP_REQUIRED" ? "Unavailable" : "Ready",
              badgeClassName: state === "READY" ? "state-ready" : "state-blocked",
              badgePresentation: "dot" as const,
            };
          })}
          onChange={onVariantChange}
          disabled={disabled}
        />
        <CampaignDropdown
          label="Motion"
          level={4}
          value={motionSelectionKey(selected)}
          options={motions.map((motion) => ({
            value: motionSelectionKey(motion),
            label: motion.motion,
            meta: motion.summary,
          }))}
          onChange={onMotionChange}
          disabled={disabled}
        />
      </div>

      <div className="campaign-case-detail">
        <header className="campaign-case-detail-header">
          <div><h3>{selected.motion}</h3></div>
          <span className={`campaign-status ${status.className}`}>{status.label}</span>
        </header>
        <article className="campaign-case-summary">
          {selected.clusterId === "controller-characterization-tuning"
            && selected.placementMarker ? (
            <section className="twin-run-preparation" aria-label="Run setup">
              <header>
                <span>Run setup</span>
                <strong>Marker {selected.placementMarker}</strong>
              </header>
              <label>
                <span>Heading</span>
                <div><input
                  type="number"
                  min="0"
                  max="90"
                  step="1"
                  inputMode="decimal"
                  value={headingInput}
                  disabled={disabled}
                  aria-label="Heading (degrees)"
                  aria-describedby="twin-heading-help"
                  onChange={(event) => onHeadingInputChange(event.target.value)}
                /><em>deg</em></div>
                <small id="twin-heading-help">0 = front +Y · 45 = between +Y/+X · 90 = front +X</small>
              </label>
              <label>
                <span>{selected.physicalScope === "FIXTURE_OBSERVATION"
                  ? "Sensor height"
                  : "Flight height"}</span>
                <div><input
                  type="number"
                  min={selected.physicalScope === "FIXTURE_OBSERVATION" ? "0" : "0.01"}
                  max="0.5"
                  step="0.01"
                  inputMode="decimal"
                  value={heightInput}
                  disabled={disabled}
                  placeholder={selected.physicalScope === "FIXTURE_OBSERVATION"
                    ? "Optional"
                    : "Required"}
                  aria-label={selected.physicalScope === "FIXTURE_OBSERVATION"
                    ? "Sensor height (metres)"
                    : "Flight height (metres)"}
                  aria-describedby="twin-height-help"
                  onChange={(event) => onHeightInputChange(event.target.value)}
                /><em>m</em></div>
                <small id="twin-height-help">{selected.physicalScope === "FIXTURE_OBSERVATION"
                  ? "Optional grounded sensor-center height"
                  : "Required height above the fixture floor"}</small>
              </label>
            </section>
          ) : null}
          {selected.clusterId === "controller-characterization-tuning"
            && catalog.controllerTuningFixture?.state !== "READY" ? (
            <div className="twin-lab-setup-note" role="status">
              <CircleAlert size={14} />
              <span>
                <strong>Characterization incomplete</strong>
                <small>{catalog.controllerTuningFixture?.detail}</small>
              </span>
            </div>
          ) : null}
          {selected.blockReason && (
            selected.implementationState === "RAW"
            || selected.clusterId !== "controller-characterization-tuning"
          ) ? (
            <div className="twin-lab-setup-note" role="status">
              <CircleAlert size={14} />
              <span><strong>{selected.implementationState === "RAW" ? "Raw stage" : "Unavailable"}</strong><small>{selected.blockReason}</small></span>
            </div>
          ) : null}
          <div className="campaign-case-objective">
            <span>Learning objective</span>
            <p>{selected.summary}</p>
          </div>
          <div className="campaign-case-highlights">
            <div>
              <span>What it does</span>
              <p>{selected.steps.length > 0
                ? selected.steps.map((step) => step.title).join(" → ")
                : "No executable sequence yet"}</p>
            </div>
            <div>
              <span>Expected outcome</span>
              <p>{selected.implementationState === "RAW"
                ? "This stage remains visible without an executable workflow."
                : selected.physicalScope === "FIXTURE_OBSERVATION"
                  ? "The grounded drone sends no flight command and retains measured telemetry."
                  : "The paired physical drone lands after retaining measured telemetry."}</p>
            </div>
          </div>
          <details className="campaign-case-technical">
            <summary>
              <span>Technical criteria</span>
              <strong>{selected.steps.length} steps · {selected.learningSignals.length} signals</strong>
            </summary>
            <div>
              <div><span>Scope</span><p>{scopeLabel(selected.physicalScope)} · {selected.physicalExecution === "OPERATOR_GATED" ? "One operator action per physical run" : "Physical execution not enabled"}</p></div>
              {selected.blockReason
                && selected.implementationState === "SETUP_REQUIRED"
                && selected.clusterId === "controller-characterization-tuning" ? (
                <div><span>Command prerequisite</span><p>{selected.blockReason}</p></div>
              ) : null}
              <div><span>Learning signals</span><p>{selected.learningSignals.length > 0 ? selected.learningSignals.join(" · ") : "Not defined"}</p></div>
              <div><span>Qualification</span><p>{catalog.qualificationClaim === "NONE" ? "Learning data only; no qualification claim" : catalog.qualificationClaim}</p></div>
            </div>
          </details>
        </article>
      </div>
    </section>
  );
}

function MotionSequence({ motion }: { motion: TwinBasicFlightMotionView }) {
  return (
    <article className="twin-motion-sequence">
      <header>
        <div><strong>{motion.motion}</strong><small>{motion.summary}</small></div>
        <span>{motion.steps.length} steps</span>
      </header>
      {motion.steps.length > 0 ? <ol>
        {motion.steps.map((step) => (
          <li key={step.stepId}>
            <span>{step.title}</span>
            <small>{step.behavior} {step.containment}</small>
          </li>
        ))}
      </ol> : <p>No executable sequence is attached to this raw stage.</p>}
    </article>
  );
}

function SafetyScope({ motion }: { motion: TwinBasicFlightMotionView }) {
  return (
    <div className="twin-lab-safety-note">
      <ShieldCheck size={14} />
      <span>
        <strong>{motion.physicalScope === "FIXTURE_OBSERVATION"
          ? "Motors-off observation"
          : motion.motionId === "arm-disarm"
            ? "Physical ground action"
            : "Physical flight"}</strong>
        <small>{motion.physicalExecution === "OPERATOR_GATED"
          ? motion.physicalScope === "FIXTURE_OBSERVATION"
            ? "The paired drone remains grounded with motors off while measured ranger and state telemetry is retained."
            : motion.motionId === "arm-disarm"
            ? "The paired drone arms on the ground for three seconds while telemetry is recorded, then disarms without takeoff."
            : `The paired drone performs “${motion.motion}” at the configured height, then lands and disarms. Abort and land remains available throughout.`
          : "Physical execution is not enabled for this mission."}</small>
      </span>
    </div>
  );
}

function TwinReview({
  run,
  selected,
}: {
  run?: TwinBasicFlightRunView;
  selected?: TwinBasicFlightMotionView;
}) {
  if (!run) {
    return (
      <section
        id="twin-campaign-workspace-panel-review"
        className="campaign-review-workspace"
        role="tabpanel"
        aria-labelledby="twin-campaign-workspace-tab-review"
      >
        <div className="campaign-workspace-empty"><CircleAlert size={16} />No physical run has been recorded in this workspace yet</div>
      </section>
    );
  }
  return (
    <section
      id="twin-campaign-workspace-panel-review"
      className="campaign-review-workspace"
      role="tabpanel"
      aria-labelledby="twin-campaign-workspace-tab-review"
    >
      <div className="campaign-review-journal">
        <section className="campaign-run-history" aria-label="Digital Twin physical runs">
          <header><span>Run history</span><strong>1</strong></header>
          <div className="campaign-run-history-list">
            <article className="is-selected">
              <button type="button" aria-pressed="true">
                <span><strong>Run 1</strong><small>{selected?.motion ?? run.motionId}</small></span>
                <span className="campaign-run-state"><em className={`state-${run.status.toLowerCase()}`}>{run.status === "COMPLETED" ? "Completed" : "Failed"}</em></span>
              </button>
            </article>
          </div>
        </section>
        <section className="campaign-review-detail">
          <header><span>Run 1</span><strong>{run.status === "COMPLETED" ? "Completed" : "Failed"}</strong></header>
          <p>{selected?.summary ?? "The Digital Twin physical action finished."}</p>
          <p className="campaign-run-facts">Real Crazyflie · measured telemetry · no qualification claim</p>
          <div className="campaign-review-detail-body">
            <TwinLearningResult run={run} />
          </div>
        </section>
      </div>
    </section>
  );
}

function TwinLearningResult({ run }: { run: TwinBasicFlightRunView }) {
  const sample = run.learningSample;
  const range = run.controllerTuningRangeSummary;
  const preparation = run.controllerTuningPreparation;
  const metrics = useMemo(() => [
    ...(preparation ? [
      ["Placement", `Marker ${preparation.stationId}`],
      ["Heading", `${preparation.headingDeg.toFixed(1)}°`],
      ["Height", preparation.targetHeightM === undefined
        ? "Not entered"
        : `${preparation.targetHeightM.toFixed(3)} m`],
    ] : []),
    ["Battery", `${sample.batteryStartPercent.toFixed(2)} → ${sample.batteryEndPercent.toFixed(2)}%`],
    ["Minimum voltage", sample.minimumVoltageV === undefined ? "Unavailable" : `${sample.minimumVoltageV.toFixed(3)} V`],
    ["Peak current", sample.maximumCurrentA === undefined ? "Unavailable" : `${sample.maximumCurrentA.toFixed(3)} A`],
    ["Peak motor", sample.peakMotorCommandPercent === undefined ? "Unavailable" : `${sample.peakMotorCommandPercent.toFixed(1)}%`],
    ["Hover RMS drift", sample.hoverRmsDriftM === undefined ? "Not sampled" : `${sample.hoverRmsDriftM.toFixed(4)} m`],
    ["Max altitude", `${sample.maximumAltitudeM.toFixed(3)} m`],
    ...(range ? [
      ["Range values", `${range.validRangeValueCount}`],
      [range.predictionSource === "CONFIGURED_PLACEMENT" ? "Placement ↔ fixture" : "Estimator ↔ fixture", range.posePredictionResidualRmsM === undefined ? "Raw only" : `${range.posePredictionResidualRmsM.toFixed(4)} m RMS`],
      ["Opposing sums", range.opposingRangeSumResidualRmsM === undefined ? "Unavailable" : `${range.opposingRangeSumResidualRmsM.toFixed(4)} m RMS`],
      ["Estimator ↔ range pose", range.estimatorToRangeXyRmsM === undefined ? "Unavailable" : `${range.estimatorToRangeXyRmsM.toFixed(4)} m RMS`],
    ] : []),
  ], [preparation, range, sample]);
  return (
    <article className="twin-learning-result" aria-label="Learning observation">
      <header><Database size={14} /><span><strong>Learning observation retained</strong><small>Not a battery test or qualification result</small></span></header>
      <dl>
        {metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
      <small>{sample.landingContactObserved ? "Landing contact observed" : "No landing contact"} · Final state {sample.finalState} · {run.telemetryRowCount === undefined ? "summary retained" : `${run.telemetryRowCount} measured telemetry rows retained`}{range ? ` · Fixture ${range.fixtureId} ${range.fixtureVersion} · ${range.modelStatus === "EVALUATED" ? "range model evaluated" : "raw ranges only"}` : ""} · {run.runId.slice(0, 20)}…</small>
    </article>
  );
}

function scopeLabel(value: TwinBasicFlightMotionView["physicalScope"]): string {
  return value === "PROPS_OFF_BENCH"
    ? "Props-off bench"
    : value === "FIXTURE_OBSERVATION"
      ? "Motors-off fixture observation"
      : "Contained flight";
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function motionSelectionKey(motion?: TwinBasicFlightMotionView): string {
  if (!motion) return "";
  return motion.placementMarker
    ? `${motion.motionId}::${motion.placementMarker}`
    : motion.motionId;
}

function missionClusterLabel(clusterId: string): string {
  if (clusterId === "controller-characterization-tuning") {
    return "Controller characterization & tuning";
  }
  return clusterId
    .split("-")
    .filter(Boolean)
    .map((word, index) => index === 0 ? `${word[0]?.toUpperCase() ?? ""}${word.slice(1)}` : word)
    .join(" ");
}
