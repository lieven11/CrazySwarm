import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CampaignDropdown,
  CampaignLab,
  CaseSummary,
  filterCampaignCases,
  humanizeCampaignValue,
} from "../app/components/CampaignLab";
import type { ControlApi } from "../app/lib/api";
import type { CampaignCaseView, CampaignRunMode, CampaignWorkspaceView } from "../app/lib/models";

function campaignCase(overrides: Partial<CampaignCaseView> = {}): CampaignCaseView {
  return {
    case_id: "1d.move_return.canonical_nominal",
    case_sha256: "a".repeat(64),
    cluster: "BASIC_FLIGHT_AND_ROUTE_FOLLOWING",
    family: "move_return",
    variation_name: "canonical_nominal",
    purpose: "Qualify one complete move-and-return route.",
    behavior_under_test: "Checks outbound motion, return tracking, and landing.",
    expected_outcome: "The drone lands inside the declared region without an internal stop.",
    drone_count: 1,
    environment: "SIMULATION",
    authorization: "SOFTWARE_SIMULATION_ONLY",
    implementation_status: "EXECUTABLE",
    lifecycle: "DEFINED_NOT_RUN",
    allowed_strategies: ["DIRECT"],
    objective_order: ["MISSION_COMPLETION_TIME_S"],
    expected_decisions: ["DIRECT"],
    execution_eligibility: "BOTH",
    operator_observation_questions: ["Was the motion smooth?"],
    difficulty: 2,
    prerequisites: [],
    execution: {
      seed: 42,
      repetitions: 1,
      backend_profile_id: "fast-sim-v1",
      configuration_sha256: "0".repeat(64),
    },
    ...overrides,
  };
}

describe("campaign laboratory", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.removeItem("crazyswarm.campaign-workspace.v1");
  });

  it("clusters and changes fleet-size results instead of retaining an incompatible case", () => {
    const one = campaignCase();
    const two = campaignCase({
      case_id: "2d.perpendicular_crossing.nominal_equal_priority",
      cluster: "GEOMETRIC_CONFLICT_RESOLUTION",
      family: "perpendicular_crossing",
      drone_count: 2,
      difficulty: 5,
    });

    expect(filterCampaignCases([one, two], "SIMULATION", "all", "1").map((item) => item.case_id)).toEqual([
      one.case_id,
    ]);
    expect(filterCampaignCases([one, two], "SIMULATION", "all", "2").map((item) => item.case_id)).toEqual([
      two.case_id,
    ]);
    expect(filterCampaignCases(
      [one, two],
      "SIMULATION",
      "GEOMETRIC_CONFLICT_RESOLUTION",
      "2",
    )).toEqual([two]);
  });

  it("keeps simulation and real mirrors in separate catalog scopes", () => {
    const simulation = campaignCase();
    const real = campaignCase({
      case_id: "real.1d.move_return.canonical_nominal",
      environment: "REAL",
      authorization: "NOT_AUTHORIZED",
    });

    expect(filterCampaignCases([simulation, real], "SIMULATION", "all", "1"))
      .toEqual([simulation]);
    expect(filterCampaignCases([simulation, real], "REAL", "all", "1"))
      .toEqual([real]);
  });

  it("explains each case without exposing raw decision codes or its hash", () => {
    const value = campaignCase();
    render(<CaseSummary campaignCase={value} />);

    expect(screen.getByText("What it does")).toBeVisible();
    expect(screen.getByText(value.behavior_under_test)).toBeVisible();
    expect(screen.getByText("Expected outcome")).toBeVisible();
    expect(screen.getByText(value.expected_outcome)).toBeVisible();
    expect(screen.queryByText(value.purpose)).toBeNull();
    expect(screen.queryByText(/Difficulty/)).toBeNull();
    expect(screen.queryByText(value.authorization)).toBeNull();
    expect(screen.queryByText("Planner may use")).toBeNull();
    expect(screen.queryByText("Expected")).toBeNull();
    expect(screen.queryByText(/aaaaaaaaaaaaaaaaaaaa/)).toBeNull();
  });

  it("opens a bounded searchable menu with readable color-coded statuses", () => {
    const onChange = vi.fn();
    render(
      <CampaignDropdown
        label="Mission case"
        value="altitude"
        searchable
        onChange={onChange}
        options={[
          {
            value: "altitude",
            label: "Altitude transition",
            meta: "Canonical nominal · Difficulty 2/10 · 1D",
            badge: "Not started",
            badgeClassName: "state-defined_not_run",
          },
          {
            value: "curved",
            label: "Curved route",
            meta: "Wide · Difficulty 3/10 · 1D",
            badge: "Completed",
            badgeClassName: "state-promoted",
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Altitude transition/i }));
    expect(screen.getByRole("listbox", { name: "Mission case" })).toBeVisible();
    expect(screen.getByRole("option", { name: /Not started.*Altitude transition/i }))
      .toHaveClass("is-selected");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "curved" } });
    fireEvent.click(screen.getByRole("option", { name: /Completed.*Curved route/i }));
    expect(onChange).toHaveBeenCalledWith("curved");
  });

  it("turns immutable identifiers into operator-facing names", () => {
    expect(humanizeCampaignValue("continuous_waypoint_sequence"))
      .toBe("Continuous waypoint sequence");
  });

  it("configures the bottom dock run mode without starting from the workspace", async () => {
    const value = campaignCase();
    const onActiveCaseChange = vi.fn();
    const onCampaignRunChange = vi.fn();
    const onExecutionModeChange = vi.fn();
    let workspace: CampaignWorkspaceView = { runs: [], reviews: [] };
    const api = {
      campaignCatalog: vi.fn(async () => ({ cases: [value], hierarchy: {} })),
      campaignState: vi.fn(async () => workspace),
      setActiveCampaignCase: vi.fn(async () => {
        workspace = {
          ...workspace,
          active_case_id: value.case_id,
          locked_inputs: {
            case_sha256: value.case_sha256,
            seed: 42,
            backend_profile_id: "fast-sim-v1",
            configuration_sha256: "0".repeat(64),
            planner_implementation_id: "bounded-joint-planner",
            planner_implementation_version: "1.0.0",
            planner_settings_sha256: "1".repeat(64),
          },
        };
        return {};
      }),
      runActiveCampaign: vi.fn(async (mode: CampaignRunMode) => {
        const run = {
          accepted: true as const,
          run_id: "campaign-run-ui",
          mode,
          status: "RUNNING" as const,
        };
        workspace = {
          ...workspace,
          runs: [{
            ...run,
            locked_inputs: {
              case_id: value.case_id,
              case_sha256: value.case_sha256,
              seed: 42,
              backend_profile_id: "fast-sim-v1",
              configuration_sha256: "0".repeat(64),
              planner_implementation_id: "bounded-joint-planner",
              planner_implementation_version: "1.0.0",
              planner_settings_sha256: "1".repeat(64),
            },
            requested_at_utc: new Date().toISOString(),
          }],
        };
        return run;
      }),
    } as unknown as ControlApi;

    render(
      <CampaignLab
        api={api}
        onNotice={vi.fn()}
        onActiveCaseChange={onActiveCaseChange}
        onCampaignRunChange={onCampaignRunChange}
        onExecutionModeChange={onExecutionModeChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Set active" }));
    await waitFor(() => expect(onActiveCaseChange).toHaveBeenCalledWith(value));

    fireEvent.click(screen.getByRole("tab", { name: "Active run" }));
    const realtime = screen.getByRole("radio", { name: "Realtime" });
    expect(realtime).toHaveAttribute("aria-checked", "true");
    expect(realtime).toHaveClass("mode-realtime");
    await waitFor(() => expect(onExecutionModeChange).toHaveBeenLastCalledWith("OPERATOR_OBSERVED_REALTIME"));

    const accelerated = screen.getByRole("radio", { name: "Accelerated" });
    fireEvent.click(accelerated);
    await waitFor(() => expect(onExecutionModeChange).toHaveBeenLastCalledWith("AUTOMATED_ACCELERATED"));
    expect(accelerated).toHaveAttribute("aria-checked", "true");
    expect(accelerated).toHaveClass("mode-accelerated");
    expect(screen.queryByRole("button", { name: /Start (realtime|accelerated)/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Same inputs" })).not.toBeInTheDocument();
    expect(api.runActiveCampaign).not.toHaveBeenCalled();
    expect(onCampaignRunChange).not.toHaveBeenCalled();
  });

  it("restores the selected execution mode from campaign workspace preferences", async () => {
    const value = campaignCase();
    window.localStorage.setItem("crazyswarm.campaign-workspace.v1", JSON.stringify({
      runMode: "AUTOMATED_ACCELERATED",
    }));
    const onExecutionModeChange = vi.fn();
    const api = {
      campaignCatalog: vi.fn(async () => ({ cases: [value], hierarchy: {} })),
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
    } as unknown as ControlApi;

    render(
      <CampaignLab
        api={api}
        onNotice={vi.fn()}
        onExecutionModeChange={onExecutionModeChange}
      />,
    );

    await waitFor(() => expect(onExecutionModeChange)
      .toHaveBeenLastCalledWith("AUTOMATED_ACCELERATED"));
    await waitFor(() => expect(JSON.parse(
      window.localStorage.getItem("crazyswarm.campaign-workspace.v1") ?? "{}",
    ).runMode).toBe("AUTOMATED_ACCELERATED"));
  });
});
