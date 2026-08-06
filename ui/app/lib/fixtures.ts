import type { DashboardModel, Freshness, TelemetryView } from "./models";

function fixtureTelemetry(freshness: Freshness = "current"): TelemetryView {
  return {
    armed: true,
    flying: true,
    estimate: { x: 0.02, y: -0.01, z: 0.3 },
    simulatedTruth: { x: 0, y: 0, z: 0.3 },
    velocity: { x: 0, y: 0, z: 0 },
    yawRad: 0,
    batteryPercent: 99.4,
    batteryVoltage: 4.19,
    localizationPercent: 98,
    localizationLabel: "simulated",
    ranges: [],
    faults: [],
    provenance: {
      evidenceClass: "SIMULATED_MODEL",
      source: "visual-test fixture",
      timestamp: "2026-08-05T16:18:42.125Z",
      ageMs: freshness === "stale" ? 1830 : 38,
      unit: "SI",
      frame: "home",
      freshness,
    },
  };
}

/** Development-only fixture. The production dashboard has no import path to this module. */
export const testFixtureDashboard: DashboardModel = {
  mode: "SIM",
  apiConnected: false,
  serviceLabel: "TEST FIXTURE — NOT AN OBSERVATION",
  selectedVehicleId: "fixture-sim01",
  room: {
    id: "fixture-room",
    widthM: 4,
    depthM: 4,
    heightM: 2.5,
    home: { x: 0, y: 0, z: 0 },
    obstacles: [],
    source: "configured",
    frame: "world",
    version: 1,
  },
  vehicles: [{
    id: "fixture-sim01",
    name: "Visual test vehicle",
    adapter: "sim",
    selected: true,
    state: "FLYING",
    commandAuthority: false,
    observationStatus: "ACTIVE",
    observationClass: "SIMULATED_MODEL",
    observationRunId: "fixture-run",
    telemetry: fixtureTelemetry(),
    decks: [],
    capabilities: ["arming", "relative_positioning"],
    armed: true,
    flying: true,
  }],
  missions: [],
  twins: [],
};

export function fixtureForState(state: string): DashboardModel {
  const model = structuredClone(testFixtureDashboard);
  if (state === "stale" && model.vehicles[0].telemetry) {
    model.vehicles[0].telemetry = fixtureTelemetry("stale");
  }
  if (state === "disconnected") {
    model.vehicles[0] = {
      ...model.vehicles[0],
      state: "DISCONNECTED",
      observationStatus: "NOT_STARTED",
      observationClass: "UNAVAILABLE",
      observationRunId: undefined,
      telemetry: undefined,
    };
  }
  if (state === "fault") {
    model.fault = { code: "TEST_FAULT", message: "Explicit fixture fault state" };
  }
  return model;
}

// Compatibility alias for the isolated component tests only.
export const deterministicDashboard = testFixtureDashboard;
