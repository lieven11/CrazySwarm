import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MotionQualityEvidence } from "../app/components/CampaignLab";

const analysis = {
  motion_quality: [{
    vehicle_id: "Alpha",
    contract_sha256: "a".repeat(64),
    csv_sha256: "b".repeat(64),
    sample_count: 120,
    vector: {
      speed_compliance_fraction: .97,
      speed_ripple_m_s: .04,
      angular_rate_p95_rad_s: .52,
      terminal_secondary_peak_m_s: .021,
    },
    failed_guards: ["angular_rate_p95_rad_s", "terminal_secondary_peak_m_s"],
    missing_guards: [],
    analysis_sha256: "c".repeat(64),
  }],
  physical_truth: [],
};

describe("campaign motion quality evidence", () => {
  it("renders scalar speed and shakiness as separate guards", () => {
    render(<MotionQualityEvidence analysis={analysis as never} />);
    expect(screen.getByText("Speed compliance fraction")).toBeTruthy();
    expect(screen.getByText("Angular rate p95 rad s")).toBeTruthy();
    expect(screen.getByText("Terminal secondary peak m s")).toBeTruthy();
    expect(screen.getByText("2 failed")).toBeTruthy();
  });
});
