import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldAlert, Undo2 } from "lucide-react";
import {
  getHealthOverrides,
  revokeHealthOverride,
  setHealthOverride,
} from "../lib/api";
import type {
  HealthOverrideCreateInput,
  HealthOverrideValue,
  HealthOverrideTarget,
  ProjectHealth,
} from "../types";
import { HealthDot } from "./HealthDot";

const TARGETS: { key: HealthOverrideTarget; label: string }[] = [
  { key: "overall", label: "Overall" },
  { key: "timeline", label: "Timeline" },
  { key: "budget", label: "Budget" },
  { key: "safety", label: "Safety" },
];

const VALUES: { key: HealthOverrideValue; label: string }[] = [
  { key: "green", label: "Green — on track" },
  { key: "amber", label: "Amber — at risk" },
  { key: "red", label: "Red — off track" },
];

const EMPTY_FORM: HealthOverrideCreateInput = {
  applied_to: "overall",
  value: "green",
  reason: "",
  expires_in_days: null,
};

function formatRelative(iso: string) {
  const days = Math.max(
    0,
    Math.round(
      (Date.now() - new Date(iso).getTime()) / (24 * 60 * 60 * 1000)
    )
  );
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

function DimensionBlock({
  title,
  dim,
}: {
  title: string;
  dim: ProjectHealth["timeline"];
}) {
  const overridden = dim.value !== dim.effective;
  return (
    <div className="rounded-md border border-ink-border p-3">
      <div className="mb-1.5 flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-wide text-paper-muted">
          {title}
        </p>
        <HealthDot status={dim.effective} showLabel />
      </div>
      {overridden && (
        <p className="mb-1 text-[11px] text-blueprint-300">
          Computed: <HealthDot status={dim.value} />{" "}
          <span className="uppercase">{dim.value}</span> · override applied
        </p>
      )}
      {dim.reasons.map((reason) => (
        <p key={reason} className="text-xs text-paper-muted">
          {reason}
        </p>
      ))}
    </div>
  );
}

export function ProjectHealthPanel({
  projectId,
  health,
  isOverrideManager,
  canWriteHealth,
}: {
  projectId: string;
  health: ProjectHealth;
  isOverrideManager: boolean;
  canWriteHealth: boolean;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<HealthOverrideCreateInput>(EMPTY_FORM);
  const [formError, setFormError] = useState("");

  const { data: history = [] } = useQuery({
    queryKey: ["overrides", projectId],
    queryFn: () => getHealthOverrides(projectId),
    enabled: isOverrideManager,
  });

  const invalidateHealth = () => {
    queryClient.invalidateQueries({ queryKey: ["project-health", projectId] });
    queryClient.invalidateQueries({ queryKey: ["projects-health"] });
    queryClient.invalidateQueries({ queryKey: ["overrides", projectId] });
  };

  const createMutation = useMutation({
    mutationFn: ({
      projectId: pid,
      input,
    }: {
      projectId: string;
      input: HealthOverrideCreateInput;
    }) => setHealthOverride(pid, input),
    onSuccess: () => {
      invalidateHealth();
      setForm(EMPTY_FORM);
      setFormError("");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Could not set the override.";
      setFormError(msg);
    },
  });

  const revokeMutation = useMutation({
    mutationFn: ({
      projectId: pid,
      overrideId,
    }: {
      projectId: string;
      overrideId: string;
    }) => revokeHealthOverride(pid, overrideId),
    onSuccess: invalidateHealth,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (form.reason.trim().length < 10) {
      setFormError("A reason of at least 10 characters is required.");
      return;
    }
    createMutation.mutate({
      projectId,
      input: {
        ...form,
        expires_in_days: form.expires_in_days || null,
      },
    });
  };

  const safetyNotTracked = !health.safety.rated;

  return (
    <div className="rounded-md border border-ink-border">
      <div className="flex items-center justify-between border-b border-ink-border px-4 py-3">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">
          PROJECT HEALTH
        </p>
        {health.frozen && (
          <span className="rounded border border-ink-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-paper-muted">
            Frozen — reflects completion state
          </span>
        )}
      </div>

      <div className="space-y-4 p-4">
        {/* Overall summary */}
        <div className="rounded-md border border-ink-border bg-ink p-3">
          <div className="flex items-center justify-between">
            <p className="text-[11px] uppercase tracking-wide text-paper-muted">
              Overall
            </p>
            <HealthDot status={health.overall.effective} showLabel />
          </div>
          {health.overall.reasons.map((reason) => (
            <p key={reason} className="mt-1 text-xs text-paper-muted">
              {reason}
            </p>
          ))}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <DimensionBlock title="Timeline" dim={health.timeline} />
          <DimensionBlock title="Budget" dim={health.budget} />
          <DimensionBlock title="Safety" dim={health.safety} />
        </div>

        {safetyNotTracked && (
          <div className="flex items-start gap-2 rounded-md border border-ink-border bg-ink px-3 py-2 text-xs text-paper-muted">
            <ShieldAlert size={14} className="mt-0.5 shrink-0" />
            <span>
              Safety is not rated: no incident/inspection records are captured
              yet. It is excluded from the overall verdict until a safety-data
              milestone ships.
            </span>
          </div>
        )}
      </div>

      {/* Admin-only override surface */}
      {isOverrideManager && (
        <div className="border-t border-ink-border px-4 py-3">
          <p className="mb-2 font-mono text-xs tracking-widest text-blueprint-400">
            HEALTH OVERRIDE
          </p>
          {!canWriteHealth && (
            <p className="mb-2 text-xs text-status-red">
              This project is archived — overrides cannot be added.
            </p>
          )}
          <form onSubmit={submit} className={`space-y-3 ${canWriteHealth ? "" : "opacity-40"}`}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block text-xs text-paper-muted">
                Applies to
                <select
                  value={form.applied_to}
                  disabled={!canWriteHealth}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      applied_to: e.target.value as HealthOverrideTarget,
                    })
                  }
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none disabled:opacity-50"
                >
                  {TARGETS.map((t) => (
                    <option key={t.key} value={t.key}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-paper-muted">
                Verdict
                <select
                  value={form.value}
                  disabled={!canWriteHealth}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      value: e.target.value as HealthOverrideValue,
                    })
                  }
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none disabled:opacity-50"
                >
                  {VALUES.map((v) => (
                    <option key={v.key} value={v.key}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="block text-xs text-paper-muted">
              Reason (mandatory, at least 10 characters)
              <textarea
                value={form.reason}
                disabled={!canWriteHealth}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                rows={2}
                className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                placeholder="e.g. Timeline re-baselined after monsoon ground-water issue"
              />
            </label>
            <label className="block text-xs text-paper-muted">
              Expires after (days) — optional
              <input
                type="number"
                min={1}
                value={form.expires_in_days ?? ""}
                disabled={!canWriteHealth}
                onChange={(e) =>
                  setForm({
                    ...form,
                    expires_in_days: e.target.value
                      ? Number(e.target.value)
                      : null,
                  })
                }
                className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none disabled:opacity-50"
                placeholder="Leave blank to never expire"
              />
            </label>
            {formError && <p className="text-xs text-status-red">{formError}</p>}
            <button
              type="submit"
              disabled={!canWriteHealth || createMutation.isPending}
              className="flex items-center gap-1.5 rounded bg-blueprint-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blueprint-400 disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                "Set override"
              )}
            </button>
          </form>

          {history.length > 0 && (
            <div className="mt-4">
              <p className="mb-2 text-[11px] uppercase tracking-wide text-paper-muted">
                Override history
              </p>
              <ul className="space-y-2">
                {history.map((o) => (
                  <li
                    key={o.id}
                    className="flex items-start justify-between gap-3 rounded border border-ink-border bg-ink px-3 py-2 text-xs"
                  >
                    <div className="min-w-0">
                      <p className="text-paper">
                        <span className="font-mono text-[11px] uppercase text-paper-muted">
                          {o.applied_to}
                        </span>{" "}
                        →{" "}
                        <span className="uppercase">{o.value}</span>
                        <span className="ml-2 text-paper-faint">
                          {formatRelative(o.created_at)}
                        </span>
                        {!o.active && o.revoked_at && (
                          <span className="ml-2 text-paper-faint">
                            · revoked
                          </span>
                        )}
                      </p>
                      <p className="mt-0.5 text-paper-muted">{o.reason}</p>
                      {o.expires_at && (
                        <p className="mt-0.5 text-paper-faint">
                          Expires {formatRelative(o.expires_at)}
                        </p>
                      )}
                    </div>
                    {o.active && (
                      <button
                        onClick={() =>
                          revokeMutation.mutate({ projectId, overrideId: o.id })
                        }
                        disabled={revokeMutation.isPending}
                        className="flex shrink-0 items-center gap-1 rounded border border-ink-border px-2 py-1 text-[11px] text-paper-muted hover:text-paper disabled:opacity-50"
                        title="Revoke (soft delete — history retained)"
                      >
                        <Undo2 size={12} />
                        Revoke
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}