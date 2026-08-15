import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2, PowerOff } from "lucide-react";
import { AppShell } from "../components/AppShell";
import { AssistantChat } from "../components/AssistantChat";
import { getCapabilities } from "../lib/assistant";
import type { AssistantCapabilities } from "../types/assistant";

export function Assistant() {
  const {
    data: capabilities,
    isLoading,
    isError,
    refetch,
  } = useQuery<AssistantCapabilities>({
    queryKey: ["assistant-capabilities"],
    queryFn: getCapabilities,
    retry: 1,
    staleTime: 60_000,
  });

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-8rem)] flex-col">
        {isLoading && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-paper-muted">
            <Loader2 size={22} strokeWidth={2} className="animate-spin text-blueprint-400" />
            <p className="text-sm">Loading the ICE Copilot…</p>
          </div>
        )}

        {isError && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
            <AlertTriangle size={22} strokeWidth={2} className="text-status-red" />
            <p className="max-w-sm text-sm text-paper">
              The ICE Copilot could not be loaded.
            </p>
            <p className="max-w-sm text-xs text-paper-muted">
              This could mean the assistant is unavailable or your session has
              expired. Please sign in again if needed.
            </p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="rounded-md border border-ink-border px-3 py-1.5 text-sm text-paper transition-colors hover:border-blueprint-400/40"
            >
              Retry
            </button>
          </div>
        )}

        {!isLoading && !isError && capabilities && !capabilities.enabled && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
            <PowerOff size={22} strokeWidth={2} className="text-paper-faint" />
            <p className="text-sm text-paper">The ICE Copilot is not enabled.</p>
            <p className="max-w-sm text-xs text-paper-muted">
              The assistant is disabled for this environment. Please check the
              ICE Copilot configuration.
            </p>
          </div>
        )}

        {!isLoading && !isError && capabilities && capabilities.enabled && (
          <AssistantChat capabilities={capabilities} />
        )}
      </div>
    </AppShell>
  );
}
