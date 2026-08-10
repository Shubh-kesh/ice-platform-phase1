import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Loader2, IndianRupee, AlertTriangle } from "lucide-react";
import { api } from "../lib/api";
import type { BudgetRollup, CostCode, JobCost, JobCostCreateInput } from "../types";

const COST_CODE_LABEL: Record<CostCode, string> = {
  foundation: "Foundation",
  structure: "Structure",
  masonry: "Masonry",
  roofing: "Roofing",
  electrical: "Electrical",
  plumbing: "Plumbing",
  hvac: "HVAC",
  finishing: "Finishing",
  landscaping: "Landscaping",
  labor: "Labor",
  material: "Material",
  equipment: "Equipment",
  other: "Other",
};

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

function getErrorMessage(err: unknown) {
  if (typeof err === "object" && err && "response" in err) {
    return (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
  }
  return undefined;
}

export function JobCostsPanel({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<JobCostCreateInput>({
    cost_code: "labor",
    description: "",
    amount: 0,
    incurred_on: new Date().toISOString().slice(0, 10),
  });

  const { data: costs, isLoading } = useQuery({
    queryKey: ["job-costs", projectId],
    queryFn: async () => {
      const { data } = await api.get<JobCost[]>(`/projects/${projectId}/job-costs`);
      return data;
    },
  });

  const { data: budget } = useQuery({
    queryKey: ["budget", projectId],
    queryFn: async () => {
      const { data } = await api.get<BudgetRollup>(`/projects/${projectId}/budget`);
      return data;
    },
  });

  const createCost = useMutation({
    mutationFn: async (payload: JobCostCreateInput) => {
      await api.post(`/projects/${projectId}/job-costs`, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job-costs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["budget", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      setForm({ cost_code: "labor", description: "", amount: 0, incurred_on: new Date().toISOString().slice(0, 10) });
      setShowForm(false);
      setError("");
    },
    onError: (err: unknown) => {
      setError(getErrorMessage(err) ?? "Could not record cost.");
    },
  });

  return (
    <div className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">JOB COST</p>
        {canWrite && (
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
          >
            <Plus size={13} /> Add cost
          </button>
        )}
      </div>

      {error && (
        <p className="mb-3 inline-flex items-center gap-1.5 rounded border border-status-red/30 bg-status-red/10 px-2 py-1.5 text-xs text-status-red">
          <AlertTriangle size={12} /> {error}
        </p>
      )}

      {budget && (
        <div className="mb-4 grid grid-cols-3 gap-3 text-center">
          <div className="rounded-md border border-ink-border bg-ink p-2">
            <p className="text-[10px] uppercase tracking-wide text-paper-muted">Budget</p>
            <p className="font-mono text-sm text-paper">{formatCurrency(budget.budget_total)}</p>
          </div>
          <div className="rounded-md border border-ink-border bg-ink p-2">
            <p className="text-[10px] uppercase tracking-wide text-paper-muted">Spent</p>
            <p className="font-mono text-sm text-paper">{formatCurrency(budget.budget_spent)}</p>
          </div>
          <div className="rounded-md border border-ink-border bg-ink p-2">
            <p className="text-[10px] uppercase tracking-wide text-paper-muted">Remaining</p>
            <p className="font-mono text-sm text-paper">{formatCurrency(budget.budget_remaining)}</p>
          </div>
        </div>
      )}

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.description || form.amount <= 0 || !form.incurred_on) return;
            createCost.mutate(form);
          }}
          className="mb-4 grid grid-cols-1 gap-2 rounded-md border border-dashed border-ink-border p-3 sm:grid-cols-4"
        >
          <select
            value={form.cost_code}
            onChange={(e) => setForm({ ...form, cost_code: e.target.value as CostCode })}
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
          >
            {Object.entries(COST_CODE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <input
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper sm:col-span-1"
            placeholder="Description"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <input
            type="number"
            min={1}
            step="0.01"
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            placeholder="Amount (₹)"
            value={form.amount || ""}
            onChange={(e) => setForm({ ...form, amount: Number(e.target.value) })}
          />
          <input
            type="date"
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            value={form.incurred_on}
            onChange={(e) => setForm({ ...form, incurred_on: e.target.value })}
          />
          <button
            type="submit"
            disabled={createCost.isPending}
            className="col-span-full flex items-center justify-center gap-1.5 rounded bg-blueprint-400/15 py-1.5 text-sm text-blueprint-400 hover:bg-blueprint-400/25 disabled:opacity-50"
          >
            <IndianRupee size={14} />
            {createCost.isPending ? "Saving…" : "Add cost"}
          </button>
        </form>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading costs…
        </div>
      )}

      {costs && costs.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">No costs recorded yet.</p>
      )}

      {costs && costs.length > 0 && (
        <div className="space-y-2">
          {costs.map((cost) => (
            <div key={cost.id} className="flex items-center justify-between rounded-md border border-ink-border p-3">
              <div>
                <p className="text-sm text-paper">
                  {COST_CODE_LABEL[cost.cost_code]}
                  <span className="ml-2 text-xs text-paper-muted">{cost.description}</span>
                </p>
                <p className="text-xs text-paper-muted">{cost.incurred_on}</p>
              </div>
              <p className="font-mono text-sm text-paper">{formatCurrency(cost.amount)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}