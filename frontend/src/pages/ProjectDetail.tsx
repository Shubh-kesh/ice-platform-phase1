import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import { api } from "../lib/api";
import type { Project } from "../types";
import { AppShell } from "../components/AppShell";
import { HealthDot } from "../components/HealthDot";
import { ProjectTimeline } from "../components/ProjectTimeline";
import { DailySiteLogs } from "../components/DailySiteLogs";
import { InventoryPanel } from "../components/InventoryPanel";
import { useAuth } from "../lib/auth-context";

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { user } = useAuth();

  // Mirrors backend RBAC: admin/supervisor manage the timeline & site
  // logs, admin/procurement manage inventory. The API enforces this
  // authoritatively — these just keep the UI from offering actions that
  // would 403 anyway.
  const canWriteTimeline = user?.role === "admin" || user?.role === "site_supervisor";
  const canWriteInventory = user?.role === "admin" || user?.role === "procurement_manager";

  const { data: project, isLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: async () => {
      const { data } = await api.get<Project>(`/projects/${projectId}`);
      return data;
    },
  });

  return (
    <AppShell>
      <Link
        to="/"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-paper-muted hover:text-paper"
      >
        <ArrowLeft size={15} /> Back to Command Center
      </Link>

      {isLoading && (
        <div className="flex items-center gap-2 py-16 text-paper-muted">
          <Loader2 size={18} className="animate-spin" />
          Loading site details…
        </div>
      )}

      {project && (
        <div className="rounded-md border border-ink-border bg-ink-surface p-6 shadow-panel">
          <p className="font-mono text-xs tracking-widest text-blueprint-400">
            SITE DETAIL
          </p>
          <h1 className="mt-1 text-xl font-semibold text-paper">
            {project.name}
          </h1>
          <p className="mt-1 text-sm text-paper-muted">
            {project.client_name} · {project.site_address}
          </p>

          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-md border border-ink-border p-3">
              <p className="mb-1.5 text-[11px] uppercase tracking-wide text-paper-muted">
                Timeline
              </p>
              <HealthDot status={project.timeline_health} showLabel />
            </div>
            <div className="rounded-md border border-ink-border p-3">
              <p className="mb-1.5 text-[11px] uppercase tracking-wide text-paper-muted">
                Budget
              </p>
              <HealthDot status={project.budget_health} showLabel />
            </div>
            <div className="rounded-md border border-ink-border p-3">
              <p className="mb-1.5 text-[11px] uppercase tracking-wide text-paper-muted">
                Safety
              </p>
              <HealthDot status={project.safety_health} showLabel />
            </div>
          </div>

          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 font-mono text-sm tabular">
            <div className="flex justify-between border-b border-ink-border py-2">
              <span className="text-paper-muted">Start date</span>
              <span className="text-paper">{formatDate(project.start_date)}</span>
            </div>
            <div className="flex justify-between border-b border-ink-border py-2">
              <span className="text-paper-muted">Target end date</span>
              <span className="text-paper">
                {formatDate(project.target_end_date)}
              </span>
            </div>
            <div className="flex justify-between border-b border-ink-border py-2">
              <span className="text-paper-muted">Budget total</span>
              <span className="text-paper">
                {formatCurrency(project.budget_total)}
              </span>
            </div>
            <div className="flex justify-between border-b border-ink-border py-2">
              <span className="text-paper-muted">Budget spent</span>
              <span className="text-paper">
                {formatCurrency(project.budget_spent)}
              </span>
            </div>
          </div>

          <div className="mt-6 space-y-4">
            <ProjectTimeline
              projectId={project.id}
              projectStart={project.start_date}
              projectEnd={project.target_end_date}
              canWrite={canWriteTimeline}
            />
            <DailySiteLogs projectId={project.id} canWrite={canWriteTimeline} />
            <InventoryPanel projectId={project.id} canWrite={canWriteInventory} />
          </div>
        </div>
      )}
    </AppShell>
  );
}
