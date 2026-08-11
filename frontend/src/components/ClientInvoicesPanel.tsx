import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { listInvoices } from "../lib/api";
import type { InvoiceClientRead, InvoiceStatus } from "../types";

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

function statusBadge(status: InvoiceStatus) {
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

// Clients see only their assigned projects' payment requests, in the
// restricted server-side shape — never notes, internal references or billing
// rules. Mirrors the backend InvoiceClientRead contract.
export function ClientInvoicesPanel({ projectId }: { projectId: string }) {
  const { data: invoices, isLoading } = useQuery({
    queryKey: ["invoices", projectId],
    queryFn: async () => (await listInvoices(projectId)) as InvoiceClientRead[],
  });

  return (
    <div className="rounded-md border border-ink-border bg-ink-surface p-5">
      <p className="mb-4 font-mono text-xs tracking-widest text-blueprint-400">
        PAYMENT REQUESTS
      </p>

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading payment requests…
        </div>
      )}

      {invoices && invoices.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">
          No payment requests yet.
        </p>
      )}

      {invoices && invoices.length > 0 && (
        <div className="space-y-2">
          {invoices.map((inv) => {
            const badge = statusBadge(inv.status);
            return (
              <div key={inv.id} className="flex items-center justify-between gap-3 rounded-md border border-ink-border p-3">
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
                <p className="shrink-0 font-mono text-sm text-paper">
                  {formatCurrency(inv.amount)}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
