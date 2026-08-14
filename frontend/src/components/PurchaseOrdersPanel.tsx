import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Plus,
  Send,
  Trash2,
  Undo2,
  X,
  XCircle,
} from "lucide-react";
import {
  addPoLine,
  createPurchaseOrder,
  deletePoLine,
  listPurchaseOrders,
  listVendors,
  rejectPurchaseOrder,
  transitionPurchaseOrder,
  updatePoLine,
} from "../lib/api";
import type {
  CostCode,
  POLineCreateInput,
  PurchaseOrder,
  PurchaseOrderCreateInput,
  PurchaseOrderStatus,
} from "../types";

const COST_CODES: CostCode[] = [
  "foundation",
  "structure",
  "masonry",
  "roofing",
  "electrical",
  "plumbing",
  "hvac",
  "finishing",
  "landscaping",
  "labor",
  "material",
  "equipment",
  "other",
];

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

function poStatusBadge(status: PurchaseOrderStatus) {
  const styles: Record<PurchaseOrderStatus, string> = {
    draft: "border-ink-border bg-ink text-paper-muted",
    pending_approval: "border-status-amber/40 bg-status-amber/10 text-status-amber",
    approved: "border-status-green/40 bg-status-green/10 text-status-green",
    rejected: "border-status-red/40 bg-status-red/10 text-status-red",
    cancelled: "border-ink-border bg-ink text-paper-faint line-through",
  };
  const labels: Record<PurchaseOrderStatus, string> = {
    draft: "Draft",
    pending_approval: "Pending approval",
    approved: "Approved",
    rejected: "Rejected",
    cancelled: "Cancelled",
  };
  return { className: styles[status], label: labels[status] };
}

const EMPTY_LINE: POLineCreateInput = {
  description: "",
  quantity: 1,
  unit: "pcs",
  unit_price: 0,
  cost_code: "material",
};

export function PurchaseOrdersPanel({
  projectId,
  canWrite,
  canApprove,
  frozen,
}: {
  projectId: string;
  canWrite: boolean;
  canApprove: boolean;
  frozen: boolean;
}) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  const { data: vendors } = useQuery({
    queryKey: ["vendors"],
    queryFn: listVendors,
  });

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ["purchase-orders", projectId],
    queryFn: () => listPurchaseOrders(projectId),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["purchase-orders", projectId] });
  };

  const report = (err: unknown, fallback: string) =>
    setError(getErrorMessage(err) ?? fallback);

  const createMutation = useMutation({
    mutationFn: (payload: PurchaseOrderCreateInput) =>
      createPurchaseOrder(projectId, payload),
    onSuccess: () => {
      invalidate();
      setShowForm(false);
      setError("");
    },
    onError: (err: unknown) => report(err, "Could not create the purchase order."),
  });

  const transitionMutation = useMutation({
    mutationFn: ({
      poId,
      action,
    }: {
      poId: string;
      action: "submit" | "approve" | "revise" | "resubmit" | "cancel";
    }) => transitionPurchaseOrder(projectId, poId, action),
    onSuccess: () => {
      invalidate();
      setError("");
    },
    onError: (err: unknown) => report(err, "Could not update the purchase order."),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ poId, reason }: { poId: string; reason: string }) =>
      rejectPurchaseOrder(projectId, poId, reason),
    onSuccess: () => {
      invalidate();
      setError("");
    },
    onError: (err: unknown) => report(err, "Could not reject the purchase order."),
  });

  const addLineMutation = useMutation({
    mutationFn: ({ poId, line }: { poId: string; line: POLineCreateInput }) =>
      addPoLine(projectId, poId, line),
    onSuccess: () => {
      invalidate();
      setError("");
    },
    onError: (err: unknown) => report(err, "Could not add the line."),
  });

  const editLineMutation = useMutation({
    mutationFn: ({
      poId,
      lineId,
      input,
    }: {
      poId: string;
      lineId: string;
      input: Partial<POLineCreateInput>;
    }) => updatePoLine(projectId, poId, lineId, input),
    onSuccess: () => {
      invalidate();
      setError("");
    },
    onError: (err: unknown) => report(err, "Could not update the line."),
  });

  const deleteLineMutation = useMutation({
    mutationFn: ({ poId, lineId }: { poId: string; lineId: string }) =>
      deletePoLine(projectId, poId, lineId),
    onSuccess: () => {
      invalidate();
      setError("");
    },
    onError: (err: unknown) => report(err, "Could not remove the line."),
  });

  const activeVendors = (vendors ?? []).filter((v) => v.is_active);

  return (
    <div className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">
          PURCHASE ORDERS
        </p>
        {canWrite && !frozen && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
          >
            <Plus size={13} /> Create PO
          </button>
        )}
      </div>

      {error && (
        <p className="mb-3 inline-flex items-center gap-1.5 rounded border border-status-red/30 bg-status-red/10 px-2 py-1.5 text-xs text-status-red">
          <AlertTriangle size={12} /> {error}
        </p>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading purchase orders…
        </div>
      )}

      {!isLoading && orders.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">
          No purchase orders yet. Create a PO to start committing material spend.
        </p>
      )}

      {orders.length > 0 && (
        <div className="space-y-3">
          {orders.map((po) => (
            <PoCard
              key={po.id}
              po={po}
              canWrite={canWrite}
              canApprove={canApprove}
              frozen={frozen}
              onTransition={(action) =>
                transitionMutation.mutate({ poId: po.id, action })
              }
              onReject={(reason) => rejectMutation.mutate({ poId: po.id, reason })}
              onAddLine={(line) => addLineMutation.mutate({ poId: po.id, line })}
              onEditLine={(lineId, input) =>
                editLineMutation.mutate({ poId: po.id, lineId, input })
              }
              onDeleteLine={(lineId) =>
                deleteLineMutation.mutate({ poId: po.id, lineId })
              }
              busy={transitionMutation.isPending || rejectMutation.isPending}
            />
          ))}
        </div>
      )}

      {showForm && (
        <CreatePoForm
          vendors={activeVendors}
          onClose={() => setShowForm(false)}
          onSubmit={(payload) => createMutation.mutate(payload)}
          pending={createMutation.isPending}
        />
      )}
    </div>
  );
}

function PoCard({
  po,
  canWrite,
  canApprove,
  frozen,
  onTransition,
  onReject,
  onAddLine,
  onEditLine,
  onDeleteLine,
  busy,
}: {
  po: PurchaseOrder;
  canWrite: boolean;
  canApprove: boolean;
  frozen: boolean;
  onTransition: (action: "submit" | "approve" | "revise" | "resubmit" | "cancel") => void;
  onReject: (reason: string) => void;
  onAddLine: (line: POLineCreateInput) => void;
  onEditLine: (lineId: string, input: Partial<POLineCreateInput>) => void;
  onDeleteLine: (lineId: string) => void;
  busy: boolean;
}) {
  const [showAddLine, setShowAddLine] = useState(false);
  const [editingLineId, setEditingLineId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<POLineCreateInput>(EMPTY_LINE);
  const [newLine, setNewLine] = useState<POLineCreateInput>(EMPTY_LINE);

  const badge = poStatusBadge(po.status);
  const isDraft = po.status === "draft";
  const editable = canWrite && !frozen && isDraft;

  const rejectWithReason = () => {
    const reason = window.prompt("Rejection reason (required):");
    if (reason === null) return;
    if (!reason.trim()) {
      window.alert("A rejection reason is required.");
      return;
    }
    onReject(reason.trim());
  };

  const startEdit = (line: PurchaseOrder["lines"][number]) => {
    setEditingLineId(line.id);
    setEditForm({
      description: line.description,
      quantity: line.quantity,
      unit: line.unit,
      unit_price: line.unit_price,
      cost_code: line.cost_code,
    });
  };

  return (
    <div className="rounded-md border border-ink-border p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-paper">
            {po.po_number}
            <span className="ml-2 text-paper-muted">{po.vendor_name}</span>
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-paper-muted">
            <span
              className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] ${badge.className}`}
            >
              {badge.label}
            </span>
            <span>Ordered {formatDate(po.order_date)}</span>
            {po.expected_delivery && (
              <span>ETA {formatDate(po.expected_delivery)}</span>
            )}
            {po.tax_rate != null && <span>Tax {po.tax_rate}%</span>}
            <span>{po.lines.length} line(s)</span>
          </p>
          {po.status === "rejected" && po.rejected_reason && (
            <p className="mt-1 text-xs text-status-red">
              Rejected: {po.rejected_reason}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <p className="font-mono text-sm text-paper">{formatCurrency(po.total_amount)}</p>
          {canWrite && !frozen && po.status === "draft" && (
            <button
              onClick={() => onTransition("submit")}
              disabled={busy || po.lines.length === 0}
              className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper disabled:opacity-50"
              title={po.lines.length === 0 ? "Add at least one line first" : undefined}
            >
              <Send size={12} /> Submit
            </button>
          )}
          {canWrite && !frozen && po.status === "draft" && (
            <button
              onClick={() => {
                if (window.confirm(`Cancel PO ${po.po_number}?`)) onTransition("cancel");
              }}
              disabled={busy}
              className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-status-red/10 hover:text-status-red disabled:opacity-50"
            >
              <XCircle size={12} /> Cancel
            </button>
          )}
          {canApprove && !frozen && po.status === "pending_approval" && (
            <>
              <button
                onClick={() => onTransition("approve")}
                disabled={busy}
                className="flex items-center gap-1 rounded bg-status-green/15 px-2 py-1 text-xs text-status-green hover:bg-status-green/25 disabled:opacity-50"
              >
                <CheckCircle2 size={12} /> Approve
              </button>
              <button
                onClick={rejectWithReason}
                disabled={busy}
                className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-status-red/10 hover:text-status-red disabled:opacity-50"
              >
                <XCircle size={12} /> Reject
              </button>
            </>
          )}
          {canWrite && !frozen && po.status === "pending_approval" && (
            <button
              onClick={() => {
                if (window.confirm(`Cancel PO ${po.po_number}?`)) onTransition("cancel");
              }}
              disabled={busy}
              className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-status-red/10 hover:text-status-red disabled:opacity-50"
            >
              <XCircle size={12} /> Cancel
            </button>
          )}
          {canWrite && !frozen && po.status === "rejected" && (
            <>
              <button
                onClick={() => onTransition("revise")}
                disabled={busy}
                className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper disabled:opacity-50"
              >
                <Undo2 size={12} /> Revise
              </button>
              <button
                onClick={() => onTransition("resubmit")}
                disabled={busy}
                className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper disabled:opacity-50"
              >
                <Send size={12} /> Resubmit
              </button>
            </>
          )}
          {canApprove && !frozen && po.status === "approved" && (
            <button
              onClick={() => {
                if (window.confirm(`Cancel approved PO ${po.po_number}?`)) onTransition("cancel");
              }}
              disabled={busy}
              className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-status-red/10 hover:text-status-red disabled:opacity-50"
            >
              <XCircle size={12} /> Cancel
            </button>
          )}
        </div>
      </div>

      {po.lines.length > 0 && (
        <div className="mt-3 overflow-x-auto rounded-md border border-ink-border">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-ink-border text-[10px] uppercase tracking-widest text-paper-faint">
                <th className="px-3 py-1.5 font-medium">Description</th>
                <th className="px-3 py-1.5 font-medium">Qty</th>
                <th className="px-3 py-1.5 font-medium">Unit</th>
                <th className="px-3 py-1.5 font-medium">Unit price</th>
                <th className="px-3 py-1.5 font-medium">Cost code</th>
                <th className="px-3 py-1.5 text-right font-medium">Total</th>
                {editable && <th className="px-3 py-1.5" />}
              </tr>
            </thead>
            <tbody>
              {po.lines.map((line) =>
                editingLineId === line.id ? (
                  <tr key={line.id} className="border-b border-ink-border last:border-0">
                    <td className="px-3 py-1.5" colSpan={6}>
                      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-6">
                        <input
                          className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper sm:col-span-2"
                          value={editForm.description}
                          onChange={(e) =>
                            setEditForm({ ...editForm, description: e.target.value })
                          }
                        />
                        <input
                          type="number"
                          min={0.01}
                          step="any"
                          className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                          value={editForm.quantity}
                          onChange={(e) =>
                            setEditForm({ ...editForm, quantity: Number(e.target.value) })
                          }
                        />
                        <input
                          className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                          value={editForm.unit}
                          onChange={(e) => setEditForm({ ...editForm, unit: e.target.value })}
                        />
                        <input
                          type="number"
                          min={0}
                          step="any"
                          className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                          value={editForm.unit_price}
                          onChange={(e) =>
                            setEditForm({ ...editForm, unit_price: Number(e.target.value) })
                          }
                        />
                        <div className="flex items-center gap-1.5">
                          <select
                            value={editForm.cost_code}
                            onChange={(e) =>
                              setEditForm({
                                ...editForm,
                                cost_code: e.target.value as CostCode,
                              })
                            }
                            className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                          >
                            {COST_CODES.map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </select>
                          <button
                            onClick={() => {
                              if (!editForm.description.trim()) return;
                              onEditLine(line.id, editForm);
                              setEditingLineId(null);
                            }}
                            className="rounded bg-blueprint-400/15 px-2 py-1 text-xs text-blueprint-400 hover:bg-blueprint-400/25"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setEditingLineId(null)}
                            className="rounded px-2 py-1 text-xs text-paper-muted hover:text-paper"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                ) : (
                  <tr key={line.id} className="border-b border-ink-border last:border-0">
                    <td className="px-3 py-1.5 text-paper">{line.description}</td>
                    <td className="px-3 py-1.5 text-paper-muted">{line.quantity}</td>
                    <td className="px-3 py-1.5 text-paper-muted">{line.unit}</td>
                    <td className="px-3 py-1.5 text-paper-muted">
                      {formatCurrency(line.unit_price)}
                    </td>
                    <td className="px-3 py-1.5 text-paper-muted">{line.cost_code}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-paper">
                      {formatCurrency(line.line_total)}
                    </td>
                    {editable && (
                      <td className="px-3 py-1.5 text-right">
                        <button
                          onClick={() => startEdit(line)}
                          className="mr-1.5 rounded border border-ink-border px-1.5 py-0.5 text-paper-muted hover:text-paper"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => {
                            if (window.confirm("Remove this line?")) onDeleteLine(line.id);
                          }}
                          className="rounded border border-ink-border px-1.5 py-0.5 text-paper-muted hover:bg-status-red/10 hover:text-status-red"
                        >
                          <Trash2 size={11} />
                        </button>
                      </td>
                    )}
                  </tr>
                )
              )}
            </tbody>
          </table>
        </div>
      )}

      {editable && (
        <div className="mt-2">
          {showAddLine ? (
            <div className="grid grid-cols-1 gap-1.5 rounded-md border border-dashed border-ink-border p-2 sm:grid-cols-6">
              <input
                className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper sm:col-span-2"
                placeholder="Description"
                value={newLine.description}
                onChange={(e) => setNewLine({ ...newLine, description: e.target.value })}
              />
              <input
                type="number"
                min={0.01}
                step="any"
                className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                placeholder="Qty"
                value={newLine.quantity}
                onChange={(e) => setNewLine({ ...newLine, quantity: Number(e.target.value) })}
              />
              <input
                className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                placeholder="Unit"
                value={newLine.unit}
                onChange={(e) => setNewLine({ ...newLine, unit: e.target.value })}
              />
              <input
                type="number"
                min={0}
                step="any"
                className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                placeholder="Unit price"
                value={newLine.unit_price}
                onChange={(e) => setNewLine({ ...newLine, unit_price: Number(e.target.value) })}
              />
              <select
                value={newLine.cost_code}
                onChange={(e) => setNewLine({ ...newLine, cost_code: e.target.value as CostCode })}
                className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
              >
                {COST_CODES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-1.5 sm:col-span-6">
                <button
                  onClick={() => {
                    if (!newLine.description.trim()) return;
                    onAddLine(newLine);
                    setNewLine(EMPTY_LINE);
                  }}
                  className="flex items-center gap-1 rounded bg-blueprint-400/15 px-2 py-1 text-xs text-blueprint-400 hover:bg-blueprint-400/25"
                >
                  <Plus size={12} /> Add line
                </button>
                <button
                  onClick={() => setShowAddLine(false)}
                  className="rounded px-2 py-1 text-xs text-paper-muted hover:text-paper"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowAddLine(true)}
              className="flex items-center gap-1 rounded border border-dashed border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
            >
              <Plus size={12} /> Add line
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function CreatePoForm({
  vendors,
  onClose,
  onSubmit,
  pending,
}: {
  vendors: { id: string; name: string }[];
  onClose: () => void;
  onSubmit: (payload: PurchaseOrderCreateInput) => void;
  pending: boolean;
}) {
  const [formError, setFormError] = useState("");
  const [vendorId, setVendorId] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const [expectedDelivery, setExpectedDelivery] = useState("");
  const [taxRate, setTaxRate] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<POLineCreateInput[]>([EMPTY_LINE]);

  const updateLine = (index: number, patch: Partial<POLineCreateInput>) => {
    setLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  };

  const submit = () => {
    setFormError("");
    if (!vendorId) {
      setFormError("Select a vendor.");
      return;
    }
    const validLines = lines.filter((l) => l.description.trim() && l.quantity > 0);
    if (validLines.length === 0) {
      setFormError("Add at least one line with a description.");
      return;
    }
    onSubmit({
      vendor_id: vendorId,
      order_date: orderDate || null,
      expected_delivery: expectedDelivery || null,
      tax_rate: taxRate === "" ? null : Number(taxRate),
      notes: notes || null,
      lines: validLines,
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-16"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-md border border-ink-border bg-ink-surface p-5 shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <p className="font-mono text-xs tracking-widest text-blueprint-400">
            CREATE PURCHASE ORDER
          </p>
          <button
            onClick={onClose}
            className="rounded p-1 text-paper-muted hover:text-paper"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs text-paper-muted">
              Vendor
              <select
                value={vendorId}
                onChange={(e) => setVendorId(e.target.value)}
                className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
              >
                <option value="">Select vendor…</option>
                {vendors.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-paper-muted">
              Order date
              <input
                type="date"
                value={orderDate}
                onChange={(e) => setOrderDate(e.target.value)}
                className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
              />
            </label>
            <label className="block text-xs text-paper-muted">
              Expected delivery
              <input
                type="date"
                value={expectedDelivery}
                onChange={(e) => setExpectedDelivery(e.target.value)}
                className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
              />
            </label>
            <label className="block text-xs text-paper-muted">
              Tax rate % (0–100)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={taxRate}
                onChange={(e) => setTaxRate(e.target.value)}
                className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
              />
            </label>
          </div>
          <label className="block text-xs text-paper-muted">
            Notes
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
            />
          </label>

          <div>
            <p className="mb-1 font-mono text-xs tracking-widest text-blueprint-400">
              LINES
            </p>
            <div className="space-y-2">
              {lines.map((line, index) => (
                <div
                  key={index}
                  className="grid grid-cols-1 gap-1.5 rounded-md border border-dashed border-ink-border p-2 sm:grid-cols-6"
                >
                  <input
                    className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper sm:col-span-2"
                    placeholder="Description"
                    value={line.description}
                    onChange={(e) => updateLine(index, { description: e.target.value })}
                  />
                  <input
                    type="number"
                    min={0.01}
                    step="any"
                    className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                    placeholder="Qty"
                    value={line.quantity}
                    onChange={(e) => updateLine(index, { quantity: Number(e.target.value) })}
                  />
                  <input
                    className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                    placeholder="Unit"
                    value={line.unit}
                    onChange={(e) => updateLine(index, { unit: e.target.value })}
                  />
                  <input
                    type="number"
                    min={0}
                    step="any"
                    className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                    placeholder="Unit price"
                    value={line.unit_price}
                    onChange={(e) => updateLine(index, { unit_price: Number(e.target.value) })}
                  />
                  <select
                    value={line.cost_code}
                    onChange={(e) =>
                      updateLine(index, { cost_code: e.target.value as CostCode })
                    }
                    className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                  >
                    {COST_CODES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  {lines.length > 1 && (
                    <button
                      onClick={() => setLines(lines.filter((_, i) => i !== index))}
                      className="rounded px-2 py-1 text-xs text-paper-muted hover:text-status-red"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button
              onClick={() => setLines([...lines, EMPTY_LINE])}
              className="mt-2 flex items-center gap-1 rounded border border-dashed border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
            >
              <Plus size={12} /> Add line
            </button>
          </div>

          {formError && <p className="text-xs text-status-red">{formError}</p>}

          <button
            onClick={submit}
            disabled={pending}
            className="w-full rounded bg-blueprint-500 px-3 py-2 text-sm font-medium text-white hover:bg-blueprint-400 disabled:opacity-50"
          >
            {pending ? "Creating…" : "Create purchase order"}
          </button>
        </div>
      </div>
    </div>
  );
}
