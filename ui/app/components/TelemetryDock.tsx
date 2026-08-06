"use client";

import {
  Activity,
  BatteryCharging,
  ChevronRight,
  CircleGauge,
  Cpu,
  Crosshair,
  Gauge,
  RadioTower,
  Radar,
  Route,
  Satellite,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import type {
  DashboardModel,
  EvidenceClass,
  RangeRay,
  TwinSessionView,
  Vec3,
  VehicleView,
} from "../lib/models";
import { formatClockContext } from "./RoomScene";

export type TelemetrySample = {
  t: number;
  altitude?: number;
  speed?: number;
  battery?: number;
  current?: number;
  localization?: number;
};

type TelemetryTab = "overview" | "systems" | "evidence";
type TrendMetric = "altitude" | "speed" | "battery" | "current";

export function TelemetryDock({
  model,
  vehicle,
  twin,
  samples,
  onCollapse,
}: {
  model: DashboardModel;
  vehicle?: VehicleView;
  twin?: TwinSessionView;
  samples: TelemetrySample[];
  onCollapse: () => void;
}) {
  const [tab, setTab] = useState<TelemetryTab>("overview");
  const data = vehicle?.telemetry;
  const freshness = data?.provenance.freshness ?? "absent";

  return (
    <aside className="telemetry-dock" aria-label="Telemetry and evidence">
      <header className="telemetry-header">
        <div className="telemetry-identity">
          <span className={`status-orb status-${statusTone(vehicle?.state, freshness)}`} aria-hidden="true" />
          <span>
            <small>ACTIVE VEHICLE</small>
            <strong>{vehicle?.name ?? "No vehicle"}</strong>
          </span>
        </div>
        <button className="dock-collapse" type="button" onClick={onCollapse} aria-label="Collapse telemetry">
          <ChevronRight size={17} />
        </button>
        <div className="telemetry-context">
          <span>{vehicle?.state ? sentenceCase(vehicle.state) : "Unavailable"}</span>
          <SourceChip source={vehicle?.observationClass ?? "UNAVAILABLE"} />
          {data ? <span className={freshness === "current" ? "freshness-current" : "freshness-stale"}>{sentenceCase(freshness)}{data.provenance.ageMs !== undefined ? ` · ${Math.round(data.provenance.ageMs)} ms` : ""}</span> : null}
        </div>
      </header>

      <div className="telemetry-tabs" role="tablist" aria-label="Telemetry views">
        {(["overview", "systems", "evidence"] as const).map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={tab === item}
            className={tab === item ? "is-active" : ""}
            onClick={() => setTab(item)}
          >
            {sentenceCase(item)}
          </button>
        ))}
      </div>

      <div className="telemetry-scroll">
        {tab === "overview" ? <OverviewView vehicle={vehicle} samples={samples} /> : null}
        {tab === "systems" ? <SystemsView vehicle={vehicle} /> : null}
        {tab === "evidence" ? <EvidenceView model={model} vehicle={vehicle} twin={twin} /> : null}
      </div>
    </aside>
  );
}

function OverviewView({ vehicle, samples }: { vehicle?: VehicleView; samples: TelemetrySample[] }) {
  const [trendMetric, setTrendMetric] = useState<TrendMetric>("altitude");
  const data = vehicle?.telemetry;
  const source = vehicle?.observationClass ?? "UNAVAILABLE";
  const speed = data?.velocity ? vectorMagnitude(data.velocity) : undefined;
  const altitude = data?.estimate?.z;
  const batteryTone = data?.batteryPercent !== undefined && data.batteryPercent <= 15
    ? "critical"
    : data?.batteryPercent !== undefined && data.batteryPercent <= 30
      ? "warning"
      : sourceTone(source);
  const localizationTone = data?.localizationPercent !== undefined && data.localizationPercent < 50
    ? "critical"
    : data?.localizationPercent !== undefined && data.localizationPercent < 75
      ? "warning"
      : sourceTone(source);

  if (!data) {
    return (
      <div className="telemetry-empty">
        <Radar size={24} />
        <strong>No observation</strong>
        <p>The configured room remains available. Live values will appear when a truthful observation is received.</p>
      </div>
    );
  }

  return (
    <div className="overview-grid">
      <MetricTile
        title={vehicle?.adapter === "sim" ? "Battery model" : "Battery"}
        icon={<BatteryCharging size={15} />}
        value={formatValue(data.batteryPercent, 0)}
        unit="%"
        detail={batteryDetail(data.batteryVoltage, data.batteryCurrent)}
        tone={batteryTone}
        progress={data.batteryPercent}
        series={samples.map((point) => point.battery)}
      />
      <MetricTile
        title="World Z"
        icon={<Route size={15} />}
        value={formatValue(altitude, 2)}
        unit="m"
        detail={data.estimate ? `X ${signed(data.estimate.x)} · Y ${signed(data.estimate.y)}` : "Position unavailable"}
        tone={sourceTone(source)}
        series={samples.map((point) => point.altitude)}
      />
      <MetricTile
        title="Speed"
        icon={<Gauge size={15} />}
        value={formatValue(speed, 2)}
        unit="m/s"
        detail={data.velocity ? vectorText(data.velocity, 2) : "Velocity unavailable"}
        tone={sourceTone(source)}
        series={samples.map((point) => point.speed)}
      />
      <MetricTile
        title="Localization"
        icon={<Crosshair size={15} />}
        value={formatValue(data.localizationPercent, 0)}
        unit="%"
        detail={data.localizationLabel ?? (data.localizationPercent === undefined ? "Unavailable" : "Quality")}
        tone={localizationTone}
        progress={data.localizationPercent}
        series={samples.map((point) => point.localization)}
      />

      <section className="telemetry-tile trend-tile">
        <header className="tile-heading">
          <span><Activity size={15} />Flight trend</span>
          <span className="window-chip">60 s</span>
        </header>
        <div className="trend-switch" role="group" aria-label="Trend metric">
          {(["altitude", "speed", "battery", "current"] as const).map((metric) => (
            <button key={metric} type="button" className={metric === trendMetric ? "is-active" : ""} onClick={() => setTrendMetric(metric)}>
              {metric === "altitude" ? "Z" : sentenceCase(metric)}
            </button>
          ))}
        </div>
        <TrendChart samples={samples} metric={trendMetric} tone={sourceTone(source)} />
      </section>

      <ProximityTile ranges={data.ranges} source={source} />
    </div>
  );
}

function MetricTile({
  title,
  icon,
  value,
  unit,
  detail,
  tone,
  progress,
  series,
}: {
  title: string;
  icon: ReactNode;
  value: string;
  unit: string;
  detail: string;
  tone: string;
  progress?: number;
  series: Array<number | undefined>;
}) {
  return (
    <article className={`telemetry-tile metric-tile tone-${tone}`}>
      <header className="tile-heading"><span>{icon}{title}</span></header>
      <div className="metric-value"><strong>{value}</strong><span>{unit}</span></div>
      <p>{detail}</p>
      {progress !== undefined ? (
        <div className="metric-progress" role="progressbar" aria-label={title} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)}>
          <span style={{ width: `${clamp(progress, 0, 100)}%` }} />
        </div>
      ) : <Sparkline values={series} />}
    </article>
  );
}

function Sparkline({ values }: { values: Array<number | undefined> }) {
  const points = chartPoints(values.filter((value): value is number => value !== undefined), 112, 22);
  if (!points) return <span className="sparkline-empty">COLLECTING</span>;
  return (
    <svg className="sparkline" viewBox="0 0 112 22" role="img" aria-label="Recent trend">
      <polyline points={points} fill="none" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function TrendChart({ samples, metric, tone }: { samples: TelemetrySample[]; metric: TrendMetric; tone: string }) {
  const definition = TREND_DEFINITIONS[metric];
  const values = useMemo(() => {
    const latestTime = samples.at(-1)?.t;
    if (latestTime === undefined) return [];
    return samples
      .filter((sample) => latestTime - sample.t <= 60 && sample[metric] !== undefined)
      .map((sample) => ({ t: sample.t, value: sample[metric] as number }));
  }, [metric, samples]);
  const latest = values.at(-1)?.value;

  if (values.length < 2) {
    return (
      <div className="trend-empty">
        <span>Trend collecting</span>
        <strong>{latest === undefined ? "—" : latest.toFixed(definition.decimals)} {definition.unit}</strong>
      </div>
    );
  }

  const min = Math.min(...values.map((point) => point.value));
  const max = Math.max(...values.map((point) => point.value));
  const range = max - min || 1;
  const start = values[0].t;
  const duration = values.at(-1)!.t - start || 1;
  const points = values.map((point) => {
    const x = 8 + ((point.t - start) / duration) * 304;
    const y = 94 - ((point.value - min) / range) * 76;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const description = `${definition.label} ranges from ${min.toFixed(definition.decimals)} to ${max.toFixed(definition.decimals)} ${definition.unit} over the latest ${Math.min(60, Math.round(duration))} seconds.`;

  return (
    <div className={`trend-chart tone-${tone}`}>
      <div className="trend-current"><strong>{latest?.toFixed(definition.decimals) ?? "—"}</strong><span>{definition.unit} · {definition.label}</span></div>
      <svg viewBox="0 0 320 102" role="img" aria-label={description}>
        <line x1="8" x2="312" y1="18" y2="18" />
        <line x1="8" x2="312" y1="56" y2="56" />
        <line x1="8" x2="312" y1="94" y2="94" />
        <polyline className="trend-line" points={points} fill="none" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="trend-range"><span>{min.toFixed(definition.decimals)} min</span><span>{max.toFixed(definition.decimals)} max</span></div>
    </div>
  );
}

const TREND_DEFINITIONS: Record<TrendMetric, { label: string; unit: string; decimals: number }> = {
  altitude: { label: "World Z", unit: "m", decimals: 2 },
  speed: { label: "Speed", unit: "m/s", decimals: 2 },
  battery: { label: "Battery", unit: "%", decimals: 0 },
  current: { label: "Current", unit: "A", decimals: 2 },
};

function ProximityTile({ ranges, source }: { ranges: RangeRay[]; source: EvidenceClass }) {
  const available = ranges.filter((range) => range.distanceM !== null);
  const nearest = available.length ? Math.min(...available.map((range) => range.distanceM as number)) : undefined;
  return (
    <section className="telemetry-tile proximity-tile">
      <header className="tile-heading">
        <span><Radar size={15} />Proximity</span>
        <SourceChip source={source} />
      </header>
      <div className="proximity-summary"><strong>{nearest === undefined ? "—" : nearest.toFixed(2)}</strong><span>m nearest</span></div>
      {ranges.length ? (
        <div className="range-grid">
          {ranges.map((ray) => {
            const percent = ray.distanceM === null ? 0 : clamp(ray.distanceM / ray.maximumM * 100, 0, 100);
            const tone = ray.distanceM === null ? "absent" : percent < 18 ? "critical" : percent < 35 ? "warning" : "normal";
            return (
              <div className={`range-meter range-${tone}`} key={ray.direction}>
                <span><small>{ray.direction}</small><strong>{ray.distanceM === null ? "—" : `${ray.distanceM.toFixed(2)} m`}</strong></span>
                <i aria-hidden="true"><b style={{ width: `${percent}%` }} /></i>
              </div>
            );
          })}
        </div>
      ) : <div className="tile-empty">Range data unavailable</div>}
    </section>
  );
}

function SystemsView({ vehicle }: { vehicle?: VehicleView }) {
  const data = vehicle?.telemetry;
  if (!data) return <DockEmpty title="Systems unavailable" body="No telemetry has been received for this vehicle." />;
  return (
    <div className="systems-stack">
      {data.motors ? (
        <section className="telemetry-tile systems-card">
          <header className="tile-heading"><span><Cpu size={15} />Motor balance</span><span className="window-chip">{data.motors.modelVersion}</span></header>
          <div className="motor-bars">
            {data.motors.readings.map((motor) => (
              <div className="motor-column" key={motor.id}>
                <div className="motor-track"><span style={{ height: `${clamp(motor.commandPercent, 0, 100)}%` }} /></div>
                <strong>{motor.id}</strong>
                <small>{motor.commandPercent.toFixed(0)}%</small>
                <small>{motor.currentA.toFixed(2)} A</small>
              </div>
            ))}
          </div>
          <p className="system-source">{data.motors.modelId} · simulated motor model</p>
        </section>
      ) : null}

      {data.imu ? (
        <section className="telemetry-tile systems-card">
          <header className="tile-heading"><span><Activity size={15} />Modeled IMU</span><SourceChip source={data.imu.provenance.evidenceClass} /></header>
          <VectorBlock label="Acceleration" vector={data.imu.acceleration} unit="m/s²" />
          <VectorBlock label="Angular velocity" vector={data.imu.angularVelocity} unit="rad/s" />
        </section>
      ) : null}

      {data.flow ? (
        <section className="telemetry-tile systems-card">
          <header className="tile-heading"><span><CircleGauge size={15} />Modeled Flow</span><SourceChip source={data.flow.provenance.evidenceClass} /></header>
          {data.flow.groundDistanceM !== undefined ? <DataRow label="Ground distance" value={`${data.flow.groundDistanceM.toFixed(2)} m`} /> : null}
          {data.flow.qualityPercent !== undefined ? <DataRow label="Quality" value={`${data.flow.qualityPercent.toFixed(0)}%`} /> : null}
          <VectorBlock label="Velocity" vector={data.flow.velocity} unit="m/s" />
          <p className="system-source">Relative · drift-prone</p>
        </section>
      ) : null}

      {data.radio || data.transport ? (
        <section className="telemetry-tile systems-card">
          <header className="tile-heading"><span><RadioTower size={15} />{data.radio ? "Physical radio" : "Modeled transport"}</span><SourceChip source={(data.radio ?? data.transport)!.evidenceClass} /></header>
          {(data.radio?.qualityPercent ?? data.transport?.deliveryQualityPercent) !== undefined ? <DataRow label="Quality" value={`${(data.radio?.qualityPercent ?? data.transport?.deliveryQualityPercent)!.toFixed(0)}%`} /> : null}
          {(data.radio?.latencyMs ?? data.transport?.latencyMs) !== undefined ? <DataRow label="Latency" value={`${(data.radio?.latencyMs ?? data.transport?.latencyMs)!.toFixed(0)} ms`} /> : null}
          {(data.radio?.packetLossPercent ?? data.transport?.packetLossPercent) !== undefined ? <DataRow label="Packet loss" value={`${(data.radio?.packetLossPercent ?? data.transport?.packetLossPercent)!.toFixed(1)}%`} /> : null}
          {!data.radio ? <p className="system-source">Not physical radio data</p> : null}
        </section>
      ) : null}

      {vehicle?.decks.length ? (
        <section className="telemetry-tile systems-card">
          <header className="tile-heading"><span><Satellite size={15} />{vehicle.adapter === "sim" ? "Sensor models" : "Decks"}</span></header>
          {vehicle.decks.map((deck) => <DataRow key={deck.id} label={deck.name} value={vehicle.adapter === "sim" ? "Modeled" : sentenceCase(deck.health)} />)}
        </section>
      ) : null}

      {!data.motors && !data.imu && !data.flow && !data.radio && !data.transport && !vehicle?.decks.length ? <DockEmpty title="No system detail" body="This adapter has not supplied detailed system telemetry." /> : null}
    </div>
  );
}

function EvidenceView({ model, vehicle, twin }: { model: DashboardModel; vehicle?: VehicleView; twin?: TwinSessionView }) {
  const data = vehicle?.telemetry;
  return (
    <div className="systems-stack evidence-stack">
      <section className="telemetry-tile systems-card">
        <header className="tile-heading"><span><Crosshair size={15} />Observation</span><SourceChip source={vehicle?.observationClass ?? "UNAVAILABLE"} /></header>
        <DataRow label="Status" value={vehicle?.observationStatus ? sentenceCase(vehicle.observationStatus) : "Unavailable"} />
        {data?.estimate ? <VectorBlock label="Position" vector={data.estimate} unit={`m · ${data.provenance.frame}`} /> : null}
        {data ? <DataRow label="Freshness" value={sentenceCase(data.provenance.freshness)} /> : null}
        {data ? <DataRow label="Clock" value={formatClockContext(data.provenance)} /> : null}
        {data?.provenance.sourceClockId ? <DataRow label="Source clock" value={data.provenance.sourceClockId} mono /> : null}
        {vehicle?.observationRunId ? <DataRow label="Run" value={vehicle.observationRunId} mono /> : null}
      </section>

      {model.room ? (
        <section className="telemetry-tile systems-card">
          <header className="tile-heading"><span><Route size={15} />Room / world frame</span><SourceChip source="CONFIGURED" /></header>
          <DataRow label="Room" value={model.room.id} />
          <DataRow label="Volume" value={`${model.room.widthM} × ${model.room.depthM} × ${model.room.heightM} m`} />
          <DataRow label="Version" value={String(model.room.version)} />
        </section>
      ) : null}

      {model.fidelity ? (
        <section className="telemetry-tile systems-card">
          <header className="tile-heading"><span><Cpu size={15} />Simulation fidelity</span><SourceChip source={model.fidelity.sourceClass} /></header>
          <DataRow label="Manifest" value={model.fidelity.id} mono />
          <DataRow label="Model" value={model.fidelity.model} />
          <p className="evidence-copy">{model.fidelity.limitations.join(" · ")}</p>
        </section>
      ) : null}

      {twin?.latestDeviation ? (
        <section className="telemetry-tile systems-card">
          <header className="tile-heading"><span><Activity size={15} />Digital twin residual</span><SourceChip source="DERIVED" /></header>
          {twin.latestDeviation.positionM !== undefined ? <DataRow label="Position delta" value={`${twin.latestDeviation.positionM.toFixed(3)} m`} /> : null}
          {twin.latestDeviation.altitudeM !== undefined ? <DataRow label="Altitude delta" value={`${twin.latestDeviation.altitudeM.toFixed(3)} m`} /> : null}
          <DataRow label="Observed latency" value={`${twin.latestDeviation.observedLatencyMs.toFixed(1)} ms`} />
          <DataRow label="Twin latency" value={`${twin.latestDeviation.simulatedLatencyMs.toFixed(1)} ms`} />
          <DataRow label="Clock alignment" value={`${twin.latestDeviation.alignmentDeltaMs.toFixed(1)} ms`} />
          <p className="system-source">{twin.groundTruthAvailable ? "External ground truth" : "No external ground truth"}</p>
        </section>
      ) : null}
    </div>
  );
}

function VectorBlock({ label, vector, unit }: { label: string; vector: Vec3; unit: string }) {
  return (
    <div className="vector-block">
      <span>{label}</span>
      <div><strong>X {signed(vector.x)}</strong><strong>Y {signed(vector.y)}</strong><strong>Z {signed(vector.z)}</strong></div>
      <small>{unit}</small>
    </div>
  );
}

function DataRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="data-row"><span>{label}</span><strong className={mono ? "is-mono" : ""}>{value}</strong></div>;
}

function DockEmpty({ title, body }: { title: string; body: string }) {
  return <div className="telemetry-empty"><Radar size={24} /><strong>{title}</strong><p>{body}</p></div>;
}

export function SourceChip({ source }: { source: EvidenceClass }) {
  return <span className={`source-chip source-${source.toLowerCase()}`}>{sourceLabel(source)}</span>;
}

function sourceLabel(source: EvidenceClass) {
  const labels: Record<EvidenceClass, string> = {
    MEASURED_REAL: "Measured",
    SIMULATED_MODEL: "Modeled",
    DERIVED: "Derived",
    PLANNED: "Planned",
    CONFIGURED: "Configured",
    REPLAYED: "Replayed",
    UNAVAILABLE: "Unavailable",
  };
  return labels[source];
}

function sourceTone(source: EvidenceClass) {
  if (source === "SIMULATED_MODEL") return "modeled";
  if (source === "REPLAYED") return "replay";
  if (source === "UNAVAILABLE") return "muted";
  return "observed";
}

function statusTone(state?: string, freshness?: string) {
  if (state === "EMERGENCY" || state === "FAULT") return "critical";
  if (freshness === "stale" || state === "DEGRADED") return "warning";
  if (!state || state === "DISCONNECTED" || freshness === "absent" || freshness === "invalid") return "muted";
  return "healthy";
}

function chartPoints(values: number[], width: number, height: number) {
  if (values.length < 2) return undefined;
  const visible = values.slice(-40);
  const min = Math.min(...visible);
  const max = Math.max(...visible);
  const range = max - min || 1;
  return visible.map((value, index) => {
    const x = index / (visible.length - 1) * width;
    const y = height - 2 - (value - min) / range * (height - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function batteryDetail(voltage?: number, current?: number) {
  const parts = [];
  if (voltage !== undefined) parts.push(`${voltage.toFixed(2)} V`);
  if (current !== undefined) parts.push(`${current.toFixed(2)} A`);
  return parts.length ? parts.join(" · ") : "Electrical detail unavailable";
}

function vectorMagnitude(vector: Vec3) {
  return Math.hypot(vector.x, vector.y, vector.z);
}

function vectorText(vector: Vec3, decimals: number) {
  return `${signed(vector.x, decimals)} / ${signed(vector.y, decimals)} / ${signed(vector.z, decimals)}`;
}

function formatValue(value: number | undefined, decimals: number) {
  return value === undefined ? "—" : value.toFixed(decimals);
}

function signed(value: number, decimals = 2) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}`;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

function sentenceCase(value: string) {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase());
}
