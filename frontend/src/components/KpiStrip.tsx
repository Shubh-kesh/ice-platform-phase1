import type { Project, ProjectHealth } from "../types";

export function KpiStrip({
  projects,
  healths,
  canViewBudget,
}: {
  projects: Project[];
  healths: ProjectHealth[];
  canViewBudget: boolean;
}) {
  const counts = { green: 0, amber: 0, red: 0, not_rated: 0 };
  for (const h of healths) {
    counts[h.overall.effective]++;
  }

  const items: { label: string; value: number | string; accent: string }[] = [
    { label: "Total sites", value: projects.length, accent: "text-paper" },
    { label: "On track", value: counts.green, accent: "text-status-green" },
    { label: "At risk", value: counts.amber, accent: "text-status-amber" },
    { label: "Off track", value: counts.red, accent: "text-status-red" },
    {
      label: "Not rated",
      value: counts.not_rated,
      accent: "text-paper-faint",
    },
  ];

  // Monetary roll-ups are admin/procurement only (M6 slice / M3) — supervisor
  // and client responses carry no budget figures at all.
  if (canViewBudget) {
    const totalBudget = projects.reduce((sum, p) => sum + p.budget_total, 0);
    const totalSpent = projects.reduce((sum, p) => sum + p.budget_spent, 0);
    items.push({
      label: "Portfolio spend",
      value:
        totalBudget > 0 ? `${Math.round((totalSpent / totalBudget) * 100)}%` : "—",
      accent: "text-blueprint-400",
    });
  }

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-ink-border bg-ink-border sm:grid-cols-3 md:grid-cols-6">
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