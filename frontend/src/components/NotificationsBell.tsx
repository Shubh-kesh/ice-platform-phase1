import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck, Loader2, X } from "lucide-react";
import {
  getUnreadNotificationCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "../lib/api";
import type { AppNotification } from "../types";

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  const minutes = Math.max(1, Math.round((Date.now() - then) / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(iso).toLocaleDateString();
}

/**
 * M13 in-app notification bell for the AppShell header: unread-count badge,
 * a dropdown feed of the current user's notifications, mark-read on open, and
 * a mark-all-read action. User-scoped (the API only ever returns the caller's
 * notifications).
 */
export function NotificationsBell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const { data: unread = 0 } = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: getUnreadNotificationCount,
    refetchInterval: 30_000,
  });

  const { data: notifications = [], isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => listNotifications(),
    enabled: open,
    refetchInterval: open ? 30_000 : false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };

  const markRead = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: invalidate,
  });

  const markAll = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: invalidate,
  });

  function openNotification(n: AppNotification) {
    if (!n.read_at) markRead.mutate(n.id);
    setOpen(false);
    if (n.link) navigate(n.link);
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Notifications"
        className="relative rounded p-1.5 text-paper-muted hover:bg-ink-raised hover:text-paper"
      >
        <Bell size={16} strokeWidth={2} />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-status-red px-1 text-[9px] font-semibold text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-2 w-80 overflow-hidden rounded-md border border-ink-border bg-ink-surface shadow-panel">
            <div className="flex items-center justify-between border-b border-ink-border px-3 py-2">
              <p className="font-mono text-[10px] uppercase tracking-widest text-blueprint-400">
                Notifications
              </p>
              <div className="flex items-center gap-1">
                {unread > 0 && (
                  <button
                    onClick={() => markAll.mutate()}
                    disabled={markAll.isPending}
                    className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-paper-muted hover:bg-ink-raised hover:text-paper disabled:opacity-50"
                    title="Mark all read"
                  >
                    <CheckCheck size={12} /> All
                  </button>
                )}
                <button
                  onClick={() => setOpen(false)}
                  className="rounded p-0.5 text-paper-muted hover:text-paper"
                  aria-label="Close"
                >
                  <X size={13} />
                </button>
              </div>
            </div>

            <div className="max-h-96 overflow-y-auto">
              {isLoading && (
                <div className="flex items-center gap-2 px-3 py-6 text-sm text-paper-muted">
                  <Loader2 size={14} className="animate-spin" /> Loading…
                </div>
              )}
              {!isLoading && notifications.length === 0 && (
                <p className="px-3 py-6 text-center text-sm text-paper-muted">
                  You're all caught up.
                </p>
              )}
              {notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => openNotification(n)}
                  className={`block w-full border-b border-ink-border px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-ink-raised ${
                    n.read_at ? "opacity-60" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-medium text-paper">{n.title}</p>
                    <span className="shrink-0 text-[10px] text-paper-faint">
                      {timeAgo(n.created_at)}
                    </span>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[11px] text-paper-muted">{n.body}</p>
                  {!n.read_at && (
                    <span className="mt-1 inline-block h-1.5 w-1.5 rounded-full bg-blueprint-400" />
                  )}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
