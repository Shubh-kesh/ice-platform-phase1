import { useState, type FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Building2, AlertCircle } from "lucide-react";
import { useAuth } from "../lib/auth-context";
import { googleAuthorize, GOOGLE_VERIFIER_KEY, GOOGLE_STATE_KEY } from "../lib/api";
import type { ApiErrorShape } from "../types";
import type { AxiosError } from "axios";

function GoogleG({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84Z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15A11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 7.3 9.14 5.38 12 5.38Z"
      />
    </svg>
  );
}

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [googleError, setGoogleError] = useState<string | null>(null);
  const [googlePending, setGooglePending] = useState(false);

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

  // On click, the backend hand the SPA a fresh consent URL + flow state, which
  // is stashed in sessionStorage (the callback route verifies `state`) before
  // the whole tab navigates to Google.
  async function handleGoogle() {
    setGoogleError(null);
    setGooglePending(true);
    try {
      const flow = await googleAuthorize();
      sessionStorage.setItem(GOOGLE_STATE_KEY, flow.state);
      sessionStorage.setItem(GOOGLE_VERIFIER_KEY, flow.code_verifier);
      window.location.href = flow.authorize_url;
    } catch {
      setGoogleError(
        "Google sign-in isn't configured for this workspace yet — use your email and password."
      );
      setGooglePending(false);
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

          <button
            type="button"
            onClick={handleGoogle}
            disabled={googlePending}
            className="mb-4 flex w-full items-center justify-center gap-2.5 rounded-md border border-ink-border bg-ink px-3 py-2 text-sm text-paper transition-colors hover:bg-ink-raised disabled:cursor-not-allowed disabled:opacity-60"
          >
            <GoogleG size={16} />
            {googlePending ? "Contacting Google…" : "Continue with Google"}
          </button>

          {googleError && (
            <div className="mb-4 flex items-start gap-2 rounded-md border border-status-amber/30 bg-status-amber/10 px-3 py-2 text-sm text-status-amber">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <span>{googleError}</span>
            </div>
          )}

          <div className="mb-4 flex items-center gap-3 text-[10px] uppercase tracking-widest text-paper-faint">
            <span className="h-px flex-1 bg-ink-border" />
            or sign in with email
            <span className="h-px flex-1 bg-ink-border" />
          </div>

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
