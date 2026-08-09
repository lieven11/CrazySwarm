import type { DashboardModel } from "./models";

export function createEmptyDashboard(): DashboardModel {
  return {
    apiConnected: false,
    serviceLabel: "Local service not connected",
    vehicles: [],
    missions: [],
    twins: [],
    fleetSessions: [],
  };
}
