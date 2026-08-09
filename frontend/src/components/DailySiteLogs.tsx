import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Loader2, CloudSun, Users, AlertTriangle } from "lucide-react";
import { api } from "../lib/api";
import type { DailySiteLog, DailySiteLogCreateInput } from "../types";

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

const emptyForm: DailySiteLogCreateInput = {
  log_date: new Date().toISOString().slice(0, 10),
  work_summary: "",
  issues: "",
  workers_present: undefined,
  weather: "",
};

export function DailySiteLogs({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<DailySiteLogCreateInput>(emptyForm);

  const { data: logs, isLoading } = useQuery({
    queryKey: ["site-logs", projectId],
    queryFn: async () => {
      const { data } = await api.get<DailySiteLog[]>(`/projects/${projectId}/site-logs`);
      return data;
    },
  });

  const createLog = useMutation({
    mutationFn: async (payload: DailySiteLogCreateInput) => {
      await api.post(`/projects/${projectId}/site-logs`, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["site-logs", projectId] });
      setForm(emptyForm);
      setShowForm(false);
    },
  });

  return (
    <div className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">DAILY SITE LOGS</p>
        {canWrite && (
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
          >
            <Plus size={13} /> New entry
          </button>
        )}
      </div>

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.work_summary.trim()) return;
            createLog.mutate(form);
          }}
          className="mb-4 space-y-2 rounded-md border border-dashed border-ink-border p-3"
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <input
              type="date"
              className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
              value={form.log_date}
              onChange={(e) => setForm({ ...form, log_date: e.target.value })}
            />
            <input
              type="number"
              min={0}
              placeholder="Workers present"
              className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
              value={form.workers_present ?? ""}
              onChange={(e) =>
                setForm({ ...form, workers_present: e.target.value ? Number(e.target.value) : undefined })
              }
            />
            <input
              placeholder="Weather (e.g. Clear)"
              className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
              value={form.weather ?? ""}
              onChange={(e) => setForm({ ...form, weather: e.target.value })}
            />
          </div>
          <textarea
            placeholder="Work completed today…"
            rows={2}
            className="w-full rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            value={form.work_summary}
            onChange={(e) => setForm({ ...form, work_summary: e.target.value })}
          />
          <textarea
            placeholder="Issues / blockers (optional)"
            rows={1}
            className="w-full rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            value={form.issues ?? ""}
            onChange={(e) => setForm({ ...form, issues: e.target.value })}
          />
          <button
            type="submit"
            disabled={createLog.isPending}
            className="w-full rounded bg-blueprint-400/15 py-1.5 text-sm text-blueprint-400 hover:bg-blueprint-400/25 disabled:opacity-50"
          >
            {createLog.isPending ? "Saving…" : "Save log entry"}
          </button>
        </form>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading logs…
        </div>
      )}

      {logs && logs.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">No site logs recorded yet.</p>
      )}

      {logs && logs.length > 0 && (
        <div className="max-h-96 space-y-3 overflow-y-auto">
          {logs.map((log) => (
            <div key={log.id} className="rounded-md border border-ink-border p-3">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-xs font-medium text-paper">{formatDate(log.log_date)}</span>
                <div className="flex items-center gap-3 text-[11px] text-paper-muted">
                  {log.workers_present !== null && (
                    <span className="flex items-center gap-1">
                      <Users size={11} /> {log.workers_present}
                    </span>
                  )}
                  {log.weather && (
                    <span className="flex items-center gap-1">
                      <CloudSun size={11} /> {log.weather}
                    </span>
                  )}
                </div>
              </div>
              <p className="text-sm text-paper-muted">{log.work_summary}</p>
              {log.issues && (
                <p className="mt-1 flex items-start gap-1.5 text-sm text-status-amber">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {log.issues}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
