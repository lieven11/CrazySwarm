import { afterEach, describe, expect, it, vi } from "vitest";
import { ControlApi } from "../app/lib/api";

const status = {
  schema_version: 1,
  state: "PAIRED",
  configured: true,
  vehicle_label: "Lab Crazyflie",
  redacted_uri: "radio://0/80/2M/******E701",
  uri_sha256: "a".repeat(64),
  command_readiness: "UNQUALIFIED",
  command_readiness_issues: ["MISSING_DECK_BCMULTIRANGER"],
  session_id: "twin-test",
  observed_source_class: "TEST",
  predicted_source_class: "TEST",
  provenance: "TEST",
  test_only: true,
  sample_count: 12,
  last_failure_kind: "RF_ACK_LOSS",
  reconnect_attempt: 5,
  reconnect_mode: "LOW_DUTY",
  observed: {
    role: "OBSERVED",
    vehicle_id: "physical:2645312894b94ede",
    source_class: "TEST",
    freshness: "CURRENT",
    frame: "home",
    source_clock_id: "test-fixture",
    source_epoch: 1,
    raw_source_timestamp_s: 42.2,
    position_availability: "INCOMPATIBLE",
    position_m: { x: 0, y: 0, z: 0 },
    battery_availability: "AVAILABLE",
    battery_voltage_v: 4.05,
    motor_pwm_percent: [41.25, 42.5, 43.75, 45],
    transport: {
      kind: "physical_radio",
      source_class: "MEASURED_REAL",
      delivery_quality_percent: 98.75,
      packet_loss_percent: 1.25,
      radio: {
        connection_epoch: 3,
        state: "DEGRADED",
        failure_kind: "RF_ACK_LOSS",
        acked_packet_count: 987,
        lost_packet_count: 13,
        packet_loss_percent: 1.25,
        consecutive_lost_packet_count: 0,
        maximum_consecutive_lost_packet_count: 7,
        outbound_queue_depth: 0,
        outbound_queue_capacity: 1,
        queue_saturation_count: 2,
        usb_error_count: 0,
      },
    },
  },
  predicted: {
    role: "PREDICTED",
    vehicle_id: "fast-sim:2645312894b94ede",
    source_class: "TEST",
    freshness: "STALE",
    frame: "home",
    source_clock_id: "test-fixture",
    source_epoch: 1,
    raw_source_timestamp_s: 0.1,
    position_availability: "INCOMPATIBLE",
    position_m: { x: 0, y: 0, z: 0 },
    battery_availability: "MISSING",
    battery_voltage_v: null,
  },
};

describe("physical twin API client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("preserves visible test provenance and command-readiness gaps", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(status), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "test-client" });

    await expect(api.physicalTwinStatus()).resolves.toEqual(expect.objectContaining({
      state: "PAIRED",
      provenance: "TEST",
      testOnly: true,
      observedSourceClass: "TEST",
      predictedSourceClass: "TEST",
      commandReadinessIssues: ["MISSING_DECK_BCMULTIRANGER"],
      sampleCount: 12,
      lastFailureKind: "RF_ACK_LOSS",
      reconnectAttempt: 5,
      reconnectMode: "LOW_DUTY",
      observed: expect.objectContaining({
        vehicleId: "physical:2645312894b94ede",
        freshness: "CURRENT",
        positionAvailability: "INCOMPATIBLE",
        batteryVoltage: 4.05,
        motorPwmPercent: [41.25, 42.5, 43.75, 45],
        transport: expect.objectContaining({
          packetLossPercent: 1.25,
          radio: expect.objectContaining({
            ackedPacketCount: 987,
            lostPacketCount: 13,
            queueSaturationCount: 2,
          }),
        }),
      }),
      predicted: expect.objectContaining({
        vehicleId: "fast-sim:2645312894b94ede",
        freshness: "STALE",
        batteryAvailability: "MISSING",
      }),
    }));
  });

  it("sends the complete exact URI only to the local binding endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        ...status,
        state: "DISCONNECTED",
        session_id: null,
        provenance: null,
        test_only: false,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const api = new ControlApi({ endpoint: "/control-api", clientId: "test-client" });

    await api.configurePhysicalTwin("radio://0/80/2M/E7E7E7E701", "Lab Crazyflie");
    expect(fetchMock).toHaveBeenCalledWith(
      "/control-api/api/v1/physical-twin/binding",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          selected_uri: "radio://0/80/2M/E7E7E7E701",
          vehicle_label: "Lab Crazyflie",
          confirm_exact_uri: true,
        }),
      }),
    );
  });

  it("parses compact physical-twin server events incrementally", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("id: 8\nevent: physical-twin\ndata: {\"schema_version\":1,\"state\":\"PAIRED\","));
        controller.enqueue(encoder.encode("\"vehicle_label\":\"Lab Crazyflie\",\"live_sequence\":8,\"paired_cycle_count\":3,\"channel_record_count\":168,\"observed\":"));
        controller.enqueue(encoder.encode(`${JSON.stringify(status.observed)}}\n\n`));
        controller.close();
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }));
    const api = new ControlApi({ endpoint: "/control-api", clientId: "test-client" });
    const frames: unknown[] = [];

    await api.streamPhysicalTwin((frame) => frames.push(frame), new AbortController().signal);

    expect(frames).toEqual([expect.objectContaining({
      state: "PAIRED",
      liveSequence: 8,
      pairedCycleCount: 3,
      channelRecordCount: 168,
      observed: expect.objectContaining({ batteryVoltage: 4.05 }),
    })]);
  });
});
