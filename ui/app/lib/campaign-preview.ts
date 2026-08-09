import type { CampaignCaseView, MissionOption, MissionPreview, Vec3 } from "./models";

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownRecord
    : undefined;
}

function finite(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function vector(value: unknown): Vec3 | undefined {
  const item = record(value);
  if (!item) return undefined;
  const x = finite(item.x, Number.NaN);
  const y = finite(item.y, Number.NaN);
  const z = finite(item.z, Number.NaN);
  return [x, y, z].every(Number.isFinite) ? { x, y, z } : undefined;
}

function routeCommands(points: Vec3[], durationS: number): MissionOption["plannedCommands"] {
  if (!points.length) return [];
  const commands: MissionOption["plannedCommands"] = [];
  const first = points[0]!;
  if (first.z > 0) {
    commands.push({ action: "takeoff", arguments: { height_m: first.z, duration_s: 2 } });
  }
  const segmentDurationS = points.length > 1 ? durationS / (points.length - 1) : 0;
  points.slice(1).forEach((point, index) => {
    const previous = points[index]!;
    commands.push({
      action: "move_relative",
      arguments: {
        x_m: point.x - previous.x,
        y_m: point.y - previous.y,
        z_m: point.z - previous.z,
        duration_s: segmentDurationS,
        frame: "world",
      },
    });
  });
  commands.push({ action: "land", arguments: { duration_s: 2 } });
  return commands;
}

/** Adapt the bounded campaign planner response to the shared mission preview surface. */
export function campaignMissionPreview(
  campaignCase: CampaignCaseView,
  payload: Record<string, unknown>,
): MissionPreview | undefined {
  const plan = record(payload.plan);
  const schedule = record(payload.schedule);
  if (!plan || !schedule) return undefined;

  const candidates = Array.isArray(plan.retained_candidates) ? plan.retained_candidates : [];
  const selectedIndex = Number.isInteger(plan.selected_candidate_index)
    ? plan.selected_candidate_index as number
    : -1;
  const selected = selectedIndex >= 0 ? record(candidates[selectedIndex]) : undefined;
  const routes = Array.isArray(selected?.routes) ? selected.routes.flatMap((value) => {
    const route = record(value);
    const roleId = typeof route?.role_id === "string" ? route.role_id : undefined;
    const points = Array.isArray(route?.points_m)
      ? route.points_m.flatMap((point) => vector(point) ?? [])
      : [];
    if (!roleId || !points.length) return [];
    return [{
      roleId,
      points,
      durationS: finite(route?.route_duration_s),
    }];
  }) : [];
  if (!routes.length) return undefined;

  const scheduleRoles = new Map(
    (Array.isArray(schedule.roles) ? schedule.roles : []).flatMap((value) => {
      const role = record(value);
      return typeof role?.role_id === "string" ? [[role.role_id, role] as const] : [];
    }),
  );
  const predictedBattery = record(selected?.predicted_battery_end_percent);
  const planReady = plan.status === "READY";
  const planSha = typeof plan.plan_sha256 === "string" ? plan.plan_sha256 : campaignCase.case_sha256;
  const scheduleSha = typeof schedule.schedule_sha256 === "string" ? schedule.schedule_sha256 : planSha;

  return {
    missionId: `campaign:${campaignCase.case_id}`,
    sourceSha256: campaignCase.case_sha256,
    plan: {
      id: `campaign-plan:${campaignCase.case_id}`,
      sha256: planSha,
      safetyCaseSha256: scheduleSha,
      status: planReady ? "APPROVED" : "BLOCKED",
      objective: campaignCase.purpose,
      plugins: [{
        id: typeof plan.planner_id === "string" ? plan.planner_id : "campaign-planner",
        kind: "ROUTE_PLANNER",
        version: typeof plan.planner_version === "string" ? plan.planner_version : "unknown",
        capabilities: campaignCase.allowed_strategies,
        manifestSha256: campaignCase.case_sha256,
      }],
      phases: [{
        id: "campaign-execution",
        objective: campaignCase.expected_outcome,
        roleIds: routes.map((route) => route.roleId),
        maximumDurationS: finite(schedule.source_schedule_duration_s),
      }],
      routes: routes.map((route) => {
        const roleSchedule = scheduleRoles.get(route.roleId);
        const energy = record(roleSchedule?.energy);
        const lengthM = route.points.slice(1).reduce((total, point, index) => {
          const previous = route.points[index]!;
          return total + Math.hypot(
            point.x - previous.x,
            point.y - previous.y,
            point.z - previous.z,
          );
        }, 0);
        return {
          roleId: route.roleId,
          status: planReady ? "READY" as const : "BLOCKED" as const,
          durationS: route.durationS,
          energyPercent: finite(energy?.route_energy_percent),
          lengthM,
          waypointCount: route.points.length,
          findings: [],
        };
      }),
      findings: planReady ? [] : [{
        code: "CAMPAIGN_PLAN_BLOCKED",
        severity: "BLOCKER",
        message: typeof plan.blocking_reason === "string" ? plan.blocking_reason : "Campaign planning is blocked",
        requiresConfirmation: false,
      }],
    },
    vehicles: routes.map((route) => {
      const first = route.points[0]!;
      return {
        roleId: route.roleId,
        vehicleId: route.roleId,
        displayName: route.roleId,
        initialRole: "ACTIVE" as const,
        home: { x: first.x, y: first.y, z: 0 },
        start: { x: first.x, y: first.y, z: 0 },
        batteryPercent: finite(predictedBattery?.[route.roleId], 100),
        minimumBatteryPercent: 20,
        existingVehicle: false,
        backendRole: campaignCase.environment === "SIMULATION" ? "FAST_SIM" as const : undefined,
        previewFidelity: "EXACT_ROLE" as const,
        plannedCommands: routeCommands(route.points, route.durationS),
      };
    }),
  };
}
