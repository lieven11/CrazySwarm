import type { MissionOption, MissionPreview, RangeRay, RoomView, Vec3 } from "./models";

export type ScenePoint = readonly [number, number, number];

/** Convert application world coordinates (x, y, altitude z) to Three.js (x, up, depth). */
export function worldToScene(point: Vec3): ScenePoint {
  return [point.x, point.z, point.y];
}

/** Return a normalized world-frame vector for a body-mounted range sensor. */
export function rangeDirectionVector(direction: RangeRay["direction"], yawRad: number, rollRad = 0, pitchRad = 0): Vec3 {
  const bodyDirections: Record<RangeRay["direction"], Vec3> = {
    front: { x: 1, y: 0, z: 0 },
    back: { x: -1, y: 0, z: 0 },
    left: { x: 0, y: 1, z: 0 },
    right: { x: 0, y: -1, z: 0 },
    up: { x: 0, y: 0, z: 1 },
    down: { x: 0, y: 0, z: -1 },
  };
  const body = bodyDirections[direction];
  const cr = Math.cos(rollRad), sr = Math.sin(rollRad);
  const cp = Math.cos(pitchRad), sp = Math.sin(pitchRad);
  const cy = Math.cos(yawRad), sy = Math.sin(yawRad);
  return {
    x: (cy * cp) * body.x + (cy * sp * sr - sy * cr) * body.y + (cy * sp * cr + sy * sr) * body.z,
    y: (sy * cp) * body.x + (sy * sp * sr + cy * cr) * body.y + (sy * sp * cr - cy * sr) * body.z,
    z: (-sp) * body.x + (cp * sr) * body.y + (cp * cr) * body.z,
  };
}

export function rangeEndpoint(origin: Vec3, ray: RangeRay, yawRad: number, rollRad = 0, pitchRad = 0): Vec3 | null {
  if (ray.distanceM === null) return null;
  const direction = rangeDirectionVector(ray.direction, yawRad, rollRad, pitchRad);
  const distance = Math.min(ray.distanceM, ray.maximumM);
  return {
    x: origin.x + direction.x * distance,
    y: origin.y + direction.y * distance,
    z: origin.z + direction.z * distance,
  };
}

/** Planned geometry derived only from the selected mission parameters and configured home. */
export function missionPlan(
  mission: MissionOption | undefined,
  room: RoomView | undefined,
): Vec3[] {
  if (!mission || !room?.home) return [];
  return plannedPathFromCommands(room.home, mission.plannedCommands);
}

export function missionPreviewPaths(preview: MissionPreview | undefined): Record<string, Vec3[]> {
  if (!preview) return {};
  return Object.fromEntries(
    preview.vehicles.map((vehicle) => [
      vehicle.vehicleId,
      vehicle.initialRole === "ACTIVE"
        ? plannedPathFromCommands(vehicle.start, vehicle.plannedCommands)
        : [vehicle.start],
    ]),
  );
}

export function plannedPathFromCommands(
  home: Vec3,
  commands: MissionOption["plannedCommands"],
): Vec3[] {
  const path: Vec3[] = [home];
  let current = home;
  for (const command of commands) {
    if (command.action === "takeoff") {
      const height = finiteArgument(command.arguments.height_m);
      if (height === undefined) continue;
      current = { ...current, z: height };
      path.push(current);
    } else if (command.action === "move_relative") {
      current = {
        x: current.x + (finiteArgument(command.arguments.x_m) ?? 0),
        y: current.y + (finiteArgument(command.arguments.y_m) ?? 0),
        z: current.z + (finiteArgument(command.arguments.z_m) ?? 0),
      };
      path.push(current);
    } else if (command.action === "land") {
      current = { ...current, z: 0 };
      path.push(current);
    }
  }
  return path;
}

function finiteArgument(value: number | string | undefined): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
