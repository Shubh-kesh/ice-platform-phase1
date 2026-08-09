import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Loader2, AlertTriangle, ArrowDownCircle, ArrowUpCircle } from "lucide-react";
import { api } from "../lib/api";
import type { InventoryItem, InventoryItemCreateInput, MovementType, StockMovementCreateInput } from "../types";

const MOVEMENT_LABEL: Record<MovementType, string> = {
  received: "Received (+)",
  consumed: "Consumed (-)",
  transferred: "Transferred out (-)",
  adjusted: "Adjusted (+)",
};

export function InventoryPanel({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<InventoryItemCreateInput>({ name: "", unit: "", opening_quantity: 0 });
  const [movementItemId, setMovementItemId] = useState<string | null>(null);
  const [movementForm, setMovementForm] = useState<StockMovementCreateInput>({
    movement_type: "received",
    quantity: 0,
    note: "",
  });

  const { data: items, isLoading } = useQuery({
    queryKey: ["inventory", projectId],
    queryFn: async () => {
      const { data } = await api.get<InventoryItem[]>(`/projects/${projectId}/inventory`);
      return data;
    },
  });

  const createItem = useMutation({
    mutationFn: async (payload: InventoryItemCreateInput) => {
      await api.post(`/projects/${projectId}/inventory`, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inventory", projectId] });
      setForm({ name: "", unit: "", opening_quantity: 0 });
      setShowForm(false);
    },
  });

  const recordMovement = useMutation({
    mutationFn: async ({ itemId, payload }: { itemId: string; payload: StockMovementCreateInput }) => {
      await api.post(`/projects/${projectId}/inventory/${itemId}/movements`, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inventory", projectId] });
      setMovementItemId(null);
      setMovementForm({ movement_type: "received", quantity: 0, note: "" });
    },
    onError: (err: unknown) => {
      const detail =
        typeof err === "object" && err && "response" in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      alert(detail ?? "Could not record movement.");
    },
  });

  return (
    <div className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">INVENTORY</p>
        {canWrite && (
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
          >
            <Plus size={13} /> Add item
          </button>
        )}
      </div>

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.name || !form.unit) return;
            createItem.mutate(form);
          }}
          className="mb-4 grid grid-cols-1 gap-2 rounded-md border border-dashed border-ink-border p-3 sm:grid-cols-4"
        >
          <input
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper sm:col-span-2"
            placeholder="Material name (e.g. Cement OPC 53)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            placeholder="Unit (bags, kg, m3…)"
            value={form.unit}
            onChange={(e) => setForm({ ...form, unit: e.target.value })}
          />
          <input
            type="number"
            min={0}
            className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
            placeholder="Opening qty"
            value={form.opening_quantity ?? 0}
            onChange={(e) => setForm({ ...form, opening_quantity: Number(e.target.value) })}
          />
          <button
            type="submit"
            disabled={createItem.isPending}
            className="col-span-full rounded bg-blueprint-400/15 py-1.5 text-sm text-blueprint-400 hover:bg-blueprint-400/25 disabled:opacity-50"
          >
            {createItem.isPending ? "Adding…" : "Add item"}
          </button>
        </form>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading inventory…
        </div>
      )}

      {items && items.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">No materials tracked yet.</p>
      )}

      {items && items.length > 0 && (
        <div className="space-y-2">
          {items.map((item) => {
            const isLow =
              item.reorder_threshold !== null && item.quantity_on_hand <= item.reorder_threshold;
            return (
              <div key={item.id} className="rounded-md border border-ink-border p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-paper">{item.name}</p>
                    <p className="text-xs text-paper-muted">
                      {item.quantity_on_hand} {item.unit} on hand
                      {isLow && (
                        <span className="ml-2 inline-flex items-center gap-1 text-status-amber">
                          <AlertTriangle size={11} /> Low stock
                        </span>
                      )}
                    </p>
                  </div>
                  {canWrite && (
                    <button
                      onClick={() => setMovementItemId(movementItemId === item.id ? null : item.id)}
                      className="rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
                    >
                      Record movement
                    </button>
                  )}
                </div>

                {movementItemId === item.id && (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (movementForm.quantity <= 0) return;
                      recordMovement.mutate({ itemId: item.id, payload: movementForm });
                    }}
                    className="mt-3 grid grid-cols-1 gap-2 rounded-md border border-dashed border-ink-border p-2 sm:grid-cols-4"
                  >
                    <select
                      value={movementForm.movement_type}
                      onChange={(e) =>
                        setMovementForm({ ...movementForm, movement_type: e.target.value as MovementType })
                      }
                      className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
                    >
                      {Object.entries(MOVEMENT_LABEL).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min={0.01}
                      step="0.01"
                      placeholder="Quantity"
                      className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
                      value={movementForm.quantity || ""}
                      onChange={(e) => setMovementForm({ ...movementForm, quantity: Number(e.target.value) })}
                    />
                    <input
                      placeholder="Note (optional)"
                      className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper sm:col-span-2"
                      value={movementForm.note ?? ""}
                      onChange={(e) => setMovementForm({ ...movementForm, note: e.target.value })}
                    />
                    <button
                      type="submit"
                      disabled={recordMovement.isPending}
                      className="col-span-full flex items-center justify-center gap-1.5 rounded bg-blueprint-400/15 py-1.5 text-sm text-blueprint-400 hover:bg-blueprint-400/25 disabled:opacity-50"
                    >
                      {movementForm.movement_type === "consumed" || movementForm.movement_type === "transferred" ? (
                        <ArrowDownCircle size={14} />
                      ) : (
                        <ArrowUpCircle size={14} />
                      )}
                      {recordMovement.isPending ? "Saving…" : "Save movement"}
                    </button>
                  </form>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
