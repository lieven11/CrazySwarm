export function controlApiTimeoutMs(pathname: string, method: string): number {
  const isPhysicalLabOperation = pathname.startsWith("/api/v1/physical-twin/lab/")
    && method !== "GET";
  if (isPhysicalLabOperation) return 90_000;
  const isPhysicalTwinConnectionOperation = [
    "/api/v1/physical-twin/connect",
    "/api/v1/physical-twin/confirm",
    "/api/v1/physical-twin/disconnect",
  ].includes(pathname) && method !== "GET";
  if (isPhysicalTwinConnectionOperation) return 60_000;
  if (pathname === "/api/v1/campaign/active/preview") return 30_000;
  return 5_000;
}
