import { describe, expect, it } from "vitest";
import { campaignRunHistoryRows } from "../app/components/CampaignLab";

const run = (runId: string, supersededAtUtc?: string) => ({
  run: {
    run_id: runId,
    mode: "AUTOMATED_ACCELERATED",
    status: "SUCCEEDED",
    locked_inputs: {
      case_id: "1d.takeoff_hover_land.canonical_nominal",
      case_sha256: "a".repeat(64),
      seed: 1,
      backend_profile_id: "fast-sim-v1",
      configuration_sha256: "b".repeat(64),
      planner_implementation_id: "planner",
      planner_implementation_version: "1",
      planner_settings_sha256: "c".repeat(64),
    },
    requested_at_utc: "2026-08-14T00:00:00Z",
    superseded_at_utc: supersededAtUtc,
  },
  number: 1,
});

describe("campaign run history generations", () => {
  it("places one divider before the first old run", () => {
    const rows = campaignRunHistoryRows([
      run("campaign-run-current"),
      run("campaign-run-old-2", "2026-08-14T12:00:00Z"),
      run("campaign-run-old-1", "2026-08-14T12:00:00Z"),
    ] as never);

    expect(rows.map((row) => row.showOldDivider)).toEqual([false, true, false]);
  });
});
