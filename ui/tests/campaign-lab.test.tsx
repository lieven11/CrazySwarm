import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CampaignDropdown,
  CampaignLab,
  CaseSummary,
  campaignWorkspaceHeaderSummary,
  filterCampaignCases,
  humanizeCampaignValue,
} from "../app/components/CampaignLab";
import type { ControlApi } from "../app/lib/api";
import type {
  CampaignCaseView,
  CampaignPlanningSubmissionView,
  CampaignRunMode,
  CampaignSubmissionView,
  CampaignWorkspaceView,
} from "../app/lib/models";

function campaignCase(overrides: Partial<CampaignCaseView> = {}): CampaignCaseView {
  return {
    case_id: "1d.move_return.canonical_nominal",
    case_sha256: "a".repeat(64),
    execution_semantics_sha256: "b".repeat(64),
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
    drones: [],
    semantic_audit: {
      classification: "SEMANTICALLY_EXECUTABLE",
      reason: "Executable behavior contract passes the family invariant.",
    },
    execution: {
      seed: 42,
      repetitions: 1,
      backend_profile_id: "fast-sim-v1",
      configuration_sha256: "0".repeat(64),
    },
    motion_preparation_limits: {
      accuracy_min_m: 0.01,
      accuracy_max_m: 0.08,
      accuracy_binding: "mission goal tolerance",
    },
    ...overrides,
  };
}

function campaignSubmission(
  overrides: Partial<CampaignSubmissionView> = {},
): CampaignSubmissionView {
  return {
    submission_id: "1d.altitude_transition.canonical_nominal.planner-retimed-baseline",
    submission_sha256: "c".repeat(64),
    semantic_fingerprint_sha256: "d".repeat(64),
    submission_version: "1.0.0",
    display_name: "Planner-retimed baseline",
    case_id: "1d.altitude_transition.canonical_nominal",
    case_sha256: "a".repeat(64),
    kind: "PLANNER_RETIMED_BASELINE",
    owner: "PLANNER",
    status: "EXECUTABLE",
    run_eligible: true,
    missing_prerequisites: [],
    comparison_case_ids: ["1d.altitude_transition.canonical_nominal"],
    rationale: "Retains the case's existing bounded planner and time-allocation behavior.",
    parameters: {
      segment_target_speeds_m_s: [],
      entry_exit_ramp_s: 0,
      steady_window_tolerance_fraction: 0.08,
    },
    prerequisite_submission_ids: [],
    metric_ids: ["mission_completion_time_s"],
    admission: {
      causal_question: "What behavior does the existing bounded planner select for this case?",
      baseline_limitation: "The baseline does not isolate a commanded speed law.",
      distinguishing_oracle: "Accepted plan and trajectory identities reproduce the retained baseline.",
      reused_evidence: [],
      new_integration_gate: "No new integration gate.",
      learning_value: "Provides the immutable comparison point for successor submissions.",
    },
    ...overrides,
  };
}

function campaignPlanningSubmission(
  overrides: Partial<CampaignPlanningSubmissionView> = {},
): CampaignPlanningSubmissionView {
  return {
    planning_submission_id: "planning.baseline",
    planning_submission_sha256: "e".repeat(64),
    semantic_fingerprint_sha256: "f".repeat(64),
    submission_version: "1.0.0",
    display_name: "Baseline planning authority",
    case_id: "1d.altitude_transition.canonical_nominal",
    case_sha256: "a".repeat(64),
    status: "EXECUTABLE",
    rationale: "Uses the case's declared strategies and objective order.",
    experiment_id: "baseline_case_authority",
    experiment_axis: "OBJECTIVE_ORDER",
    axis_value: "case_default",
    layer: "P",
    support_reason: "Executable through the configured Fast-Sim planning path.",
    strategy_authority: ["DIRECT", "GROUND_DELAY"],
    maneuver_dimensions: ["RELEASE_TIME"],
    path_adherence: { mode: "GOAL_SEQUENCE_ONLY" },
    clearance: {
      nominal_vehicle_radius_m: 0.12,
      nominal_vehicle_half_height_m: 0.06,
      required_pairwise_center_separation_m: 0.3,
      required_solid_clearance_m: 0.08,
      uncertainty_allowance_m: 0.02,
    },
    coordination: {
      synchronized_launch_required: false,
      synchronized_route_start_required: false,
      minimum_simultaneous_flight_s: 0,
      maximum_release_delay_s: 60,
    },
    objective: {
      composition: "LEXICOGRAPHIC",
      terms: [{ metric: "MISSION_COMPLETION_TIME_S" }],
      deterministic_tie_breaker: "CANDIDATE_SHA256",
    },
    feasibility_oracle_ids: ["continuous-clearance"],
    admission: {
      causal_question: "What behavior does the immutable case authority select?",
      baseline_limitation: "This is the retained comparison baseline.",
      principal_variable: "case_default",
      fixed_inputs: ["case_hash"],
      behavior_difference: "No override is applied.",
      distinguishing_oracle: "The accepted plan reproduces retained case authority.",
      reused_evidence: [],
      new_integration_gate: "Deterministic planning must pass.",
      backend_semantics: "Fast Sim only.",
      safety_bounds: "All case constraints remain hard.",
      operator_comparison: "Compare accepted plan and evidence hashes.",
      learning_value: "Provides the comparison point.",
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
    const value = campaignCase({
      semantics: {
        curriculum_level: 3,
        learning_objective: "Verify one bounded altitude transition.",
        difficulty_rationale: "One active role plus vertical route geometry.",
        route_intent_by_role: {
          Alpha: [{
            region_id: "Alpha-goal-1",
            mode: "FLY_THROUGH",
            dwell_s: 0,
            capture_tolerance_m: 0.1,
          }],
        },
        scenario_events: [],
        behavior_oracles: [{
          oracle_id: "route-nodes-captured",
          kind: "ROUTE_NODES_CAPTURED",
          evidence_source: "trajectory",
        }],
      },
    });
    render(<CaseSummary campaignCase={value} />);

    expect(screen.getByText("Level 3 objective")).toBeVisible();
    expect(screen.getByText("Verify one bounded altitude transition.")).toBeVisible();
    expect(screen.getByText("What it does")).toBeVisible();
    expect(screen.getByText(value.behavior_under_test)).toBeVisible();
    expect(screen.getByText("Expected outcome")).toBeVisible();
    expect(screen.getByText(value.expected_outcome)).toBeVisible();
    expect(screen.getByText("Technical criteria")).toBeVisible();
    expect(document.querySelector<HTMLDetailsElement>(".campaign-case-technical")?.open).toBe(false);
    fireEvent.click(screen.getByText("Technical criteria"));
    expect(document.querySelector<HTMLDetailsElement>(".campaign-case-technical")?.open).toBe(true);
    expect(screen.getByText("Authored route")).toBeVisible();
    expect(screen.queryByText(value.purpose)).toBeNull();
    expect(screen.queryByText(/Difficulty/)).toBeNull();
    expect(screen.queryByText(value.authorization)).toBeNull();
    expect(screen.queryByText("Planner may use")).toBeNull();
    expect(screen.queryByText("Expected")).toBeNull();
    expect(screen.queryByText(/aaaaaaaaaaaaaaaaaaaa/)).toBeNull();
    expect(screen.queryByText(/bbbbbbbbbbbb/)).toBeNull();
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

  it("shows compact lifecycle dots on the selected variant and its choices", () => {
    render(
      <CampaignDropdown
        label="Variant"
        level={3}
        value="review"
        onChange={vi.fn()}
        options={[
          {
            value: "progress",
            label: "Canonical nominal",
            badge: "In progress",
            badgeClassName: "state-active_development",
            badgePresentation: "dot",
          },
          {
            value: "review",
            label: "Wide altitude transition",
            badge: "In review",
            badgeClassName: "state-baselined",
            badgePresentation: "dot",
          },
          {
            value: "completed",
            label: "High altitude transition",
            badge: "Completed",
            badgeClassName: "state-promoted",
            badgePresentation: "dot",
          },
        ]}
      />,
    );

    const trigger = screen.getByRole("button", { name: /Wide altitude transition.*In review/i });
    expect(within(trigger).getByTitle("In review")).toHaveClass("is-dot", "state-baselined");
    fireEvent.click(trigger);
    expect(within(screen.getByRole("option", { name: /In progress.*Canonical nominal/i }))
      .getByTitle("In progress")).toHaveClass("is-dot", "state-active_development");
    expect(within(screen.getByRole("option", { name: /Completed.*High altitude transition/i }))
      .getByTitle("Completed")).toHaveClass("is-dot", "state-promoted");
  });

  it("turns immutable identifiers into operator-facing names", () => {
    expect(humanizeCampaignValue("continuous_waypoint_sequence"))
      .toBe("Continuous waypoint sequence");
  });

  it("summarizes the catalog name, active-run mode, and review status", () => {
    const selected = campaignCase({
      family: "altitude_transition",
      lifecycle: "ACTIVE_DEVELOPMENT",
    });

    expect(campaignWorkspaceHeaderSummary({
      selectedCase: selected,
      runMode: "AUTOMATED_ACCELERATED",
      reviewStatus: "NEEDS_RERUN",
    })).toBe("Altitude transition · Accelerated · Needs rerun");
  });

  it("offers four lifecycle-only status controls without a duplicate state picker", async () => {
    const value = campaignCase({ lifecycle: "ACTIVE_DEVELOPMENT" });
    const setCampaignCaseLifecycle = vi.fn(async () => ({}));
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(async () => ({ cases: [value], hierarchy: {} })),
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
      setCampaignCaseLifecycle,
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));
    const notStarted = await screen.findByRole("button", { name: "Not started" });
    expect(screen.queryByRole("combobox", { name: "Mission state" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check only" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Preview plan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Qualification" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Constraint matrix" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use mission" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "In progress" })).toBeVisible();
    expect(screen.getByRole("button", { name: "In review" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Completed" })).toBeVisible();
    fireEvent.click(notStarted);

    await waitFor(() => expect(setCampaignCaseLifecycle).toHaveBeenCalledWith(
      value.case_id,
      "DEFINED_NOT_RUN",
      "operator set mission to inactive",
    ));
  });

  it("shows an in-progress mission as completed before its catalog refresh finishes", async () => {
    const value = campaignCase({ lifecycle: "ACTIVE_DEVELOPMENT" });
    const setCampaignCaseLifecycle = vi.fn(async () => ({}));
    let catalogRequestCount = 0;
    const api = {
      campaignCatalog: vi.fn(() => {
        catalogRequestCount += 1;
        return catalogRequestCount === 1
          ? Promise.resolve({ cases: [value], hierarchy: {} })
          : new Promise<never>(() => {});
      }),
      campaignState: vi.fn(async () => ({ active_case_id: value.case_id, runs: [], reviews: [] })),
      setCampaignCaseLifecycle,
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));

    const completed = await screen.findByRole("button", { name: "Completed" });
    expect(completed).toBeEnabled();
    fireEvent.click(completed);

    await waitFor(() => expect(setCampaignCaseLifecycle).toHaveBeenCalledWith(
      value.case_id,
      "PROMOTED",
      "operator marked mission as completed",
    ));
    await waitFor(() => expect(completed).toBeDisabled());
    expect(completed).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".campaign-case-detail .campaign-status")).toHaveTextContent("Completed");
  });

  it("blocks mission selection while another campaign run is active", async () => {
    const selected = campaignCase({
      case_id: "1d.continuous_waypoint_sequence.canonical_nominal",
      family: "continuous_waypoint_sequence",
    });
    const active = campaignCase({
      case_id: "1d.altitude_transition.wide",
      case_sha256: "b".repeat(64),
      family: "altitude_transition",
      variation_name: "wide",
      lifecycle: "ACTIVE_DEVELOPMENT",
    });
    window.localStorage.setItem("crazyswarm.campaign-workspace.v1", JSON.stringify({
      selectedId: selected.case_id,
    }));
    const setActiveCampaignCase = vi.fn(async () => ({}));
    const workspace: CampaignWorkspaceView = {
      active_case_id: active.case_id,
      runs: [{
        run_id: "campaign-run-active",
        mode: "OPERATOR_OBSERVED_REALTIME",
        status: "RUNNING",
        locked_inputs: {
          case_id: active.case_id,
          case_sha256: active.case_sha256,
          seed: 42,
          backend_profile_id: "fast-sim-v1",
          configuration_sha256: "0".repeat(64),
          planner_implementation_id: "bounded-joint-planner",
          planner_implementation_version: "1.0.0",
          planner_settings_sha256: "1".repeat(64),
        },
        requested_at_utc: "2026-08-13T15:00:00Z",
      }],
      reviews: [],
    };
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(async () => ({ cases: [active, selected], hierarchy: {} })),
      campaignState: vi.fn(async () => workspace),
      setActiveCampaignCase,
    } as unknown as ControlApi;

    const onNotice = vi.fn();
    render(<CampaignLab api={api} onNotice={onNotice} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));

    expect(await screen.findByText("Continuous waypoint sequence · Realtime · No review")).toBeVisible();
    const majorMission = screen.getByRole("button", { name: "Continuous waypoint sequence" });
    fireEvent.click(majorMission);
    fireEvent.click(screen.getByRole("option", { name: /^Continuous waypoint sequence/ }));
    expect(setActiveCampaignCase).not.toHaveBeenCalled();
    expect(onNotice).toHaveBeenCalledWith("Stop the active campaign run before selecting another mission");
  });

  it("uses the distinct two-drone curriculum and exposes resolution and launch-gap controls", async () => {
    const basic = campaignCase();
    const conflict = campaignCase({
      case_id: "2d.bottleneck.canonical_nominal",
      case_sha256: "c".repeat(64),
      cluster: "GEOMETRIC_CONFLICT_RESOLUTION",
      family: "bottleneck",
      drone_count: 2,
      planning_submissions: [
        campaignPlanningSubmission({
          planning_submission_id: "bottleneck.earliest_safe_release",
          display_name: "Earliest safe release",
          maneuver_dimensions: ["TIMING"],
          strategy_authority: ["GROUND_DELAY"],
        }),
        campaignPlanningSubmission({
          planning_submission_id: "bottleneck.vertical_layer",
          display_name: "Vertical layer",
          maneuver_dimensions: ["VERTICAL"],
          strategy_authority: ["VERTICAL_LAYER"],
        }),
      ],
    });
    window.localStorage.setItem("crazyswarm.campaign-workspace.v1", JSON.stringify({
      selectedId: basic.case_id,
    }));
    const setActiveCampaignCase = vi.fn(async () => ({}));
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(async () => ({
        cases: [basic, conflict],
        hierarchy: {},
        two_drone_missions: {
          schema_version: 1,
          curriculum_id: "2d-conflict-missions-v1",
          groups: [{
            label: "Traffic",
            variants: [{
              label: "Narrow bottleneck",
              case_id: conflict.case_id,
              status: "EXECUTABLE",
            }],
          }],
        },
      })),
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
      setActiveCampaignCase,
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));

    await screen.findByRole("button", { name: "Basic flight & routes" });
    fireEvent.click(screen.getByRole("button", { name: "2D" }));

    await waitFor(() => expect(setActiveCampaignCase).toHaveBeenCalledWith(
      conflict.case_id,
      "operator selected mission from catalog hierarchy",
    ));
    expect(screen.getByRole("button", { name: "2D" })).toHaveClass("is-selected");
    expect(screen.queryByRole("button", { name: "Conflict resolution" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Traffic" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Narrow bottleneck.*Not started/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /^Earliest safe release/ })).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: "Tune launch gap" }));
    const startGap = screen.getByRole("slider", { name: "Start gap" });
    expect(startGap).toBeVisible();
    fireEvent.change(startGap, { target: { value: "7.5" } });
    expect(startGap).toHaveValue("7.5");
    for (const label of ["Balance", "Speed", "Accuracy", "Smoothness"]) {
      expect(screen.getByRole("slider", { name: label })).toBeVisible();
    }
  });

  it("never exposes two-drone launch-gap preparation for a 1D mission", async () => {
    const oneDroneTimingCase = campaignCase({
      case_id: "1d.altitude_transition.canonical_nominal",
      family: "altitude_transition",
      planning_submissions: [campaignPlanningSubmission({
        planning_submission_id: "altitude.timing-capable",
        maneuver_dimensions: ["TIMING"],
        coordination: {
          synchronized_launch_required: false,
          synchronized_route_start_required: false,
          minimum_simultaneous_flight_s: 0,
          maximum_release_delay_s: 10,
        },
      })],
    });
    const onCoordinationPreparationChange = vi.fn();
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(async () => ({
        cases: [oneDroneTimingCase],
        hierarchy: {},
      })),
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
    } as unknown as ControlApi;

    render(
      <CampaignLab
        api={api}
        onNotice={vi.fn()}
        onCoordinationPreparationChange={onCoordinationPreparationChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));

    await screen.findByText("Altitude transition · Realtime · No review");
    expect(screen.queryByRole("checkbox", { name: "Tune launch gap" }))
      .not.toBeInTheDocument();
    expect(screen.queryByText("Launch timing")).not.toBeInTheDocument();
    const motion = screen.getByRole("region", { name: "Motion preparation" });
    expect(within(motion).getByText("4")).toBeVisible();
    expect(onCoordinationPreparationChange).toHaveBeenLastCalledWith(undefined);
  });

  it("selects a discovered simulation mission regardless of catalog implementation status", async () => {
    const available = campaignCase();
    const planned = campaignCase({
      case_id: "1d.failure_recovery.dynamic_nominal",
      case_sha256: "c".repeat(64),
      cluster: "FAILURE_RECOVERY_AND_REPLANNING",
      family: "failure_recovery",
      variation_name: "dynamic_nominal",
      implementation_status: "PLANNED_NOT_EXECUTABLE",
      execution_eligibility: "STATIC_VALIDATE_ONLY",
    });
    const setActiveCampaignCase = vi.fn(async () => ({}));
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(async () => ({ cases: [available, planned], hierarchy: {} })),
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
      setActiveCampaignCase,
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));

    const cluster = await screen.findByRole("button", { name: "Basic flight & routes" });
    fireEvent.click(cluster);
    fireEvent.click(screen.getByRole("option", { name: "Recovery & replanning" }));

    await waitFor(() => expect(setActiveCampaignCase).toHaveBeenCalledWith(
      planned.case_id,
      "operator selected mission from catalog hierarchy",
    ));
    expect(screen.getByRole("button", { name: /Dynamic nominal.*Not started/i })).toBeEnabled();
    expect(screen.queryByText(/Unavailable: Planned not executable/i)).not.toBeInTheDocument();
  });

  it("replaces technical submission choices with the shared preparation hierarchy", async () => {
    const baseline = campaignSubmission();
    const constantSpeed = campaignSubmission({
      submission_id: "1d.altitude_transition.canonical_nominal.constant-path-speed",
      submission_sha256: "d".repeat(64),
      display_name: "Constant path speed",
      kind: "CONSTANT_PATH_SPEED",
      owner: "TIME_PARAMETERIZER",
      rationale: "Holds path speed constant across the climb and descent segments.",
      parameters: {
        target_path_speed_m_s: 0.35,
        segment_target_speeds_m_s: [],
        entry_exit_ramp_s: 0.5,
        steady_window_tolerance_fraction: 0.08,
      },
    });
    const baselinePlanning = campaignPlanningSubmission();
    const directedPlanning = campaignPlanningSubmission({
      planning_submission_id: "constraint_directed.altitude.flexible",
      planning_submission_sha256: "f".repeat(64),
      display_name: "Constraint-directed vertical planning",
      rationale: "Authorizes vertical alternatives under continuous clearance checks.",
      maneuver_dimensions: ["VERTICAL", "RELEASE_TIME"],
      strategy_authority: ["VERTICAL_LAYER", "GROUND_DELAY"],
    });
    const value = campaignCase({
      case_id: baseline.case_id,
      family: "altitude_transition",
      submissions: [baseline, constantSpeed],
      planning_submissions: [baselinePlanning, directedPlanning],
    });
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(async () => ({ cases: [value], hierarchy: {} })),
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));
    await screen.findByText("Altitude transition · Realtime · No review");

    const controls = document.querySelector<HTMLElement>(".campaign-catalog-controls");
    const detail = document.querySelector<HTMLElement>(".campaign-case-detail");
    expect(controls).not.toBeNull();
    expect(detail).not.toBeNull();
    expect(within(controls!).getByText("Major mission")).toBeVisible();
    expect(within(controls!).getByText("Variant")).toBeVisible();
    expect(within(controls!).getByText("Motion")).toBeVisible();
    expect(within(controls!).queryByText("Execution submission")).not.toBeInTheDocument();
    expect(within(controls!).queryByText("Planning contract")).not.toBeInTheDocument();
    expect(within(detail!).queryByText("Planner-retimed baseline")).not.toBeInTheDocument();
    expect(screen.queryByText("Eligible")).not.toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Smoothness" })).toBeVisible();
  });

  it("renders the five plain major missions and bounded motion controls without internal labels", async () => {
    const cases = [
      ["1d.takeoff_hover_land.canonical_nominal", "takeoff_hover_land"],
      ["1d.move_to_target.canonical_nominal", "move_to_target"],
      ["1d.curved_route.canonical_nominal", "curved_route"],
      ["1d.altitude_transition.canonical_nominal", "altitude_transition"],
      ["1d.planar_shape_loop.figure_eight", "planar_shape_loop"],
    ].map(([case_id, family]) => campaignCase({
      case_id,
      family,
      ...(family === "curved_route" || family === "altitude_transition" || family === "planar_shape_loop"
        ? {
          motion_preparation_limits: {
            accuracy_min_m: 0.01,
            accuracy_max_m: 5.1884487084291395,
            accuracy_binding: "flight-volume route span",
          },
        }
        : {}),
    }));
    const majorMissions = {
      schema_version: 1 as const,
      curriculum_id: "1d-major-missions-v1" as const,
      groups: [
        { label: "Flight" as const, variants: [{ label: "Take off, hover, land", case_id: cases[0].case_id, status: "EXECUTABLE" as const }] },
        { label: "Target" as const, variants: [{ label: "Move to target", case_id: cases[1].case_id, status: "EXECUTABLE" as const }] },
        { label: "Level path" as const, variants: [{ label: "Curved route", case_id: cases[2].case_id, status: "EXECUTABLE" as const }] },
        { label: "3D path" as const, variants: [
          { label: "Altitude transition", case_id: cases[3].case_id, status: "EXECUTABLE" as const },
          { label: "Wind shift", case_id: "1d.wind_shift.reserved", status: "PLANNED_NOT_EXECUTABLE" as const, disabled_reason: "Available after dynamic reaction qualification." },
        ] },
        { label: "Shape" as const, variants: [{ label: "Figure eight", case_id: cases[4].case_id, status: "EXECUTABLE" as const }] },
      ],
    };
    const api = {
      campaignQualificationUrl: vi.fn(() => "/control-api/api/v1/campaign/qualification/export"),
      campaignCatalog: vi.fn(async () => ({
        cases,
        hierarchy: {},
        major_missions: majorMissions,
      })),
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
      setActiveCampaignCase: vi.fn(async () => ({})),
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));
    const majorMission = await screen.findByRole("button", { name: "Flight" });
    fireEvent.click(majorMission);
    for (const label of ["Flight", "Target", "Level path", "3D path", "Shape"]) {
      expect(screen.getByRole("option", { name: new RegExp(`^${label}`) })).toBeVisible();
    }
    fireEvent.click(screen.getByRole("option", { name: /^3D path/ }));
    await waitFor(() => expect(api.setActiveCampaignCase).toHaveBeenCalledWith(
      cases[3].case_id,
      "operator selected major mission",
    ));

    const balance = screen.getByRole("slider", { name: "Balance" });
    expect(balance).toHaveAttribute("type", "range");
    expect(balance).toBeEnabled();
    expect(balance).toHaveValue("50");
    fireEvent.change(balance, { target: { value: "60" } });
    expect(balance).toHaveValue("60");
    expect(screen.getByRole("slider", { name: "Speed" })).toBeVisible();
    const accuracy = screen.getByRole("slider", { name: "Accuracy" });
    expect(accuracy).toBeVisible();
    expect(accuracy).toHaveAttribute("max", "5.1884487084291395");
    fireEvent.change(accuracy, { target: { value: "4" } });
    expect(accuracy).toHaveValue("4");
    fireEvent.focus(accuracy);
    expect(screen.getByText("Accuracy: flight-volume route span 5.19 m maximum.")).toBeVisible();
    const smoothness = screen.getByRole("slider", { name: "Smoothness" });
    expect(smoothness).toBeVisible();
    fireEvent.change(smoothness, { target: { value: "70" } });
    expect(smoothness).toHaveValue("70");
    expect(screen.queryByText("Tune")).not.toBeInTheDocument();

    const variant = screen.getByRole("button", { name: /Altitude transition/i });
    fireEvent.click(variant);
    expect(screen.queryByRole("option", { name: /Wind shift/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Eligible")).not.toBeInTheDocument();
    expect(screen.queryByText("Planner-retimed baseline")).not.toBeInTheDocument();
  });

  it("configures the bottom dock run mode without starting from the workspace", async () => {
    const value = campaignCase();
    const onActiveCaseChange = vi.fn();
    const onCampaignRunChange = vi.fn();
    const onExecutionModeChange = vi.fn();
    let workspace: CampaignWorkspaceView = { runs: [], reviews: [] };
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
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
    expect(await screen.findByText("Move return · Realtime · No review")).toBeVisible();
    expect(screen.getByRole("button", { name: `Copy mission case ID ${value.case_id}` }))
      .toHaveTextContent(value.case_id);
    fireEvent.click(await screen.findByRole("button", { name: /Canonical nominal.*Not started/i }));
    fireEvent.click(screen.getByRole("option", { name: /Not started.*Canonical nominal/i }));
    await waitFor(() => expect(onActiveCaseChange).toHaveBeenCalledWith(value));

    fireEvent.click(screen.getByRole("tab", { name: "Active run" }));
    expect(screen.getByText("Move return · Realtime · No review")).toBeVisible();
    const realtime = screen.getByRole("radio", { name: "Realtime" });
    expect(realtime).toHaveAttribute("aria-checked", "true");
    expect(realtime).toHaveClass("mode-realtime");
    await waitFor(() => expect(onExecutionModeChange).toHaveBeenLastCalledWith("OPERATOR_OBSERVED_REALTIME"));

    const accelerated = screen.getByRole("radio", { name: "Accelerated" });
    fireEvent.click(accelerated);
    await waitFor(() => expect(onExecutionModeChange).toHaveBeenLastCalledWith("AUTOMATED_ACCELERATED"));
    expect(accelerated).toHaveAttribute("aria-checked", "true");
    expect(accelerated).toHaveClass("mode-accelerated");
    expect(screen.getByText("Move return · Accelerated · No review")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Start (realtime|accelerated)/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Same inputs" })).not.toBeInTheDocument();
    expect(api.runActiveCampaign).not.toHaveBeenCalled();
    expect(onCampaignRunChange).toHaveBeenLastCalledWith(undefined);
  });

  it("restores the selected execution mode from campaign workspace preferences", async () => {
    const value = campaignCase();
    window.localStorage.setItem("crazyswarm.campaign-workspace.v1", JSON.stringify({
      runMode: "AUTOMATED_ACCELERATED",
    }));
    const onExecutionModeChange = vi.fn();
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
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

  it("replaces a failed workspace load with an actionable retry", async () => {
    const value = campaignCase();
    const campaignCatalog = vi.fn()
      .mockRejectedValueOnce(new Error("catalog reconciliation failed"))
      .mockResolvedValue({ cases: [value], hierarchy: {} });
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog,
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Campaign workspace unavailable: catalog reconciliation failed",
    );
    expect(screen.queryByText("Loading campaign workspace")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Move return · Realtime · No review")).toBeVisible();
    expect(campaignCatalog).toHaveBeenCalledTimes(2);
  });

  it("renders explicit loading and empty catalog states", async () => {
    let resolveCatalog: ((value: { cases: CampaignCaseView[]; hierarchy: object }) => void) | undefined;
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(() => new Promise<{ cases: CampaignCaseView[]; hierarchy: object }>((resolve) => {
        resolveCatalog = resolve;
      })),
      campaignState: vi.fn(async () => ({ runs: [], reviews: [] })),
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));
    expect(screen.getByText("Loading campaign workspace")).toBeVisible();

    resolveCatalog?.({ cases: [], hierarchy: {} });
    expect(await screen.findByText("Select a mission case")).toBeVisible();
  });

  it("shows every run for the active campaign and saves per-run observation logs", async () => {
    const value = campaignCase({
      case_id: "1d.altitude_transition.canonical_nominal",
      family: "altitude_transition",
      lifecycle: "ACTIVE_DEVELOPMENT",
    });
    const lockedInputs = {
      case_id: value.case_id,
      case_sha256: value.case_sha256,
      seed: 42,
      backend_profile_id: "fast-sim-v1",
      configuration_sha256: "0".repeat(64),
      planner_implementation_id: "bounded-joint-planner",
      planner_implementation_version: "1.0.0",
      planner_settings_sha256: "1".repeat(64),
    };
    const workspace: CampaignWorkspaceView = {
      active_case_id: value.case_id,
      runs: [
        {
          run_id: "campaign-run-1",
          mode: "OPERATOR_OBSERVED_REALTIME",
          status: "SUCCEEDED",
          locked_inputs: {
            ...lockedInputs,
            planner_implementation_version: "0.9.0",
          },
          requested_at_utc: "2026-08-10T14:00:00Z",
          finished_at_utc: "2026-08-10T14:00:16Z",
          mission_execution_id: "campaign-run-1",
        },
        {
          run_id: "campaign-run-2",
          mode: "AUTOMATED_ACCELERATED",
          status: "SUCCEEDED",
          locked_inputs: lockedInputs,
          requested_at_utc: "2026-08-10T15:00:00Z",
          finished_at_utc: "2026-08-10T15:00:16Z",
          mission_execution_id: "campaign-run-2",
        },
      ],
      snapshots: [
        {
          snapshot_id: "snapshot-2-1",
          run_id: "campaign-run-2",
          captured_at_utc: "2026-08-10T15:00:08Z",
          content_type: "image/webp",
          filename: "snapshot-2-1.webp",
          size_bytes: 42_000,
          sha256: "2".repeat(64),
          width_px: 960,
          height_px: 540,
          image_available: true,
        },
      ],
      reviews: [
        {
          review_id: "review-1",
          run_id: "campaign-run-1",
          case_id: value.case_id,
          status: "SUCCEEDED",
          operator_questions: ["Was run one smooth?"],
          operator_observations: ["Slight pause before descent."],
          analysis: {
            mission_execution_id: "campaign-run-1",
            mission_outcome: "SUCCEEDED",
            telemetry_row_count: 1200,
            primary_cause: { stage: "UNKNOWN", confidence: 1, reason: "Run one completed." },
          },
        },
        {
          review_id: "review-2",
          run_id: "campaign-run-2",
          case_id: value.case_id,
          status: "SUCCEEDED",
          operator_questions: ["Was run two smooth?"],
          operator_observations: [],
          analysis: {
            mission_execution_id: "campaign-run-2",
            mission_outcome: "SUCCEEDED",
            telemetry_row_count: 1474,
            primary_cause: { stage: "UNKNOWN", confidence: 1, reason: "Run two completed." },
            vehicles: [{
              vehicle_id: "Beta",
              kinematics_gate_reconciliation: {
                raw_horizontal_speed_peak_m_s: 0.22,
                raw_vertical_speed_peak_m_s: 0.741,
                processed_horizontal_speed_peak_m_s: 0.20,
                processed_vertical_speed_peak_m_s: 0.012,
                maximum_horizontal_speed_m_s: 0.5,
                maximum_vertical_speed_m_s: 0.3,
                raw_gate_passed: false,
                processed_gate_passed: true,
                gate_disagreement: true,
              },
            }],
            landing: [{
              vehicle_id: "Beta",
              accepted_landing_center_m: { x: 1, y: -0.4, z: 0 },
              planned_arrival_m: { x: 1, y: -0.4, z: 0.08 },
              estimated_touchdown_m: { x: 1.01, y: -0.4, z: 0.01 },
              truth_touchdown_m: { x: 1, y: -0.4, z: 0 },
              displayed_goal_marker_m: { x: 1, y: -0.4, z: 0 },
              coordinate_conversion_chain: ["role Beta", "world"],
            }],
          },
        },
      ],
    };
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(async () => ({ cases: [value], hierarchy: {} })),
      campaignState: vi.fn(async () => workspace),
      campaignTelemetryCsvUrl: vi.fn((missionExecutionId: string) => `/control-api/api/v1/run-files/${missionExecutionId}/telemetry.csv`),
      campaignTelemetryCharts: vi.fn(async () => ({
        rowCount: 6,
        durationS: 16,
        vehicles: [{
          vehicleId: "Alpha",
          sampleCount: 6,
          altitudeSource: "Ground truth" as const,
          motorSource: "Applied PWM" as const,
          samples: [
            { timeS: 0, speedMS: 0, altitudeM: 0, motorPercent: { m1: 0, m2: 0, m3: 0, m4: 0 }, attitudeDeg: { x: 0, y: 0, z: 0 }, accelerationMS2: { x: 0, y: 0, z: 9.81 }, angularVelocityRadS: { x: 0, y: 0, z: 0 } },
            { timeS: 8, speedMS: 0.35, altitudeM: 0.6, motorPercent: { m1: 52, m2: 51, m3: 53, m4: 52 }, attitudeDeg: { x: 2, y: -3, z: 6 }, accelerationMS2: { x: 0.2, y: -0.1, z: 9.7 }, angularVelocityRadS: { x: 0.1, y: -0.2, z: 0.3 } },
            { timeS: 16, speedMS: 0, altitudeM: 0, motorPercent: { m1: 0, m2: 0, m3: 0, m4: 0 }, attitudeDeg: { x: 0, y: 0, z: 0 }, accelerationMS2: { x: 0, y: 0, z: 9.81 }, angularVelocityRadS: { x: 0, y: 0, z: 0 } },
          ],
        }],
      })),
      addCampaignObservation: vi.fn(async () => ({})),
      deleteCampaignRun: vi.fn(async () => undefined),
      campaignSnapshotImageUrl: vi.fn((snapshotId: string) => `/control-api/api/v1/campaign/snapshots/${snapshotId}/image`),
      updateCampaignSnapshotComment: vi.fn(async () => ({})),
      updateCampaignSnapshotAssessment: vi.fn(async (
        _snapshotId: string,
        assessment: string,
        disposition: string,
      ) => {
        workspace.snapshots![0] = {
          ...workspace.snapshots![0],
          neutral_assessment: assessment,
          assessment_disposition: disposition as "VALID",
          assessment_confidence: 0.8,
          assessment_evidence_refs: [],
          assessed_at_utc: "2026-08-10T16:00:00Z",
        };
        return workspace.snapshots![0];
      }),
      previewActiveCampaign: vi.fn(async () => ({})),
      setCampaignCaseLifecycle: vi.fn(async () => ({})),
    } as unknown as ControlApi;
    const onCampaignRunChange = vi.fn();

    render(
      <CampaignLab
        api={api}
        onNotice={vi.fn()}
        onCampaignRunChange={onCampaignRunChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));
    fireEvent.click(await screen.findByRole("tab", { name: "Review" }));

    expect(screen.getByRole("button", { name: /Run 2.*Succeeded/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /Run 1.*Succeeded/i })).toBeVisible();
    expect(screen.queryByText("Previous implementation iterations")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Download telemetry CSV for run/i })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: /Delete run \d/i })).toHaveLength(2);
    expect(screen.getByText(/1,474 rows/)).toBeVisible();
    expect(await screen.findByText("Flight graphs")).toBeVisible();
    expect(screen.getByRole("img", { name: /Speed over 16.0 seconds/i })).toBeVisible();
    expect(screen.getByRole("img", { name: /World Z over 16.0 seconds/i })).toBeVisible();
    expect(screen.getByRole("img", { name: /Motor output over 16.0 seconds/i })).toBeVisible();
    expect(screen.getByRole("img", { name: /Attitude over 16.0 seconds/i })).toBeVisible();
    expect(screen.getByRole("img", { name: /Acceleration over 16.0 seconds/i })).toBeVisible();
    expect(screen.getByRole("img", { name: /Angular velocity over 16.0 seconds/i })).toBeVisible();
    expect(screen.getByText(/Beta kinematics · GATE DISAGREEMENT/i)).not.toBeVisible();
    fireEvent.click(screen.getByText("Evidence details"));
    expect(screen.getByText(/Beta kinematics · GATE DISAGREEMENT/i)).toBeVisible();
    expect(screen.getByText(/Beta role-relative landing target/i)).toBeVisible();
    const speedGraph = screen.getByRole("button", { name: "Expand Speed graph" });
    fireEvent.click(speedGraph);
    expect(screen.getByRole("button", { name: "Collapse Speed graph" })).toHaveAttribute("aria-expanded", "true");
    expect(api.campaignTelemetryCharts).toHaveBeenCalledWith("campaign-run-2");
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Needs rerun" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "In review" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "In review" })).toHaveClass("campaign-action-review");
    expect(screen.getByRole("button", { name: "Completed" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Review snapshot 1 from run 2" }));
    expect(screen.getByRole("dialog", { name: /Aug 10/i })).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "Snapshot comment" }), {
      target: { value: "Altitude correction was visible here." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save snapshot comment" }));
    await waitFor(() => expect(api.updateCampaignSnapshotComment).toHaveBeenCalledWith(
      "snapshot-2-1",
      "Altitude correction was visible here.",
    ));
    fireEvent.change(screen.getByRole("textbox", { name: "Neutral snapshot evidence assessment" }), {
      target: { value: "The source-time frame supports the visible altitude correction." },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Neutral assessment disposition" }), {
      target: { value: "VALID" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save neutral assessment" }));
    await waitFor(() => expect(api.updateCampaignSnapshotAssessment).toHaveBeenCalledWith(
      "snapshot-2-1",
      "The source-time frame supports the visible altitude correction.",
      "VALID",
      0.8,
      [],
    ));
    fireEvent.click(screen.getByRole("button", { name: "Close snapshot review" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "In review" })).toBeEnabled());

    fireEvent.change(screen.getByRole("textbox", { name: "Operator comment for run 2" }), {
      target: { value: "Second run stayed smooth." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Run 1.*Succeeded/i }));
    expect(screen.getByText("Slight pause before descent.")).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "Operator comment for run 1" }), {
      target: { value: "First-run follow-up." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Run 2.*Succeeded/i }));
    expect(screen.getByRole("textbox", { name: "Operator comment for run 2" })).toHaveValue("Second run stayed smooth.");
    fireEvent.click(screen.getByRole("button", { name: "Save comment" }));

    await waitFor(() => expect(api.addCampaignObservation).toHaveBeenCalledWith(
      "review-2",
      "Second run stayed smooth.",
    ));
    fireEvent.click(screen.getByRole("button", { name: "Delete run 2" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(api.deleteCampaignRun).toHaveBeenCalledWith("campaign-run-2"));
    await waitFor(() => expect(onCampaignRunChange).toHaveBeenCalledWith(workspace.runs[1]));
    fireEvent.click(screen.getByRole("button", { name: "In review" }));
    await waitFor(() => expect(api.setCampaignCaseLifecycle).toHaveBeenCalledWith(
      value.case_id,
      "BASELINED",
      "operator marked mission as in review",
    ));
  });

  it("switches between independent case journals without hiding earlier run evidence", async () => {
    const canonical = campaignCase({
      case_id: "1d.altitude_transition.canonical_nominal",
      family: "altitude_transition",
      variation_name: "canonical_nominal",
      lifecycle: "ACTIVE_DEVELOPMENT",
    });
    const wide = campaignCase({
      case_id: "1d.altitude_transition.wide",
      case_sha256: "b".repeat(64),
      family: "altitude_transition",
      variation_name: "wide",
      lifecycle: "ACTIVE_DEVELOPMENT",
    });
    const lockedInputs = (value: CampaignCaseView) => ({
      case_id: value.case_id,
      case_sha256: value.case_sha256,
      seed: 42,
      backend_profile_id: "fast-sim-v1",
      configuration_sha256: "0".repeat(64),
      planner_implementation_id: "bounded-joint-planner",
      planner_implementation_version: "1.0.0",
      planner_settings_sha256: "1".repeat(64),
    });
    const workspace: CampaignWorkspaceView = {
      active_case_id: wide.case_id,
      runs: [canonical, wide].map((value, index) => ({
        run_id: `run-${index + 1}`,
        mode: "OPERATOR_OBSERVED_REALTIME",
        status: "SUCCEEDED",
        locked_inputs: lockedInputs(value),
        requested_at_utc: `2026-08-10T1${index}:00:00Z`,
        finished_at_utc: `2026-08-10T1${index}:00:10Z`,
      })),
      reviews: [canonical, wide].map((value, index) => ({
        review_id: `review-${index + 1}`,
        run_id: `run-${index + 1}`,
        case_id: value.case_id,
        status: "SUCCEEDED",
        operator_questions: [],
        operator_observations: index === 0 ? ["Canonical observation retained."] : [],
        analysis: {
          mission_execution_id: `run-${index + 1}`,
          mission_outcome: "SUCCEEDED",
          telemetry_row_count: 100 + index,
          primary_cause: {
            stage: "UNKNOWN",
            confidence: 1,
            reason: index === 0 ? "Canonical evidence." : "Wide evidence.",
          },
        },
      })),
    };
    const api = {
      campaignQualificationUrl: vi.fn(
        () => "/control-api/api/v1/campaign/qualification/export",
      ),
      campaignCatalog: vi.fn(async () => ({ cases: [canonical, wide], hierarchy: {} })),
      campaignState: vi.fn(async () => workspace),
      campaignTelemetryCsvUrl: vi.fn(() => "#"),
      campaignSnapshotImageUrl: vi.fn(() => "#"),
    } as unknown as ControlApi;

    render(<CampaignLab api={api} onNotice={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Campaign laboratory/i }));
    fireEvent.click(await screen.findByRole("tab", { name: "Review" }));

    expect(screen.getByText("Wide evidence.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Altitude transition.*Wide.*1 run/i }));
    fireEvent.click(screen.getByRole("option", { name: /Canonical nominal.*1 run/i }));

    expect(screen.getByText("Canonical evidence.")).toBeVisible();
    expect(screen.getByText("Canonical observation retained.")).toBeVisible();
  });
});
