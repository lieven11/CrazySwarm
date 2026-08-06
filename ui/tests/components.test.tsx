import axe from "axe-core";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { deterministicDashboard } from "../app/lib/fixtures";
import { FixtureGallery } from "../app/components/FixtureGallery";
import { armActionEnabled, ControlCenter, controlActionsEnabled, ModeBadge, SafetyDialog } from "../app/components/ControlCenter";
import { formatClockContext } from "../app/components/RoomScene";

describe("operator components", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each(["SIM", "LIVE", "SHADOW", "REPLAY"] as const)("labels %s mode in text", (mode) => {
    render(<ModeBadge mode={mode} />);
    expect(screen.getByLabelText(`Mode: ${mode}`)).toHaveTextContent(mode);
  });

  it("requires the explicit STOP phrase for last-resort motor cutoff", () => {
    const confirm = vi.fn();
    render(
      <SafetyDialog
        kind="emergency"
        vehicle={deterministicDashboard.vehicles[0]}
        onClose={vi.fn()}
        onConfirm={confirm}
      />,
    );
    const button = screen.getByRole("button", { name: "Cut motors now" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Type STOP/), { target: { value: "STOP" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(confirm).toHaveBeenCalledOnce();
  });

  it("keeps flight actions disabled without API, lease, and armed state", () => {
    const vehicle = deterministicDashboard.vehicles[0];
    expect(controlActionsEnabled(deterministicDashboard, vehicle)).toBe(false);
    expect(controlActionsEnabled({ ...deterministicDashboard, apiConnected: true }, { ...vehicle, commandAuthority: false })).toBe(false);
    expect(controlActionsEnabled({ ...deterministicDashboard, apiConnected: true }, { ...vehicle, telemetry: vehicle.telemetry ? { ...vehicle.telemetry, armed: false } : undefined })).toBe(false);
    expect(controlActionsEnabled({ ...deterministicDashboard, apiConnected: true }, { ...vehicle, commandAuthority: true })).toBe(true);
  });

  it("never enables arming from a latched emergency state", () => {
    const vehicle = { ...deterministicDashboard.vehicles[0], state: "EMERGENCY" };
    const preflight = { reportId: "preflight-1", approved: true, expiresAtMonotonicS: 100, checks: [] };
    expect(armActionEnabled(vehicle, preflight)).toBe(false);
    expect(armActionEnabled({ ...vehicle, state: "READY" }, preflight)).toBe(true);
  });

  it("formats simulation and replay clocks without relabeling receive time", () => {
    const provenance = deterministicDashboard.vehicles[0].telemetry!.provenance;
    expect(formatClockContext({ ...provenance, sourceTimeS: 4, receiveTimeS: 4.03, simulationTimeS: 4 }))
      .toBe("sim 4.00 s · received 4.03 s");
    expect(formatClockContext({ ...provenance, sourceTimeS: 4, receiveTimeS: 4.03, replayTimeS: 9 }))
      .toBe("replay 9.00 s · source 4.00 s");
  });

  it("exposes only Python upload, the two execution paths, and clickable controls", async () => {
    const json = (value: unknown) => new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/state")) return json({
        mode: "SIM",
        selected_vehicle_id: "sim01",
        configured_flight_volume: null,
        mission_runs: [],
        vehicles: [{
          identity: { vehicle_id: "sim01", display_name: "Simulator", adapter: "sim" },
          capabilities: { decks: [] },
          selected: true,
          state: "DISCONNECTED",
          telemetry: null,
          control_lease: null,
          control_state: { armed: null, flying: null },
        }],
      });
      if (url.endsWith("/api/v1/mission-files")) return json([]);
      if (url.endsWith("/api/v1/simulation/world")) return json({
        schema_version: 1,
        world: { world_id: "room", width_m: 4, depth_m: 4, height_m: 2.5, obstacles: [] },
        vehicles: [{ vehicle_id: "sim01", position_m: { x: 0, y: 0, z: 0 } }],
      });
      if (url.endsWith("/api/v1/simulation/fidelity")) return json({
        manifest_id: "mission-kinematics-v1",
        source_class: "SIMULATED_MODEL",
        model: "mission kinematics",
        modeled_outputs: ["position"],
        omitted_outputs: ["motor_dynamics"],
        limitations: ["not 6DOF"],
      });
      if (url.endsWith("/api/v1/twins")) return json([]);
      if (url.endsWith("/api/v1/simulation/vehicles/sim01/clock")) return json({
        now_s: 0,
        paused: false,
        speed: 1,
        battery_percent: 100,
        reset_scope: ["clock", "pose", "battery", "model_state"],
      });
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ControlCenter />);
    expect(await screen.findByRole("button", { name: "Simulation" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Digital twin" })).toBeDisabled();
    expect(screen.getByText("Add Python")).toBeVisible();
    expect(screen.queryByText(/mission parameters/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recharge simulation" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Simulator reset · battery 100.0%");
    fireEvent.click(screen.getByRole("button", { name: "Controls" }));
    expect(await screen.findByRole("heading", { name: "Engineering" })).toBeVisible();
  });

  it("renders its deterministic component gallery without serious accessibility violations", async () => {
    const { container } = render(<FixtureGallery />);
    const result = await axe.run(container, {
      rules: {
        region: { enabled: false },
        // jsdom has no canvas-backed color parser; contrast is checked in the visual QA checklist.
        "color-contrast": { enabled: false },
      },
    });
    expect(result.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious")).toEqual([]);
  });
});
