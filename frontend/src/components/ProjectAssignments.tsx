import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Loader2, UserMinus, UserCheck, AlertTriangle } from "lucide-react";
import { api } from "../lib/api";
import type { AssignmentCreateInput, User, UserRole } from "../types";

const ROLE_LABEL: Record<UserRole, string> = {
  admin: "Admin",
  site_supervisor: "Site Supervisor",
  procurement_manager: "Procurement Manager",
  client: "Client",
};

// Mirrors backend: only supervisors and clients get per-project assignments —
// admin and procurement already see every project by role.
const ASSIGNABLE_ROLES: UserRole[] = ["site_supervisor", "client"];

function getErrorMessage(err: unknown) {
  if (typeof err === "object" && err && "response" in err) {
    return (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
  }
  return undefined;
}

export function ProjectAssignments({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [selectedUserId, setSelectedUserId] = useState("");
  const [error, setError] = useState("");

  const { data: assigned, isLoading: loadingAssigned } = useQuery({
    queryKey: ["assignments", projectId],
    queryFn: async () => {
      const { data } = await api.get<User[]>(`/projects/${projectId}/assignments`);
      return data;
    },
  });

  const { data: users } = useQuery({
    queryKey: ["users"],
    queryFn: async () => {
      const { data } = await api.get<User[]>("/users");
      return data;
    },
  });

  const assignUser = useMutation({
    mutationFn: async (payload: AssignmentCreateInput) => {
      await api.post(`/projects/${projectId}/assignments`, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments", projectId] });
      setSelectedUserId("");
      setError("");
    },
    onError: (err: unknown) => {
      setError(getErrorMessage(err) ?? "Could not assign user.");
    },
  });

  const unassignUser = useMutation({
    mutationFn: async (userId: string) => {
      await api.delete(`/projects/${projectId}/assignments/${userId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments", projectId] });
      setError("");
    },
    onError: (err: unknown) => {
      setError(getErrorMessage(err) ?? "Could not remove user.");
    },
  });

  const assignableUsers = useMemo(() => {
    if (!users || !assigned) return [];
    const assignedIds = new Set(assigned.map((u) => u.id));
    return users.filter(
      (u) => ASSIGNABLE_ROLES.includes(u.role) && !assignedIds.has(u.id) && u.is_active
    );
  }, [users, assigned]);

  return (
    <div className="rounded-md border border-ink-border bg-ink-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-mono text-xs tracking-widest text-blueprint-400">ASSIGNED TEAM</p>
      </div>

      {error && (
        <p className="mb-3 inline-flex items-center gap-1.5 rounded border border-status-red/30 bg-status-red/10 px-2 py-1.5 text-xs text-status-red">
          <AlertTriangle size={12} /> {error}
        </p>
      )}

      {loadingAssigned && (
        <div className="flex items-center gap-2 py-4 text-sm text-paper-muted">
          <Loader2 size={14} className="animate-spin" /> Loading team…
        </div>
      )}

      {assigned && assigned.length === 0 && (
        <p className="py-4 text-center text-sm text-paper-muted">
          No supervisors or clients assigned yet.
        </p>
      )}

      {assigned && assigned.length > 0 && (
        <ul className="mb-4 divide-y divide-ink-border rounded-md border border-ink-border">
          {assigned.map((user) => (
            <li key={user.id} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <UserCheck size={15} className="shrink-0 text-blueprint-400" />
                <div className="min-w-0">
                  <p className="truncate text-sm text-paper">{user.full_name}</p>
                  <p className="truncate text-xs text-paper-muted">
                    {user.email} · {ROLE_LABEL[user.role]}
                  </p>
                </div>
              </div>
              <button
                onClick={() => unassignUser.mutate(user.id)}
                disabled={unassignUser.isPending}
                className="flex shrink-0 items-center gap-1 rounded border border-ink-border px-2 py-1 text-xs text-paper-muted hover:bg-ink-raised hover:text-status-red disabled:opacity-50"
              >
                <UserMinus size={13} /> Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!selectedUserId) return;
          assignUser.mutate({ user_id: selectedUserId });
        }}
        className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto]"
      >
        <select
          value={selectedUserId}
          onChange={(e) => setSelectedUserId(e.target.value)}
          className="rounded border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper"
        >
          <option value="">Assign a supervisor or client…</option>
          {assignableUsers.map((user) => (
            <option key={user.id} value={user.id}>
              {user.full_name} ({user.email}) — {ROLE_LABEL[user.role]}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={!selectedUserId || assignUser.isPending}
          className="flex items-center justify-center gap-1.5 rounded bg-blueprint-400/15 px-3 py-1.5 text-sm text-blueprint-400 hover:bg-blueprint-400/25 disabled:opacity-50"
        >
          <Plus size={14} />
          {assignUser.isPending ? "Assigning…" : "Assign"}
        </button>
      </form>
      {assignableUsers.length === 0 && users && assigned && (
        <p className="mt-2 text-xs text-paper-muted">
          No other active supervisors/clients to assign.
        </p>
      )}
    </div>
  );
}