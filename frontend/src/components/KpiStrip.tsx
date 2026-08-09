import type { Project } from "../types";
import { overallHealth } from "./HealthDot";

export function KpiStrip({ projects }: { projects: Project[] }) {
  const counts = { green: 0, amber: 0, red: 0 };
  for (const p of projects) {
    counts[overallHealth(p.timeline_health, p.budget_health, p.safety_health)]++;
  }

  const totalBudget = projects.reduce((sum, p) => sum + p.budget_total, 0);
  const totalSpent = projects.reduce((sum, p) => sum + p.budget_spent, 0);

  const items = [
    { label: "Total sites", value: projects.length, accent: "text-paper" },
    { label: "On track", value: counts.green, accent: "text-status-green" },
    { label: "At risk", value: counts.amber, accent: "text-status-amber" },
    { label: "Off track", value: counts.red, accent: "text-status-red" },
    {
      label: "Portfolio spend",
      value:
        totalBudget > 0
          ? `${Math.round((totalSpent / totalBudget) * 100)}%`
          : "—",
      accent: "text-blueprint-400",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-ink-border bg-ink-border sm:grid-cols-5">
      {items.map((item) => (
        <div key={item.label} className="bg-ink-surface px-4 py-3">
          <p className={`font-mono text-2xl tabular ${item.accent}`}>
            {item.value}
          </p>
          <p className="mt-0.5 text-[11px] uppercase tracking-wide text-paper-muted">
            {item.label}
          </p>
        </div>
      ))}
    </div>
  );
}
