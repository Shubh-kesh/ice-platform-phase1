import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  PackageCheck,
  Plus,
  Send,
  Trash2,
  Undo2,
  X,
  XCircle,
} from "lucide-react";
import {
  addPoLine,
  api,
  createPurchaseOrder,
  deletePoLine,
  getDelivery,
  listDeliveries,
  listPurchaseOrders,
  listVendors,
  receivePurchaseOrder,
  rejectPurchaseOrder,
  transitionPurchaseOrder,
  updatePoLine,
} from "../lib/api";
import type {
  CostCode,
  Delivery,
  DeliveryCreateInput,
  DeliveryLineCreateInput,
  InventoryItem,
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

function formatDateTime(value: string) {
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortId(value: string | null | undefined): string {
  return value ? value.slice(0, 8) : "—";
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
    partially_received: "border-status-amber/60 bg-status-amber/20 text-status-amber",
    received: "border-status-green/60 bg-status-green/20 text-status-green",
    rejected: "border-status-red/40 bg-status-red/10 text-status-red",
    cancelled: "border-ink-border bg-ink text-paper-faint line-through",
  };
  const labels: Record<PurchaseOrderStatus, string> = {
    draft: "Draft",
    pending_approval: "Pending approval",
    approved: "Approved",
    partially_received: "Partially received",
    received: "Received",
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
  const [receiveFor, setReceiveFor] = useState<PurchaseOrder | null>(null);
  const [error, setError] = useState("");

  const { data: vendors } = useQuery({
    queryKey: ["vendors"],
    queryFn: listVendors,
  });

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ["purchase-orders", projectId],
    queryFn: () => listPurchaseOrders(projectId),
  });

  // Inventory items for the receive form's per-line item picker (fetched lazily,
  // only once a receive form is opened).
  const { data: inventoryItems = [] } = useQuery({
    queryKey: ["inventory", projectId],
    queryFn: async () => {
      const { data } = await api.get<InventoryItem[]>(`/projects/${projectId}/inventory`);
      return data;
    },
    enabled: receiveFor !== null,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["purchase-orders", projectId] });
  };

  const report = (err: unknown, fallback: string) =>
    setError(getErrorMessage(err) ?? fallback);

  const receiveMutation = useMutation({
    mutationFn: ({
      poId,
      payload,
      idempotencyKey,
    }: {
      poId: string;
      payload: DeliveryCreateInput;
      idempotencyKey: string;
    }) => receivePurchaseOrder(projectId, poId, payload, idempotencyKey),
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ["deliveries", projectId] });
      queryClient.invalidateQueries({ queryKey: ["inventory", projectId] });
      queryClient.invalidateQueries({ queryKey: ["job-costs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["budget", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project-health", projectId] });
      setReceiveFor(null);
      setError("");
    },
    onError: (err: unknown) => report(err, "Could not receive the purchase order."),
  });

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
              onReceive={(receivePo) => setReceiveFor(receivePo)}
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

      {receiveFor && (
        <ReceiveForm
          po={receiveFor}
          items={inventoryItems}
          onClose={() => setReceiveFor(null)}
          onSubmit={(payload, idempotencyKey) =>
            receiveMutation.mutate({ poId: receiveFor.id, payload, idempotencyKey })
          }
          pending={receiveMutation.isPending}
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
  onReceive,
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
  onReceive: (po: PurchaseOrder) => void;
  onAddLine: (line: POLineCreateInput) => void;
  onEditLine: (lineId: string, input: Partial<POLineCreateInput>) => void;
  onDeleteLine: (lineId: string) => void;
  busy: boolean;
}) {
  const [showAddLine, setShowAddLine] = useState(false);
  const [editingLineId, setEditingLineId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<POLineCreateInput>(EMPTY_LINE);
  const [newLine, setNewLine] = useState<POLineCreateInput>(EMPTY_LINE);
  const [showDeliveries, setShowDeliveries] = useState(false);

  const badge = poStatusBadge(po.status);
  const isDraft = po.status === "draft";
  const editable = canWrite && !frozen && isDraft;
  const receivable = canWrite && !frozen && (po.status === "approved" || po.status === "partially_received");

  const { data: deliveries = [], isLoading: deliveriesLoading } = useQuery({
    queryKey: ["deliveries", po.project_id, po.id],
    queryFn: () => listDeliveries(po.project_id, po.id),
    enabled: showDeliveries,
  });

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
          {receivable && (
            <button
              onClick={() => onReceive(po)}
              className="flex items-center gap-1 rounded bg-blueprint-400/15 px-2 py-1 text-xs text-blueprint-400 hover:bg-blueprint-400/25"
            >
              <PackageCheck size={12} /> Receive
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
                <th className="px-3 py-1.5 font-medium">Received</th>
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
                    <td className="px-3 py-1.5" colSpan={7}>
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
                    <td className="px-3 py-1.5">
                      <span className="text-paper">{line.received_quantity}</span>
                      {line.received_remaining > 0 && (
                        <span className="ml-1.5 text-[10px] text-paper-faint">
                          {line.received_remaining} remaining
                        </span>
                      )}
                    </td>
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

      <div className="mt-3">
        <button
          onClick={() => setShowDeliveries((v) => !v)}
          className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-blueprint-400 hover:text-blueprint-300"
        >
          {showDeliveries ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Deliveries
        </button>
        {showDeliveries && (
          <div className="mt-2 overflow-hidden rounded-md border border-ink-border">
            {deliveriesLoading && (
              <div className="flex items-center gap-2 px-3 py-4 text-xs text-paper-muted">
                <Loader2 size={12} className="animate-spin" /> Loading receipts…
              </div>
            )}
            {!deliveriesLoading && deliveries.length === 0 && (
              <p className="px-3 py-4 text-xs text-paper-muted">
                No receipts yet for this purchase order.
              </p>
            )}
            {!deliveriesLoading &&
              deliveries.map((delivery) => (
                <DeliveryRow
                  key={delivery.id}
                  projectId={po.project_id}
                  poId={po.id}
                  delivery={delivery}
                />
              ))}
          </div>
        )}
      </div>
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

function DeliveryRow({
  projectId,
  poId,
  delivery,
}: {
  projectId: string;
  poId: string;
  delivery: Delivery;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: detail, isLoading } = useQuery({
    queryKey: ["deliveries", projectId, poId, "detail", delivery.id],
    queryFn: () => getDelivery(projectId, poId, delivery.id),
    enabled: expanded,
  });

  return (
    <div className="border-b border-ink-border last:border-0">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-ink-raised"
      >
        <span className="flex items-center gap-1.5 font-mono text-xs text-paper">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {delivery.reference}
        </span>
        <span className="shrink-0 text-[10px] text-paper-faint">
          {formatDateTime(delivery.verified_at)} · by {shortId(delivery.verified_by)} ·{" "}
          {delivery.line_count} line(s)
        </span>
      </button>
      {expanded && (
        <div className="border-t border-ink-border px-3 py-2">
          {isLoading && (
            <div className="flex items-center gap-2 text-xs text-paper-muted">
              <Loader2 size={12} className="animate-spin" /> Loading…
            </div>
          )}
          {detail && (
            <div className="space-y-1">
              {detail.note && <p className="text-xs text-paper-muted">Note: {detail.note}</p>}
              {detail.photo_reference && (
                <p className="break-all text-xs text-paper-muted">
                  Photo ref: {detail.photo_reference}
                </p>
              )}
              {(detail.lines ?? []).map((line) => (
                <div
                  key={line.id}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span className="text-paper">
                    {line.description ?? "—"}
                    <span className="ml-1.5 text-paper-faint">
                      {line.quantity_received} {line.unit ?? ""}
                    </span>
                  </span>
                  <span className="font-mono text-paper">{formatCurrency(line.line_total)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReceiveForm({
  po,
  items,
  onClose,
  onSubmit,
  pending,
}: {
  po: PurchaseOrder;
  items: InventoryItem[];
  onClose: () => void;
  onSubmit: (payload: DeliveryCreateInput, idempotencyKey: string) => void;
  pending: boolean;
}) {
  const [formError, setFormError] = useState("");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [photoReference, setPhotoReference] = useState("");

  // One Idempotency-Key per logical receive operation: minted when this form
  // mounts and REUSED across retries of the same submission (a failed attempt
  // keeps the form open, so the retry replays the stored receipt instead of
  // double-receiving). A newly opened form is a new operation -> a new key.
  const idempotencyKey = useRef<string | null>(null);
  if (idempotencyKey.current === null) {
    idempotencyKey.current = crypto.randomUUID();
  }

  const receivableLines = po.lines.filter((line) => line.received_remaining > 0);
  const [rows, setRows] = useState<DeliveryLineCreateInput[]>(() =>
    receivableLines.map((line) => ({
      po_line_id: line.id,
      quantity: line.received_remaining,
      inventory_item_id: line.inventory_item_id ?? "",
    }))
  );

  const updateRow = (index: number, patch: Partial<DeliveryLineCreateInput>) => {
    setRows(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const submit = () => {
    setFormError("");
    if (!reference.trim()) {
      setFormError("Enter a delivery/packing-slip reference (required).");
      return;
    }
    const valid = rows.filter((row) => row.quantity > 0 && row.inventory_item_id);
    if (valid.length === 0) {
      setFormError("Choose at least one line with a quantity and an inventory item.");
      return;
    }
    for (const row of valid) {
      const line = po.lines.find((l) => l.id === row.po_line_id);
      if (!line) continue;
      if (row.quantity > line.received_remaining) {
        setFormError(
          `Quantity for '${line.description}' exceeds the remaining ${line.received_remaining} ${line.unit}.`
        );
        return;
      }
    }
    onSubmit(
      {
        reference: reference.trim(),
        note: note || null,
        photo_reference: photoReference || null,
        lines: valid,
      },
      idempotencyKey.current!
    );
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
            RECEIVE — {po.po_number}
          </p>
          <button
            onClick={onClose}
            className="rounded p-1 text-paper-muted hover:text-paper"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3">
          <label className="block text-xs text-paper-muted">
            Delivery / packing-slip reference
            <input
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="e.g. DN-1042"
              className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
            />
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs text-paper-muted">
              Verification note (optional)
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
              />
            </label>
            <label className="block text-xs text-paper-muted">
              Photo reference (optional)
              <input
                value={photoReference}
                onChange={(e) => setPhotoReference(e.target.value)}
                placeholder="External URL or id"
                className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
              />
            </label>
          </div>

          <div>
            <p className="mb-1 font-mono text-xs tracking-widest text-blueprint-400">
              LINES TO RECEIVE
            </p>
            <div className="space-y-2">
              {receivableLines.length === 0 && (
                <p className="text-xs text-paper-muted">
                  All lines on this purchase order are fully received.
                </p>
              )}
              {receivableLines.map((line, index) => {
                const matchingItems = items.filter((item) => item.unit === line.unit);
                return (
                  <div
                    key={line.id}
                    className="grid grid-cols-1 gap-1.5 rounded-md border border-dashed border-ink-border p-2 sm:grid-cols-3"
                  >
                    <div className="sm:col-span-1">
                      <p className="text-xs text-paper">{line.description}</p>
                      <p className="text-[10px] text-paper-faint">
                        {line.received_remaining} of {line.quantity} {line.unit} remaining
                      </p>
                    </div>
                    <input
                      type="number"
                      min={0.01}
                      step="any"
                      className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                      placeholder="Qty"
                      value={rows[index]?.quantity}
                      onChange={(e) => updateRow(index, { quantity: Number(e.target.value) })}
                    />
                    <select
                      value={rows[index]?.inventory_item_id ?? ""}
                      onChange={(e) => updateRow(index, { inventory_item_id: e.target.value })}
                      className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper"
                    >
                      <option value="">Select item…</option>
                      {matchingItems.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name} ({item.unit})
                        </option>
                      ))}
                    </select>
                    {matchingItems.length === 0 && (
                      <p className="text-[10px] text-status-amber sm:col-span-3">
                        No inventory item with unit "{line.unit}" exists. Add one in the
                        Inventory panel first.
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {formError && <p className="text-xs text-status-red">{formError}</p>}

          <button
            onClick={submit}
            disabled={pending}
            className="w-full rounded bg-blueprint-500 px-3 py-2 text-sm font-medium text-white hover:bg-blueprint-400 disabled:opacity-50"
          >
            {pending ? "Receiving…" : "Verify & receive"}
          </button>
        </div>
      </div>
    </div>
  );
}
