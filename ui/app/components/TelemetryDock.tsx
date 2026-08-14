"use client";

import { ChevronDown, ChevronUp, Download, FileSpreadsheet, LoaderCircle, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { DashboardModel, RangeRay, RunFileMissionView, TwinSessionView, TwinTimelineSampleView, TwinTimelineView, Vec3, VehicleView } from "../lib/models";
import { formatClockContext, type TwinSceneOverlay } from "./RoomScene";

export type TelemetrySample = {
  t: number;
  altitude?: number;
  speed?: number;
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
type TrendGroup = "flight" | "attitude" | "acceleration" | "angularVelocity" | "motors";

const TREND_GROUPS: readonly {
  id: TrendGroup;
  label: string;
  title: string;
  metrics: readonly TrendMetric[];
}[] = [
  { id: "flight", label: "Flight", title: "Flight essentials", metrics: ["altitude", "speed", "battery", "current"] },
  { id: "attitude", label: "Attitude", title: "Roll, pitch, and yaw", metrics: ["roll", "pitch", "yaw"] },
  { id: "acceleration", label: "Accel", title: "IMU acceleration", metrics: ["accelerationX", "accelerationY", "accelerationZ"] },
  { id: "angularVelocity", label: "Gyro", title: "IMU angular velocity", metrics: ["angularVelocityX", "angularVelocityY", "angularVelocityZ"] },
  { id: "motors", label: "Motors", title: "Individual motor output", metrics: ["motorM1", "motorM2", "motorM3", "motorM4"] },
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
  twin,
  samples,
  expanded,
  onToggle,
  onLoadTwinTimeline,
  onTwinSceneOverlay,
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
  const [trendMetric, setTrendMetric] = useState<TrendMetric>("altitude");
  const [systemsOpen, setSystemsOpen] = useState(true);
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const data = vehicle?.telemetry;
  if (!vehicle || !data) return null;
  const trendGroup = TREND_GROUPS.find((group) => group.metrics.includes(trendMetric)) ?? TREND_GROUPS[0];

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
  const meanMotorPwm = data.motors
    ? data.motors.readings.reduce(
        (total, motor) => total + (motor.appliedPwmPercent ?? motor.commandPercent),
        0,
      ) / data.motors.readings.length
    : undefined;

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
          <section className="trend-controls" aria-label="Telemetry history controls">
            <div className="trend-groups" role="group" aria-label="Trend category">
              {TREND_GROUPS.map((group) => (
                <button
                  key={group.id}
                  type="button"
                  className={group.id === trendGroup.id ? "is-active" : ""}
                  aria-pressed={group.id === trendGroup.id}
                  title={group.title}
                  onClick={() => setTrendMetric(group.metrics[0])}
                >
                  {group.label}
                </button>
              ))}
            </div>
            <div className="trend-switch" role="group" aria-label={`${trendGroup.title} trend metric`} data-count={trendGroup.metrics.length}>
              {trendGroup.metrics.map((metric) => (
                <button
                  key={metric}
                  type="button"
                  className={metric === trendMetric ? "is-active" : ""}
                  aria-pressed={metric === trendMetric}
                  onClick={() => setTrendMetric(metric)}
                >
                  {TREND_DEFINITIONS[metric].switchLabel}
                </button>
              ))}
            </div>
          </section>
          <TrendChart samples={samples} metric={trendMetric} source={vehicle.observationClass} />

          {twin && onLoadTwinTimeline ? (
            <details
              className="detail-disclosure twin-evidence-disclosure"
              open={evidenceOpen}
              onToggle={(event) => setEvidenceOpen(event.currentTarget.open)}
            >
              <summary>Evidence <ChevronDown size={15} /></summary>
              <div className="disclosure-body">
                <TwinSessionPanel twin={twin} onLoad={onLoadTwinTimeline} onSceneOverlay={onTwinSceneOverlay} />
              </div>
            </details>
          ) : null}

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
                          <i aria-hidden="true"><b style={{ width: `${clamp(motor.appliedPwmPercent ?? motor.commandPercent, 0, 100)}%` }} /></i>
                          <strong>{(motor.appliedPwmPercent ?? motor.commandPercent).toFixed(2)}% · {motor.thrustN.toFixed(4)} N · {motor.currentA.toFixed(3)} A</strong>
                          <small>{meanMotorPwm === undefined ? "" : `${(motor.appliedPwmPercent ?? motor.commandPercent) - meanMotorPwm >= 0 ? "+" : ""}${((motor.appliedPwmPercent ?? motor.commandPercent) - meanMotorPwm).toFixed(3)} pp`}{motor.saturated ? " · SATURATED" : ""}</small>
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

const TREND_DEFINITIONS: Record<TrendMetric, { label: string; switchLabel: string; unit: string; decimals: number }> = {
  altitude: { label: "World Z", switchLabel: "Z", unit: "m", decimals: 2 },
  speed: { label: "Speed", switchLabel: "Speed", unit: "m/s", decimals: 2 },
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
  const motors = new Map(data.motors?.readings.map((reading) => [reading.id, reading.commandPercent]));
  return {
    t: time,
    altitude: data.estimate?.z,
    speed: data.velocity ? vectorMagnitude(data.velocity) : undefined,
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
