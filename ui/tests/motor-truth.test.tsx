import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MotionQualityEvidence } from "../app/components/CampaignLab";

describe("motor physical truth", () => {
  it("renders the independent torque and IMU relationship", () => {
    render(<MotionQualityEvidence analysis={{ motion_quality: [], physical_truth: [{
      vehicle_id: "Alpha",
      paired_sample_count: 80,
      maneuver_sample_count: 36,
      sign_agreement_fraction: .98,
      normalized_error_p95: .06,
      maximum_source_pairing_error_s: 0,
      all_equal_moving_sample_count: 0,
      saturated_maneuver_sample_count: 0,
      failures: [],
      passed: true,
      analysis_sha256: "c".repeat(64),
    }] } as never} />);
    expect(screen.getByText(/Torque ↔ IMU sign agreement 0.980/)).toBeTruthy();
    expect(screen.getByText("Physical oracle passed")).toBeTruthy();
    expect(screen.getByText(/All-equal moving samples 0/)).toBeTruthy();
  });
});
