import type { HealthStatus } from "../types";

const HEALTH_CONFIG: Record<HealthStatus, { color: string; label: string }> = {
  green: { color: "bg-status-green", label: "On track" },
  amber: { color: "bg-status-amber", label: "At risk" },
  red: { color: "bg-status-red", label: "Off track" },
};

export function HealthDot({
  status,
  showLabel = false,
}: {
  status: HealthStatus;
  showLabel?: boolean;
}) {
  const config = HEALTH_CONFIG[status];
  return (
    <span className="inline-flex items-center gap-1.5" title={config.label}>
      <span
        className={`h-2 w-2 rounded-full ${config.color} shadow-[0_0_6px_currentColor]`}
        aria-hidden="true"
      />
      {showLabel && (
        <span className="text-xs text-paper-muted">{config.label}</span>
      )}
    </span>
  );
}

export function overallHealth(
  timeline: HealthStatus,
  budget: HealthStatus,
  safety: HealthStatus
): HealthStatus {
  // Worst-of-three — one red pillar means the project card reads red overall.
  if (timeline === "red" || budget === "red" || safety === "red") return "red";
  if (timeline === "amber" || budget === "amber" || safety === "amber")
    return "amber";
  return "green";
}
