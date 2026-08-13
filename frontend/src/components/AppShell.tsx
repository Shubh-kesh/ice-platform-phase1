import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutGrid,
  Boxes,
  Receipt,
  ShieldCheck,
  LogOut,
  Building2,
} from "lucide-react";
import { useAuth } from "../lib/auth-context";
import { NotificationsBell } from "./NotificationsBell";
import type { UserRole } from "../types";

const ROLE_LABEL: Record<UserRole, string> = {
  admin: "Admin",
  site_supervisor: "Site Supervisor",
  procurement_manager: "Procurement Manager",
  client: "Client",
};

const NAV_ITEMS = [
  { to: "/", label: "Command Center", icon: LayoutGrid },
  { to: "/inventory", label: "Inventory", icon: Boxes, phase: 2 },
  { to: "/finance", label: "Finance", icon: Receipt, phase: 2 },
  { to: "/quality", label: "Quality & Safety", icon: ShieldCheck, phase: 2 },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const location = useLocation();

  return (
    <div className="flex min-h-screen bg-ink bg-blueprint-grid bg-grid">
      {/* Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-ink-border bg-ink-surface/60 backdrop-blur">
        <div className="flex items-center gap-2 border-b border-ink-border px-5 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-blueprint-400/10 text-blueprint-400">
            <Building2 size={18} strokeWidth={2} />
          </div>
          <div>
            <p className="text-sm font-semibold leading-tight text-paper">
              ICE
            </p>
            <p className="text-[10px] leading-tight text-paper-muted">
              Construction Engine
            </p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-4">
          {NAV_ITEMS.map((item) => {
            const isActive = location.pathname === item.to;
            const Icon = item.icon;
            const isFuturePhase = "phase" in item;
            return (
              <Link
                key={item.to}
                to={isFuturePhase ? "#" : item.to}
                aria-disabled={isFuturePhase}
                className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-blueprint-400/10 text-blueprint-400"
                    : isFuturePhase
                    ? "cursor-not-allowed text-paper-faint"
                    : "text-paper-muted hover:bg-ink-raised hover:text-paper"
                }`}
              >
                <Icon size={16} strokeWidth={2} />
                {item.label}
                {isFuturePhase && (
                  <span className="ml-auto rounded bg-ink px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-paper-faint">
                    Phase {item.phase}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-ink-border px-3 py-3">
          <div className="mb-2 px-2">
            <p className="truncate text-xs font-medium text-paper">
              {user?.full_name}
            </p>
            <p className="truncate text-[11px] text-paper-muted">
              {user ? ROLE_LABEL[user.role] : ""}
            </p>
          </div>
          <button
            onClick={logout}
            className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm text-paper-muted transition-colors hover:bg-ink-raised hover:text-status-red"
          >
            <LogOut size={16} strokeWidth={2} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1">
        <header className="flex items-center justify-between border-b border-ink-border bg-ink-surface/60 px-6 py-3 backdrop-blur">
          <div>
            <p className="text-[11px] uppercase tracking-widest text-paper-faint">
              {new Date().toLocaleDateString("en-IN", {
                weekday: "long",
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <NotificationsBell />
            <span className="rounded border border-ink-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-paper-muted">
              {import.meta.env.MODE}
            </span>
          </div>
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  );
}
