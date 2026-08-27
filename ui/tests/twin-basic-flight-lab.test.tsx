import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TWIN_WORKSPACE_PREFERENCES_KEY, TwinBasicFlightLab } from "../app/components/TwinBasicFlightLab";
import type { ControlApi } from "../app/lib/api";
import type {
  PhysicalTwinStatusView,
  TwinBasicFlightCatalogView,
  TwinBasicFlightRunView,
} from "../app/lib/models";

const pairedGroundedStatus: PhysicalTwinStatusView = {
  state: "PAIRED",
  configured: true,
  autoConnectEnabled: true,
  commandReadiness: "NOT_ASSESSED",
  commandReadinessIssues: [],
  testOnly: false,
  sampleCount: 56,
  pairedCycleCount: 1,
  observed: {
    role: "OBSERVED",
    vehicleId: "physical:test",
    sourceClass: "TEST",
    freshness: "CURRENT",
    positionAvailability: "MISSING",
    batteryAvailability: "MISSING",
    armed: false,
    flying: false,
    familyAvailability: {},
  },
};

const catalog: TwinBasicFlightCatalogView = {
  clusterId: "basic-flight",
  clusterName: "Basic flight",
  purpose: "Build basic behavior and retain learning observations.",
  qualificationClaim: "NONE",
  clusters: [{
    clusterId: "basic-flight",
    clusterName: "Basic flight",
    purpose: "Build basic behavior.",
    state: "READY",
  }],
  motions: [
    {
      motionId: "commissioning-baseline",
      clusterId: "basic-flight",
      majorMission: "First liftoff",
      variant: "30 cm · 30 s",
      motion: "Arm → motor rehearsal → hover → land",
      summary: "First end-to-end behavior.",
      physicalScope: "CONTAINED_FLIGHT",
      physicalExecution: "OPERATOR_GATED",
      catalogVisibility: true,
      implementationState: "READY",
      steps: [
        { stepId: "arm", title: "Arm", behavior: "Arm.", containment: "Ground only." },
        { stepId: "motors-30", title: "Motors at 30%", behavior: "Model 30%.", containment: "Props off." },
        { stepId: "land", title: "Land", behavior: "Land.", containment: "At home." },
      ],
      learningSignals: ["battery start/minimum/end"],
    },
  ],
};

const run: TwinBasicFlightRunView = {
  runId: "twin-basic-123",
  motionId: "commissioning-baseline",
  status: "COMPLETED",
  executionBackend: "FAST_SIM",
  evidenceClass: "SIMULATED_MODEL",
  learningDisposition: "SIMULATOR_INPUT_CANDIDATE",
  qualificationClaim: "NONE",
  steps: [{ stepId: "motors-30", status: "MODELED_ONLY", detail: "No output sent" }],
  learningSample: {
    batteryStartPercent: 100,
    batteryMinimumPercent: 99.8,
    batteryEndPercent: 99.8,
    batteryDeltaPercent: 0.2,
    minimumVoltageV: 4.1,
    maximumCurrentA: 1.2,
    peakMotorCommandPercent: 44,
    hoverRmsDriftM: 0.002,
    maximumAltitudeM: 0.31,
    landingContactObserved: true,
    finalState: "READY",
  },
  artifactPath: "/tmp/basic-flight.jsonl",
};

describe("Digital Twin basic-flight campaign lab", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.removeItem(TWIN_WORKSPACE_PREFERENCES_KEY);
  });

  it("restores the open workspace, tab, and selected motion after a refresh", async () => {
    window.localStorage.setItem(TWIN_WORKSPACE_PREFERENCES_KEY, JSON.stringify({
      open: true,
      tab: "review",
      selectedMotionId: "commissioning-baseline",
    }));
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab api={api} onNotice={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Campaign Laboratory" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Review" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/First liftoff · Physical drone/)).toBeVisible();
  });

  it("selects in Campaign Laboratory and runs from the shared mission control", async () => {
    const twinBasicFlightCatalog = vi.fn().mockResolvedValue(catalog);
    const completedRun = {
      ...run,
      executionBackend: "REAL_CRAZYFLIE" as const,
      evidenceClass: "MEASURED_REAL" as const,
    };
    const startPhysicalFlight = vi.fn().mockResolvedValue({
      state: "COMPLETED",
      stopRequired: false,
      operationId: "physical-operation-1",
      motionId: "commissioning-baseline",
      result: completedRun,
    });
    const pairedStatus = pairedGroundedStatus;
    const physicalTwinStatus = vi.fn().mockResolvedValue(pairedStatus);
    const onNotice = vi.fn();
    const onPhysicalStatusChange = vi.fn();
    const api = {
      twinBasicFlightCatalog,
      startPhysicalFlight,
      physicalTwinStatus,
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      onNotice={onNotice}
      onPhysicalStatusChange={onPhysicalStatusChange}
      physicalStatus={pairedGroundedStatus}
    />);

    expect(await screen.findByText("Campaign Laboratory")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Campaign Laboratory/i }));
    expect(await screen.findByRole("heading", { name: "Campaign Laboratory" })).toBeInTheDocument();
    expect(screen.getByText("Mission cluster")).toBeInTheDocument();
    expect(screen.getByText("Major mission")).toBeInTheDocument();
    expect(screen.getByText("Variant")).toBeInTheDocument();
    expect(screen.getByText("Motion")).toBeInTheDocument();
    expect(screen.queryByText("Physical flight entry")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run Fast Sim" })).not.toBeInTheDocument();
    const laboratory = screen.getByRole("dialog", { name: "Campaign Laboratory" });
    expect(within(laboratory).queryByRole("button", { name: /Run 30 cm|Arm and fly/ })).not.toBeInTheDocument();
    expect(within(laboratory).getByText("Selected mission appears in the bottom mission control")).toBeVisible();

    fireEvent.click(within(laboratory).getByRole("button", { name: "Close Campaign Laboratory" }));
    fireEvent.click(await screen.findByRole("button", { name: "Run 30 cm commissioning flight" }));

    await waitFor(() => expect(startPhysicalFlight).toHaveBeenCalledWith("commissioning-baseline"));
    fireEvent.click(screen.getByRole("button", { name: /Campaign Laboratory/i }));
    fireEvent.click(await screen.findByRole("tab", { name: "Review" }));
    expect(await screen.findByText("Learning observation retained")).toBeInTheDocument();
    expect(screen.getByText("Not a battery test or qualification result")).toBeInTheDocument();
    expect(onNotice).toHaveBeenCalledWith(expect.stringContaining("commissioning flight completed"));
    expect(physicalTwinStatus).toHaveBeenCalledOnce();
    expect(onPhysicalStatusChange).toHaveBeenCalledWith(pairedStatus);
  });

  it("shows the controller-tuning cluster with A to E staged and F to H raw", async () => {
    const tuningCatalog: TwinBasicFlightCatalogView = {
      ...catalog,
      // The motion boundary is authoritative even if older catalog metadata omits
      // the controller cluster during a rolling dashboard/backend update.
      clusters: catalog.clusters,
      controllerTuningFixture: {
        fixtureId: "controller-tuning-box",
        fixtureVersion: "1.0-draft",
        artifactPath: "/project/config/fixtures/controller-tuning-box-v1.json",
        state: "AWAITING_MEASUREMENTS",
        implementedFlightsAvailable: true,
        missingFields: ["dimensions.inside_x_m"],
        detail: "Characterization metadata is incomplete. Implemented flights remain operator-selectable.",
      },
      motions: [
        ...catalog.motions,
        ...["A", "B", "C", "D", "E"].flatMap((majorLetter) => (
          ["A", "B", "C", "D", "E"].map((marker) => ({
            ...catalog.motions[0]!,
            motionId: majorLetter === "A"
              ? `tuning-a-station-${marker.toLowerCase()}`
              : `tuning-${majorLetter.toLowerCase()}-stage`,
            clusterId: "controller-characterization-tuning",
            majorMission: majorLetter === "A"
              ? "A · Fixture & sensor baseline"
              : majorLetter === "B"
                ? "B · Default-PID vertical baseline"
                : `${majorLetter} · Implemented stage`,
            variant: marker,
            placementMarker: marker as "A" | "B" | "C" | "D" | "E",
            motion: majorLetter === "A" ? "Observe baseline" : `${majorLetter} setup workflow`,
            summary: majorLetter === "A"
              ? `Record marker ${marker} with motors off.`
              : `${majorLetter} is implemented and operator-selectable.`,
            physicalScope: majorLetter === "A" ? "FIXTURE_OBSERVATION" as const : "CONTAINED_FLIGHT" as const,
            implementationState: "READY" as const,
            blockReason: undefined,
            steps: majorLetter === "A" ? [{
              stepId: "observe",
              title: "Record for 30 s",
              behavior: "Keep motors off.",
              containment: "No flight command.",
            }] : catalog.motions[0]!.steps,
          }))
        )),
        ...["F", "G", "H"].map((letter) => ({
          ...catalog.motions[0]!,
          motionId: `tuning-${letter.toLowerCase()}-raw`,
          clusterId: "controller-characterization-tuning",
          majorMission: `${letter} · Future stage`,
          variant: "Raw",
          motion: "Raw stage",
          summary: `${letter} remains raw.`,
          physicalExecution: "NOT_ENABLED" as const,
          implementationState: "RAW" as const,
          blockReason: "Raw future stage; no executable workflow is attached yet.",
          steps: [],
          learningSignals: [],
        })),
      ],
    };
    window.localStorage.setItem(TWIN_WORKSPACE_PREFERENCES_KEY, JSON.stringify({
      open: true,
      tab: "catalog",
      selectedMotionId: "commissioning-baseline",
    }));
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(tuningCatalog),
      physicalFlightStatus: vi.fn().mockResolvedValue({ state: "IDLE", stopRequired: false }),
      startPhysicalFlight: vi.fn().mockResolvedValue({
        state: "STARTING",
        stopRequired: true,
        operationId: "tuning-observation-1",
        motionId: "tuning-a-station-a",
      }),
      physicalTwinStatus: vi.fn().mockResolvedValue(pairedGroundedStatus),
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      onNotice={vi.fn()}
      physicalStatus={pairedGroundedStatus}
    />);

    expect(await screen.findByRole("button", { name: "Basic flight" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "First liftoff" }));
    expect(screen.queryByRole("option", { name: "A · Fixture & sensor baseline" })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("listbox", { name: "Major mission" }), { key: "Escape" });

    fireEvent.click(screen.getByRole("button", { name: "Basic flight" }));
    fireEvent.click(screen.getByRole("option", { name: /Controller characterization & tuning/ }));

    expect(await screen.findByRole("button", { name: /Controller characterization & tuning/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "A · Fixture & sensor baseline" })).toBeVisible();
    expect(screen.getByRole("button", { name: "AReady" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "AReady" }));
    for (const marker of ["A", "B", "C", "D", "E"]) {
      expect(screen.getByRole("option", { name: new RegExp(`${marker}$`) })).toBeVisible();
    }
    fireEvent.keyDown(screen.getByRole("listbox", { name: "Variant" }), { key: "Escape" });
    const heading = screen.getByRole("spinbutton", { name: /^Heading/ });
    expect(heading).toHaveValue(0);
    expect(heading.closest(".campaign-case-detail")).not.toBeNull();
    expect(screen.getByText("Run setup")).toBeVisible();
    expect(screen.getByText("Marker A")).toBeVisible();
    expect(screen.getByText("0 = front +Y · 45 = between +Y/+X · 90 = front +X")).toBeVisible();
    fireEvent.change(heading, {
      target: { value: "45" },
    });

    fireEvent.click(screen.getByRole("button", { name: "A · Fixture & sensor baseline" }));
    fireEvent.click(screen.getByRole("option", { name: "B · Default-PID vertical baseline" }));
    expect(screen.getByRole("spinbutton", { name: "Flight height (metres)" })).toHaveAttribute(
      "placeholder",
      "Required",
    );
    expect(screen.getByText("Marker A")).toBeVisible();
    expect(screen.queryByText("Setup required")).not.toBeInTheDocument();
    expect(screen.queryByText("Flight gated")).not.toBeInTheDocument();
    expect(screen.getByText("Characterization incomplete")).toBeVisible();
    expect(screen.getByText(/Implemented flights remain operator-selectable/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "B · Default-PID vertical baseline" }));
    fireEvent.click(screen.getByRole("option", { name: "F · Future stage" }));

    expect(await screen.findByText("Raw future stage; no executable workflow is attached yet.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Run Raw stage" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "F · Future stage" }));
    fireEvent.click(screen.getByRole("option", { name: "A · Fixture & sensor baseline" }));
    fireEvent.click(screen.getByRole("button", { name: "Record Observe baseline" }));
    await waitFor(() => expect(api.startPhysicalFlight).toHaveBeenCalledWith(
      "tuning-a-station-a",
      { stationId: "A", headingDeg: 45, targetHeightM: undefined },
    ));
  });

  it("starts the cushioned-acrobatics hover, then exposes its one-shot Flip action", async () => {
    const acrobaticsCatalog: TwinBasicFlightCatalogView = {
      ...catalog,
      clusters: [
        ...catalog.clusters,
        {
          clusterId: "controller-characterization-tuning",
          clusterName: "Controller characterization & tuning",
          purpose: "Characterize the measured fixture.",
          state: "SETUP_REQUIRED",
        },
        {
          clusterId: "cushioned-acrobatics",
          clusterName: "Cushioned acrobatics",
          purpose: "Learn the rate-controller and motor-mixer boundary.",
          state: "READY",
          detail: "Play establishes a 50 cm hover; Flip then runs once and auto-lands.",
        },
      ],
      motions: [
        ...catalog.motions,
        {
          motionId: "acro-single-roll",
          clusterId: "cushioned-acrobatics",
          majorMission: "Single flip",
          variant: "Positive roll · 360°",
          motion: "Hover → boost → fast roll → recover → land",
          summary: "Exercise the onboard rate controller and motor mixer.",
          physicalScope: "CONTAINED_FLIGHT",
          physicalExecution: "OPERATOR_GATED",
          catalogVisibility: true,
          implementationState: "READY",
          steps: [{
            stepId: "single-roll-rate-profile",
            title: "One cubic roll-rate profile",
            behavior: "Stream one 360° roll at 100 Hz.",
            containment: "The onboard rate PID and X mixer retain motor authority.",
          }],
          learningSignals: ["measured motor m1/m2/m3/m4 outputs"],
        },
      ],
    };
    window.localStorage.setItem(TWIN_WORKSPACE_PREFERENCES_KEY, JSON.stringify({
      open: true,
      tab: "catalog",
      selectedMotionId: "commissioning-baseline",
    }));
    const physicalFlightStatus = vi.fn().mockResolvedValue({ state: "IDLE", stopRequired: false });
    const startPhysicalFlight = vi.fn().mockImplementation(async () => {
      physicalFlightStatus.mockResolvedValue({
        state: "HOVERING_READY",
        stopRequired: true,
        operationId: "twin-acrobatics-real-1",
        motionId: "acro-single-roll",
        detail: "Hovering at 0.50 m; Flip is ready for one operator trigger",
        availableAction: "FLIP",
      });
      return {
        state: "STARTING",
        stopRequired: true,
        operationId: "twin-acrobatics-real-1",
        motionId: "acro-single-roll",
      };
    });
    const triggerAcrobaticsFlip = vi.fn().mockResolvedValue({
      state: "FLIPPING",
      stopRequired: true,
      operationId: "twin-acrobatics-real-1",
      motionId: "acro-single-roll",
    });
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(acrobaticsCatalog),
      physicalFlightStatus,
      startPhysicalFlight,
      triggerAcrobaticsFlip,
      abortPhysicalFlight: vi.fn(),
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      onNotice={vi.fn()}
      physicalStatus={pairedGroundedStatus}
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Basic flight" }));
    fireEvent.click(screen.getByRole("option", { name: /Cushioned acrobatics/ }));

    expect(await screen.findByRole("button", { name: /Cushioned acrobatics/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "Single flip" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Positive roll · 360°Ready" })).toBeVisible();
    const start = screen.getByRole("button", { name: "Start 50 cm hover" });
    expect(start).toBeEnabled();
    fireEvent.click(start);
    await waitFor(() => expect(startPhysicalFlight).toHaveBeenCalledWith("acro-single-roll"));

    const flip = await screen.findByRole("button", { name: "Flip" }, { timeout: 1_500 });
    expect(screen.getByRole("button", { name: "Abort and land" })).toBeVisible();
    fireEvent.click(flip);
    await waitFor(() => expect(triggerAcrobaticsFlip).toHaveBeenCalledOnce());
  });

  it("shows an immediate connecting state while Play is waiting for admission", async () => {
    const startPhysicalFlight = vi.fn(() => new Promise(() => {}));
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
      physicalFlightStatus: vi.fn().mockResolvedValue({ state: "IDLE", stopRequired: false }),
      startPhysicalFlight,
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      onNotice={vi.fn()}
      physicalStatus={pairedGroundedStatus}
    />);

    fireEvent.click(await screen.findByRole("button", {
      name: "Run 30 cm commissioning flight",
    }));

    expect(await screen.findByText("Physical drone · Connecting")).toBeVisible();
    expect(screen.getByRole("button", { name: "Connecting to physical drone" })).toBeDisabled();
    expect(startPhysicalFlight).toHaveBeenCalledWith("commissioning-baseline");
  });

  it("passes the selected physical mission through instead of rewriting it to commissioning", async () => {
    const hoverMotion = {
      ...catalog.motions[0],
      motionId: "hover-12s",
      majorMission: "Hover stability",
      variant: "30 cm · 12 s",
      motion: "Take off → hover → land at home",
      summary: "Hold 0.30 m for 12 seconds before landing at home.",
    };
    const physicalCatalog = { ...catalog, motions: [catalog.motions[0], hoverMotion] };
    window.localStorage.setItem(TWIN_WORKSPACE_PREFERENCES_KEY, JSON.stringify({
      open: false,
      tab: "catalog",
      selectedMotionId: "hover-12s",
    }));
    const startPhysicalFlight = vi.fn().mockResolvedValue({
      state: "RUNNING",
      stopRequired: true,
      operationId: "hover-operation",
      motionId: "hover-12s",
    });
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(physicalCatalog),
      startPhysicalFlight,
      physicalTwinStatus: vi.fn().mockResolvedValue(pairedGroundedStatus),
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      onNotice={vi.fn()}
      physicalStatus={pairedGroundedStatus}
    />);

    fireEvent.click(await screen.findByRole("button", {
      name: "Run Take off → hover → land at home",
    }));

    await waitFor(() => expect(startPhysicalFlight).toHaveBeenCalledWith("hover-12s"));
  });

  it("restores a backend-owned active flight and keeps global abort available", async () => {
    const onPhysicalFlightActiveChange = vi.fn();
    const physicalFlightStatus = vi.fn().mockResolvedValue({
      state: "RUNNING",
      stopRequired: true,
      operationId: "physical-operation-active",
      motionId: "commissioning-baseline",
      detail: "Physical drone action running",
    });
    const abortPhysicalFlight = vi.fn().mockResolvedValue({
      state: "ABORTED",
      stopRequired: false,
      operationId: "physical-operation-active",
      motionId: "commissioning-baseline",
      detail: "Physical flight aborted, landed, and disarmed",
    });
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
      physicalFlightStatus,
      abortPhysicalFlight,
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      onNotice={vi.fn()}
      onPhysicalFlightActiveChange={onPhysicalFlightActiveChange}
      physicalStatus={pairedGroundedStatus}
    />);

    const abort = await screen.findByRole("button", { name: "Abort and land" });
    await waitFor(() => expect(onPhysicalFlightActiveChange).toHaveBeenCalledWith(true));
    expect(abort).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Run 30 cm commissioning flight" })).not.toBeInTheDocument();
    fireEvent.click(abort);
    await waitFor(() => expect(abortPhysicalFlight).toHaveBeenCalledOnce());
    await waitFor(() => expect(onPhysicalFlightActiveChange).toHaveBeenCalledWith(false));
  });

  it("does not activate the flight visualization for idle observation", async () => {
    const onPhysicalFlightActiveChange = vi.fn();
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
      physicalFlightStatus: vi.fn().mockResolvedValue({ state: "IDLE", stopRequired: false }),
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      onNotice={vi.fn()}
      onPhysicalFlightActiveChange={onPhysicalFlightActiveChange}
      physicalStatus={pairedGroundedStatus}
    />);

    expect(await screen.findByRole("button", { name: "Run 30 cm commissioning flight" })).toBeEnabled();
    expect(onPhysicalFlightActiveChange).toHaveBeenCalledWith(false);
    expect(onPhysicalFlightActiveChange).not.toHaveBeenCalledWith(true);
  });

  it("blocks Play when supervisor state is flying or unavailable", async () => {
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
      physicalFlightStatus: vi.fn().mockResolvedValue({ state: "IDLE", stopRequired: false }),
    } as unknown as ControlApi;
    const flyingStatus: PhysicalTwinStatusView = {
      ...pairedGroundedStatus,
      observed: { ...pairedGroundedStatus.observed!, armed: true, flying: true },
    };
    const { rerender } = render(<TwinBasicFlightLab
      api={api}
      onNotice={vi.fn()}
      physicalStatus={flyingStatus}
    />);

    expect(await screen.findByRole("button", { name: "Run 30 cm commissioning flight" })).toBeDisabled();

    rerender(<TwinBasicFlightLab
      api={api}
      onNotice={vi.fn()}
      physicalStatus={{
        ...pairedGroundedStatus,
        observed: { ...pairedGroundedStatus.observed!, armed: undefined, flying: undefined },
      }}
    />);
    expect(screen.getByRole("button", { name: "Run 30 cm commissioning flight" })).toBeDisabled();
  });

  it("keeps one Play action when the grounded supervisor reports armed", async () => {
    const armedGroundedStatus: PhysicalTwinStatusView = {
      ...pairedGroundedStatus,
      observed: { ...pairedGroundedStatus.observed!, armed: true, flying: false },
    };
    const startPhysicalFlight = vi.fn().mockResolvedValue({
      state: "RUNNING",
      stopRequired: true,
      operationId: "prearmed-flight",
      motionId: "commissioning-baseline",
    });
    const physicalTwinStatus = vi.fn().mockResolvedValue(pairedGroundedStatus);
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
      physicalFlightStatus: vi.fn().mockResolvedValue({ state: "IDLE", stopRequired: false }),
      startPhysicalFlight,
      physicalTwinStatus,
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      actuationStatus={{ state: "IDLE", stopRequired: false, rebootRequired: false }}
      onNotice={vi.fn()}
      physicalStatus={armedGroundedStatus}
    />);

    const play = await screen.findByRole("button", { name: "Run 30 cm commissioning flight" });
    expect(play).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Disarm drone" })).not.toBeInTheDocument();
    fireEvent.click(play);

    await waitFor(() => expect(startPhysicalFlight).toHaveBeenCalledWith(
      "commissioning-baseline",
    ));
  });

  it("blocks Play while firmware still requires a power cycle", async () => {
    const startPhysicalFlight = vi.fn();
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
      physicalFlightStatus: vi.fn().mockResolvedValue({ state: "IDLE", stopRequired: false }),
      startPhysicalFlight,
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      actuationStatus={{ state: "IDLE", stopRequired: false, rebootRequired: true }}
      onNotice={vi.fn()}
      physicalStatus={pairedGroundedStatus}
    />);

    expect(await screen.findByText("Motors off · Power cycle required")).toBeVisible();
    const play = screen.getByRole("button", { name: "Run 30 cm commissioning flight" });
    expect(play).toBeDisabled();
    expect(play).toHaveAttribute(
      "title",
      "Power cycle the Crazyflie before starting another physical action",
    );
    expect(startPhysicalFlight).not.toHaveBeenCalled();
  });

  it("restores stop-unconfirmed as Abort and land rather than Play", async () => {
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
      physicalFlightStatus: vi.fn().mockResolvedValue({
        state: "STOP_UNCONFIRMED",
        stopRequired: true,
        operationId: "restored-flight",
        motionId: "commissioning-baseline",
        detail: "A previous physical flight did not retain a confirmed stop",
      }),
      abortPhysicalFlight: vi.fn().mockResolvedValue({
        state: "ABORTED",
        stopRequired: false,
        operationId: "restored-flight",
      }),
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab api={api} onNotice={vi.fn()} physicalStatus={pairedGroundedStatus} />);

    expect(await screen.findByText("Physical flight · Stop unconfirmed")).toBeVisible();
    expect(screen.getByRole("button", { name: "Abort and land" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Run 30 cm commissioning flight" })).not.toBeInTheDocument();
  });

  it("keeps a global motor stop when the initiating bench session UI is gone", async () => {
    const stopAllMotorOutput = vi.fn().mockResolvedValue({
      state: "IDLE" as const,
      stopRequired: false,
      commandedOutputPercent: 0,
      measuredOutputActive: false,
    });
    const api = {
      twinBasicFlightCatalog: vi.fn().mockResolvedValue(catalog),
    } as unknown as ControlApi;

    render(<TwinBasicFlightLab
      api={api}
      actuationStatus={{
        state: "POSSIBLY_ACTIVE",
        stopRequired: true,
        commandedOutputPercent: 20,
        detail: "The previous direct-PWM session did not record a confirmed stop",
      }}
      onNotice={vi.fn()}
      onStopAllMotorOutput={stopAllMotorOutput}
    />);

    expect(await screen.findByText("Motor output · Unconfirmed")).toBeVisible();
    const stop = screen.getByRole("button", { name: "Stop motors" });
    expect(stop).toBeEnabled();
    fireEvent.click(stop);
    await waitFor(() => expect(stopAllMotorOutput).toHaveBeenCalledOnce());
  });
});
