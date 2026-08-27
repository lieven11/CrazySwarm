import { describe, expect, it } from "vitest";

import { controlApiTimeoutMs } from "../worker/control-api-timeout";

describe("control API proxy timeout", () => {
  it("allows physical mission mutations to complete their radio handoff", () => {
    expect(controlApiTimeoutMs("/api/v1/physical-twin/lab/physical-flight/start", "POST"))
      .toBe(90_000);
    expect(controlApiTimeoutMs("/api/v1/physical-twin/lab/physical-flight/abort", "POST"))
      .toBe(90_000);
  });

  it("keeps read-only lab polling on the short request budget", () => {
    expect(controlApiTimeoutMs("/api/v1/physical-twin/lab/physical-flight", "GET"))
      .toBe(5_000);
  });

  it("allows the physical connection handshake to use its backend budget", () => {
    expect(controlApiTimeoutMs("/api/v1/physical-twin/connect", "POST"))
      .toBe(60_000);
    expect(controlApiTimeoutMs("/api/v1/physical-twin/confirm", "POST"))
      .toBe(60_000);
    expect(controlApiTimeoutMs("/api/v1/physical-twin/disconnect", "POST"))
      .toBe(60_000);
  });

  it("keeps physical connection status reads on the short request budget", () => {
    expect(controlApiTimeoutMs("/api/v1/physical-twin/status", "GET"))
      .toBe(5_000);
  });
});
