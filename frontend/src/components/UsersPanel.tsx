import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Link2,
  Loader2,
  Power,
  Plus,
  X,
} from "lucide-react";
import {
  createUser,
  listUsers,
  updateUser,
} from "../lib/api";
import type { User, UserCreateInput, UserRole } from "../types";

const ROLE_LABEL: Record<UserRole, string> = {
  admin: "Admin",
  site_supervisor: "Site Supervisor",
  procurement_manager: "Procurement Manager",
  client: "Client",
};

const ROLES: UserRole[] = ["admin", "site_supervisor", "procurement_manager", "client"];

function roleLabel(role: UserRole): string {
  return ROLE_LABEL[role];
}

function getErrorMessage(err: unknown): string {
  if (typeof err === "object" && err && "response" in err) {
    return (
      (err as { response?: { data?: { detail?: string } } }).response?.data
        ?.detail ?? "Something went wrong. Check the API is running."
    );
  }
  return "Something went wrong. Check the API is running.";
}

function AccountBadge({ user }: { user: User }) {
  // Derived status mirrors the backend: admin-created invites have no password
  // and no Google identity yet ("pending"); a bound google_sub means linked.
  let label = "Password";
  if (user.google_linked && user.has_password) label = "Google + password";
  else if (user.google_linked) label = "Google linked";
  else if (!user.has_password) label = "Pending Google link";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
        label === "Pending Google link"
          ? "border-status-amber/40 bg-status-amber/10 text-status-amber"
          : "border-blueprint-400/30 bg-blueprint-400/10 text-blueprint-400"
      }`}
    >
      {user.google_linked && <Link2 size={10} />}
      {label}
    </span>
  );
}

const EMPTY_FORM: UserCreateInput = {
  email: "",
  full_name: "",
  phone: "",
  role: "site_supervisor",
  google_only: false,
  password: "",
};

export function UsersPanel() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<UserCreateInput>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [rowError, setRowError] = useState("");

  const { data: users, isLoading, isError, refetch } = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["users"] });
  };

  const createMutation = useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      invalidate();
      setForm(EMPTY_FORM);
      setShowForm(false);
      setFormError("");
    },
    onError: (err: unknown) => setFormError(getErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ userId, input }: { userId: string; input: Parameters<typeof updateUser>[1] }) =>
      updateUser(userId, input),
    onSuccess: () => {
      invalidate();
      setRowError("");
    },
    onError: (err: unknown) => setRowError(getErrorMessage(err)),
  });

  const submitCreate = (e: FormEvent) => {
    e.preventDefault();
    setFormError("");
    if (!form.email.trim() || !form.full_name.trim()) {
      setFormError("Email and full name are required.");
      return;
    }
    if (!form.google_only && !form.password) {
      setFormError("A password is required unless this is a Google-only invite.");
      return;
    }
    createMutation.mutate({
      ...form,
      password: form.google_only ? null : form.password,
    });
  };

  return (
    <section className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">
          TEAM / USERS
        </p>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 rounded bg-blueprint-400/15 px-2.5 py-1.5 text-xs text-blueprint-400 hover:bg-blueprint-400/25"
        >
          <Plus size={13} />
          Add user
        </button>
      </div>

      {rowError && (
        <p className="mb-3 inline-flex items-center gap-1.5 rounded border border-status-red/30 bg-status-red/10 px-2 py-1.5 text-xs text-status-red">
          <AlertTriangle size={12} /> {rowError}
        </p>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading team…
        </div>
      )}

      {isError && (
        <div className="flex items-start gap-3 rounded-md border border-status-red/30 bg-status-red/10 p-3 text-sm text-status-red">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">Couldn't load users.</p>
            <button
              onClick={() => refetch()}
              className="mt-2 rounded border border-status-red/40 px-2.5 py-1 text-xs hover:bg-status-red/10"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {users && users.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-ink-border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-ink-border text-[10px] uppercase tracking-widest text-paper-faint">
                <th className="px-3 py-2 font-medium">User</th>
                <th className="px-3 py-2 font-medium">Role</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 text-right font-medium">Active</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-b border-ink-border last:border-0">
                  <td className="px-3 py-2">
                    <p className="text-paper">{user.full_name}</p>
                    <p className="text-xs text-paper-muted">{user.email}</p>
                  </td>
                  <td className="px-3 py-2">
                    <select
                      value={user.role}
                      disabled={updateMutation.isPending}
                      onChange={(e) =>
                        updateMutation.mutate({
                          userId: user.id,
                          input: { role: e.target.value as UserRole },
                        })
                      }
                      className="rounded border border-ink-border bg-ink px-2 py-1 text-xs text-paper focus:border-blueprint-400 focus:outline-none disabled:opacity-50"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {roleLabel(r)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <AccountBadge user={user} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() =>
                        updateMutation.mutate({
                          userId: user.id,
                          input: { is_active: !user.is_active },
                        })
                      }
                      disabled={updateMutation.isPending}
                      className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 text-xs disabled:opacity-50 ${
                        user.is_active
                          ? "border-status-green/40 bg-status-green/10 text-status-green"
                          : "border-status-red/40 bg-status-red/10 text-status-red"
                      }`}
                    >
                      <Power size={12} />
                      {user.is_active ? "Active" : "Deactivated"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {users && users.length === 0 && (
        <p className="py-6 text-center text-sm text-paper-muted">
          No users yet. Add your first teammate.
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
                ADD USER
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
                Full name
                <input
                  value={form.full_name}
                  onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  required
                />
              </label>
              <label className="block text-xs text-paper-muted">
                Email
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  required
                />
              </label>
              <label className="block text-xs text-paper-muted">
                Phone
                <input
                  value={form.phone ?? ""}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                />
              </label>
              <label className="block text-xs text-paper-muted">
                Role
                <select
                  value={form.role}
                  onChange={(e) =>
                    setForm({ ...form, role: e.target.value as UserRole })
                  }
                  className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {roleLabel(r)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2 text-xs text-paper-muted">
                <input
                  type="checkbox"
                  checked={form.google_only ?? false}
                  onChange={(e) =>
                    setForm({ ...form, google_only: e.target.checked })
                  }
                  className="h-4 w-4 accent-blueprint-400"
                />
                Google-only invite — no password; they sign in with their
                Google account.
              </label>

              {!form.google_only && (
                <label className="block text-xs text-paper-muted">
                  Temporary password
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={form.password ?? ""}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    className="mt-1 w-full rounded border border-ink-border bg-ink px-2.5 py-1.5 text-sm text-paper focus:border-blueprint-400 focus:outline-none"
                  />
                </label>
              )}

              {formError && <p className="text-xs text-status-red">{formError}</p>}

              <button
                type="submit"
                disabled={createMutation.isPending}
                className="w-full rounded bg-blueprint-500 px-3 py-2 text-sm font-medium text-white hover:bg-blueprint-400 disabled:opacity-50"
              >
                {createMutation.isPending ? "Creating…" : "Create user"}
              </button>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}