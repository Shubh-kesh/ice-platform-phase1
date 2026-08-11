import type { HealthStatus } from "../types";

const HEALTH_CONFIG: Record<HealthStatus, { color: string; label: string }> = {
  green: { color: "bg-status-green", label: "On track" },
  amber: { color: "bg-status-amber", label: "At risk" },
  red: { color: "bg-status-red", label: "Off track" },
  not_rated: {
    color: "bg-ink-border",
    label: "Not rated — insufficient data",
  },
};

export function HealthDot({
  status,
  showLabel = false,
  reason,
}: {
  status: HealthStatus;
  showLabel?: boolean;
  reason?: string;
}) {
  const config = HEALTH_CONFIG[status];
  return (
    <span className="inline-flex items-center gap-1.5" title={reason ?? config.label}>
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