import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Loader2, ArrowRight } from "lucide-react";
import { api } from "../lib/api";
import type { ProjectTask, TaskCreateInput, TaskStatus } from "../types";

const STATUS_CONFIG: Record<TaskStatus, { label: string; className: string }> = {
  not_started: { label: "Not started", className: "bg-ink-raised text-paper-muted" },
  in_progress: { label: "In progress", className: "bg-blueprint-400/15 text-blueprint-400" },
  completed: { label: "Completed", className: "bg-status-green/15 text-status-green" },
  blocked: { label: "Blocked", className: "bg-status-red/15 text-status-red" },
};

function daysBetween(a: string, b: string) {
  return Math.max(1, Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86_400_000));
}

type TaskDates = { start: string; end: string };

/**
 * A minimal Gantt view — each task renders as a proportional bar positioned
 * within the project's overall date span. Good enough to see sequencing and
 * progress at a glance without pulling in a charting library for Phase 2.
 *
 * M12: dependency picker (create + per-task), per-task start/end date editing,
 * a predecessor tag, and a transient "N tasks shifted" notice when a schedule
 * change cascades to dependents. All write controls remain gated by `canWrite`;
 * clients keep the read-only view.
 */
export function ProjectTimeline({
  projectId,
  projectStart,
  projectEnd,
  canWrite,
}: {
  projectId: string;
  projectStart: string;
  projectEnd: string;
  canWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<{ name: string; start_date: string; end_date: string; depends_on_id: string }>(
    { name: "", start_date: "", end_date: "", depends_on_id: "" }
  );
  const [notice, setNotice] = useState<string | null>(null);

  // Snapshot machinery for the "N tasks shifted" notice: dates at the moment a
  // mutation starts, compared to the refetched list after it succeeds.
  const prevDatesRef = useRef<Record<string, TaskDates>>({});
  const pendingCompareRef = useRef(false);
  const lastEditedRef = useRef<string | null>(null);

  const { data: tasks, isLoading } = useQuery({
    queryKey: ["tasks", projectId],
    queryFn: async () => {
      const { data } = await api.get<ProjectTask[]>(`/projects/${projectId}/tasks`);
      return data;
    },
  });

  function snapshotDates() {
    prevDatesRef.current = Object.fromEntries(
      (tasks ?? []).map((t) => [t.id, { start: t.start_date, end: t.end_date }])
    );
  }

  useEffect(() => {
    if (!pendingCompareRef.current || !tasks) return;
    pendingCompareRef.current = false;
    const shifted = tasks.filter(
      (t) =>
        t.id !== lastEditedRef.current &&
        prevDatesRef.current[t.id] &&
        (prevDatesRef.current[t.id].start !== t.start_date ||
          prevDatesRef.current[t.id].end !== t.end_date)
    );
    if (shifted.length > 0) {
      setNotice(
        `${shifted.length} task${shifted.length === 1 ? "" : "s"} shifted to keep dependencies valid`
      );
      const timer = window.setTimeout(() => setNotice(null), 6000);
      return () => window.clearTimeout(timer);
    }
  }, [tasks]);

  const createTask = useMutation({
    mutationFn: async (payload: TaskCreateInput) => {
      await api.post(`/projects/${projectId}/tasks`, payload);
    },
    onMutate: () => {
      lastEditedRef.current = null;
      snapshotDates();
      pendingCompareRef.current = true;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
      setForm({ name: "", start_date: "", end_date: "", depends_on_id: "" });
      setShowForm(false);
    },
  });

  const updateTask = useMutation({
    mutationFn: async ({ id, fields }: { id: string; fields: Record<string, unknown> }) => {
      await api.patch(`/projects/${projectId}/tasks/${id}`, fields);
    },
    onMutate: ({ id }) => {
      lastEditedRef.current = id;
      snapshotDates();
      pendingCompareRef.current = true;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
  });

  const deleteTask = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/projects/${projectId}/tasks/${id}`);
    },
    onMutate: (id) => {
      lastEditedRef.current = id;
      snapshotDates();
      pendingCompareRef.current = true;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
  });

  const spanDays = daysBetween(projectStart, projectEnd);
  const taskById = new Map((tasks ?? []).map((t) => [t.id, t]));

  return (
    <div className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">TIMELINE</p>
        {canWrite && (
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
          >
            <Plus size={13} /> Add task
          </button>
        )}
      </div>

      {notice && (
        <div className="mb-4 rounded-md border border-status-amber/30 bg-status-amber/10 px-3 py-2 text-xs text-status-amber">
          {notice}
        </div>
      )}

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.name || !form.start_date || !form.end_date) return;
            createTask.mutate({
              name: form.name,
              start_date: form.start_date,
              end_date: form.end_date,
              depends_on_id: form.depends_on_id || null,
            });
          }}
          className="mb-4 grid grid-cols-1 gap-2 rounded-md border border-dashed border-ink-border p-3 sm:grid-cols-4"
        >
          <input
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper sm:col-span-2"
            placeholder="Task name (e.g. Foundation)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            type="date"
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            value={form.start_date}
            onChange={(e) => setForm({ ...form, start_date: e.target.value })}
          />
          <input
            type="date"
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            value={form.end_date}
            onChange={(e) => setForm({ ...form, end_date: e.target.value })}
          />
          <select
            value={form.depends_on_id}
            onChange={(e) => setForm({ ...form, depends_on_id: e.target.value })}
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
          >
            <option value="">No dependency</option>
            {(tasks ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                After: {t.name}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={createTask.isPending}
            className="col-span-full rounded bg-blueprint-400/15 py-1.5 text-sm text-blueprint-400 hover:bg-blueprint-400/25 disabled:opacity-50"
          >
            {createTask.isPending ? "Adding…" : "Add task"}
          </button>
        </form>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading timeline…
        </div>
      )}

      {tasks && tasks.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">
          No tasks yet. Add the first milestone above.
        </p>
      )}

      {tasks && tasks.length > 0 && (
        <div className="space-y-2">
          {tasks.map((task) => {
            const offsetDays = daysBetween(projectStart, task.start_date) - 1;
            const durationDays = daysBetween(task.start_date, task.end_date);
            const leftPct = Math.min(100, (offsetDays / spanDays) * 100);
            const widthPct = Math.min(100 - leftPct, (durationDays / spanDays) * 100);
            const status = STATUS_CONFIG[task.status];
            const predecessor = task.depends_on_id ? taskById.get(task.depends_on_id) : null;

            return (
              <div key={task.id} className="group">
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1.5 text-paper">
                    {predecessor && (
                      <span className="flex items-center gap-1 text-[10px] text-paper-faint">
                        <ArrowRight size={10} />
                        {predecessor.name}
                      </span>
                    )}
                    {task.name}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] ${status.className}`}>
                      {status.label}
                    </span>
                    <span className="text-paper-muted">{task.percent_complete}%</span>
                    {canWrite && (
                      <button
                        onClick={() => deleteTask.mutate(task.id)}
                        className="text-paper-faint opacity-0 transition-opacity hover:text-status-red group-hover:opacity-100"
                        title="Delete task"
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                </div>
                <div className="relative h-5 rounded bg-ink">
                  <div
                    className="absolute top-0 h-5 rounded bg-blueprint-400/25"
                    style={{ left: `${leftPct}%`, width: `${Math.max(widthPct, 2)}%` }}
                  >
                    <div
                      className="h-5 rounded bg-blueprint-400/60"
                      style={{ width: `${task.percent_complete}%` }}
                    />
                  </div>
                </div>
                {canWrite && (
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <select
                      value={task.status}
                      onChange={(e) =>
                        updateTask.mutate({ id: task.id, fields: { status: e.target.value as TaskStatus } })
                      }
                      className="rounded border border-ink-border bg-ink px-1.5 py-0.5 text-[11px] text-paper-muted"
                    >
                      {Object.entries(STATUS_CONFIG).map(([value, cfg]) => (
                        <option key={value} value={value}>
                          {cfg.label}
                        </option>
                      ))}
                    </select>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={task.percent_complete}
                      onChange={(e) =>
                        updateTask.mutate({ id: task.id, fields: { percent_complete: Number(e.target.value) } })
                      }
                      className="h-1 w-24 accent-blueprint-400"
                    />
                    <input
                      type="date"
                      aria-label="Start date"
                      value={task.start_date}
                      onChange={(e) =>
                        updateTask.mutate({ id: task.id, fields: { start_date: e.target.value } })
                      }
                      className="rounded border border-ink-border bg-ink px-1.5 py-0.5 text-[11px] text-paper-muted"
                    />
                    <input
                      type="date"
                      aria-label="End date"
                      value={task.end_date}
                      onChange={(e) =>
                        updateTask.mutate({ id: task.id, fields: { end_date: e.target.value } })
                      }
                      className="rounded border border-ink-border bg-ink px-1.5 py-0.5 text-[11px] text-paper-muted"
                    />
                    <select
                      value={task.depends_on_id ?? ""}
                      onChange={(e) =>
                        updateTask.mutate({ id: task.id, fields: { depends_on_id: e.target.value || null } })
                      }
                      className="rounded border border-ink-border bg-ink px-1.5 py-0.5 text-[11px] text-paper-muted"
                    >
                      <option value="">No dependency</option>
                      {tasks
                        .filter((t) => t.id !== task.id)
                        .map((t) => (
                          <option key={t.id} value={t.id}>
                            After: {t.name}
                          </option>
                        ))}
                    </select>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
