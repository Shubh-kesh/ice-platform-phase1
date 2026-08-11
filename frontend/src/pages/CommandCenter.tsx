import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, Loader2, Plus, X } from "lucide-react";
import { api, createProject, getProjectsHealth } from "../lib/api";
import type { Project, ProjectCreateInput } from "../types";
import { AppShell } from "../components/AppShell";
import { KpiStrip } from "../components/KpiStrip";
import { ProjectCard } from "../components/ProjectCard";
import { useAuth } from "../lib/auth-context";

const EMPTY_FORM: ProjectCreateInput = {
  name: "",
  site_address: "",
  client_name: "",
  start_date: "",
  target_end_date: "",
  budget_total: 0,
};

export function CommandCenter() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ProjectCreateInput>(EMPTY_FORM);
  const [formError, setFormError] = useState("");

  const {
    data: projects,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["projects", showArchived],
    queryFn: async () => {
      const { data } = await api.get<Project[]>("/projects", {
        params: showArchived ? { include_archived: true } : {},
      });
      return data;
    },
  });

  // Deterministic health is served by the API (M3); the frontend no longer
  // derives an "overall" verdict itself. Clients are 403 on the health
  // endpoints (M6) so the roll-up is never fetched for them.
  const isClient = user?.role === "client";
  const { data: healths = [] } = useQuery({
    queryKey: ["projects-health", showArchived],
    queryFn: () => getProjectsHealth(showArchived),
    enabled: !isClient,
  });

  const isAdmin = user?.role === "admin";
  const canViewBudget =
    user?.role === "admin" || user?.role === "procurement_manager";

  const healthByProject = new Map(healths.map((h) => [h.project_id, h]));

  const createProjectMutation = useMutation({
    mutationFn: createProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setForm(EMPTY_FORM);
      setShowForm(false);
      setFormError("");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Could not create the project. Check the API is running.";
      setFormError(msg);
    },
  });

  const submitForm = (event: FormEvent) => {
    event.preventDefault();
    if (!form.client_name || !form.site_address || !form.budget_total) {
      setFormError("Client, site address and budget are required.");
      return;
    }
    createProjectMutation.mutate(form);
  };

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <p className="font-mono text-xs tracking-widest text-blueprint-400">
            COMMAND CENTER
          </p>
          <h1 className="mt-1 text-xl font-semibold text-paper">
            Welcome back{user ? `, ${user.full_name.split(" ")[0]}` : ""}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          {!isClient && (
            <button
              onClick={() => setShowArchived((v) => !v)}
              className={`flex items-center gap-1.5 rounded border border-ink-border bg-ink px-3 py-1.5 text-xs hover:bg-ink-raised ${
                showArchived ? "text-paper" : "text-paper-muted"
              }`}
            >
              <Archive size={14} />
              Show archived
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-1.5 rounded bg-blueprint-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blueprint-400"
            >
              <Plus size={14} />
              New site
            </button>
          )}
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-16 text-paper-muted">
          <Loader2 size={18} className="animate-spin" />
          Loading your sites…
        </div>
      )}

      {isError && (
        <div className="flex items-start gap-3 rounded-md border border-status-red/30 bg-status-red/10 p-4 text-sm text-status-red">
          <AlertTriangle size={18} className="mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">Couldn't load projects.</p>
            <p className="mt-0.5 text-status-red/80">
              Check that the API is running, then retry.
            </p>
            <button
              onClick={() => refetch()}
              className="mt-2 rounded border border-status-red/40 px-2.5 py-1 text-xs hover:bg-status-red/10"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {projects && projects.length === 0 && (
        <div className="rounded-md border border-dashed border-ink-border p-10 text-center">
          <p className="text-sm text-paper-muted">
            {showArchived
              ? "No archived sites."
              : "No sites yet. Once projects are created, they'll appear here as drawing sheets on the command board."}
          </p>
        </div>
      )}

      {projects && projects.length > 0 && (
        <>
          <div className="mb-6">
            <KpiStrip
              projects={projects}
              healths={healths}
              canViewBudget={canViewBudget}
              showHealth={!isClient}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {projects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                health={healthByProject.get(project.id)}
                showBudget={canViewBudget}
                showHealth={!isClient}
              />
            ))}
          </div>
        </>
      )}

      {showForm && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-16"
          onClick={() => setShowForm(false)}
        >
          <div
            className="w-full max-w-md rounded-md border border-ink-border bg-ink-surface p-5 shadow-panel"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <p className="font-mono text-xs tracking-widest text-blueprint-400">
                NEW SITE
              </p>
              <button
                onClick={() => setShowForm(false)}
                className="rounded p-1 text-paper-muted hover:text-paper"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={submitForm} className="space-y-3">
              <label className="block text-xs text-paper-muted">
                Project name
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  placeholder="e.g. Emerald Heights"
                  required
                />
              </label>
              <label className="block text-xs text-paper-muted">
                Client name
                <input
                  value={form.client_name}
                  onChange={(e) =>
                    setForm({ ...form, client_name: e.target.value })
                  }
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  placeholder="e.g. A. Sharma"
                  required
                />
              </label>
              <label className="block text-xs text-paper-muted">
                Site address
                <input
                  value={form.site_address}
                  onChange={(e) =>
                    setForm({ ...form, site_address: e.target.value })
                  }
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  placeholder="e.g. 42 Lakeview Road"
                  required
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-xs text-paper-muted">
                  Start date
                  <input
                    type="date"
                    value={form.start_date}
                    onChange={(e) =>
                      setForm({ ...form, start_date: e.target.value })
                    }
                    className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                    required
                  />
                </label>
                <label className="block text-xs text-paper-muted">
                  Target end date
                  <input
                    type="date"
                    value={form.target_end_date}
                    onChange={(e) =>
                      setForm({ ...form, target_end_date: e.target.value })
                    }
                    className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                    required
                  />
                </label>
              </div>
              <label className="block text-xs text-paper-muted">
                Budget total (₹)
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={form.budget_total || ""}
                  onChange={(e) =>
                    setForm({ ...form, budget_total: Number(e.target.value) })
                  }
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  required
                />
              </label>

              {formError && (
                <p className="text-xs text-status-red">{formError}</p>
              )}

              <button
                type="submit"
                disabled={createProjectMutation.isPending}
                className="w-full rounded bg-blueprint-500 px-3 py-2 text-sm font-medium text-white hover:bg-blueprint-400 disabled:opacity-50"
              >
                {createProjectMutation.isPending ? "Creating…" : "Create project"}
              </button>
            </form>
          </div>
        </div>
      )}
    </AppShell>
  );
}
