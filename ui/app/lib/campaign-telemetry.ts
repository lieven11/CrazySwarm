const MOTOR_IDS = ["m1", "m2", "m3", "m4"] as const;
const AXES = ["x", "y", "z"] as const;
const DEFAULT_MAX_SAMPLES_PER_VEHICLE = 240;

export type CampaignMotorId = typeof MOTOR_IDS[number];
export type CampaignAxis = typeof AXES[number];

export interface CampaignTelemetryChartSample {
  timeS: number;
  speedMS?: number;
  altitudeM?: number;
  motorPercent: Partial<Record<CampaignMotorId, number>>;
  attitudeDeg: Partial<Record<CampaignAxis, number>>;
  accelerationMS2: Partial<Record<CampaignAxis, number>>;
  angularVelocityRadS: Partial<Record<CampaignAxis, number>>;
}

export interface CampaignTelemetryVehicleChart {
  vehicleId: string;
  sampleCount: number;
  altitudeSource: "Ground truth" | "Position estimate" | "Unavailable";
  motorSource: "Applied PWM" | "Command" | "Unavailable";
  samples: CampaignTelemetryChartSample[];
}

export interface CampaignTelemetryChartView {
  rowCount: number;
  durationS: number;
  vehicles: CampaignTelemetryVehicleChart[];
}

type RawSample = {
  absoluteTimeS: number;
  speedMS?: number;
  groundTruthAltitudeM?: number;
  estimatedAltitudeM?: number;
  appliedMotorPercent: Partial<Record<CampaignMotorId, number>>;
  commandedMotorPercent: Partial<Record<CampaignMotorId, number>>;
  attitudeDeg: Partial<Record<CampaignAxis, number>>;
  accelerationMS2: Partial<Record<CampaignAxis, number>>;
  angularVelocityRadS: Partial<Record<CampaignAxis, number>>;
};

export function parseCampaignTelemetryCsv(
  source: string,
  maximumSamplesPerVehicle = DEFAULT_MAX_SAMPLES_PER_VEHICLE,
): CampaignTelemetryChartView {
  const rows = parseCsv(source);
  const header = rows[0] ?? [];
  if (!header.length) return { rowCount: 0, durationS: 0, vehicles: [] };
  const column = new Map(header.map((name, index) => [name, index] as const));
  const samplesByVehicle = new Map<string, RawSample[]>();
  let earliestTimeS = Number.POSITIVE_INFINITY;
  let latestTimeS = Number.NEGATIVE_INFINITY;

  rows.slice(1).forEach((row, rowIndex) => {
    if (!row.some((cell) => cell.length)) return;
    const vehicleId = cell(row, column, "vehicle_id") || "Unknown vehicle";
    const absoluteTimeS = firstFinite(
      numericCell(row, column, "source_timestamp_s"),
      numericCell(row, column, "simulation_timestamp_s"),
      numericCell(row, column, "replay_timestamp_s"),
      numericCell(row, column, "event_sequence"),
      rowIndex,
    );
    const velocity = [
      numericCell(row, column, "velocity_x_m_s"),
      numericCell(row, column, "velocity_y_m_s"),
      numericCell(row, column, "velocity_z_m_s"),
    ];
    const speedMS = velocity.every((value) => value !== undefined)
      ? Math.hypot(...velocity as [number, number, number])
      : undefined;
    const appliedMotorPercent: Partial<Record<CampaignMotorId, number>> = {};
    const commandedMotorPercent: Partial<Record<CampaignMotorId, number>> = {};
    for (const motorId of MOTOR_IDS) {
      const applied = numericCell(row, column, `motor_${motorId}_applied_pwm_percent`);
      const commanded = numericCell(row, column, `motor_${motorId}_command_percent`);
      if (applied !== undefined) appliedMotorPercent[motorId] = applied;
      if (commanded !== undefined) commandedMotorPercent[motorId] = commanded;
    }
    const attitudeDeg: Partial<Record<CampaignAxis, number>> = {};
    const accelerationMS2: Partial<Record<CampaignAxis, number>> = {};
    const angularVelocityRadS: Partial<Record<CampaignAxis, number>> = {};
    for (const axis of AXES) {
      const attitude = numericCell(row, column, `${attitudeColumn(axis)}_rad`);
      const acceleration = numericCell(row, column, `imu_acceleration_${axis}_m_s2`);
      const angularVelocity = numericCell(
        row,
        column,
        `imu_angular_velocity_${axis}_rad_s`,
      );
      if (attitude !== undefined) attitudeDeg[axis] = attitude * 180 / Math.PI;
      if (acceleration !== undefined) accelerationMS2[axis] = acceleration;
      if (angularVelocity !== undefined) angularVelocityRadS[axis] = angularVelocity;
    }
    const sample: RawSample = {
      absoluteTimeS,
      speedMS,
      groundTruthAltitudeM: numericCell(row, column, "ground_truth_z_m"),
      estimatedAltitudeM: numericCell(row, column, "position_z_m"),
      appliedMotorPercent,
      commandedMotorPercent,
      attitudeDeg,
      accelerationMS2,
      angularVelocityRadS,
    };
    samplesByVehicle.set(vehicleId, [...(samplesByVehicle.get(vehicleId) ?? []), sample]);
    earliestTimeS = Math.min(earliestTimeS, absoluteTimeS);
    latestTimeS = Math.max(latestTimeS, absoluteTimeS);
  });

  if (!Number.isFinite(earliestTimeS)) return { rowCount: 0, durationS: 0, vehicles: [] };
  const sampleLimit = Math.max(2, Math.trunc(maximumSamplesPerVehicle));
  const vehicles = [...samplesByVehicle.entries()]
    .toSorted(([left], [right]) => left.localeCompare(right))
    .map(([vehicleId, rawSamples]) => {
      const ordered = rawSamples.toSorted((left, right) => left.absoluteTimeS - right.absoluteTimeS);
      const hasGroundTruth = ordered.some((sample) => sample.groundTruthAltitudeM !== undefined);
      const hasEstimatedAltitude = ordered.some((sample) => sample.estimatedAltitudeM !== undefined);
      const hasAppliedMotor = ordered.some((sample) => MOTOR_IDS.some(
        (motorId) => sample.appliedMotorPercent[motorId] !== undefined,
      ));
      const hasCommandedMotor = ordered.some((sample) => MOTOR_IDS.some(
        (motorId) => sample.commandedMotorPercent[motorId] !== undefined,
      ));
      const samples = ordered.map<CampaignTelemetryChartSample>((sample) => ({
        timeS: Math.max(0, sample.absoluteTimeS - earliestTimeS),
        speedMS: sample.speedMS,
        altitudeM: hasGroundTruth
          ? sample.groundTruthAltitudeM
          : sample.estimatedAltitudeM,
        motorPercent: hasAppliedMotor
          ? sample.appliedMotorPercent
          : sample.commandedMotorPercent,
        attitudeDeg: sample.attitudeDeg,
        accelerationMS2: sample.accelerationMS2,
        angularVelocityRadS: sample.angularVelocityRadS,
      }));
      return {
        vehicleId,
        sampleCount: samples.length,
        altitudeSource: hasGroundTruth
          ? "Ground truth" as const
          : hasEstimatedAltitude
            ? "Position estimate" as const
            : "Unavailable" as const,
        motorSource: hasAppliedMotor
          ? "Applied PWM" as const
          : hasCommandedMotor
            ? "Command" as const
            : "Unavailable" as const,
        samples: downsample(samples, sampleLimit),
      };
    });

  return {
    rowCount: [...samplesByVehicle.values()].reduce((total, samples) => total + samples.length, 0),
    durationS: Math.max(0, latestTimeS - earliestTimeS),
    vehicles,
  };
}

function downsample(
  samples: CampaignTelemetryChartSample[],
  maximumSamples: number,
): CampaignTelemetryChartSample[] {
  if (samples.length <= maximumSamples) return samples;
  const indices = new Set<number>([0, samples.length - 1]);
  for (let index = 1; index < maximumSamples - 1; index += 1) {
    indices.add(Math.round(index * (samples.length - 1) / (maximumSamples - 1)));
  }
  return [...indices].toSorted((left, right) => left - right).map((index) => samples[index]);
}

function parseCsv(source: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (quoted) {
      if (character === '"' && source[index + 1] === '"') {
        value += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        value += character;
      }
      continue;
    }
    if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(value);
      value = "";
    } else if (character === "\n") {
      row.push(value);
      rows.push(row);
      row = [];
      value = "";
    } else if (character !== "\r") {
      value += character;
    }
  }
  if (value.length || row.length) {
    row.push(value);
    rows.push(row);
  }
  return rows;
}

function cell(row: string[], columns: Map<string, number>, name: string): string {
  const index = columns.get(name);
  return index === undefined ? "" : (row[index] ?? "").trim();
}

function numericCell(
  row: string[],
  columns: Map<string, number>,
  name: string,
): number | undefined {
  const value = cell(row, columns, name);
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function firstFinite(...values: Array<number | undefined>): number {
  return values.find((value): value is number => value !== undefined && Number.isFinite(value)) ?? 0;
}

function attitudeColumn(axis: CampaignAxis): "roll" | "pitch" | "yaw" {
  if (axis === "x") return "roll";
  if (axis === "y") return "pitch";
  return "yaw";
}
