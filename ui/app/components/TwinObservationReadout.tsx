"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { PhysicalTwinLiveFrameView, PhysicalTwinSourceStatusView, PhysicalTwinStatusView, Vec3 } from "../lib/models";

type TwinView = "position" | "attitude" | "motors" | "ranges" | "power" | "connection";
type TwinTelemetrySample = {
  t: number;
  positionX?: number;
  positionY?: number;
  positionZ?: number;
  batteryVoltage?: number;
  tilt?: number;
  nearestRange?: number;
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
  rangeFront?: number;
  rangeBack?: number;
  rangeLeft?: number;
  rangeRight?: number;
  rangeUp?: number;
  rangeDown?: number;
  packetLossPercent?: number;
  retryQualityPercent?: number;
  uplinkRateHz?: number;
  downlinkRateHz?: number;
};
type TwinTrendMetric = Exclude<keyof TwinTelemetrySample, "t">;
type TwinTrendDefinition = { label: string; switchLabel: string; unit: string; decimals: number };
type TwinTrendSeries = {
  metric: TwinTrendMetric;
  index: number;
  definition: TwinTrendDefinition;
  values: Array<{ t: number; value: number }>;
};
type TwinTelemetryHistory = { identity?: string; samples: TwinTelemetrySample[] };
const CLOSE_RANGE_DISPLAY_M = 1;
const FAR_RANGE_INDICATOR_M = 2;
const TWIN_HISTORY_WINDOW_SECONDS = 60;
const TWIN_HISTORY_SAMPLE_INTERVAL_SECONDS = .1;
const TWIN_HISTORY_SAMPLE_LIMIT = 720;

const TWIN_VIEWS: ReadonlyArray<{ id: TwinView; label: string }> = [
  { id: "position", label: "Position" },
  { id: "attitude", label: "Attitude" },
  { id: "motors", label: "Motors" },
  { id: "ranges", label: "Ranges" },
  { id: "power", label: "Power" },
  { id: "connection", label: "Link" },
];

const TWIN_TREND_DEFINITIONS: Record<TwinTrendMetric, TwinTrendDefinition> = {
  positionX: { label: "Position X", switchLabel: "X", unit: "m", decimals: 2 },
  positionY: { label: "Position Y", switchLabel: "Y", unit: "m", decimals: 2 },
  positionZ: { label: "Position Z", switchLabel: "Z", unit: "m", decimals: 2 },
  batteryVoltage: { label: "Battery voltage", switchLabel: "Voltage", unit: "V", decimals: 3 },
  tilt: { label: "Tilt", switchLabel: "Tilt", unit: "°", decimals: 1 },
  nearestRange: { label: "Nearest range", switchLabel: "Nearest", unit: "m", decimals: 3 },
  roll: { label: "Roll", switchLabel: "Roll", unit: "°", decimals: 1 },
  pitch: { label: "Pitch", switchLabel: "Pitch", unit: "°", decimals: 1 },
  yaw: { label: "Yaw", switchLabel: "Yaw", unit: "°", decimals: 1 },
  accelerationX: { label: "Acceleration X", switchLabel: "X", unit: "m/s²", decimals: 2 },
  accelerationY: { label: "Acceleration Y", switchLabel: "Y", unit: "m/s²", decimals: 2 },
  accelerationZ: { label: "Acceleration Z", switchLabel: "Z", unit: "m/s²", decimals: 2 },
  angularVelocityX: { label: "Angular velocity X", switchLabel: "X", unit: "rad/s", decimals: 3 },
  angularVelocityY: { label: "Angular velocity Y", switchLabel: "Y", unit: "rad/s", decimals: 3 },
  angularVelocityZ: { label: "Angular velocity Z", switchLabel: "Z", unit: "rad/s", decimals: 3 },
  motorM1: { label: "Motor M1 output", switchLabel: "M1", unit: "%", decimals: 1 },
  motorM2: { label: "Motor M2 output", switchLabel: "M2", unit: "%", decimals: 1 },
  motorM3: { label: "Motor M3 output", switchLabel: "M3", unit: "%", decimals: 1 },
  motorM4: { label: "Motor M4 output", switchLabel: "M4", unit: "%", decimals: 1 },
  rangeFront: { label: "Front range", switchLabel: "Front", unit: "m", decimals: 3 },
  rangeBack: { label: "Back range", switchLabel: "Back", unit: "m", decimals: 3 },
  rangeLeft: { label: "Left range", switchLabel: "Left", unit: "m", decimals: 3 },
  rangeRight: { label: "Right range", switchLabel: "Right", unit: "m", decimals: 3 },
  rangeUp: { label: "Up range", switchLabel: "Up", unit: "m", decimals: 3 },
  rangeDown: { label: "Down range", switchLabel: "Down", unit: "m", decimals: 3 },
  packetLossPercent: { label: "Packet loss", switchLabel: "Loss", unit: "%", decimals: 2 },
  retryQualityPercent: { label: "Retry quality", switchLabel: "Retry", unit: "%", decimals: 2 },
  uplinkRateHz: { label: "Uplink rate", switchLabel: "Up", unit: "Hz", decimals: 1 },
  downlinkRateHz: { label: "Downlink rate", switchLabel: "Down", unit: "Hz", decimals: 1 },
};

const POSITION_TRENDS = ["positionX", "positionY", "positionZ"] as const;
const ATTITUDE_TRENDS = ["roll", "pitch", "yaw"] as const;
const ACCELERATION_TRENDS = ["accelerationX", "accelerationY", "accelerationZ"] as const;
const GYRO_TRENDS = ["angularVelocityX", "angularVelocityY", "angularVelocityZ"] as const;
const MOTOR_TRENDS = ["motorM1", "motorM2", "motorM3", "motorM4"] as const;
const RANGE_TRENDS = ["rangeFront", "rangeBack", "rangeLeft", "rangeRight", "rangeUp", "rangeDown"] as const;
const POWER_TRENDS = ["batteryVoltage"] as const;
const LINK_QUALITY_TRENDS = ["packetLossPercent", "retryQualityPercent"] as const;
const LINK_RATE_TRENDS = ["uplinkRateHz", "downlinkRateHz"] as const;

export function TwinObservationReadout({
  status,
  expanded,
  onToggle,
  subscribe,
  onLiveFrame,
  position,
}: {
  status?: PhysicalTwinStatusView;
  expanded: boolean;
  onToggle: () => void;
  subscribe?: (
    onFrame: (frame: PhysicalTwinLiveFrameView) => void,
    signal: AbortSignal,
  ) => Promise<void>;
  onLiveFrame?: (frame: PhysicalTwinLiveFrameView) => void;
  position?: Vec3;
}) {
  const [view, setView] = useState<TwinView>("position");
  const [receivedFrame, setReceivedFrame] = useState<{
    sessionId?: string;
    frame: PhysicalTwinLiveFrameView;
  }>();
  const [telemetryHistory, setTelemetryHistory] = useState<TwinTelemetryHistory>({ samples: [] });
  useEffect(() => {
    if (!subscribe || (status?.state !== "PAIRED" && status?.state !== "SUSPENDED")) return;
    const controller = new AbortController();
    let retryTimer: number | undefined;
    let terminal = false;
    const connect = async () => {
      try {
        await subscribe((frame) => {
          terminal = frame.state !== "PAIRED" && frame.state !== "SUSPENDED";
          const observed = frame.observed;
          if (observed) {
            setTelemetryHistory((current) => appendTwinTelemetryHistory(
              current,
              twinHistoryIdentity(status.sessionId, frame.telemetryOwner ?? status.telemetryOwner, observed),
              observed,
            ));
          }
          setReceivedFrame({ sessionId: status.sessionId, frame });
          onLiveFrame?.(frame);
        }, controller.signal);
      } catch (error) {
        if (controller.signal.aborted) return;
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          // The lifecycle poll remains the quiet fallback while this compact
          // latest-only presentation stream reconnects.
        }
      }
      if (!controller.signal.aborted && !terminal) {
        retryTimer = window.setTimeout(connect, 500);
      }
    };
    void connect();
    return () => {
      controller.abort();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [onLiveFrame, status?.sessionId, status?.state, status?.telemetryOwner, subscribe]);
  useEffect(() => {
    if (!status?.observed) return;
    // Lifecycle polling is also a truthful, low-rate history source when the
    // presentation stream is reconnecting.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTelemetryHistory((current) => appendTwinTelemetryHistory(
      current,
      twinHistoryIdentity(status.sessionId, status.telemetryOwner, status.observed!),
      status.observed!,
    ));
  }, [status?.observed, status?.sessionId, status?.telemetryOwner]);
  const receivedSource = receivedFrame?.frame.observed;
  const polledSource = status?.observed;
  const polledSourceRejectsCachedCurrent = Boolean(
    polledSource
    && polledSource.freshness !== "CURRENT"
    && receivedSource?.freshness === "CURRENT"
    && (
      polledSource.rawSourceTimestampS === undefined
      || receivedSource.rawSourceTimestampS === undefined
      || receivedSource.rawSourceTimestampS <= polledSource.rawSourceTimestampS
    )
  );
  const liveFrame = receivedFrame
    && (status?.state === "PAIRED" || status?.state === "SUSPENDED")
    && receivedFrame.frame.state === status.state
    && receivedFrame.sessionId === status.sessionId
    && !polledSourceRejectsCachedCurrent
    ? receivedFrame.frame
    : undefined;
  const displayedStatus = useMemo<PhysicalTwinStatusView | undefined>(() => {
    if (!status || !liveFrame) return status;
    return {
      ...status,
      state: liveFrame.state,
      vehicleLabel: liveFrame.vehicleLabel ?? status.vehicleLabel,
      sampleCount: liveFrame.channelRecordCount,
      pairedCycleCount: liveFrame.pairedCycleCount,
      observed: liveFrame.observed,
      telemetryOwner: liveFrame.telemetryOwner,
      operationSampleCount: liveFrame.operationSampleCount,
    };
  }, [liveFrame, status]);
  const measured = displayedStatus?.observed;
  const operationTelemetry = displayedStatus?.telemetryOwner === "PHYSICAL_OPERATION";
  const activeView = TWIN_VIEWS.find((item) => item.id === view) ?? TWIN_VIEWS[0];
  const attitudeSummary = compactAttitude(measured);
  const rangeSummary = nearestRange(measured);

  return (
    <section className={`twin-observation-readout ${expanded ? "is-expanded" : ""}`} aria-label="Digital twin sensor diagnostics">
      <button className="twin-observation-summary" type="button" aria-label={expanded ? "Collapse drone telemetry" : "Expand drone telemetry"} aria-expanded={expanded} onClick={onToggle}>
        <span><small>BATTERY</small><strong>{formatBattery(measured)}</strong><em>{batteryDetail(measured)}</em></span>
        <span><small>ROLL · PITCH</small><strong>{attitudeSummary.value}</strong><em>{attitudeSummary.detail}</em></span>
        <span><small>NEAREST RANGE</small><strong>{rangeSummary.value}</strong><em>{rangeSummary.detail}</em></span>
        {expanded ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
      </button>
      {expanded ? (
        <div className="twin-observation-detail">
          <TwinMissionOverview samples={telemetryHistory.samples} operationTelemetry={operationTelemetry} />
          <section className="telemetry-category-nav twin-category-nav" role="group" aria-label="Twin telemetry category">
            {TWIN_VIEWS.map((item) => (
              <button key={item.id} type="button" className={view === item.id ? "is-active" : ""} aria-pressed={view === item.id} onClick={() => setView(item.id)}>{item.label}</button>
            ))}
          </section>
          <section className="telemetry-category-panel twin-category-panel" aria-label={`${activeView.label} telemetry`}>
            {view === "position" ? <TwinPosition source={measured} position={position} samples={telemetryHistory.samples} /> : null}
            {view === "attitude" ? <TwinAttitude source={measured} samples={telemetryHistory.samples} /> : null}
            {view === "motors" ? <TwinMotors source={measured} samples={telemetryHistory.samples} /> : null}
            {view === "ranges" ? <TwinRanges source={measured} samples={telemetryHistory.samples} /> : null}
            {view === "power" ? <TwinPower measured={measured} samples={telemetryHistory.samples} /> : null}
            {view === "connection" ? <TwinConnection status={displayedStatus} measured={measured} samples={telemetryHistory.samples} /> : null}
          </section>
        </div>
      ) : null}
    </section>
  );
}

function TwinMissionOverview({ samples, operationTelemetry }: { samples: TwinTelemetrySample[]; operationTelemetry: boolean }) {
  const cards: ReadonlyArray<{ metric: TwinTrendMetric; label: string }> = [
    ...(samples.some((sample) => sample.positionZ !== undefined) ? [{ metric: "positionZ" as const, label: "Height" }] : []),
    { metric: "batteryVoltage", label: "Battery" },
    { metric: "tilt", label: "Tilt" },
    { metric: "nearestRange", label: "Nearest" },
  ];
  return (
    <section className="twin-mission-overview" aria-label="Mission overview telemetry">
      <header><h2>Mission overview</h2><small>{operationTelemetry ? "Physical link" : "Observed"} · last 60 seconds</small></header>
      <div>
        {cards.map((card) => <TwinMissionHistoryCard key={card.metric} samples={samples} metric={card.metric} label={card.label} />)}
      </div>
    </section>
  );
}

function TwinMissionHistoryCard({ samples, metric, label }: { samples: TwinTelemetrySample[]; metric: TwinTrendMetric; label: string }) {
  const series = useMemo(() => buildTwinTrendSeries(samples, [metric]), [metric, samples]);
  const definition = TWIN_TREND_DEFINITIONS[metric];
  const latest = series[0].values.at(-1)?.value;
  return <article className="twin-mission-history-card" aria-label={`${label} measured history`}>
    <span>{label}</span>
    <strong>{latest === undefined ? "—" : latest.toFixed(definition.decimals)} {definition.unit}</strong>
    <TwinTrendPlot series={series} variant="overview" showLegend={false} />
  </article>;
}

function TwinPosition({ source, position, samples }: { source?: PhysicalTwinSourceStatusView; position?: Vec3; samples: TwinTelemetrySample[] }) {
  const displayed = position ?? (source?.positionAvailability === "AVAILABLE" ? source.position : undefined);
  return <div className="twin-category-stack">
    {displayed ? <TwinVectorMeters label="Position" vector={displayed} unit="m" range={5} decimals={2} /> : <p className="telemetry-unavailable">Position unavailable</p>}
    <TwinHistoryBlock samples={samples} metrics={POSITION_TRENDS} label="Position" />
  </div>;
}

function TwinAttitude({ source, samples }: { source?: PhysicalTwinSourceStatusView; samples: TwinTelemetrySample[] }) {
  return (
    <div className="twin-attitude-stack">
      {source?.attitude ? <TwinAttitudeInstrument attitude={source.attitude} /> : <p className="telemetry-unavailable">Attitude telemetry unavailable</p>}
      <TwinImu source={source} />
      <TwinHistoryBlock samples={samples} metrics={ATTITUDE_TRENDS} label="Orientation" />
      <TwinHistoryBlock samples={samples} metrics={ACCELERATION_TRENDS} label="Acceleration" />
      <TwinHistoryBlock samples={samples} metrics={GYRO_TRENDS} label="Gyro" />
    </div>
  );
}

function TwinAttitudeInstrument({ attitude }: { attitude: NonNullable<PhysicalTwinSourceStatusView["attitude"]> }) {
  const roll = degrees(attitude.rollRad);
  const pitch = degrees(attitude.pitchRad);
  const yaw = degrees(attitude.yawRad);
  return (
    <div className="twin-attitude-instrument" role="group" aria-label={`Attitude: roll ${roll.toFixed(1)} degrees, pitch ${pitch.toFixed(1)} degrees, yaw ${yaw.toFixed(1)} degrees`}>
      <div className="twin-attitude-window" aria-hidden="true"><div className="twin-attitude-horizon" style={{ transform: `translateY(${clamp(pitch / 30, -1, 1) * 24}px) rotate(${roll}deg)` }}><i /><b /></div><span className="twin-attitude-reference" /></div>
      <div className="twin-attitude-values"><AttitudeValue label="Roll" value={roll} /><AttitudeValue label="Pitch" value={pitch} /><AttitudeValue label="Yaw" value={yaw} /></div>
    </div>
  );
}

function AttitudeValue({ label, value }: { label: string; value: number }) {
  return <span><small>{label}</small><strong>{signed(value, 1)}°</strong></span>;
}

function TwinImu({ source }: { source?: PhysicalTwinSourceStatusView }) {
  if (!source?.imu) return <p className="telemetry-unavailable">IMU telemetry unavailable</p>;
  return <div className="twin-vector-grid"><TwinVectorMeters label="Acceleration" vector={source.imu.acceleration} unit="m/s²" range={12} decimals={2} /><TwinVectorMeters label="Gyro" vector={source.imu.angularVelocity} unit="rad/s" range={5} decimals={3} /></div>;
}

function TwinMotors({ source, samples }: { source?: PhysicalTwinSourceStatusView; samples: TwinTelemetrySample[] }) {
  return (
    <div className="twin-category-stack">
      {source?.motorPwmPercent ? <div className="motor-lines twin-motor-lines" role="group" aria-label="Current measured motor output">
        {source.motorPwmPercent.map((output, index) => (
          <div key={index}>
            <span>M{index + 1}</span>
            <i aria-hidden="true"><b style={{ width: `${clamp(output, 0, 100)}%` }} /></i>
            <strong>{output.toFixed(2)}%</strong>
            <small>Measured PWM</small>
          </div>
        ))}
      </div> : <p className="telemetry-unavailable">Motor telemetry unavailable</p>}
      <TwinHistoryBlock samples={samples} metrics={MOTOR_TRENDS} label="Motor output" />
    </div>
  );
}

function TwinVectorMeters({ label, vector, unit, range, decimals }: { label: string; vector: Vec3; unit: string; range: number; decimals: number }) {
  return (
    <div className="vector-bars twin-vector-bars" role="group" aria-label={`${label} on X, Y, and Z axes`}>
      <h3>{label}</h3>
      {(["x", "y", "z"] as const).map((axis) => {
        const value = vector[axis];
        const position = 50 + clamp(value / range, -1, 1) * 48;
        return <div className={`axis-meter axis-${axis}`} key={axis}><span>{axis.toUpperCase()}</span><i aria-hidden="true"><b style={{ left: `${Math.min(50, position)}%`, width: `${Math.abs(position - 50)}%` }} /><em style={{ left: `${position}%` }} /></i><strong>{signed(value, decimals)} {unit}</strong></div>;
      })}
    </div>
  );
}

function TwinRanges({ source, samples }: { source?: PhysicalTwinSourceStatusView; samples: TwinTelemetrySample[] }) {
  if (!source?.ranges) return <div className="twin-category-stack"><p className="telemetry-unavailable">Range telemetry unavailable</p><TwinHistoryBlock samples={samples} metrics={RANGE_TRENDS} label="Obstacle ranges" /></div>;
  const ranges = source.ranges;
  return (
    <div className="twin-range-view" role="group" aria-label="Measured obstacle distances around the drone">
      <div className="twin-range-diagrams">
        <RangePlane title="Top view" detail="Front · back · left · right" directions={["front", "back", "left", "right"]} ranges={ranges} />
        <RangePlane title="Front view" detail="Up · down · left · right" directions={["up", "down", "left", "right"]} ranges={ranges} />
      </div>
      <div className="twin-range-list">
        <FlowQualityReading flow={source.flow} />
        {(["front", "back", "left", "right", "up", "down"] as const).map((direction) => <RangeReading key={direction} direction={direction} value={ranges[`${direction}M`]} state={ranges.statuses[direction] ?? "MISSING"} />)}
      </div>
      <p>0–1 m close-range scale · readings beyond 2 m are violet; exact measured values remain shown.</p>
      <TwinHistoryBlock samples={samples} metrics={RANGE_TRENDS} label="Obstacle ranges" />
    </div>
  );
}

function RangePlane({ title, detail, directions, ranges }: { title: string; detail: string; directions: ReadonlyArray<"front" | "back" | "left" | "right" | "up" | "down">; ranges: NonNullable<PhysicalTwinSourceStatusView["ranges"]> }) {
  return (
    <figure className="twin-range-plane">
      <figcaption><strong>{title}</strong><small>{detail}</small></figcaption>
      <div className={`twin-range-plane-map ${title === "Top view" ? "is-top" : "is-front"}`} aria-hidden="true">
        <span className="twin-range-drone" />
        {directions.map((direction) => <RangeRay key={direction} direction={direction} value={ranges[`${direction}M`]} />)}
      </div>
    </figure>
  );
}

function RangeRay({ direction, value }: { direction: string; value?: number }) {
  const percent = value === undefined ? 0 : Math.max(4, clamp(value / CLOSE_RANGE_DISPLAY_M, 0, 1) * 100);
  return <i className={`twin-range-ray ray-${direction} range-${rangeTone(value)}`} style={{ "--range": `${percent}%` } as CSSProperties} />;
}

function RangeReading({ direction, value, state }: { direction: string; value?: number; state: string }) {
  const percent = value === undefined ? 0 : clamp(value / CLOSE_RANGE_DISPLAY_M, 0, 1) * 100;
  return <div className={`twin-range-reading range-${rangeTone(value)}`}><span>{direction}</span><i aria-hidden="true"><b style={{ width: `${percent}%` }} /></i><strong>{value === undefined ? "Missing" : `${value.toFixed(3)} m`}</strong><em>{state}</em></div>;
}

function FlowQualityReading({ flow }: { flow?: PhysicalTwinSourceStatusView["flow"] }) {
  const quality = flow?.qualityPercent;
  const percent = quality === undefined ? 0 : clamp(quality, 0, 100);
  return (
    <div className="twin-range-reading twin-flow-quality">
      <span>Flow</span>
      <i aria-hidden="true"><b style={{ width: `${percent}%` }} /></i>
      <strong>{formatPercent(quality)}</strong>
      <em>Downward optical flow · {flow?.status ?? "UNAVAILABLE"}</em>
    </div>
  );
}

function TwinPower({ measured, samples }: { measured?: PhysicalTwinSourceStatusView; samples: TwinTelemetrySample[] }) {
  return <div className="twin-power-grid"><SourceVoltage label="Measured" source={measured} /><p>Current and battery percentage are unavailable from this observer.</p><TwinHistoryBlock samples={samples} metrics={POWER_TRENDS} label="Battery voltage" /></div>;
}

function SourceVoltage({ label, source }: { label: string; source?: PhysicalTwinSourceStatusView }) {
  return <article className="twin-voltage"><span>{label} voltage</span><strong>{formatBattery(source)}</strong><small>{availability(source, "battery")}</small></article>;
}

function TwinHistoryBlock({ samples, metrics, label }: { samples: TwinTelemetrySample[]; metrics: readonly TwinTrendMetric[]; label: string }) {
  const series = useMemo(() => buildTwinTrendSeries(samples, metrics), [metrics, samples]);
  return (
    <section className="trend-chart-block twin-history-block" aria-label={`${label} measured history`}>
      <header><h3>{label}</h3><small>Last 60 seconds</small></header>
      <TwinTrendPlot series={series} />
    </section>
  );
}

function TwinTrendPlot({
  series,
  variant = "combined",
  showLegend = true,
}: {
  series: TwinTrendSeries[];
  variant?: "combined" | "overview";
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
    <section className={`trend-plot trend-plot-${variant} twin-trend-plot ${drawable.length ? "" : "is-collecting"}`}>
      {showLegend ? <div className="trend-legend" aria-label={`Current ${unit} values`}>
        {series.map((item) => {
          const latest = item.values.at(-1)?.value;
          return <span key={item.metric}>
            <i className={`trend-series-${item.index}`} aria-hidden="true" />
            <small>{item.definition.switchLabel}</small>
            <strong>{latest === undefined ? "—" : latest.toFixed(item.definition.decimals)} {unit}</strong>
          </span>;
        })}
      </div> : null}
      {drawable.length ? <>
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
      </> : <small className="trend-plot-empty">Collecting measured {unit} history</small>}
    </section>
  );
}

function buildTwinTrendSeries(samples: TwinTelemetrySample[], metrics: readonly TwinTrendMetric[]): TwinTrendSeries[] {
  const latestTime = samples.at(-1)?.t;
  const recentSamples = latestTime === undefined
    ? []
    : samples.filter((sample) => latestTime - sample.t <= TWIN_HISTORY_WINDOW_SECONDS);
  return metrics.map((metric, index) => ({
    metric,
    index,
    definition: TWIN_TREND_DEFINITIONS[metric],
    values: recentSamples
      .filter((sample) => sample[metric] !== undefined)
      .map((sample) => ({ t: sample.t, value: sample[metric] as number })),
  }));
}

function appendTwinTelemetryHistory(
  history: TwinTelemetryHistory,
  identity: string,
  source: PhysicalTwinSourceStatusView,
): TwinTelemetryHistory {
  const sample = twinTelemetrySample(source);
  if (!sample) return history;
  if (history.identity !== identity) return { identity, samples: [sample] };
  const latest = history.samples.at(-1);
  if (!latest) return { identity, samples: [sample] };
  if (sample.t <= latest.t) return history;

  const nextSamples = sample.t - latest.t < TWIN_HISTORY_SAMPLE_INTERVAL_SECONDS
    ? [...history.samples.slice(0, -1), { ...latest, ...sample }]
    : [...history.samples, sample];
  const cutoff = sample.t - TWIN_HISTORY_WINDOW_SECONDS;
  return {
    identity,
    samples: nextSamples.filter((item) => item.t >= cutoff).slice(-TWIN_HISTORY_SAMPLE_LIMIT),
  };
}

function twinHistoryIdentity(
  sessionId: string | undefined,
  owner: PhysicalTwinStatusView["telemetryOwner"],
  source: PhysicalTwinSourceStatusView,
): string {
  return `${owner ?? "OBSERVER"}:${sessionId ?? "unscoped"}:${source.vehicleId}`;
}

function twinTelemetrySample(source: PhysicalTwinSourceStatusView): TwinTelemetrySample | undefined {
  if (source.freshness !== "CURRENT") return undefined;
  const t = source.sourceTimestampS ?? source.rawSourceTimestampS;
  if (t === undefined) return undefined;
  const attitude = source.attitude;
  const acceleration = source.imu?.acceleration;
  const angularVelocity = source.imu?.angularVelocity;
  const position = source.positionAvailability === "AVAILABLE" ? source.position : undefined;
  const motors = source.motorPwmPercent;
  const ranges = source.ranges;
  const radio = source.transport?.radio;
  const validRange = (direction: "front" | "back" | "left" | "right" | "up" | "down"): number | undefined => (
    ranges?.statuses[direction] === "VALID" ? ranges[`${direction}M`] : undefined
  );
  const rangeValues = ["front", "back", "left", "right", "up", "down"]
    .map((direction) => validRange(direction as "front" | "back" | "left" | "right" | "up" | "down"))
    .filter((value): value is number => value !== undefined);
  const roll = attitude ? degrees(attitude.rollRad) : undefined;
  const pitch = attitude ? degrees(attitude.pitchRad) : undefined;
  return {
    t,
    positionX: position?.x,
    positionY: position?.y,
    positionZ: position?.z,
    batteryVoltage: source.batteryAvailability === "AVAILABLE" ? source.batteryVoltage : undefined,
    tilt: roll !== undefined && pitch !== undefined ? Math.hypot(roll, pitch) : undefined,
    nearestRange: rangeValues.length ? Math.min(...rangeValues) : undefined,
    roll,
    pitch,
    yaw: attitude ? degrees(attitude.yawRad) : undefined,
    accelerationX: acceleration?.x,
    accelerationY: acceleration?.y,
    accelerationZ: acceleration?.z,
    angularVelocityX: angularVelocity?.x,
    angularVelocityY: angularVelocity?.y,
    angularVelocityZ: angularVelocity?.z,
    motorM1: motors?.[0],
    motorM2: motors?.[1],
    motorM3: motors?.[2],
    motorM4: motors?.[3],
    rangeFront: validRange("front"),
    rangeBack: validRange("back"),
    rangeLeft: validRange("left"),
    rangeRight: validRange("right"),
    rangeUp: validRange("up"),
    rangeDown: validRange("down"),
    packetLossPercent: radio?.packetLossPercent,
    retryQualityPercent: radio?.retryQualityPercent,
    uplinkRateHz: radio?.uplinkRateHz,
    downlinkRateHz: radio?.downlinkRateHz,
  };
}

function TwinConnection({ status, measured, samples }: { status?: PhysicalTwinStatusView; measured?: PhysicalTwinSourceStatusView; samples: TwinTelemetrySample[] }) {
  const radio = measured?.transport?.radio;
  const radioState = radio?.state ?? availability(measured, "transport");
  const failureBoundary = radio?.failureKind ?? status?.lastFailureKind ?? "NONE";
  const packetSuccess = radio?.packetLossPercent === undefined ? undefined : clamp(100 - radio.packetLossPercent, 0, 100);
  return <div className="twin-link-dashboard">
    <section className={`twin-link-hero state-${radioState.toLowerCase()}`} aria-label="Link health">
      <div className="twin-link-state">
        <i aria-hidden="true" />
        <small>Radio link</small>
        <strong>{radioState}</strong>
        <em>{failureBoundary === "NONE" ? "No active failure" : `Boundary · ${failureBoundary}`}</em>
      </div>
      <LinkGauge label="Packet success" value={packetSuccess} />
      <div className="twin-link-ack">
        <small>Last acknowledgement</small>
        <strong>{radio?.lastAckAgeMs === undefined ? "Missing" : `${radio.lastAckAgeMs.toFixed(0)} ms`}</strong>
        <em><span>{status?.state ?? "MISSING"}</span> observer</em>
      </div>
    </section>

    <section className="twin-link-section" aria-label="Delivery quality">
      <header><h3>Delivery quality</h3><small>Measured packets</small></header>
      <div className="twin-link-meter-grid">
        <LinkMeter label="Packet success" value={packetSuccess} detail={`${formatPercent(radio?.packetLossPercent)} packet loss`} />
        <LinkMeter label="Retry quality" value={radio?.retryQualityPercent} detail="Radio retry outcome" />
      </div>
      <div className="twin-link-stat-grid">
        <LinkStat label="ACK packets" value={compactCount(radio?.ackedPacketCount)} detail={radio ? `${radio.ackedPacketCount.toLocaleString()} received · ${radio.lostPacketCount.toLocaleString()} lost` : "Missing"} />
        <LinkStat label="Loss streak" value={radio ? radio.consecutiveLostPacketCount.toLocaleString() : "—"} detail={radio ? `${radio.maximumConsecutiveLostPacketCount.toLocaleString()} maximum` : "Missing"} />
      </div>
    </section>

    <section className="twin-link-section" aria-label="Radio traffic">
      <header><h3>Radio traffic</h3><small>Rate · congestion</small></header>
      <div className="twin-link-directions">
        <LinkDirection label="Uplink" rateHz={radio?.uplinkRateHz} congestionPercent={radio?.uplinkCongestionPercent} />
        <LinkDirection label="Downlink" rateHz={radio?.downlinkRateHz} congestionPercent={radio?.downlinkCongestionPercent} />
      </div>
      <LinkStat
        label="Outbound queue"
        value={radio ? `${radio.outboundQueueDepth}/${radio.outboundQueueCapacity}` : "—"}
        detail={radio ? `${radio.queueSaturationCount.toLocaleString()} saturation events` : "Missing"}
      />
    </section>

    <TwinHistoryBlock samples={samples} metrics={LINK_QUALITY_TRENDS} label="Link quality" />
    <TwinHistoryBlock samples={samples} metrics={LINK_RATE_TRENDS} label="Packet rate" />

    <details className="detail-disclosure twin-link-details">
      <summary><span><strong>Technical details</strong><small>Clocks · counters · radio diagnostics</small></span><ChevronDown size={14} /></summary>
      <div className="twin-link-detail-grid">
        <LinkDetail label="Connection" value={status?.state ?? "MISSING"} />
        <LinkDetail label="Failure boundary" value={failureBoundary} />
        <LinkDetail label="RSSI raw" value={radio?.uplinkRssiRaw === undefined ? "Missing" : radio.uplinkRssiRaw.toFixed(1)} />
        <LinkDetail label="Outbound queue" value={radio ? `${radio.outboundQueueDepth}/${radio.outboundQueueCapacity} · ${radio.queueSaturationCount} saturation events` : "Missing"} />
        <LinkDetail label="USB errors" value={(radio?.usbErrorCount ?? 0).toLocaleString()} />
        <LinkDetail label="Reconnect" value={status?.reconnectMode && status.reconnectMode !== "IDLE" ? `${status.reconnectMode === "LOW_DUTY" ? "Low duty" : "Fast"} · attempt ${status.reconnectAttempt ?? 0}` : "Idle"} />
        <LinkDetail label="Paired cycles" value={(status?.pairedCycleCount ?? 0).toLocaleString()} />
        <LinkDetail label="Channel records" value={(status?.sampleCount ?? 0).toLocaleString()} />
        <LinkDetail label="Measured clock" value={clock(measured)} wide />
        <LinkDetail label="Alignment" value={measured?.pairSequence ? `#${measured.pairSequence} · epoch ${measured.alignmentEpoch ?? "missing"}` : "Missing"} wide />
      </div>
    </details>
  </div>;
}

function LinkGauge({ label, value }: { label: string; value?: number }) {
  const percent = clamp(value ?? 0, 0, 100);
  return <div className="twin-link-gauge" role="group" aria-label={`${label}: ${value === undefined ? "Missing" : `${value.toFixed(2)}%`}`} style={{ "--quality": `${percent * 3.6}deg` } as CSSProperties}>
    <span><strong>{value === undefined ? "—" : value.toFixed(1)}</strong><small>%</small></span>
    <em>{label}</em>
  </div>;
}

function LinkMeter({ label, value, detail }: { label: string; value?: number; detail: string }) {
  const percent = clamp(value ?? 0, 0, 100);
  return <div className="twin-link-meter" role="group" aria-label={`${label}: ${value === undefined ? "Missing" : `${value.toFixed(2)}%`}`}>
    <header><span>{label}</span><strong>{value === undefined ? "—" : `${value.toFixed(2)}%`}</strong></header>
    <i aria-hidden="true"><b style={{ width: `${percent}%` }} /></i>
    <small>{detail}</small>
  </div>;
}

function LinkDirection({ label, rateHz, congestionPercent }: { label: string; rateHz?: number; congestionPercent?: number }) {
  const congestion = clamp(congestionPercent ?? 0, 0, 100);
  const tone = congestion >= 80 ? "critical" : congestion >= 50 ? "warning" : "normal";
  return <div className={`twin-link-direction tone-${tone}`}>
    <span>{label}</span>
    <strong>{formatRate(rateHz)}</strong>
    <i aria-hidden="true"><b style={{ width: `${congestion}%` }} /></i>
    <small>{formatPercent(congestionPercent)} congestion</small>
  </div>;
}

function LinkStat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <article className="twin-link-stat"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function LinkDetail({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return <article className={wide ? "is-wide" : undefined}><span>{label}</span><strong>{value}</strong></article>;
}

function compactCount(value?: number): string {
  if (value === undefined) return "—";
  if (value < 1_000) return value.toLocaleString();
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}K`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}

function formatPercent(value?: number): string {
  return value === undefined ? "Missing" : `${value.toFixed(2)}%`;
}

function formatRate(value?: number): string {
  return value === undefined ? "missing" : `${value.toFixed(1)} Hz`;
}

function availability(source: PhysicalTwinSourceStatusView | undefined, family: string): string {
  return source?.familyAvailability[family] ?? "MISSING";
}

function formatBattery(source?: PhysicalTwinSourceStatusView): string {
  return source?.batteryVoltage === undefined ? "Missing" : `${source.batteryVoltage.toFixed(3)} V`;
}

function batteryDetail(source?: PhysicalTwinSourceStatusView): string {
  if (source?.batteryVoltage === undefined) return "No reading";
  return source.freshness === "CURRENT" ? "Measured voltage" : `${source.freshness[0]}${source.freshness.slice(1).toLowerCase()} reading`;
}

function compactAttitude(source?: PhysicalTwinSourceStatusView): { value: string; detail: string } {
  if (!source?.attitude) return { value: "Missing", detail: "No reading" };
  return {
    value: `${signed(degrees(source.attitude.rollRad), 1)}° · ${signed(degrees(source.attitude.pitchRad), 1)}°`,
    detail: `Yaw ${signed(degrees(source.attitude.yawRad), 1)}°${freshnessSuffix(source)}`,
  };
}

function nearestRange(source?: PhysicalTwinSourceStatusView): { value: string; detail: string } {
  const ranges = source?.ranges;
  if (!ranges) return { value: "Missing", detail: "No reading" };
  const directions = ["front", "back", "left", "right", "up", "down"] as const;
  const available = directions
    .map((direction) => ({ direction, value: ranges[`${direction}M`] }))
    .filter((reading): reading is { direction: (typeof directions)[number]; value: number } => (
      reading.value !== undefined && ranges.statuses[reading.direction] === "VALID"
    ));
  if (available.length === 0) return { value: "Missing", detail: "No valid reading" };
  const nearest = available.reduce((current, reading) => reading.value < current.value ? reading : current);
  return {
    value: `${nearest.value.toFixed(3)} m`,
    detail: nearest.direction[0].toUpperCase() + nearest.direction.slice(1) + freshnessSuffix(source),
  };
}

function freshnessSuffix(source: PhysicalTwinSourceStatusView): string {
  return source.freshness === "CURRENT" ? "" : ` · ${source.freshness[0]}${source.freshness.slice(1).toLowerCase()}`;
}

function rangeTone(value?: number): "critical" | "warning" | "clear" | "far" | "missing" {
  if (value === undefined) return "missing";
  if (value < .2) return "critical";
  if (value < .5) return "warning";
  if (value > FAR_RANGE_INDICATOR_M) return "far";
  return "clear";
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function degrees(value: number): number {
  return value * 180 / Math.PI;
}

function signed(value: number, decimals: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}`;
}

function clock(source?: PhysicalTwinSourceStatusView): string {
  if (!source) return "Missing";
  const mapped = source.sourceTimestampS === undefined ? "mapped missing" : `${source.sourceTimestampS.toFixed(3)} s`;
  const raw = source.rawSourceTimestampS === undefined ? "raw missing" : `${source.rawSourceTimestampS.toFixed(3)} s`;
  return `${mapped} · raw ${raw}`;
}
