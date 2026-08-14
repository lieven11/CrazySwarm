import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TwinSessionPanel, twinSourceLabel } from "../app/components/TelemetryDock";

describe("digital twin session", () => {
  it("never labels a configured simulator source as measured real", async () => {
    const onLoad = vi.fn().mockResolvedValue({
      sessionId: "twin-1",
      timelineSha256: "d".repeat(64),
      samples: [
        { sampleSha256: "a".repeat(64), side: "OBSERVED", channelId: "pose.position", sourceTimestampS: 1, receivedTimestampS: 1.02, availability: "AVAILABLE", quality: "GOOD", unit: "m", frame: "world", value: { x: .1, y: 0, z: .4 } },
        { sampleSha256: "b".repeat(64), side: "PREDICTED", channelId: "pose.position", sourceTimestampS: 1, receivedTimestampS: 1.01, availability: "AVAILABLE", quality: "GOOD", unit: "m", frame: "world", value: { x: .09, y: 0, z: .4 } },
      ],
      residuals: [],
    });
    render(<TwinSessionPanel twin={{
      id: "twin-1",
      status: "ACTIVE",
      observedVehicleId: "Alpha",
      simulatedVehicleId: "Alpha-model",
      observedSourceClass: "CONFIGURED",
      simulatedSourceClass: "SIMULATED_MODEL",
      groundTruthAvailable: true,
    }} onLoad={onLoad} />);
    await waitFor(() => expect(screen.getByText(/Immutable review/)).toBeTruthy());
    expect(screen.getByText(/Configured source → Simulated model/)).toBeTruthy();
    expect(screen.queryByText(/Measured real adapter/)).toBeNull();
    expect(screen.getByRole("img", { name: /Observed and predicted world path overlay/ })).toBeTruthy();
    expect(twinSourceLabel("MEASURED_REAL")).toBe("Measured real adapter");
  });
});
