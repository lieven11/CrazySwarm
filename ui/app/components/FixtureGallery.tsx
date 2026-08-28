import { AlertOctagon, AlertTriangle, Beaker, Check, EyeOff, LoaderCircle, Pause, Play, Radio, ShieldCheck, ShieldX, Square, WifiOff } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { fixtureForState } from "../lib/fixtures";
import type { OperatingMode } from "../lib/models";
import { HealthGlyph, ModeBadge } from "./ControlCenter";

export function FixtureGallery() {
  const stale = fixtureForState("stale").vehicles[0];
  return (
    <main className="fixture-page">
      <header><span className="eyebrow">COMPONENT DEVELOPMENT</span><h1>Operator-state fixtures</h1><p>Explicit test-only states used for visual and accessibility regression.</p></header>
      <div className="fixture-warning">TEST FIXTURES — NOT TELEMETRY — THIS ROUTE IS NOT LINKED FROM THE OPERATOR DASHBOARD</div>
      <section className="fixture-section visual-state-suite" aria-labelledby="visual-state-title">
        <h2 id="visual-state-title">Deterministic operator-state screenshot suite</h2>
        <div className="visual-state-grid">
          {VISUAL_STATES.map((state) => <VisualStateCard key={state.id} state={state} />)}
        </div>
      </section>
      <section className="fixture-section"><h2>Mode identity</h2><div className="fixture-row">{(["SIM", "LIVE", "SHADOW", "REPLAY"] as OperatingMode[]).map((mode) => <ModeBadge key={mode} mode={mode} label={mode === "SIM" ? "SIMULATION" : mode} />)}</div></section>
      <section className="fixture-section" aria-labelledby="avoidance-control-title">
        <h2 id="avoidance-control-title">Obstacle-avoidance mission control</h2>
        <div className="fixture-mission-dock-stage">
          <section className="mission-dock twin-mission-dock has-avoidance-control" aria-label="Digital Twin mission controls">
            <button className="mission-dock-summary" type="button" aria-expanded="false">
              <Beaker size={17} />
              <span><strong>Move forward 20 cm</strong><small>READY · BODY FRAME</small></span>
            </button>
            <button
              className="twin-avoidance-toggle"
              type="button"
              role="switch"
              aria-checked="true"
              title="Enforced by default; turn off only to record ranges without intervention"
            >
              <ShieldCheck size={13} />
              <span>Avoidance</span>
              <small>On</small>
            </button>
            <button className="dock-run-button twin-physical-run-button" type="button" aria-label="Run selected mission">
              <Play size={14} fill="currentColor" />
            </button>
          </section>
        </div>
      </section>
      <section className="fixture-section"><h2>Data and permission states</h2><div className="state-grid">
        <StateCard icon={<LoaderCircle />} title="Loading" body="Connecting to local control service" className="is-loading" />
        <StateCard icon={<WifiOff />} title="Disconnected" body="No API data · configured room only" />
        <StateCard icon={<EyeOff />} title="Stale" body={`Fixture age ${stale.telemetry?.provenance.ageMs ?? "—"} ms · not current`} className="is-stale" />
        <StateCard icon={<AlertTriangle />} title="Degraded" body="Localization below preferred quality" className="is-degraded" />
        <StateCard icon={<ShieldX />} title="Permission denied" body="No command lease for selected vehicle" className="is-denied" />
        <StateCard icon={<Radio />} title="Live current" body="Timestamp, source and frame verified" className="is-current" />
      </div></section>
      <section className="fixture-section"><h2>Deck health — symbol and text, never color alone</h2><div className="fixture-row">{(["HEALTHY", "DEGRADED", "FAILED", "UNKNOWN"] as const).map((health) => <div className="fixture-health" key={health}><HealthGlyph health={health} /><span>{health}</span></div>)}</div></section>
      <Link className="fixture-back" href="/">Return to control center</Link>
    </main>
  );
}

type VisualState = {
  id: "idle" | "running" | "fault" | "aborted" | "emergency" | "completed" | "replay";
  title: string;
  detail: string;
  mode: OperatingMode;
  run: string;
  icon: ReactNode;
};

const VISUAL_STATES: VisualState[] = [
  { id: "idle", title: "Idle / ready", detail: "Configured room · no observation", mode: "SIM", run: "NO ACTIVE RUN", icon: <Play /> },
  { id: "running", title: "Running", detail: "Received telemetry sequence 184 · current", mode: "SIM", run: "RUNNING · HOVER", icon: <LoaderCircle /> },
  { id: "fault", title: "Fault", detail: "Localization loss · recovery policy active", mode: "SIM", run: "FAULT · ABORTING", icon: <AlertTriangle /> },
  { id: "aborted", title: "Controlled abort", detail: "Abort-and-land receipt committed", mode: "SIM", run: "ABORTED · LANDED", icon: <Square /> },
  { id: "emergency", title: "Emergency cutoff", detail: "Motor cutoff latched · reset prohibited", mode: "SIM", run: "EMERGENCY · TERMINATED", icon: <AlertOctagon /> },
  { id: "completed", title: "Completed", detail: "Immutable result and final snapshot available", mode: "SIM", run: "SUCCEEDED · RECEIPT", icon: <Check /> },
  { id: "replay", title: "Replay", detail: "Recorded sequence 184 / 184 · command-free", mode: "REPLAY", run: "REPLAY · PAUSED", icon: <Pause /> },
];

function VisualStateCard({ state }: { state: VisualState }) {
  return (
    <article className={`visual-state-card visual-${state.id}`} data-testid={`visual-${state.id}`} data-visual-state={state.id}>
      <header>
        <ModeBadge mode={state.mode} label={state.mode === "SIM" ? "SIMULATION" : "REPLAY"} />
        <span className="visual-state-icon" aria-hidden="true">{state.icon}</span>
      </header>
      <div className="visual-mini-room" aria-hidden="true">
        <span className="visual-plan-path" />
        <span className={state.id === "replay" ? "visual-replay-path" : "visual-estimate-path"} />
        <span className="visual-truth-marker" />
        <span className="visual-vehicle-marker" />
      </div>
      <div className="visual-state-copy"><span>OPERATOR STATE</span><h3>{state.title}</h3><p>{state.detail}</p></div>
      <footer><strong>{state.run}</strong><small>{state.id === "idle" ? "CONFIGURED" : state.id === "replay" ? "RECORDED_EVIDENCE" : "SIMULATED_MODEL"}</small></footer>
    </article>
  );
}

function StateCard({ icon, title, body, className = "" }: { icon: ReactNode; title: string; body: string; className?: string }) {
  return <article className={`state-card ${className}`}><span>{icon}</span><h3>{title}</h3><p>{body}</p></article>;
}
