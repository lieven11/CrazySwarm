"use client";

import { Beaker, Check, ChevronDown, CircleAlert, Clock3, FastForward, LoaderCircle, Maximize2, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import type { ControlApi } from "../lib/api";
import type {
  CampaignCaseView,
  CampaignCatalogView,
  CampaignRunMode,
  CampaignRunSummary,
  CampaignWorkspaceView,
} from "../lib/models";

const FLEET_SIZES = ["1", "2", "3"] as const;
type FleetSizeFilter = typeof FLEET_SIZES[number];
type ClusterFilter = "all" | CampaignCaseView["cluster"];
type EnvironmentFilter = CampaignCaseView["environment"];
type CampaignWorkspaceTab = "catalog" | "run" | "review";

const CAMPAIGN_WORKSPACE_PREFERENCES_KEY = "crazyswarm.campaign-workspace.v1";
const CAMPAIGN_WORKSPACE_TABS: ReadonlyArray<{ id: CampaignWorkspaceTab; label: string }> = [
  { id: "catalog", label: "Catalog" },
  { id: "run", label: "Active run" },
  { id: "review", label: "Review" },
];

export const MISSION_CLUSTERS: ReadonlyArray<{
  id: CampaignCaseView["cluster"];
  label: string;
}> = [
  {
    id: "BASIC_FLIGHT_AND_ROUTE_FOLLOWING",
    label: "Basic flight & routes",
  },
  {
    id: "GEOMETRIC_CONFLICT_RESOLUTION",
    label: "Conflict resolution",
  },
  {
    id: "CONSTRAINTS_AND_OPTIMIZATION",
    label: "Constraints & optimization",
  },
  {
    id: "COORDINATION_AND_ALLOCATION",
    label: "Coordination & allocation",
  },
  {
    id: "FAILURE_RECOVERY_AND_REPLANNING",
    label: "Recovery & replanning",
  },
];

type CampaignDropdownOption = {
  value: string;
  label: string;
  meta?: string;
  badge?: string;
  badgeClassName?: string;
};

export function humanizeCampaignValue(value: string): string {
  const words = value.replaceAll("_", " ").trim().toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : value;
}

function lifecycleLabel(value: string): string {
  const labels: Record<string, string> = {
    ACTIVE_DEVELOPMENT: "In progress",
    BASELINED: "Reviewed",
    BLOCKED: "Blocked",
    DEFINED_NOT_RUN: "Not started",
    PROMOTED: "Completed",
    READY: "Ready",
  };
  return labels[value] ?? humanizeCampaignValue(value);
}

export function CampaignDropdown({
  label,
  value,
  options,
  onChange,
  searchable = false,
}: {
  label: string;
  value: string;
  options: CampaignDropdownOption[];
  onChange: (value: string) => void;
  searchable?: boolean;
}) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = options.find((option) => option.value === value) ?? options[0];
  const visibleOptions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((option) => (
      `${option.label} ${option.meta ?? ""} ${option.badge ?? ""}`
        .toLowerCase()
        .includes(needle)
    ));
  }, [options, query]);
  const [highlighted, setHighlighted] = useState(0);

  const openMenu = () => {
    setHighlighted(Math.max(0, options.findIndex((option) => option.value === value)));
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    (searchable ? searchRef.current : listRef.current)?.focus();

    const closeOnOutsidePress = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("pointerdown", closeOnOutsidePress);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePress);
  }, [open, searchable]);

  const close = () => {
    setOpen(false);
    setQuery("");
    triggerRef.current?.focus();
  };

  const select = (option: CampaignDropdownOption) => {
    onChange(option.value);
    close();
  };

  const handleListKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!visibleOptions.length) return;
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setHighlighted((current) => (current + direction + visibleOptions.length) % visibleOptions.length);
      listRef.current?.focus();
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setHighlighted(event.key === "Home" ? 0 : Math.max(0, visibleOptions.length - 1));
      listRef.current?.focus();
      return;
    }
    if (event.key === "Enter" && visibleOptions[highlighted]) {
      event.preventDefault();
      select(visibleOptions[highlighted]);
    }
  };

  const openWithKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      openMenu();
    }
  };

  return (
    <div className="campaign-dropdown" ref={rootRef}>
      <span className="campaign-dropdown-label">{label}</span>
      <button
        ref={triggerRef}
        type="button"
        className="campaign-dropdown-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-listbox`}
        disabled={!selected}
        onClick={() => open ? close() : openMenu()}
        onKeyDown={openWithKeyboard}
      >
        <span>
          <strong>{selected?.label ?? "No matching cases"}</strong>
          {selected?.meta ? <small>{selected.meta}</small> : null}
        </span>
        {selected?.badge ? (
          <em className={selected.badgeClassName}>{selected.badge}</em>
        ) : null}
        <ChevronDown className={open ? "is-open" : ""} size={14} />
      </button>
      {open ? (
        <div className="campaign-dropdown-popover">
          {searchable ? (
            <label className="campaign-dropdown-search">
              <span className="sr-only">Search {label.toLowerCase()}</span>
              <input
                ref={searchRef}
                type="search"
                value={query}
                placeholder="Search mission cases…"
                onChange={(event) => {
                  setQuery(event.target.value);
                  setHighlighted(0);
                }}
                onKeyDown={handleListKeyDown}
              />
            </label>
          ) : null}
          <div
            ref={listRef}
            id={`${id}-listbox`}
            className={`campaign-dropdown-list ${options.some((option) => option.badge) ? "has-status" : ""}`}
            role="listbox"
            aria-label={label}
            tabIndex={-1}
            onKeyDown={handleListKeyDown}
          >
            {visibleOptions.map((option, index) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                className={`${index === highlighted ? "is-highlighted" : ""} ${option.value === value ? "is-selected" : ""}`}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => select(option)}
              >
                {option.badge ? <em className={option.badgeClassName}>{option.badge}</em> : null}
                <span>
                  <strong>{option.label}</strong>
                  {option.meta ? <small>{option.meta}</small> : null}
                </span>
                {option.value === value ? <Check size={13} /> : <i aria-hidden="true" />}
              </button>
            ))}
            {!visibleOptions.length ? (
              <p className="campaign-dropdown-empty">No mission cases match that search.</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

const clusterOrder = new Map(MISSION_CLUSTERS.map((item, index) => [item.id, index]));

export function filterCampaignCases(
  cases: CampaignCaseView[],
  environment: EnvironmentFilter,
  cluster: ClusterFilter,
  fleetSize: FleetSizeFilter,
): CampaignCaseView[] {
  return cases
    .filter((item) => item.environment === environment)
    .filter((item) => cluster === "all" || item.cluster === cluster)
    .filter((item) => item.drone_count === Number(fleetSize))
    .toSorted((left, right) =>
      (clusterOrder.get(left.cluster) ?? 99) - (clusterOrder.get(right.cluster) ?? 99)
      || left.drone_count - right.drone_count
      || left.difficulty - right.difficulty
      || left.family.localeCompare(right.family)
      || left.variation_name.localeCompare(right.variation_name));
}

export function CampaignLab({
  api,
  onNotice,
  onActiveCaseChange,
  onCampaignRunChange,
  onExecutionModeChange,
}: {
  api: ControlApi;
  onNotice: (message: string) => void;
  onActiveCaseChange?: (campaignCase: CampaignCaseView | undefined) => void;
  onCampaignRunChange?: (run: CampaignRunSummary | undefined) => void;
  onExecutionModeChange?: (mode: CampaignRunMode) => void;
}) {
  const [open, setOpen] = useState(false);
  const [workspaceTab, setWorkspaceTab] = useState<CampaignWorkspaceTab>("catalog");
  const [preferencesReady, setPreferencesReady] = useState(false);
  const [catalog, setCatalog] = useState<CampaignCatalogView>();
  const [workspace, setWorkspace] = useState<CampaignWorkspaceView>();
  const [selectedId, setSelectedId] = useState("");
  const [environment, setEnvironment] = useState<EnvironmentFilter>("SIMULATION");
  const [fleetSize, setFleetSize] = useState<FleetSizeFilter>("1");
  const [cluster, setCluster] = useState<ClusterFilter>("all");
  const [runMode, setRunMode] = useState<CampaignRunMode>("OPERATOR_OBSERVED_REALTIME");
  const [busy, setBusy] = useState<string>();
  const [preview, setPreview] = useState<Record<string, unknown>>();
  const [advanced, setAdvanced] = useState(false);
  const [seed, setSeed] = useState("42");
  const [repetitions, setRepetitions] = useState("1");
  const [observation, setObservation] = useState("");
  const launcherRef = useRef<HTMLButtonElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const selectedIdRef = useRef(selectedId);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  /* Local storage is an external preference source hydrated after mount. */
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(CAMPAIGN_WORKSPACE_PREFERENCES_KEY);
      if (stored) {
        const preferences = JSON.parse(stored) as Record<string, unknown>;
        if (typeof preferences.open === "boolean") setOpen(preferences.open);
        if (CAMPAIGN_WORKSPACE_TABS.some((tab) => tab.id === preferences.tab)) {
          setWorkspaceTab(preferences.tab as CampaignWorkspaceTab);
        }
        if (preferences.environment === "SIMULATION" || preferences.environment === "REAL") {
          setEnvironment(preferences.environment);
        }
        if (FLEET_SIZES.includes(preferences.fleetSize as FleetSizeFilter)) {
          setFleetSize(preferences.fleetSize as FleetSizeFilter);
        }
        if (
          preferences.cluster === "all"
          || MISSION_CLUSTERS.some((item) => item.id === preferences.cluster)
        ) {
          setCluster(preferences.cluster as ClusterFilter);
        }
        if (
          preferences.runMode === "AUTOMATED_ACCELERATED"
          || preferences.runMode === "OPERATOR_OBSERVED_REALTIME"
        ) {
          setRunMode(preferences.runMode);
        }
        if (typeof preferences.selectedId === "string") setSelectedId(preferences.selectedId);
      }
    } catch {
      window.localStorage.removeItem(CAMPAIGN_WORKSPACE_PREFERENCES_KEY);
    } finally {
      setPreferencesReady(true);
    }
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (!preferencesReady) return;
    window.localStorage.setItem(CAMPAIGN_WORKSPACE_PREFERENCES_KEY, JSON.stringify({
      open,
      tab: workspaceTab,
      environment,
      fleetSize,
      cluster,
      runMode,
      selectedId,
    }));
  }, [cluster, environment, fleetSize, open, preferencesReady, runMode, selectedId, workspaceTab]);

  useEffect(() => {
    onExecutionModeChange?.(runMode);
  }, [onExecutionModeChange, runMode]);

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

  const refresh = async () => {
    const [nextCatalog, nextWorkspace] = await Promise.all([api.campaignCatalog(), api.campaignState()]);
    setCatalog(nextCatalog);
    setWorkspace(nextWorkspace);
    setSelectedId((current) => current || nextWorkspace.active_case_id || nextCatalog.cases[0]?.case_id || "");
  };

  useEffect(() => {
    if (!preferencesReady || catalog) return;
    let cancelled = false;
    void Promise.all([api.campaignCatalog(), api.campaignState()])
      .then(([nextCatalog, nextWorkspace]) => {
        if (cancelled) return;
        const preferredId = selectedIdRef.current;
        const initialCase = nextCatalog.cases.find(
          (item) => item.case_id === preferredId,
        ) ?? nextCatalog.cases.find(
          (item) => item.case_id === nextWorkspace.active_case_id,
        ) ?? nextCatalog.cases.find(
          (item) => item.environment === "SIMULATION" && item.drone_count === 1,
        ) ?? nextCatalog.cases[0];
        setCatalog(nextCatalog);
        setWorkspace(nextWorkspace);
        setSelectedId(initialCase?.case_id ?? "");
        if (initialCase && !preferredId) {
          setEnvironment(initialCase.environment);
          setFleetSize(String(initialCase.drone_count) as FleetSizeFilter);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          onNotice(error instanceof Error ? error.message : "Campaign catalog unavailable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, catalog, onNotice, preferencesReady]);

  const cases = useMemo(
    () => filterCampaignCases(catalog?.cases ?? [], environment, cluster, fleetSize),
    [catalog, environment, cluster, fleetSize],
  );
  const selected = cases.find((item) => item.case_id === selectedId);
  const active = catalog?.cases.find((item) => item.case_id === workspace?.active_case_id);
  const activeCampaignRun = workspace?.runs.toReversed().find((run) => (
    run.locked_inputs.case_id === workspace.active_case_id
    && (run.status === "QUEUED" || run.status === "RUNNING")
  ));
  const latestReview = workspace?.reviews.at(-1);

  useEffect(() => {
    if (!catalog || !workspace) return;
    onActiveCaseChange?.(active);
    if (activeCampaignRun) onCampaignRunChange?.(activeCampaignRun);
  }, [active, activeCampaignRun, catalog, onActiveCaseChange, onCampaignRunChange, workspace]);

  useEffect(() => {
    if (!activeCampaignRun) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const nextWorkspace = await api.campaignState();
        if (cancelled) return;
        setWorkspace(nextWorkspace);
        const tracked = nextWorkspace.runs.find((run) => run.run_id === activeCampaignRun.run_id);
        if (tracked?.status === "QUEUED" || tracked?.status === "RUNNING") {
          timer = window.setTimeout(poll, 500);
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(poll, 2_000);
      }
    };
    timer = window.setTimeout(poll, 500);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeCampaignRun, api]);

  const availableFleetSizes = useMemo(() => new Set(
    (catalog?.cases ?? [])
      .filter((item) => item.environment === environment)
      .filter((item) => cluster === "all" || item.cluster === cluster)
      .map((item) => String(item.drone_count) as FleetSizeFilter),
  ), [catalog, cluster, environment]);
  const clusterOptions = useMemo<CampaignDropdownOption[]>(() => [
    {
      value: "all",
      label: "All mission clusters",
    },
    ...MISSION_CLUSTERS.map((item) => ({
      value: item.id,
      label: item.label,
    })),
  ], []);
  const caseOptions = useMemo<CampaignDropdownOption[]>(() => cases.map((item) => ({
    value: item.case_id,
    label: humanizeCampaignValue(item.family),
    meta: humanizeCampaignValue(item.variation_name),
    badge: lifecycleLabel(item.lifecycle),
    badgeClassName: `state-${item.lifecycle.toLowerCase()}`,
  })), [cases]);

  const chooseFilters = (
    nextEnvironment: EnvironmentFilter,
    nextCluster: ClusterFilter,
    nextFleetSize: FleetSizeFilter,
    useAvailableFleetFallback = false,
  ) => {
    let resolvedFleetSize = nextFleetSize;
    let matching = filterCampaignCases(
      catalog?.cases ?? [],
      nextEnvironment,
      nextCluster,
      resolvedFleetSize,
    );
    if (useAvailableFleetFallback && !matching.length) {
      const firstAvailable = FLEET_SIZES.find((candidate) => (
        filterCampaignCases(
          catalog?.cases ?? [],
          nextEnvironment,
          nextCluster,
          candidate,
        ).length > 0
      ));
      if (firstAvailable) {
        resolvedFleetSize = firstAvailable;
        matching = filterCampaignCases(
          catalog?.cases ?? [],
          nextEnvironment,
          nextCluster,
          resolvedFleetSize,
        );
      }
    }
    setEnvironment(nextEnvironment);
    setCluster(nextCluster);
    setFleetSize(resolvedFleetSize);
    if (!matching.some((item) => item.case_id === selectedId)) {
      setSelectedId(matching[0]?.case_id ?? "");
      setPreview(undefined);
    }
  };

  const act = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    try {
      await action();
      await refresh();
      onNotice(label);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : `${label} failed`);
    } finally {
      setBusy(undefined);
    }
  };

  const footerActions = (
    <div className="campaign-actions">
      <button type="button" disabled={!selected || Boolean(busy)} onClick={() => selected && void act("Static validation complete", () => api.staticValidateCampaignCase(selected.case_id))}>Validate</button>
      <button type="button" disabled={!selected || selected.case_id === active?.case_id || selected.environment === "REAL" || selected.implementation_status !== "EXECUTABLE" || Boolean(busy)} onClick={() => selected && void act("Active mission locked", () => api.setActiveCampaignCase(selected.case_id, "operator selected in campaign workspace"))}>Set active</button>
      <button type="button" disabled={!active || Boolean(busy)} onClick={() => void act("Plan preview ready", async () => {
        setPreview(await api.previewActiveCampaign());
        setWorkspaceTab("run");
      })}>Preview plan</button>
    </div>
  );

  const workspaceOverlay = open && typeof document !== "undefined" ? createPortal(
    <div className="campaign-workspace-backdrop">
      <section
        ref={workspaceRef}
        className="campaign-workspace"
        role="dialog"
        aria-modal="true"
        aria-labelledby="campaign-workspace-title"
      >
        <header className="campaign-workspace-header">
          <div className="campaign-workspace-title">
            <span><Beaker size={17} /></span>
            <div>
              <h2 id="campaign-workspace-title">Campaign Laboratory</h2>
              <small>{active
                ? `Active · ${humanizeCampaignValue(active.family)} · ${lifecycleLabel(active.lifecycle)}`
                : "No active mission"}</small>
            </div>
          </div>
          <div className="campaign-filter campaign-workspace-environment" role="group" aria-label="Environment">
            {(["SIMULATION", "REAL"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={environment === value ? "is-selected" : ""}
                onClick={() => chooseFilters(value, cluster, fleetSize, true)}
              >
                {value === "SIMULATION" ? "Simulation" : "Real"}
              </button>
            ))}
          </div>
          <button ref={closeButtonRef} className="campaign-workspace-close" type="button" aria-label="Close Campaign Laboratory" onClick={() => setOpen(false)}><X size={18} /></button>
        </header>

        <div className="campaign-workspace-tabs" role="tablist" aria-label="Campaign Laboratory sections">
          {CAMPAIGN_WORKSPACE_TABS.map((tab) => (
            <button
              key={tab.id}
              id={`campaign-workspace-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={workspaceTab === tab.id}
              aria-controls={`campaign-workspace-panel-${tab.id}`}
              className={workspaceTab === tab.id ? "is-selected" : ""}
              onClick={() => setWorkspaceTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="campaign-workspace-body">
          {!catalog ? <div className="campaign-loading"><LoaderCircle className="spin" size={16} />Loading campaign workspace</div> : null}

          {catalog && workspaceTab === "catalog" ? (
            <section id="campaign-workspace-panel-catalog" className="campaign-catalog-workspace" role="tabpanel" aria-labelledby="campaign-workspace-tab-catalog">
              <div className="campaign-catalog-controls">
                <div className="campaign-filter" role="group" aria-label="Fleet size">
                  {FLEET_SIZES.map((value) => (
                    <button
                      key={value}
                      type="button"
                      className={fleetSize === value ? "is-selected" : ""}
                      disabled={!availableFleetSizes.has(value)}
                      onClick={() => chooseFilters(environment, cluster, value)}
                    >
                      {value}D
                    </button>
                  ))}
                </div>
                <CampaignDropdown
                  label="Mission cluster"
                  value={cluster}
                  options={clusterOptions}
                  onChange={(nextCluster) => chooseFilters(
                    environment,
                    nextCluster as ClusterFilter,
                    fleetSize,
                    true,
                  )}
                />
                <CampaignDropdown
                  label="Mission case"
                  value={selectedId}
                  options={caseOptions}
                  searchable
                  onChange={(nextCaseId) => {
                    setSelectedId(nextCaseId);
                    setPreview(undefined);
                  }}
                />
              </div>
              <div className="campaign-case-detail">
                {selected ? (
                  <>
                    <header className="campaign-case-detail-header">
                      <div>
                        <small>{humanizeCampaignValue(selected.variation_name)}</small>
                        <h3>{humanizeCampaignValue(selected.family)}</h3>
                      </div>
                      <span className={`campaign-status state-${selected.lifecycle.toLowerCase()}`}>{lifecycleLabel(selected.lifecycle)}</span>
                    </header>
                    <CaseSummary campaignCase={selected} />
                  </>
                ) : <div className="campaign-workspace-empty"><CircleAlert size={16} />Select a mission case</div>}
              </div>
            </section>
          ) : null}

          {catalog && workspaceTab === "run" ? (
            <section id="campaign-workspace-panel-run" className="campaign-run-workspace" role="tabpanel" aria-labelledby="campaign-workspace-tab-run">
              {active ? (
                <header className="campaign-case-detail-header">
                  <div><small>Active mission</small><h3>{humanizeCampaignValue(active.family)}</h3></div>
                  <span className={`campaign-status state-${active.lifecycle.toLowerCase()}`}>{lifecycleLabel(active.lifecycle)}</span>
                </header>
              ) : <div className="campaign-workspace-empty"><CircleAlert size={16} />Choose and activate a mission from the Catalog tab</div>}
              {activeCampaignRun ? <div className="campaign-running"><LoaderCircle className="spin" size={14} />{humanizeCampaignValue(activeCampaignRun.status)} run</div> : null}
              <button className="campaign-advanced-toggle" type="button" aria-expanded={advanced} onClick={() => setAdvanced((value) => !value)}>Advanced inputs <ChevronDown className={advanced ? "is-open" : ""} size={13} /></button>
              {advanced ? (
                <div className="campaign-advanced">
                  <label>Seed<input type="number" min="0" value={seed} onChange={(event) => setSeed(event.target.value)} /></label>
                  <label>Repetitions<input type="number" min="1" max="100" value={repetitions} onChange={(event) => setRepetitions(event.target.value)} /></label>
                  <button type="button" disabled={!active || Boolean(busy)} onClick={() => {
                    if (!active) return;
                    const childId = `${active.case_id}.child-${Date.now()}`;
                    void act("Child case created", () => api.createCampaignChild(childId, { execution: { seed: Number(seed), repetitions: Number(repetitions) } }));
                  }}>Save as new case</button>
                </div>
              ) : null}
              {preview ? <PlanPreview value={preview} /> : null}
              <div className="campaign-run-mode" role="radiogroup" aria-label="Campaign execution mode">
                <button
                  type="button"
                  role="radio"
                  aria-checked={runMode === "OPERATOR_OBSERVED_REALTIME"}
                  className={runMode === "OPERATOR_OBSERVED_REALTIME" ? "is-selected mode-realtime" : ""}
                  disabled={Boolean(activeCampaignRun)}
                  onClick={() => setRunMode("OPERATOR_OBSERVED_REALTIME")}
                ><Clock3 size={14} />Realtime</button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={runMode === "AUTOMATED_ACCELERATED"}
                  className={runMode === "AUTOMATED_ACCELERATED" ? "is-selected mode-accelerated" : ""}
                  disabled={Boolean(activeCampaignRun)}
                  onClick={() => setRunMode("AUTOMATED_ACCELERATED")}
                ><FastForward size={14} />Accelerated</button>
              </div>
            </section>
          ) : null}

          {catalog && workspaceTab === "review" ? (
            <section id="campaign-workspace-panel-review" className="campaign-review-workspace" role="tabpanel" aria-labelledby="campaign-workspace-tab-review">
              {latestReview ? (
                <section className="campaign-review">
                  <header><span>Latest review</span><strong>{humanizeCampaignValue(latestReview.status)}</strong></header>
                  <p>{latestReview.analysis.primary_cause.reason}</p>
                  <label className="campaign-observation-field">
                    <span>Operator comment</span>
                    <textarea aria-label="Operator observation" placeholder={latestReview.operator_questions[0] ?? "Add an operator observation"} value={observation} onChange={(event) => setObservation(event.target.value)} />
                  </label>
                  <div>
                    <button type="button" disabled={!observation.trim() || Boolean(busy)} onClick={() => void act("Observation added", async () => { await api.addCampaignObservation(latestReview.review_id, observation); setObservation(""); })}>Add note</button>
                    <button type="button" disabled={Boolean(busy)} onClick={() => void act("Review approved", () => api.decideCampaignReview(latestReview.review_id, "APPROVE", "operator approved campaign evidence"))}><Check size={12} />Approve</button>
                    <button type="button" disabled={Boolean(busy)} onClick={() => void act("Rerun requested", () => api.decideCampaignReview(latestReview.review_id, "NEEDS_RERUN", "operator requested same-input rerun"))}>Needs rerun</button>
                  </div>
                </section>
              ) : <div className="campaign-workspace-empty"><CircleAlert size={16} />No review is available yet</div>}
            </section>
          ) : null}
        </div>

        <footer className="campaign-workspace-footer">
          {footerActions}
        </footer>
      </section>
    </div>,
    document.body,
  ) : null;

  return (
    <>
      <section className="campaign-lab" aria-label="Mission development laboratory">
        <button ref={launcherRef} className="campaign-lab-toggle" type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
          <Beaker size={15} />
          <span><strong>Campaign Laboratory</strong>{active ? <small>Active · {humanizeCampaignValue(active.family)} · {lifecycleLabel(active.lifecycle)}</small> : <small>Open mission development workspace</small>}</span>
          <em>Open <Maximize2 size={13} /></em>
        </button>
      </section>
      {workspaceOverlay}
    </>
  );
}

export function CaseSummary({ campaignCase }: { campaignCase: CampaignCaseView }) {
  return (
    <article className="campaign-case-summary">
      <div><span>What it does</span><p>{campaignCase.behavior_under_test}</p></div>
      <div><span>Expected outcome</span><p>{campaignCase.expected_outcome}</p></div>
    </article>
  );
}

function PlanPreview({ value }: { value: Record<string, unknown> }) {
  const plan = value.plan && typeof value.plan === "object" ? value.plan as Record<string, unknown> : {};
  const candidates = Array.isArray(plan.retained_candidates) ? plan.retained_candidates : [];
  const selectedIndex = typeof plan.selected_candidate_index === "number" ? plan.selected_candidate_index : -1;
  const selected = selectedIndex >= 0 && typeof candidates[selectedIndex] === "object" ? candidates[selectedIndex] as Record<string, unknown> : undefined;
  return (
    <article className="campaign-plan-preview">
      <header><span>PLAN PREVIEW</span><strong>{humanizeCampaignValue(String(selected?.strategy ?? plan.status ?? "BLOCKED"))}</strong></header>
      <p>{String(plan.optimality_claim ?? plan.blocking_reason ?? "Bounded plan ready")}</p>
    </article>
  );
}
