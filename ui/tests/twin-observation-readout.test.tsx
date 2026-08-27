import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PhysicalTwinStatusView } from "../app/lib/models";
import { TwinObservationReadout } from "../app/components/TwinObservationReadout";


const status: PhysicalTwinStatusView = {
  state: "PAIRED",
  configured: true,
  vehicleLabel: "Drone#1 - Nike",
  commandReadiness: "UNQUALIFIED",
  commandReadinessIssues: ["PROTOCOL_UNQUALIFIED"],
  testOnly: true,
  sampleCount: 70784,
  pairedCycleCount: 1264,
  observed: {
    role: "OBSERVED",
    vehicleId: "physical:test",
    sourceClass: "TEST",
    freshness: "CURRENT",
    frame: "home",
    sourceEpoch: 2,
    rawSourceTimestampS: 1933.909,
    sourceTimestampS: 12.4,
    pairSequence: 125,
    alignmentEpoch: 2,
    positionAvailability: "INCOMPATIBLE",
    batteryAvailability: "AVAILABLE",
    batteryVoltage: 3.906158,
    attitude: { rollRad: 0.01, pitchRad: -0.02, yawRad: 0.03 },
    imu: {
      acceleration: { x: 0, y: 0, z: 9.81 },
      angularVelocity: { x: 0.001, y: 0.002, z: 0.003 },
    },
    flow: {
      velocity: { x: -1.5, y: 3.2, z: 0 },
      groundDistanceM: 0.018,
      qualityPercent: 3.529,
      status: "VALID",
    },
    ranges: {
      frontM: 0.4,
      backM: 1.2,
      leftM: 0.15,
      rightM: 2.4,
      upM: 1.6,
      downM: 0.04,
      statuses: { front: "VALID", back: "VALID", left: "VALID", right: "VALID", up: "VALID", down: "VALID" },
    },
    estimator: {
      converged: false,
      positionVariance: { x: 6.7, y: 5.0, z: 0.015 },
    },
    motorPwmPercent: [41.25, 42.5, 43.75, 45],
    transport: {
      kind: "physical_radio",
      deliveryQualityPercent: 98.75,
      packetLossPercent: 1.25,
      radio: {
        connectionEpoch: 3,
        state: "DEGRADED",
        failureKind: "RF_ACK_LOSS",
        ackedPacketCount: 987,
        lostPacketCount: 13,
        packetLossPercent: 1.25,
        consecutiveLostPacketCount: 0,
        maximumConsecutiveLostPacketCount: 7,
        retryQualityPercent: 92.5,
        uplinkRssiRaw: 47,
        uplinkRateHz: 101.2,
        downlinkRateHz: 54.8,
        uplinkCongestionPercent: 12,
        downlinkCongestionPercent: 31,
        outboundQueueDepth: 0,
        outboundQueueCapacity: 1,
        queueSaturationCount: 2,
        usbErrorCount: 0,
        lastAckAgeMs: 14,
      },
    },
    familyAvailability: {
      attitude: "AVAILABLE",
      imu: "AVAILABLE",
      battery: "AVAILABLE",
      flow: "AVAILABLE",
      ranges: "AVAILABLE",
      estimator: "AVAILABLE",
      motors: "AVAILABLE",
      transport: "AVAILABLE",
    },
  },
  predicted: {
    role: "PREDICTED",
    vehicleId: "fast-sim:test",
    sourceClass: "TEST",
    freshness: "CURRENT",
    sourceEpoch: 1,
    sourceTimestampS: 12.4,
    pairSequence: 125,
    alignmentEpoch: 2,
    positionAvailability: "INCOMPATIBLE",
    batteryAvailability: "MISSING",
    familyAvailability: { battery: "MISSING" },
  },
};

describe("TwinObservationReadout", () => {
  it("renders compact live frames without waiting for lifecycle polling", async () => {
    const subscribe = vi.fn(async (onFrame: Parameters<NonNullable<Parameters<typeof TwinObservationReadout>[0]["subscribe"]>>[0]) => {
      onFrame({
        state: "PAIRED",
        vehicleLabel: "Drone#1 - Nike",
        liveSequence: 30,
        pairedCycleCount: 1265,
        channelRecordCount: 70820,
        observed: {
          ...status.observed!,
          sourceTimestampS: 12.2,
          batteryVoltage: 3.84,
          ranges: { ...status.observed!.ranges!, frontM: 0.3 },
        },
      });
      onFrame({
        state: "PAIRED",
        vehicleLabel: "Drone#1 - Nike",
        liveSequence: 31,
        pairedCycleCount: 1265,
        channelRecordCount: 70840,
        observed: {
          ...status.observed!,
          sourceTimestampS: 12.4,
          batteryVoltage: 3.812,
          ranges: { ...status.observed!.ranges!, frontM: 0.25 },
        },
      });
    });
    const { unmount } = render(
      <TwinObservationReadout status={status} subscribe={subscribe} expanded onToggle={() => undefined} />,
    );

    const summary = screen.getByRole("button", { name: "Collapse drone telemetry" });
    await waitFor(() => expect(within(summary).getByText("3.812 V")).toBeVisible());
    expect(within(summary).getByText("+0.6° · -1.1°")).toBeVisible();
    expect(within(summary).getByText("0.040 m")).toBeVisible();
    expect(await screen.findByRole("img", { name: /Battery voltage 3.812 to 3.840 V over/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Attitude" }));
    expect(within(screen.getByLabelText("Orientation measured history")).getByRole("img")).toBeVisible();
    expect(within(screen.getByLabelText("Acceleration measured history")).getByRole("img")).toBeVisible();
    expect(within(screen.getByLabelText("Gyro measured history")).getByRole("img")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Motors" }));
    expect(within(screen.getByLabelText("Motor output measured history")).getByRole("img")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Ranges" }));
    expect(within(screen.getByLabelText("Obstacle ranges measured history")).getByRole("img")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Power" }));
    expect(within(screen.getByLabelText("Battery voltage measured history")).getByRole("img")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    expect(within(screen.getByLabelText("Link quality measured history")).getByRole("img")).toBeVisible();
    expect(within(screen.getByLabelText("Packet rate measured history")).getByRole("img")).toBeVisible();
    expect(screen.queryByText("70,840 channel records")).not.toBeInTheDocument();
    expect(subscribe).toHaveBeenCalledOnce();
    unmount();
  });

  it("does not let a cached current frame mask polled stale or error state", async () => {
    const connected = { ...status, sessionId: "twin-current" };
    const subscribe = vi.fn(async (onFrame: Parameters<NonNullable<Parameters<typeof TwinObservationReadout>[0]["subscribe"]>>[0]) => {
      onFrame({
        state: "PAIRED",
        vehicleLabel: "Drone#1 - Nike",
        liveSequence: 32,
        pairedCycleCount: 1265,
        channelRecordCount: 70840,
        observed: {
          ...status.observed!,
          batteryVoltage: 3.812,
        },
      });
    });
    const { rerender, unmount } = render(
      <TwinObservationReadout status={connected} subscribe={subscribe} expanded onToggle={() => undefined} />,
    );

    const summary = screen.getByRole("button", { name: "Collapse drone telemetry" });
    await waitFor(() => expect(within(summary).getByText("3.812 V")).toBeVisible());

    rerender(
      <TwinObservationReadout
        status={{
          ...connected,
          observed: { ...connected.observed!, freshness: "STALE" },
        }}
        subscribe={subscribe}
        expanded
        onToggle={() => undefined}
      />,
    );
    expect(within(summary).getByText("3.906 V")).toBeVisible();
    expect(within(summary).getByText("Stale reading")).toBeVisible();
    expect(within(summary).queryByText("3.812 V")).not.toBeInTheDocument();

    rerender(
      <TwinObservationReadout
        status={{
          ...connected,
          state: "ERROR",
          observed: undefined,
          predicted: undefined,
          lastErrorCode: "TELEMETRY_STREAM_FAILED",
          lastErrorMessage: "Too many packets lost",
        }}
        subscribe={subscribe}
        expanded
        onToggle={() => undefined}
      />,
    );
    expect(within(summary).getAllByText("Missing")).toHaveLength(3);
    expect(within(summary).queryByText("ERROR")).not.toBeInTheDocument();
    expect(within(summary).queryByText("3.812 V")).not.toBeInTheDocument();
    unmount();
  });

  it("shows literal props-off diagnostics without predicted substitution", () => {
    const onToggle = () => rerender(
      <TwinObservationReadout status={status} expanded onToggle={() => undefined} />,
    );
    const { rerender } = render(
      <TwinObservationReadout status={status} expanded={false} onToggle={onToggle} />,
    );
    expect(screen.queryByText("Drone#1 - Nike")).not.toBeInTheDocument();
    const summary = screen.getByRole("button", { expanded: false });
    expect(within(summary).getByText("3.906 V")).toBeVisible();
    expect(within(summary).getByText("+0.6° · -1.1°")).toBeVisible();
    expect(within(summary).getByText("Yaw +1.7°")).toBeVisible();
    expect(within(summary).getByText("0.040 m")).toBeVisible();
    expect(within(summary).getByText("Down")).toBeVisible();
    expect(screen.queryByText("70,784 channel records")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    const missionOverview = screen.getByRole("region", { name: "Mission overview telemetry" });
    expect(within(missionOverview).getByLabelText("Battery measured history")).toBeVisible();
    expect(within(missionOverview).getByLabelText("Tilt measured history")).toBeVisible();
    expect(within(missionOverview).getByLabelText("Nearest measured history")).toBeVisible();
    expect(within(missionOverview).getByText(/Observed.*last 60 seconds/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Overview" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Overview telemetry")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Position telemetry")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    const linkTelemetry = screen.getByLabelText("Link telemetry");
    const linkHealth = within(linkTelemetry).getByLabelText("Link health");
    expect(linkHealth).toBeVisible();
    expect(within(linkTelemetry).getByText("DEGRADED")).toBeVisible();
    expect(within(linkHealth).getByText("PAIRED")).toBeVisible();
    expect(within(linkTelemetry).getByText("1.25% packet loss")).toBeVisible();
    expect(within(linkTelemetry).getByText("987 received · 13 lost")).toBeVisible();
    expect(within(linkTelemetry).getByText(/Boundary · RF_ACK_LOSS/)).toBeVisible();
    fireEvent.click(within(linkTelemetry).getByText("Technical details"));
    expect(within(linkTelemetry).getByText("1,264")).toBeVisible();
    expect(within(linkTelemetry).getByText("70,784")).toBeVisible();
    expect(within(linkTelemetry).getByText("0/1 · 2 saturation events")).toBeVisible();
    expect(within(linkTelemetry).getByText("12.400 s · raw 1933.909 s")).toBeVisible();
    expect(within(linkTelemetry).queryByText("Predicted clock")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Power" }));
    expect(within(screen.getByLabelText("Power telemetry")).getByText("Measured voltage")).toBeVisible();
    expect(screen.getByText("Current and battery percentage are unavailable from this observer.")).toBeVisible();
    expect(screen.queryByText("Predicted voltage")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ranges" }));
    expect(screen.getByText("0–1 m close-range scale · readings beyond 2 m are violet; exact measured values remain shown.")).toBeVisible();
    expect(screen.getByText("3.53%")).toBeVisible();
    expect(screen.getByText("Downward optical flow · VALID")).toBeVisible();
    expect(screen.getAllByText("2.400 m").find((item) => item.closest(".twin-range-reading"))?.closest(".twin-range-reading")).toHaveClass("range-far");
    fireEvent.click(screen.getByRole("button", { name: "Position" }));
    expect(screen.getByText("Position unavailable")).toBeVisible();
  });

  it("keeps measured sensors live from the mission link while observation is suspended", async () => {
    const suspended = {
      ...status,
      state: "SUSPENDED" as const,
      sessionId: undefined,
      observed: undefined,
      telemetryOwner: "PHYSICAL_OPERATION" as const,
      operationSampleCount: 0,
      suspensionReason: "Physical mission owns the radio",
    };
    const subscribe = vi.fn(async (onFrame: Parameters<NonNullable<Parameters<typeof TwinObservationReadout>[0]["subscribe"]>>[0]) => {
      onFrame({
        state: "SUSPENDED",
        vehicleLabel: "Drone#1 - Nike",
        liveSequence: 12,
        pairedCycleCount: 0,
        channelRecordCount: 0,
        telemetryOwner: "PHYSICAL_OPERATION",
        operationSampleCount: 12,
        observed: status.observed,
      });
    });
    const { container, unmount } = render(
      <TwinObservationReadout status={suspended} subscribe={subscribe} expanded onToggle={() => undefined} />,
    );
    const readout = within(container);

    const summary = readout.getByRole("button", { name: "Collapse drone telemetry" });
    await waitFor(() => expect(within(summary).getByText("3.906 V")).toBeVisible());
    expect(readout.queryByText("MISSION TELEMETRY")).not.toBeInTheDocument();
    expect(readout.queryByText("12")).not.toBeInTheDocument();
    expect(readout.getByText(/Physical link.*last 60 seconds/)).toBeVisible();
    fireEvent.click(readout.getByRole("button", { name: "Attitude" }));
    const attitudeTelemetry = readout.getByLabelText("Attitude telemetry");
    expect(within(attitudeTelemetry).queryByRole("heading", { name: "Attitude" })).not.toBeInTheDocument();
    expect(within(attitudeTelemetry).queryByText(/Measured.*CURRENT/)).not.toBeInTheDocument();
    expect(within(attitudeTelemetry).getAllByText("+9.81 m/s²").length).toBeGreaterThan(0);
    fireEvent.click(readout.getByRole("button", { name: "Motors" }));
    expect(readout.getByText("41.25%")).toBeVisible();
    expect(readout.getByText("45.00%")).toBeVisible();
    fireEvent.click(readout.getByRole("button", { name: "Ranges" }));
    expect(readout.getAllByText("0.400 m").some((item) => item.closest(".twin-range-reading"))).toBe(true);
    expect(subscribe).toHaveBeenCalledOnce();
    unmount();
  });
});
