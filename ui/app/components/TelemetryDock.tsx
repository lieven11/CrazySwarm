"use client";

import { ChevronDown, ChevronUp, Download, FileSpreadsheet, LoaderCircle, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import type { DashboardModel, RangeRay, RunFileMissionView, TwinSessionView, Vec3, VehicleView } from "../lib/models";
import { formatClockContext } from "./RoomScene";

export type TelemetrySample = {
  t: number;
  altitude?: number;
  speed?: number;
  battery?: number;
  current?: number;
  localization?: number;
};

type TrendMetric = "altitude" | "speed" | "battery" | "current";

export function RunFilesControl({
  missions = [],
  loaded = false,
  loading = false,
  error,
  onLoad = () => undefined,
}: {
  missions?: RunFileMissionView[];
  loaded?: boolean;
  loading?: boolean;
  error?: string;
  onLoad?: () => void;
}) {
  return (
    <details
      className="run-files-control"
      onToggle={(event) => {
        if (event.currentTarget.open && !loaded && !loading) {
          onLoad();
        }
      }}
    >
      <summary className="run-files-toggle">
        <FileSpreadsheet size={17} />
        <span>Run files{loaded ? <small>{missions.length}</small> : null}</span>
        <ChevronUp className="run-files-chevron" size={14} />
      </summary>
      <section className="run-files-popover" aria-label="Previous run files">
        <header>
          <span><strong>Run files</strong><small>Telemetry CSV exports</small></span>
          {loaded ? <small>{missions.length} missions</small> : null}
        </header>
        <div className="run-files-body">
          {loading ? (
            <p className="run-files-state" role="status"><LoaderCircle className="spin" size={14} />Loading previous runs</p>
          ) : null}
          {error ? (
            <div className="run-files-error" role="alert">
              <span>{error}</span>
              <button type="button" onClick={onLoad}><RefreshCw size={13} />Retry</button>
            </div>
          ) : null}
          {loaded && !missions.length ? (
            <p className="run-files-state">No previous runs</p>
          ) : null}
          {missions.length ? (
            <div className="run-files-list" role="list" aria-label="Previous run CSV files">
              {missions.map((mission) => (
                <RunFileMission key={mission.missionExecutionId} mission={mission} />
              ))}
            </div>
          ) : null}
        </div>
      </section>
    </details>
  );
}

export function FlightReadout({
  model,
  vehicle,
  twin,
  samples,
  expanded,
  onToggle,
}: {
  model: DashboardModel;
  vehicle?: VehicleView;
  twin?: TwinSessionView;
  samples: TelemetrySample[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const [trendMetric, setTrendMetric] = useState<TrendMetric>("altitude");
  const [systemsOpen, setSystemsOpen] = useState(true);
  const data = vehicle?.telemetry;
  if (!vehicle || !data) return null;

  const speed = data.velocity ? vectorMagnitude(data.velocity) : undefined;
  const nearestRange = data.ranges
    .filter((range) => range.distanceM !== null)
    .sort((left, right) => left.distanceM! - right.distanceM!)[0];
  const nearest = nearestRange?.distanceM ?? undefined;
  const batteryTone = data.batteryPercent !== undefined && data.batteryPercent <= 15
    ? "critical"
    : data.batteryPercent !== undefined && data.batteryPercent <= 30
      ? "warning"
      : "normal";
  const rangeTone = nearest !== undefined && nearest < .2 ? "critical" : nearest !== undefined && nearest < .45 ? "warning" : "normal";

  return (
    <aside className={`flight-readout ${expanded ? "is-expanded" : ""}`} aria-label="Flight telemetry">
      <button className="flight-readout-summary" type="button" aria-expanded={expanded} onClick={onToggle}>
        <ReadoutValue label="Battery" value={formatValue(data.batteryPercent, 0)} unit="%" tone={batteryTone} />
        <ReadoutValue label="World Z" value={formatValue(data.estimate?.z, 2)} unit="m" />
        <ReadoutValue label="Speed" value={formatValue(speed, 2)} unit="m/s" />
        <ReadoutValue label="Nearest" value={formatValue(nearest, 2)} unit="m" tone={rangeTone} />
        <span className="readout-chevron" aria-hidden="true">{expanded ? <ChevronDown size={16} /> : <ChevronUp size={16} />}</span>
      </button>

      {expanded ? (
        <div className="flight-readout-detail">
          <InstrumentCluster
            battery={data.batteryPercent}
            altitude={data.estimate?.z}
            speed={speed}
            nearest={nearest}
            nearestMaximum={nearestRange?.maximumM}
            roomHeight={model.room?.heightM}
            batteryTone={batteryTone}
            rangeTone={rangeTone}
          />
          <div className="trend-switch" role="group" aria-label="Trend metric">
            {(["altitude", "speed", "battery", "current"] as const).map((metric) => (
              <button key={metric} type="button" className={metric === trendMetric ? "is-active" : ""} onClick={() => setTrendMetric(metric)}>
                {metric === "altitude" ? "Z" : sentenceCase(metric)}
              </button>
            ))}
          </div>
          <TrendChart samples={samples} metric={trendMetric} source={vehicle.observationClass} />

          {hasSystemDetail(vehicle) ? (
            <details
              className="detail-disclosure"
              open={systemsOpen}
              onToggle={(event) => setSystemsOpen(event.currentTarget.open)}
            >
              <summary>Systems <ChevronDown size={15} /></summary>
              <div className="disclosure-body">
                {data.motors ? (
                  <section className="detail-group">
                    <h3>Motors</h3>
                    <div className="motor-lines">
                      {data.motors.readings.map((motor) => (
                        <div key={motor.id}>
                          <span>{motor.id}</span>
                          <i aria-hidden="true"><b style={{ width: `${clamp(motor.commandPercent, 0, 100)}%` }} /></i>
                          <strong>{motor.commandPercent.toFixed(0)}%</strong>
                        </div>
                      ))}
                    </div>
                    <small>{data.motors.modelId} · {data.motors.modelVersion}</small>
                  </section>
                ) : null}

                {data.imu || data.attitude ? (
                  <section className="detail-group">
                    <h3>Attitude &amp; IMU</h3>
                    {data.attitude ? <AttitudeAxes attitude={data.attitude} /> : null}
                    {data.imu ? (
                      <div className="imu-vectors">
                        <VectorBars label="Acceleration" vector={data.imu.acceleration} unit="m/s²" displayRange={10} />
                        <VectorBars label="Angular velocity" vector={data.imu.angularVelocity} unit="rad/s" displayRange={5} />
                      </div>
                    ) : null}
                  </section>
                ) : null}

                {data.flow ? (
                  <section className="detail-group">
                    <h3>Flow</h3>
                    {data.flow.groundDistanceM !== undefined ? <DataRow label="Ground distance" value={`${data.flow.groundDistanceM.toFixed(2)} m`} /> : null}
                    {data.flow.qualityPercent !== undefined ? <PercentageBar label="Quality" value={data.flow.qualityPercent} /> : null}
                    <VectorBars label="Velocity" vector={data.flow.velocity} unit="m/s" displayRange={1} />
                    <small>Relative · drift-prone</small>
                  </section>
                ) : null}

                {data.ranges.length ? (
                  <section className="detail-group">
                    <h3>Ranges</h3>
                    <RangeBars ranges={data.ranges} />
                  </section>
                ) : null}

                {data.radio || data.transport ? (
                  <section className="detail-group">
                    <h3>{data.radio ? "Radio" : "Modeled transport"}</h3>
                    {(data.radio?.qualityPercent ?? data.transport?.deliveryQualityPercent) !== undefined ? <PercentageBar label="Quality" value={(data.radio?.qualityPercent ?? data.transport?.deliveryQualityPercent)!} /> : null}
                    {(data.radio?.latencyMs ?? data.transport?.latencyMs) !== undefined ? <DataRow label="Latency" value={`${(data.radio?.latencyMs ?? data.transport?.latencyMs)!.toFixed(0)} ms`} /> : null}
                    {!data.radio ? <small>Not physical radio data</small> : null}
                  </section>
                ) : null}
              </div>
            </details>
          ) : null}

          <details className="detail-disclosure">
            <summary>Evidence <ChevronDown size={15} /></summary>
            <div className="disclosure-body">
              <section className="detail-group">
                <DataRow label="Source" value={sourceLabel(vehicle.observationClass)} />
                <DataRow label="Status" value={sentenceCase(vehicle.observationStatus)} />
                <DataRow label="Freshness" value={sentenceCase(data.provenance.freshness)} />
                <DataRow label="Clock" value={formatClockContext(data.provenance)} />
                {vehicle.observationRunId ? <DataRow label="Run" value={vehicle.observationRunId} mono /> : null}
              </section>
              {model.room ? (
                <section className="detail-group">
                  <h3>{model.room.id}</h3>
                  <DataRow label="World volume" value={`${model.room.widthM} × ${model.room.depthM} × ${model.room.heightM} m`} />
                  <DataRow label="Version" value={String(model.room.version)} />
                </section>
              ) : null}
              {model.fidelity ? (
                <section className="detail-group">
                  <h3>Fidelity</h3>
                  <DataRow label="Model" value={model.fidelity.model} />
                  <small>{model.fidelity.limitations.join(" · ")}</small>
                </section>
              ) : null}
              {twin?.latestDeviation ? (
                <section className="detail-group">
                  <h3>Twin residual</h3>
                  {twin.latestDeviation.positionM !== undefined ? <DataRow label="Position" value={`${twin.latestDeviation.positionM.toFixed(3)} m`} /> : null}
                  <DataRow label="Clock alignment" value={`${twin.latestDeviation.alignmentDeltaMs.toFixed(1)} ms`} />
                  <small>{twin.groundTruthAvailable ? "External ground truth" : "No external ground truth"}</small>
                </section>
              ) : null}
            </div>
          </details>
        </div>
      ) : null}
    </aside>
  );
}

function RunFileMission({ mission }: { mission: RunFileMissionView }) {
  const sampleCount = `${mission.telemetryRowCount} ${mission.telemetryRowCount === 1 ? "sample" : "samples"}`;
  return (
    <article
      className="run-file-mission"
      role="listitem"
      title={`${formatRunStart(mission.startedAtUtc)} · ${mission.filename ?? "Recording"}`}
    >
      <span className={`run-file-status status-${mission.status.toLowerCase()}`}>{mission.status === "INCOMPLETE" ? "RECORDING" : mission.status}</span>
      <strong className="run-file-mission-name">{mission.missionName}</strong>
      {mission.available && mission.downloadUrl && mission.filename ? (
        <a
          className="run-file-download"
          href={mission.downloadUrl}
          download={mission.filename}
          aria-label={`Download ${mission.filename}`}
          title={`Download ${mission.filename}`}
        >
          <Download size={14} />
        </a>
      ) : (
        <span className="run-file-download is-disabled" aria-hidden="true"><Download size={14} /></span>
      )}
      <span className="run-file-count">{mission.status === "INCOMPLETE" ? "Recording" : sampleCount}</span>
    </article>
  );
}

function formatRunStart(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "UTC unavailable" : date.toISOString().replace(".000Z", "Z");
}

function ReadoutValue({ label, value, unit, tone = "normal" }: { label: string; value: string; unit: string; tone?: string }) {
  return (
    <span className={`readout-value value-${tone}`}>
      <small>{label}</small>
      <span><strong>{value}</strong><i>{unit}</i></span>
    </span>
  );
}

function InstrumentCluster({
  battery,
  altitude,
  speed,
  nearest,
  nearestMaximum,
  roomHeight,
  batteryTone,
  rangeTone,
}: {
  battery?: number;
  altitude?: number;
  speed?: number;
  nearest?: number;
  nearestMaximum?: number;
  roomHeight?: number;
  batteryTone: string;
  rangeTone: string;
}) {
  return (
    <section className="instrument-cluster" aria-label="Visual flight instruments">
      <div className="arc-gauges">
        <ArcGauge label="Battery" value={battery} maximum={100} decimals={0} unit="%" tone={batteryTone} />
        <ArcGauge label="Clearance" value={nearest} maximum={nearestMaximum} decimals={2} unit="m" tone={rangeTone} />
      </div>
      <div className="instrument-bars">
        <LinearInstrument label="World Z" value={altitude} maximum={roomHeight} unit="m" decimals={2} />
        <LinearInstrument label="Speed" value={speed} maximum={1.5} unit="m/s" decimals={2} />
      </div>
    </section>
  );
}

function ArcGauge({ label, value, maximum, decimals, unit, tone }: { label: string; value?: number; maximum?: number; decimals: number; unit: string; tone: string }) {
  const percent = value === undefined || maximum === undefined || maximum <= 0 ? 0 : clamp(value / maximum * 100, 0, 100);
  const readableValue = value === undefined ? "—" : value.toFixed(decimals);
  return (
    <div className={`arc-gauge gauge-${label.toLowerCase()} gauge-${tone}`} role="img" aria-label={`${label} ${readableValue} ${unit}${maximum ? ` of ${maximum.toFixed(decimals)} ${unit}` : ""}`}>
      <svg viewBox="0 0 112 66" aria-hidden="true">
        <path className="arc-track" pathLength="100" d="M 12 57 A 44 44 0 0 1 100 57" />
        <path className="arc-value" pathLength="100" d="M 12 57 A 44 44 0 0 1 100 57" style={{ strokeDasharray: `${percent} 100` }} />
      </svg>
      <span><strong>{readableValue}</strong><i>{unit}</i><small>{label}</small></span>
    </div>
  );
}

function LinearInstrument({ label, value, maximum, unit, decimals }: { label: string; value?: number; maximum?: number; unit: string; decimals: number }) {
  const validMaximum = maximum !== undefined && maximum > 0 ? maximum : undefined;
  const percent = value === undefined || !validMaximum ? 0 : clamp(value / validMaximum * 100, 0, 100);
  return (
    <div className="linear-instrument">
      <span><small>{label}</small><strong>{value === undefined ? "—" : value.toFixed(decimals)} <i>{unit}</i></strong></span>
      <b aria-hidden="true"><i style={{ width: `${percent}%` }} /></b>
      <em>0 — {validMaximum?.toFixed(decimals) ?? "—"} {unit}</em>
    </div>
  );
}

function AttitudeAxes({ attitude }: { attitude: { rollRad: number; pitchRad: number; yawRad: number } }) {
  return (
    <div className="attitude-axes" role="group" aria-label="Attitude around all axes">
      <AxisMeter label="Roll" axis="x" value={toDegrees(attitude.rollRad)} displayRange={45} unit="°" decimals={1} />
      <AxisMeter label="Pitch" axis="y" value={toDegrees(attitude.pitchRad)} displayRange={45} unit="°" decimals={1} />
      <AxisMeter label="Yaw" axis="z" value={toDegrees(attitude.yawRad)} displayRange={180} unit="°" decimals={1} />
    </div>
  );
}

function VectorBars({ label, vector, unit, displayRange }: { label: string; vector: Vec3; unit: string; displayRange: number }) {
  return (
    <div className="vector-bars" role="group" aria-label={`${label} on X Y and Z axes`}>
      <h4>{label}</h4>
      <AxisMeter label="X" axis="x" value={vector.x} displayRange={displayRange} unit={unit} decimals={2} />
      <AxisMeter label="Y" axis="y" value={vector.y} displayRange={displayRange} unit={unit} decimals={2} />
      <AxisMeter label="Z" axis="z" value={vector.z} displayRange={displayRange} unit={unit} decimals={2} />
    </div>
  );
}

function AxisMeter({ label, axis, value, displayRange, unit, decimals }: { label: string; axis: "x" | "y" | "z"; value: number; displayRange: number; unit: string; decimals: number }) {
  const position = 50 + clamp(value / displayRange, -1, 1) * 48;
  const start = Math.min(50, position);
  const width = Math.abs(position - 50);
  return (
    <div className={`axis-meter axis-${axis}`}>
      <span>{label}</span>
      <i aria-hidden="true"><b style={{ left: `${start}%`, width: `${width}%` }} /><em style={{ left: `${position}%` }} /></i>
      <strong>{signedFixed(value, decimals)} {unit}</strong>
    </div>
  );
}

function PercentageBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="percentage-bar">
      <span><small>{label}</small><strong>{value.toFixed(0)}%</strong></span>
      <i aria-hidden="true"><b style={{ width: `${clamp(value, 0, 100)}%` }} /></i>
    </div>
  );
}

function RangeBars({ ranges }: { ranges: RangeRay[] }) {
  return (
    <div className="range-bars">
      {ranges.map((range) => {
        const percent = range.distanceM === null ? 0 : clamp(range.distanceM / range.maximumM * 100, 0, 100);
        const tone = range.distanceM === null ? "unavailable" : range.distanceM < .2 ? "critical" : range.distanceM < .45 ? "warning" : "normal";
        return (
          <div className={`range-bar range-${tone}`} key={range.direction}>
            <span><small>{sentenceCase(range.direction)}</small><strong>{range.distanceM === null ? "—" : `${range.distanceM.toFixed(2)} m`}</strong></span>
            <i aria-hidden="true"><b style={{ width: `${percent}%` }} /></i>
          </div>
        );
      })}
    </div>
  );
}

function TrendChart({ samples, metric, source }: { samples: TelemetrySample[]; metric: TrendMetric; source: VehicleView["observationClass"] }) {
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
    return <div className="trend-empty"><strong>{latest === undefined ? "—" : latest.toFixed(definition.decimals)}</strong><span>{definition.unit} · collecting</span></div>;
  }

  const min = Math.min(...values.map((point) => point.value));
  const max = Math.max(...values.map((point) => point.value));
  const range = max - min || 1;
  const start = values[0].t;
  const duration = values.at(-1)!.t - start || 1;
  const points = values.map((point) => {
    const x = 3 + ((point.t - start) / duration) * 314;
    const y = 88 - ((point.value - min) / range) * 72;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  return (
    <div className={`trend-chart source-${source.toLowerCase()}`}>
      <div className="trend-current"><strong>{latest?.toFixed(definition.decimals) ?? "—"}</strong><span>{definition.unit} · {definition.label}</span></div>
      <svg viewBox="0 0 320 94" role="img" aria-label={`${definition.label} from ${min.toFixed(definition.decimals)} to ${max.toFixed(definition.decimals)} ${definition.unit} over ${Math.min(60, Math.round(duration))} seconds`}>
        <polyline className="trend-line" points={points} fill="none" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="trend-range"><span>{min.toFixed(definition.decimals)}</span><span>{max.toFixed(definition.decimals)}</span></div>
    </div>
  );
}

const TREND_DEFINITIONS: Record<TrendMetric, { label: string; unit: string; decimals: number }> = {
  altitude: { label: "World Z", unit: "m", decimals: 2 },
  speed: { label: "Speed", unit: "m/s", decimals: 2 },
  battery: { label: "Battery", unit: "%", decimals: 0 },
  current: { label: "Current", unit: "A", decimals: 2 },
};

function hasSystemDetail(vehicle: VehicleView) {
  const data = vehicle.telemetry;
  return Boolean(data?.motors || data?.attitude || data?.imu || data?.flow || data?.ranges.length || data?.radio || data?.transport);
}

function DataRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="data-row"><span>{label}</span><strong className={mono ? "is-mono" : ""}>{value}</strong></div>;
}

function sourceLabel(source: VehicleView["observationClass"]) {
  const labels: Record<VehicleView["observationClass"], string> = {
    MEASURED_REAL: "Measured real",
    SIMULATED_MODEL: "Simulated model",
    DERIVED: "Derived",
    PLANNED: "Planned",
    CONFIGURED: "Configured",
    REPLAYED: "Replayed",
    UNAVAILABLE: "Unavailable",
  };
  return labels[source];
}

function vectorMagnitude(vector: Vec3) {
  return Math.hypot(vector.x, vector.y, vector.z);
}

function formatValue(value: number | undefined, decimals: number) {
  return value === undefined ? "—" : value.toFixed(decimals);
}

function signedFixed(value: number, decimals: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}`;
}

function toDegrees(value: number) {
  return value * 180 / Math.PI;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

function sentenceCase(value: string) {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase());
}
