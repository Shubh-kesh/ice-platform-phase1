import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Plus, Power, X } from "lucide-react";
import { createVendor, listVendors, updateVendor } from "../lib/api";
import type { VendorCreateInput } from "../types";

function getErrorMessage(err: unknown): string {
  if (typeof err === "object" && err && "response" in err) {
    return (
      (err as { response?: { data?: { detail?: string } } }).response?.data
        ?.detail ?? "Something went wrong. Check the API is running."
    );
  }
  return "Something went wrong. Check the API is running.";
}

const EMPTY_FORM: VendorCreateInput = {
  name: "",
  contact_name: "",
  email: "",
  phone: "",
  payment_terms: "",
  address: "",
  notes: "",
};

export function VendorsPanel() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<VendorCreateInput>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [rowError, setRowError] = useState("");

  const { data: vendors, isLoading, isError, refetch } = useQuery({
    queryKey: ["vendors"],
    queryFn: listVendors,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["vendors"] });
  };

  const createMutation = useMutation({
    mutationFn: createVendor,
    onSuccess: () => {
      invalidate();
      setForm(EMPTY_FORM);
      setShowForm(false);
      setFormError("");
    },
    onError: (err: unknown) => setFormError(getErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      vendorId,
      input,
    }: {
      vendorId: string;
      input: Parameters<typeof updateVendor>[1];
    }) => updateVendor(vendorId, input),
    onSuccess: () => {
      invalidate();
      setRowError("");
    },
    onError: (err: unknown) => setRowError(getErrorMessage(err)),
  });

  const submitCreate = (e: FormEvent) => {
    e.preventDefault();
    setFormError("");
    if (!form.name.trim()) {
      setFormError("Vendor name is required.");
      return;
    }
    createMutation.mutate({
      ...form,
      contact_name: form.contact_name || null,
      email: form.email || null,
      phone: form.phone || null,
      payment_terms: form.payment_terms || null,
      address: form.address || null,
      notes: form.notes || null,
    });
  };

  return (
    <section className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">
          VENDORS
        </p>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 rounded bg-blueprint-400/15 px-2.5 py-1.5 text-xs text-blueprint-400 hover:bg-blueprint-400/25"
        >
          <Plus size={13} />
          Add vendor
        </button>
      </div>

      {rowError && (
        <p className="mb-3 inline-flex items-center gap-1.5 rounded border border-status-red/30 bg-status-red/10 px-2 py-1.5 text-xs text-status-red">
          <AlertTriangle size={12} /> {rowError}
        </p>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading vendors…
        </div>
      )}

      {isError && (
        <div className="flex items-start gap-3 rounded-md border border-status-red/30 bg-status-red/10 p-3 text-sm text-status-red">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">Couldn't load vendors.</p>
            <button
              onClick={() => refetch()}
              className="mt-2 rounded border border-status-red/40 px-2.5 py-1 text-xs hover:bg-status-red/10"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {vendors && vendors.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-ink-border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-ink-border text-[10px] uppercase tracking-widest text-paper-faint">
                <th className="px-3 py-2 font-medium">Vendor</th>
                <th className="px-3 py-2 font-medium">Contact</th>
                <th className="px-3 py-2 font-medium">Terms</th>
                <th className="px-3 py-2 text-right font-medium">Active</th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((vendor) => (
                <tr key={vendor.id} className="border-b border-ink-border last:border-0">
                  <td className="px-3 py-2">
                    <p className="text-paper">{vendor.name}</p>
                    <p className="text-xs text-paper-muted">
                      {vendor.email ?? "—"}
                    </p>
                  </td>
                  <td className="px-3 py-2 text-paper-muted">
                    {vendor.contact_name ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-paper-muted">
                    {vendor.payment_terms ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() =>
                        updateMutation.mutate({
                          vendorId: vendor.id,
                          input: { is_active: !vendor.is_active },
                        })
                      }
                      disabled={updateMutation.isPending}
                      className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 text-xs disabled:opacity-50 ${
                        vendor.is_active
                          ? "border-status-green/40 bg-status-green/10 text-status-green"
                          : "border-status-red/40 bg-status-red/10 text-status-red"
                      }`}
                    >
                      <Power size={12} />
                      {vendor.is_active ? "Active" : "Deactivated"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {vendors && vendors.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">
          No vendors yet. Add your first vendor to create purchase orders.
        </p>
      )}

      {showForm && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-16"
          onClick={() => setShowForm(false)}
        >
          <div
            className="w-full max-w-md rounded-md border border-ink-border bg-ink-surface p-5 shadow-panel"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <p className="font-mono text-xs tracking-widest text-blueprint-400">
                ADD VENDOR
              </p>
              <button
                onClick={() => setShowForm(false)}
                className="rounded p-1 text-paper-muted hover:text-paper"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={submitCreate} className="space-y-3">
              <label className="block text-xs text-paper-muted">
                Vendor name
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  required
                />
              </label>
              <label className="block text-xs text-paper-muted">
                Contact name
                <input
                  value={form.contact_name ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, contact_name: e.target.value })
                  }
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                />
              </label>
              <label className="block text-xs text-paper-muted">
                Email
                <input
                  type="email"
                  value={form.email ?? ""}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-xs text-paper-muted">
                  Phone
                  <input
                    value={form.phone ?? ""}
                    onChange={(e) => setForm({ ...form, phone: e.target.value })}
                    className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  />
                </label>
                <label className="block text-xs text-paper-muted">
                  Payment terms
                  <input
                    value={form.payment_terms ?? ""}
                    onChange={(e) =>
                      setForm({ ...form, payment_terms: e.target.value })
                    }
                    className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                    placeholder="e.g. NET 30"
                  />
                </label>
              </div>
              <label className="block text-xs text-paper-muted">
                Address
                <input
                  value={form.address ?? ""}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                />
              </label>
              <label className="block text-xs text-paper-muted">
                Notes
                <input
                  value={form.notes ?? ""}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                />
              </label>

              {formError && <p className="text-xs text-status-red">{formError}</p>}

              <button
                type="submit"
                disabled={createMutation.isPending}
                className="w-full rounded bg-blueprint-500 px-3 py-2 text-sm font-medium text-white hover:bg-blueprint-400 disabled:opacity-50"
              >
                {createMutation.isPending ? "Creating…" : "Create vendor"}
              </button>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
