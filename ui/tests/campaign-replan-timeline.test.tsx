import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReplanTimeline } from "../app/components/CampaignLab";

describe("campaign replan timeline", () => {
  it("shows sensor persistence before dispatch and exact fallback", () => {
    render(<ReplanTimeline analysis={{ replan_timeline: [
      { stage: "PERCEPTION_PERSISTED", observation_id: "obs-1", received_timestamp_s: 2.12, observation_sha256: "a".repeat(64) },
      { event_id: "rock-appears", execution_disposition: "DISPATCHED", decision_sha256: "b".repeat(64) },
      { stage: "SAFE_FALLBACK_EXECUTED", fallback_command: "STOP_AND_HOLD", reason: "late changed world" },
    ] } as never} />);
    expect(screen.getByText("Perception persisted")).toBeTruthy();
    expect(screen.getByText("Dispatched")).toBeTruthy();
    expect(screen.getByText(/Stop and hold/)).toBeTruthy();
  });
});
