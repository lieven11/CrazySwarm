import { afterEach, describe, expect, it, vi } from "vitest";
import { adaptDashboard, adaptDashboardState, ControlApi } from "../app/lib/api";

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

  it("uses declared backend role and authority without adapter-name inference", () => {
    const model = adaptDashboard({
      mode: "SIM",
      selected_vehicle_id: "isaac01",
      vehicles: [{
        identity: { vehicle_id: "isaac01", display_name: "Isaac", adapter: "opaque-worker-v7" },
        backend: { role: "ISAAC_SIM", authority: "SIMULATION" },
        capabilities: { decks: [] },
        selected: true,
        state: "READY",
        telemetry: null,
        control_lease: null,
      }],
      mission_runs: [],
    }, [], world, fidelity, "control-center-ui");

    expect(model.vehicles[0]).toMatchObject({
      adapter: "opaque-worker-v7",
      backendRole: "ISAAC_SIM",
      authorityClass: "SIMULATION",
    });
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
    const result = { mission_run_id: "run-1", execution_session_id: "execution-1", member_count: 2, status: "SCHEDULED" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "http://127.0.0.1:8000", token: "local-token", clientId: "control-center-ui" });
    await expect(api.startMissionFile("py-123", "SIMULATION")).resolves.toEqual(result);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8000/api/v1/mission-files/py-123/start");
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify({ execution_mode: "SIMULATION" }),
      headers: expect.objectContaining({ "X-Local-Token": "local-token", "X-Client-ID": "control-center-ui" }),
    });
  });

  it("sends the explicit low-battery confirmation only after operator consent", async () => {
    const result = { mission_run_id: "run-risk", execution_session_id: "execution-risk", member_count: 1, status: "SCHEDULED" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });

    await api.startMissionFile("py-risk", "SIMULATION", true);

    expect(fetchMock).toHaveBeenCalledWith(
      "/control-api/api/v1/mission-files/py-risk/start",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          execution_mode: "SIMULATION",
          confirm_low_battery_risk: true,
        }),
      }),
    );
  });

  it("approves and starts the exact reviewed plan hash", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        approval_id: "approval-1",
        plan_sha256: "plan-hash",
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        mission_run_id: "run-approved",
        execution_session_id: "execution-approved",
        member_count: 1,
        status: "SCHEDULED",
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });

    const approval = await api.approveMissionPlan(
      "py-approved",
      "plan-hash",
      ["BATTERY_BELOW_TAKEOFF_MINIMUM"],
    );
    await api.startMissionFile("py-approved", "SIMULATION", true, approval);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/control-api/api/v1/mission-files/py-approved/approve",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      body: JSON.stringify({
        expected_plan_sha256: "plan-hash",
        acknowledged_finding_codes: ["BATTERY_BELOW_TAKEOFF_MINIMUM"],
      }),
    });
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      body: JSON.stringify({
        execution_mode: "SIMULATION",
        confirm_low_battery_risk: true,
        approval_id: "approval-1",
        expected_plan_sha256: "plan-hash",
      }),
    });
  });

  it("keeps home reset and battery recharge as separate simulator actions", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ position_m: { x: 0, y: 0, z: 0 } }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ battery_percent: 37.5 }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });

    await api.resetSimulationPose("sim01");
    await expect(api.setSimulationBattery("sim01", 37.5)).resolves.toBe(37.5);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/control-api/api/v1/simulation/vehicles/sim01/clock", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ action: "reset_pose" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/control-api/api/v1/simulation/vehicles/sim01/clock", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ action: "recharge", battery_percent: 37.5 }),
    }));
  });

  it("maps only backend-authored telemetry CSV artifacts onto the control proxy", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify([{
      run_id: "run-csv-1",
      mission_id: "hover",
      vehicle_id: "sim01",
      status: "SUCCEEDED",
      configuration_hash: "abc123",
      started_at_utc: "2026-08-08T13:22:43Z",
      artifacts: [{
        kind: "TELEMETRY_CSV",
        filename: "hover_run-csv-1_telemetry-v1.csv",
        media_type: "text/csv",
        schema_version: "run-telemetry-v1",
        download_url: "/api/v1/run-files/run-csv-1/telemetry.csv",
        available: true,
        unavailable_reason: null,
        row_count: 42,
      }],
    }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });

    await expect(api.runHistory()).resolves.toEqual([{
      runId: "run-csv-1",
      missionId: "hover",
      vehicleId: "sim01",
      status: "SUCCEEDED",
      configurationHash: "abc123",
      startedAtUtc: "2026-08-08T13:22:43Z",
      telemetryCsv: {
        kind: "TELEMETRY_CSV",
        filename: "hover_run-csv-1_telemetry-v1.csv",
        mediaType: "text/csv",
        schemaVersion: "run-telemetry-v1",
        downloadUrl: "/control-api/api/v1/run-files/run-csv-1/telemetry.csv",
        available: true,
        unavailableReason: undefined,
        rowCount: 42,
      },
    }]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/control-api/api/v1/runs?limit=100",
      expect.any(Object),
    );
  });

  it("maps one combined CSV for a multi-drone mission", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify([{
      mission_execution_id: "run-fleet-1",
      mission_id: "py-crossing",
      mission_name: "crossing_route_separation",
      status: "ABORTED",
      started_at_utc: "2026-08-08T13:08:18Z",
      completed_at_utc: "2026-08-08T13:09:02Z",
      telemetry_row_count: 5226,
      artifact: {
        run_ids: ["child-south", "child-west"],
        vehicle_ids: ["cross_south", "cross_west"],
        filename: "crossing-route-separation_run-fleet-1_telemetry-v1.csv",
        download_url: "/api/v1/run-files/run-fleet-1/telemetry.csv",
        available: true,
        telemetry_row_count: 5226,
        size_bytes: 9123456,
        sha256: "abc",
      },
    }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });

    await expect(api.runFiles()).resolves.toEqual([expect.objectContaining({
      missionExecutionId: "run-fleet-1",
      missionName: "crossing_route_separation",
      status: "ABORTED",
      telemetryRowCount: 5226,
      filename: "crossing-route-separation_run-fleet-1_telemetry-v1.csv",
      downloadUrl: "/control-api/api/v1/run-files/run-fleet-1/telemetry.csv",
      available: true,
      sizeBytes: 9123456,
    })]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/control-api/api/v1/run-files?limit=100",
      expect.any(Object),
    );
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

  it("maps a read-only role-specific mission preview", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      mission_id: "py-preview",
      source_sha256: "abc123",
      plan_sha256: "plan-hash",
      plan: {
        plan_id: "plan-preview",
        status: "APPROVED",
        findings: [],
        planning: {
          plugin_selections: [{
            plugin_id: "route.direct",
            kind: "ROUTE_PLANNER",
            implementation_version: "1.0.0",
            capabilities_used: ["DIRECT"],
            manifest_sha256: "manifest-hash",
          }],
          route_plans: [{
            role_id: "left",
            status: "READY",
            expected_duration_s: 4,
            expected_energy_percent: 2,
            route_length_m: 1,
            waypoints: [{}, {}],
            findings: [],
          }],
          mission_intent: {
            objective: "Execute preview",
            phases: [{
              phase_id: "explicit-actions",
              objective: "Execute actions",
              role_ids: ["left"],
              maximum_duration_s: 30,
            }],
          },
          safety_case: { safety_case_sha256: "safety-hash" },
        },
      },
      vehicles: [{
        role_id: "left",
        vehicle_id: "drone-left",
        display_name: "Left drone",
        initial_role: "ACTIVE",
        home_m: { x: -0.8, y: 0, z: 0 },
        start_m: { x: -0.95, y: 0.2, z: 0 },
        battery_percent: 37.5,
        minimum_battery_percent: 55,
        existing_vehicle: true,
        backend_role: "FAST_SIM",
        vehicle_state: "DISCONNECTED",
        preview_fidelity: "EXACT_ROLE",
        planned_commands: [
          { action: "takeoff", arguments: { height_m: 0.3 } },
          { action: "move_relative", arguments: { x_m: -0.1 } },
          { action: "land", arguments: {} },
        ],
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });

    await expect(api.previewMission("py-preview")).resolves.toMatchObject({
      missionId: "py-preview",
      plan: {
        id: "plan-preview",
        status: "APPROVED",
        plugins: [{ id: "route.direct" }],
      },
      vehicles: [{
        roleId: "left",
        vehicleId: "drone-left",
        home: { x: -0.8, y: 0, z: 0 },
        start: { x: -0.95, y: 0.2, z: 0 },
        batteryPercent: 37.5,
        minimumBatteryPercent: 55,
        existingVehicle: true,
        backendRole: "FAST_SIM",
        vehicleState: "DISCONNECTED",
        previewFidelity: "EXACT_ROLE",
      }],
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/control-api/api/v1/mission-files/py-preview/preview",
      expect.any(Object),
    );
  });

  it("uses the same-origin control proxy without exposing a token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ mission_run_id: "run-2", execution_session_id: "execution-2", member_count: 1, status: "SCHEDULED" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });
    await api.startMissionFile("py-123", "SIMULATION");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/control-api/api/v1/mission-files/py-123/start");
    expect(init?.headers).toEqual(expect.not.objectContaining({ "X-Local-Token": expect.anything() }));
  });

  it("refreshes live vehicle state without refetching static dashboard context", async () => {
    const current = adaptDashboard({
      mode: "SIM",
      selected_vehicle_id: "sim01",
      vehicles: [],
      mission_runs: [],
    }, [], world, fidelity, "control-center-ui");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      mode: "SIM",
      selected_vehicle_id: "sim01",
      configured_flight_volume: null,
      safety_policy: {
        minimum_takeoff_battery_percent: 30,
        critical_battery_percent: 10,
      },
      vehicles: [{
        identity: { vehicle_id: "sim01", display_name: "Drone 1", adapter: "sim" },
        backend: { role: "FAST_SIM", authority: "SIMULATION" },
        capabilities: { decks: [] },
        selected: true,
        state: "FLYING",
        telemetry: null,
        control_lease: null,
      }],
      mission_runs: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });

    const snapshot = await api.loadLiveDashboard(current, "run-stale");
    const refreshed = snapshot.dashboard;

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toBe("/control-api/api/v1/state");
    expect(refreshed.room).toEqual(current.room);
    expect(refreshed.fidelity).toEqual(current.fidelity);
    expect(refreshed.vehicles[0]).toMatchObject({ id: "sim01", state: "FLYING" });
    expect(refreshed.safetyPolicy).toEqual({
      minimumTakeoffBatteryPercent: 30,
      criticalBatteryPercent: 10,
    });
    expect(snapshot.activeRun).toBeUndefined();
  });

  it("tracks the requested active run even when a newer run is already complete", async () => {
    const current = adaptDashboard({ mode: "SIM", vehicles: [], mission_runs: [] }, [], world, fidelity, "control-center-ui");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      mode: "SIM",
      selected_vehicle_id: "sim01",
      vehicles: [],
      mission_runs: [{
        mission_run_id: "run-active",
        mission_id: "mission-a",
        vehicle_id: "sim01",
        phase: "EXECUTING",
        parameters: {},
        started_at_monotonic_s: 10,
        result: null,
      }, {
        mission_run_id: "run-newer",
        mission_id: "mission-b",
        vehicle_id: "sim01",
        phase: "COMPLETE",
        parameters: {},
        started_at_monotonic_s: 20,
        result: { status: "SUCCEEDED" },
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "control-center-ui" });

    const snapshot = await api.loadLiveDashboard(current, "run-active");

    expect(snapshot.activeRun).toMatchObject({ id: "run-active", status: "RUNNING" });
    expect(snapshot.dashboard.latestRun).toMatchObject({ id: "run-newer", status: "SUCCEEDED" });
  });

  it("preserves the backend reason for mission and fleet failures", () => {
    const model = adaptDashboard({
      mode: "SIM",
      vehicles: [],
      mission_runs: [{
        mission_run_id: "run-failed",
        mission_id: "mission-a",
        vehicle_id: "sim01",
        phase: "COMPLETE",
        parameters: {},
        started_at_monotonic_s: 10,
        result: {
          status: "FAILED",
          reason_code: "CRITICAL_BATTERY",
          message: "modeled battery reached authoritative cutoff",
        },
      }],
      fleet_sessions: [{
        session: { execution_session_id: "execution-failed", status: "FAULT", vehicles: [] },
        deployment: { deployment_id: "deployment-failed", fleet: [], tasks: [], constraints: {} },
        binding: { backend: "FAST_SIM" },
        fleet_run_status: "FAILED",
        tasks: [{
          definition: { task_id: "cover-zone-a", zone_id: "zone-a", priority: 200 },
          state: "COMPLETED",
          owner_vehicle_id: "reserve-a",
          progress_percent: 100,
          lease_generation: 2,
        }],
        coordination: {
          vehicle_states: { "active-a": "RETURNING", "reserve-a": "ACTIVE" },
          minimum_separation_m: 0.84,
          warning_violations: 1,
          critical_violations: 0,
          authority_transition_count: 2,
          handovers: [{
            handover_id: "handover-cover-zone-a-2",
            task_id: "cover-zone-a",
            outgoing_vehicle_id: "active-a",
            incoming_vehicle_id: "reserve-a",
            phase: "FAILED",
            incoming_lease_generation: 2,
            takeover_confirmed: true,
            reason: "LOW_ENERGY_MARGIN",
            release_reason: "LOCALIZATION_INVALID",
          }],
          dock_snapshots: [{
            dock_id: "dock-a",
            health: "AVAILABLE",
            reservations: [{
              vehicle_id: "active-a",
              state: "READY",
              modeled_charging_confirmed: true,
            }],
          }],
        },
        execution: {
          created_at_monotonic_s: 12,
          mission_id: "mission-a",
          reason_code: "SEPARATION_CRITICAL",
          message: "minimum separation could not be maintained",
        },
      }],
    }, [], world, fidelity, "control-center-ui");

    expect(model.latestRun).toMatchObject({
      resultReasonCode: "CRITICAL_BATTERY",
      resultMessage: "modeled battery reached authoritative cutoff",
    });
    expect(model.fleetSessions[0]).toMatchObject({
      missionId: "mission-a",
      resultReasonCode: "SEPARATION_CRITICAL",
      resultMessage: "minimum separation could not be maintained",
      vehicleStates: { "active-a": "RETURNING", "reserve-a": "ACTIVE" },
      minimumSeparationM: 0.84,
      warningViolations: 1,
      criticalViolations: 0,
      authorityTransitionCount: 2,
      tasks: [{ ownerVehicleId: "reserve-a", leaseGeneration: 2 }],
      handovers: [{
        outgoingVehicleId: "active-a",
        incomingVehicleId: "reserve-a",
        incomingLeaseGeneration: 2,
        takeoverConfirmed: true,
      }],
      docks: [{ reservations: [{ vehicleId: "active-a", state: "READY" }] }],
    });
  });

  it("preserves static context when adapting a live state snapshot", () => {
    const current = adaptDashboard({ mode: "SIM", vehicles: [], mission_runs: [] }, [], world, fidelity, "control-center-ui");
    const refreshed = adaptDashboardState(current, {
      mode: "SIM",
      selected_vehicle_id: "sim01",
      vehicles: [],
      mission_runs: [],
    }, "control-center-ui");
    expect(refreshed.room).toEqual(current.room);
    expect(refreshed.fidelity).toEqual(current.fidelity);
  });

  it("maps every fleet member's immutable deployment home", () => {
    const model = adaptDashboard({
      mode: "SIM",
      vehicles: [],
      mission_runs: [],
      fleet_sessions: [{
        session: {
          execution_session_id: "execution-1",
          status: "READY",
          vehicles: [
            { vehicle_id: "drone-left" },
            { vehicle_id: "drone-right" },
          ],
        },
        deployment: {
          deployment_id: "deployment-1",
          fleet: [
            { vehicle_id: "drone-left", home: { x: -1, y: -0.4, z: 0 } },
            { vehicle_id: "drone-right", home: { x: 1, y: 0.4, z: 0 } },
          ],
          tasks: [],
          constraints: {},
        },
        binding: { backend: "FAST_SIM" },
        execution: { created_at_monotonic_s: 12 },
      }],
    }, [], world, fidelity, "control-center-ui");

    expect(model.fleetSessions[0].vehicles.map((vehicle) => ({ id: vehicle.id, home: vehicle.home }))).toEqual([
      { id: "drone-left", home: { x: -1, y: -0.4, z: 0 } },
      { id: "drone-right", home: { x: 1, y: 0.4, z: 0 } },
    ]);
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
