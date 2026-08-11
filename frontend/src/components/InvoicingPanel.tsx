import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2, Plus, Send, XCircle } from "lucide-react";
import {
  completeBillingMilestone,
  createBillingMilestone,
  createInvoice,
  listBillingMilestones,
  listInvoices,
  transitionInvoice,
} from "../lib/api";
import type {
  BillingMilestone,
  BillingMilestoneCreateInput,
  BillingMilestoneStatus,
  Invoice,
  InvoiceStatus,
} from "../types";

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDate(value: string) {
  return new Date(value + "T00:00:00").toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function getErrorMessage(err: unknown) {
  if (typeof err === "object" && err && "response" in err) {
    return (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
  }
  return undefined;
}

function milestoneStatusBadge(status: BillingMilestoneStatus) {
  const styles: Record<BillingMilestoneStatus, string> = {
    not_started: "border-ink-border bg-ink text-paper-muted",
    in_progress: "border-status-amber/40 bg-status-amber/10 text-status-amber",
    completed: "border-status-green/40 bg-status-green/10 text-status-green",
  };
  const labels: Record<BillingMilestoneStatus, string> = {
    not_started: "Not started",
    in_progress: "In progress",
    completed: "Completed",
  };
  return { className: styles[status], label: labels[status] };
}

function invoiceStatusBadge(status: InvoiceStatus) {
  const styles: Record<InvoiceStatus, string> = {
    draft: "border-ink-border bg-ink text-paper-muted",
    sent: "border-status-amber/40 bg-status-amber/10 text-status-amber",
    paid: "border-status-green/40 bg-status-green/10 text-status-green",
    cancelled: "border-ink-border bg-ink text-paper-faint line-through",
  };
  const labels: Record<InvoiceStatus, string> = {
    draft: "Draft",
    sent: "Issued",
    paid: "Paid",
    cancelled: "Cancelled",
  };
  return { className: styles[status], label: labels[status] };
}

function milestoneRule(m: BillingMilestone) {
  if (m.billing_type === "percentage") return `${m.billing_percentage}% of contract`;
  return m.fixed_amount != null ? formatCurrency(m.fixed_amount) : "—";
}

const EMPTY_FORM: BillingMilestoneCreateInput = {
  name: "",
  billing_type: "percentage",
  billing_percentage: 10,
  fixed_amount: null,
  description: "",
  sort_order: 0,
};

export function InvoicingPanel({
  projectId,
  canWrite,
  contractTotal,
}: {
  projectId: string;
  canWrite: boolean;
  contractTotal: number;
}) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<BillingMilestoneCreateInput>(EMPTY_FORM);

  const { data: milestones, isLoading } = useQuery({
    queryKey: ["billing-milestones", projectId],
    queryFn: () => listBillingMilestones(projectId),
  });

  const { data: invoices = [] } = useQuery({
    queryKey: ["invoices", projectId],
    queryFn: async () => (await listInvoices(projectId)) as Invoice[],
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["billing-milestones", projectId] });
    queryClient.invalidateQueries({ queryKey: ["invoices", projectId] });
  };

  const createMilestone = useMutation({
    mutationFn: async () => {
      const payload = {
        ...form,
        billing_percentage: form.billing_type === "percentage" ? form.billing_percentage : null,
        fixed_amount: form.billing_type === "fixed_amount" ? form.fixed_amount : null,
        description: form.description || null,
      };
      return createBillingMilestone(projectId, payload);
    },
    onSuccess: () => {
      invalidate();
      setForm(EMPTY_FORM);
      setShowForm(false);
      setError("");
    },
    onError: (err: unknown) => setError(getErrorMessage(err) ?? "Could not add milestone."),
  });

  const completeMilestone = useMutation({
    mutationFn: (milestoneId: string) => completeBillingMilestone(projectId, milestoneId),
    onSuccess: () => {
      invalidate();
      setError("");
    },
    onError: (err: unknown) => setError(getErrorMessage(err) ?? "Could not complete milestone."),
  });

  const generateInvoice = useMutation({
    mutationFn: (milestoneId: string) => createInvoice(projectId, { billing_milestone_id: milestoneId }),
    onSuccess: () => {
      invalidate();
      setError("");
    },
    onError: (err: unknown) => setError(getErrorMessage(err) ?? "Could not generate invoice."),
  });

  const invoiceTransition = useMutation({
    mutationFn: ({
      invoiceId,
      action,
    }: {
      invoiceId: string;
      action: "issue" | "mark-paid" | "cancel";
    }) => transitionInvoice(projectId, invoiceId, action),
    onSuccess: () => {
      invalidate();
      setError("");
    },
    onError: (err: unknown) => setError(getErrorMessage(err) ?? "Could not update invoice."),
  });

  // A milestone that already has a non-cancelled invoice is "invoiced" — the
  // generate button must not be offered again (the backend returns 409).
  const invoiceByMilestone = new Map<string, Invoice>(
    invoices
      .filter((inv) => inv.status !== "cancelled" && inv.billing_milestone_id)
      .map((inv) => [inv.billing_milestone_id!, inv])
  );

  const invoicedTotal = invoices
    .filter((inv) => inv.status !== "cancelled")
    .reduce((sum, inv) => sum + inv.amount, 0);
  const outstandingTotal = invoices
    .filter((inv) => inv.status === "sent")
    .reduce((sum, inv) => sum + inv.amount, 0);

  return (
    <div className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">
          BILLING & INVOICES
        </p>
        {canWrite && (
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
          >
            <Plus size={13} /> Add milestone
          </button>
        )}
      </div>

      {error && (
        <p className="mb-3 inline-flex items-center gap-1.5 rounded border border-status-red/30 bg-status-red/10 px-2 py-1.5 text-xs text-status-red">
          <AlertTriangle size={12} /> {error}
        </p>
      )}

      <div className="mb-4 grid grid-cols-3 gap-3 text-center">
        <div className="rounded-md border border-ink-border bg-ink p-2">
          <p className="text-[10px] uppercase tracking-wide text-paper-muted">Contract</p>
          <p className="font-mono text-sm text-paper">{formatCurrency(contractTotal)}</p>
        </div>
        <div className="rounded-md border border-ink-border bg-ink p-2">
          <p className="text-[10px] uppercase tracking-wide text-paper-muted">Invoiced</p>
          <p className="font-mono text-sm text-paper">{formatCurrency(invoicedTotal)}</p>
        </div>
        <div className="rounded-md border border-ink-border bg-ink p-2">
          <p className="text-[10px] uppercase tracking-wide text-paper-muted">Outstanding</p>
          <p className="font-mono text-sm text-paper">{formatCurrency(outstandingTotal)}</p>
        </div>
      </div>

      {showForm && canWrite && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.name) return;
            if (form.billing_type === "percentage" && !form.billing_percentage) return;
            if (form.billing_type === "fixed_amount" && !form.fixed_amount) return;
            createMilestone.mutate();
          }}
          className="mb-4 grid grid-cols-1 gap-2 rounded-md border border-dashed border-ink-border p-3 sm:grid-cols-4"
        >
          <input
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            placeholder="Milestone name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <select
            value={form.billing_type}
            onChange={(e) =>
              setForm({
                ...form,
                billing_type: e.target.value as BillingMilestoneCreateInput["billing_type"],
              })
            }
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
          >
            <option value="percentage">% of contract</option>
            <option value="fixed_amount">Fixed amount</option>
          </select>
          {form.billing_type === "percentage" ? (
            <input
              type="number"
              min={0.01}
              max={100}
              step="0.01"
              className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
              placeholder="Percentage"
              value={form.billing_percentage ?? ""}
              onChange={(e) => setForm({ ...form, billing_percentage: Number(e.target.value) })}
            />
          ) : (
            <input
              type="number"
              min={1}
              step="0.01"
              className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
              placeholder="Amount (₹)"
              value={form.fixed_amount ?? ""}
              onChange={(e) => setForm({ ...form, fixed_amount: Number(e.target.value) })}
            />
          )}
          <input
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            placeholder="Description (optional)"
            value={form.description ?? ""}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <button
            type="submit"
            disabled={createMilestone.isPending}
            className="col-span-full flex items-center justify-center gap-1.5 rounded bg-blueprint-400/15 py-1.5 text-sm text-blueprint-400 hover:bg-blueprint-400/25 disabled:opacity-50"
          >
            <Plus size={14} />
            {createMilestone.isPending ? "Saving…" : "Add milestone"}
          </button>
        </form>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading schedule…
        </div>
      )}

      {milestones && milestones.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">
          No billing milestones yet. Add the schedule of values to start invoicing.
        </p>
      )}

      {milestones && milestones.length > 0 && (
        <div className="space-y-2">
          {milestones.map((m) => {
            const badge = milestoneStatusBadge(m.status);
            const existing = invoiceByMilestone.get(m.id);
            return (
              <div key={m.id} className="rounded-md border border-ink-border p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-paper">
                      {m.name}
                      <span className="ml-2 font-mono text-xs text-paper-muted">
                        {milestoneRule(m)}
                      </span>
                    </p>
                    <p className="mt-1 flex items-center gap-2">
                      <span
                        className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] ${badge.className}`}
                      >
                        {badge.label}
                      </span>
                      {m.description && (
                        <span className="truncate text-xs text-paper-muted">{m.description}</span>
                      )}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {m.status !== "completed" && canWrite && (
                      <button
                        onClick={() => completeMilestone.mutate(m.id)}
                        disabled={completeMilestone.isPending || generateInvoice.isPending}
                        className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper disabled:opacity-50"
                      >
                        <CheckCircle2 size={12} /> Complete
                      </button>
                    )}
                    {m.status === "completed" && canWrite && !existing && (
                      <button
                        onClick={() => generateInvoice.mutate(m.id)}
                        disabled={generateInvoice.isPending || completeMilestone.isPending}
                        className="flex items-center gap-1 rounded bg-blueprint-400/15 px-2 py-1 text-xs text-blueprint-400 hover:bg-blueprint-400/25 disabled:opacity-50"
                      >
                        <Send size={12} /> Generate invoice
                      </button>
                    )}
                    {existing && (
                      <span className="text-xs text-paper-faint">
                        {existing.invoice_number}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {invoices.length > 0 && (
        <div className="mt-5">
          <p className="mb-2 font-mono text-xs tracking-widest text-blueprint-400">
            INVOICES
          </p>
          <div className="space-y-2">
            {invoices.map((inv) => {
              const badge = invoiceStatusBadge(inv.status);
              return (
                <div key={inv.id} className="rounded-md border border-ink-border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs text-paper">
                        {inv.invoice_number}
                        <span className="ml-2 text-paper-muted">{inv.milestone_name}</span>
                      </p>
                      <p className="mt-1 flex items-center gap-2 text-xs text-paper-muted">
                        <span
                          className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] ${badge.className}`}
                        >
                          {badge.label}
                        </span>
                        <span>Due {formatDate(inv.due_date)}</span>
                        {inv.overdue && inv.status === "sent" && (
                          <span className="text-status-red">Overdue</span>
                        )}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <p className="font-mono text-sm text-paper">{formatCurrency(inv.amount)}</p>
                      {canWrite && inv.status === "draft" && (
                        <button
                          onClick={() => invoiceTransition.mutate({ invoiceId: inv.id, action: "issue" })}
                          disabled={invoiceTransition.isPending}
                          className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper disabled:opacity-50"
                        >
                          <Send size={12} /> Issue
                        </button>
                      )}
                      {canWrite && inv.status === "sent" && (
                        <>
                          <button
                            onClick={() => invoiceTransition.mutate({ invoiceId: inv.id, action: "mark-paid" })}
                            disabled={invoiceTransition.isPending}
                            className="flex items-center gap-1 rounded bg-status-green/15 px-2 py-1 text-xs text-status-green hover:bg-status-green/25 disabled:opacity-50"
                          >
                            <CheckCircle2 size={12} /> Mark paid
                          </button>
                          <button
                            onClick={() => {
                              if (window.confirm(`Cancel invoice ${inv.invoice_number}?`)) {
                                invoiceTransition.mutate({ invoiceId: inv.id, action: "cancel" });
                              }
                            }}
                            disabled={invoiceTransition.isPending}
                            className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-status-red/10 hover:text-status-red disabled:opacity-50"
                          >
                            <XCircle size={12} /> Cancel
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
