import { Link } from "react-router-dom";
import type { Project, ProjectHealth } from "../types";
import { HealthDot } from "./HealthDot";

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

// overall border tone for an effective verdict (server-derived, M3).
const OVERALL_TONE: Record<ProjectHealth["overall"]["effective"], string> = {
  green: "border-l-status-green",
  amber: "border-l-status-amber",
  red: "border-l-status-red",
  not_rated: "border-l-ink-border",
};

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

const DIMENSION_ROWS: {
  key: "timeline" | "budget" | "safety";
  label: string;
}[] = [
  { key: "timeline", label: "Timeline" },
  { key: "budget", label: "Budget" },
  { key: "safety", label: "Safety" },
];

export function ProjectCard({
  project,
  health,
  showBudget,
}: {
  project: Project;
  health?: ProjectHealth;
  showBudget: boolean;
}) {
  const overall = health?.overall.effective ?? "not_rated";

  return (
    <Link
      to={`/projects/${project.id}`}
      className={`group relative block rounded-md border border-ink-border ${OVERALL_TONE[overall]} border-l-4 bg-ink-surface p-4 shadow-panel transition-colors hover:bg-ink-raised`}
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

      {/* Health row — verdicts come from the server (M3); each dot carries its
          first explanation sentence in the tooltip. */}
      <div className="mb-3 flex items-center gap-4 text-[11px] text-paper-muted">
        {DIMENSION_ROWS.map(({ key, label }) => {
          const dim = health?.[key];
          return (
            <span key={key} className="flex items-center gap-1.5">
              <HealthDot
                status={dim?.effective ?? "not_rated"}
                reason={dim?.reasons[0]}
              />
              {label}
            </span>
          );
        })}
      </div>

      {/* Bottom row — role-gated money (M6 slice / M3): admin/procurement see
          the spent/total amounts; supervisor/client see only a budget badge. */}
      {showBudget ? (
        <div className="flex items-baseline justify-between border-t border-ink-border pt-2 font-mono text-xs tabular">
          <span className="text-paper-muted">
            {formatCurrency(project.budget_spent)}
          </span>
          <span className="text-paper-faint">
            / {formatCurrency(project.budget_total)}
          </span>
        </div>
      ) : (
        <div className="flex items-center justify-between border-t border-ink-border pt-2 text-[11px] text-paper-muted">
          <span className="flex items-center gap-1.5">
            <HealthDot
              status={health?.budget.effective ?? "not_rated"}
              reason={health?.budget.reasons[0]}
            />
            Budget
          </span>
          <span className="font-mono text-[10px] uppercase tracking-wide text-paper-faint">
            colour only
          </span>
        </div>
      )}
    </Link>
  );
}