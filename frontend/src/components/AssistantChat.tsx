import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Check,
  Loader2,
  Send,
  Sparkles,
  Square,
} from "lucide-react";
import { streamChat } from "../lib/assistant";
import type {
  AssistantCapabilities,
  AssistantRunDetails,
  ChatMessage,
  ToolActivity,
} from "../types/assistant";

interface AssistantChatProps {
  capabilities: AssistantCapabilities;
}

function exampleQuestions(capabilities: AssistantCapabilities): string[] {
  const labels = new Set(capabilities.tools.map((t) => t.label));
  const questions: string[] = [];
  if (labels.has("Projects")) questions.push("Show my projects.");
  if (labels.has("Project health")) questions.push("Which projects need attention?");
  if (labels.has("Project budget")) questions.push("What is the budget situation for a project?");
  if (labels.has("Project inventory")) questions.push("Show inventory for a project.");
  if (labels.has("Purchase orders")) questions.push("What purchase orders are open for a project?");
  if (labels.has("Notifications")) questions.push("What notifications need my attention?");
  return questions.slice(0, 4);
}

export function AssistantChat({ capabilities }: AssistantChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [toolActivities, setToolActivities] = useState<ToolActivity[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<AssistantRunDetails | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const controller = abortRef.current;
    return () => controller?.abort();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolActivities, streaming]);

  function appendAssistantText(delta: string) {
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last && last.role === "assistant") {
        copy[copy.length - 1] = { ...last, text: last.text + delta };
      } else {
        copy.push({ role: "assistant", text: delta });
      }
      return copy;
    });
  }

  function addToolActivity(label: unknown, status: ToolActivity["status"]) {
    if (typeof label !== "string" || !label) return;
    setToolActivities((prev) => [...prev, { label, status }]);
  }

  function updateToolActivity(label: unknown, status: ToolActivity["status"]) {
    if (typeof label !== "string" || !label) return;
    setToolActivities((prev) =>
      prev.map((a) => (a.label === label ? { ...a, status } : a)),
    );
  }

  function stop() {
    abortRef.current?.abort();
  }

  async function send() {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setError(null);
    setRunDetails(null);
    setToolActivities([]);
    setMessages((prev) => [...prev, { role: "user", text }]);
    setMessages((prev) => [...prev, { role: "assistant", text: "" }]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    let completed = false;
    try {
      for await (const event of streamChat(text, controller.signal)) {
        switch (event.event) {
          case "assistant_token": {
            const delta = typeof event.data.text === "string" ? event.data.text : "";
            if (delta) appendAssistantText(delta);
            break;
          }
          case "tool_started":
            addToolActivity(event.data.tool, "active");
            break;
          case "tool_finished":
            updateToolActivity(event.data.tool, event.data.ok === false ? "error" : "done");
            break;
          case "assistant_complete": {
            const usage =
              typeof event.data.usage === "object" && event.data.usage !== null
                ? (event.data.usage as AssistantRunDetails)
                : {};
            setRunDetails({
              ...usage,
              took_ms: typeof event.data.took_ms === "number" ? event.data.took_ms : undefined,
            });
            completed = true;
            break;
          }
          case "error":
            setError(
              typeof event.data.message === "string"
                ? event.data.message
                : "The assistant could not complete this request.",
            );
            completed = true;
            break;
          default:
            break; // unknown events are ignored safely
        }
      }
      if (!completed && !controller.signal.aborted) {
        setError("The assistant stopped unexpectedly. Please try again.");
      }
    } catch (err) {
      if (controller.signal.aborted) {
        // Graceful stop: partial text remains, no scary abort error.
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("The assistant could not be reached.");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  const hasToolLabels = capabilities.tools.length > 0;
  const examples = exampleQuestions(capabilities);
  const empty = messages.length === 0;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-ink-border bg-ink-surface shadow-panel">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-ink-border px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-blueprint-400/10 text-blueprint-400">
            <Bot size={16} strokeWidth={2} />
          </div>
          <div>
            <p className="text-sm font-semibold leading-tight text-paper">ICE Copilot</p>
            <p className="text-[10px] leading-tight text-paper-muted">
              Ask about your projects
            </p>
          </div>
        </div>
        <span className="flex items-center gap-1 rounded border border-ink-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-paper-muted">
          <Check size={11} strokeWidth={2} className="text-status-green" />
          Read-only
        </span>
      </div>

      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {empty && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Sparkles size={26} strokeWidth={1.5} className="mb-3 text-blueprint-400" />
            <p className="mb-1 text-sm font-medium text-paper">How can I help?</p>
            <p className="mb-4 max-w-xs text-xs text-paper-muted">
              I can look up project status, health, budget, inventory, purchase
              orders and notifications using the tools you are allowed to use.
            </p>
            {hasToolLabels && examples.length > 0 && (
              <div className="flex max-w-md flex-wrap justify-center gap-2">
                {examples.map((example) => (
                  <button
                    key={example}
                    type="button"
                    disabled={streaming}
                    onClick={() => setInput(example)}
                    className="rounded-md border border-ink-border bg-ink px-3 py-1.5 text-xs text-paper-muted transition-colors hover:border-blueprint-400/40 hover:text-paper disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {example}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {messages.map((message, index) => (
          <div key={index} className="flex">
            {message.role === "assistant" && (
              <div className="mr-2 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded bg-blueprint-400/10 text-blueprint-400">
                <Bot size={13} strokeWidth={2} />
              </div>
            )}
            <div
              className={
                message.role === "user"
                  ? "ml-auto max-w-[85%] whitespace-pre-wrap rounded-lg bg-blueprint-400/15 px-3 py-2 text-sm text-paper"
                  : "max-w-[85%] whitespace-pre-wrap rounded-lg bg-ink px-3 py-2 text-sm text-paper"
              }
            >
              {message.text}
              {message.role === "assistant" && streaming && index === messages.length - 1 && (
                <span className="ml-0.5 inline-block h-3.5 w-1 animate-pulse bg-blueprint-400 align-text-bottom" />
              )}
            </div>
          </div>
        ))}

        {toolActivities.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {toolActivities.map((activity) => (
              <span
                key={activity.label}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] ${
                  activity.status === "active"
                    ? "border-blueprint-400/40 text-blueprint-200"
                    : activity.status === "error"
                      ? "border-status-red/40 text-status-red"
                      : "border-ink-border text-paper-muted"
                }`}
              >
                {activity.status === "active" ? (
                  <Loader2 size={11} strokeWidth={2} className="animate-spin" />
                ) : activity.status === "error" ? (
                  <AlertTriangle size={11} strokeWidth={2} />
                ) : (
                  <Check size={11} strokeWidth={2} className="text-status-green" />
                )}
                Checking {activity.label}...
              </span>
            ))}
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-status-red/40 bg-status-red/10 px-3 py-2 text-sm text-status-red">
            <AlertTriangle size={15} strokeWidth={2} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Dev-only run details */}
        {import.meta.env.DEV && runDetails && (
          <details className="pt-1 text-[11px] text-paper-faint">
            <summary className="cursor-pointer select-none">Run details</summary>
            <pre className="mt-1 rounded border border-ink-border bg-ink p-2 font-mono text-[10px]">
              {JSON.stringify(runDetails, null, 2)}
            </pre>
          </details>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div className="border-t border-ink-border px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            rows={2}
            placeholder="Ask about your projects…"
            disabled={streaming}
            className="flex-1 resize-none rounded-md border border-ink-border bg-ink px-3 py-2 text-sm text-paper placeholder:text-paper-faint focus:border-blueprint-400/60 focus:outline-none disabled:cursor-not-allowed disabled:opacity-70"
          />
          {streaming ? (
            <button
              type="button"
              onClick={stop}
              className="flex h-9 items-center gap-1.5 rounded-md border border-status-red/50 bg-status-red/10 px-3 text-sm text-status-red transition-colors hover:bg-status-red/20"
            >
              <Square size={13} strokeWidth={2} fill="currentColor" />
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void send()}
              disabled={!input.trim()}
              className="flex h-9 items-center gap-1.5 rounded-md bg-blueprint-500 px-3 text-sm font-medium text-white transition-colors hover:bg-blueprint-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Send size={13} strokeWidth={2} />
              Send
            </button>
          )}
        </div>
        <p className="mt-2 text-[10px] text-paper-faint">
          Answers are read-only and grounded in your permitted project data.
        </p>
      </div>
    </div>
  );
}
