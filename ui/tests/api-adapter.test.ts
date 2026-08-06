import { afterEach, describe, expect, it, vi } from "vitest";
import { adaptDashboard, ControlApi } from "../app/lib/api";

const world = {
  schema_version: 2,
  world: {
    world_id: "lab-a",
    width_m: 5,
    depth_m: 4,
    height_m: 2.4,
    obstacles: [],
  },
  vehicles: [{ vehicle_id: "sim01", position_m: { x: 0.2, y: -0.1, z: 0 } }],
};

const fidelity = {
  manifest_id: "mission-kinematics-v1",
  source_class: "SIMULATED_MODEL",
  model: "deterministic mission-level indoor kinematics",
  modeled_outputs: ["position", "range_rays"],
  omitted_outputs: ["physical_radio_link_quality"],
  limitations: ["not a flight-dynamics model"],
};

describe("control API view adapter", () => {
  afterEach(() => vi.restoreAllMocks());

  it("never inherits flying fixture state when the API reports a disconnected vehicle", () => {
    const model = adaptDashboard({
      mode: "SIM",
      selected_vehicle_id: "sim01",
      vehicles: [{
        identity: { vehicle_id: "sim01", display_name: "Drone 1", adapter: "sim" },
        capabilities: { decks: [] },
        selected: true,
        state: "DISCONNECTED",
        telemetry: null,
        control_lease: null,
        control_state: { armed: null, flying: null },
      }],
      mission_runs: [],
    }, [], world, fidelity, "control-center-ui");

    expect(model.apiConnected).toBe(true);
    expect(model.vehicles[0]).toMatchObject({
      state: "DISCONNECTED",
      commandAuthority: false,
      observationStatus: "UNAVAILABLE",
      observationClass: "UNAVAILABLE",
    });
    expect(model.vehicles[0].telemetry).toBeUndefined();
    expect(model.room).toMatchObject({ id: "lab-a", version: 2, home: { x: 0.2, y: -0.1, z: 0 } });
    expect(model.fidelity?.omittedOutputs).toContain("physical_radio_link_quality");
  });

  it("grants the display authority flag only to the matching lease owner", () => {
    const model = adaptDashboard({
      mode: "SIM",
      selected_vehicle_id: "sim01",
      vehicles: [{
        identity: { vehicle_id: "sim01", display_name: "Drone 1", adapter: "sim" },
        capabilities: { decks: [] },
        selected: true,
        state: "ARMED",
        observation: {
          status: "ACTIVE",
          source_class: "SIMULATED_MODEL",
          run_id: "run-1",
        },
        telemetry: {
          recorded_at_utc: new Date().toISOString(),
          source_timestamp_s: 12,
          received_timestamp_s: 12.03,
          simulation_timestamp_s: 12,
          replay_timestamp_s: null,
          source_clock_id: "fast-sim-sim01",
          source_clock_epoch: 1,
          telemetry: {
            armed: true,
            position_m: { x: 0, y: 0, z: 0 },
            velocity_m_s: { x: 0, y: 0, z: 0 },
            attitude: { roll_rad: 0, pitch_rad: 0, yaw_rad: 0 },
            battery_percent: 90,
            battery_voltage_v: 4,
            localization_quality_percent: 88,
            transport: {
              kind: "modeled_transport",
              source_class: "SIMULATED_MODEL",
              delivery_quality_percent: 95,
            },
          },
        },
        control_lease: { owner_id: "control-center-ui" },
      }],
      mission_runs: [],
    }, [], world, fidelity, "control-center-ui");

    expect(model.vehicles[0].commandAuthority).toBe(true);
    expect(model.vehicles[0].telemetry?.armed).toBe(true);
    expect(model.vehicles[0].telemetry?.transport).toMatchObject({
      kind: "modeled_transport",
      evidenceClass: "SIMULATED_MODEL",
    });
    expect(model.vehicles[0].telemetry?.provenance).toMatchObject({
      sourceTimeS: 12,
      receiveTimeS: 12.03,
      simulationTimeS: 12,
      sourceClockId: "fast-sim-sim01",
      sourceClockEpoch: 1,
    });
  });

  it("starts an uploaded Python mission through the authenticated local API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ mission_run_id: "run-1", status: "SCHEDULED" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "http://127.0.0.1:8000", token: "local-token", clientId: "control-center-ui" });
    await expect(api.startMissionFile("py-123", "sim01", "SIMULATION")).resolves.toEqual({ mission_run_id: "run-1", status: "SCHEDULED" });
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8000/api/v1/mission-files/py-123/start");
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify({ vehicle_id: "sim01", execution_mode: "SIMULATION" }),
      headers: expect.objectContaining({ "X-Local-Token": "local-token", "X-Client-ID": "control-center-ui" }),
    });
  });

  it("uploads and maps an immutable Python mission artifact", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      mission_id: "py-123",
      mission_version: "abcdef123456",
      name: "Hover",
      description: "hover.py",
      source_kind: "UPLOADED_PYTHON",
      source_filename: "hover.py",
      source_sha256: "abcdef1234567890",
      planned_commands: [
        { action: "takeoff", arguments: { height_m: 0.3, duration_s: 2 } },
        { action: "land", arguments: { duration_s: 2 } },
      ],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });
    const source = "async def mission(drone):\n    pass\n";

    await expect(api.uploadMission("Hover", "hover.py", source)).resolves.toMatchObject({
      id: "py-123",
      sourceKind: "UPLOADED_PYTHON",
      sourceFilename: "hover.py",
      sourceSha256: "abcdef1234567890",
      plannedCommands: [
        { action: "takeoff", arguments: { height_m: 0.3, duration_s: 2 } },
        { action: "land", arguments: { duration_s: 2 } },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/control-api/api/v1/mission-files", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ name: "Hover", filename: "hover.py", source }),
    }));
  });

  it("uses the same-origin control proxy without exposing a token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ mission_run_id: "run-2", status: "SCHEDULED" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });
    await api.startMissionFile("py-123", "sim01", "SIMULATION");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/control-api/api/v1/mission-files/py-123/start");
    expect(init?.headers).toEqual(expect.not.objectContaining({ "X-Local-Token": expect.anything() }));
  });

  it("omits incomplete sensor vectors instead of filling missing components with zero", () => {
    const model = adaptDashboard({
      mode: "SIM",
      selected_vehicle_id: "sim01",
      vehicles: [{
        identity: { vehicle_id: "sim01", display_name: "Drone 1", adapter: "sim" },
        capabilities: { decks: [] },
        selected: true,
        state: "READY",
        observation: { status: "ACTIVE", source_class: "SIMULATED_MODEL", run_id: "run-1" },
        telemetry: {
          recorded_at_utc: new Date().toISOString(),
          telemetry: {
            armed: false,
            flying: false,
            imu: { acceleration_body_m_s2: { x: 0, y: 0, z: 0 } },
            flow: { ground_distance_m: 0.3 },
          },
        },
        control_lease: null,
      }],
      mission_runs: [],
    }, [], world, fidelity, "control-center-ui");

    expect(model.vehicles[0].telemetry?.imu).toBeUndefined();
    expect(model.vehicles[0].telemetry?.flow).toBeUndefined();
  });

  it("maps control state and source-backed twin residuals without inventing metrics", () => {
    const model = adaptDashboard({
      mode: "SHADOW",
      selected_vehicle_id: "real01",
      vehicles: [{
        identity: { vehicle_id: "real01", display_name: "Real 1", adapter: "cflib" },
        capabilities: { features: ["arming"], decks: [] },
        state: "READY",
        selected: true,
        telemetry: null,
        observation: { status: "NOT_STARTED", source_class: "UNAVAILABLE" },
        control_lease: null,
        control_state: { armed: true, flying: false },
      }],
      mission_runs: [],
    }, [], world, fidelity, "control-center-ui", [{
      session_id: "twin-1",
      status: "ACTIVE",
      observed_vehicle_id: "real01",
      simulated_vehicle_id: "sim01",
      ground_truth_available: false,
      latest_deviation: {
        source_timestamp_s: 12,
        observed_latency_ms: 18,
        simulated_latency_ms: 4,
        alignment_delta_ms: 2,
        frame: "world",
        validity: "VALID",
        position_m: 0.04,
        altitude_m: null,
      },
    }]);
    expect(model.vehicles[0]).toMatchObject({ armed: true, flying: false, capabilities: ["arming"] });
    expect(model.twins[0].latestDeviation).toMatchObject({
      positionM: 0.04,
      altitudeM: undefined,
      observedLatencyMs: 18,
      simulatedLatencyMs: 4,
      alignmentDeltaMs: 2,
    });

    const incomplete = adaptDashboard({
      mode: "SHADOW",
      selected_vehicle_id: "real01",
      vehicles: [],
      mission_runs: [],
    }, [], world, fidelity, "control-center-ui", [{
      session_id: "twin-2",
      status: "ACTIVE",
      observed_vehicle_id: "real01",
      simulated_vehicle_id: "sim01",
      ground_truth_available: false,
      latest_deviation: { source_timestamp_s: 12, position_m: 0.04 },
    }]);
    expect(incomplete.twins[0].latestDeviation).toBeUndefined();
  });
});
