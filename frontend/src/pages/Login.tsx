import { useState, type FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Building2, AlertCircle } from "lucide-react";
import { useAuth } from "../lib/auth-context";
import type { ApiErrorShape } from "../types";
import type { AxiosError } from "axios";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const from = (location.state as { from?: string })?.from ?? "/";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      const axiosErr = err as AxiosError<ApiErrorShape>;
      setError(
        axiosErr.response?.data?.detail ??
          "Couldn't sign in. Check your connection and try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-ink bg-blueprint-grid bg-grid">
      {/* Left panel — brand identity */}
      <div className="hidden w-1/2 flex-col justify-between border-r border-ink-border p-10 lg:flex">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-blueprint-400/10 text-blueprint-400">
            <Building2 size={18} strokeWidth={2} />
          </div>
          <span className="text-sm font-semibold text-paper">
            Intelligent Construction Engine
          </span>
        </div>

        <div>
          <p className="font-mono text-xs tracking-widest text-blueprint-400">
            SHEET P-00 / COMMAND CENTER
          </p>
          <h1 className="mt-3 max-w-md text-3xl font-semibold leading-tight text-paper">
            15 sites. One command center.
          </h1>
          <p className="mt-3 max-w-sm text-sm text-paper-muted">
            Track timeline, budget, and safety health across every active
            site — scheduling, inventory, and finance in a single view.
          </p>
        </div>

        <p className="font-mono text-[11px] text-paper-faint">
          v0.1.0 — Phase 1
        </p>
      </div>

      {/* Right panel — login form */}
      <div className="flex flex-1 items-center justify-center p-6">
        <form
          onSubmit={handleSubmit}
          className="w-full max-w-sm rounded-md border border-ink-border bg-ink-surface p-6 shadow-panel"
        >
          <div className="mb-6 lg:hidden">
            <div className="mb-2 flex items-center gap-2">
              <Building2 size={18} className="text-blueprint-400" />
              <span className="text-sm font-semibold text-paper">ICE</span>
            </div>
          </div>

          <h2 className="text-lg font-semibold text-paper">Sign in</h2>
          <p className="mb-6 mt-1 text-sm text-paper-muted">
            Enter your credentials to access your dashboard.
          </p>

          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-md border border-status-red/30 bg-status-red/10 px-3 py-2 text-sm text-status-red">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <label className="mb-3 block">
            <span className="mb-1.5 block text-xs font-medium text-paper-muted">
              Email
            </span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-ink-border bg-ink px-3 py-2 text-sm text-paper placeholder:text-paper-faint focus:border-blueprint-400"
              placeholder="you@company.com"
            />
          </label>

          <label className="mb-5 block">
            <span className="mb-1.5 block text-xs font-medium text-paper-muted">
              Password
            </span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-ink-border bg-ink px-3 py-2 text-sm text-paper placeholder:text-paper-faint focus:border-blueprint-400"
              placeholder="••••••••"
            />
          </label>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-blueprint-400 px-3 py-2 text-sm font-medium text-ink transition-colors hover:bg-blueprint-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
