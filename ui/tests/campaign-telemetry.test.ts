import { describe, expect, it } from "vitest";
import {
  exactCampaignTelemetrySample,
  nearestCampaignTelemetrySample,
  parseCampaignTelemetryCsv,
} from "../app/lib/campaign-telemetry";

const HEADER = [
  "vehicle_id",
  "source_timestamp_s",
  "position_z_m",
  "ground_truth_z_m",
  "velocity_x_m_s",
  "velocity_y_m_s",
  "velocity_z_m_s",
  "motor_m1_command_percent",
  "motor_m1_applied_pwm_percent",
  "motor_m2_command_percent",
  "motor_m2_applied_pwm_percent",
  "motor_m3_command_percent",
  "motor_m3_applied_pwm_percent",
  "motor_m4_command_percent",
  "motor_m4_applied_pwm_percent",
  "roll_rad",
  "pitch_rad",
  "yaw_rad",
  "imu_acceleration_x_m_s2",
  "imu_acceleration_y_m_s2",
  "imu_acceleration_z_m_s2",
  "imu_angular_velocity_x_rad_s",
  "imu_angular_velocity_y_rad_s",
  "imu_angular_velocity_z_rad_s",
].join(",");

describe("campaign telemetry chart parsing", () => {
  it("builds time-aligned per-drone speed, altitude, and motor series", () => {
    const value = parseCampaignTelemetryCsv([
      HEADER,
      '"Alpha, lead",10.0,0.42,0.40,3,4,0,51,48,52,49,53,50,54,51,1.5707963267948966,0,-1.5707963267948966,1,2,3,0.1,0.2,0.3',
      "Bravo,10.0,0.31,,0,0,2,61,,62,,63,,64,,0.1,0.2,0.3,4,5,6,0.4,0.5,0.6",
      '"Alpha, lead",11.0,0.62,0.60,0,0,1,56,53,57,54,58,55,59,56,0,0,0,2,3,4,0.2,0.3,0.4',
      "Bravo,11.0,0.51,,0,0,3,66,,67,,68,,69,,0.2,0.3,0.4,5,6,7,0.5,0.6,0.7",
    ].join("\r\n"));

    expect(value.rowCount).toBe(4);
    expect(value.durationS).toBe(1);
    expect(value.vehicles.map((vehicle) => vehicle.vehicleId)).toEqual([
      "Alpha, lead",
      "Bravo",
    ]);
    expect(value.vehicles[0]).toMatchObject({
      sampleCount: 2,
      altitudeSource: "Ground truth",
      motorSource: "Applied PWM",
    });
    expect(value.vehicles[0].samples[0]).toMatchObject({
      timeS: 0,
      speedMS: 5,
      altitudeM: 0.4,
      motorPercent: { m1: 48, m2: 49, m3: 50, m4: 51 },
      attitudeDeg: { x: 90, y: 0, z: -90 },
      accelerationMS2: { x: 1, y: 2, z: 3 },
      angularVelocityRadS: { x: 0.1, y: 0.2, z: 0.3 },
    });
    expect(value.vehicles[1]).toMatchObject({
      altitudeSource: "Position estimate",
      motorSource: "Command",
    });
    expect(value.vehicles[1].samples[1]).toMatchObject({
      timeS: 1,
      speedMS: 3,
      altitudeM: 0.51,
      motorPercent: { m1: 66, m2: 67, m3: 68, m4: 69 },
    });
  });

  it("bounds display samples while retaining the first and last observation", () => {
    const rows = Array.from({ length: 10 }, (_, index) => (
      `Alpha,${index},${index / 10},${index / 10},${index},0,0,50,50,50,50,50,50,50,50,0,0,0,0,0,0,0,0,0`
    ));
    const value = parseCampaignTelemetryCsv([HEADER, ...rows].join("\n"), 4);

    expect(value.vehicles[0].sampleCount).toBe(10);
    expect(value.vehicles[0].samples).toHaveLength(4);
    expect(value.vehicles[0].samples.map((sample) => sample.timeS)).toEqual([0, 3, 6, 9]);
  });

  it("keeps unavailable signals explicit instead of inventing values", () => {
    const value = parseCampaignTelemetryCsv([
      "vehicle_id,source_timestamp_s",
      "Alpha,1",
    ].join("\n"));

    expect(value.vehicles[0]).toMatchObject({
      altitudeSource: "Unavailable",
      motorSource: "Unavailable",
      samples: [{
        timeS: 0,
        motorPercent: {},
        attitudeDeg: {},
        accelerationMS2: {},
        angularVelocityRadS: {},
      }],
    });
    expect(value.vehicles[0].samples[0].speedMS).toBeUndefined();
  });

  it("selects the exact source row despite row reorder and duplicate receive times", () => {
    const header = [
      "vehicle_id",
      "event_id",
      "source_timestamp_s",
      "received_timestamp_s",
      "telemetry_sequence",
      "source_clock_id",
      "source_clock_epoch",
      "position_x_m",
      "position_y_m",
      "position_z_m",
      "velocity_x_m_s",
      "velocity_y_m_s",
      "velocity_z_m_s",
    ].join(",");
    const rows = [
      "Alpha,event-9,12,99,9,fast-sim,3,1.2,0.2,0.4,0.2,0,0",
      "Alpha,event-7,10,99,7,fast-sim,3,1.0,0.0,0.4,0.1,0,0",
      "Alpha,event-8,11,99,8,fast-sim,3,1.1,0.1,0.4,0.9,0,0",
    ];
    const forward = parseCampaignTelemetryCsv([header, ...rows].join("\n"));
    const reordered = parseCampaignTelemetryCsv([header, ...rows.toReversed()].join("\n"));
    const first = nearestCampaignTelemetrySample(
      forward.vehicles[0].cursorSamples,
      11.1,
    );
    const second = nearestCampaignTelemetrySample(
      reordered.vehicles[0].cursorSamples,
      11.1,
    );

    expect(first).toMatchObject({
      sourceSequence: 8,
      sourceTimestampS: 11,
      receivedTimestampS: 99,
      correlationId: "event-8",
      positionM: { x: 1.1, y: 0.1, z: 0.4 },
      speedMS: 0.9,
    });
    expect(second).toEqual(first);
  });

  it("does not fabricate a cursor row across a source-sequence gap", () => {
    const value = parseCampaignTelemetryCsv([
      "vehicle_id,event_id,source_timestamp_s,telemetry_sequence,position_x_m,position_y_m,position_z_m",
      "Alpha,event-4,10,4,1,0,0.4",
      "Alpha,event-missing,11,,9,9,9",
      "Alpha,event-6,12,6,2,0,0.4",
    ].join("\n"));
    const selected = nearestCampaignTelemetrySample(value.vehicles[0].cursorSamples, 11);

    expect(selected).toMatchObject({
      sourceSequence: 4,
      sourceTimestampS: 10,
      positionM: { x: 1, y: 0, z: 0.4 },
    });
    expect(selected?.sourceTimestampS).not.toBe(11);
  });

  it("resolves a frozen source timestamp by exact source sequence after row reorder", () => {
    const csv = [
      "vehicle_id,event_id,source_timestamp_s,received_timestamp_s,telemetry_sequence,source_clock_id,source_clock_epoch,position_x_m,position_y_m,position_z_m,motor_m1_applied_pwm_percent",
      "Alpha,event-5,11,99,5,fast-sim,3,5,0,0.4,55",
      "Alpha,event-4,11,99,4,fast-sim,3,4,0,0.4,44",
    ].join("\n");
    const forward = parseCampaignTelemetryCsv(csv);
    const reordered = parseCampaignTelemetryCsv(csv.split("\n").toSpliced(1, 2,
      csv.split("\n")[2],
      csv.split("\n")[1],
    ).join("\n"));
    const identity = {
      sourceTimestampS: 11,
      sourceSequence: 5,
      sourceClockId: "fast-sim",
      sourceClockEpoch: 3,
      correlationId: "event-5",
    };

    const selected = exactCampaignTelemetrySample(
      forward.vehicles[0].cursorSamples,
      identity,
    );
    const selectedAfterReorder = exactCampaignTelemetrySample(
      reordered.vehicles[0].cursorSamples,
      identity,
    );

    expect(selected).toMatchObject({
      sourceSequence: 5,
      positionM: { x: 5, y: 0, z: 0.4 },
      appliedMotorPercent: { m1: 55 },
    });
    expect(selectedAfterReorder).toEqual(selected);
    expect(exactCampaignTelemetrySample(forward.vehicles[0].cursorSamples, {
      ...identity,
      sourceSequence: 6,
    })).toBeUndefined();
  });
});
