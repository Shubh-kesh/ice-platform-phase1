import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  CheckCircle2,
  Loader2,
  Play,
  RotateCcw,
} from "lucide-react";
import { api, getProjectHealth, transitionProject } from "../lib/api";
import type { Project, ProjectStatus } from "../types";
import { AppShell } from "../components/AppShell";
import { ProjectHealthPanel } from "../components/ProjectHealthPanel";
import { ProjectTimeline } from "../components/ProjectTimeline";
import { DailySiteLogs } from "../components/DailySiteLogs";
import { InventoryPanel } from "../components/InventoryPanel";
import { JobCostsPanel } from "../components/JobCostsPanel";
import { ProjectAssignments } from "../components/ProjectAssignments";
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

function formatDateOrDash(value: string | null) {
  return value ? formatDate(value) : "—";
}

const LIFE_ACTIONS: {
  action: "activate" | "complete" | "archive" | "restore";
  icon: typeof Play;
  label: string;
  needsConfirm: boolean;
  confirmMsg: string;
}[] = [
  { action: "activate", icon: Play, label: "Activate", needsConfirm: false, confirmMsg: "" },
  { action: "complete", icon: CheckCircle2, label: "Mark complete", needsConfirm: false, confirmMsg: "" },
  {
    action: "archive",
    icon: Archive,
    label: "Archive",
    needsConfirm: true,
    confirmMsg: "Archiving hides this project from non-admin users. Continue?",
  },
  { action: "restore", icon: RotateCcw, label: "Restore", needsConfirm: false, confirmMsg: "" },
];

// Only certain transitions are legal from a given status; the backend
// enforces this authoritatively and the menu only surfaces the legal ones.
const VALID_FROM: Record<ProjectStatus, ("activate" | "complete" | "archive" | "restore")[]> = {
  draft: ["activate"],
  planning: [],
  active: ["complete", "archive"],
  on_hold: [],
  completed: ["archive"],
  archived: ["restore"],
};

export function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const { data: project, isLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: async () => {
      const { data } = await api.get<Project>(`/projects/${projectId}`);
      return data;
    },
  });

  // Deterministic, server-computed health (M3) — colors + reasons + override UI.
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["project-health", projectId],
    queryFn: () => getProjectHealth(projectId!),
    enabled: Boolean(projectId),
  });

  const isAdmin = user?.role === "admin";
  const canViewFinance =
    user?.role === "admin" || user?.role === "procurement_manager";
  const isArchived = project?.status === "archived";

  // Mirrors backend RBAC: admin/supervisor manage the timeline & site
  // logs, admin/procurement manage inventory. The API enforces this
  // authoritatively — these just keep the UI from offering actions that
  // would 403 anyway. Archived projects are frozen in the UI.
  const canWriteTimeline =
    !isArchived && (user?.role === "admin" || user?.role === "site_supervisor");
  const canWriteInventory =
    !isArchived && (user?.role === "admin" || user?.role === "procurement_manager");
  const canWriteFinance =
    !isArchived && (user?.role === "admin" || user?.role === "procurement_manager");

  const transition = useMutation({
    mutationFn: async (action: "activate" | "complete" | "archive" | "restore") => {
      return transitionProject(projectId!, action);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const legalActions = project
    ? VALID_FROM[project.status]
    : [];

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
          {isArchived && (
            <div className="mb-4 flex items-start gap-2 rounded-md border border-ink-border bg-ink px-3 py-2 text-xs text-paper-muted">
              <Archive size={14} className="mt-0.5 shrink-0" />
              <span>
                This project is archived. It's hidden from non-admin users and
                is presented read-only until restored.
                {project.archived_at && (
                  <span className="text-paper-faint">
                    {" "}
                    Archived {formatDate(project.archived_at)}.
                  </span>
                )}
              </span>
            </div>
          )}

          <p className="font-mono text-xs tracking-widest text-blueprint-400">
              SITE DETAIL
            </p>
            <h1 className="mt-1 text-xl font-semibold text-paper">
              {project.name}
            </h1>
            <p className="mt-1 text-sm text-paper-muted">
              <span className="font-mono text-xs text-blueprint-400">
                {project.project_code}
              </span>{" "}
              · {project.client_name} · {project.site_address}
            </p>

          {isAdmin && legalActions.length > 0 && (
            <div className="mt-5">
              <p className="mb-2 font-mono text-xs tracking-widest text-blueprint-400">
                LIFECYCLE
              </p>
              <div className="flex flex-wrap gap-2">
                {LIFE_ACTIONS.filter((a) => legalActions.includes(a.action)).map((a) => {
                  const Icon = a.icon;
                  const run = () => {
                    if (a.needsConfirm && !window.confirm(a.confirmMsg)) return;
                    transition.mutate(a.action);
                  };
                  return (
                    <button
                      key={a.action}
                      onClick={run}
                      disabled={transition.isPending}
                      className="flex items-center gap-1.5 rounded border border-ink-border bg-ink px-3 py-1.5 text-xs text-paper hover:bg-ink-raised hover:text-paper disabled:opacity-50"
                    >
                      <Icon size={14} />
                      {a.label}
                    </button>
                  );
                })}
              </div>
              {transition.isError && (
                <p className="mt-2 text-xs text-status-red">
                  Couldn't update the project lifecycle. Try again.
                </p>
              )}
            </div>
          )}

          {healthLoading ? (
            <div className="mt-6 flex items-center gap-2 py-6 text-paper-muted">
              <Loader2 size={16} className="animate-spin" />
              Computing health…
            </div>
          ) : health ? (
            <div className="mt-6">
              <ProjectHealthPanel
                projectId={project.id}
                health={health}
                isOverrideManager={isAdmin}
                canWriteHealth={isAdmin && !isArchived}
              />
            </div>
          ) : null}

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
            {canViewFinance && (
              <>
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
              </>
            )}
            <div className="flex justify-between border-b border-ink-border py-2">
              <span className="text-paper-muted">Completed</span>
              <span className="text-paper">
                {formatDateOrDash(project.completed_at)}
              </span>
            </div>
            <div className="flex justify-between border-b border-ink-border py-2">
              <span className="text-paper-muted">Archived</span>
              <span className="text-paper">
                {formatDateOrDash(project.archived_at)}
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
            {canWriteFinance && <JobCostsPanel projectId={project.id} canWrite={canWriteFinance} />}
            {isAdmin && <ProjectAssignments projectId={project.id} />}
          </div>
        </div>
      )}
    </AppShell>
  );
}
