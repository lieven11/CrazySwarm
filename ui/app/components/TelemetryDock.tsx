"use client";

import { ChevronDown, ChevronUp, Download, FileSpreadsheet, LoaderCircle, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { DashboardModel, RunFileMissionView, TwinSessionView, TwinTimelineSampleView, TwinTimelineView, Vec3, VehicleView } from "../lib/models";
import type { TwinSceneOverlay } from "./RoomScene";

export type TelemetrySample = {
  t: number;
  positionX?: number;
  positionY?: number;
  positionZ?: number;
  velocityX?: number;
  velocityY?: number;
  velocityZ?: number;
  speed?: number;
  nearest?: number;
  battery?: number;
  current?: number;
  localization?: number;
  roll?: number;
  pitch?: number;
  yaw?: number;
  accelerationX?: number;
  accelerationY?: number;
  accelerationZ?: number;
  angularVelocityX?: number;
  angularVelocityY?: number;
  angularVelocityZ?: number;
  motorM1?: number;
  motorM2?: number;
  motorM3?: number;
  motorM4?: number;
};

type TrendMetric = Exclude<keyof TelemetrySample, "t" | "localization">;
type TrendGroup = "position" | "velocity" | "acceleration" | "power" | "attitude" | "angularVelocity" | "motors";

export const MOTOR_STARTUP_TRIM_SECONDS = 3;
const MOTOR_ACTIVE_THRESHOLD_PERCENT = 1;

const TREND_GROUPS: readonly {
  id: TrendGroup;
  label: string;
  title: string;
  metrics: readonly TrendMetric[];
}[] = [
  { id: "position", label: "Position", title: "Position", metrics: ["positionX", "positionY", "positionZ"] },
  { id: "velocity", label: "Velocity", title: "Velocity", metrics: ["velocityX", "velocityY", "velocityZ"] },
  { id: "acceleration", label: "Acceleration", title: "Acceleration", metrics: ["accelerationX", "accelerationY", "accelerationZ"] },
  { id: "power", label: "Power", title: "Power", metrics: ["battery", "current"] },
  { id: "attitude", label: "Attitude", title: "Attitude", metrics: ["roll", "pitch", "yaw"] },
  { id: "angularVelocity", label: "Gyro", title: "Gyro", metrics: ["angularVelocityX", "angularVelocityY", "angularVelocityZ"] },
  { id: "motors", label: "Motors", title: "Motors", metrics: ["motorM1", "motorM2", "motorM3", "motorM4"] },
];

const MISSION_OVERVIEW_METRICS: readonly { metric: TrendMetric; label: string }[] = [
  { metric: "positionZ", label: "Height" },
  { metric: "speed", label: "Speed" },
  { metric: "battery", label: "Battery" },
  { metric: "nearest", label: "Nearest" },
];

export function RunFilesControl({
  missions = [],
  loaded = false,
  loading = false,
  error,
  onLoad = () => undefined,
  onDelete = () => undefined,
  deletingMissionId,
}: {
  missions?: RunFileMissionView[];
  loaded?: boolean;
  loading?: boolean;
  error?: string;
  onLoad?: () => void;
  onDelete?: (mission: RunFileMissionView) => void;
  deletingMissionId?: string;
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
                <RunFileMission
                  key={mission.missionExecutionId}
                  mission={mission}
                  deleting={deletingMissionId === mission.missionExecutionId}
                  onDelete={onDelete}
                />
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
  onLoadTwinTimeline?: (sessionId: string) => Promise<TwinTimelineView>;
  onTwinSceneOverlay?: (overlay?: TwinSceneOverlay) => void;
}) {
  const [trendGroupId, setTrendGroupId] = useState<TrendGroup>("position");
  const data = vehicle?.telemetry;
  if (!vehicle || !data) return null;
  const trendGroup = TREND_GROUPS.find((group) => group.id === trendGroupId) ?? TREND_GROUPS[0];

  const speed = data.velocity ? vectorMagnitude(data.velocity) : undefined;
  const batteryTone = data.batteryPercent !== undefined && data.batteryPercent <= 15
    ? "critical"
    : data.batteryPercent !== undefined && data.batteryPercent <= 30
      ? "warning"
      : "normal";
  const meanMotorPwm = data.motors
    ? data.motors.readings.reduce(
        (total, motor) => total + (motor.appliedPwmPercent ?? motor.commandPercent),
        0,
      ) / data.motors.readings.length
    : undefined;
  const positionDisplayRange = Math.max(model.room?.widthM ?? 0, model.room?.depthM ?? 0, model.room?.heightM ?? 0, 1);

  return (
    <aside className={`flight-readout ${expanded ? "is-expanded" : ""}`} aria-label="Flight telemetry">
      <button className="flight-readout-summary" type="button" aria-expanded={expanded} onClick={onToggle}>
        <ReadoutValue label="World Z" value={formatValue(data.estimate?.z, 2)} unit="m" />
        <ReadoutValue label="Speed" value={formatValue(speed, 2)} unit="m/s" />
        <ReadoutValue label="Battery" value={formatValue(data.batteryPercent, 0)} unit="%" tone={batteryTone} />
        <span className="readout-chevron" aria-hidden="true">{expanded ? <ChevronDown size={16} /> : <ChevronUp size={16} />}</span>
      </button>

      {expanded ? (
        <div className="flight-readout-detail">
          <MissionOverview samples={samples} />
          <section className="telemetry-category-nav" role="group" aria-label="Telemetry category">
            {TREND_GROUPS.map((group) => (
              <button
                key={group.id}
                type="button"
                className={group.id === trendGroup.id ? "is-active" : ""}
                aria-pressed={group.id === trendGroup.id}
                onClick={() => setTrendGroupId(group.id)}
              >
                {group.label}
              </button>
            ))}
          </section>
          <section className="telemetry-category-panel" aria-label={`${trendGroup.title} telemetry`}>
            <header>
              <h2>{trendGroup.title}</h2>
              <small>Last 60 seconds</small>
            </header>
            <TelemetryCategoryCurrent
              group={trendGroup.id}
              vehicle={vehicle}
              batteryTone={batteryTone}
              meanMotorPwm={meanMotorPwm}
              positionDisplayRange={positionDisplayRange}
            />
            <TrendChart samples={samples} metrics={trendGroup.metrics} group={trendGroup.id} />
          </section>
        </div>
      ) : null}
    </aside>
  );
}

type TwinViewGroup = "PATH" | "SENSORS" | "MOTORS" | "RESIDUALS" | "EVENTS";

const TWIN_GROUPS: readonly { id: TwinViewGroup; label: string }[] = [
  { id: "PATH", label: "Path" },
  { id: "SENSORS", label: "Sensors" },
  { id: "MOTORS", label: "Motors" },
  { id: "RESIDUALS", label: "Residuals" },
  { id: "EVENTS", label: "World & replan" },
];

export function twinSourceLabel(source: TwinSessionView["observedSourceClass"]): string {
  if (source === "MEASURED_REAL") return "Measured real adapter";
  if (source === "SIMULATED_MODEL") return "Simulated model";
  if (source === "TEST") return "Test-only source";
  return "Configured source";
}

export function TwinSessionPanel({
  twin,
  onLoad,
  onSceneOverlay,
}: {
  twin: TwinSessionView;
  onLoad: (sessionId: string) => Promise<TwinTimelineView>;
  onSceneOverlay?: (overlay?: TwinSceneOverlay) => void;
}) {
  const [timeline, setTimeline] = useState<TwinTimelineView>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [group, setGroup] = useState<TwinViewGroup>("PATH");
  const [cursor, setCursor] = useState(100);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(undefined);
    void onLoad(twin.id)
      .then(setTimeline)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Twin timeline is unavailable"))
      .finally(() => setLoading(false));
  }, [onLoad, twin.id]);

  // The selected session is an external data source; changing it must restart loading.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(refresh, [refresh]);
  const sourceTimes = useMemo(
    () => [...new Set(timeline?.samples.map((sample) => sample.sourceTimestampS) ?? [])].sort((left, right) => left - right),
    [timeline],
  );
  const cursorIndex = sourceTimes.length ? Math.min(sourceTimes.length - 1, Math.round((cursor / 100) * (sourceTimes.length - 1))) : 0;
  const cursorSourceS = sourceTimes[cursorIndex];
  const visibleSamples = useMemo(
    () => timeline?.samples.filter((sample) => cursorSourceS === undefined || sample.sourceTimestampS <= cursorSourceS) ?? [],
    [cursorSourceS, timeline],
  );
  const latest = visibleSamples.at(-1);
  const dataAgeMs = latest ? Math.max(0, latest.receivedTimestampS - latest.sourceTimestampS) * 1000 : undefined;
  const stale = visibleSamples.some((sample) => sample.availability === "STALE") || (dataAgeMs !== undefined && dataAgeMs > 250);

  useEffect(() => {
    onSceneOverlay?.(twinSceneOverlayFromSamples(visibleSamples, twin));
    return () => onSceneOverlay?.(undefined);
  }, [onSceneOverlay, twin, visibleSamples]);

  return (
    <section className="twin-session-panel" aria-label="Digital twin session">
      <header>
        <span>
          <strong>Digital twin</strong>
          <small>{twinSourceLabel(twin.observedSourceClass)} → {twinSourceLabel(twin.simulatedSourceClass)}</small>
        </span>
        <span className={`twin-quality ${error ? "is-error" : stale ? "is-stale" : "is-current"}`}>
          {error ? "ERROR" : stale ? "STALE" : latest?.quality ?? twin.status}
        </span>
      </header>
      <div className="twin-session-meta">
        <DataRow label="Outcome" value={twin.status} />
        <DataRow label="Primary residual" value={twin.latestDeviation?.positionM === undefined ? "Unavailable" : `${twin.latestDeviation.positionM.toFixed(3)} m · ${twin.latestDeviation.validity.toLowerCase()}`} />
        <DataRow label="Observed" value={twin.observedVehicleId} mono />
        <DataRow label="Predicted" value={twin.simulatedVehicleId} mono />
        <DataRow label="Observed source" value={twin.observedSourceId ?? twinSourceLabel(twin.observedSourceClass)} mono />
        <DataRow label="Predicted source" value={twin.simulatedSourceId ?? twinSourceLabel(twin.simulatedSourceClass)} mono />
        <DataRow label="Calibration" value={twin.calibrationId ?? "Uncalibrated predecessor"} mono />
        <DataRow label="Data age" value={dataAgeMs === undefined ? "Unavailable" : `${dataAgeMs.toFixed(0)} ms`} />
        <DataRow label="Ground truth" value={twin.groundTruthAvailable ? "Available" : "Not available"} />
        {twin.campaignReviewId ? <DataRow label="Campaign review" value={twin.campaignReviewId} mono /> : null}
      </div>
      <div className="twin-view-switch" role="group" aria-label="Twin timeline view">
        {TWIN_GROUPS.map((item) => (
          <button key={item.id} type="button" aria-pressed={group === item.id} className={group === item.id ? "is-active" : ""} onClick={() => setGroup(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      {loading ? <p className="twin-session-state" role="status"><LoaderCircle className="spin" size={14} />Loading retained twin timeline</p> : null}
      {error ? (
        <div className="twin-session-error" role="alert"><span>{error}</span><button type="button" onClick={refresh}><RefreshCw size={13} />Retry</button></div>
      ) : null}
      {!loading && !error && !timeline?.samples.length ? <p className="twin-session-state">No twin samples retained. Missing channels are not inferred.</p> : null}
      {!loading && !error && timeline?.samples.length ? (
        <>
          {group === "PATH" ? <TwinPathOverlay samples={visibleSamples} observedLabel={twinSourceLabel(twin.observedSourceClass)} /> : null}
          {group === "SENSORS" ? <TwinChannelGrid samples={visibleSamples} channels={["imu.acceleration", "imu.angular_velocity", "attitude.euler", "battery.voltage", "battery.current", "battery.state", "estimator.health", "flow.state", "range.state"]} /> : null}
          {group === "MOTORS" ? <TwinChannelGrid samples={visibleSamples} channels={["motor.m1.pwm", "motor.m2.pwm", "motor.m3.pwm", "motor.m4.pwm", "motor.m1.thrust", "motor.m2.thrust", "motor.m3.thrust", "motor.m4.thrust", "motor.m1.state", "motor.m2.state", "motor.m3.state", "motor.m4.state"]} /> : null}
          {group === "RESIDUALS" ? (
            timeline.residuals.length ? <div className="twin-residual-list">{timeline.residuals.filter((item) => cursorSourceS === undefined || item.sourceTimestampS <= cursorSourceS).slice(-12).map((item) => <DataRow key={item.residualSha256} label={item.channelId} value={formatTwinValue(item.value, item.unit, item.availability)} />)}</div> : <p className="twin-session-state">No source-aligned residuals are available.</p>
          ) : null}
          {group === "EVENTS" ? <TwinChannelGrid samples={visibleSamples} channels={["perception.world_revision", "command.identity", "plan.identity", "replan.identity", "safety.state"]} /> : null}
          <label className="twin-time-cursor">
            <span>Source-time cursor <strong>{cursorSourceS?.toFixed(3) ?? "—"} s</strong></span>
            <input type="range" min="0" max="100" value={cursor} onChange={(event) => setCursor(Number(event.target.value))} aria-label="Twin source-time cursor" />
          </label>
          <small className="twin-review-hash">Immutable review · {timeline.timelineSha256}</small>
        </>
      ) : null}
    </section>
  );
}

export function twinSceneOverlayFromSamples(
  samples: TwinTimelineSampleView[],
  twin: TwinSessionView,
): TwinSceneOverlay | undefined {
  const positions = samples.filter(
    (sample) => sample.channelId === "pose.position"
      && sample.availability === "AVAILABLE"
      && isVec3(sample.value),
  );
  const observedPath = positions
    .filter((sample) => sample.side === "OBSERVED")
    .map((sample) => sample.value as Vec3);
  const predictedPath = positions
    .filter((sample) => sample.side === "PREDICTED")
    .map((sample) => sample.value as Vec3);
  if (!observedPath.length && !predictedPath.length) return undefined;
  return {
    observedPath,
    predictedPath,
    observedLabel: twinSourceLabel(twin.observedSourceClass),
    predictedLabel: twinSourceLabel(twin.simulatedSourceClass),
    sourceTimestampS: positions.at(-1)?.sourceTimestampS,
  };
}

function TwinPathOverlay({ samples, observedLabel }: { samples: TwinTimelineSampleView[]; observedLabel: string }) {
  const pathSamples = samples.filter((sample) => sample.channelId === "pose.position" && isVec3(sample.value));
  const observed = pathSamples.filter((sample) => sample.side === "OBSERVED").map((sample) => sample.value as Vec3);
  const predicted = pathSamples.filter((sample) => sample.side === "PREDICTED").map((sample) => sample.value as Vec3);
  const all = [...observed, ...predicted];
  if (!all.length) return <p className="twin-session-state">Observed and predicted paths are unavailable.</p>;
  const xs = all.map((point) => point.x);
  const ys = all.map((point) => point.y);
  const minimumX = Math.min(...xs);
  const maximumX = Math.max(...xs);
  const minimumY = Math.min(...ys);
  const maximumY = Math.max(...ys);
  const points = (values: Vec3[]) => values.map((point) => `${12 + ((point.x - minimumX) / Math.max(maximumX - minimumX, .001)) * 216},${128 - ((point.y - minimumY) / Math.max(maximumY - minimumY, .001)) * 112}`).join(" ");
  return (
    <figure className="twin-path-overlay">
      <svg viewBox="0 0 240 140" role="img" aria-label="Observed and predicted world path overlay">
        <polyline className="twin-path-predicted" points={points(predicted)} />
        <polyline className="twin-path-observed" points={points(observed)} />
      </svg>
      <figcaption><span><i className="observed" />{observedLabel}</span><span><i className="predicted" />Predicted model</span></figcaption>
    </figure>
  );
}

function TwinChannelGrid({ samples, channels }: { samples: TwinTimelineSampleView[]; channels: string[] }) {
  return (
    <div className="twin-channel-grid">
      {channels.map((channel) => {
        const latest = samples.filter((sample) => sample.channelId === channel).at(-1);
        return <DataRow key={channel} label={channel} value={latest ? formatTwinValue(latest.value, latest.unit, latest.availability) : "Unavailable"} />;
      })}
    </div>
  );
}

function isVec3(value: TwinTimelineSampleView["value"]): value is Vec3 {
  return Boolean(value && typeof value === "object" && "x" in value && "y" in value && "z" in value);
}

function formatTwinValue(value: TwinTimelineSampleView["value"], unit: string, availability: string): string {
  if (availability !== "AVAILABLE" || value === undefined) return availability.toLowerCase();
  if (isVec3(value)) return `${value.x.toFixed(3)}, ${value.y.toFixed(3)}, ${value.z.toFixed(3)} ${unit}`;
  return `${typeof value === "number" ? value.toFixed(3) : String(value)} ${unit}`.trim();
}

function RunFileMission({
  mission,
  deleting = false,
  onDelete,
}: {
  mission: RunFileMissionView;
  deleting?: boolean;
  onDelete: (mission: RunFileMissionView) => void;
}) {
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
      <button
        type="button"
        className="run-file-delete"
        disabled={mission.status === "INCOMPLETE" || deleting}
        onClick={() => onDelete(mission)}
        aria-label={`Delete ${mission.missionName} run files`}
        title={mission.status === "INCOMPLETE" ? "A recording cannot be deleted" : "Delete mission files and folder"}
      >
        {deleting ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}
      </button>
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

function TelemetryCategoryCurrent({
  group,
  vehicle,
  batteryTone,
  meanMotorPwm,
  positionDisplayRange,
}: {
  group: TrendGroup;
  vehicle: VehicleView;
  batteryTone: string;
  meanMotorPwm?: number;
  positionDisplayRange: number;
}) {
  const data = vehicle.telemetry!;
  if (group === "position") {
    return data.estimate
      ? <VectorBars label="Position" vector={data.estimate} unit="m" displayRange={positionDisplayRange} showLabel={false} />
      : <TelemetryUnavailable label="Position" />;
  }
  if (group === "velocity") {
    return data.velocity
      ? <VectorBars label="Velocity" vector={data.velocity} unit="m/s" displayRange={1.5} showLabel={false} />
      : <TelemetryUnavailable label="Velocity" />;
  }
  if (group === "acceleration") {
    return data.imu
      ? <VectorBars label="Acceleration" vector={data.imu.acceleration} unit="m/s²" displayRange={10} showLabel={false} />
      : <TelemetryUnavailable label="Acceleration" />;
  }
  if (group === "power") {
    return (
      <div className="power-instruments">
        <ArcGauge label="Battery" value={data.batteryPercent} maximum={100} decimals={0} unit="%" tone={batteryTone} />
        <div className="power-current">
          <small>Current</small>
          <span><strong>{formatValue(data.batteryCurrent, 2)}</strong><i>A</i></span>
        </div>
      </div>
    );
  }
  if (group === "attitude") {
    return data.attitude ? <AttitudeAxes attitude={data.attitude} /> : <TelemetryUnavailable label="Attitude" />;
  }
  if (group === "angularVelocity") {
    return data.imu
      ? <VectorBars label="Gyro" vector={data.imu.angularVelocity} unit="rad/s" displayRange={5} showLabel={false} />
      : <TelemetryUnavailable label="Gyro" />;
  }
  if (!data.motors) return <TelemetryUnavailable label="Motor" />;
  return (
    <div className="motor-lines" role="group" aria-label="Current motor output">
      {data.motors.readings.map((motor) => {
        const output = motor.appliedPwmPercent ?? motor.commandPercent;
        return (
          <div key={motor.id}>
            <span>{motor.id}</span>
            <i aria-hidden="true"><b style={{ width: `${clamp(output, 0, 100)}%` }} /></i>
            <strong>{output.toFixed(2)}% · {motor.thrustN.toFixed(4)} N · {motor.currentA.toFixed(3)} A</strong>
            <small>{meanMotorPwm === undefined ? "" : `${output - meanMotorPwm >= 0 ? "+" : ""}${(output - meanMotorPwm).toFixed(3)} pp`}{motor.saturated ? " · SATURATED" : ""}</small>
          </div>
        );
      })}
    </div>
  );
}

function TelemetryUnavailable({ label }: { label: string }) {
  return <p className="telemetry-unavailable">{label} telemetry unavailable</p>;
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

function AttitudeAxes({ attitude }: { attitude: { rollRad: number; pitchRad: number; yawRad: number } }) {
  return (
    <div className="attitude-axes" role="group" aria-label="Attitude around all axes">
      <AxisMeter label="Roll" axis="x" value={toDegrees(attitude.rollRad)} displayRange={45} unit="°" decimals={1} />
      <AxisMeter label="Pitch" axis="y" value={toDegrees(attitude.pitchRad)} displayRange={45} unit="°" decimals={1} />
      <AxisMeter label="Yaw" axis="z" value={toDegrees(attitude.yawRad)} displayRange={180} unit="°" decimals={1} />
    </div>
  );
}

function VectorBars({ label, vector, unit, displayRange, showLabel = true }: { label: string; vector: Vec3; unit: string; displayRange: number; showLabel?: boolean }) {
  return (
    <div className="vector-bars" role="group" aria-label={`${label} on X Y and Z axes`}>
      {showLabel ? <h4>{label}</h4> : null}
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

function MissionOverview({ samples }: { samples: TelemetrySample[] }) {
  const metrics = useMemo(() => MISSION_OVERVIEW_METRICS.map((item) => item.metric), []);
  const series = useMemo(() => buildTrendSeries(samples, metrics), [metrics, samples]);

  return (
    <section className="mission-overview" aria-label="Mission overview telemetry">
      <header>
        <h2>Mission overview</h2>
        <small>Last 60 seconds</small>
      </header>
      <div className="mission-overview-grid">
        {MISSION_OVERVIEW_METRICS.map((item, index) => {
          const trend = series[index];
          const latest = trend?.values.at(-1)?.value;
          const definition = trend?.definition ?? TREND_DEFINITIONS[item.metric];
          return (
            <article key={item.metric} className="mission-overview-card" aria-label={`${item.label} mission history`}>
              <header>
                <span>{item.label}</span>
                <strong>{latest === undefined ? "—" : latest.toFixed(definition.decimals)} {definition.unit}</strong>
              </header>
              <TrendPlot series={trend ? [trend] : []} variant="overview" showLegend={false} />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function TrendChart({ samples, metrics, group }: { samples: TelemetrySample[]; metrics: readonly TrendMetric[]; group: TrendGroup }) {
  const startupCutoff = useMemo(
    () => group === "motors" ? motorStartupCutoffTime(samples) : undefined,
    [group, samples],
  );
  const series = useMemo(() => buildTrendSeries(samples, metrics, startupCutoff), [metrics, samples, startupCutoff]);
  const unitGroups = [...new Set(series.map((item) => item.definition.unit))];
  const groupLabel = TREND_GROUPS.find((item) => item.id === group)?.label ?? group;

  return (
    <div className={`trend-chart trend-group-${group}`}>
      {startupCutoff !== undefined ? <p className="trend-filter-note">Startup trimmed · first {MOTOR_STARTUP_TRIM_SECONDS} s</p> : null}
      <section className="trend-chart-block" aria-label={`${groupLabel} combined history`}>
        <header><h3>Combined</h3></header>
        {unitGroups.map((unit) => <TrendPlot key={unit} series={series.filter((item) => item.definition.unit === unit)} />)}
      </section>
      <section className="trend-chart-block" aria-label={`${groupLabel} individual history`}>
        <header><h3>Individual</h3></header>
        <div className="trend-individual-grid">
          {series.map((item) => <TrendPlot key={item.metric} series={[item]} variant="individual" />)}
        </div>
      </section>
    </div>
  );
}

type TrendSeries = {
  metric: TrendMetric;
  index: number;
  definition: (typeof TREND_DEFINITIONS)[TrendMetric];
  values: { t: number; value: number }[];
};

function buildTrendSeries(
  samples: TelemetrySample[],
  metrics: readonly TrendMetric[],
  minimumTime?: number,
): TrendSeries[] {
  const latestTime = samples.at(-1)?.t;
  const recentSamples = latestTime === undefined
    ? []
    : samples.filter((sample) => latestTime - sample.t <= 60 && (minimumTime === undefined || sample.t >= minimumTime));
  return metrics.map((metric, index) => ({
    metric,
    index,
    definition: TREND_DEFINITIONS[metric],
    values: recentSamples
      .filter((sample) => sample[metric] !== undefined)
      .map((sample) => ({ t: sample.t, value: sample[metric] as number })),
  }));
}

export function motorStartupCutoffTime(samples: TelemetrySample[]): number | undefined {
  const latestTime = samples.at(-1)?.t;
  if (latestTime === undefined) return undefined;
  let sawInactiveMotors = false;
  for (const sample of samples) {
    const outputs = [sample.motorM1, sample.motorM2, sample.motorM3, sample.motorM4]
      .filter((value): value is number => value !== undefined);
    if (!outputs.length) continue;
    if (!outputs.some((value) => value > MOTOR_ACTIVE_THRESHOLD_PERCENT)) {
      sawInactiveMotors = true;
      continue;
    }
    if (!sawInactiveMotors) return undefined;
    return latestTime - sample.t >= MOTOR_STARTUP_TRIM_SECONDS
      ? sample.t + MOTOR_STARTUP_TRIM_SECONDS
      : undefined;
  }
  return undefined;
}

function TrendPlot({
  series,
  variant = "combined",
  showLegend = true,
}: {
  series: TrendSeries[];
  variant?: "combined" | "individual" | "overview";
  showLegend?: boolean;
}) {
  const drawable = series.filter((item) => item.values.length >= 2);
  const allValues = drawable.flatMap((item) => item.values.map((point) => point.value));
  const firstTimes = drawable.map((item) => item.values[0].t);
  const lastTimes = drawable.map((item) => item.values.at(-1)!.t);
  const start = firstTimes.length ? Math.min(...firstTimes) : 0;
  const end = lastTimes.length ? Math.max(...lastTimes) : start;
  const duration = end - start || 1;
  const minimum = allValues.length ? Math.min(...allValues) : 0;
  const maximum = allValues.length ? Math.max(...allValues) : 0;
  const range = maximum - minimum || 1;
  const unit = series[0]?.definition.unit ?? "";
  const summary = drawable.map((item) => {
    const values = item.values.map((point) => point.value);
    return `${item.definition.label} ${Math.min(...values).toFixed(item.definition.decimals)} to ${Math.max(...values).toFixed(item.definition.decimals)} ${unit}`;
  }).join("; ");

  return (
    <section className={`trend-plot trend-plot-${variant} ${drawable.length ? "" : "is-collecting"}`}>
      {showLegend ? <div className="trend-legend" aria-label={`Current ${unit} values`}>
        {series.map((item) => {
          const latest = item.values.at(-1)?.value;
          return (
            <span key={item.metric}>
              <i className={`trend-series-${item.index}`} aria-hidden="true" />
              <small>{item.definition.switchLabel}</small>
              <strong>{latest === undefined ? "—" : latest.toFixed(item.definition.decimals)} {unit}</strong>
            </span>
          );
        })}
      </div> : null}
      {drawable.length ? (
        <>
          <svg viewBox="0 0 320 104" role="img" aria-label={`${summary} over ${Math.min(60, Math.round(duration))} seconds`}>
            {minimum <= 0 && maximum >= 0 ? <line className="trend-zero" x1="3" x2="317" y1={96 - ((0 - minimum) / range) * 80} y2={96 - ((0 - minimum) / range) * 80} /> : null}
            {drawable.map((item) => {
              const points = item.values.map((point) => {
                const x = 3 + ((point.t - start) / duration) * 314;
                const y = 96 - ((point.value - minimum) / range) * 80;
                return `${x.toFixed(1)},${y.toFixed(1)}`;
              }).join(" ");
              return <polyline key={item.metric} className={`trend-line trend-series-${item.index}`} points={points} fill="none" vectorEffect="non-scaling-stroke" />;
            })}
          </svg>
          <div className="trend-range"><span>{minimum.toFixed(series[0].definition.decimals)} {unit}</span><span>{maximum.toFixed(series[0].definition.decimals)} {unit}</span></div>
        </>
      ) : <small className="trend-plot-empty">Collecting {unit} history</small>}
    </section>
  );
}

const TREND_DEFINITIONS: Record<TrendMetric, { label: string; switchLabel: string; unit: string; decimals: number }> = {
  positionX: { label: "Position X", switchLabel: "X", unit: "m", decimals: 2 },
  positionY: { label: "Position Y", switchLabel: "Y", unit: "m", decimals: 2 },
  positionZ: { label: "Position Z", switchLabel: "Z", unit: "m", decimals: 2 },
  velocityX: { label: "Velocity X", switchLabel: "X", unit: "m/s", decimals: 2 },
  velocityY: { label: "Velocity Y", switchLabel: "Y", unit: "m/s", decimals: 2 },
  velocityZ: { label: "Velocity Z", switchLabel: "Z", unit: "m/s", decimals: 2 },
  speed: { label: "Speed", switchLabel: "Speed", unit: "m/s", decimals: 2 },
  nearest: { label: "Nearest range", switchLabel: "Nearest", unit: "m", decimals: 2 },
  battery: { label: "Battery", switchLabel: "Battery", unit: "%", decimals: 0 },
  current: { label: "Battery current", switchLabel: "Current", unit: "A", decimals: 2 },
  roll: { label: "Roll", switchLabel: "Roll", unit: "°", decimals: 1 },
  pitch: { label: "Pitch", switchLabel: "Pitch", unit: "°", decimals: 1 },
  yaw: { label: "Yaw", switchLabel: "Yaw", unit: "°", decimals: 1 },
  accelerationX: { label: "Acceleration X", switchLabel: "X", unit: "m/s²", decimals: 2 },
  accelerationY: { label: "Acceleration Y", switchLabel: "Y", unit: "m/s²", decimals: 2 },
  accelerationZ: { label: "Acceleration Z", switchLabel: "Z", unit: "m/s²", decimals: 2 },
  angularVelocityX: { label: "Angular velocity X", switchLabel: "X", unit: "rad/s", decimals: 2 },
  angularVelocityY: { label: "Angular velocity Y", switchLabel: "Y", unit: "rad/s", decimals: 2 },
  angularVelocityZ: { label: "Angular velocity Z", switchLabel: "Z", unit: "rad/s", decimals: 2 },
  motorM1: { label: "Motor M1 output", switchLabel: "M1", unit: "%", decimals: 0 },
  motorM2: { label: "Motor M2 output", switchLabel: "M2", unit: "%", decimals: 0 },
  motorM3: { label: "Motor M3 output", switchLabel: "M3", unit: "%", decimals: 0 },
  motorM4: { label: "Motor M4 output", switchLabel: "M4", unit: "%", decimals: 0 },
};

export function telemetrySample(vehicle?: VehicleView): TelemetrySample | undefined {
  const data = vehicle?.telemetry;
  if (!data) return undefined;
  const time = data.provenance.replayTimeS
    ?? data.provenance.simulationTimeS
    ?? data.provenance.sourceTimeS
    ?? data.provenance.receiveTimeS
    ?? Date.now() / 1_000;
  const motors = new Map(data.motors?.readings.map((reading) => [reading.id, reading.appliedPwmPercent ?? reading.commandPercent]));
  const nearest = data.ranges
    .filter((range) => range.distanceM !== null)
    .sort((left, right) => left.distanceM! - right.distanceM!)[0]?.distanceM ?? undefined;
  return {
    t: time,
    positionX: data.estimate?.x,
    positionY: data.estimate?.y,
    positionZ: data.estimate?.z,
    velocityX: data.velocity?.x,
    velocityY: data.velocity?.y,
    velocityZ: data.velocity?.z,
    speed: data.velocity ? vectorMagnitude(data.velocity) : undefined,
    nearest,
    battery: data.batteryPercent,
    current: data.batteryCurrent,
    localization: data.localizationPercent,
    roll: data.attitude ? toDegrees(data.attitude.rollRad) : undefined,
    pitch: data.attitude ? toDegrees(data.attitude.pitchRad) : undefined,
    yaw: data.attitude || data.yawRad !== undefined
      ? toDegrees(data.attitude?.yawRad ?? data.yawRad!)
      : undefined,
    accelerationX: data.imu?.acceleration.x,
    accelerationY: data.imu?.acceleration.y,
    accelerationZ: data.imu?.acceleration.z,
    angularVelocityX: data.imu?.angularVelocity.x,
    angularVelocityY: data.imu?.angularVelocity.y,
    angularVelocityZ: data.imu?.angularVelocity.z,
    motorM1: motors.get("M1"),
    motorM2: motors.get("M2"),
    motorM3: motors.get("M3"),
    motorM4: motors.get("M4"),
  };
}

function DataRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="data-row"><span>{label}</span><strong className={mono ? "is-mono" : ""}>{value}</strong></div>;
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
