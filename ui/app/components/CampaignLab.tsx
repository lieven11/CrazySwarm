"use client";

import { Beaker, Check, ChevronDown, CircleAlert, Clock3, Copy, Download, FastForward, ImageIcon, ImageOff, LoaderCircle, Maximize2, Minimize2, Trash2, X } from "lucide-react";
import { Fragment, useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import Image from "next/image";
import type { ControlApi } from "../lib/api";
import type {
  CampaignAxis,
  CampaignMotorId,
  CampaignTelemetryChartSample,
  CampaignTelemetryChartView,
} from "../lib/campaign-telemetry";
import type {
  CampaignCaseView,
  CampaignCatalogView,
  CampaignLifecycle,
  CampaignPlanningSubmissionView,
  CampaignRunMode,
  CampaignRunSummary,
  CampaignSnapshotView,
  CampaignSubmissionView,
  CampaignWorkspaceView,
} from "../lib/models";

const FLEET_SIZES = ["1", "2", "3"] as const;
type FleetSizeFilter = typeof FLEET_SIZES[number];
type ClusterFilter = "all" | CampaignCaseView["cluster"];
type EnvironmentFilter = CampaignCaseView["environment"];
type CampaignWorkspaceTab = "catalog" | "run" | "review";
type SnapshotAssessmentDisposition = NonNullable<CampaignSnapshotView["assessment_disposition"]>;
type CampaignTelemetryLoadState =
  | { status: "ready"; value: CampaignTelemetryChartView }
  | { status: "error"; message: string };

type CampaignRunEntry = {
  run: CampaignWorkspaceView["runs"][number];
  review?: CampaignWorkspaceView["reviews"][number];
  number: number;
};

export function campaignRunHistoryRows(entries: CampaignRunEntry[]) {
  return entries.map((entry, index) => ({
    ...entry,
    showOldDivider: Boolean(
      entry.run.superseded_at_utc
      && (index === 0 || !entries[index - 1]?.run.superseded_at_utc)
    ),
  }));
}

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
  disabled?: boolean;
};

export function humanizeCampaignValue(value: string): string {
  const words = value.replaceAll("_", " ").trim().toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : value;
}

function lifecycleLabel(value: string): string {
  const labels: Record<string, string> = {
    ACTIVE_DEVELOPMENT: "In progress",
    BASELINED: "In review",
    BLOCKED: "Blocked",
    DEFINED_NOT_RUN: "Not started",
    PROMOTED: "Completed",
    READY: "Ready",
  };
  return labels[value] ?? humanizeCampaignValue(value);
}

export function campaignWorkspaceHeaderSummary({
  selectedCase,
  runMode,
  reviewStatus,
}: {
  selectedCase?: CampaignCaseView;
  runMode: CampaignRunMode;
  reviewStatus?: string;
}): string {
  const missionName = selectedCase
    ? humanizeCampaignValue(selectedCase.family)
    : "No mission selected";
  const executionMode = runMode === "AUTOMATED_ACCELERATED" ? "Accelerated" : "Realtime";
  const status = reviewStatus ? humanizeCampaignValue(reviewStatus) : "No review";
  return `${missionName} · ${executionMode} · ${status}`;
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
    if (option.disabled) return;
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
    if (event.key === "Enter" && visibleOptions[highlighted] && !visibleOptions[highlighted].disabled) {
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
                aria-disabled={option.disabled}
                disabled={option.disabled}
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

function SubmissionSummary({ submission }: { submission: CampaignSubmissionView }) {
  const target = typeof submission.parameters.target_path_speed_m_s === "number"
    ? `${submission.parameters.target_path_speed_m_s.toFixed(2)} m/s path speed${typeof submission.parameters.lookahead_time_s === "number" ? ` · ${submission.parameters.lookahead_time_s.toFixed(2)} s lookahead` : ""}`
    : typeof submission.parameters.target_vertical_rate_m_s === "number"
      ? `${submission.parameters.target_vertical_rate_m_s.toFixed(2)} m/s vertical rate`
      : typeof submission.parameters.duration_scale === "number"
        ? `${submission.parameters.duration_scale.toFixed(2)}× baseline duration`
      : submission.parameters.segment_target_speeds_m_s.length
        ? `${submission.parameters.segment_target_speeds_m_s.map((value) => value.toFixed(2)).join(" / ")} m/s by segment`
        : "Planner-owned time law";
  return (
    <article className="campaign-submission-summary">
      <header><strong>{target}</strong><span>{humanizeCampaignValue(submission.owner)}</span></header>
      <p>{submission.rationale}</p>
      {submission.missing_prerequisites.length ? (
        <p>Requires successful evidence for: {submission.missing_prerequisites.join(", ")}.</p>
      ) : null}
      <dl>
        {submission.feasibility ? (
          <div><dt>Feasible interval</dt><dd>{submission.feasibility.minimum_path_speed_m_s.toFixed(2)}–{submission.feasibility.maximum_path_speed_m_s.toFixed(2)} m/s before bounded allocation</dd></div>
        ) : null}
        <div><dt>Causal question</dt><dd>{submission.admission.causal_question}</dd></div>
        <div><dt>Evidence gate</dt><dd>{submission.admission.distinguishing_oracle}</dd></div>
        {submission.comparison_case_ids.length > 1 && submission.comparison_case_ids.length <= 5 ? (
          <div><dt>Cross-case comparison</dt><dd>{submission.comparison_case_ids.join(" ↔ ")}</dd></div>
        ) : null}
        <div><dt>Learning value</dt><dd>{submission.admission.learning_value}</dd></div>
      </dl>
    </article>
  );
}

function PlanningSubmissionSummary({ submission }: { submission: CampaignPlanningSubmissionView }) {
  return (
    <article className="campaign-submission-summary">
      <header>
        <strong>{submission.display_name}</strong>
        <span>{humanizeCampaignValue(submission.status)} · {humanizeCampaignValue(submission.path_adherence.mode)}</span>
      </header>
      <p>{submission.rationale}</p>
      <dl>
        <div><dt>Experiment</dt><dd>{humanizeCampaignValue(submission.experiment_axis)} · {humanizeCampaignValue(submission.axis_value)}</dd></div>
        <div><dt>Support</dt><dd>{submission.support_reason}</dd></div>
        <div><dt>Authorized strategies</dt><dd>{submission.strategy_authority.map(humanizeCampaignValue).join(" · ")}</dd></div>
        <div><dt>Maneuver dimensions</dt><dd>{submission.maneuver_dimensions.map(humanizeCampaignValue).join(" · ")}</dd></div>
        <div><dt>Protected separation</dt><dd>{submission.clearance.required_pairwise_center_separation_m.toFixed(2)} m center-to-center</dd></div>
        <div><dt>Coordination</dt><dd>{submission.coordination.synchronized_launch_required ? "Synchronized launch" : "Release timing is flexible"} · maximum release delay {submission.coordination.maximum_release_delay_s.toFixed(1)} s</dd></div>
        <div><dt>Objective</dt><dd>{submission.objective.terms.map((term) => humanizeCampaignValue(term.metric)).join(" → ")}</dd></div>
        <div><dt>Causal question</dt><dd>{submission.admission.causal_question}</dd></div>
        <div><dt>Evidence gate</dt><dd>{submission.admission.distinguishing_oracle}</dd></div>
        <div><dt>Learning value</dt><dd>{submission.admission.learning_value}</dd></div>
      </dl>
    </article>
  );
}

const TELEMETRY_MOTOR_IDS: CampaignMotorId[] = ["m1", "m2", "m3", "m4"];
const TELEMETRY_AXES: CampaignAxis[] = ["x", "y", "z"];

type TelemetryChartLine = {
  id: string;
  label: string;
  className: string;
  value: (sample: CampaignTelemetryChartSample) => number | undefined;
};

function CampaignTelemetryPlots({
  state,
  runNumber,
}: {
  state: CampaignTelemetryLoadState | undefined;
  runNumber: number;
}) {
  const [expandedChart, setExpandedChart] = useState<string>();
  if (!state) {
    return (
      <section className="campaign-telemetry-plots is-loading" aria-label={`Flight graphs for run ${runNumber}`}>
        <LoaderCircle className="spin" size={14} /> Loading flight graphs from the retained CSV
      </section>
    );
  }
  if (state.status === "error") {
    return (
      <section className="campaign-telemetry-plots is-empty" aria-label={`Flight graphs for run ${runNumber}`}>
        <CircleAlert size={14} />
        <span>Graphs unavailable: {state.message}. The raw CSV remains available from Run history.</span>
      </section>
    );
  }
  const { value } = state;
  if (!value.vehicles.length || !value.rowCount) {
    return (
      <section className="campaign-telemetry-plots is-empty" aria-label={`Flight graphs for run ${runNumber}`}>
        <CircleAlert size={14} /> No velocity, altitude, or motor percentage samples were recorded.
      </section>
    );
  }
  const allSamples = value.vehicles.flatMap((vehicle) => vehicle.samples);
  const speedDomain = telemetryDomain(
    allSamples.flatMap((sample) => sample.speedMS === undefined ? [] : [sample.speedMS]),
    true,
  );
  const altitudeDomain = telemetryDomain(
    allSamples.flatMap((sample) => sample.altitudeM === undefined ? [] : [sample.altitudeM]),
  );
  const attitudeDomain = telemetrySymmetricDomain(allSamples.flatMap(
    (sample) => TELEMETRY_AXES.flatMap(
      (axis) => sample.attitudeDeg[axis] === undefined ? [] : [sample.attitudeDeg[axis]],
    ),
  ));
  const accelerationDomain = telemetrySymmetricDomain(allSamples.flatMap(
    (sample) => TELEMETRY_AXES.flatMap(
      (axis) => sample.accelerationMS2[axis] === undefined ? [] : [sample.accelerationMS2[axis]],
    ),
  ));
  const angularVelocityDomain = telemetrySymmetricDomain(allSamples.flatMap(
    (sample) => TELEMETRY_AXES.flatMap(
      (axis) => sample.angularVelocityRadS[axis] === undefined
        ? []
        : [sample.angularVelocityRadS[axis]],
    ),
  ));
  return (
    <section className="campaign-telemetry-plots" aria-label={`Flight graphs for run ${runNumber}`}>
      <header>
        <div><span>Flight graphs</span><small>CSV-derived compact view</small></div>
        <strong>{value.vehicles.length} {value.vehicles.length === 1 ? "drone" : "drones"} · {value.durationS.toFixed(1)} s</strong>
      </header>
      <div className="campaign-telemetry-vehicles">
        {value.vehicles.map((vehicle) => (
          <article key={vehicle.vehicleId}>
            <header>
              <strong>{humanizeCampaignValue(vehicle.vehicleId)}</strong>
              <span>{vehicle.sampleCount.toLocaleString()} rows</span>
            </header>
            <CampaignTelemetryMetricChart
              chartId={`${vehicle.vehicleId}-speed`}
              expanded={expandedChart === `${vehicle.vehicleId}-speed`}
              onToggle={() => setExpandedChart((current) => current === `${vehicle.vehicleId}-speed` ? undefined : `${vehicle.vehicleId}-speed`)}
              title="Speed"
              source="Velocity magnitude"
              unit="m/s"
              durationS={value.durationS}
              domain={speedDomain}
              samples={vehicle.samples}
              lines={[{
                id: "speed",
                label: "Speed",
                className: "series-speed",
                value: (sample) => sample.speedMS,
              }]}
            />
            <CampaignTelemetryMetricChart
              chartId={`${vehicle.vehicleId}-altitude`}
              expanded={expandedChart === `${vehicle.vehicleId}-altitude`}
              onToggle={() => setExpandedChart((current) => current === `${vehicle.vehicleId}-altitude` ? undefined : `${vehicle.vehicleId}-altitude`)}
              title="World Z"
              source={vehicle.altitudeSource}
              unit="m"
              durationS={value.durationS}
              domain={altitudeDomain}
              samples={vehicle.samples}
              lines={[{
                id: "altitude",
                label: "World Z",
                className: "series-altitude",
                value: (sample) => sample.altitudeM,
              }]}
            />
            <CampaignTelemetryMetricChart
              chartId={`${vehicle.vehicleId}-motors`}
              expanded={expandedChart === `${vehicle.vehicleId}-motors`}
              onToggle={() => setExpandedChart((current) => current === `${vehicle.vehicleId}-motors` ? undefined : `${vehicle.vehicleId}-motors`)}
              title="Motor output"
              source={vehicle.motorSource}
              unit="%"
              durationS={value.durationS}
              domain={[0, 100]}
              samples={vehicle.samples}
              lines={TELEMETRY_MOTOR_IDS.map((motorId) => ({
                id: motorId,
                label: motorId.toUpperCase(),
                className: `series-${motorId}`,
                value: (sample) => sample.motorPercent[motorId],
              }))}
            />
            <CampaignTelemetryMetricChart
              chartId={`${vehicle.vehicleId}-attitude`}
              expanded={expandedChart === `${vehicle.vehicleId}-attitude`}
              onToggle={() => setExpandedChart((current) => current === `${vehicle.vehicleId}-attitude` ? undefined : `${vehicle.vehicleId}-attitude`)}
              title="Attitude"
              source="Roll / pitch / yaw"
              unit="°"
              durationS={value.durationS}
              domain={attitudeDomain}
              samples={vehicle.samples}
              lines={TELEMETRY_AXES.map((axis) => ({
                id: `attitude-${axis}`,
                label: axis === "x" ? "Roll" : axis === "y" ? "Pitch" : "Yaw",
                className: `series-axis-${axis}`,
                value: (sample) => sample.attitudeDeg[axis],
              }))}
            />
            <CampaignTelemetryMetricChart
              chartId={`${vehicle.vehicleId}-acceleration`}
              expanded={expandedChart === `${vehicle.vehicleId}-acceleration`}
              onToggle={() => setExpandedChart((current) => current === `${vehicle.vehicleId}-acceleration` ? undefined : `${vehicle.vehicleId}-acceleration`)}
              title="Acceleration"
              source="IMU body frame"
              unit="m/s²"
              durationS={value.durationS}
              domain={accelerationDomain}
              samples={vehicle.samples}
              lines={TELEMETRY_AXES.map((axis) => ({
                id: `acceleration-${axis}`,
                label: axis.toUpperCase(),
                className: `series-axis-${axis}`,
                value: (sample) => sample.accelerationMS2[axis],
              }))}
            />
            <CampaignTelemetryMetricChart
              chartId={`${vehicle.vehicleId}-angular-velocity`}
              expanded={expandedChart === `${vehicle.vehicleId}-angular-velocity`}
              onToggle={() => setExpandedChart((current) => current === `${vehicle.vehicleId}-angular-velocity` ? undefined : `${vehicle.vehicleId}-angular-velocity`)}
              title="Angular velocity"
              source="IMU body frame"
              unit="rad/s"
              durationS={value.durationS}
              domain={angularVelocityDomain}
              samples={vehicle.samples}
              lines={TELEMETRY_AXES.map((axis) => ({
                id: `angular-velocity-${axis}`,
                label: axis.toUpperCase(),
                className: `series-axis-${axis}`,
                value: (sample) => sample.angularVelocityRadS[axis],
              }))}
            />
          </article>
        ))}
      </div>
    </section>
  );
}

function CampaignTelemetryMetricChart({
  chartId,
  expanded,
  onToggle,
  title,
  source,
  unit,
  durationS,
  domain,
  samples,
  lines,
}: {
  chartId: string;
  expanded: boolean;
  onToggle: () => void;
  title: string;
  source: string;
  unit: string;
  durationS: number;
  domain: [number, number];
  samples: CampaignTelemetryChartSample[];
  lines: TelemetryChartLine[];
}) {
  const values = lines.flatMap((line) => samples.flatMap((sample) => {
    const value = line.value(sample);
    return value === undefined ? [] : [value];
  }));
  const observedMinimum = values.length ? Math.min(...values) : undefined;
  const observedMaximum = values.length ? Math.max(...values) : undefined;
  const range = observedMinimum === undefined || observedMaximum === undefined
    ? "No data"
    : `${observedMinimum.toFixed(2)}–${observedMaximum.toFixed(2)} ${unit}`;
  return (
    <figure className={`campaign-telemetry-chart${expanded ? " is-expanded" : ""}`}>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={`campaign-chart-${chartId}`}
        aria-label={`${expanded ? "Collapse" : "Expand"} ${title} graph`}
        onClick={onToggle}
      >
        <div className="campaign-chart-caption">
          <span><strong>{title}</strong><small>{source}</small></span>
          <span className="campaign-chart-range"><em>{range}</em>{expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</span>
        </div>
        <div id={`campaign-chart-${chartId}`}>
          {values.length ? (
            <>
          <svg viewBox="0 0 240 62" preserveAspectRatio="none" role="img" aria-label={`${title} over ${durationS.toFixed(1)} seconds; ${range}`}>
            <line className="grid-line" x1="0" x2="240" y1="8" y2="8" />
            <line className="grid-line" x1="0" x2="240" y1="30" y2="30" />
            <line className="grid-line" x1="0" x2="240" y1="52" y2="52" />
            {lines.flatMap((line) => telemetryPathSegments(
              samples,
              line.value,
              domain,
              durationS,
            ).map((path, index) => (
              <path
                key={`${line.id}-${index}`}
                className={line.className}
                d={path}
                fill="none"
                vectorEffect="non-scaling-stroke"
              />
            )))}
          </svg>
          <div className="campaign-telemetry-time"><span>0 s</span><span>{durationS.toFixed(1)} s</span></div>
          {lines.length > 1 ? (
            <div className="campaign-telemetry-legend">
              {lines.map((line) => <span key={line.id} className={line.className}>{line.label}</span>)}
            </div>
          ) : null}
            </>
          ) : <p>No recorded {title.toLowerCase()} values</p>}
        </div>
      </button>
    </figure>
  );
}

function telemetryDomain(values: number[], includeZero = false): [number, number] {
  if (!values.length) return [0, 1];
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (includeZero) minimum = Math.min(0, minimum);
  if (Math.abs(maximum - minimum) < 1e-9) {
    const padding = Math.max(Math.abs(maximum) * 0.05, 0.05);
    minimum -= includeZero ? 0 : padding;
    maximum += padding;
  } else {
    const padding = (maximum - minimum) * 0.06;
    minimum -= includeZero ? 0 : padding;
    maximum += padding;
  }
  return [minimum, maximum];
}

function telemetrySymmetricDomain(values: number[]): [number, number] {
  if (!values.length) return [-1, 1];
  const bound = Math.max(...values.map((value) => Math.abs(value)), 1e-6);
  const paddedBound = Math.max(bound * 1.08, 0.01);
  return [-paddedBound, paddedBound];
}

function telemetryPathSegments(
  samples: CampaignTelemetryChartSample[],
  valueForSample: (sample: CampaignTelemetryChartSample) => number | undefined,
  domain: [number, number],
  durationS: number,
): string[] {
  const paths: string[] = [];
  let points: string[] = [];
  const flush = () => {
    if (points.length === 1) points.push(points[0]);
    if (points.length) paths.push(`M ${points.join(" L ")}`);
    points = [];
  };
  const span = Math.max(1e-9, domain[1] - domain[0]);
  const plottedDurationS = Math.max(1e-9, durationS);
  for (const sample of samples) {
    const value = valueForSample(sample);
    if (value === undefined) {
      flush();
      continue;
    }
    const x = Math.max(0, Math.min(240, sample.timeS / plottedDurationS * 240));
    const y = 52 - Math.max(0, Math.min(1, (value - domain[0]) / span)) * 44;
    points.push(`${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  flush();
  return paths;
}

export function CampaignLab({
  api,
  onNotice,
  onActiveCaseChange,
  onCampaignRunChange,
  onExecutionModeChange,
  onSubmissionChange,
  onPlanningSubmissionChange,
}: {
  api: ControlApi;
  onNotice: (message: string) => void;
  onActiveCaseChange?: (campaignCase: CampaignCaseView | undefined) => void;
  onCampaignRunChange?: (run: CampaignRunSummary | undefined) => void;
  onExecutionModeChange?: (mode: CampaignRunMode) => void;
  onSubmissionChange?: (submissionId: string | undefined) => void;
  onPlanningSubmissionChange?: (planningSubmissionId: string | undefined) => void;
}) {
  const [open, setOpen] = useState(false);
  const [workspaceTab, setWorkspaceTab] = useState<CampaignWorkspaceTab>("catalog");
  const [preferencesReady, setPreferencesReady] = useState(false);
  const [catalog, setCatalog] = useState<CampaignCatalogView>();
  const [workspace, setWorkspace] = useState<CampaignWorkspaceView>();
  const [loadError, setLoadError] = useState<string>();
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [submissionByCase, setSubmissionByCase] = useState<Record<string, string>>({});
  const [planningSubmissionByCase, setPlanningSubmissionByCase] = useState<Record<string, string>>({});
  const [environment, setEnvironment] = useState<EnvironmentFilter>("SIMULATION");
  const [fleetSize, setFleetSize] = useState<FleetSizeFilter>("1");
  const [cluster, setCluster] = useState<ClusterFilter>("all");
  const [runMode, setRunMode] = useState<CampaignRunMode>("OPERATOR_OBSERVED_REALTIME");
  const [busy, setBusy] = useState<string>();
  const [preview, setPreview] = useState<Record<string, unknown>>();
  const [advanced, setAdvanced] = useState(false);
  const [seed, setSeed] = useState("42");
  const [repetitions, setRepetitions] = useState("1");
  const [selectedReviewRunId, setSelectedReviewRunId] = useState("");
  const [observationDrafts, setObservationDrafts] = useState<Record<string, string>>({});
  const [snapshotCommentDrafts, setSnapshotCommentDrafts] = useState<Record<string, string>>({});
  const [snapshotAssessmentDrafts, setSnapshotAssessmentDrafts] = useState<Record<string, string>>({});
  const [snapshotAssessmentDispositions, setSnapshotAssessmentDispositions] = useState<Record<string, SnapshotAssessmentDisposition>>({});
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [copiedCaseId, setCopiedCaseId] = useState<string>();
  const [telemetryChartsByExecution, setTelemetryChartsByExecution] = useState<Record<string, CampaignTelemetryLoadState>>({});
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
        if (workspaceRef.current?.querySelector(".campaign-snapshot-viewer")) {
          setSelectedSnapshotId("");
          return;
        }
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
          const message = error instanceof Error ? error.message : "Campaign catalog unavailable";
          setLoadError(message);
          onNotice(message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, catalog, loadAttempt, onNotice, preferencesReady]);

  const cases = useMemo(
    () => filterCampaignCases(catalog?.cases ?? [], environment, cluster, fleetSize),
    [catalog, environment, cluster, fleetSize],
  );
  const selected = catalog?.cases.find((item) => item.case_id === selectedId);
  const active = catalog?.cases.find((item) => item.case_id === workspace?.active_case_id);
  const selectedSubmission = (selected?.submissions ?? []).find(
    (item) => item.submission_id === submissionByCase[selected?.case_id ?? ""],
  ) ?? (selected?.submissions ?? []).find((item) => item.status === "EXECUTABLE");
  const activeSubmission = (active?.submissions ?? []).find(
    (item) => item.submission_id === submissionByCase[active?.case_id ?? ""],
  ) ?? (active?.submissions ?? []).find((item) => item.status === "EXECUTABLE");
  const selectedPlanningSubmission = (selected?.planning_submissions ?? []).find(
    (item) => item.planning_submission_id === planningSubmissionByCase[selected?.case_id ?? ""],
  ) ?? (selected?.planning_submissions ?? []).find((item) => item.status === "EXECUTABLE");
  const activePlanningSubmission = (active?.planning_submissions ?? []).find(
    (item) => item.planning_submission_id === planningSubmissionByCase[active?.case_id ?? ""],
  ) ?? (active?.planning_submissions ?? []).find((item) => item.status === "EXECUTABLE");
  const latestActiveCampaignRun = workspace?.runs.toReversed().find((run) => (
    run.locked_inputs.case_id === workspace.active_case_id
    && run.locked_inputs.case_sha256 === active?.case_sha256
  ));
  const activeCampaignRun = workspace?.runs.toReversed().find((run) => (
    run.locked_inputs.case_id === workspace.active_case_id
    && run.locked_inputs.case_sha256 === active?.case_sha256
    && (run.status === "QUEUED" || run.status === "RUNNING")
  ));
  const reviewCaseId = selected?.case_id ?? active?.case_id;
  const reviewCase = catalog?.cases.find((item) => item.case_id === reviewCaseId);
  const reviewByRunId = new Map(
    (workspace?.reviews ?? [])
      .filter((review) => review.case_id === reviewCaseId)
      .map((review) => [review.run_id, review] as const),
  );
  const campaignRunEntries = (workspace?.runs ?? [])
    .filter((run) => (
      run.locked_inputs.case_id === reviewCaseId
      && run.locked_inputs.case_sha256 === reviewCase?.case_sha256
    ))
    .map((run, index) => ({ run, review: reviewByRunId.get(run.run_id), number: index + 1 }))
    .toReversed();
  const campaignRunRows = campaignRunHistoryRows(campaignRunEntries);
  const selectedRunEntry = campaignRunEntries.find(
    ({ run }) => run.run_id === selectedReviewRunId,
  ) ?? campaignRunEntries[0];
  const selectedMissionExecutionId = selectedRunEntry?.run.mission_execution_id;
  const selectedTelemetryCharts = selectedMissionExecutionId
    ? telemetryChartsByExecution[selectedMissionExecutionId]
    : undefined;
  const selectedRunSnapshots = (workspace?.snapshots ?? []).filter(
    (snapshot) => snapshot.run_id === selectedRunEntry?.run.run_id,
  );
  const selectedCaseRunIds = new Set((workspace?.runs ?? [])
    .filter((run) => (
      !run.superseded_at_utc
      && run.locked_inputs.case_id === selected?.case_id
    ))
    .map((run) => run.run_id));
  const unassessedSnapshotCount = (workspace?.snapshots ?? []).filter((snapshot) => (
    selectedCaseRunIds.has(snapshot.run_id)
    && snapshot.image_available
    && (!snapshot.neutral_assessment || !snapshot.assessment_disposition || !snapshot.assessed_at_utc)
  )).length;
  const selectedSnapshot = selectedRunSnapshots.find(
    (snapshot) => snapshot.snapshot_id === selectedSnapshotId,
  );
  const headerSummary = campaignWorkspaceHeaderSummary({
    selectedCase: selected,
    runMode,
    reviewStatus: selectedRunEntry?.review?.status ?? selectedRunEntry?.run.status,
  });

  useEffect(() => {
    if (!catalog || !workspace) return;
    onActiveCaseChange?.(active);
    onCampaignRunChange?.(latestActiveCampaignRun);
  }, [active, catalog, latestActiveCampaignRun, onActiveCaseChange, onCampaignRunChange, workspace]);

  useEffect(() => {
    onSubmissionChange?.(activeSubmission?.submission_id);
  }, [activeSubmission?.submission_id, onSubmissionChange]);

  useEffect(() => {
    onPlanningSubmissionChange?.(activePlanningSubmission?.planning_submission_id);
  }, [activePlanningSubmission?.planning_submission_id, onPlanningSubmissionChange]);

  useEffect(() => {
    if (!selectedMissionExecutionId || telemetryChartsByExecution[selectedMissionExecutionId]) return;
    let cancelled = false;
    void api.campaignTelemetryCharts(selectedMissionExecutionId)
      .then((value) => {
        if (!cancelled) {
          setTelemetryChartsByExecution((current) => ({
            ...current,
            [selectedMissionExecutionId]: { status: "ready", value },
          }));
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setTelemetryChartsByExecution((current) => ({
            ...current,
            [selectedMissionExecutionId]: {
              status: "error",
              message: error instanceof Error ? error.message : "telemetry could not be loaded",
            },
          }));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, selectedMissionExecutionId, telemetryChartsByExecution]);

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
        } else {
          const nextCatalog = await api.campaignCatalog();
          if (!cancelled) setCatalog(nextCatalog);
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
  const submissionOptions = (campaignCase: CampaignCaseView | undefined) => (
    campaignCase?.submissions?.map((item) => ({
      value: item.submission_id,
      label: item.display_name,
      meta: humanizeCampaignValue(item.kind),
      badge: item.run_eligible ? "Eligible" : item.status === "EXECUTABLE" ? "Prerequisite" : "Future",
      badgeClassName: item.run_eligible ? "state-ready" : "state-blocked",
      disabled: !item.run_eligible,
    })) ?? []
  );
  const planningSubmissionOptions = (campaignCase: CampaignCaseView | undefined) => (
    campaignCase?.planning_submissions?.map((item) => ({
      value: item.planning_submission_id,
      label: item.display_name,
      meta: item.maneuver_dimensions.map(humanizeCampaignValue).join(" · "),
      badge: item.status === "EXECUTABLE" ? "Eligible" : "Future",
      badgeClassName: item.status === "EXECUTABLE" ? "state-ready" : "state-blocked",
      disabled: item.status !== "EXECUTABLE",
    })) ?? []
  );
  const selectSubmission = (caseId: string, submissionId: string) => {
    setSubmissionByCase((current) => ({ ...current, [caseId]: submissionId }));
    setPreview(undefined);
  };
  const selectPlanningSubmission = (caseId: string, planningSubmissionId: string) => {
    setPlanningSubmissionByCase((current) => ({
      ...current,
      [caseId]: planningSubmissionId,
    }));
    setPreview(undefined);
  };
  const reviewCaseOptions = useMemo<CampaignDropdownOption[]>(() => {
    const runCounts = new Map<string, number>();
    for (const run of workspace?.runs ?? []) {
      runCounts.set(run.locked_inputs.case_id, (runCounts.get(run.locked_inputs.case_id) ?? 0) + 1);
    }
    return (catalog?.cases ?? [])
      .filter((item) => item.environment === environment)
      .filter((item) => runCounts.has(item.case_id))
      .toSorted((left, right) => (
        (runCounts.get(right.case_id) ?? 0) - (runCounts.get(left.case_id) ?? 0)
        || left.family.localeCompare(right.family)
        || left.variation_name.localeCompare(right.variation_name)
      ))
      .map((item) => {
        const runCount = runCounts.get(item.case_id) ?? 0;
        return {
          value: item.case_id,
          label: humanizeCampaignValue(item.family),
          meta: `${humanizeCampaignValue(item.variation_name)} · ${runCount} ${runCount === 1 ? "run" : "runs"}`,
          badge: lifecycleLabel(item.lifecycle),
          badgeClassName: `state-${item.lifecycle.toLowerCase()}`,
        };
      });
  }, [catalog?.cases, environment, workspace?.runs]);

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

  const act = async (
    label: string,
    action: () => Promise<unknown>,
    reconcileConfirmedResult?: () => void,
  ) => {
    setBusy(label);
    try {
      await action();
      reconcileConfirmedResult?.();
      try {
        await refresh();
      } finally {
        reconcileConfirmedResult?.();
      }
      onNotice(label);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : `${label} failed`);
    } finally {
      setBusy(undefined);
    }
  };

  const reconcileLifecycle = (caseId: string, lifecycle: CampaignLifecycle) => {
    setCatalog((current) => current ? {
      ...current,
      cases: current.cases.map((item) => (
        item.case_id === caseId ? { ...item, lifecycle } : item
      )),
    } : current);
  };

  const copyCaseId = async (caseId: string) => {
    try {
      await navigator.clipboard.writeText(caseId);
      setCopiedCaseId(caseId);
      onNotice("Mission case ID copied");
    } catch {
      onNotice("Mission case ID could not be copied");
    }
  };

  const footerActions = (
    <div className="campaign-actions">
      <button
        className="campaign-action-inactive"
        type="button"
        aria-pressed={selected?.lifecycle === "DEFINED_NOT_RUN"}
        disabled={!selected || selected.lifecycle === "DEFINED_NOT_RUN" || Boolean(busy)}
        onClick={() => selected && void act(
          "Mission set to inactive",
          () => api.setCampaignCaseLifecycle(selected.case_id, "DEFINED_NOT_RUN", "operator set mission to inactive"),
          () => reconcileLifecycle(selected.case_id, "DEFINED_NOT_RUN"),
        )}
      >Inactive</button>
      <button
        className="campaign-action-active"
        type="button"
        disabled={!selected || selected.case_id === active?.case_id || selected.environment === "REAL" || selected.implementation_status !== "EXECUTABLE" || Boolean(activeCampaignRun) || Boolean(busy)}
        title={activeCampaignRun
          ? "Stop the active campaign run before selecting another mission"
          : "Checks the mission and selects it in one step"}
        onClick={() => selected && void act("Mission selected and checks passed", () => api.setActiveCampaignCase(selected.case_id, "operator selected mission for development"))}
      >Use mission</button>
      <button
        className="campaign-action-review"
        type="button"
        disabled={!selected || selected.lifecycle === "BASELINED" || !workspace?.reviews.some((review) => review.case_id === selected.case_id) || unassessedSnapshotCount > 0 || Boolean(busy)}
        title={unassessedSnapshotCount ? `${unassessedSnapshotCount} retained snapshot${unassessedSnapshotCount === 1 ? " requires" : "s require"} a neutral assessment` : undefined}
        onClick={() => selected && void act("Mission case moved to review", () => api.moveCampaignCaseToReview(selected.case_id, "operator moved case to review"))}
      >Review</button>
      <button
        className="campaign-action-complete"
        type="button"
        aria-pressed={selected?.lifecycle === "PROMOTED"}
        disabled={!selected || selected.lifecycle === "PROMOTED" || Boolean(busy)}
        onClick={() => selected && void act(
          "Mission case completed",
          () => api.setCampaignCaseLifecycle(
            selected.case_id,
            "PROMOTED",
            "operator marked mission as completed",
          ),
          () => reconcileLifecycle(selected.case_id, "PROMOTED"),
        )}
      >Completed</button>
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
              <small>{headerSummary}</small>
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
          {!catalog && !loadError ? <div className="campaign-loading"><LoaderCircle className="spin" size={16} />Loading campaign workspace</div> : null}
          {loadError ? (
            <div className="campaign-loading" role="alert">
              <CircleAlert size={16} />
              <span>Campaign workspace unavailable: {loadError}</span>
              <button type="button" onClick={() => {
                setLoadError(undefined);
                setLoadAttempt((value) => value + 1);
              }}>Retry</button>
            </div>
          ) : null}

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
                {selected && (selected.submissions?.length ?? 0) > 1 ? (
                  <div className="campaign-submission-picker">
                    <CampaignDropdown
                      label="Execution submission"
                      value={selectedSubmission?.submission_id ?? ""}
                      options={submissionOptions(selected)}
                      onChange={(submissionId) => selectSubmission(selected.case_id, submissionId)}
                    />
                  </div>
                ) : null}
                {selected && (selected.planning_submissions?.length ?? 0) > 1 ? (
                  <div className="campaign-submission-picker">
                    <CampaignDropdown
                      label="Planning contract"
                      value={selectedPlanningSubmission?.planning_submission_id ?? ""}
                      options={planningSubmissionOptions(selected)}
                      onChange={(planningSubmissionId) => selectPlanningSubmission(selected.case_id, planningSubmissionId)}
                    />
                  </div>
                ) : null}
              </div>
              <div className="campaign-case-detail">
                {selected ? (
                  <>
                    <header className="campaign-case-detail-header">
                      <div>
                        <h3>{humanizeCampaignValue(selected.family)}</h3>
                      </div>
                      <span className={`campaign-status state-${selected.lifecycle.toLowerCase()}`}>{lifecycleLabel(selected.lifecycle)}</span>
                    </header>
                    <button
                      className={copiedCaseId === selected.case_id ? "campaign-case-id is-copied" : "campaign-case-id"}
                      type="button"
                      aria-label={`Copy mission case ID ${selected.case_id}`}
                      title={`Copy mission case ID: ${selected.case_id}`}
                      onClick={() => void copyCaseId(selected.case_id)}
                    >
                      <code>{selected.case_id}</code>
                      <span>{copiedCaseId === selected.case_id ? <Check size={12} /> : <Copy size={12} />}{copiedCaseId === selected.case_id ? "Copied" : "Copy"}</span>
                    </button>
                    <CaseSummary campaignCase={selected} />
                    {selected.submission_registry?.baseline_only ? (
                      <p className="campaign-inline-note">
                        Baseline only: {selected.submission_registry.baseline_only_rationale}
                      </p>
                    ) : null}
                    {(selected.submissions?.length ?? 0) > 1 && selectedSubmission ? (
                      <section
                        className="campaign-submission-detail"
                        aria-label={`Selected execution submission: ${selectedSubmission.display_name}`}
                      >
                        <div className="campaign-submission-detail-title">
                          <span>Selected submission</span>
                          <strong>{selectedSubmission.display_name}</strong>
                        </div>
                        <SubmissionSummary submission={selectedSubmission} />
                      </section>
                    ) : null}
                    {(selected.planning_submissions?.length ?? 0) > 1 && selectedPlanningSubmission ? (
                      <section
                        className="campaign-submission-detail"
                        aria-label={`Selected planning contract: ${selectedPlanningSubmission.display_name}`}
                      >
                        <div className="campaign-submission-detail-title">
                          <span>Selected planning contract</span>
                          <strong>{selectedPlanningSubmission.planning_submission_id}</strong>
                        </div>
                        <PlanningSubmissionSummary submission={selectedPlanningSubmission} />
                      </section>
                    ) : null}
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
              {active && (active.submissions?.length ?? 0) > 1 ? (
                <div className="campaign-submission-panel">
                  <CampaignDropdown
                    label="Execution submission"
                    value={activeSubmission?.submission_id ?? ""}
                    options={submissionOptions(active)}
                    onChange={(submissionId) => selectSubmission(active.case_id, submissionId)}
                  />
                  {activeSubmission ? <SubmissionSummary submission={activeSubmission} /> : null}
                </div>
              ) : null}
              {active && (active.planning_submissions?.length ?? 0) > 1 ? (
                <div className="campaign-submission-panel">
                  <CampaignDropdown
                    label="Planning contract"
                    value={activePlanningSubmission?.planning_submission_id ?? ""}
                    options={planningSubmissionOptions(active)}
                    onChange={(planningSubmissionId) => selectPlanningSubmission(active.case_id, planningSubmissionId)}
                  />
                  {activePlanningSubmission ? <PlanningSubmissionSummary submission={activePlanningSubmission} /> : null}
                </div>
              ) : null}
              {active && typeof api.campaignResolvedPackageUrl === "function" ? (
                <a
                  className="campaign-qualification-download"
                  href={api.campaignResolvedPackageUrl(
                    activeSubmission?.submission_id,
                    activePlanningSubmission?.planning_submission_id,
                  )}
                  download
                >
                  <Download size={14} /> Download resolved package
                </a>
              ) : null}
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
              {preview ? <PlanPreview value={preview} campaignCase={active} /> : null}
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
              {selectedRunEntry ? (
                <div className="campaign-review-journal">
                  <section className="campaign-run-history" aria-label={`Runs for ${reviewCase ? humanizeCampaignValue(reviewCase.family) : "campaign"}`}>
                    <div className="campaign-review-case-picker">
                      <CampaignDropdown
                        label="Review mission case"
                        value={reviewCaseId ?? ""}
                        options={reviewCaseOptions}
                        searchable
                        onChange={(nextCaseId) => {
                          const nextCase = catalog.cases.find((item) => item.case_id === nextCaseId);
                          setSelectedId(nextCaseId);
                          setSelectedReviewRunId("");
                          setSelectedSnapshotId("");
                          if (nextCase) {
                            setEnvironment(nextCase.environment);
                            setFleetSize(String(nextCase.drone_count) as FleetSizeFilter);
                          }
                        }}
                      />
                    </div>
                    <header>
                      <span>Run history</span>
                      <strong>{campaignRunEntries.length}</strong>
                    </header>
                    <div className="campaign-run-history-list">
                      {campaignRunRows.map(({ run, number, showOldDivider }) => (
                        <Fragment key={run.run_id}>
                          {showOldDivider ? (
                            <div
                              className="campaign-run-history-divider"
                              role="separator"
                              aria-label="Old runs"
                            ><span>Old runs</span></div>
                          ) : null}
                          <article className={run.run_id === selectedRunEntry.run.run_id ? "is-selected" : ""}>
                          <button type="button" aria-pressed={run.run_id === selectedRunEntry.run.run_id} onClick={() => setSelectedReviewRunId(run.run_id)}>
                            <span><strong>Run {number}</strong><small>{run.locked_inputs.submission_id ? `${humanizeCampaignValue(run.locked_inputs.submission_id)} · ` : ""}{formatCampaignRunDate(run.finished_at_utc ?? run.requested_at_utc)}</small></span>
                            <span className="campaign-run-state">
                              {run.superseded_at_utc ? <em className="state-old">Old</em> : null}
                              <em className={`state-${run.status.toLowerCase()}`}>{humanizeCampaignValue(run.status)}</em>
                            </span>
                          </button>
                          {run.mission_execution_id ? (
                            <a href={api.campaignTelemetryCsvUrl(run.mission_execution_id)} download aria-label={`Download telemetry CSV for run ${number}`} title="Download telemetry CSV"><Download size={13} /></a>
                          ) : null}
                          <button
                            className="campaign-delete-run"
                            type="button"
                            aria-label={`Delete run ${number}`}
                            title={run.status === "RUNNING" || run.status === "QUEUED" ? "Active runs cannot be deleted" : "Delete run"}
                            disabled={run.status === "RUNNING" || run.status === "QUEUED" || Boolean(busy)}
                            onClick={() => {
                              const runId = run.run_id;
                              void act("Campaign run deleted", async () => {
                                await api.deleteCampaignRun(runId);
                                setSelectedReviewRunId("");
                              });
                            }}
                          ><Trash2 size={13} /></button>
                          </article>
                        </Fragment>
                      ))}
                    </div>
                  </section>

                  <section className="campaign-review-detail">
                    <header>
                      <span>Run {selectedRunEntry.number}</span>
                      <strong>{humanizeCampaignValue(selectedRunEntry.run.status)}</strong>
                    </header>
                    <p>{selectedRunEntry.review?.analysis.primary_cause.reason
                      ?? selectedRunEntry.run.failure_reason
                      ?? (selectedRunEntry.run.status === "RUNNING" || selectedRunEntry.run.status === "QUEUED"
                        ? "This run is still in progress."
                        : "Evidence for this run is not available.")}</p>
                    <p className="campaign-run-facts">
                      {selectedRunEntry.run.mode === "AUTOMATED_ACCELERATED" ? "Accelerated" : "Realtime"}
                      {` · ${selectedRunEntry.review?.analysis.telemetry_row_count?.toLocaleString() ?? "—"} rows`}
                      {` · ${formatCampaignRunDate(selectedRunEntry.run.finished_at_utc)}`}
                    </p>
                    {selectedRunEntry.review?.twin_session_ids?.length ? (
                      <details className="campaign-twin-evidence">
                        <summary>
                          Digital twin evidence · {selectedRunEntry.review.twin_session_ids.length} retained {selectedRunEntry.review.twin_session_ids.length === 1 ? "session" : "sessions"}
                        </summary>
                        <p>Source-aligned session links are immutable review evidence. Simulator sources are not physical-flight qualification.</p>
                        <ol>
                          {selectedRunEntry.review.twin_session_ids.map((sessionId) => <li key={sessionId}><code>{sessionId}</code></li>)}
                        </ol>
                      </details>
                    ) : null}
                    <div className="campaign-review-detail-body">
                      {selectedMissionExecutionId ? (
                        <CampaignTelemetryPlots
                          state={selectedTelemetryCharts}
                          runNumber={selectedRunEntry.number}
                        />
                      ) : (
                        <section className="campaign-telemetry-plots is-empty" aria-label={`Flight graphs for run ${selectedRunEntry.number}`}>
                          <CircleAlert size={14} /> Flight graphs become available when the run telemetry CSV is retained.
                        </section>
                      )}
                      {selectedRunEntry.review ? (
                        <MotionQualityEvidence analysis={selectedRunEntry.review.analysis} />
                      ) : null}
                      {selectedRunEntry.review ? (
                        <ReplanTimeline analysis={selectedRunEntry.review.analysis} />
                      ) : null}
                      {selectedRunEntry.review ? (
                        <EvidenceReconciliation analysis={selectedRunEntry.review.analysis} />
                      ) : null}
                      {selectedRunEntry.review ? (
                        <>
                          {selectedRunEntry.review.operator_observations.length ? (
                            <div className="campaign-observation-log">
                              <span>Saved observations</span>
                              <ol>
                                {selectedRunEntry.review.operator_observations.map((note, index) => <li key={`${selectedRunEntry.review?.review_id}-${index}`}>{note}</li>)}
                              </ol>
                            </div>
                          ) : null}
                          <div className="campaign-review-composer">
                            <label className="campaign-observation-field">
                              <span>Operator comment</span>
                              <textarea
                                aria-label={`Operator comment for run ${selectedRunEntry.number}`}
                                placeholder={selectedRunEntry.review.operator_questions[0] ?? "Record what you observed during this run"}
                                value={observationDrafts[selectedRunEntry.review.review_id] ?? ""}
                                onChange={(event) => setObservationDrafts((current) => ({
                                  ...current,
                                  [selectedRunEntry.review!.review_id]: event.target.value,
                                }))}
                              />
                            </label>
                            <button
                              className="campaign-save-observation"
                              type="button"
                              disabled={!observationDrafts[selectedRunEntry.review.review_id]?.trim() || Boolean(busy)}
                              onClick={() => {
                                const reviewId = selectedRunEntry.review!.review_id;
                                const note = observationDrafts[reviewId] ?? "";
                                void act("Operator comment saved", async () => {
                                  await api.addCampaignObservation(reviewId, note);
                                  setObservationDrafts((current) => ({ ...current, [reviewId]: "" }));
                                });
                              }}
                            >Save comment</button>
                          </div>
                        </>
                      ) : null}
                      <section className="campaign-snapshot-strip" aria-label={`Snapshots for run ${selectedRunEntry.number}`}>
                        <header>
                          <span><ImageIcon size={12} />Scene snapshots</span>
                          <strong>{selectedRunSnapshots.length}</strong>
                        </header>
                        {selectedRunSnapshots.length ? (
                          <div>
                            {selectedRunSnapshots.map((snapshot, index) => (
                              <button
                                type="button"
                                key={snapshot.snapshot_id}
                                aria-label={`Review snapshot ${index + 1} from run ${selectedRunEntry.number}`}
                                onClick={() => setSelectedSnapshotId(snapshot.snapshot_id)}
                              >
                                {snapshot.image_available ? (
                                  <Image unoptimized src={api.campaignSnapshotImageUrl(snapshot.snapshot_id)} width={92} height={54} alt="" />
                                ) : <ImageOff size={17} />}
                                <span>{index + 1}</span>
                                {snapshot.operator_comment ? <i aria-label="Comment saved" /> : null}
                              </button>
                            ))}
                          </div>
                        ) : <p>No scene snapshots were captured during this run.</p>}
                      </section>
                    </div>
                  </section>
                </div>
              ) : <div className="campaign-workspace-empty"><CircleAlert size={16} />No runs have been recorded for this campaign yet</div>}
            </section>
          ) : null}
        </div>

        <footer className="campaign-workspace-footer">
          {footerActions}
        </footer>
        {selectedSnapshot && selectedRunEntry ? (
          <div className="campaign-snapshot-viewer-backdrop">
            <section className="campaign-snapshot-viewer" role="dialog" aria-modal="true" aria-labelledby="campaign-snapshot-viewer-title">
              <header>
                <div>
                  <span>Run {selectedRunEntry.number} · Scene snapshot</span>
                  <h3 id="campaign-snapshot-viewer-title">{formatCampaignRunDate(selectedSnapshot.captured_at_utc)}</h3>
                </div>
                <button type="button" aria-label="Close snapshot review" onClick={() => setSelectedSnapshotId("")}><X size={16} /></button>
              </header>
              <div className="campaign-snapshot-image">
                {selectedSnapshot.image_available ? (
                  <Image
                    unoptimized
                    src={api.campaignSnapshotImageUrl(selectedSnapshot.snapshot_id)}
                    width={selectedSnapshot.width_px}
                    height={selectedSnapshot.height_px}
                    alt={`Scene captured during run ${selectedRunEntry.number}`}
                  />
                ) : (
                  <div><ImageOff size={24} /><strong>Image removed</strong><span>The retained comment and capture metadata remain available.</span></div>
                )}
              </div>
              <label className="campaign-snapshot-comment">
                <span>Comment for this snapshot</span>
                <textarea
                  aria-label="Snapshot comment"
                  placeholder="What was visible at this moment?"
                  value={snapshotCommentDrafts[selectedSnapshot.snapshot_id] ?? selectedSnapshot.operator_comment ?? ""}
                  onChange={(event) => setSnapshotCommentDrafts((current) => ({
                    ...current,
                    [selectedSnapshot.snapshot_id]: event.target.value,
                  }))}
                />
              </label>
              {selectedSnapshot.review_frame ? (
                <div className="campaign-run-facts" aria-label="Snapshot source-time identity">
                  <span><small>Source time</small><strong>{selectedSnapshot.review_frame.source_timestamp_s.toFixed(3)} s</strong></span>
                  <span><small>Estimate / truth</small><strong>{selectedSnapshot.review_frame.estimate_source_timestamp_s.toFixed(3)} / {selectedSnapshot.review_frame.truth_source_timestamp_s?.toFixed(3) ?? "—"} s</strong></span>
                  <span><small>Display age</small><strong>{selectedSnapshot.review_frame.playback_buffer_age_s.toFixed(3)} s</strong></span>
                  <span><small>Interpolation</small><strong>{humanizeCampaignValue(selectedSnapshot.review_frame.interpolation_state)}</strong></span>
                </div>
              ) : null}
              <button
                className="campaign-save-snapshot-comment"
                type="button"
                disabled={
                  !(snapshotCommentDrafts[selectedSnapshot.snapshot_id] ?? selectedSnapshot.operator_comment ?? "").trim()
                  || (snapshotCommentDrafts[selectedSnapshot.snapshot_id] ?? selectedSnapshot.operator_comment ?? "").trim() === (selectedSnapshot.operator_comment ?? "")
                  || Boolean(busy)
                }
                onClick={() => {
                  const note = (snapshotCommentDrafts[selectedSnapshot.snapshot_id] ?? selectedSnapshot.operator_comment ?? "").trim();
                  void act("Snapshot comment saved", async () => {
                    await api.updateCampaignSnapshotComment(selectedSnapshot.snapshot_id, note);
                    setSnapshotCommentDrafts((current) => ({ ...current, [selectedSnapshot.snapshot_id]: note }));
                  });
                }}
              >Save snapshot comment</button>
              <label className="campaign-snapshot-comment">
                <span>Neutral evidence assessment</span>
                <textarea
                  aria-label="Neutral snapshot evidence assessment"
                  placeholder="Separate what the evidence supports from the operator observation"
                  value={snapshotAssessmentDrafts[selectedSnapshot.snapshot_id] ?? selectedSnapshot.neutral_assessment ?? ""}
                  onChange={(event) => setSnapshotAssessmentDrafts((current) => ({
                    ...current,
                    [selectedSnapshot.snapshot_id]: event.target.value,
                  }))}
                />
                <select
                  aria-label="Neutral assessment disposition"
                  value={snapshotAssessmentDispositions[selectedSnapshot.snapshot_id] ?? selectedSnapshot.assessment_disposition ?? "NEEDS_MORE_EVIDENCE"}
                  onChange={(event) => setSnapshotAssessmentDispositions((current) => ({
                    ...current,
                    [selectedSnapshot.snapshot_id]: event.target.value as SnapshotAssessmentDisposition,
                  }))}
                >
                  <option value="VALID">Valid</option>
                  <option value="PARTLY_VALID">Partly valid</option>
                  <option value="DISPLAY_EFFECT">Display effect</option>
                  <option value="NOT_SUPPORTED">Not supported</option>
                  <option value="NEEDS_MORE_EVIDENCE">Needs more evidence</option>
                </select>
              </label>
              <button
                className="campaign-save-snapshot-comment"
                type="button"
                disabled={!(snapshotAssessmentDrafts[selectedSnapshot.snapshot_id] ?? selectedSnapshot.neutral_assessment ?? "").trim() || Boolean(busy)}
                onClick={() => {
                  const assessment = (snapshotAssessmentDrafts[selectedSnapshot.snapshot_id] ?? selectedSnapshot.neutral_assessment ?? "").trim();
                  const disposition = snapshotAssessmentDispositions[selectedSnapshot.snapshot_id] ?? selectedSnapshot.assessment_disposition ?? "NEEDS_MORE_EVIDENCE";
                  void act("Neutral snapshot assessment saved", async () => {
                    await api.updateCampaignSnapshotAssessment(
                      selectedSnapshot.snapshot_id,
                      assessment,
                      disposition,
                      selectedSnapshot.assessment_confidence ?? 0.8,
                      selectedSnapshot.assessment_evidence_refs ?? [],
                    );
                    setSnapshotAssessmentDrafts((current) => ({
                      ...current,
                      [selectedSnapshot.snapshot_id]: assessment,
                    }));
                  });
                }}
              >Save neutral assessment</button>
            </section>
          </div>
        ) : null}
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

function formatCampaignRunDate(value?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

type CampaignReviewAnalysis = CampaignWorkspaceView["reviews"][number]["analysis"];
type CampaignEvidencePoint = { x: number; y: number; z: number };

function formatEvidencePoint(point?: CampaignEvidencePoint): string {
  if (!point) return "—";
  return `(${point.x.toFixed(3)}, ${point.y.toFixed(3)}, ${point.z.toFixed(3)}) m`;
}

function evidenceDistance(left?: CampaignEvidencePoint, right?: CampaignEvidencePoint): string {
  if (!left || !right) return "—";
  return Math.hypot(left.x - right.x, left.y - right.y, left.z - right.z).toFixed(3);
}

function EvidenceReconciliation({ analysis }: { analysis: CampaignReviewAnalysis }) {
  const kinematics = (analysis.vehicles ?? []).filter(
    (vehicle) => vehicle.kinematics_gate_reconciliation,
  );
  return (
    <details className="campaign-evidence-details">
      <summary>
        <span>Evidence details</span>
        <strong>{kinematics.length + (analysis.landing?.length ?? 0)} checks</strong>
        <ChevronDown size={14} aria-hidden="true" />
      </summary>
      <div>
        {analysis.planning_submission_id ? (
          <div>
            <span>Planning authority</span>
            <p>{analysis.planning_submission_id} · submission {analysis.planning_submission_sha256?.slice(0, 12) ?? "—"} · package {analysis.resolved_planning_package_sha256?.slice(0, 12) ?? "—"}</p>
          </div>
        ) : null}
      {kinematics.map((vehicle) => {
        const gate = vehicle.kinematics_gate_reconciliation!;
        return (
          <div key={`kinematics-${vehicle.vehicle_id}`}>
            <span>{vehicle.vehicle_id} kinematics {gate.gate_disagreement ? "· GATE DISAGREEMENT" : ""}</span>
            <p>
              Raw H/V {gate.raw_horizontal_speed_peak_m_s?.toFixed(3) ?? "—"}/{gate.raw_vertical_speed_peak_m_s?.toFixed(3) ?? "—"} m/s ({gate.raw_gate_passed === undefined ? "not evaluated" : gate.raw_gate_passed ? "pass" : "fail"}) · Processed H/V {gate.processed_horizontal_speed_peak_m_s?.toFixed(3) ?? "—"}/{gate.processed_vertical_speed_peak_m_s?.toFixed(3) ?? "—"} m/s ({gate.processed_gate_passed === undefined ? "not evaluated" : gate.processed_gate_passed ? "pass" : "fail"}) · Limits {gate.maximum_horizontal_speed_m_s?.toFixed(2) ?? "—"}/{gate.maximum_vertical_speed_m_s?.toFixed(2) ?? "—"} m/s
            </p>
          </div>
        );
      })}
      {(analysis.landing ?? []).map((landing) => (
        <div key={`landing-${landing.vehicle_id}`}>
          <span>{landing.vehicle_id} role-relative landing target {landing.landing_goal_id ? `· ${landing.landing_goal_id}` : ""}</span>
          <p>
            Accepted {formatEvidencePoint(landing.accepted_landing_center_m)} · Planned arrival {formatEvidencePoint(landing.planned_arrival_m)} ({evidenceDistance(landing.planned_arrival_m, landing.accepted_landing_center_m)} m) · Estimate {formatEvidencePoint(landing.estimated_touchdown_m)} ({evidenceDistance(landing.estimated_touchdown_m, landing.accepted_landing_center_m)} m) · Truth {formatEvidencePoint(landing.truth_touchdown_m)} ({evidenceDistance(landing.truth_touchdown_m, landing.accepted_landing_center_m)} m) · Display marker {formatEvidencePoint(landing.displayed_goal_marker_m)} ({evidenceDistance(landing.displayed_goal_marker_m, landing.accepted_landing_center_m)} m)
          </p>
          <p>Coordinate chain: {landing.coordinate_conversion_chain.join(" → ")}{landing.terminal_contact ? ` · ${humanizeCampaignValue(landing.terminal_contact)}` : ""}{landing.motors_cut_after_contact === undefined ? "" : ` · motors ${landing.motors_cut_after_contact ? "cut after contact" : "not confirmed cut after contact"}`}</p>
        </div>
      ))}
      </div>
    </details>
  );
}

export function MotionQualityEvidence({ analysis }: { analysis: CampaignReviewAnalysis }) {
  const motion = analysis.motion_quality ?? [];
  const physical = analysis.physical_truth ?? [];
  if (!motion.length && !physical.length) return null;
  return (
    <section className="campaign-motion-quality" aria-label="Motion quality and motor physical truth">
      <header><span>Motion quality</span><strong>RAW SOURCE CLOCK</strong></header>
      {motion.map((item) => (
        <article key={item.analysis_sha256}>
          <div className="campaign-motion-heading">
            <strong>{item.vehicle_id}</strong>
            <span className={item.failed_guards.length ? "is-fail" : item.missing_guards.length ? "is-missing" : "is-pass"}>
              {item.failed_guards.length ? `${item.failed_guards.length} failed` : item.missing_guards.length ? `${item.missing_guards.length} unavailable` : "All guards passed"}
            </span>
          </div>
          <dl>
            {Object.entries(item.vector).map(([metric, value]) => (
              <div key={metric} className={item.failed_guards.includes(metric) ? "is-fail" : item.missing_guards.includes(metric) ? "is-missing" : ""}>
                <dt>{humanizeCampaignValue(metric)}</dt>
                <dd>{typeof value === "number" ? value.toFixed(4) : value === null ? "Unavailable" : String(value)}</dd>
              </div>
            ))}
          </dl>
          <small>Contract {item.contract_sha256.slice(0, 12)} · CSV {item.csv_sha256.slice(0, 12)} · {item.sample_count.toLocaleString()} samples</small>
        </article>
      ))}
      {physical.map((item) => (
        <article className="campaign-motor-truth" key={item.analysis_sha256}>
          <div className="campaign-motion-heading"><strong>{item.vehicle_id} differential actuation</strong><span className={item.passed ? "is-pass" : "is-fail"}>{item.passed ? "Physical oracle passed" : "Physical oracle failed"}</span></div>
          <p>Torque ↔ IMU sign agreement {item.sign_agreement_fraction?.toFixed(3) ?? "unavailable"} · normalized magnitude error p95 {item.normalized_error_p95?.toFixed(3) ?? "unavailable"} · pairing {item.maximum_source_pairing_error_s?.toFixed(4) ?? "unavailable"} s · {item.maneuver_sample_count} maneuver components</p>
          <p>All-equal moving samples {item.all_equal_moving_sample_count} · saturated maneuvers {item.saturated_maneuver_sample_count}{item.failures.length ? ` · ${item.failures.map(humanizeCampaignValue).join(" · ")}` : ""}</p>
        </article>
      ))}
    </section>
  );
}

export function ReplanTimeline({ analysis }: { analysis: CampaignReviewAnalysis }) {
  const records = analysis.replan_timeline ?? [];
  if (!records.length) return null;
  return (
    <section className="campaign-replan-timeline" aria-label="Sensor-sourced replan timeline">
      <header><span>Changed-world timeline</span><strong>{records.length} retained stages</strong></header>
      <ol>
        {records.map((record, index) => (
          <li key={`${record.observation_sha256 ?? record.decision_sha256 ?? record.event_id ?? "record"}-${index}`}>
            <i aria-hidden="true" />
            <span>
              <strong>{humanizeCampaignValue(record.stage ?? record.execution_disposition ?? record.disposition ?? "event")}</strong>
              <small>{record.observation_id ?? record.event_id ?? "Source event"}{record.change_kind ? ` · ${humanizeCampaignValue(record.change_kind)}` : ""}{record.solid_id ? ` · ${record.solid_id}` : ""}{record.fallback_command ? ` · ${humanizeCampaignValue(record.fallback_command)}` : ""}</small>
              {record.reason ? <em>{record.reason}</em> : null}
            </span>
            <time>{record.received_timestamp_s?.toFixed(3) ?? record.source_timestamp_s?.toFixed(3) ?? "—"} s</time>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function CaseSummary({ campaignCase }: { campaignCase: CampaignCaseView }) {
  const semantics = campaignCase.semantics;
  const routeCount = semantics ? Object.keys(semantics.route_intent_by_role).length : 0;
  const oracleCount = semantics?.behavior_oracles.length ?? 0;
  return (
    <article className="campaign-case-summary">
      {semantics ? (
        <section className="campaign-case-objective">
          <span>Level {semantics.curriculum_level} objective</span>
          <p>{semantics.learning_objective}</p>
        </section>
      ) : null}
      <div className="campaign-case-highlights">
        <div><span>What it does</span><p>{campaignCase.behavior_under_test}</p></div>
        <div><span>Expected outcome</span><p>{campaignCase.expected_outcome}</p></div>
      </div>
      {semantics ? (
        <details className="campaign-case-technical">
          <summary>
            <span>Technical criteria</span>
            <strong>
              {routeCount} {routeCount === 1 ? "route" : "routes"} · {oracleCount} {oracleCount === 1 ? "check" : "checks"}
            </strong>
            <ChevronDown size={14} aria-hidden="true" />
          </summary>
          <div>
            <div><span>Level rationale</span><p>{semantics.difficulty_rationale}</p></div>
            <div>
              <span>Authored route</span>
              <p>{Object.entries(semantics.route_intent_by_role).map(([role, nodes]) => `${role}: ${nodes.map((node) => `${humanizeCampaignValue(node.mode)}${node.mode === "CAPTURE_AND_HOLD" ? ` ${node.dwell_s}s` : ""} · ${node.region_id}`).join(" → ")}`).join(" · ")}</p>
            </div>
            {semantics.scenario_events.length ? (
              <div><span>Injected events</span><p>{semantics.scenario_events.map((event) => `${event.trigger_time_s.toFixed(1)}s · ${humanizeCampaignValue(event.kind)} · ${humanizeCampaignValue(event.expected_disposition)}`).join(" · ")}</p></div>
            ) : null}
            <div>
              <span>Evidence checks</span>
              <p>{semantics.behavior_oracles.map((oracle) => `${humanizeCampaignValue(oracle.kind)}${oracle.threshold === undefined ? "" : `: ${oracle.threshold} ${oracle.unit ?? ""}`}`).join(" · ")}</p>
            </div>
          </div>
        </details>
      ) : null}
    </article>
  );
}

function PlanPreview({ value, campaignCase }: { value: Record<string, unknown>; campaignCase?: CampaignCaseView }) {
  const plan = value.plan && typeof value.plan === "object" ? value.plan as Record<string, unknown> : {};
  const resolvedPackage = value.resolved_package && typeof value.resolved_package === "object"
    ? value.resolved_package as Record<string, unknown>
    : {};
  const planningSubmission = resolvedPackage.planning_submission && typeof resolvedPackage.planning_submission === "object"
    ? resolvedPackage.planning_submission as Record<string, unknown>
    : {};
  const certificate = plan.feasibility_certificate && typeof plan.feasibility_certificate === "object"
    ? plan.feasibility_certificate as Record<string, unknown>
    : undefined;
  const candidates = Array.isArray(plan.retained_candidates) ? plan.retained_candidates : [];
  const selectedIndex = typeof plan.selected_candidate_index === "number" ? plan.selected_candidate_index : -1;
  const selected = selectedIndex >= 0 && typeof candidates[selectedIndex] === "object" ? candidates[selectedIndex] as Record<string, unknown> : undefined;
  const routes = Array.isArray(selected?.routes) ? selected.routes as Array<Record<string, unknown>> : [];
  return (
    <article className="campaign-plan-preview">
      <header><span>PLAN PREVIEW</span><strong>{humanizeCampaignValue(String(selected?.strategy ?? plan.status ?? "BLOCKED"))}</strong></header>
      <p>{String(plan.optimality_claim ?? plan.blocking_reason ?? "Bounded plan ready")}</p>
      <div>
        <span>Resolved authority</span>
        <p>{String(planningSubmission.display_name ?? plan.planning_submission_id ?? "Baseline planning contract")} · package {String(resolvedPackage.resolved_package_sha256 ?? "unavailable").slice(0, 12)} · plan {String(plan.plan_sha256 ?? "unavailable").slice(0, 12)}</p>
      </div>
      <div>
        <span>Bounded search</span>
        <p>{humanizeCampaignValue(String(plan.search_disposition ?? plan.status ?? "UNKNOWN"))} · {Number(plan.generated_candidate_count ?? candidates.length)} generated · {Number(plan.retained_candidate_count ?? candidates.length)} retained · {Array.isArray(plan.representative_candidate_sha256s) ? plan.representative_candidate_sha256s.length : 0} representative · {plan.bounded_search_complete === true ? "declared bounds complete" : "bounds incomplete"}</p>
      </div>
      {certificate ? (
        <div>
          <span>Independent feasibility certificate</span>
          <p>{certificate.passed === true ? "PASS" : "FAIL"} · protected pairwise clearance {Number(certificate.minimum_pairwise_protected_clearance_m ?? 0).toFixed(3)} m · protected solid clearance {Number(certificate.minimum_solid_protected_clearance_m ?? 0).toFixed(3)} m · boundary clearance {Number(certificate.minimum_boundary_clearance_m ?? 0).toFixed(3)} m · certificate {String(certificate.certificate_sha256 ?? "unavailable").slice(0, 12)}</p>
        </div>
      ) : null}
      {routes.map((route) => {
        const points = Array.isArray(route.points_m) ? route.points_m as Array<Record<string, unknown>> : [];
        return <div key={String(route.role_id)}><span>{String(route.role_id)} route</span><p>{points.map((point) => `(${Number(point.x).toFixed(2)}, ${Number(point.y).toFixed(2)}, ${Number(point.z).toFixed(2)})`).join(" → ")}</p></div>;
      })}
      {campaignCase?.semantics?.scenario_events.length ? <div><span>Event triggers</span><p>{campaignCase.semantics.scenario_events.map((event) => `${event.trigger_time_s.toFixed(1)}s ${humanizeCampaignValue(event.kind)}`).join(" · ")}</p></div> : null}
    </article>
  );
}
