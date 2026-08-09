import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2 } from "lucide-react";
import { api } from "../lib/api";
import type { Project } from "../types";
import { AppShell } from "../components/AppShell";
import { KpiStrip } from "../components/KpiStrip";
import { ProjectCard } from "../components/ProjectCard";
import { useAuth } from "../lib/auth-context";

export function CommandCenter() {
  const { user } = useAuth();
  const {
    data: projects,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["projects"],
    queryFn: async () => {
      const { data } = await api.get<Project[]>("/projects");
      return data;
    },
  });

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
            No sites yet. Once projects are created, they'll appear here as
            drawing sheets on the command board.
          </p>
        </div>
      )}

      {projects && projects.length > 0 && (
        <>
          <div className="mb-6">
            <KpiStrip projects={projects} />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {projects.map((project, index) => (
              <ProjectCard key={project.id} project={project} index={index} />
            ))}
          </div>
        </>
      )}
    </AppShell>
  );
}
