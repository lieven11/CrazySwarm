import axe from "axe-core";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { deterministicDashboard } from "../app/lib/fixtures";
import { FixtureGallery } from "../app/components/FixtureGallery";
import { appendObservedTracePoint, armActionEnabled, campaignDockModePresentation, campaignMissionFilename, campaignReferencePlan, campaignScenePreview, ControlCenter, controlActionsEnabled, DeploymentSummary, LowBatterySimulationDialog, missionCompletionNotice, missionIdForRunningReference, missionPreviewControlVehicles, missionPreviewHomeBases, missionSceneHomeBases, MissionPlanReview, ModeBadge, OBSERVED_TRACE_HISTORY_LIMIT, SafetyDialog, shouldDisplayHistoricalPath, simulationBatteryControlEnabled, simulationBatteryStartRisk, Toast, toggleVehicleSelection, TOAST_DURATION_MS, TOAST_FAILURE_DURATION_MS, vehiclesForTargetSelection, withObservationFocus, withVehicleTargetSelection } from "../app/components/ControlCenter";
import { campaignMissionPreview } from "../app/lib/campaign-preview";
import { formatClockContext } from "../app/components/RoomScene";
import { FlightReadout, RunFilesControl, telemetrySample } from "../app/components/TelemetryDock";
import type { CampaignCaseView, FleetSessionView, MissionPreview } from "../app/lib/models";

describe("operator components", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("maps the persisted campaign mode to the bottom Play label and color", () => {
    expect(campaignDockModePresentation("AUTOMATED_ACCELERATED")).toEqual({
      label: "Accelerated",
      actionLabel: "accelerated",
      buttonClassName: "campaign-mode-accelerated",
    });
    expect(campaignDockModePresentation("OPERATOR_OBSERVED_REALTIME")).toEqual({
      label: "Realtime",
      actionLabel: "realtime",
      buttonClassName: "",
    });
  });

  it("retains six minutes of observed trace points in FIFO order", () => {
    const points = Array.from({ length: OBSERVED_TRACE_HISTORY_LIMIT }, (_, index) => ({
      x: index,
      y: 0,
      z: 0.3,
    }));

    const retained = appendObservedTracePoint(points, {
      x: OBSERVED_TRACE_HISTORY_LIMIT,
      y: 0,
      z: 0.3,
    });

    expect(retained).toHaveLength(OBSERVED_TRACE_HISTORY_LIMIT);
    expect(retained[0]?.x).toBe(1);
    expect(retained.at(-1)?.x).toBe(OBSERVED_TRACE_HISTORY_LIMIT);
  });

  it("uses the runtime Python filename for the active campaign mission", () => {
    expect(campaignMissionFilename({
      case_id: "three_drone_multi_conflict",
    } as CampaignCaseView)).toBe("campaign_three_drone_multi_conflict.py");
  });

  it("adapts a campaign plan into the shared mission preview scene", () => {
    const campaignCase = {
      case_id: "1d.altitude_transition.canonical_nominal",
      case_sha256: "a".repeat(64),
      purpose: "Preview one altitude transition drone",
      expected_outcome: "The route completes",
      environment: "SIMULATION",
      allowed_strategies: ["DIRECT"],
    } as CampaignCaseView;
    const preview = campaignMissionPreview(campaignCase, {
      plan: {
        status: "READY",
        planner_id: "bounded-planner",
        planner_version: "1.0.0",
        plan_sha256: "b".repeat(64),
        selected_candidate_index: 0,
        retained_candidates: [{
          predicted_battery_end_percent: { Alpha: 96 },
          routes: [{
            role_id: "Alpha",
            route_duration_s: 12,
            points_m: [
              { x: -1.5, y: 0, z: 0.3 },
              { x: 1.5, y: 0, z: 0.3 },
            ],
          }],
        }],
      },
      schedule: {
        schedule_sha256: "c".repeat(64),
        source_schedule_duration_s: 16,
        roles: [{ role_id: "Alpha", energy: { route_energy_percent: 4 } }],
      },
    });

    expect(preview).toMatchObject({
      missionId: "campaign:1d.altitude_transition.canonical_nominal",
      plan: { status: "APPROVED" },
      vehicles: [{
        vehicleId: "Alpha",
        home: { x: -1.5, y: 0, z: 0 },
        start: { x: -1.5, y: 0, z: 0 },
        batteryPercent: 96,
      }],
    });
    expect(preview?.vehicles[0]?.plannedCommands.map((command) => command.action)).toEqual([
      "takeoff",
      "move_relative",
      "land",
    ]);
    expect(campaignReferencePlan(campaignCase, preview)).toBe(preview);
    expect(shouldDisplayHistoricalPath(undefined, campaignCase, undefined)).toBe(false);
    expect(shouldDisplayHistoricalPath(undefined, campaignCase, {
      run_id: "campaign-run-1",
      mode: "OPERATOR_OBSERVED_REALTIME",
      status: "RUNNING",
    })).toBe(true);
    expect(shouldDisplayHistoricalPath(preview, undefined, undefined)).toBe(false);
    expect(shouldDisplayHistoricalPath(preview, undefined, undefined, true)).toBe(true);
    expect(shouldDisplayHistoricalPath(preview, campaignCase, {
      run_id: "campaign-run-1",
      mode: "OPERATOR_OBSERVED_REALTIME",
      status: "SUCCEEDED",
    }, true)).toBe(true);
    expect(campaignScenePreview(preview, {
      run_id: "campaign-run-1",
      mode: "OPERATOR_OBSERVED_REALTIME",
      status: "SUCCEEDED",
    })).toBeUndefined();
    expect(campaignScenePreview(preview, undefined)).toBe(preview);
  });

  it("dismisses status banners automatically after a few seconds", () => {
    vi.useFakeTimers();
    const close = vi.fn();
    const { unmount } = render(<Toast message="Mission succeeded" onClose={close} />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Mission succeeded");
    expect(status.parentElement).toBe(document.body);
    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS - 1));
    expect(close).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(close).toHaveBeenCalledOnce();
    unmount();
  });

  it("shows the authoritative reason when a mission fails", () => {
    vi.useFakeTimers();
    const close = vi.fn();
    const message = missionCompletionNotice(
      "FAILED",
      "modeled battery reached authoritative cutoff",
      "CRITICAL_BATTERY",
    );
    const { unmount } = render(<Toast message={message} onClose={close} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Mission failed");
    expect(alert).toHaveTextContent("Reason: Critical battery — Modeled battery reached authoritative cutoff");
    act(() => vi.advanceTimersByTime(TOAST_FAILURE_DURATION_MS - 1));
    expect(close).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(close).toHaveBeenCalledOnce();
    unmount();
  });

  it("shows execution cancellation as a temporary operation notice", () => {
    vi.useFakeTimers();
    const close = vi.fn();
    const message = missionCompletionNotice(
      "ABORTED",
      "execution cancellation completed with bounded fleet cleanup",
      "EXECUTION_CANCELLED",
    );
    const { unmount } = render(<Toast message={message} onClose={close} />);

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Execution cancelled");
    expect(notice).toHaveTextContent("Execution cancellation completed with bounded fleet cleanup");
    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS));
    expect(close).toHaveBeenCalledOnce();
    unmount();
  });

  it.each(["SIM", "LIVE", "SHADOW", "REPLAY"] as const)("labels %s mode in text", (mode) => {
    render(<ModeBadge mode={mode} />);
    expect(screen.getByLabelText(`Mode: ${mode}`)).toHaveTextContent(mode);
  });

  it("binds reference geometry only to the active mission", () => {
    const fleet = {
      runId: "run-active",
      missionId: "mission-active",
    } as FleetSessionView;

    expect(missionIdForRunningReference(
      "run-active",
      fleet,
      false,
      {
        id: "run-other",
        missionId: "mission-other",
        vehicleId: "other",
        phase: "RUNNING",
        status: "RUNNING",
        parameters: {},
      },
      { missionId: "mission-stale", runId: "run-stale" },
    )).toBe("mission-active");

    expect(missionIdForRunningReference(
      "run-active",
      undefined,
      false,
      {
        id: "run-active",
        missionId: "mission-active",
        vehicleId: "active",
        phase: "RUNNING",
        status: "RUNNING",
        parameters: {},
      },
      undefined,
    )).toBe("mission-active");

    expect(missionIdForRunningReference(
      "run-active",
      undefined,
      false,
      undefined,
      { missionId: "mission-stale", runId: "run-stale" },
    )).toBeUndefined();
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

  it("explains and confirms the simulation-only low-battery risk", () => {
    const confirm = vi.fn();
    render(
      <LowBatterySimulationDialog
        batteryPercent={5}
        minimumPercent={30}
        criticalPercent={10}
        starting={false}
        onClose={vi.fn()}
        onConfirm={confirm}
      />,
    );

    const warning = screen.getByRole("alertdialog", { name: "5% battery · run anyway?" });
    expect(warning).toBeVisible();
    expect(warning.closest(".dialog-backdrop")).toBeNull();
    expect(screen.getByText(/10% critical threshold/)).toBeVisible();
    expect(screen.getByText(/all other safety checks stay active/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Run anyway" }));
    expect(confirm).toHaveBeenCalledOnce();
  });

  it("uses a mission-specific battery minimum for simulation confirmation", () => {
    const preview: MissionPreview = {
      missionId: "coverage",
      sourceSha256: "abc123",
      plan: {
        id: "plan-coverage", sha256: "plan-hash", safetyCaseSha256: "safety-hash",
        status: "APPROVED", objective: "Coverage", plugins: [], phases: [], routes: [], findings: [],
      },
      vehicles: [{
        roleId: "zone-a",
        vehicleId: "coverage-a",
        displayName: "Coverage A",
        initialRole: "ACTIVE",
        home: { x: 0, y: 0, z: 0 },
        start: { x: 0, y: 0, z: 0 },
        batteryPercent: 50,
        minimumBatteryPercent: 55,
        existingVehicle: true,
        previewFidelity: "EXACT_ROLE",
        plannedCommands: [],
      }],
    };

    expect(simulationBatteryStartRisk(preview, [], undefined, 30)).toEqual({
      batteryPercent: 50,
      minimumPercent: 55,
      minimumKind: "mission",
      vehicleId: "coverage-a",
      affectedVehicleCount: 1,
    });
  });

  it("separates mission plan blockers from confirmable risks", () => {
    const preview: MissionPreview = {
      missionId: "review",
      sourceSha256: "source-hash",
      plan: {
        id: "plan-review",
        sha256: "plan-hash",
        safetyCaseSha256: "safety-hash",
        status: "BLOCKED",
        objective: "Review the exact route before Play",
        plugins: [{
          id: "route.direct",
          kind: "ROUTE_PLANNER",
          version: "1.0.0",
          capabilities: ["DIRECT"],
          manifestSha256: "manifest-hash",
        }],
        phases: [],
        routes: [{
          roleId: "survey",
          status: "BLOCKED",
          durationS: 16.5,
          energyPercent: 2.8,
          lengthM: 2.75,
          waypointCount: 3,
          findings: [],
        }],
        findings: [{
          code: "ROUTE_OUTSIDE_FLIGHT_VOLUME",
          severity: "BLOCKER",
          message: "Route exceeds the configured volume",
          roleId: "survey",
          requiresConfirmation: false,
        }, {
          code: "BATTERY_BELOW_PLANNED_REQUIREMENT",
          severity: "WARNING",
          message: "Battery is below the planned requirement",
          roleId: "survey",
          requiresConfirmation: true,
        }],
      },
      vehicles: [{
        roleId: "survey",
        vehicleId: "drone-1",
        displayName: "Drone 1",
        initialRole: "ACTIVE",
        home: { x: 0, y: 0, z: 0 },
        start: { x: 0, y: 0, z: 0 },
        existingVehicle: true,
        previewFidelity: "EXACT_ROLE",
        plannedCommands: [],
      }],
    };

    render(<MissionPlanReview preview={preview} />);

    expect(screen.getByText("BLOCKED")).toBeVisible();
    expect(screen.getByText("Blockers")).toBeVisible();
    expect(screen.getByText("Confirm before Play")).toBeVisible();
    expect(screen.getByText("ROUTE_OUTSIDE_FLIGHT_VOLUME · survey")).toBeVisible();
    expect(screen.getByText("Planned energy")).toBeVisible();
    expect(screen.getAllByText("2.8%")).toHaveLength(2);
    expect(screen.getByText("Start")).toBeVisible();
    expect(screen.getByText("Home")).toBeVisible();
    const routeCard = screen.getByText("Drone 1").closest("article");
    expect(routeCard).not.toBeNull();
    expect(within(routeCard!).queryByText("survey")).not.toBeInTheDocument();
    expect(screen.queryByText("Plan overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Review the exact route before Play")).not.toBeInTheDocument();
    expect(screen.queryByText("plan-hash")).not.toBeInTheDocument();
    expect(screen.queryByText("safety-hash")).not.toBeInTheDocument();
    expect(screen.queryByText("route.direct")).not.toBeInTheDocument();
  });

  it("places a single-drone center pad at the mission's actual start", () => {
    const preview: MissionPreview = {
      missionId: "move-return",
      sourceSha256: "abc123",
      plan: {
        id: "plan-move", sha256: "plan-hash", safetyCaseSha256: "safety-hash",
        status: "APPROVED", objective: "Move", plugins: [], phases: [], routes: [], findings: [],
      },
      vehicles: [{
        roleId: "primary",
        vehicleId: "sim01",
        displayName: "Simulator",
        initialRole: "ACTIVE",
        home: { x: 0, y: 0, z: 0 },
        start: { x: 0.85, y: -0.35, z: 0 },
        existingVehicle: true,
        previewFidelity: "EXACT_ROLE",
        plannedCommands: [],
      }],
    };

    expect(missionPreviewHomeBases(preview)).toEqual([{
      vehicleId: "sim01",
      number: 1,
      position: preview.vehicles[0]!.start,
    }]);
    const retainedBases = [{
      vehicleId: "sim01",
      number: 1,
      position: { x: 0.85, y: -0.35, z: 0 },
    }];
    expect(missionSceneHomeBases(undefined, retainedBases, undefined, undefined)).toBe(retainedBases);
    expect(missionSceneHomeBases(preview, retainedBases, undefined, undefined)).toBe(retainedBases);
  });

  it("limits campaign setup controls to the newly selected mission roster", () => {
    const alpha = {
      ...structuredClone(deterministicDashboard.vehicles[0]!),
      id: "Alpha",
      name: "Alpha",
      backendRole: "FAST_SIM" as const,
      state: "DISCONNECTED",
    };
    const staleFromPreviousMission = {
      ...structuredClone(alpha),
      id: "Bravo",
      name: "Bravo",
    };
    const preview: MissionPreview = {
      missionId: "campaign:1d.altitude_transition.canonical_nominal",
      sourceSha256: "campaign-source",
      plan: {
        id: "campaign-plan", sha256: "campaign-plan-hash", safetyCaseSha256: "safety-hash",
        status: "APPROVED", objective: "Altitude transition", plugins: [], phases: [], routes: [], findings: [],
      },
      vehicles: [{
        roleId: "Alpha",
        vehicleId: "Alpha",
        displayName: "Alpha",
        initialRole: "ACTIVE",
        home: { x: -1.2, y: 0, z: 0 },
        start: { x: -1.2, y: 0, z: 0 },
        existingVehicle: false,
        backendRole: "FAST_SIM",
        previewFidelity: "EXACT_ROLE",
        plannedCommands: [],
      }],
    };

    expect(missionPreviewControlVehicles(preview, [alpha, staleFromPreviousMission]))
      .toEqual([expect.objectContaining({ id: "Alpha", state: "DISCONNECTED" })]);
  });

  it("keeps flight actions disabled without API, lease, and armed state", () => {
    const vehicle = deterministicDashboard.vehicles[0];
    expect(controlActionsEnabled(deterministicDashboard, vehicle)).toBe(false);
    expect(controlActionsEnabled({ ...deterministicDashboard, apiConnected: true }, { ...vehicle, commandAuthority: false })).toBe(false);
    expect(controlActionsEnabled({ ...deterministicDashboard, apiConnected: true }, { ...vehicle, telemetry: vehicle.telemetry ? { ...vehicle.telemetry, armed: false } : undefined })).toBe(false);
    expect(controlActionsEnabled({ ...deterministicDashboard, apiConnected: true }, { ...vehicle, commandAuthority: true })).toBe(true);
  });

  it("allows a safely stopped Fast Sim drone to recover from a battery abort", () => {
    const vehicle = deterministicDashboard.vehicles[0];
    const depleted = {
      ...vehicle,
      backendRole: "FAST_SIM" as const,
      state: "ABORTING",
      armed: false,
      flying: false,
    };

    expect(simulationBatteryControlEnabled(depleted)).toBe(true);
    expect(simulationBatteryControlEnabled({ ...depleted, flying: true })).toBe(false);
    expect(simulationBatteryControlEnabled(depleted, true)).toBe(false);
  });

  it("keeps fleet observation local while exposing handover ownership evidence", () => {
    const left = { ...deterministicDashboard.vehicles[0], id: "drone-left", name: "drone-left", selected: true };
    const right = {
      ...deterministicDashboard.vehicles[0],
      id: "drone-right",
      name: "drone-right",
      selected: false,
      telemetry: deterministicDashboard.vehicles[0].telemetry
        ? { ...deterministicDashboard.vehicles[0].telemetry, batteryPercent: 87 }
        : undefined,
    };
    const fleet: FleetSessionView = {
      id: "execution-1",
      deploymentId: "deployment-1",
      backend: "FAST_SIM",
      status: "CLOSED",
      runId: "run-1",
      runStatus: "SUCCEEDED",
      vehicles: [left, right].map((vehicle) => ({
        id: vehicle.id,
        registration: "VERIFIED",
        connection: "DISCONNECTED",
        missionRole: "ACTIVE",
        observation: "COMPLETED_SNAPSHOT",
        preflightApproved: false,
        readinessSamples: 1,
        readinessReason: "TERMINAL_SNAPSHOT",
      })),
      tasks: [{
        id: "cover-zone-a",
        zoneId: "zone-a",
        priority: 200,
        state: "COMPLETED",
        ownerVehicleId: "drone-right",
        progressPercent: 100,
        leaseGeneration: 2,
      }],
      vehicleStates: { "drone-left": "RETURNING", "drone-right": "ACTIVE" },
      handovers: [{
        id: "handover-cover-zone-a-2",
        taskId: "cover-zone-a",
        outgoingVehicleId: "drone-left",
        incomingVehicleId: "drone-right",
        phase: "COMPLETED",
        incomingLeaseGeneration: 2,
        takeoverConfirmed: true,
        reason: "LOW_ENERGY_MARGIN",
      }],
      docks: [{
        id: "dock-a",
        health: "AVAILABLE",
        reservations: [{
          vehicleId: "drone-left",
          state: "READY",
          modeledChargingConfirmed: true,
        }],
      }],
      minimumSeparationM: .91,
      warningViolations: 0,
      criticalViolations: 0,
      authorityTransitionCount: 2,
      warningSeparationM: .75,
      criticalSeparationM: .5,
      missionDerived: true,
      createdAtMonotonicS: 1,
      resultReasonCode: "EXECUTION_CANCELLED",
      resultMessage: "execution cancellation completed with bounded fleet cleanup",
    };
    const onSelect = vi.fn();
    render(<DeploymentSummary fleet={fleet} vehicles={[left, right]} selectedVehicleIds={["drone-right"]} onSelect={onSelect} />);

    const panel = screen.getByRole("region", { name: "Mission deployment status" });
    const selected = within(panel).getByRole("button", { name: "Toggle drone-right command selection · battery 87%" });
    expect(selected).toHaveAttribute("aria-pressed", "true");
    expect(selected).toHaveClass("is-selected");
    expect(within(panel).getByText("SUCCEEDED")).toBeInTheDocument();
    expect(within(panel).queryByText("drone-right · gen 2")).not.toBeInTheDocument();
    expect(within(panel).queryByText("Minimum separation")).not.toBeInTheDocument();
    expect(within(panel).queryByText("drone-left → drone-right")).not.toBeInTheDocument();

    const disclosure = within(panel).getByRole("button", { name: "Expand mission deployment details" });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(disclosure);
    expect(within(panel).getByText("drone-left → drone-right")).toBeInTheDocument();
    expect(within(panel).getByText("0.91 m")).toBeInTheDocument();
    expect(within(panel).getByText("dock-a · drone-left")).toBeInTheDocument();
    expect(within(panel).queryByText(/execution cancellation/i)).not.toBeInTheDocument();
    expect(within(panel).queryByText(/FAST_SIM|Automatic allocation/)).not.toBeInTheDocument();
    const separation = within(panel).getByText("Minimum separation").closest(".deployment-separation");
    expect(separation).not.toBeNull();
    expect(separation!.compareDocumentPosition(selected) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(selected);
    expect(onSelect).toHaveBeenCalledWith("drone-right");

    const collapse = within(panel).getByRole("button", { name: "Collapse mission deployment details" });
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(collapse);
    expect(within(panel).getByText("drone-left")).toBeVisible();
    expect(within(panel).getByText("drone-right")).toBeVisible();
    expect(within(panel).queryByText("Minimum separation")).not.toBeInTheDocument();
    expect(within(panel).queryByText("drone-left → drone-right")).not.toBeInTheDocument();
    expect(within(panel).queryByText("dock-a · drone-left")).not.toBeInTheDocument();

    const focused = withObservationFocus(
      { ...deterministicDashboard, vehicles: [left, right] },
      "drone-right",
    );
    expect(focused.selectedVehicleId).toBe("drone-right");
    expect(focused.vehicles.find((vehicle) => vehicle.id === "drone-right")?.selected).toBe(true);
    expect(focused.vehicles.find((vehicle) => vehicle.id === "drone-left")?.selected).toBe(false);
  });

  it("targets all drones when selection is empty and only the toggled subset otherwise", () => {
    const left = { ...deterministicDashboard.vehicles[0], id: "drone-left", selected: true };
    const middle = { ...deterministicDashboard.vehicles[0], id: "drone-middle", selected: false };
    const right = { ...deterministicDashboard.vehicles[0], id: "drone-right", selected: false };
    const vehicles = [left, middle, right];

    expect(vehiclesForTargetSelection(vehicles, []).map((vehicle) => vehicle.id))
      .toEqual(["drone-left", "drone-middle", "drone-right"]);

    let selection = toggleVehicleSelection([], "drone-left");
    selection = toggleVehicleSelection(selection, "drone-right");
    expect(selection).toEqual(["drone-left", "drone-right"]);
    expect(vehiclesForTargetSelection(vehicles, selection).map((vehicle) => vehicle.id))
      .toEqual(["drone-left", "drone-right"]);

    const focused = withVehicleTargetSelection(
      { ...deterministicDashboard, vehicles },
      selection,
    );
    expect(focused.selectedVehicleId).toBeUndefined();
    expect(focused.vehicles.filter((vehicle) => vehicle.selected).map((vehicle) => vehicle.id))
      .toEqual(["drone-left", "drone-right"]);

    selection = toggleVehicleSelection(selection, "drone-left");
    expect(selection).toEqual(["drone-right"]);
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

  it("keeps essential flight data visible and moves detail behind disclosures", () => {
    const baseVehicle = deterministicDashboard.vehicles[0];
    const vehicle = {
      ...baseVehicle,
      telemetry: baseVehicle.telemetry ? {
        ...baseVehicle.telemetry,
        attitude: { rollRad: .12, pitchRad: -.08, yawRad: .45 },
        imu: {
          acceleration: { x: .1, y: -.2, z: .22 },
          angularVelocity: { x: .02, y: 0, z: -.03 },
          provenance: baseVehicle.telemetry.provenance,
        },
      } : undefined,
    };
    render(
      <FlightReadout
        model={deterministicDashboard}
        vehicle={vehicle}
        samples={[
          { t: 1, altitude: 0.2, speed: 0.1, battery: 100, localization: 99, roll: 2, pitch: -3, motorM1: 41, motorM4: 44 },
          { t: 2, altitude: 0.3, speed: 0, battery: 99.4, localization: 98, roll: 4, pitch: -1, motorM1: 46, motorM4: 49 },
        ]}
        expanded
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getAllByText("Battery").length).toBeGreaterThan(0);
    expect(screen.getAllByText("World Z").length).toBeGreaterThan(0);
    expect(screen.getByText("Nearest")).toBeVisible();
    expect(screen.getByRole("img", { name: /Battery/ })).toBeVisible();
    expect(screen.getByRole("img", { name: /Clearance/ })).toBeVisible();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByText(/system health/i)).not.toBeInTheDocument();
    expect(screen.getByText("Systems").closest("details")).toHaveAttribute("open");
    expect(screen.getByRole("group", { name: "Attitude around all axes" })).toBeVisible();
    expect(screen.getByRole("group", { name: /Acceleration on X Y and Z axes/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Attitude" }));
    fireEvent.click(screen.getByRole("button", { name: "Pitch" }));
    expect(screen.getByRole("img", { name: /Pitch from -3.0 to -1.0 ° over 1 seconds/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Motors" }));
    fireEvent.click(screen.getByRole("button", { name: "M4" }));
    expect(screen.getByRole("img", { name: /Motor M4 output from 44 to 49 % over 1 seconds/ })).toBeVisible();
    fireEvent.click(screen.getByText("Evidence"));
    expect(screen.getByText("World volume")).toBeVisible();
    expect(screen.getByText("fixture-run")).toBeVisible();
  });

  it("records attitude, IMU, and every motor in live telemetry history", () => {
    const vehicle = structuredClone(deterministicDashboard.vehicles[0]!);
    vehicle.telemetry = {
      ...vehicle.telemetry!,
      attitude: { rollRad: Math.PI / 6, pitchRad: -Math.PI / 4, yawRad: Math.PI / 2 },
      imu: {
        acceleration: { x: 1, y: -2, z: 3 },
        angularVelocity: { x: .1, y: -.2, z: .3 },
        provenance: vehicle.telemetry!.provenance,
      },
      motors: {
        modelId: "crazyflie-6dof",
        modelVersion: "2.0.0",
        readings: [
          { id: "M1", commandPercent: 41, thrustN: .1, currentA: .2 },
          { id: "M2", commandPercent: 42, thrustN: .1, currentA: .2 },
          { id: "M3", commandPercent: 43, thrustN: .1, currentA: .2 },
          { id: "M4", commandPercent: 44, thrustN: .1, currentA: .2 },
        ],
      },
    };

    const sample = telemetrySample(vehicle);
    expect(sample?.roll).toBeCloseTo(30);
    expect(sample?.pitch).toBeCloseTo(-45);
    expect(sample?.yaw).toBeCloseTo(90);
    expect(sample).toEqual(expect.objectContaining({
      accelerationX: 1,
      accelerationY: -2,
      accelerationZ: 3,
      angularVelocityX: .1,
      angularVelocityY: -.2,
      angularVelocityZ: .3,
      motorM1: 41,
      motorM2: 42,
      motorM3: 43,
      motorM4: 44,
    }));
  });

  it("shows one non-expandable CSV download for each mission", () => {
    const loadRunFiles = vi.fn();
    const deleteRunFiles = vi.fn();
    const props = { onLoad: loadRunFiles, onDelete: deleteRunFiles };
    const { rerender } = render(<RunFilesControl {...props} />);
    const disclosure = screen.getAllByText("Run files")[0].closest("details");
    expect(disclosure).not.toBeNull();
    disclosure!.open = true;
    fireEvent(disclosure!, new Event("toggle"));
    expect(loadRunFiles).toHaveBeenCalledOnce();

    rerender(
      <RunFilesControl
        {...props}
        loaded
        missions={[{
          missionExecutionId: "execution-complete",
          missionId: "hover",
          missionName: "Crossing route separation",
          status: "ABORTED",
          startedAtUtc: "2026-08-08T13:22:43Z",
          telemetryRowCount: 12,
          filename: "crossing-route-separation_execution-complete_telemetry-v1.csv",
          downloadUrl: "/control-api/api/v1/run-files/execution-complete/telemetry.csv",
          available: true,
          sizeBytes: 2560,
          sha256: "abc",
        }]}
      />,
    );

    const filename = "crossing-route-separation_execution-complete_telemetry-v1.csv";
    const download = screen.getByRole("link", { name: `Download ${filename}` });
    expect(download).toHaveAttribute("href", "/control-api/api/v1/run-files/execution-complete/telemetry.csv");
    expect(download).toHaveAttribute("download", filename);
    expect(screen.getByText("12 samples")).toBeVisible();
    expect(screen.getByText("ABORTED")).toBeVisible();
    const missionRow = screen.getByText("Crossing route separation").closest("article");
    expect(missionRow).not.toBeNull();
    expect(missionRow!.querySelector("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Delete Crossing route separation run files" }));
    expect(deleteRunFiles).toHaveBeenCalledWith(expect.objectContaining({
      missionExecutionId: "execution-complete",
    }));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("shows a retry action when previous run files cannot be loaded", () => {
    const retry = vi.fn();
    render(
      <RunFilesControl error="Run files unavailable" onLoad={retry} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Run files unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("exposes only Python upload, the two execution paths, and clickable controls", async () => {
    const json = (value: unknown) => new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/state")) return json({
        mode: "SIM",
        selected_vehicle_id: "sim01",
        configured_flight_volume: null,
        mission_runs: [],
        vehicles: [{
          identity: { vehicle_id: "sim01", display_name: "Simulator", adapter: "sim" },
          backend: { role: "FAST_SIM", authority: "SIMULATION" },
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
      if (url.endsWith("/api/v1/simulation/fleet/reset-poses")) return json({
        vehicle_ids: ["sim01"],
        reset_scope: ["active_fleet", "pose", "motion", "estimator_state"],
      });
      if (url.endsWith("/api/v1/simulation/vehicles/sim01/clock")) {
        const body = JSON.parse(String(init?.body)) as { action: string; battery_percent?: number };
        if (body.action === "reset_pose") return json({
          now_s: 4,
          paused: false,
          speed: 1,
          position_m: { x: 0, y: 0, z: 0 },
          reset_scope: ["pose", "motion", "estimator_state"],
        });
        if (body.action === "recharge") return json({
          now_s: 4,
          paused: false,
          speed: 1,
          battery_percent: body.battery_percent,
          reset_scope: ["battery"],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ControlCenter />);
    const engineering = await screen.findByRole("button", { name: "Engineering" });
    fireEvent.click(screen.getByRole("button", { name: "Mission" }));
    expect(await screen.findByRole("button", { name: "Simulation" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Digital twin" })).toBeDisabled();
    expect(screen.getByText("Add Python")).toBeVisible();
    expect(screen.getByRole("button", { name: "Reposition drone to home" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Recharge battery to 100%" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Choose battery level" })).toBeEnabled();
    expect(screen.queryByText(/mission parameters/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reposition drone to home" }));
    expect(await screen.findByText("Drone repositioned to configured home")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/simulation/fleet/reset-poses"), expect.objectContaining({
      body: JSON.stringify({ vehicle_ids: ["sim01"] }),
    }));
    fireEvent.click(screen.getByRole("button", { name: "Recharge battery to 100%" }));
    expect(await screen.findByText("Battery set to 100.0%")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/simulation/vehicles/sim01/clock"), expect.objectContaining({
      body: JSON.stringify({ action: "recharge", battery_percent: 100 }),
    }));
    fireEvent.click(screen.getByRole("button", { name: "Choose battery level" }));
    expect(screen.getByRole("dialog", { name: "Battery level" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "20%" }));
    expect(await screen.findByText("Battery set to 20.0%")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Choose battery level" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Custom battery percentage" }), { target: { value: "37.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Set" }));
    expect(await screen.findByText("Battery set to 37.5%")).toBeVisible();
    fireEvent.click(engineering);
    expect(await screen.findByRole("heading", { name: "Engineering" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Recharge simulation" })).not.toBeInTheDocument();
  });

  it("keeps the active campaign mission visible and selectable after choosing a Python file", async () => {
    window.localStorage.removeItem("crazyswarm.campaign-workspace.v1");
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
        vehicles: [],
      });
      if (url.endsWith("/api/v1/mission-files")) return json([{
        mission_id: "manual-python",
        mission_version: "manual-sha",
        name: "Manual mission",
        description: "manual.py",
        source_kind: "UPLOADED_PYTHON",
        source_filename: "manual.py",
        source_sha256: "manual-sha",
        package_schema_version: 2,
        logical_roles: [],
        planned_commands: [],
      }]);
      if (url.endsWith("/api/v1/mission-files/manual-python/preview")) return json({});
      if (url.endsWith("/api/v1/simulation/world")) return json({
        schema_version: 1,
        world: { world_id: "room", width_m: 4, depth_m: 4, height_m: 2.5, obstacles: [] },
        vehicles: [],
      });
      if (url.endsWith("/api/v1/simulation/fidelity")) return json({
        manifest_id: "mission-kinematics-v1",
        source_class: "SIMULATED_MODEL",
        model: "mission kinematics",
        modeled_outputs: ["position"],
        omitted_outputs: [],
        limitations: [],
      });
      if (url.endsWith("/api/v1/twins")) return json([]);
      if (url.endsWith("/api/v1/campaign/cases")) return json({
        cases: [{
          case_id: "three_drone_multi_conflict",
          case_sha256: "campaign-sha",
          cluster: "GEOMETRIC_CONFLICT_RESOLUTION",
          family: "simultaneous_center_conflict",
          variation_name: "wide_priority_200_150_100",
          purpose: "Qualify a three-drone conflict",
          behavior_under_test: "Checks conflict resolution",
          expected_outcome: "All drones land safely",
          drone_count: 3,
          environment: "SIMULATION",
          authorization: "SOFTWARE_SIMULATION_ONLY",
          implementation_status: "EXECUTABLE",
          lifecycle: "ACTIVE_DEVELOPMENT",
          allowed_strategies: ["GROUND_DELAY"],
          objective_order: ["MISSION_COMPLETION_TIME_S"],
          expected_decisions: ["GROUND_DELAY"],
          execution_eligibility: "BOTH",
          operator_observation_questions: [],
          difficulty: 5,
          prerequisites: [],
          execution: {
            seed: 42,
            repetitions: 1,
            backend_profile_id: "fast-sim-v1",
            configuration_sha256: "0".repeat(64),
          },
        }],
        hierarchy: {},
      });
      if (url.endsWith("/api/v1/campaign/state")) return json({
        active_case_id: "three_drone_multi_conflict",
        runs: [],
        reviews: [],
      });
      if (url.endsWith("/api/v1/campaign/active/preview")) return json({});
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ControlCenter />);
    fireEvent.click(await screen.findByRole("button", { name: "Mission" }));
    const campaignMission = await screen.findByRole("button", {
      name: /Three drone multi conflict.*campaign_three_drone_multi_conflict\.py/i,
    });
    const simulation = screen.getByRole("button", { name: "Simulation" });
    const executionSwitch = simulation.closest(".execution-switch");
    expect(executionSwitch?.nextElementSibling).toContainElement(
      screen.getByRole("button", { name: /Campaign laboratory/i }),
    );
    expect(campaignMission.parentElement?.nextElementSibling).toHaveAttribute("role", "separator");
    expect(campaignMission).toHaveClass("is-selected");

    const manualMission = screen.getByRole("button", { name: /Manual mission.*manual\.py/i });
    fireEvent.click(manualMission);
    await waitFor(() => expect(manualMission).toHaveClass("is-selected"));
    expect(campaignMission).not.toHaveClass("is-selected");

    fireEvent.click(campaignMission);
    await waitFor(() => expect(campaignMission).toHaveClass("is-selected"));
    expect(manualMission).not.toHaveClass("is-selected");
  });

  it("applies simulator quick actions to the selected subset or the whole scene", async () => {
    const json = (value: unknown) => new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const vehicleIds = ["sim01", "sim02", "sim03"];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/state")) return json({
        mode: "SIM",
        selected_vehicle_id: "sim01",
        configured_flight_volume: null,
        mission_runs: [],
        vehicles: vehicleIds.map((vehicleId, index) => ({
          identity: { vehicle_id: vehicleId, display_name: `Simulator ${index + 1}`, adapter: "sim" },
          backend: { role: "FAST_SIM", authority: "SIMULATION" },
          capabilities: { decks: [] },
          selected: index === 0,
          state: "DISCONNECTED",
          telemetry: null,
          control_lease: null,
          control_state: { armed: null, flying: null },
        })),
      });
      if (url.endsWith("/api/v1/mission-files")) return json([]);
      if (url.endsWith("/api/v1/simulation/world")) return json({
        schema_version: 1,
        world: { world_id: "room", width_m: 4, depth_m: 4, height_m: 2.5, obstacles: [] },
        vehicles: vehicleIds.map((vehicleId, index) => ({
          vehicle_id: vehicleId,
          position_m: { x: index - 1, y: 0, z: 0 },
        })),
      });
      if (url.endsWith("/api/v1/simulation/fidelity")) return json({
        manifest_id: "mission-kinematics-v1",
        source_class: "SIMULATED_MODEL",
        model: "mission kinematics",
        modeled_outputs: ["position"],
        omitted_outputs: [],
        limitations: [],
      });
      if (url.endsWith("/api/v1/twins")) return json([]);
      if (/\/api\/v1\/simulation\/vehicles\/sim\d+\/clock$/.test(url)) {
        const body = JSON.parse(String(init?.body)) as { battery_percent?: number };
        return json({ battery_percent: body.battery_percent });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ControlCenter />);
    await screen.findByRole("button", { name: "Engineering" });
    expect(screen.queryByRole("combobox", { name: "Vehicle" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Toggle Simulator 2 selection" }));

    fireEvent.click(screen.getByRole("button", { name: "Recharge 2 selected drones to 100%" }));
    expect(await screen.findByText("2 drone batteries set to 100.0%")).toBeVisible();
    const selectedUrls = fetchMock.mock.calls
      .filter(([, init]) => String(init?.body).includes('"action":"recharge"'))
      .map(([input]) => String(input));
    expect(selectedUrls.some((url) => url.includes("/sim01/clock"))).toBe(true);
    expect(selectedUrls.some((url) => url.includes("/sim02/clock"))).toBe(true);
    expect(selectedUrls.some((url) => url.includes("/sim03/clock"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Clear drone selection" }));
    fireEvent.click(screen.getByRole("button", { name: "Recharge all 3 drones to 100%" }));
    expect(await screen.findByText("3 drone batteries set to 100.0%")).toBeVisible();
    const allUrls = fetchMock.mock.calls
      .filter(([, init]) => String(init?.body).includes('"action":"recharge"'))
      .map(([input]) => String(input));
    expect(allUrls.some((url) => url.includes("/sim03/clock"))).toBe(true);
  });

  it("targets retained mission-preview drones even when another fleet is in the dashboard", async () => {
    const json = (value: unknown) => new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const previewVehicleIds = ["multi-alpha", "multi-beta", "multi-gamma"];
    const preview = {
      mission_id: "py-three-role",
      source_sha256: "abc123",
      plan_sha256: "plan-hash",
      plan: {
        plan_id: "plan-three-role",
        status: "APPROVED",
        findings: [],
        planning: {
          plugin_selections: [],
          route_plans: [],
          mission_intent: { objective: "Execute three roles", phases: [] },
          safety_case: { safety_case_sha256: "safety-hash" },
        },
      },
      vehicles: previewVehicleIds.map((vehicleId, index) => ({
        role_id: `route_${index + 1}`,
        vehicle_id: vehicleId,
        display_name: `Multi ${index + 1}`,
        initial_role: "ACTIVE",
        home_m: { x: index - 1, y: 0, z: 0 },
        start_m: { x: index - 1, y: 1, z: 0 },
        battery_percent: 80,
        existing_vehicle: true,
        backend_role: "FAST_SIM",
        vehicle_state: "DISCONNECTED",
        preview_fidelity: "EXACT_ROLE",
        planned_commands: [],
      })),
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/state")) return json({
        mode: "SIM",
        selected_vehicle_id: "crossing-south",
        configured_flight_volume: null,
        mission_runs: [],
        fleet_sessions: [],
        vehicles: ["crossing-south", "crossing-west"].map((vehicleId) => ({
          identity: { vehicle_id: vehicleId, display_name: vehicleId, adapter: "sim" },
          backend: { role: "FAST_SIM", authority: "SIMULATION" },
          capabilities: { decks: [] },
          selected: vehicleId === "crossing-south",
          state: "DISCONNECTED",
          telemetry: null,
          control_lease: null,
          control_state: { armed: null, flying: null },
        })),
      });
      if (url.endsWith("/api/v1/mission-files")) return json([{
        mission_id: "py-three-role",
        mission_version: "abc123",
        name: "three_drone_multi_conflict",
        description: "three_drone_multi_conflict.py",
        source_kind: "UPLOADED_PYTHON",
        source_filename: "three_drone_multi_conflict.py",
        source_sha256: "abc123",
        package_schema_version: 2,
        logical_roles: [],
        planned_commands: [],
      }]);
      if (url.endsWith("/api/v1/mission-files/py-three-role/preview")) return json(preview);
      if (url.endsWith("/api/v1/simulation/world")) return json({
        schema_version: 1,
        world: { world_id: "room", width_m: 8, depth_m: 6, height_m: 3, obstacles: [] },
        vehicles: [],
      });
      if (url.endsWith("/api/v1/simulation/fidelity")) return json({
        manifest_id: "mission-kinematics-v1",
        source_class: "SIMULATED_MODEL",
        model: "mission kinematics",
        modeled_outputs: ["position"],
        omitted_outputs: [],
        limitations: [],
      });
      if (url.endsWith("/api/v1/twins")) return json([]);
      if (url.endsWith("/api/v1/simulation/fleet/reset-poses")) {
        const body = JSON.parse(String(init?.body)) as { vehicle_ids: string[] };
        return json({
          vehicle_ids: body.vehicle_ids,
          reset_scope: ["active_fleet", "pose", "motion", "estimator_state"],
        });
      }
      if (previewVehicleIds.some((vehicleId) =>
        url.endsWith(`/api/v1/simulation/vehicles/${vehicleId}/clock`))) return json({});
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ControlCenter />);
    expect(await screen.findByText("3 in scene")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reposition all 3 drones to home" }));
    expect(await screen.findByText("3 drones repositioned to configured home")).toBeVisible();

    const resetBodies = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith("/api/v1/simulation/fleet/reset-poses"))
      .map(([, init]) => JSON.parse(String(init?.body)) as { vehicle_ids: string[] });
    expect(resetBodies).toEqual([{ vehicle_ids: previewVehicleIds }]);

    fireEvent.click(screen.getByRole("button", { name: "Toggle Multi 2 selection" }));
    fireEvent.click(screen.getByRole("button", { name: "Reposition drone to home" }));
    expect(await screen.findByText("Drone repositioned to configured home")).toBeVisible();
    const selectedResetBodies = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith("/api/v1/simulation/fleet/reset-poses"))
      .map(([, init]) => JSON.parse(String(init?.body)) as { vehicle_ids: string[] });
    expect(selectedResetBodies).toEqual([
      { vehicle_ids: previewVehicleIds },
      { vehicle_ids: ["multi-beta"] },
    ]);
  });

  it("auto-stages the selected two-drone mission in the scene", async () => {
    const json = (value: unknown) => new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/state")) return json({
        mode: "SIM",
        selected_vehicle_id: "sim01",
        configured_flight_volume: null,
        mission_runs: [],
        fleet_sessions: [],
        vehicles: [{
          identity: { vehicle_id: "sim01", display_name: "Simulator", adapter: "sim" },
          backend: { role: "FAST_SIM", authority: "SIMULATION" },
          capabilities: { decks: [] },
          selected: true,
          state: "DISCONNECTED",
          telemetry: null,
          control_lease: null,
          control_state: { armed: null, flying: null },
        }],
      });
      if (url.endsWith("/api/v1/mission-files")) return json([{
        mission_id: "py-two-role",
        mission_version: "abc123",
        name: "two_role_move",
        description: "two_role_move.py",
        source_kind: "UPLOADED_PYTHON",
        source_filename: "two_role_move.py",
        source_sha256: "abc123",
        package_schema_version: 2,
        logical_roles: [],
        planned_commands: [],
      }]);
      if (url.endsWith("/api/v1/mission-files/py-two-role/preview")) return json({
        mission_id: "py-two-role",
        source_sha256: "abc123",
        plan_sha256: "plan-hash",
        plan: {
          plan_id: "plan-two-role",
          status: "APPROVED",
          findings: [],
          planning: {
            plugin_selections: [],
            route_plans: [],
            mission_intent: { objective: "Execute roles", phases: [] },
            safety_case: { safety_case_sha256: "safety-hash" },
          },
        },
        vehicles: [
          {
            role_id: "left",
            vehicle_id: "drone-left",
            display_name: "Left",
            initial_role: "ACTIVE",
            home_m: { x: -0.8, y: 0, z: 0 },
            start_m: { x: -0.8, y: 0, z: 0 },
            existing_vehicle: false,
            preview_fidelity: "EXACT_ROLE",
            planned_commands: [{ action: "takeoff", arguments: { height_m: 0.3 } }],
          },
          {
            role_id: "right",
            vehicle_id: "drone-right",
            display_name: "Right",
            initial_role: "ACTIVE",
            home_m: { x: 0.8, y: 0, z: 0 },
            start_m: { x: 0.8, y: 0, z: 0 },
            existing_vehicle: false,
            preview_fidelity: "EXACT_ROLE",
            planned_commands: [{ action: "takeoff", arguments: { height_m: 0.3 } }],
          },
        ],
      });
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
        omitted_outputs: [],
        limitations: [],
      });
      if (url.endsWith("/api/v1/twins")) return json([]);
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ControlCenter />);
    await screen.findByRole("button", { name: "Engineering" });
    expect(await screen.findByRole("img", { name: /previewing 2 mission vehicles/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "two_role_move" }));
    fireEvent.click(await screen.findByRole("button", { name: /two_role_move\.py/ }));

    expect(await screen.findByRole("img", { name: /previewing 2 mission vehicles/ })).toBeVisible();
    expect(screen.queryByText("MISSION PREVIEW")).not.toBeInTheDocument();
    expect(screen.queryByText("2 configured drones · not running")).not.toBeInTheDocument();
    const deployment = screen.getByRole("region", { name: "Mission deployment status" });
    expect(within(deployment).queryByText("two_role_move")).not.toBeInTheDocument();
    expect(within(deployment).queryByText("Plan overview")).not.toBeInTheDocument();
    expect(within(deployment).queryByText("Ready for approval")).not.toBeInTheDocument();
    const expandDeployment = within(deployment).getByRole("button", { name: "Expand mission deployment details" });
    expect(expandDeployment).toHaveAttribute("aria-expanded", "false");
    expect(within(deployment).queryByRole("region", { name: "Operational mission plan" })).not.toBeInTheDocument();
    fireEvent.click(expandDeployment);
    expect(within(deployment).getByRole("region", { name: "Operational mission plan" })).toBeVisible();
    expect(within(screen.getByLabelText("Mission setup")).queryByRole("region", { name: "Operational mission plan" }))
      .not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/control-api/api/v1/mission-files/py-two-role/preview",
      expect.any(Object),
    );
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
