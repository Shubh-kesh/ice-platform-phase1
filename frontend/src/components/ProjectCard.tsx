import { Link } from "react-router-dom";
import type { Project } from "../types";
import { HealthDot, overallHealth } from "./HealthDot";

const STATUS_LABEL: Record<Project["status"], string> = {
  draft: "Draft",
  planning: "Planning",
  active: "Active",
  on_hold: "On hold",
  completed: "Completed",
  archived: "Archived",
};

const STATUS_TONE: Record<Project["status"], string> = {
  draft: "border-blueprint-500/40 text-blueprint-300",
  planning: "border-ink-border bg-ink text-paper-muted",
  active: "border-status-green/40 text-status-green",
  on_hold: "border-status-amber/40 text-status-amber",
  completed: "border-blueprint-500/40 text-blueprint-300",
  archived: "border-ink-border text-paper-faint",
};

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function ProjectCard({ project }: { project: Project }) {
  const overall = overallHealth(
    project.timeline_health,
    project.budget_health,
    project.safety_health
  );
  const overallBorder = {
    green: "border-l-status-green",
    amber: "border-l-status-amber",
    red: "border-l-status-red",
  }[overall];

  return (
    <Link
      to={`/projects/${project.id}`}
      className={`group relative block rounded-md border border-ink-border ${overallBorder} border-l-4 bg-ink-surface p-4 shadow-panel transition-colors hover:bg-ink-raised`}
    >
      {/* Drafting corner marks — the signature detail, evoking an
          architectural drawing sheet's title-block corners. */}
      <span className="pointer-events-none absolute left-1.5 top-1.5 h-2 w-2 border-l border-t border-blueprint-600/50" />
      <span className="pointer-events-none absolute right-1.5 top-1.5 h-2 w-2 border-r border-t border-blueprint-600/50" />
      <span className="pointer-events-none absolute bottom-1.5 left-1.5 h-2 w-2 border-b border-l border-blueprint-600/50" />
      <span className="pointer-events-none absolute bottom-1.5 right-1.5 h-2 w-2 border-b border-r border-blueprint-600/50" />

      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-[11px] tracking-wider text-blueprint-400">
            {project.project_code}
          </p>
          <h3 className="truncate text-sm font-semibold text-paper">
            {project.name}
          </h3>
          <p className="truncate text-xs text-paper-muted">
            {project.client_name}
          </p>
        </div>
        <span
          className={`shrink-0 rounded border px-2 py-0.5 text-[10px] uppercase tracking-wide ${STATUS_TONE[project.status]}`}
        >
          {STATUS_LABEL[project.status]}
        </span>
      </div>

      {/* Progress bar */}
      <div className="mb-3">
        <div className="mb-1 flex items-center justify-between text-[11px] text-paper-muted">
          <span>Progress</span>
          <span className="font-mono tabular text-paper">
            {project.percent_complete}%
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink">
          <div
            className="h-full rounded-full bg-blueprint-400 transition-all"
            style={{ width: `${project.percent_complete}%` }}
          />
        </div>
      </div>

      {/* Health row */}
      <div className="mb-3 flex items-center gap-4 text-[11px] text-paper-muted">
        <span className="flex items-center gap-1.5">
          <HealthDot status={project.timeline_health} /> Timeline
        </span>
        <span className="flex items-center gap-1.5">
          <HealthDot status={project.budget_health} /> Budget
        </span>
        <span className="flex items-center gap-1.5">
          <HealthDot status={project.safety_health} /> Safety
        </span>
      </div>

      {/* Budget */}
      <div className="flex items-baseline justify-between border-t border-ink-border pt-2 font-mono text-xs tabular">
        <span className="text-paper-muted">
          {formatCurrency(project.budget_spent)}
        </span>
        <span className="text-paper-faint">
          / {formatCurrency(project.budget_total)}
        </span>
      </div>
    </Link>
  );
}
