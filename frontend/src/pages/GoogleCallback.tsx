import { useEffect, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { AlertCircle, Loader2, Building2 } from "lucide-react";
import { useAuth } from "../lib/auth-context";
import { GOOGLE_STATE_KEY, GOOGLE_VERIFIER_KEY } from "../lib/api";
import type { ApiErrorShape } from "../types";
import type { AxiosError } from "axios";

export function GoogleCallback() {
  const { googleLogin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    const state = params.get("state");

    // The `state` returned by Google must match the one this tab stashed when
    // it started the flow — CSRF protection on top of the server-side HMAC.
    const storedState = sessionStorage.getItem(GOOGLE_STATE_KEY);
    const verifier = sessionStorage.getItem(GOOGLE_VERIFIER_KEY);
    sessionStorage.removeItem(GOOGLE_STATE_KEY);
    sessionStorage.removeItem(GOOGLE_VERIFIER_KEY);

    if (!code || !state || !storedState || !verifier || state !== storedState) {
      setError("This sign-in request was invalid or expired. Please try again.");
      setIsRunning(false);
      return;
    }

    googleLogin(code, state, verifier)
      .then(() => navigate("/", { replace: true }))
      .catch((err: unknown) => {
        const axiosErr = err as AxiosError<ApiErrorShape>;
        const detail = axiosErr.response?.data?.detail;
        setError(
          detail ??
            "Could not sign in with Google. Please try again or use your email and password."
        );
        setIsRunning(false);
      });
    // Run exactly once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink bg-blueprint-grid bg-grid p-6">
      <div className="w-full max-w-md rounded-md border border-ink-border bg-ink-surface p-6 shadow-panel">
        <div className="mb-4 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-blueprint-400/10 text-blueprint-400">
            <Building2 size={18} />
          </div>
          <span className="text-sm font-semibold text-paper">
            Intelligent Construction Engine
          </span>
        </div>

        {isRunning ? (
          <div className="flex items-center gap-2 text-sm text-paper-muted">
            <Loader2 size={18} className="animate-spin text-blueprint-400" />
            Completing your Google sign-in…
          </div>
        ) : (
          <div className="flex items-start gap-2 rounded-md border border-status-amber/30 bg-status-amber/10 px-3 py-2 text-sm text-status-amber">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">{error}</p>
              <p className="mt-0.5 text-status-amber/80">
                You can sign in with your email and password instead.
              </p>
            </div>
          </div>
        )}

        <Link
          to="/login"
          className="mt-5 inline-block rounded border border-ink-border px-3 py-1.5 text-xs text-paper-muted hover:bg-ink-raised hover:text-paper"
        >
          Back to sign in
        </Link>
      </div>
    </div>
  );
}