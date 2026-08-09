"use client";

import { Beaker, Check, ChevronDown, CircleAlert, LoaderCircle, Play, RotateCcw } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { ControlApi } from "../lib/api";
import type { CampaignCaseView, CampaignCatalogView, CampaignWorkspaceView } from "../lib/models";

const FLEET_SIZES = ["1", "2", "3"] as const;
type FleetSizeFilter = typeof FLEET_SIZES[number];
type ClusterFilter = "all" | CampaignCaseView["cluster"];
type EnvironmentFilter = CampaignCaseView["environment"];

export const MISSION_CLUSTERS: ReadonlyArray<{
  id: CampaignCaseView["cluster"];
  label: string;
  description: string;
}> = [
  {
    id: "BASIC_FLIGHT_AND_ROUTE_FOLLOWING",
    label: "Basic flight & routes",
    description: "Takeoff, tracking, smooth routes, goals, boundaries, and landing.",
  },
  {
    id: "GEOMETRIC_CONFLICT_RESOLUTION",
    label: "Conflict resolution",
    description: "Separation through timing, speed, detours, or altitude.",
  },
  {
    id: "CONSTRAINTS_AND_OPTIMIZATION",
    label: "Constraints & optimization",
    description: "Hard limits and objective-ordered planner decisions.",
  },
  {
    id: "COORDINATION_AND_ALLOCATION",
    label: "Coordination & allocation",
    description: "Roles, task ownership, priority, reserve selection, and handover.",
  },
  {
    id: "FAILURE_RECOVERY_AND_REPLANNING",
    label: "Recovery & replanning",
    description: "Safe rejection, atomic replanning, recovery, and abort behavior.",
  },
];

type CampaignDropdownOption = {
  value: string;
  label: string;
  meta?: string;
  description?: string;
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
      `${option.label} ${option.meta ?? ""} ${option.description ?? ""} ${option.badge ?? ""}`
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
              <small>{visibleOptions.length} of {options.length}</small>
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
                  {option.description ? <small>{option.description}</small> : null}
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

export function CampaignLab({ api, onNotice }: { api: ControlApi; onNotice: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<CampaignCatalogView>();
  const [workspace, setWorkspace] = useState<CampaignWorkspaceView>();
  const [selectedId, setSelectedId] = useState("");
  const [environment, setEnvironment] = useState<EnvironmentFilter>("SIMULATION");
  const [fleetSize, setFleetSize] = useState<FleetSizeFilter>("1");
  const [cluster, setCluster] = useState<ClusterFilter>("all");
  const [busy, setBusy] = useState<string>();
  const [preview, setPreview] = useState<Record<string, unknown>>();
  const [advanced, setAdvanced] = useState(false);
  const [seed, setSeed] = useState("42");
  const [repetitions, setRepetitions] = useState("1");
  const [observation, setObservation] = useState("");

  const refresh = async () => {
    const [nextCatalog, nextWorkspace] = await Promise.all([api.campaignCatalog(), api.campaignState()]);
    setCatalog(nextCatalog);
    setWorkspace(nextWorkspace);
    setSelectedId((current) => current || nextWorkspace.active_case_id || nextCatalog.cases[0]?.case_id || "");
  };

  useEffect(() => {
    if (!open || catalog) return;
    let cancelled = false;
    void Promise.all([api.campaignCatalog(), api.campaignState()])
      .then(([nextCatalog, nextWorkspace]) => {
        if (cancelled) return;
        const initialCase = nextCatalog.cases.find(
          (item) => item.case_id === nextWorkspace.active_case_id,
        ) ?? nextCatalog.cases.find(
          (item) => item.environment === "SIMULATION" && item.drone_count === 1,
        ) ?? nextCatalog.cases[0];
        setCatalog(nextCatalog);
        setWorkspace(nextWorkspace);
        setSelectedId(initialCase?.case_id ?? "");
        if (initialCase) {
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
  }, [api, open, catalog, onNotice]);

  const cases = useMemo(
    () => filterCampaignCases(catalog?.cases ?? [], environment, cluster, fleetSize),
    [catalog, environment, cluster, fleetSize],
  );
  const selected = cases.find((item) => item.case_id === selectedId);
  const active = catalog?.cases.find((item) => item.case_id === workspace?.active_case_id);
  const latestReview = workspace?.reviews.at(-1);
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
      meta: "Browse the complete catalog",
      description: "Basic execution through recovery and replanning.",
    },
    ...MISSION_CLUSTERS.map((item) => ({
      value: item.id,
      label: item.label,
      meta: item.description,
    })),
  ], []);
  const caseOptions = useMemo<CampaignDropdownOption[]>(() => cases.map((item) => ({
    value: item.case_id,
    label: humanizeCampaignValue(item.family),
    meta: `${humanizeCampaignValue(item.variation_name)} · Difficulty ${item.difficulty}/10 · ${item.drone_count}D`,
    description: item.purpose,
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

  return (
    <section className="campaign-lab" aria-label="Mission development laboratory">
      <button className="campaign-lab-toggle" type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <Beaker size={15} />
        <span><strong>Campaign laboratory</strong>{active ? <small>Active · {active.family}</small> : null}</span>
        <ChevronDown className={open ? "is-open" : ""} size={15} />
      </button>
      {open ? (
        <div className="campaign-lab-body">
          {!catalog ? <div className="campaign-loading"><LoaderCircle className="spin" size={16} />Loading immutable cases</div> : (
            <>
              {workspace?.locked_inputs && active ? (
                <header className="campaign-active-header">
                  <span>ACTIVE DEVELOPMENT</span>
                  <strong>{active.case_id}</strong>
                  <small>seed {workspace.locked_inputs.seed} · {workspace.locked_inputs.backend_profile_id} · planner {workspace.locked_inputs.planner_implementation_version}</small>
                  <code>{workspace.locked_inputs.case_sha256.slice(0, 12)}…</code>
                </header>
              ) : <div className="campaign-no-active"><CircleAlert size={14} />No active development case</div>}

              <div className="campaign-filter campaign-environment-filter" role="group" aria-label="Environment">
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
              {selected ? <CaseSummary campaignCase={selected} /> : null}
              <div className="campaign-actions">
                <button type="button" disabled={!selected || Boolean(busy)} onClick={() => selected && void act("Static validation complete", () => api.staticValidateCampaignCase(selected.case_id))}>Validate</button>
                <button type="button" disabled={!selected || selected.case_id === active?.case_id || selected.environment === "REAL" || selected.implementation_status !== "EXECUTABLE" || Boolean(busy)} onClick={() => selected && void act("Active mission locked", () => api.setActiveCampaignCase(selected.case_id, "operator selected in campaign panel"))}>Set active</button>
                <button type="button" disabled={!active || Boolean(busy)} onClick={() => void act("Plan preview ready", async () => setPreview(await api.previewActiveCampaign()))}>Preview plan</button>
              </div>

              <button className="campaign-advanced-toggle" type="button" aria-expanded={advanced} onClick={() => setAdvanced((value) => !value)}>Bounded advanced inputs <ChevronDown className={advanced ? "is-open" : ""} size={13} /></button>
              {advanced ? (
                <div className="campaign-advanced">
                  <label>Seed<input type="number" min="0" value={seed} onChange={(event) => setSeed(event.target.value)} /></label>
                  <label>Repetitions<input type="number" min="1" max="100" value={repetitions} onChange={(event) => setRepetitions(event.target.value)} /></label>
                  <button type="button" disabled={!active || Boolean(busy)} onClick={() => {
                    if (!active) return;
                    const childId = `${active.case_id}.child-${Date.now()}`;
                    void act("Child case created", () => api.createCampaignChild(childId, { execution: { seed: Number(seed), repetitions: Number(repetitions) } }));
                  }}>Create immutable child</button>
                </div>
              ) : null}

              {preview ? <PlanPreview value={preview} /> : null}
              <div className="campaign-run-actions">
                <button type="button" disabled={!active || Boolean(busy)} onClick={() => void act("Accelerated campaign run complete", () => api.runActiveCampaign("AUTOMATED_ACCELERATED"))}><Play size={13} />Accelerated</button>
                <button type="button" disabled={!active || Boolean(busy)} onClick={() => void act("Realtime observation complete", () => api.runActiveCampaign("OPERATOR_OBSERVED_REALTIME"))}><Play size={13} />Observe realtime</button>
                <button type="button" disabled={!active || Boolean(busy)} onClick={() => void act("Same-input rerun complete", () => api.runActiveCampaign("AUTOMATED_ACCELERATED"))}><RotateCcw size={13} />Same inputs</button>
              </div>

              {latestReview ? (
                <section className="campaign-review">
                  <header><span>REVIEW QUEUE</span><strong>{latestReview.status}</strong></header>
                  <p>{latestReview.analysis.primary_cause.stage} · {Math.round(latestReview.analysis.primary_cause.confidence * 100)}% — {latestReview.analysis.primary_cause.reason}</p>
                  <small>Source-clock motion · aligned wall-clock fleet separation · raw evidence only</small>
                  <textarea aria-label="Operator observation" placeholder={latestReview.operator_questions[0] ?? "Operator observation"} value={observation} onChange={(event) => setObservation(event.target.value)} />
                  <div>
                    <button type="button" disabled={!observation.trim() || Boolean(busy)} onClick={() => void act("Observation added", async () => { await api.addCampaignObservation(latestReview.review_id, observation); setObservation(""); })}>Add note</button>
                    <button type="button" disabled={Boolean(busy)} onClick={() => void act("Review approved", () => api.decideCampaignReview(latestReview.review_id, "APPROVE", "operator approved campaign evidence"))}><Check size={12} />Approve</button>
                    <button type="button" disabled={Boolean(busy)} onClick={() => void act("Rerun requested", () => api.decideCampaignReview(latestReview.review_id, "NEEDS_RERUN", "operator requested same-input rerun"))}>Needs rerun</button>
                  </div>
                </section>
              ) : null}
              {busy ? <div className="campaign-busy"><LoaderCircle className="spin" size={13} />{busy}</div> : null}
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}

export function CaseSummary({ campaignCase }: { campaignCase: CampaignCaseView }) {
  const cluster = MISSION_CLUSTERS.find((item) => item.id === campaignCase.cluster);
  return (
    <article className="campaign-case-summary">
      <header><span className={`campaign-badge state-${campaignCase.lifecycle.toLowerCase()}`}>{lifecycleLabel(campaignCase.lifecycle)}</span><small>{campaignCase.drone_count} drone{campaignCase.drone_count > 1 ? "s" : ""} · Difficulty {campaignCase.difficulty}/10</small></header>
      <small className="campaign-case-cluster">{cluster?.label} · {campaignCase.environment} · {campaignCase.authorization}</small>
      <p>{campaignCase.purpose}</p>
      <div><span>What it does</span><p>{campaignCase.behavior_under_test}</p></div>
      <div><span>Expected outcome</span><p>{campaignCase.expected_outcome}</p></div>
      <div><span>Planner may use</span><p>{campaignCase.allowed_strategies.map((item) => item.replaceAll("_", " ").toLowerCase()).join(" · ")}</p></div>
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
      <header><span>PRE-PLAY PLAN</span><strong>{String(selected?.strategy ?? plan.status ?? "BLOCKED")}</strong></header>
      <p>{String(plan.optimality_claim ?? plan.blocking_reason ?? "Bounded plan ready")}</p>
      <small>{candidates.length} retained candidates · {candidates.filter((item) => (item as Record<string, unknown>).status === "REJECTED").length} rejected · source step {String(plan.prediction_step_s ?? "—")} s</small>
    </article>
  );
}
