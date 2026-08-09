import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CampaignDropdown,
  CaseSummary,
  filterCampaignCases,
  humanizeCampaignValue,
} from "../app/components/CampaignLab";
import type { CampaignCaseView } from "../app/lib/models";

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
  afterEach(cleanup);

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
      "all",
    )).toEqual([two]);
  });

  it("keeps simulation and real mirrors in separate catalog scopes", () => {
    const simulation = campaignCase();
    const real = campaignCase({
      case_id: "real.1d.move_return.canonical_nominal",
      environment: "REAL",
      authorization: "NOT_AUTHORIZED",
    });

    expect(filterCampaignCases([simulation, real], "SIMULATION", "all", "all"))
      .toEqual([simulation]);
    expect(filterCampaignCases([simulation, real], "REAL", "all", "all"))
      .toEqual([real]);
  });

  it("explains each case without exposing raw decision codes or its hash", () => {
    const value = campaignCase();
    render(<CaseSummary campaignCase={value} />);

    expect(screen.getByText("What it does")).toBeVisible();
    expect(screen.getByText(value.behavior_under_test)).toBeVisible();
    expect(screen.getByText("Expected outcome")).toBeVisible();
    expect(screen.getByText(value.expected_outcome)).toBeVisible();
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
});
